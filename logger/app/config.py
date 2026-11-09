"""Configuration: the columns of the raw and work databases come from the entities (fields.py); per-user YAML files: <user>_layout.yml, <user>_breakdown.yml."""
import copy
import os
from pathlib import Path

import yaml
from .db import user_file, safe_identifier
from .cssafe import sanitize_layout

SYSTEM_COLUMNS = [
    {"column": "id", "display_name": "ID", "position": 0, "system": True, "data_type": "integer", "nullable": False, "visible": False, "editable": False, "primary_key": True},
    {"column": "created_at", "display_name": "Created at", "position": 0, "system": True, "data_type": "datetime", "nullable": False, "visible": False, "editable": False},
    {"column": "updated_at", "display_name": "Updated at", "position": 0, "system": True, "data_type": "datetime", "nullable": False, "visible": False, "editable": False},
    {"column": "import_source", "display_name": "Import source", "position": 0, "system": True, "data_type": "text", "nullable": True, "visible": False, "editable": False},
]
LOGBOOK_SYSTEM_COLUMNS = [dict(c) for c in SYSTEM_COLUMNS]

DEFAULT_LOGBOOK_LAYOUT = yaml.safe_load((Path(__file__).resolve().parent.parent / "defaults" / "logbook_layout.yml").read_text(encoding="utf-8"))


DEFAULT_BREAKDOWN = yaml.safe_load((Path(__file__).resolve().parent.parent / "defaults" / "breakdown.yml").read_text(encoding="utf-8"))


def _atomic_write(path, text):
    """Écriture atomique : fichier temporaire voisin, fsync, puis remplacement (jamais de YAML tronqué)."""
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as handle:
            handle.write(text); handle.flush(); os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _cfg_username(username):
    from .db import current_username
    return username or current_username()


def logbook_layout_path(username=None):
    u = _cfg_username(username); return user_file(f"{u}_layout.yml", username)
def breakdown_path(username=None):
    u = _cfg_username(username); return user_file(f"{u}_breakdown.yml", username)


def technical_name(display_name):
    value = str(display_name or "").strip().lower()
    value = __import__("re").sub(r"[^a-z0-9]+", "_", value)
    value = __import__("re").sub(r"_+", "_", value).strip("_")
    if not value:
        raise ValueError("The display_name must produce a valid technical column name.")
    if value[0].isdigit():
        value = "_" + value
    safe_identifier(value)
    if value in {"id", "created_at", "updated_at", "import_source", "import_profile"}:
        raise ValueError(f"Reserved column name: {value}")
    return value


def is_system(column):
    """Technical column (id, created_at, ...). Older YAML files marked them with group: system."""
    return bool(column.get("system")) or column.get("group") == "system"


def _norm_system(raw, base):
    by = {x.get("column"): dict(x) for x in (raw or []) if x.get("column")}
    out = []
    for b in base:
        x = dict(b); x.update(by.get(b["column"], {})); x.pop("group", None); x.update(system=True, position=0, visible=False, editable=False)
        out.append(x)
    return out


def _load_yaml(path, fallback):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        _atomic_write(path, yaml.safe_dump(fallback, allow_unicode=True, sort_keys=False))
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def ensure_configs(username=None):
    if not logbook_layout_path(username).exists():
        try:
            from flask import current_app
            bundled = __import__("pathlib").Path(current_app.root_path).parent / "defaults" / "logbook_layout.yml"
        except Exception:
            bundled = None
        if bundled and bundled.exists():
            _atomic_write(logbook_layout_path(username), bundled.read_text(encoding="utf-8"))
        else:
            _atomic_write(logbook_layout_path(username), yaml.safe_dump(DEFAULT_LOGBOOK_LAYOUT, allow_unicode=True, sort_keys=False))


    if not breakdown_path(username).exists():
        _atomic_write(breakdown_path(username), (Path(__file__).resolve().parent.parent / "defaults" / "breakdown.yml").read_text(encoding="utf-8"))


