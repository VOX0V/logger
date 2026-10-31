"""Per-user YAML configuration: <user>_data.yml, <user>_logbook.yml, <user>_layout.yml."""
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

DEFAULT_COLUMNS = [
 {"position": 1, "display_name": "year", "column": "year", "data_type": "integer", "nullable": True, "visible": True, "editable": True, "import_rules": ["year"]},
 {"position": 2, "display_name": "month", "column": "month", "data_type": "integer", "nullable": True, "visible": True, "editable": True, "import_rules": ["month"]},
 {"position": 3, "display_name": "day", "column": "day", "data_type": "integer", "nullable": True, "visible": True, "editable": True, "import_rules": ["day"]},
 {"position": 4, "display_name": "type", "column": "type", "data_type": "text", "nullable": True, "visible": True, "editable": True, "import_rules": ["type"]},
 {"position": 5, "display_name": "registration", "column": "registration", "data_type": "text", "nullable": True, "visible": True, "editable": True, "import_rules": ["immat", "reg", "registration"]},
 {"position": 6, "display_name": "pilot in command", "column": "pilot_in_command", "data_type": "text", "nullable": True, "visible": True, "editable": True, "import_rules": ["pic"]},
 {"position": 7, "display_name": "copilot", "column": "copilot", "data_type": "text", "nullable": True, "visible": True, "editable": True, "import_rules": ["copi"]},
 {"position": 8, "display_name": "departure", "column": "departure", "data_type": "text", "nullable": True, "visible": True, "editable": True, "import_rules": ["dep"]},
 {"position": 9, "display_name": "arrival", "column": "arrival", "data_type": "text", "nullable": True, "visible": True, "editable": True, "import_rules": ["arr"]},
 {"position": 10, "display_name": "remarks", "column": "remarks", "data_type": "text", "nullable": True, "visible": True, "editable": True, "import_rules": ["remarks"]},
]

DEFAULT_LOGBOOK_DB_COLUMNS = [
 {'column': 'date', 'display_name': 'date', 'position': 1, 'data_type': 'date', 'nullable': True, 'visible': True, 'editable': True},
 {'column': 'aircraft_type', 'display_name': 'aircraft type', 'position': 2, 'data_type': 'text', 'nullable': True, 'visible': True, 'editable': True},
 {'column': 'registration', 'display_name': 'registration', 'position': 3, 'data_type': 'text', 'nullable': True, 'visible': True, 'editable': True},
 {'column': 'pilot_in_command', 'display_name': 'pilot in command', 'position': 4, 'data_type': 'text', 'nullable': True, 'visible': True, 'editable': True},
 {'column': 'copilot', 'display_name': 'copilot', 'position': 5, 'data_type': 'text', 'nullable': True, 'visible': True, 'editable': True},
 {'column': 'departure', 'display_name': 'departure', 'position': 6, 'data_type': 'text', 'nullable': True, 'visible': True, 'editable': True},
 {'column': 'arrival', 'display_name': 'arrival', 'position': 7, 'data_type': 'text', 'nullable': True, 'visible': True, 'editable': True},
 {'column': 'remarks', 'display_name': 'remarks', 'position': 8, 'data_type': 'text', 'nullable': True, 'visible': True, 'editable': True},
 {'column': 'single_engine_dual_day', 'display_name': 'single engine dual day', 'position': 9, 'data_type': 'text', 'nullable': True, 'visible': True, 'editable': True},
 {'column': 'single_engine_pic_day', 'display_name': 'single engine pic day', 'position': 10, 'data_type': 'text', 'nullable': True, 'visible': True, 'editable': True},
 {'column': 'single_engine_dual_night', 'display_name': 'single engine dual night', 'position': 11, 'data_type': 'text', 'nullable': True, 'visible': True, 'editable': True},
 {'column': 'single_engine_pic_night', 'display_name': 'single engine pic night', 'position': 12, 'data_type': 'text', 'nullable': True, 'visible': True, 'editable': True},
 {'column': 'multi_engine_dual_day', 'display_name': 'multi engine dual day', 'position': 13, 'data_type': 'text', 'nullable': True, 'visible': True, 'editable': True},
 {'column': 'multi_engine_pic_day', 'display_name': 'multi engine pic day', 'position': 14, 'data_type': 'text', 'nullable': True, 'visible': True, 'editable': True},
 {'column': 'multi_engine_copi_day', 'display_name': 'multi engine copilot day', 'position': 15, 'data_type': 'text', 'nullable': True, 'visible': True, 'editable': True},
 {'column': 'multi_engine_dual_night', 'display_name': 'multi engine dual night', 'position': 16, 'data_type': 'text', 'nullable': True, 'visible': True, 'editable': True},
 {'column': 'multi_engine_pic_night', 'display_name': 'multi engine pic night', 'position': 17, 'data_type': 'text', 'nullable': True, 'visible': True, 'editable': True},
 {'column': 'multi_engine_copi_night', 'display_name': 'multi engine copilot night', 'position': 18, 'data_type': 'text', 'nullable': True, 'visible': True, 'editable': True},
 {'column': 'ifr', 'display_name': 'ifr', 'position': 19, 'data_type': 'text', 'nullable': True, 'visible': True, 'editable': True},
 {'column': 'hood', 'display_name': 'hood', 'position': 20, 'data_type': 'text', 'nullable': True, 'visible': True, 'editable': True},
 {'column': 'ftd', 'display_name': 'ftd', 'position': 21, 'data_type': 'text', 'nullable': True, 'visible': True, 'editable': True},
 {'column': 'ifr_approach', 'display_name': 'ifr app', 'position': 22, 'data_type': 'text', 'nullable': True, 'visible': True, 'editable': True},
 {'column': 'cross_country_dual_day', 'display_name': 'cross country dual day', 'position': 23, 'data_type': 'text', 'nullable': True, 'visible': True, 'editable': True},
 {'column': 'cross_country_pic_day', 'display_name': 'cross country pic day', 'position': 24, 'data_type': 'text', 'nullable': True, 'visible': True, 'editable': True},
 {'column': 'cross_country_dual_night', 'display_name': 'cross country dual night', 'position': 25, 'data_type': 'text', 'nullable': True, 'visible': True, 'editable': True},
 {'column': 'cross_country_pic_night', 'display_name': 'cross country pic night', 'position': 26, 'data_type': 'text', 'nullable': True, 'visible': True, 'editable': True},
 {'column': 'landings_day', 'display_name': 'landings day', 'position': 27, 'data_type': 'text', 'nullable': True, 'visible': True, 'editable': True},
 {'column': 'landings_night', 'display_name': 'landings night', 'position': 28, 'data_type': 'text', 'nullable': True, 'visible': True, 'editable': True},
 {'column': 'instruction_day', 'display_name': 'instruction day', 'position': 29, 'data_type': 'text', 'nullable': True, 'visible': True, 'editable': True},
 {'column': 'instruction_night', 'display_name': 'instruction night', 'position': 30, 'data_type': 'text', 'nullable': True, 'visible': True, 'editable': True},
]

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


