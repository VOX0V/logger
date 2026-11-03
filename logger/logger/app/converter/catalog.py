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
    "airline_prefix": "AC",
    "aircraft_types": {"CRJ9": "CRJ", "CRJ7": "CRJ", "CRJ2": "CRJ"},
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
    _migrate_shared()


# ---------------- one-time migrations ----------------
# Each step adds the new default rules to an existing catalog and switches the users over,
# without overwriting or deleting anything. Markers keep a step from running twice.

MIGRATIONS = [
    {"id": "1.7.1", "disable": ["copy_aircraft_type", "copy_registration", "copy_departure", "copy_arrival"],
     "front": [], "append": ["aircraft_type_normalize", "registration_format", "departure_icao", "arrival_icao",
                             "crew_from_list", "remarks_flight_number", "ifr_block_time", "daynight_multi_copi",
                             "daynight_xc_pic"]},
    {"id": "1.7.2", "disable": [], "front": ["skip_not_flying"], "append": []},   # filter: first in the catalog
    {"id": "1.7.3", "disable": [], "front": ["skip_zero_block"], "append": []},
    {"id": "1.8.0", "disable": [], "front": [], "append": [], "labels": True},   # English labels of the bundled rules
]


def _migrate_shared():
    marker = converter_dir() / "migrations.yml"
    done = (yaml.safe_load(marker.read_text(encoding="utf-8")) or []) if marker.exists() else []
    todo = [m for m in MIGRATIONS if m["id"] not in done]
    if not todo:
        return
    rules = (yaml.safe_load(rules_path().read_text(encoding="utf-8")) or {}).get("rules", [])
    bundled = (yaml.safe_load((defaults_dir() / "converter_rules.yml").read_text(encoding="utf-8")) or {}).get("rules", [])
    bundled = {r["id"]: r for r in bundled if r.get("id")}
    for m in todo:
        present = {r.get("id") for r in rules}
        rules[:0] = [bundled[i] for i in m["front"] if i in bundled and i not in present]
        rules += [bundled[i] for i in m["append"] if i in bundled and i not in present]
        for r in rules:
            if r.get("id") in m["disable"]:
                r["default"] = False          # replaced by the new rules, kept in the catalog
        if m.get("labels"):
            legacy = yaml.safe_load((defaults_dir() / "converter_rules_legacy_fr.yml").read_text(encoding="utf-8")) or {}
            for r in rules:
                was, now = legacy.get(r.get("id")), bundled.get(r.get("id"))
                if was and now:
                    for key in ("name",):
                        if r.get(key) == was[key]:
                            r[key] = now[key]
    save_rules(rules)
    marker.write_text(yaml.safe_dump(done + [m["id"] for m in todo]), encoding="utf-8")


def _migrate_user(username=None):
    data = _selection_data(username)
    done = data.get("migrations") or []
    todo = [m for m in MIGRATIONS if m["id"] not in done]
    if not todo:
        return
    known = {r["id"] for r in load_rules()}
    enabled = list(data.get("enabled") or [])
    for m in todo:
        enabled = [i for i in enabled if i not in m["disable"]]
        enabled += [i for i in m["front"] + m["append"] if i in known and i not in enabled]
    data["enabled"], data["migrations"] = enabled, done + [m["id"] for m in todo]
    _write_selection(data, username)


# ---------------- rules ----------------

