"""Conversion of database A (users table) into database B (logbook table)
by applying the rules the user has ticked, in catalog order.

For each B column the first rule that produces a non-empty value wins."""
from collections import Counter

from ..db import connect, logbook_connect, safe_identifier
from ..config import load_logbook_db_config, configurable_columns
from ..models import sync_logbook_columns, drop_unused_logbook_columns
from .catalog import active_rules, load_settings, rule_missing_columns
from .transforms import FUNCTIONS, Skip, Problem, blank


def refresh_logbook(config, username=None):
    """Rebuild the logbook table. Returns {"rows": int, "warnings": [str]}."""
    lcfg = load_logbook_db_config(username)
    b_columns = [c["column"] for c in lcfg["database"]["columns"] if c.get("group") != "system"]
    a_columns = [c["column"] for c in configurable_columns(config)]
    settings = load_settings()
    warnings = Counter()

    usable = []
    for rule in active_rules(username):
        missing = rule_missing_columns(rule, a_columns, b_columns)
        if missing:
            warnings[f"Règle « {rule['name']} » ignorée : colonne(s) manquante(s) ({', '.join(missing)})"] += 0
        else:
            usable.append(rule)

    conn = logbook_connect(username)
    uc = connect(username)
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS logbook (id INTEGER PRIMARY KEY AUTOINCREMENT,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,import_source TEXT)")
        sync_logbook_columns(conn, config, username)
        drop_unused_logbook_columns(conn, config, username)
        select = ",".join(["id", "import_source"] + [f'"{safe_identifier(c)}"' for c in a_columns])
        rows = uc.execute(f"SELECT {select} FROM users ORDER BY id").fetchall()
        conn.execute("DELETE FROM logbook")
        names = [safe_identifier(n) for n in b_columns]
        for row in rows:
            source = dict(row)
            out = {}
            for rule in usable:
                try:
                    result = FUNCTIONS[rule["transform"]](source, rule, settings)
                except Skip:
                    continue
                except Problem as exc:
                    warnings[str(exc)] += 1
                    continue
                for column, value in result.items():
                    if not blank(value) and blank(out.get(column)):
                        out[column] = value
            if names:
                conn.execute(
                    f'INSERT INTO logbook (import_source,{",".join(chr(34) + n + chr(34) for n in names)}) VALUES (?,{",".join("?" for _ in names)})',
                    [source["import_source"]] + [out.get(n) for n in names])
        conn.commit()
    finally:
        uc.close(); conn.close()

    messages = [msg if count == 0 else f"{msg} — {count} ligne(s)" for msg, count in sorted(warnings.items())]
    return {"rows": len(rows), "warnings": messages}


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