def config_path(username=None):
    u = _cfg_username(username); return user_file(f"{u}_data.yml", username)
def logbook_db_config_path(username=None):
    u = _cfg_username(username); return user_file(f"{u}_logbook.yml", username)
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


def _norm_user(raw, index):
    item = dict(raw or {})
    display = str(item.get("display_name", item.get("affichage", "")) or "").strip()
    col = str(item.get("column", item.get("colonne_technique", "")) or "").strip() or technical_name(display)
    safe_identifier(col)
    rules = item.get("import_rules", item.get("import", [])) or []
    rules = list(dict.fromkeys(str(x).strip() for x in rules if str(x).strip()))
    dt = str(item.get("data_type", "text") or "text").lower()
    return {"column": col, "display_name": display, "position": index,
            "data_type": dt, "nullable": bool(item.get("nullable", True)), "visible": bool(item.get("visible", True)),
            "editable": bool(item.get("editable", True)), "import_rules": rules}


def _norm_system(raw, base):
    by = {x.get("column"): dict(x) for x in (raw or []) if x.get("column")}
    out = []
    for b in base:
        x = dict(b); x.update(by.get(b["column"], {})); x.pop("group", None); x.update(system=True, position=0, visible=False, editable=False)
        out.append(x)
    return out


def _norm_lb(raw, index):
    x = dict(raw or {})
    display = str(x.get("display_name", x.get("affichage", "")) or "").strip()
    col = str(x.get("column", "") or "").strip() or technical_name(display)
    safe_identifier(col)
    return {"column": col, "display_name": display, "position": index,
            "data_type": str(x.get("data_type", "text") or "text").lower(), "nullable": bool(x.get("nullable", True)),
            "visible": bool(x.get("visible", True)), "editable": bool(x.get("editable", True))}


def _load_yaml(path, fallback):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        _atomic_write(path, yaml.safe_dump(fallback, allow_unicode=True, sort_keys=False))
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def ensure_configs(username=None):
    if not config_path(username).exists():
        try:
            from flask import current_app
            bundled = __import__("pathlib").Path(current_app.root_path).parent / "defaults" / "default-userdb.yml"
            data = yaml.safe_load(bundled.read_text(encoding="utf-8")) if bundled.exists() else {"database": {"columns": DEFAULT_COLUMNS}}
        except Exception:
            data = {"database": {"columns": DEFAULT_COLUMNS}}
        _atomic_write(config_path(username), yaml.safe_dump(data, allow_unicode=True, sort_keys=False))
    if not logbook_db_config_path(username).exists():
        _atomic_write(logbook_db_config_path(username), yaml.safe_dump({"database": {"columns": DEFAULT_LOGBOOK_DB_COLUMNS}}, allow_unicode=True, sort_keys=False))
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


