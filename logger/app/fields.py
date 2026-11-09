"""Entities are the single source of the columns of the four databases (raw, work, location, aircraft).

Each database is a list of fields chosen among the entities (table dbcols of entities.db, the same for all accounts). The type and the
label always come from the entity, so renaming a label shows everywhere at once; renaming a field is followed by the databases, the
roles and the YAML files (rename_field). The program itself reads the work data through roles (defaults/roles.yml): names that the
program knows, each bound to one field."""
import re
import sqlite3
import time
from pathlib import Path

import yaml

from .db import appdata_root, db_dir, users_root

DBS = {"raw": "Raw DB settings", "work": "Work DB settings", "location": "Location DB settings", "aircraft": "Aircraft DB settings"}
ROLES_FILE = Path(__file__).resolve().parent.parent / "defaults" / "roles.yml"


def _conn():
    from .entities import _conn as base
    conn = base()
    conn.execute("""CREATE TABLE IF NOT EXISTS dbcols (db TEXT NOT NULL, field TEXT NOT NULL, position INTEGER NOT NULL,
        visible INTEGER NOT NULL DEFAULT 1, editable INTEGER NOT NULL DEFAULT 1, nullable INTEGER NOT NULL DEFAULT 1, PRIMARY KEY (db, field))""")
    conn.execute("CREATE TABLE IF NOT EXISTS dbcols_meta (db TEXT PRIMARY KEY)")
    conn.execute("CREATE TABLE IF NOT EXISTS roles (role TEXT PRIMARY KEY, field TEXT NOT NULL)")
    if conn.execute("SELECT COUNT(*) FROM roles").fetchone()[0] == 0:
        for role, field in (yaml.safe_load(ROLES_FILE.read_text(encoding="utf-8")) or {}).items():
            conn.execute("INSERT OR IGNORE INTO roles (role, field) VALUES (?, ?)", (str(role), str(field)))
    conn.commit()
    return conn


def _entities(conn):
    return {r[0]: {"group": r[1], "data_type": r[2], "display_name": r[3]} for r in
            conn.execute("SELECT entity, group_name, data_type, display_name FROM entities ORDER BY position, id")}


def _roles(conn):
    return {r[0]: r[1] for r in conn.execute("SELECT role, field FROM roles ORDER BY rowid")}


# ---------------- roles ----------------

_ROLES = {"at": 0.0, "map": {}}


def invalidate():
    _ROLES["at"] = 0.0


def role_map():
    """{role: field}. Read from the database at most every few seconds (the program asks for it very often)."""
    if time.monotonic() - _ROLES["at"] > 5:
        conn = _conn()
        try:
            _ROLES["map"] = _roles(conn)
        finally:
            conn.close()
        _ROLES["at"] = time.monotonic()
    return dict(_ROLES["map"])


def field_of(role):
    """The field (column of the work data) that the program name `role` is bound to."""
    return role_map().get(role, role)


def save_roles(mapping):
    conn = _conn()
    try:
        known = _entities(conn)
        for role, field in mapping.items():
            if field not in known:
                raise ValueError(f"“{field}” is not an entity (role {role}).")
        for role, field in mapping.items():
            conn.execute("UPDATE roles SET field=? WHERE role=?", (field, role))
        conn.commit()
    finally:
        conn.close()
    invalidate()


def work_rows(conn, query="SELECT * FROM logbook ORDER BY id"):
    """The rows of the work data as dicts: the fields, plus every role name that the program uses (same value)."""
    roles = {r: f for r, f in role_map().items() if "." not in r}
    out = []
    for r in conn.execute(query):
        row = dict(r)
        for role, field in roles.items():
            row.setdefault(role, row.get(field))
        out.append(row)
    return out


# ---------------- structure of the databases ----------------

def required(db, roles=None):
    """Fields that the program reads in this database: they cannot be removed from it."""
    if db not in ("location", "aircraft"):
        return []
    roles = role_map() if roles is None else roles
    return [f for r, f in roles.items() if r.startswith(db + ".")]


