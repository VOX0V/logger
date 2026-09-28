"""SQLite schema management for the per-user 'users' (raw import) table."""
from .db import connect, logbook_connect, safe_identifier, sqlite_type, user_root
from .config import (SYSTEM_COLUMNS, LOGBOOK_SYSTEM_COLUMNS, load_config, load_logbook_db_config,
                      configurable_columns, ensure_configs)


def sync_columns(conn, table, columns):
    existing = {r[1] for r in conn.execute(f'PRAGMA table_info({safe_identifier(table)})').fetchall()}
    for c in columns:
        col = safe_identifier(c["column"])
        if col == "id" or col in existing:
            continue
        conn.execute(f'ALTER TABLE "{safe_identifier(table)}" ADD COLUMN "{col}" {sqlite_type(c.get("data_type"))}')


def sync_user_columns(conn, config): sync_columns(conn, "users", config["database"]["columns"])
def sync_logbook_columns(conn, config, username=None): sync_columns(conn, "logbook", load_logbook_db_config(username)["database"]["columns"])


def drop_unused_columns(conn, config):
    configured = {c["column"] for c in config["database"]["columns"]}
    existing = [r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()]
    for col in existing:
        if col not in configured and col not in {c["column"] for c in SYSTEM_COLUMNS}:
            conn.execute(f'ALTER TABLE users DROP COLUMN "{safe_identifier(col)}"')


def drop_unused_logbook_columns(conn, config, username=None):
    configured = {c["column"] for c in load_logbook_db_config(username)["database"]["columns"]}
    existing = [r[1] for r in conn.execute("PRAGMA table_info(logbook)").fetchall()]
    for col in existing:
        if col not in configured and col not in {c["column"] for c in LOGBOOK_SYSTEM_COLUMNS}:
            conn.execute(f'ALTER TABLE logbook DROP COLUMN "{safe_identifier(col)}"')


def import_rows(source, rows, config, username=None):
    conn = connect(username)
    sync_user_columns(conn, config)
    drop_unused_columns(conn, config)
    cols = [safe_identifier(c["column"]) for c in configurable_columns(config)]
    conn.execute("DELETE FROM users WHERE import_source=?", (source,))
    if rows and cols:
        sql = f'INSERT INTO users (import_source,{",".join(chr(34) + c + chr(34) for c in cols)}) VALUES (?,{",".join("?" for _ in cols)})'
        for row in rows:
            conn.execute(sql, [source] + [row.get(c) for c in cols])
    conn.commit(); conn.close()


def list_users(config, username=None):
    conn = connect(username)
    visible = [c for c in configurable_columns(config) if c.get("visible", True)]
    cols = [c["column"] for c in sorted(visible, key=lambda c: int(c["position"]))]
    select = ",".join(["id"] + [f'"{safe_identifier(c)}"' for c in cols])
    rows = conn.execute(f"SELECT {select} FROM users ORDER BY id").fetchall()
    conn.close()
    return cols, rows


def init_user_db(username):
    """Create (or bring up to date) the two SQLite databases, the YAML config
    files and the converter rule selection for a given user. Called when an
    account is created, and defensively on every login in case the user's
    folder is missing."""
    from .converter.catalog import ensure_user_selection  # lazy: avoids a circular import
    user_root(username)  # ensures the folder exists
    ensure_configs(username)
    ensure_user_selection(username)
    config = load_config(username)
    conn = connect(username)
    conn.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,import_source TEXT)")
    sync_user_columns(conn, config)
    conn.commit(); conn.close()
    lb = logbook_connect(username)
    lb.execute("CREATE TABLE IF NOT EXISTS logbook (id INTEGER PRIMARY KEY AUTOINCREMENT,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,import_source TEXT)")
    sync_logbook_columns(lb, config, username)
    lb.commit(); lb.close()
