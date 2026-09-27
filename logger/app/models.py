import re
import sqlite3
from pathlib import Path
import yaml
import shutil
from flask import current_app

SYSTEM_COLUMNS = [
    {"column": "id", "display_name": "ID", "position": 0, "group": "system", "data_type": "integer", "nullable": False, "visible": False, "editable": False, "primary_key": True},
    {"column": "created_at", "display_name": "Created at", "position": 0, "group": "system", "data_type": "datetime", "nullable": False, "visible": False, "editable": False},
    {"column": "updated_at", "display_name": "Updated at", "position": 0, "group": "system", "data_type": "datetime", "nullable": False, "visible": False, "editable": False},
    {"column": "import_source", "display_name": "Import source", "position": 0, "group": "system", "data_type": "text", "nullable": True, "visible": False, "editable": False},
]

DEFAULT_COLUMNS = [
    {"position": 1, "display_name": "year", "group": "date", "column": "year", "data_type": "integer", "nullable": True, "visible": True, "editable": True, "import_rules": ["year"]},
    {"position": 2, "display_name": "month", "group": "date", "column": "month", "data_type": "integer", "nullable": True, "visible": True, "editable": True, "import_rules": ["month"]},
    {"position": 3, "display_name": "day", "group": "date", "column": "day", "data_type": "integer", "nullable": True, "visible": True, "editable": True, "import_rules": ["day"]},
    {"position": 4, "display_name": "type", "group": "aircraft", "column": "type", "data_type": "text", "nullable": True, "visible": True, "editable": True, "import_rules": ["type"]},
    {"position": 5, "display_name": "registration", "group": "aircraft", "column": "registration", "data_type": "text", "nullable": True, "visible": True, "editable": True, "import_rules": ["immat", "reg", "registration"]},
    {"position": 6, "display_name": "pilot in command", "group": "crew", "column": "pilot_in_command", "data_type": "text", "nullable": True, "visible": True, "editable": True, "import_rules": ["pic"]},
    {"position": 7, "display_name": "copilot", "group": "crew", "column": "copilot", "data_type": "text", "nullable": True, "visible": True, "editable": True, "import_rules": ["copi"]},
    {"position": 8, "display_name": "departure", "group": "airports", "column": "departure", "data_type": "text", "nullable": True, "visible": True, "editable": True, "import_rules": ["dep"]},
    {"position": 9, "display_name": "arrival", "group": "airports", "column": "arrival", "data_type": "text", "nullable": True, "visible": True, "editable": True, "import_rules": ["arr"]},
    {"position": 10, "display_name": "remarks", "group": "misc", "column": "remarks", "data_type": "text", "nullable": True, "visible": True, "editable": True, "import_rules": ["remarks"]},
    {"position": 11, "display_name": "single engine dual day", "group": "time", "column": "single_engine_dual_day", "data_type": "text", "nullable": True, "visible": True, "editable": True, "import_rules": ["se dual day"]},
    {"position": 12, "display_name": "single engine pic day", "group": "time", "column": "single_engine_pic_day", "data_type": "text", "nullable": True, "visible": True, "editable": True, "import_rules": ["se pic day"]},
    {"position": 13, "display_name": "single engine dual night", "group": "time", "column": "single_engine_dual_night", "data_type": "text", "nullable": True, "visible": True, "editable": True, "import_rules": ["se dual night"]},
    {"position": 14, "display_name": "single engine pic night", "group": "time", "column": "single_engine_pic_night", "data_type": "text", "nullable": True, "visible": True, "editable": True, "import_rules": ["se pic night"]},
]


def config_path():
    return Path(current_app.instance_path) / "configuration.yml"


def ensure_config():
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        bundled = Path(current_app.root_path).parent / "default-configuration.yml"
        if bundled.exists():
            shutil.copyfile(bundled, path)
        else:
            save_config({"database": {"name": "users", "columns": DEFAULT_COLUMNS}})


def safe_identifier(value):
    value = str(value or "").strip()
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        raise ValueError(f"Nom de colonne technique invalide: {value}")
    return value


def _technical_name(display_name):
    value = str(display_name or "").strip().lower()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    if not value:
        raise ValueError("Le display_name doit produire un nom de colonne technique valide.")
    if value[0].isdigit():
        value = "_" + value
    safe_identifier(value)
    if value in {c["column"] for c in SYSTEM_COLUMNS}:
        raise ValueError(f"Nom de colonne réservé: {value}")
    return value


def _normalize_column(raw, index):
    item = dict(raw or {})
    display_name = str(item.get("display_name", item.get("affichage", "")) or "").strip()
    group = str(item.get("group", item.get("groupe", "")) or "").strip()
    column = str(item.get("column", item.get("colonne_technique", "")) or "").strip()
    if not column:
        column = _technical_name(display_name)
    else:
        safe_identifier(column)
        if column in {c["column"] for c in SYSTEM_COLUMNS}:
            raise ValueError(f"Nom de colonne réservé: {column}")
    rules = item.get("import_rules", item.get("import", [])) or []
    rules = list(dict.fromkeys(str(rule).strip() for rule in rules if str(rule).strip()))
    data_type = str(item.get("data_type", "text") or "text").lower()
    if data_type not in {"text", "integer", "decimal", "date", "datetime", "boolean"}:
        raise ValueError(f"Type de donnée invalide pour {column}: {data_type}")
    return {
        "column": column,
        "display_name": display_name,
        "position": index,
        "group": group,
        "data_type": data_type,
        "nullable": bool(item.get("nullable", True)),
        "visible": bool(item.get("visible", True)),
        "editable": bool(item.get("editable", True)),
        "import_rules": rules,
    }