def columns(db):
    """[{column, field, display_name, group, data_type, position, visible, editable, nullable}] of a database, in order.
    The first call fills a database that has no structure yet (raw and work: every entity; location, aircraft: the key columns)."""
    if db not in DBS:
        raise KeyError(db)
    conn = _conn()
    try:
        known = _entities(conn)
        if known and conn.execute("SELECT 1 FROM dbcols_meta WHERE db=?", (db,)).fetchone() is None:
            seed = list(known) if db in ("raw", "work") else [f for f in required(db, _roles(conn)) if f in known]
            for i, field in enumerate(seed, 1):
                conn.execute("INSERT OR IGNORE INTO dbcols (db, field, position) VALUES (?, ?, ?)", (db, field, i))
            conn.execute("INSERT OR IGNORE INTO dbcols_meta (db) VALUES (?)", (db,))
            conn.commit()
        rows = conn.execute("SELECT field, position, visible, editable, nullable FROM dbcols WHERE db=? ORDER BY position, field", (db,)).fetchall()
    finally:
        conn.close()
    return [{"column": r[0], "field": r[0], "display_name": known[r[0]]["display_name"], "group": known[r[0]]["group"],
             "data_type": known[r[0]]["data_type"], "position": r[1], "visible": bool(r[2]), "editable": bool(r[3]), "nullable": bool(r[4])}
            for r in rows if r[0] in known]


def save(db, items):
    """Replace the columns of a database by `items` ([{field, visible, editable, nullable}] in the wanted order).
    Returns the fields that were removed."""
    if db not in DBS:
        raise KeyError(db)
    conn = _conn()
    try:
        known = _entities(conn)
        seen, rows = [], []
        for item in items:
            field = str(item.get("field", "")).strip()
            if field not in known:
                raise ValueError(f"“{field}” is not an entity: a column can only be an entity.")
            if field in seen:
                raise ValueError(f"The column “{field}” appears twice.")
            seen.append(field)
            rows.append((db, field, len(seen), int(bool(item.get("visible", True))), int(bool(item.get("editable", True))), int(bool(item.get("nullable", True)))))
        missing = [f for f in required(db, _roles(conn)) if f not in seen]
        if missing:
            raise ValueError("The key columns cannot be removed: " + ", ".join(missing) + ".")
        before = [r[0] for r in conn.execute("SELECT field FROM dbcols WHERE db=?", (db,))]
        conn.execute("DELETE FROM dbcols WHERE db=?", (db,))
        conn.executemany("INSERT INTO dbcols (db, field, position, visible, editable, nullable) VALUES (?,?,?,?,?,?)", rows)
        conn.execute("INSERT OR IGNORE INTO dbcols_meta (db) VALUES (?)", (db,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return sorted(set(before) - set(seen))


def usage(field):
    """Where a field is used: [text, ...] (databases and roles)."""
    conn = _conn()
    try:
        out = [DBS[r[0]] for r in conn.execute("SELECT db FROM dbcols WHERE field=? ORDER BY db", (field,)) if r[0] in DBS]
        out += [f"role {r[0]}" for r in conn.execute("SELECT role FROM roles WHERE field=? ORDER BY role", (field,))]
    finally:
        conn.close()
    return out


# ---------------- renaming a field ----------------

def _yaml_files():
    roots = [appdata_root(), users_root()]
    for root in roots:
        if root.is_dir():
            for path in root.rglob("*.yml"):
                if not any(part.startswith(".") for part in path.relative_to(root).parts):
                    yield path


def rename_field(old, new):
    """The databases, the roles and the YAML files (profiles, layouts...) follow the new name of a field. Returns a short summary."""
    conn = _conn()
    try:
        conn.execute("UPDATE dbcols SET field=? WHERE field=?", (new, old))
        conn.execute("UPDATE roles SET field=? WHERE field=?", (new, old))
        conn.commit()
    finally:
        conn.close()
    invalidate()
    targets = [(db_dir() / "location.db", "locations"), (db_dir() / "aircrafts.db", "aircraft_types")]
    if users_root().is_dir():
        for folder in users_root().iterdir():
            if folder.is_dir() and not folder.name.startswith("."):
                targets += [(folder / f"{folder.name}_data.db", "users"), (folder / f"{folder.name}_logbook.db", "logbook")]
    renamed = 0
    for path, table in targets:
        if not path.is_file():
            continue
        db = sqlite3.connect(path, timeout=15)
        try:
            have = [r[1] for r in db.execute(f"PRAGMA table_info({table})")]
            if old in have and new not in have:
                db.execute(f'ALTER TABLE "{table}" RENAME COLUMN "{old}" TO "{new}"')
                db.commit()
                renamed += 1
        except sqlite3.Error:
            db.rollback()
        finally:
            db.close()
    pattern = re.compile(r"(?<![A-Za-z0-9_])(w_)?" + re.escape(old) + r"(?![A-Za-z0-9_])")
    changed = 0
    for path in _yaml_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        updated = pattern.sub(lambda m: (m.group(1) or "") + new, text)
        if updated != text:
            path.write_text(updated, encoding="utf-8")
            changed += 1
    return f"{renamed} table column(s) and {changed} YAML file(s) updated"
