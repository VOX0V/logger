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


def build_logbook(config, username=None, sync_schema=True):
    """Convert every row of the raw database in memory; the work rows are not touched.
    The tables' columns are brought up to date first (as a refresh always did).
    Returns {"names": [work columns], "built": [(raw row dict, converted dict)] in chronological order,
    "ignored": int, "messages": [str]}."""
    spec = workdb.load_spec()                      # an invalid file raises here: nothing is touched
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
        if sync_schema:                            # the review does not touch the tables: the columns are created when the conversion is validated
            conn.execute("CREATE TABLE IF NOT EXISTS logbook (technical_work_id INTEGER PRIMARY KEY AUTOINCREMENT,technical_import_date TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,technical_modification_date TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,technical_import_source TEXT,technical_raw_id INTEGER)")
            sync_logbook_columns(conn, config, username)
            drop_unused_logbook_columns(conn, config, username)
            conn.commit()
        a_columns = [c for c in a_columns if c in {r[1] for r in uc.execute("PRAGMA table_info(users)")}]
        select = ",".join(["technical_raw_id AS id", "technical_import_source AS import_source", "technical_import_profile AS import_profile"] + [f'"{safe_identifier(c)}"' for c in a_columns])
        rows = uc.execute(f"SELECT {select} FROM users ORDER BY technical_raw_id").fetchall()
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
    finally:
        uc.close(); conn.close()

    if ignored:
        warnings["Rows skipped (skip_rows of the profiles)"] += ignored
    messages = [f"{msg} — {count} row(s)" for msg, count in sorted(warnings.items())]
    return {"names": names, "built": built, "ignored": ignored, "messages": messages}


def insert_work_row(conn, names, values, import_source=None, raw_id=None, created_at=None, updated_at=None):
    """Insert one row in the logbook table (values: dict column -> value)."""
    cols = ["technical_import_source", "technical_raw_id"] + [n for n, v in (("technical_import_date", created_at), ("technical_modification_date", updated_at)) if v] + list(names)
    params = [import_source, raw_id] + [v for v in (created_at, updated_at) if v] + [values.get(n) for n in names]
    conn.execute(f'INSERT INTO logbook ({",".join(chr(34) + c + chr(34) for c in cols)}) VALUES ({",".join("?" for _ in cols)})', params)


def refresh_logbook(config, username=None):
    """Rebuild the logbook table from the conversion rules. Returns {"rows": int, "warnings": [str]}.
    Direct rebuild without review (the web pages go through the review page: see staging.py)."""
    result = build_logbook(config, username)
    conn = logbook_connect(username)
    try:
        conn.execute("DELETE FROM logbook")
        if result["names"]:
            for source, out in result["built"]:
                insert_work_row(conn, result["names"], out, source["import_source"], source["id"])
        conn.commit()
    finally:
        conn.close()
    return {"rows": len(result["built"]), "warnings": result["messages"]}


def list_logbook_rows(username=None):
    from .. import fields as efields
    conn = logbook_connect(username)
    try:
        return efields.work_rows(conn)
    finally:
        conn.close()


def update_logbook_date_part(row_id, part, value, username=None):
    """Change l'année, le mois ou le jour d'une ligne et recompose la date ISO (refuse une date impossible)."""
    from datetime import date
    from .. import fields as efields
    if part not in ("year", "month", "day"): raise ValueError("Invalid date part.")
    conn = logbook_connect(username)
    try:
        date_field = efields.field_of("date")
        row = conn.execute(f'SELECT "{date_field}" AS d FROM logbook WHERE technical_work_id=?', (row_id,)).fetchone()
        if not row: raise ValueError("Row not found.")
        try: y, m, d = (int(x) for x in str(row["d"] or "")[:10].split("-"))
        except ValueError: raise ValueError("This row has no date to modify.")
        try: n = int(str(value).strip())
        except ValueError: raise ValueError("Numeric value expected.")
        y, m, d = (n, m, d) if part == "year" else (y, n, d) if part == "month" else (y, m, n)
        try: new = date(y, m, d).isoformat()
        except ValueError: raise ValueError(f"Impossible date: {y:04d}-{m:02d}-{d:02d}.")
        conn.execute(f'UPDATE logbook SET "{date_field}"=?, technical_modification_date=CURRENT_TIMESTAMP WHERE technical_work_id=?', (new, row_id))
        conn.commit()
    finally:
        conn.close()


def update_logbook_cell(row_id, column, value, username=None):
    safe_identifier(column)
    conn = logbook_connect(username)
    conn.execute(f'UPDATE logbook SET "{column}"=?, technical_modification_date=CURRENT_TIMESTAMP WHERE technical_work_id=?', (value, row_id))
    conn.commit(); conn.close()
