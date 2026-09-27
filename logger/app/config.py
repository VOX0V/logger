"""Per-user YAML configuration: userdb.yml, logbookdb.yml, logbook.yml."""
import yaml
from .db import user_file, safe_identifier

SYSTEM_COLUMNS = [
    {"column": "id", "display_name": "ID", "position": 0, "group": "system", "data_type": "integer", "nullable": False, "visible": False, "editable": False, "primary_key": True},
    {"column": "created_at", "display_name": "Created at", "position": 0, "group": "system", "data_type": "datetime", "nullable": False, "visible": False, "editable": False},
    {"column": "updated_at", "display_name": "Updated at", "position": 0, "group": "system", "data_type": "datetime", "nullable": False, "visible": False, "editable": False},
    {"column": "import_source", "display_name": "Import source", "position": 0, "group": "system", "data_type": "text", "nullable": True, "visible": False, "editable": False},
]
LOGBOOK_SYSTEM_COLUMNS = [dict(c) for c in SYSTEM_COLUMNS]

DEFAULT_COLUMNS = [
 {"position": 1, "display_name": "year", "group": "date", "column": "year", "data_type": "integer", "nullable": True, "visible": True, "editable": True, "import_rules": ["year"]},
 {"position": 2, "display_name": "month", "group": "date", "column": "month", "data_type": "integer", "nullable": True, "visible": True, "editable": True, "import_rules": ["month"]},
 {"position": 3, "display_name": "day", "group": "date", "column": "day", "data_type": "integer", "nullable": True, "visible": True, "editable": True, "import_rules": ["day"]},
 {"position": 4, "display_name": "type", "group": "aircraft", "column": "type", "data_type": "text", "nullable": True, "visible": True, "editable": True, "import_rules": ["type"]},
 {"position": 5, "display_name": "registration", "group": "aircraft", "column": "registration", "data_type": "text", "nullable": True, "visible": True, "editable": True, "import_rules": ["immat", "reg", "registration"]},
 {"position": 6, "display_name": "pilot in command", "group": "crew", "column": "pilot_in_command", "data_type": "text", "nullable": True, "visible": True, "editable": True, "import_rules": ["pic"]},
 {"position": 7, "display_name": "copilot", "group": "crew", "column": "copilot", "data_type": "text", "nullable": True, "visible": True, "editable": True, "import_rules": ["copi"]},
 {"position": 8, "display_name": "departure", "group": "route", "column": "departure", "data_type": "text", "nullable": True, "visible": True, "editable": True, "import_rules": ["dep"]},
 {"position": 9, "display_name": "arrival", "group": "route", "column": "arrival", "data_type": "text", "nullable": True, "visible": True, "editable": True, "import_rules": ["arr"]},
 {"position": 10, "display_name": "remarks", "group": "remarks", "column": "remarks", "data_type": "text", "nullable": True, "visible": True, "editable": True, "import_rules": ["remarks"]},
]

