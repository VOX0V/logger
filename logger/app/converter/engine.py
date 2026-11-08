"""Conversion of database A (users table) into database B (logbook table).

Since 0.3.18 the columns of B and the way each value is obtained are defined by one YAML file,
the global profiles and the conversion profiles (see app/workdb.py): nothing about the columns is written in the code any more."""
from collections import Counter

from ..db import connect, logbook_connect, safe_identifier
from ..config import load_logbook_db_config, configurable_columns
from ..models import sync_logbook_columns, drop_unused_logbook_columns, ensure_profile_column
from .. import workdb
from .catalog import pilot_name
from .profiles import profile_rules  # noqa: F401  (no longer used here; the tests still patch it)


def refresh_logbook(config, username=None):
    """Rebuild the logbook table from the conversion rules. Returns {"rows": int, "warnings": [str]}."""
    spec = workdb.load_spec()                      # an invalid file raises here: nothing is touched
    workdb.apply_to_user(username)                 # the configured columns follow the file
    b_columns = [c["column"] for c in load_logbook_db_config(username)["database"]["columns"] if not c.get("system")]
    a_columns = [c["column"] for c in configurable_columns(config)]
    pilot = pilot_name(username)
    warnings = Counter()

    def warn(message):
        warnings[message] += 1

    conn = logbook_connect(username)
    uc = connect(username)
    try:
        ensure_profile_column(uc)
        uc.commit()
        conn.execute("CREATE TABLE IF NOT EXISTS logbook (id INTEGER PRIMARY KEY AUTOINCREMENT,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,import_source TEXT)")
        sync_logbook_columns(conn, config, username)
        drop_unused_logbook_columns(conn, config, username)
        select = ",".join(["id", "import_source", "import_profile"] + [f'"{safe_identifier(c)}"' for c in a_columns])
        rows = uc.execute(f"SELECT {select} FROM users ORDER BY id").fetchall()
        conn.execute("DELETE FROM logbook")
        names = [safe_identifier(n) for n in b_columns]
        ignored = 0
        built = []
        for row in rows:
            source = dict(row)
            out = workdb.convert_row(spec, source, pilot, warn)
            if out is None:
                ignored += 1
                continue
            built.append((source, out))
        # chronological order whatever the import order (rows without a date last)
        built.sort(key=lambda t: (t[1].get("year") is None, t[1].get("year") or 0, t[1].get("month") or 0,
                                  t[1].get("day") or 0, t[0]["id"]))
        if names:
            for source, out in built:
                conn.execute(
                    f'INSERT INTO logbook (import_source,{",".join(chr(34) + n + chr(34) for n in names)}) VALUES (?,{",".join("?" for _ in names)})',
                    [source["import_source"]] + [out.get(n) for n in names])
        conn.commit()
    finally:
        uc.close(); conn.close()

    if ignored:
        warnings["Rows skipped (skip_rows of the profiles)"] += ignored
    messages = [f"{msg} — {count} row(s)" for msg, count in sorted(warnings.items())]
    return {"rows": len(rows) - ignored, "warnings": messages}


def list_logbook_rows(username=None):
    conn = logbook_connect(username)
    rows = conn.execute("SELECT * FROM logbook ORDER BY id").fetchall()
    conn.close()
    return rows


def update_logbook_date_part(row_id, part, value, username=None):
    """Change l'année, le mois ou le jour d'une ligne et recompose la date ISO (refuse une date impossible)."""
    from datetime import date
    if part not in ("year", "month", "day"): raise ValueError("Invalid date part.")
    conn = logbook_connect(username)
    try:
        row = conn.execute('SELECT "date" FROM logbook WHERE id=?', (row_id,)).fetchone()
        if not row: raise ValueError("Row not found.")
        try: y, m, d = (int(x) for x in str(row["date"] or "")[:10].split("-"))
        except ValueError: raise ValueError("This row has no date to modify.")
        try: n = int(str(value).strip())
        except ValueError: raise ValueError("Numeric value expected.")
        y, m, d = (n, m, d) if part == "year" else (y, n, d) if part == "month" else (y, m, n)
        try: new = date(y, m, d).isoformat()
        except ValueError: raise ValueError(f"Impossible date: {y:04d}-{m:02d}-{d:02d}.")
        conn.execute('UPDATE logbook SET "date"=?, updated_at=CURRENT_TIMESTAMP WHERE id=?', (new, row_id))
        conn.commit()
    finally:
        conn.close()


def update_logbook_cell(row_id, column, value, username=None):
    safe_identifier(column)
    conn = logbook_connect(username)
    conn.execute(f'UPDATE logbook SET "{column}"=?, updated_at=CURRENT_TIMESTAMP WHERE id=?', (value, row_id))
    conn.commit(); conn.close()
