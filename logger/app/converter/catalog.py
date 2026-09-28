"""Converter rule catalog and settings (shared, in appdata/converter) and the
per-user selection of rules (users/<username>/<username>_converter.yml)."""
import re
import shutil
import unicodedata
from pathlib import Path

import yaml
from flask import current_app

from ..db import converter_dir, user_file, current_username, safe_identifier
from .transforms import TRANSFORMS

DEFAULT_SETTINGS = {
    "night": {"after_sunset_minutes": 30, "before_sunrise_minutes": 30},
    "tc_rounding": {"comment": "", "rules": []},
}


def defaults_dir():
    return Path(current_app.root_path).parent / "defaults"


def rules_path(): return converter_dir() / "rules.yml"
def settings_path(): return converter_dir() / "settings.yml"


def ensure_defaults():
    """Copy the bundled defaults into appdata/converter the first time only,
    so that an image update never overwrites the administrators' changes."""
    for name, source in (("rules.yml", "converter_rules.yml"), ("settings.yml", "converter_settings.yml")):
        target = converter_dir() / name
        if not target.exists():
            shutil.copyfile(defaults_dir() / source, target)


# ---------------- rules ----------------

def normalize_rule(raw):
    rule = dict(raw or {})
    return {
        "id": str(rule.get("id", "")).strip(),
        "name": str(rule.get("name", "")).strip(),
        "group": str(rule.get("group", "") or "Autres").strip(),
        "transform": str(rule.get("transform", "")).strip(),
        "inputs": {str(k): str(v).strip() for k, v in (rule.get("inputs") or {}).items() if str(v or "").strip()},
        "outputs": {str(k): str(v).strip() for k, v in (rule.get("outputs") or {}).items() if str(v or "").strip()},
        "params": {str(k): str(v) for k, v in (rule.get("params") or {}).items()},
        "default": bool(rule.get("default", False)),
    }


def load_rules():
    ensure_defaults()
    data = yaml.safe_load(rules_path().read_text(encoding="utf-8")) or {}
    return [normalize_rule(r) for r in data.get("rules", []) if r.get("id")]


def save_rules(rules):
    rules_path().write_text(yaml.safe_dump({"rules": rules}, allow_unicode=True, sort_keys=False), encoding="utf-8")


def get_rule(rule_id):
    return next((r for r in load_rules() if r["id"] == rule_id), None)


def rule_id_from_name(name, existing):
    ascii_name = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode("ascii")
    base = re.sub(r"[^a-z0-9]+", "_", ascii_name.lower()).strip("_")[:40] or "regle"
    candidate, n = base, 2
    while candidate in existing:
        candidate = f"{base}_{n}"; n += 1
    return candidate


def build_rule(form, transform, rule_id):
    """Build and validate a rule from the admin form. Raises ValueError."""
    spec = TRANSFORMS.get(transform)
    if not spec:
        raise ValueError("Type de transformation inconnu.")
    name = form.get("name", "").strip()
    if not name:
        raise ValueError("Le nom de la règle est obligatoire.")
    params = {}
    for key, _label, choices in spec["params"]:
        value = form.get(f"param_{key}", choices[0][0])
        if value not in {c[0] for c in choices}:
            raise ValueError("Paramètre invalide.")
        params[key] = value
    inputs, outputs = {}, {}
    for slot, label, required in spec["inputs"]:
        value = form.get(f"in_{slot}", "").strip()
        if slot == "registration":
            required = params.get("engine", "any") != "any"
        if not value:
            if required:
                raise ValueError(f"« {label} » est obligatoire.")
            continue
        inputs[slot] = safe_identifier(value)
    for slot, label, _required in spec["outputs"]:
        value = form.get(f"out_{slot}", "").strip()
        if not value:
            raise ValueError(f"« {label} » est obligatoire.")
        outputs[slot] = safe_identifier(value)
    return {"id": rule_id, "name": name, "group": form.get("group", "").strip() or "Autres", "transform": transform,
            "inputs": inputs, "outputs": outputs, "params": params, "default": form.get("default") == "1"}


def rule_missing_columns(rule, a_columns, b_columns):
    """Columns used by the rule that do not exist in this user's structures."""
    missing = [f"A.{c}" for c in rule["inputs"].values() if c not in a_columns]
    missing += [f"B.{c}" for c in rule["outputs"].values() if c not in b_columns]
    return missing


# ---------------- settings ----------------

def load_settings():
    ensure_defaults()
    data = yaml.safe_load(settings_path().read_text(encoding="utf-8")) or {}
    night = {**DEFAULT_SETTINGS["night"], **(data.get("night") or {})}
    return {"night": {k: int(v) for k, v in night.items()},
            "tc_rounding": data.get("tc_rounding") or DEFAULT_SETTINGS["tc_rounding"]}


def save_settings(settings):
    settings_path().write_text(yaml.safe_dump(settings, allow_unicode=True, sort_keys=False), encoding="utf-8")


def rounding_to_text(rules):
    lines = []
    for r in rules:
        lines.append(f"{r['min']}-{r['max']}={r['decimal']}" + ("+1h" if r.get("add_hour") else ""))
    return "\n".join(lines)


def rounding_from_text(text):
    rules = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        m = re.fullmatch(r"(\d+)-(\d+)=(\d+(?:\.\d+)?)(\+1h)?", line)
        if not m:
            raise ValueError(f"Ligne d'arrondi invalide : « {line} » (format attendu : 0-2=0.0 ou 57-60=0.0+1h)")
        lo, hi = int(m.group(1)), int(m.group(2))
        if lo > hi or hi > 60:
            raise ValueError(f"Plage de minutes invalide : « {line} »")
        rule = {"min": lo, "max": hi, "decimal": float(m.group(3))}
        if m.group(4):
            rule["add_hour"] = True
        rules.append(rule)
    if not rules:
        raise ValueError("Le tableau d'arrondi ne peut pas être vide.")
    covered = {m for r in rules for m in range(r["min"], r["max"] + 1)}
    if covered != set(range(0, 61)):
        raise ValueError("Le tableau d'arrondi doit couvrir toutes les minutes de 0 à 60.")
    return rules


# ---------------- per-user selection ----------------

def selection_path(username=None):
    username = username or current_username()
    return user_file(f"{username}_converter.yml", username)


def ensure_user_selection(username):
    path = selection_path(username)
    if not path.exists():
        enabled = [r["id"] for r in load_rules() if r["default"]]
        path.write_text(yaml.safe_dump({"enabled": enabled}, allow_unicode=True, sort_keys=False), encoding="utf-8")


def load_selection(username=None):
    ensure_user_selection(username or current_username())
    data = yaml.safe_load(selection_path(username).read_text(encoding="utf-8")) or {}
    known = {r["id"] for r in load_rules()}
    return [i for i in (data.get("enabled") or []) if i in known]


def save_selection(ids, username=None):
    known = {r["id"] for r in load_rules()}
    enabled = [i for i in ids if i in known]
    selection_path(username).write_text(yaml.safe_dump({"enabled": enabled}, allow_unicode=True, sort_keys=False), encoding="utf-8")


def active_rules(username=None):
    """The user's ticked rules, in catalog order."""
    enabled = set(load_selection(username))
    return [r for r in load_rules() if r["id"] in enabled]
