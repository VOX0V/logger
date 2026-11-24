"""SQLite schema management for the per-user 'users' (raw import) table."""
from .db import connect, logbook_connect, safe_identifier, sqlite_type, user_root, PRIMARY_KEYS, db_path, logbook_db_path
from .config import (SYSTEM_COLUMNS, LOGBOOK_SYSTEM_COLUMNS, load_config, load_logbook_db_config,
                      configurable_columns, ensure_configs)


def sync_columns(conn, table, columns):
    existing = {r[1] for r in conn.execute(f'PRAGMA table_info({safe_identifier(table)})').fetchall()}
    for c in columns:
        col = safe_identifier(c["column"])
        if col == PRIMARY_KEYS.get(table) or col in existing:
            continue
        conn.execute(f'ALTER TABLE "{safe_identifier(table)}" ADD COLUMN "{col}" {sqlite_type(c.get("data_type"))}')


def sync_user_columns(conn, config): sync_columns(conn, "users", config["database"]["columns"])
def sync_logbook_columns(conn, config, username=None): sync_columns(conn, "logbook", load_logbook_db_config(username)["database"]["columns"])


def drop_unused_columns(conn, config):
    configured = {c["column"] for c in config["database"]["columns"]}
    existing = [r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()]
    for col in existing:
        if col not in configured and col != "technical_import_profile" and col not in {c["column"] for c in SYSTEM_COLUMNS}:
            conn.execute(f'ALTER TABLE users DROP COLUMN "{safe_identifier(col)}"')


def drop_unused_logbook_columns(conn, config, username=None):
    configured = {c["column"] for c in load_logbook_db_config(username)["database"]["columns"]}
    existing = [r[1] for r in conn.execute("PRAGMA table_info(logbook)").fetchall()]
    for col in existing:
        if col not in configured and col not in {c["column"] for c in LOGBOOK_SYSTEM_COLUMNS}:
            conn.execute(f'ALTER TABLE logbook DROP COLUMN "{safe_identifier(col)}"')


def ensure_profile_column(conn):
    """Column of A telling which import profile a row came from. Always filled: 'default' for the default import."""
    if "technical_import_profile" not in [r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()]:
        conn.execute("ALTER TABLE users ADD COLUMN technical_import_profile TEXT NOT NULL DEFAULT 'default'")
    else:
        conn.execute("UPDATE users SET technical_import_profile='default' WHERE technical_import_profile IS NULL OR technical_import_profile=''")


def import_rows(source, rows, config, username=None, profile=None):
    """Merge `rows` into the raw database: never replaces or deletes anything (see merge.py)."""
    from .merge import merge_context, plan_merge
    conn = connect(username)
    ensure_profile_column(conn)
    sync_user_columns(conn, config)      # jamais de DROP COLUMN ici : un import n'efface rien (voir delete_category)
    cols = [safe_identifier(c["column"]) for c in configurable_columns(config)]
    quoted = ",".join(chr(34) + c + chr(34) for c in cols)
    cursor = conn.execute(f"SELECT technical_raw_id AS id,{quoted} FROM users ORDER BY technical_raw_id") if cols else None
    names = [d[0] for d in cursor.description] if cursor else []
    existing = [dict(zip(names, row)) for row in cursor.fetchall()] if cursor else []
    inserts, updates, stats = plan_merge(existing, rows, cols, merge_context())
    for row_id, changes in updates:
        sets = ",".join(f'"{c}"=?' for c in changes)
        conn.execute(f"UPDATE users SET {sets}, technical_modification_date=CURRENT_TIMESTAMP WHERE technical_raw_id=?", list(changes.values()) + [row_id])
    if inserts and cols:
        sql = f'INSERT INTO users (technical_import_source,technical_import_profile,{quoted}) VALUES (?,?,{",".join("?" for _ in cols)})'
        for row in inserts:
            conn.execute(sql, [source, profile or "default"] + [row.get(c) for c in cols])
    conn.commit(); conn.close()
    return stats


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
    conn.execute("CREATE TABLE IF NOT EXISTS users (technical_raw_id INTEGER PRIMARY KEY AUTOINCREMENT,technical_import_date TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,technical_modification_date TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,technical_import_source TEXT)")
    conn.commit(); conn.close()               # the data columns are created by an import or a conversion
    lb = logbook_connect(username)
    lb.execute("CREATE TABLE IF NOT EXISTS logbook (technical_work_id INTEGER PRIMARY KEY AUTOINCREMENT,technical_import_date TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,technical_modification_date TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,technical_import_source TEXT,technical_raw_id INTEGER)")
    lb.commit(); lb.close()


def _remove_db_files(path):
    for suffix in ("", "-wal", "-shm", "-journal"):
        try:
            path.with_name(path.name + suffix).unlink()
        except FileNotFoundError:
            pass


def reset_raw_db(username=None):
    """Clear: the raw database file is deleted (columns and content), then recreated empty with the current structure."""
    _remove_db_files(db_path(username))
    init_user_db(username)


def reset_work_db(username=None):
    """Clear: the work database file is deleted (columns and content), then recreated empty with the current structure."""
    _remove_db_files(logbook_db_path(username))
    init_user_db(username)
