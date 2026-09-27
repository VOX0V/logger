"""Conversion of the raw 'users' table into the derived 'logbook' table."""
from .db import connect, logbook_connect, safe_identifier
from .config import load_logbook_db_config, configurable_columns
from .models import sync_logbook_columns, drop_unused_logbook_columns


def _row_value(row, path):
    key = path.split(".", 1)[1] if "." in path else path
    return row[key] if key in row.keys() else None


def transform_logbook_value(column, row):
    source = column.get("source", []) or []
    if column.get("transformation") == "date":
        for rule in source:
            if isinstance(rule, dict):
                typ = rule.get("type"); vals = [_row_value(row, s) for s in rule.get("source", [])]
                if typ == "date_parts" and len(vals) >= 3 and all(v not in (None, "") for v in vals[:3]):
                    try: return f"{int(vals[0]):04d}-{int(vals[1]):02d}-{int(vals[2]):02d}"
                    except (TypeError, ValueError): pass
                if typ == "datetime" and vals and vals[0] not in (None, ""):
                    text = str(vals[0]); return text[:10] if len(text) >= 10 else None
        vals = [_row_value(row, s) for s in source if isinstance(s, str)]
        if len(vals) >= 3 and all(v not in (None, "") for v in vals[:3]):
            try: return f"{int(vals[0]):04d}-{int(vals[1]):02d}-{int(vals[2]):02d}"
            except (TypeError, ValueError): pass
        return None
    vals = [_row_value(row, s) for s in source if isinstance(s, str)]
    return vals[0] if len(vals) == 1 else (" ".join(str(v) for v in vals if v not in (None, "")) or None)


def refresh_logbook(config, username=None):
    lcfg = load_logbook_db_config(username)
    conn = logbook_connect(username)
    uc = connect(username)
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS logbook (id INTEGER PRIMARY KEY AUTOINCREMENT,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,import_source TEXT)")
        sync_logbook_columns(conn, config, username)
        drop_unused_logbook_columns(conn, config, username)
        ucols = [c["column"] for c in configurable_columns(config)]
        select = ",".join(["id", "import_source"] + [f'"{safe_identifier(c)}"' for c in ucols])
        rows = uc.execute(f"SELECT {select} FROM users ORDER BY id").fetchall()
        cols = lcfg["database"]["columns"][4:]
        names = [safe_identifier(c["column"]) for c in cols]
        conn.execute("DELETE FROM logbook")
        for row in rows:
            values = [transform_logbook_value(c, row) for c in cols]
            if names:
                conn.execute(f'INSERT INTO logbook (import_source,{",".join(chr(34) + n + chr(34) for n in names)}) VALUES (?,{",".join("?" for _ in names)})', [row["import_source"]] + values)
        conn.commit()
    finally:
        uc.close(); conn.close()


def list_logbook_rows(username=None):
    conn = logbook_connect(username)
    rows = conn.execute("SELECT * FROM logbook ORDER BY id").fetchall()
    conn.close()
    return rows


def update_logbook_cell(row_id, column, value, username=None):
    safe_identifier(column)
    conn = logbook_connect(username)
    conn.execute(f'UPDATE logbook SET "{column}"=?, updated_at=CURRENT_TIMESTAMP WHERE id=?', (value, row_id))
    conn.commit(); conn.close()
