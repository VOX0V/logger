import re
import sqlite3
from pathlib import Path
from flask import current_app

SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    display_name TEXT NOT NULL,
    column_name TEXT NOT NULL UNIQUE,
    position INTEGER NOT NULL,
    group_name TEXT
);
CREATE TABLE IF NOT EXISTS import_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category_id INTEGER NOT NULL,
    rule_text TEXT NOT NULL,
    FOREIGN KEY(category_id) REFERENCES categories(id) ON DELETE CASCADE,
    UNIQUE(category_id, rule_text)
);
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    import_source TEXT
);
"""


def db_path():
    return Path(current_app.instance_path) / "user.db"


def get_db():
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def table_columns(conn, table="users"):
    return [row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')]


def _slugify(name):
    text = name.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_") or "colonne"


def _unique_column_name(conn, base):
    existing = set(table_columns(conn))
    candidate = base
    n = 2
    while candidate in existing:
        candidate = f"{base}_{n}"
        n += 1
    return candidate


def list_categories(conn):
    return conn.execute("SELECT * FROM categories ORDER BY position, id").fetchall()


def list_rules_by_category(conn):
    result = {}
    for row in conn.execute("SELECT category_id, rule_text FROM import_rules ORDER BY id"):
        result.setdefault(row["category_id"], []).append(row["rule_text"])
    return result


def find_conflicting_rules(conn, rule_texts, exclude_category_id=None):
    conflicts = {}
    for rule in rule_texts:
        row = conn.execute(
            """SELECT import_rules.rule_text, categories.display_name, categories.id
               FROM import_rules JOIN categories ON categories.id = import_rules.category_id
               WHERE lower(import_rules.rule_text) = lower(?)""", (rule,)
        ).fetchone()
        if row and row["id"] != exclude_category_id:
            conflicts[rule] = row["display_name"]
    return conflicts


def create_category(conn, display_name, position, group_name, rule_texts):
    count = conn.execute("SELECT COUNT(*) FROM categories").fetchone()[0]
    position = max(1, min(position, count + 1))
    column_name = _unique_column_name(conn, _slugify(display_name))
    conn.execute("UPDATE categories SET position = position + 1 WHERE position >= ?", (position,))
    cur = conn.execute(
        "INSERT INTO categories(display_name,column_name,position,group_name) VALUES(?,?,?,?)",
        (display_name, column_name, position, group_name or None),
    )
    category_id = cur.lastrowid
    for rule in rule_texts:
        conn.execute("INSERT INTO import_rules(category_id,rule_text) VALUES(?,?)", (category_id, rule))
    conn.execute(f'ALTER TABLE users ADD COLUMN "{column_name}" TEXT')
    conn.commit()
    return category_id


def update_category(conn, category_id, display_name, position, group_name, rule_texts):
    current = conn.execute("SELECT position FROM categories WHERE id=?", (category_id,)).fetchone()
    if current is None:
        return
    count = conn.execute("SELECT COUNT(*) FROM categories").fetchone()[0]
    position = max(1, min(position, count))
    old = current["position"]
    if position != old:
        if position < old:
            conn.execute("UPDATE categories SET position=position+1 WHERE position>=? AND position<? AND id!=?", (position, old, category_id))
        else:
            conn.execute("UPDATE categories SET position=position-1 WHERE position<=? AND position>? AND id!=?", (position, old, category_id))
    conn.execute("UPDATE categories SET display_name=?,position=?,group_name=? WHERE id=?", (display_name, position, group_name or None, category_id))
    conn.execute("DELETE FROM import_rules WHERE category_id=?", (category_id,))
    for rule in rule_texts:
        conn.execute("INSERT INTO import_rules(category_id,rule_text) VALUES(?,?)", (category_id, rule))
    conn.commit()


def delete_category(conn, category_id):
    row = conn.execute("SELECT column_name,position FROM categories WHERE id=?", (category_id,)).fetchone()
    if not row:
        return
    conn.execute("DELETE FROM categories WHERE id=?", (category_id,))
    conn.execute("UPDATE categories SET position=position-1 WHERE position>?", (row["position"],))
    try:
        conn.execute(f'ALTER TABLE users DROP COLUMN "{row["column_name"]}"')
    except sqlite3.OperationalError:
        pass
    conn.commit()


def init_db(app):
    with app.app_context():
        Path(app.instance_path).mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path())
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(SCHEMA)
        columns = table_columns(conn)
        if "import_source" not in columns:
            conn.execute('ALTER TABLE users ADD COLUMN "import_source" TEXT')
        conn.execute("INSERT INTO schema_meta(key,value) VALUES('schema_version','4') ON CONFLICT(key) DO UPDATE SET value='4'")
        conn.commit()
        conn.close()
