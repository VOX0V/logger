import re
import sqlite3
from pathlib import Path
import yaml
import shutil
from flask import current_app

DEFAULT_CATEGORIES = [
    {"position": 1, "affichage": "year", "groupe": "date", "colonne_technique": "year", "import": ["year"]},
    {"position": 2, "affichage": "month", "groupe": "date", "colonne_technique": "month", "import": ["month"]},
    {"position": 3, "affichage": "day", "groupe": "date", "colonne_technique": "day", "import": ["day"]},
    {"position": 4, "affichage": "type", "groupe": "aircraft", "colonne_technique": "type", "import": ["type"]},
    {"position": 5, "affichage": "registration", "groupe": "aircraft", "colonne_technique": "registration", "import": ["immat", "reg", "registration"]},
    {"position": 6, "affichage": "pilot in command", "groupe": "crew", "colonne_technique": "pilot_in_command", "import": ["pic"]},
    {"position": 7, "affichage": "copilot", "groupe": "crew", "colonne_technique": "copilot", "import": ["copi"]},
    {"position": 8, "affichage": "departure", "groupe": "airports", "colonne_technique": "departure", "import": ["dep"]},
    {"position": 9, "affichage": "arrival", "groupe": "airports", "colonne_technique": "arrival", "import": ["arr"]},
    {"position": 10, "affichage": "remarks", "groupe": "misc", "colonne_technique": "remarks", "import": ["remarks"]},
    {"position": 11, "affichage": "single engine dual day", "groupe": "time", "colonne_technique": "single_engine_dual_day", "import": ["se dual day"]},
    {"position": 12, "affichage": "single engine pic day", "groupe": "time", "colonne_technique": "single_engine_pic_day", "import": ["se pic day"]},
    {"position": 13, "affichage": "single engine dual night", "groupe": "time", "colonne_technique": "single_engine_dual_night", "import": ["se dual night"]},
    {"position": 14, "affichage": "single engine pic night", "groupe": "time", "colonne_technique": "single_engine_pic_night", "import": ["se pic night"]},
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
            path.write_text(yaml.safe_dump({"categories": DEFAULT_CATEGORIES}, allow_unicode=True, sort_keys=False), encoding="utf-8")


def load_config():
    ensure_config()
    data = yaml.safe_load(config_path().read_text(encoding="utf-8")) or {}
    categories = data.get("categories") or []
    categories.sort(key=lambda c: int(c.get("position", 0)))
    return {"categories": categories}


def save_config(data):
    config_path().write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def db_path():
    return Path(current_app.instance_path) / "user.db"


def connect():
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    return conn


def safe_identifier(value):
    value = str(value or "").strip()
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        raise ValueError(f"Nom de colonne technique invalide: {value}")
    return value


def init_db(app):
    with app.app_context():
        ensure_config()
        conn = connect()
        conn.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, import_source TEXT NOT NULL)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_users_import_source ON users(import_source)")
        sync_user_columns(conn, load_config()["categories"])
        conn.commit()
        conn.close()


def sync_user_columns(conn, categories):
    existing = {row[1] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
    for category in categories:
        col = safe_identifier(category.get("colonne_technique"))
        if col in {"id", "import_source"}:
            raise ValueError(f"Colonne réservée: {col}")
        if col not in existing:
            conn.execute(f'ALTER TABLE users ADD COLUMN "{col}" TEXT')


def clear_import_source(source):
    conn = connect()
    conn.execute("DELETE FROM users WHERE import_source = ?", (source,))
    conn.commit()
    conn.close()


def import_rows(source, rows, categories):
    conn = connect()
    sync_user_columns(conn, categories)
    columns = [safe_identifier(c["colonne_technique"]) for c in categories]
    conn.execute("DELETE FROM users WHERE import_source = ?", (source,))
    if rows:
        placeholders = ", ".join("?" for _ in columns)
        names = ", ".join(f'"{c}"' for c in columns)
        sql = f'INSERT INTO users (import_source, {names}) VALUES (?, {placeholders})'
        for row in rows:
            conn.execute(sql, [source] + [row.get(c) for c in columns])
    conn.commit()
    conn.close()


def list_users():
    conn = connect()
    cols = [row[1] for row in conn.execute("PRAGMA table_info(users)").fetchall() if row[1] != "import_source"]
    rows = conn.execute("SELECT * FROM users ORDER BY id").fetchall()
    conn.close()
    return cols, rows
