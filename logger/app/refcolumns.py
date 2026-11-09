"""Columns of the location and aircraft databases.

Like every database they are made of entities (fields.py). The key columns are the entities bound to the roles location.* /
aircraft.* (defaults/roles.yml): the application reads them under a technical name of the table (icao_code, designator...) and
they cannot be removed. The other columns are plain entities, stored under the name of the entity."""
import re

from . import fields
from .db import location_connect, aircrafts_connect

KINDS = {
    "location": {"table": "locations", "connect": location_connect},
    "aircraft": {"table": "aircraft_types", "connect": aircrafts_connect},
}
_NAME = re.compile(r"[a-z0-9_]+")


def _sql_type(data_type):
    return {"integer": "INTEGER", "boolean": "INTEGER", "decimal": "REAL"}.get(data_type, "TEXT")


def _core(kind):
    """{entity: technical column of the table} of the key columns."""
    prefix = kind + "."
    return {f: r[len(prefix):] for r, f in fields.role_map().items() if r.startswith(prefix)}


def columns(kind):
    """The columns in the order of the settings: [{entity, field, title, core, data_type, pos, visible, editable}]
    (field = column of the table, title = label of the entity)."""
    core = _core(kind)
    items = []
    for c in fields.columns(kind):
        internal = core.get(c["column"])
        items.append({"entity": c["column"], "field": internal or c["column"], "title": c["display_name"], "core": internal is not None,
                      "data_type": "text" if internal else c["data_type"], "pos": c["position"], "visible": c["visible"], "editable": c["editable"]})
    return items


def extras(kind):
    """The columns that are not key columns, in order: [{field, title, data_type}]."""
    return [c for c in columns(kind) if not c["core"]]


def apply(kind):
    """Make the table follow the settings: the added columns are created, the removed ones are dropped (with their data)."""
    spec = KINDS[kind]
    table = spec["table"]
    wanted = {c["field"] for c in extras(kind)}
    types = {c["field"]: c["data_type"] for c in extras(kind)}
    known = set(_all_entities())
    conn = spec["connect"]()
    try:
        have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        for field in sorted(wanted - have):
            if _NAME.fullmatch(field):
                conn.execute(f'ALTER TABLE {table} ADD COLUMN "{field}" {_sql_type(types[field])}')
        for field in sorted((have & known) - wanted - set(_core(kind))):
            if _NAME.fullmatch(field):
                conn.execute(f'ALTER TABLE {table} DROP COLUMN "{field}"')
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _all_entities():
    conn = fields._conn()
    try:
        return fields._entities(conn)
    finally:
        conn.close()


def extras_values(kind, form):
    """{column: value} of the added columns found in `form` (a form or a row); numbers are checked."""
    out = {}
    for c in extras(kind):
        if c["field"] not in form:
            continue
        raw = form.get(c["field"])
        value = None if raw is None or str(raw).strip() == "" else str(raw).strip()
        if value is not None and c["data_type"] in ("integer", "decimal"):
            try:
                number = float(value.replace(",", "."))
            except ValueError:
                raise ValueError(f"{c['title']} must be a number.")
            value = int(number) if c["data_type"] == "integer" else number
        out[c["field"]] = value
    return out
