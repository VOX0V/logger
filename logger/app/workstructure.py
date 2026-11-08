"""Structure of the work data, the same for all accounts: which columns exist, their type, their order and whether they are
visible / editable / nullable. It is edited on the Data > Work DB settings page; the conversion rules (the global profiles and the
files of the import profiles) only say how each column gets its value."""
from pathlib import Path

import yaml

SEED = Path(__file__).resolve().parent.parent / "defaults" / "work_structure.yml"


def _conn():
    from .entities import _conn as entities_conn          # the structure lives in the entities database
    conn = entities_conn()
    conn.execute("""CREATE TABLE IF NOT EXISTS work_columns (
        name TEXT PRIMARY KEY, position INTEGER NOT NULL, data_type TEXT NOT NULL DEFAULT 'text', display_name TEXT NOT NULL DEFAULT '',
        visible INTEGER NOT NULL DEFAULT 1, editable INTEGER NOT NULL DEFAULT 1, nullable INTEGER NOT NULL DEFAULT 1)""")
    conn.execute("CREATE TABLE IF NOT EXISTS work_meta (key TEXT PRIMARY KEY, value TEXT)")
    return conn


def _seed_items():
    """[(name, type, display_name)] of the first structure: the former work_db.yml of the account folder when it still has the old format (it keeps what the
    administrator had), otherwise the shipped defaults/work_structure.yml."""
    from . import workdb
    legacy = workdb.edited_path()
    for path in (() if legacy is None else (legacy, legacy.with_name(legacy.name + ".old"))):
        try:
            if path.is_file():
                meta = workdb.parse_rules(yaml.safe_load(path.read_text(encoding="utf-8")))["meta"]
                if any(c["number"] is not None for c in meta):
                    return [(c["column"], c["type"], c["display_name"]) for c in meta]
        except (OSError, yaml.YAMLError, workdb.SpecError):
            pass
    data = yaml.safe_load(SEED.read_text(encoding="utf-8")) or {}
    return [(c["column"], c.get("type", "text"), c.get("display_name") or c["column"].replace("_", " ")) for c in data.get("columns", [])]


def columns():
    """[{column, display_name, position, data_type, visible, editable, nullable}] in order. The first call fills the table."""
    conn = _conn()
    try:
        if conn.execute("SELECT value FROM work_meta WHERE key='seeded'").fetchone() is None:
            for i, (name, data_type, display) in enumerate(_seed_items(), 1):
                conn.execute("INSERT OR IGNORE INTO work_columns (name, position, data_type, display_name) VALUES (?,?,?,?)",
                             (name, i, data_type, display))
            conn.execute("INSERT OR IGNORE INTO work_meta (key, value) VALUES ('seeded', '1')")
            conn.commit()
        rows = conn.execute("SELECT name, position, data_type, display_name, visible, editable, nullable FROM work_columns ORDER BY position, name").fetchall()
    finally:
        conn.close()
    return [{"column": r[0], "position": r[1], "data_type": r[2], "display_name": r[3],
             "visible": bool(r[4]), "editable": bool(r[5]), "nullable": bool(r[6])} for r in rows]


def save(items):
    """Replace the structure by `items` (a list of dicts, in the wanted order). Returns the names of the columns that were removed."""
    from .workdb import DATA_TYPES, NAME, RESERVED
    if not isinstance(items, list):
        raise ValueError("The columns are not readable.")
    clean, seen = [], set()
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("The columns are not readable.")
        name = str(item.get("column", "")).strip()
        if not NAME.fullmatch(name) or name in RESERVED:
            raise ValueError(f"“{name}” is not a valid column name (letters, digits and underscores; not reserved).")
        if name in seen:
            raise ValueError(f"The column “{name}” appears twice.")
        seen.add(name)
        data_type = str(item.get("data_type", "text")).lower()
        if data_type not in DATA_TYPES:
            raise ValueError(f"{name}: the type must be one of {', '.join(sorted(DATA_TYPES))}.")
        clean.append((name, data_type, str(item.get("display_name") or "").strip() or name.replace("_", " "),
                      int(bool(item.get("visible", True))), int(bool(item.get("editable", True))), int(bool(item.get("nullable", True)))))
    before = {c["column"] for c in columns()}
    conn = _conn()
    try:
        conn.execute("DELETE FROM work_columns")
        for i, (name, data_type, display, visible, editable, nullable) in enumerate(clean, 1):
            conn.execute("INSERT INTO work_columns (name, position, data_type, display_name, visible, editable, nullable) VALUES (?,?,?,?,?,?,?)",
                         (name, i, data_type, display, visible, editable, nullable))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return sorted(before - seen)