DEFAULT_LOGBOOK_DB_COLUMNS = [
 {"column": "date", "display_name": "date", "position": 1, "group": "date", "data_type": "date", "nullable": True, "visible": True, "editable": True,
  "source": [{"type": "date_parts", "source": ["users.year", "users.month", "users.day"]}, {"type": "datetime", "source": ["users.departure_local"]}], "transformation": "date"},
 {"column": "aircraft_type", "display_name": "aircraft type", "position": 2, "group": "aircraft", "data_type": "text", "nullable": True, "visible": True, "editable": True, "source": ["users.type"], "transformation": ""},
 {"column": "registration", "display_name": "registration", "position": 3, "group": "aircraft", "data_type": "text", "nullable": True, "visible": True, "editable": True, "source": ["users.registration"], "transformation": ""},
 {"column": "pilot_in_command", "display_name": "pilot in command", "position": 4, "group": "crew", "data_type": "text", "nullable": True, "visible": True, "editable": True, "source": ["users.pilot_in_command"], "transformation": ""},
 {"column": "copilot", "display_name": "copilot", "position": 5, "group": "crew", "data_type": "text", "nullable": True, "visible": True, "editable": True, "source": ["users.copilot"], "transformation": ""},
 {"column": "departure", "display_name": "departure", "position": 6, "group": "route", "data_type": "text", "nullable": True, "visible": True, "editable": True, "source": ["users.departure"], "transformation": ""},
 {"column": "arrival", "display_name": "arrival", "position": 7, "group": "route", "data_type": "text", "nullable": True, "visible": True, "editable": True, "source": ["users.arrival"], "transformation": ""},
 {"column": "remarks", "display_name": "remarks", "position": 8, "group": "remarks", "data_type": "text", "nullable": True, "visible": True, "editable": True, "source": ["users.remarks"], "transformation": ""},
 {"column": "single_engine_dual_day", "display_name": "single engine dual day", "position": 9, "group": "single_engine", "data_type": "text", "nullable": True, "visible": True, "editable": True, "source": ["users.single_engine_dual_day"], "transformation": ""},
 {"column": "single_engine_pic_day", "display_name": "single engine pic day", "position": 10, "group": "single_engine", "data_type": "text", "nullable": True, "visible": True, "editable": True, "source": ["users.single_engine_pic_day"], "transformation": ""},
 {"column": "single_engine_dual_night", "display_name": "single engine dual night", "position": 11, "group": "single_engine", "data_type": "text", "nullable": True, "visible": True, "editable": True, "source": ["users.single_engine_dual_night"], "transformation": ""},
 {"column": "single_engine_pic_night", "display_name": "single engine pic night", "position": 12, "group": "single_engine", "data_type": "text", "nullable": True, "visible": True, "editable": True, "source": ["users.single_engine_pic_night"], "transformation": ""},
 {"column": "multi_engine_dual_day", "display_name": "multi engine dual day", "position": 13, "group": "multi_engine", "data_type": "text", "nullable": True, "visible": True, "editable": True, "source": ["users.multi_engine_dual_day"], "transformation": ""},
 {"column": "multi_engine_pic_day", "display_name": "multi engine pic day", "position": 14, "group": "multi_engine", "data_type": "text", "nullable": True, "visible": True, "editable": True, "source": ["users.multi_engine_pic_day"], "transformation": ""},
 {"column": "multi_engine_copi_day", "display_name": "multi engine copilot day", "position": 15, "group": "multi_engine", "data_type": "text", "nullable": True, "visible": True, "editable": True, "source": ["users.multi_engine_copi_day"], "transformation": ""},
 {"column": "multi_engine_dual_night", "display_name": "multi engine dual night", "position": 16, "group": "multi_engine", "data_type": "text", "nullable": True, "visible": True, "editable": True, "source": ["users.multi_engine_dual_night"], "transformation": ""},
 {"column": "multi_engine_pic_night", "display_name": "multi engine pic night", "position": 17, "group": "multi_engine", "data_type": "text", "nullable": True, "visible": True, "editable": True, "source": ["users.multi_engine_pic_night"], "transformation": ""},
 {"column": "multi_engine_copi_night", "display_name": "multi engine copilot night", "position": 18, "group": "multi_engine", "data_type": "text", "nullable": True, "visible": True, "editable": True, "source": ["users.multi_engine_copi_night"], "transformation": ""},
 {"column": "ifr", "display_name": "ifr", "position": 19, "group": "instruments", "data_type": "text", "nullable": True, "visible": True, "editable": True, "source": ["users.ifr"], "transformation": ""},
 {"column": "hood", "display_name": "hood", "position": 20, "group": "instruments", "data_type": "text", "nullable": True, "visible": True, "editable": True, "source": ["users.hood"], "transformation": ""},
 {"column": "ftd", "display_name": "ftd", "position": 21, "group": "instruments", "data_type": "text", "nullable": True, "visible": True, "editable": True, "source": ["users.ftd"], "transformation": ""},
 {"column": "ifr_approach", "display_name": "ifr app", "position": 22, "group": "instruments", "data_type": "text", "nullable": True, "visible": True, "editable": True, "source": ["users.ifr_approach"], "transformation": ""},
 {"column": "cross_country_dual_day", "display_name": "cross country dual day", "position": 23, "group": "cross_country", "data_type": "text", "nullable": True, "visible": True, "editable": True, "source": ["users.cross_country_dual_day"], "transformation": ""},
 {"column": "cross_country_pic_day", "display_name": "cross country pic day", "position": 24, "group": "cross_country", "data_type": "text", "nullable": True, "visible": True, "editable": True, "source": ["users.cross_country_pic_day"], "transformation": ""},
 {"column": "cross_country_dual_night", "display_name": "cross country dual night", "position": 25, "group": "cross_country", "data_type": "text", "nullable": True, "visible": True, "editable": True, "source": ["users.cross_country_dual_night"], "transformation": ""},
 {"column": "cross_country_pic_night", "display_name": "cross country pic night", "position": 26, "group": "cross_country", "data_type": "text", "nullable": True, "visible": True, "editable": True, "source": ["users.cross_country_pic_night"], "transformation": ""},
 {"column": "landings_day", "display_name": "landings day", "position": 27, "group": "landings", "data_type": "text", "nullable": True, "visible": True, "editable": True, "source": ["users.landings_day"], "transformation": ""},
 {"column": "landings_night", "display_name": "landings night", "position": 28, "group": "landings", "data_type": "text", "nullable": True, "visible": True, "editable": True, "source": ["users.landings_night"], "transformation": ""},
 {"column": "instruction_day", "display_name": "instruction day", "position": 29, "group": "instruction", "data_type": "text", "nullable": True, "visible": True, "editable": True, "source": ["users.instruction_day"], "transformation": ""},
 {"column": "instruction_night", "display_name": "instruction night", "position": 30, "group": "instruction", "data_type": "text", "nullable": True, "visible": True, "editable": True, "source": ["users.instruction_night"], "transformation": ""},
]