def _from_fields(db, systems):
    """The columns of a database: the technical columns, then the fields chosen among the entities (Data > Raw / Work DB settings)."""
    from . import fields
    normal = [{"column": c["column"], "display_name": c["display_name"], "position": i, "data_type": c["data_type"],
               "nullable": c["nullable"], "visible": c["visible"], "editable": c["editable"]} for i, c in enumerate(fields.columns(db), 1)]
    return {"database": {"columns": _norm_system([], systems) + normal}}


def _save_fields(db, data):
    from . import fields
    cols = [c for c in data.get("database", data).get("columns", []) if not is_system(c)]
    return fields.save(db, [{"field": c["column"], "visible": c.get("visible", True), "editable": c.get("editable", True),
                             "nullable": c.get("nullable", True)} for c in cols])


def load_config(username=None):
    return _from_fields("raw", SYSTEM_COLUMNS)


def save_config(data, username=None):
    _save_fields("raw", data)


def load_logbook_db_config(username=None):
    return _from_fields("work", LOGBOOK_SYSTEM_COLUMNS)


def load_logbook_layout(username=None):
    ensure_configs(username)
    raw = _load_yaml(logbook_layout_path(username), DEFAULT_LOGBOOK_LAYOUT)
    cfg = dict(DEFAULT_LOGBOOK_LAYOUT); cfg.update(raw or {})
    cfg["styles"] = {**DEFAULT_LOGBOOK_LAYOUT["styles"], **(raw or {}).get("styles", {})}
    cfg["columns"] = (raw or {}).get("columns", DEFAULT_LOGBOOK_LAYOUT["columns"])
    return sanitize_layout(copy.deepcopy(cfg))      # valeurs CSS/numériques invalides -> valeurs par défaut


def configurable_columns(config): return [c for c in config["database"]["columns"] if not is_system(c)]


# ---------------- grid columns (no appearance setting: Tabulator sizes the columns to their content) ----------------

def _view(columns):
    return [{"column": c["column"], "data_type": c["data_type"], "label": str(c["display_name"])} for c in columns]


def load_data_view(config, username=None):
    return _view(configurable_columns(config))


def load_logbook_view(username=None):
    """Colonnes affichées dans Données converties : celles de la work db, telles quelles."""
    columns = []
    for c in load_logbook_db_config(username)["database"]["columns"]:
        if is_system(c): continue
        columns.append(c)
    return _view(columns)
def logbook_columns(config, username=None): return [c for c in load_logbook_db_config(username)["database"]["columns"] if not is_system(c)]
def load_breakdown(username=None):
    """Mise en page du rapport Flight time breakdown (breakdown.yml de l'utilisateur) ; valeurs invalides -> valeurs par défaut."""
    from .cssafe import sanitize_breakdown
    ensure_configs(username)
    raw = _load_yaml(breakdown_path(username), DEFAULT_BREAKDOWN) or {}
    cfg = copy.deepcopy(DEFAULT_BREAKDOWN)
    for k, v in raw.items():
        if k not in ("styles", "columns", "top_widths_u", "rows"):
            cfg[k] = v
    for k in ("styles", "top_widths_u"):
        cfg[k] = {**DEFAULT_BREAKDOWN[k], **(raw.get(k) or {})} if isinstance(raw.get(k), dict) else cfg[k]
    given = {c.get("key"): c for c in (raw.get("columns") or []) if isinstance(c, dict)}
    cfg["columns"] = [{"key": c["key"], "width": given.get(c["key"], c).get("width", c["width"])} for c in DEFAULT_BREAKDOWN["columns"]]
    if isinstance(raw.get("rows"), list):
        cfg["rows"] = [str(x or "").strip() for x in raw["rows"]][:60]
    return sanitize_breakdown(cfg)


def save_breakdown(data, username=None):
    _atomic_write(breakdown_path(username), yaml.safe_dump(data, allow_unicode=True, sort_keys=False))