def normalize_rule(raw):
    rule = dict(raw or {})
    return {
        "id": str(rule.get("id", "")).strip(),
        "name": str(rule.get("name", "")).strip(),
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
        raise ValueError("Unknown transform type.")
    name = form.get("name", "").strip()
    if not name:
        raise ValueError("The rule name is required.")
    params = {}
    for key, _label, choices in spec["params"]:
        value = form.get(f"param_{key}", choices[0][0])
        if value not in {c[0] for c in choices}:
            raise ValueError("Invalid parameter.")
        params[key] = value
    inputs, outputs = {}, {}
    for slot, label, required in spec["inputs"]:
        value = form.get(f"in_{slot}", "").strip()
        if slot == "registration":
            required = params.get("engine", "any") != "any"
        if not value:
            if required:
                raise ValueError(f"“{label} ” is required.")
            continue
        inputs[slot] = safe_identifier(value)
    for slot, label, _required in spec["outputs"]:
        value = form.get(f"out_{slot}", "").strip()
        if not value:
            raise ValueError(f"“{label} ” is required.")
        outputs[slot] = safe_identifier(value)
    return {"id": rule_id, "name": name, "transform": transform,
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
            "tc_rounding": data.get("tc_rounding") or DEFAULT_SETTINGS["tc_rounding"],
            "airline_prefix": str(data.get("airline_prefix", DEFAULT_SETTINGS["airline_prefix"])).strip(),
            "aircraft_types": data.get("aircraft_types") or DEFAULT_SETTINGS["aircraft_types"]}


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
            raise ValueError(f"Invalid rounding line: “ {line} ” (expected format: 0-2=0.0 or 57-60=0.0+1h)")
        lo, hi = int(m.group(1)), int(m.group(2))
        if lo > hi or hi > 60:
            raise ValueError(f"Invalid minute range: “ {line}”")
        rule = {"min": lo, "max": hi, "decimal": float(m.group(3))}
        if m.group(4):
            rule["add_hour"] = True
        rules.append(rule)
    if not rules:
        raise ValueError("The rounding table cannot be empty.")
    covered = {m for r in rules for m in range(r["min"], r["max"] + 1)}
    if covered != set(range(0, 61)):
        raise ValueError("The rounding table must cover all minutes from 0 to 60.")
    return rules


# ---------------- per-user selection ----------------

def selection_path(username=None):
    username = username or current_username()
    return user_file(f"{username}_converter.yml", username)


def ensure_user_selection(username):
    path = selection_path(username)
    if not path.exists():
        enabled = [r["id"] for r in load_rules() if r["default"]]
        path.write_text(yaml.safe_dump({"enabled": enabled, "migrations": [m["id"] for m in MIGRATIONS]}, allow_unicode=True, sort_keys=False), encoding="utf-8")


def load_selection(username=None):
    ensure_user_selection(username or current_username())
    _migrate_user(username)
    data = yaml.safe_load(selection_path(username).read_text(encoding="utf-8")) or {}
    known = {r["id"] for r in load_rules()}
    return [i for i in (data.get("enabled") or []) if i in known]


def _selection_data(username=None):
    path = selection_path(username)
    return (yaml.safe_load(path.read_text(encoding="utf-8")) or {}) if path.exists() else {}


def _write_selection(data, username=None):
    selection_path(username).write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def save_selection(ids, username=None):
    known = {r["id"] for r in load_rules()}
    data = _selection_data(username)
    data["enabled"] = [i for i in ids if i in known]
    _write_selection(data, username)


def pilot_name(username=None):
    """The user's family name, used to find them in the crew list (stored with their rule selection)."""
    ensure_user_selection(username or current_username())
    return str(_selection_data(username).get("pilot_name") or "").strip()


def load_profile(username=None):
    """Identity used by the converter (family name) and by the PDF reports (first name, employee number)."""
    ensure_user_selection(username or current_username())
    data = _selection_data(username)
    return {k: str(data.get(k) or "").strip()
            for k in ("pilot_name", "first_name", "employee_number", "license_number", "phone")}


def save_profile(pilot_name, first_name, employee_number, username=None, license_number=None, phone=None):
    """license_number / phone : None = laisser inchangé (utilisé par la page “Flight time breakdown”)."""
    ensure_user_selection(username or current_username())
    data = _selection_data(username)
    data["pilot_name"], data["first_name"] = str(pilot_name).strip()[:60], str(first_name).strip()[:60]
    data["employee_number"] = str(employee_number).strip()[:20]
    if license_number is not None:
        data["license_number"] = str(license_number).strip()[:30]
    if phone is not None:
        data["phone"] = str(phone).strip()[:30]
    _write_selection(data, username)


def load_qualifications(username=None):
    """Suivi des qualifications du pilote : liste de {name, expiry (AAAA-MM-JJ)}, triée par date d'expiration."""
    ensure_user_selection(username or current_username())
    items = [q for q in (_selection_data(username).get("qualifications") or [])
             if isinstance(q, dict) and q.get("name") and q.get("expiry")]
    return sorted(({"name": str(q["name"]), "expiry": str(q["expiry"])} for q in items), key=lambda q: q["expiry"])


def save_qualifications(items, username=None):
    ensure_user_selection(username or current_username())
    data = _selection_data(username)
    data["qualifications"] = [{"name": str(q["name"]).strip()[:60], "expiry": str(q["expiry"])[:10]} for q in items][:50]
    _write_selection(data, username)


def save_pilot_name(name, username=None):
    ensure_user_selection(username or current_username())
    data = _selection_data(username)
    data["pilot_name"] = str(name).strip()[:60]
    _write_selection(data, username)


def active_rules(username=None):
    """The user's ticked rules, in catalog order."""
    enabled = set(load_selection(username))
    return [r for r in load_rules() if r["id"] in enabled]