DEFAULT_LOGBOOK_LAYOUT = {
 "title": "Logbook", "rows_per_page": 30, "row_height": 16.95, "header_heights": [16.95, 16.95, 16.95, 16.95],
 "styles": {"font_family": "Arial", "font_size": 10, "header_font_size": 9, "border": "1px solid #000000", "header_background": "#ffffff", "total_background": "#eeeeee", "text_align": "center", "vertical_align": "middle"},
 "columns": [
  {"key": "year", "label": "YEAR", "db_column": "date", "date_part": "year", "width": 6.55, "group": "date"},
  {"key": "month", "label": "Month", "db_column": "date", "date_part": "month", "width": 13, "group": "date"},
  {"key": "day", "label": "Day", "db_column": "date", "date_part": "day", "width": 13, "group": "date"},
  {"key": "type", "label": "Type", "db_column": "aircraft_type", "width": 13, "group": "aircraft"},
  {"key": "registration", "label": "Registr.", "db_column": "registration", "width": 8.33, "group": "aircraft"},
  {"key": "pilot", "label": "Pilot", "db_column": "pilot_in_command", "width": 11.55, "group": "crew"},
  {"key": "copilot", "label": "Co-Pilot", "db_column": "copilot", "width": 13, "group": "crew"},
  {"key": "departure", "label": "Departure", "db_column": "departure", "width": 10, "group": "route"},
  {"key": "arrival", "label": "Arrival", "db_column": "arrival", "width": 13, "group": "route"},
  {"key": "remarks", "label": "Exercise, Mission, Flight Number…", "db_column": "remarks", "width": 13, "group": "remarks", "colspan": 2},
  {"key": "remarks_cont", "label": "", "width": 27.11, "group": "remarks_cont"},
  {"key": "se_dual_day", "label": "Dual", "db_column": "single_engine_dual_day", "width": 7.55, "group": "single_engine", "subgroup": "Day"},
  {"key": "se_pic_day", "label": "PIC", "db_column": "single_engine_pic_day", "width": 13, "group": "single_engine", "subgroup": "Day"},
  {"key": "se_dual_night", "label": "Dual", "db_column": "single_engine_dual_night", "width": 13, "group": "single_engine", "subgroup": "Night"},
  {"key": "se_pic_night", "label": "PIC", "db_column": "single_engine_pic_night", "width": 13, "group": "single_engine", "subgroup": "Night"},
  {"key": "spacer1", "label": "", "width": 3.89, "group": "spacer"},
  {"key": "spacer2", "label": "", "width": 4.89, "group": "spacer"},
  {"key": "me_dual_day", "label": "Dual", "db_column": "multi_engine_dual_day", "width": 7.66, "group": "multi_engine", "subgroup": "Day"},
  {"key": "me_pic_day", "label": "PIC", "db_column": "multi_engine_pic_day", "width": 13, "group": "multi_engine", "subgroup": "Day"},
  {"key": "me_copilot_day", "label": "Co-Pilot", "db_column": "multi_engine_copi_day", "width": 13, "group": "multi_engine", "subgroup": "Day"},
  {"key": "me_dual_night", "label": "Dual", "db_column": "multi_engine_dual_night", "width": 13, "group": "multi_engine", "subgroup": "Night"},
  {"key": "me_pic_night", "label": "PIC", "db_column": "multi_engine_pic_night", "width": 13, "group": "multi_engine", "subgroup": "Night"},
  {"key": "me_copilot_night", "label": "Co-Pilot", "db_column": "multi_engine_copi_night", "width": 13, "group": "multi_engine", "subgroup": "Night"},
  {"key": "ifr", "label": "IFR", "db_column": "ifr", "width": 13, "group": "instruments"},
  {"key": "hood", "label": "Hood", "db_column": "hood", "width": 13, "group": "instruments"},
  {"key": "ftd", "label": "FTD", "db_column": "ftd", "width": 13, "group": "instruments"},
  {"key": "ifr_app", "label": "IFR app", "db_column": "ifr_approach", "width": 13, "group": "instruments"},
  {"key": "cc_dual_day", "label": "Dual", "db_column": "cross_country_dual_day", "width": 13, "group": "cross_country", "subgroup": "Day"},
  {"key": "cc_pic_day", "label": "PIC", "db_column": "cross_country_pic_day", "width": 13, "group": "cross_country", "subgroup": "Day"},
  {"key": "cc_dual_night", "label": "Dual", "db_column": "cross_country_dual_night", "width": 13, "group": "cross_country", "subgroup": "Night"},
  {"key": "cc_pic_night", "label": "PIC", "db_column": "cross_country_pic_night", "width": 13, "group": "cross_country", "subgroup": "Night"},
  {"key": "land_day", "label": "Day", "db_column": "landings_day", "width": 13, "group": "landings"},
  {"key": "land_night", "label": "Night", "db_column": "landings_night", "width": 13, "group": "landings"},
  {"key": "instruction_day", "label": "Day", "db_column": "instruction_day", "width": 13, "group": "instruction"},
  {"key": "instruction_night", "label": "Night", "db_column": "instruction_night", "width": 13, "group": "instruction"},
  {"key": "total", "label": "Total", "width": 5, "group": "total", "total": True},
 ],
 "group_labels": {"date": "YEAR", "aircraft": "AIRCRAFT", "crew": "FLIGHT CREW", "route": "ROUTE OF FLIGHT", "remarks": "REMARKS", "single_engine": "SINGLE-ENGINE", "multi_engine": "MULTI-ENGINE", "instruments": "INSTRUMENTS", "cross_country": "CROSS-COUNTRY", "landings": "TAKEOFFS & LANDINGS", "instruction": "INSTRUCTION", "total": ""},
 "group_spans": {"date": 3, "aircraft": 2, "crew": 2, "route": 2, "remarks": 2, "single_engine": 4, "spacer": 2, "multi_engine": 6, "instruments": 4, "cross_country": 4, "landings": 2, "instruction": 2, "total": 1},
}