def _normalize_system_columns(raw_columns):
    by_name = {c["column"]: dict(c) for c in (raw_columns or []) if c.get("column")}
    result = []
    for base in SYSTEM_COLUMNS:
        item = dict(base)
        item.update(by_name.get(base["column"], {}))
        item["group"] = "system"
        item["position"] = 0
        item["visible"] = False
        item["editable"] = False
        result.append(item)
    return result


def _normalize_config(data):
    data = data or {}
    database = data.get("database") or {}
    raw_columns = database.get("columns")
    if raw_columns is None:
        raw_columns = data.get("categories") or []
    system_names = {s["column"] for s in SYSTEM_COLUMNS}
    raw_non_system = [item for item in raw_columns if str((item or {}).get("column", (item or {}).get("colonne_technique", ""))).strip() not in system_names]
    columns = [_normalize_column(item, index) for index, item in enumerate(raw_non_system, 1)]
    # System columns are always present and protected; they are part of the same list.
    system = _normalize_system_columns(database.get("columns") or [])
    return {"database": {"name": database.get("name", "users"), "columns": system + columns}}


def load_config():
    ensure_config()
    data = yaml.safe_load(config_path().read_text(encoding="utf-8")) or {}
    normalized = _normalize_config(data)
    # Migrate legacy configuration.yml to the new single-list schema on first load.
    if data != normalized:
        save_config(normalized)
    return normalized


def save_config(data):
    normalized = _normalize_config(data)
    config_path().write_text(yaml.safe_dump(normalized, allow_unicode=True, sort_keys=False), encoding="utf-8")


def configurable_columns(config):
    return [c for c in config["database"]["columns"] if c.get("group") != "system"]


def system_columns(config):
    return [c for c in config["database"]["columns"] if c.get("group") == "system"]


def db_path():
    return Path(current_app.instance_path) / "user.db"


def sqlite_type(data_type):
    return {"integer": "INTEGER", "decimal": "REAL", "boolean": "INTEGER", "date": "TEXT", "datetime": "TEXT", "text": "TEXT"}.get(data_type, "TEXT")


def connect():
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    return conn


def init_db(app):
    with app.app_context():
        config = load_config()
        conn = connect()
        conn.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, import_source TEXT)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_users_import_source ON users(import_source)")
        sync_user_columns(conn, config)
        conn.commit()
        conn.close()


def sync_user_columns(conn, config):
    existing = {row[1] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
    for column in config["database"]["columns"]:
        col = safe_identifier(column["column"])
        if col == "id":
            continue
        if col not in existing:
            nullable = "" if column.get("nullable", True) else " NOT NULL"
            conn.execute(f'ALTER TABLE users ADD COLUMN "{col}" {sqlite_type(column.get("data_type"))}{nullable}')


def drop_unused_columns(conn, config):
    configured = {c["column"] for c in config["database"]["columns"]}
    existing = [row[1] for row in conn.execute("PRAGMA table_info(users)").fetchall()]
    protected = {c["column"] for c in SYSTEM_COLUMNS}
    for col in existing:
        if col not in configured and col not in protected:
            conn.execute(f'ALTER TABLE users DROP COLUMN "{safe_identifier(col)}"')


def clear_import_source(source):
    conn = connect()
    conn.execute("DELETE FROM users WHERE import_source = ?", (source,))
    conn.commit()
    conn.close()


def import_rows(source, rows, config):
    conn = connect()
    sync_user_columns(conn, config)
    drop_unused_columns(conn, config)
    columns = [safe_identifier(c["column"]) for c in configurable_columns(config)]
    conn.execute("DELETE FROM users WHERE import_source = ?", (source,))
    if rows and columns:
        placeholders = ", ".join("?" for _ in columns)
        names = ", ".join(f'"{c}"' for c in columns)
        sql = f'INSERT INTO users (import_source, {names}) VALUES (?, {placeholders})'
        for row in rows:
            now_values = [row.get(c) for c in columns]
            conn.execute(sql, [source] + now_values)
    conn.commit()
    conn.close()


def list_users(config):
    conn = connect()
    visible = [c for c in configurable_columns(config) if c.get("visible", True)]
    cols = [c["column"] for c in sorted(visible, key=lambda c: int(c.get("position", 0)))]
    select_cols = ", ".join(["id", "created_at", "updated_at", "import_source"] + [f'"{safe_identifier(c)}"' for c in cols])
    rows = conn.execute(f"SELECT {select_cols} FROM users ORDER BY id").fetchall()
    conn.close()
    return cols, rows
