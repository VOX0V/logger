"""Conversion of database A (users table) into database B (logbook table)
by applying the rules the user has ticked, in catalog order.

For each B column the first rule that produces a non-empty value wins."""
from collections import Counter

from ..db import connect, logbook_connect, safe_identifier
from ..config import load_logbook_db_config, configurable_columns
from ..models import sync_logbook_columns, drop_unused_logbook_columns, ensure_profile_column
from .profiles import profile_rules
from .catalog import load_settings, pilot_name, rule_missing_columns
from .transforms import FUNCTIONS, Skip, SkipRow, Problem, blank


def refresh_logbook(config, username=None):
    """Rebuild the logbook table. Returns {"rows": int, "warnings": [str]}."""
    lcfg = load_logbook_db_config(username)
    b_columns = [c["column"] for c in lcfg["database"]["columns"] if c.get("group") != "system"]
    a_columns = [c["column"] for c in configurable_columns(config)]
    settings = load_settings()
    settings["pilot_name"] = pilot_name(username)
    warnings = Counter()

    conn = logbook_connect(username)
    uc = connect(username)
    rule_sets = {}

    def checked(rules, profile_id):
        keep = []
        for rule in rules:
            missing = rule_missing_columns(rule, a_columns, b_columns)
            if missing:
                warnings[f"Rule '{rule['name']}' ({profile_id}) skipped: missing column(s) ({', '.join(missing)})"] += 0
            else:
                keep.append(rule)
        return keep

    def rules_for(profile_id):
        """Conversion profile converter/<id>_convert.yml of the row's import profile; the 'default'
        profile (plain copy) when that profile has no conversion file."""
        if profile_id not in rule_sets:
            found = profile_rules(profile_id)
            if found is None and profile_id != "default":
                warnings[f"No conversion profile for import profile '{profile_id}': default profile used"] += 0
                found = profile_rules("default")
            rule_sets[profile_id] = checked(found or [], profile_id)
        return rule_sets[profile_id]

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
            out = {}
            skipped = False
            for rule in rules_for(source.get("import_profile") or "default"):
                try:
                    result = FUNCTIONS[rule["transform"]](source, rule, settings)
                except SkipRow:
                    skipped = True
                    break
                except Skip:
                    continue
                except Problem as exc:
                    warnings[str(exc)] += 1
                    continue
                for column, value in result.items():
                    if not blank(value) and blank(out.get(column)):
                        out[column] = value
            if skipped:
                ignored += 1
                continue
            built.append((source, out))
        # chronological order whatever the import order (rows without a date last)
        built.sort(key=lambda t: (not t[1].get("date"), str(t[1].get("date") or ""),
                                  str(t[0].get("departure_local") or ""), t[0]["id"]))
        if names:
            for source, out in built:
                conn.execute(
                    f'INSERT INTO logbook (import_source,{",".join(chr(34) + n + chr(34) for n in names)}) VALUES (?,{",".join("?" for _ in names)})',
                    [source["import_source"]] + [out.get(n) for n in names])
        conn.commit()
    finally:
        uc.close(); conn.close()

    if ignored:
        warnings["Rows skipped (not at the controls)"] += ignored
    messages = [msg if count == 0 else f"{msg} — {count} row(s)" for msg, count in sorted(warnings.items())]
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