def _cfg_username(username):
    from .db import current_username
    return username or current_username()


def config_path(username=None):
    u = _cfg_username(username); return user_file(f"{u}_data.yml", username)
def logbook_db_config_path(username=None):
    u = _cfg_username(username); return user_file(f"{u}_logbook.yml", username)
def logbook_layout_path(username=None):
    u = _cfg_username(username); return user_file(f"{u}_layout.yml", username)


def technical_name(display_name):
    value = str(display_name or "").strip().lower()
    value = __import__("re").sub(r"[^a-z0-9]+", "_", value)
    value = __import__("re").sub(r"_+", "_", value).strip("_")
    if not value:
        raise ValueError("Le display_name doit produire un nom de colonne technique valide.")
    if value[0].isdigit():
        value = "_" + value
    safe_identifier(value)
    if value in {"id", "created_at", "updated_at", "import_source"}:
        raise ValueError(f"Nom de colonne réservé: {value}")
    return value


def _norm_user(raw, index):
    item = dict(raw or {})
    display = str(item.get("display_name", item.get("affichage", "")) or "").strip()
    col = str(item.get("column", item.get("colonne_technique", "")) or "").strip() or technical_name(display)
    safe_identifier(col)
    rules = item.get("import_rules", item.get("import", [])) or []
    rules = list(dict.fromkeys(str(x).strip() for x in rules if str(x).strip()))
    dt = str(item.get("data_type", "text") or "text").lower()
    return {"column": col, "display_name": display, "position": index, "group": str(item.get("group", item.get("groupe", "")) or "").strip(),
            "data_type": dt, "nullable": bool(item.get("nullable", True)), "visible": bool(item.get("visible", True)),
            "editable": bool(item.get("editable", True)), "import_rules": rules}


def _norm_system(raw, base):
    by = {x.get("column"): dict(x) for x in (raw or []) if x.get("column")}
    out = []
    for b in base:
        x = dict(b); x.update(by.get(b["column"], {})); x.update(group="system", position=0, visible=False, editable=False)
        out.append(x)
    return out