def load_config(username=None):
    ensure_configs(username)
    raw = _load_yaml(config_path(username), {})
    db = raw.get("database", raw); cols = db.get("columns", raw.get("categories", [])) or []
    systems = _norm_system(cols, SYSTEM_COLUMNS)
    normal = [_norm_user(x, i) for i, x in enumerate([x for x in cols if not is_system(x)], 1)]
    return {"database": {"columns": systems + normal}}


def save_config(data, username=None):
    db = data.get("database", data); cols = db.get("columns", [])
    _atomic_write(config_path(username), yaml.safe_dump({"database": {"columns": cols}}, allow_unicode=True, sort_keys=False))


def load_logbook_db_config(username=None):
    ensure_configs(username)
    raw = _load_yaml(logbook_db_config_path(username), {})
    db = raw.get("database", raw); cols = db.get("columns", []) or []
    systems = _norm_system(cols, LOGBOOK_SYSTEM_COLUMNS)
    normal = [_norm_lb(x, i) for i, x in enumerate([x for x in cols if not is_system(x)], 1)]
    return {"database": {"columns": systems + normal}}


def save_logbook_db_config(data, username=None):
    db = data.get("database", data)
    _atomic_write(logbook_db_config_path(username), yaml.safe_dump({"database": {"columns": db.get("columns", [])}}, allow_unicode=True, sort_keys=False))


def load_logbook_layout(username=None):
    ensure_configs(username)
    raw = _load_yaml(logbook_layout_path(username), DEFAULT_LOGBOOK_LAYOUT)
    cfg = dict(DEFAULT_LOGBOOK_LAYOUT); cfg.update(raw or {})
    cfg["styles"] = {**DEFAULT_LOGBOOK_LAYOUT["styles"], **(raw or {}).get("styles", {})}
    cfg["columns"] = (raw or {}).get("columns", DEFAULT_LOGBOOK_LAYOUT["columns"])
    return sanitize_layout(copy.deepcopy(cfg))      # valeurs CSS/numériques invalides -> valeurs par défaut


def save_logbook_layout(data, username=None):
    _atomic_write(logbook_layout_path(username), yaml.safe_dump(data, allow_unicode=True, sort_keys=False))


def configurable_columns(config): return [c for c in config["database"]["columns"] if not is_system(c)]


# ---------------- read-only grid view (visual only — never touches the data) ----------------

def data_view_path(username=None): u = _cfg_username(username); return user_file(f"{u}_data_view.yml", username)
def logbook_view_path(username=None): u = _cfg_username(username); return user_file(f"{u}_logbook_view.yml", username)


def _default_view(columns):
    view = []
    for i, c in enumerate(columns):
        view.append({"column": c["column"], "label": c["display_name"],
                     "width": 160, "align": "right" if c["data_type"] in ("integer", "decimal") else "left",
                     "frozen": i == 0})
    return view


def _load_view(path, columns):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        _atomic_write(path, yaml.safe_dump({"columns": _default_view(columns)}, allow_unicode=True, sort_keys=False))
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    by = {v.get("column"): v for v in raw.get("columns", []) if v.get("column")}
    out = []
    for c in columns:
        v = by.get(c["column"], {})
        out.append({"column": c["column"], "data_type": c["data_type"], "label": str(v.get("label", c["display_name"])),
                    "width": int(v.get("width", 160)), "align": v.get("align", "left") if v.get("align") in ("left", "center", "right") else "left",
                    "frozen": bool(v.get("frozen", False))})
    return out


def load_data_view(config, username=None):
    return _load_view(data_view_path(username), configurable_columns(config))


DATE_PARTS = ("year", "month", "day")


def load_logbook_view(username=None):
    """Colonnes affichées dans Données converties : la date est séparée en année / mois / jour (filtres plus simples)."""
    columns = []
    for c in load_logbook_db_config(username)["database"]["columns"]:
        if is_system(c): continue
        if c["column"] == "date":
            columns += [{"column": p, "display_name": p, "data_type": "integer"} for p in DATE_PARTS]
        else:
            columns.append(c)
    return _load_view(logbook_view_path(username), columns)
def logbook_columns(config, username=None): return [c for c in load_logbook_db_config(username)["database"]["columns"] if not is_system(c)]
def system_columns(config): return [c for c in config["database"]["columns"] if is_system(c)]


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