def _norm_lb(raw, index):
    x = dict(raw or {})
    display = str(x.get("display_name", x.get("affichage", "")) or "").strip()
    col = str(x.get("column", "") or "").strip() or technical_name(display)
    safe_identifier(col)
    src = x.get("source", []) or []
    if isinstance(src, str): src = [src]
    norm = []
    for s in src:
        if isinstance(s, dict):
            norm.append({"type": str(s.get("type", "")), "source": [str(v).strip() for v in (s.get("source", []) or [])]})
        else:
            norm.append(str(s).strip())
    return {"column": col, "display_name": display, "position": index, "group": str(x.get("group", x.get("groupe", "")) or ""),
            "data_type": str(x.get("data_type", "text") or "text").lower(), "nullable": bool(x.get("nullable", True)),
            "visible": bool(x.get("visible", True)), "editable": bool(x.get("editable", True)), "source": norm,
            "transformation": str(x.get("transformation", "") or "")}


def _load_yaml(path, fallback):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(yaml.safe_dump(fallback, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def ensure_configs(username=None):
    if not config_path(username).exists():
        try:
            from flask import current_app
            bundled = __import__("pathlib").Path(current_app.root_path).parent / "default-userdb.yml"
            data = yaml.safe_load(bundled.read_text(encoding="utf-8")) if bundled.exists() else {"database": {"name": "user", "columns": DEFAULT_COLUMNS}}
        except Exception:
            data = {"database": {"name": "user", "columns": DEFAULT_COLUMNS}}
        config_path(username).write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    if not logbook_db_config_path(username).exists():
        logbook_db_config_path(username).write_text(yaml.safe_dump({"database": {"name": "logbook", "columns": DEFAULT_LOGBOOK_DB_COLUMNS}}, allow_unicode=True, sort_keys=False), encoding="utf-8")
    if not logbook_layout_path(username).exists():
        logbook_layout_path(username).write_text(yaml.safe_dump(DEFAULT_LOGBOOK_LAYOUT, allow_unicode=True, sort_keys=False), encoding="utf-8")


def load_config(username=None):
    ensure_configs(username)
    raw = _load_yaml(config_path(username), {})
    db = raw.get("database", raw); cols = db.get("columns", raw.get("categories", [])) or []
    systems = _norm_system(cols, SYSTEM_COLUMNS)
    normal = [_norm_user(x, i) for i, x in enumerate([x for x in cols if x.get("group") != "system"], 1)]
    return {"database": {"name": db.get("name", "user"), "columns": systems + normal}}


def save_config(data, username=None):
    db = data.get("database", data); cols = db.get("columns", [])
    config_path(username).write_text(yaml.safe_dump({"database": {"name": db.get("name", "user"), "columns": cols}}, allow_unicode=True, sort_keys=False), encoding="utf-8")


def load_logbook_db_config(username=None):
    ensure_configs(username)
    raw = _load_yaml(logbook_db_config_path(username), {})
    db = raw.get("database", raw); cols = db.get("columns", []) or []
    systems = _norm_system(cols, LOGBOOK_SYSTEM_COLUMNS)
    normal = [_norm_lb(x, i) for i, x in enumerate([x for x in cols if x.get("group") != "system"], 1)]
    return {"database": {"name": "logbook", "columns": systems + normal}}


def save_logbook_db_config(data, username=None):
    db = data.get("database", data)
    logbook_db_config_path(username).write_text(yaml.safe_dump({"database": {"name": "logbook", "columns": db.get("columns", [])}}, allow_unicode=True, sort_keys=False), encoding="utf-8")


def load_logbook_layout(username=None):
    ensure_configs(username)
    raw = _load_yaml(logbook_layout_path(username), DEFAULT_LOGBOOK_LAYOUT)
    cfg = dict(DEFAULT_LOGBOOK_LAYOUT); cfg.update(raw or {})
    cfg["styles"] = {**DEFAULT_LOGBOOK_LAYOUT["styles"], **(raw or {}).get("styles", {})}
    cfg["columns"] = (raw or {}).get("columns", DEFAULT_LOGBOOK_LAYOUT["columns"])
    return cfg


def save_logbook_layout(data, username=None):
    logbook_layout_path(username).write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def configurable_columns(config): return [c for c in config["database"]["columns"] if c.get("group") != "system"]
def logbook_columns(config, username=None): return [c for c in load_logbook_db_config(username)["database"]["columns"] if c.get("group") != "system"]
def system_columns(config): return [c for c in config["database"]["columns"] if c.get("group") == "system"]
