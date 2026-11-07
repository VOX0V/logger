"""Columns of the location and aircraft databases.

The key columns are fixed (the application reads them); the other columns are entities of the entity list
(Data > Entities) that the administrator adds on the structure page. The order of all the columns is free."""
import re

from .db import location_connect, aircrafts_connect

KINDS = {
    "location": {
        "table": "locations", "group": "location", "connect": location_connect,
        "core": [("location_display", "display", "Display"), ("location_icao", "icao_code", "ICAO code"),
                 ("location_iata", "iata_code", "IATA code"), ("location_reference", "company_code", "Company code"),
                 ("location_name", "full_name", "Name"), ("location_country", "country", "Country"),
                 ("location_latitude", "latitude", "Latitude"), ("location_longitude", "longitude", "Longitude")],
        "excluded": ("location_departure_", "location_arrival_"),     # these entities describe a flight, not a location
    },
    "aircraft": {
        "table": "aircraft_types", "group": "aircraft", "connect": aircrafts_connect,
        "core": [("aircraft_display", "display", "Display"), ("aircraft_designator", "designator", "Designator"),
                 ("aircraft_maker", "maker", "Maker"), ("aircraft_model", "model", "Model"),
                 ("aircraft_category", "category", "Category"), ("aircraft_engine", "engines", "Engines"),
                 ("aircraft_engine_type", "engine_type", "Engine type"), ("aircraft_crew", "crew", "Crew"),
                 ("aircraft_landing_gear", "landing_gear", "Landing gear"), ("aircraft_mtow_lbs", "mtow_lb", "MTOW (lb)"),
                 ("aircraft_mtow_kg", "mtow_kg", "MTOW (kg)")],
        "excluded": ("aircraft_registration", "aircraft_type"),       # these entities describe a flight, not a type
    },
}
_NAME = re.compile(r"[a-z0-9_]+")


def _sql_type(data_type):
    return {"integer": "INTEGER", "boolean": "INTEGER", "decimal": "REAL"}.get(data_type, "TEXT")


def _entities():
    from .importer import FileImportError
    from .import_profiles import load_entities
    try:
        return load_entities()
    except FileImportError:
        return {}


def eligible(kind):
    """{entity: {...}} of the entities that may be added as a column of this table."""
    spec = KINDS[kind]
    core = {c[0] for c in spec["core"]}
    return {e: v for e, v in _entities().items()
            if v["group"] == spec["group"] and e.startswith(spec["group"] + "_") and e not in core
            and not e.startswith(spec["excluded"]) and _NAME.fullmatch(e)}


def _ensure(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS structure (entity TEXT PRIMARY KEY, position INTEGER NOT NULL)")


def columns(kind):
    """The columns in the order of the pages: [{entity, field, title, core, data_type}] (field = column of the table)."""
    spec = KINDS[kind]
    conn = spec["connect"]()
    try:
        _ensure(conn)
        order = {r[0]: r[1] for r in conn.execute("SELECT entity, position FROM structure")}
        have = {r[1] for r in conn.execute(f"PRAGMA table_info({spec['table']})")}
        conn.commit()
    finally:
        conn.close()
    items = [{"entity": e, "field": f, "title": t, "core": True, "data_type": "text", "pos": order.get(e, 10000 + i)}
             for i, (e, f, t) in enumerate(spec["core"])]
    ok = eligible(kind)
    for entity, pos in order.items():
        if entity in ok and entity in have:
            items.append({"entity": entity, "field": entity, "title": ok[entity]["display_name"], "core": False,
                          "data_type": ok[entity]["data_type"], "pos": pos})
    items.sort(key=lambda c: c["pos"])
    return items


def extras(kind):
    """The added columns, in order: [{field, title, data_type}]."""
    return [c for c in columns(kind) if not c["core"]]


def save_structure(kind, ordered):
    """`ordered`: the entities in the wanted order. Every key column must be there; the others must be eligible entities.
    Returns the added columns that were removed (their column and data are deleted)."""
    spec = KINDS[kind]
    core = {c[0] for c in spec["core"]}
    ok = eligible(kind)
    if len(set(ordered)) != len(ordered):
        raise ValueError("A column appears twice.")
    missing = core - set(ordered)
    if missing:
        raise ValueError("The key columns cannot be removed: " + ", ".join(sorted(missing)) + ".")
    bad = [e for e in ordered if e not in core and e not in ok]
    if bad:
        raise ValueError(f"“{bad[0]}” is not an entity that can be a column of this table.")
    table = spec["table"]
    wanted = [e for e in ordered if e not in core]
    conn = spec["connect"]()
    try:
        _ensure(conn)
        have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        for e in wanted:
            if e not in have:
                conn.execute(f'ALTER TABLE {table} ADD COLUMN "{e}" {_sql_type(ok[e]["data_type"])}')
        previous = {r[0] for r in conn.execute("SELECT entity FROM structure")} - core
        removed = sorted(e for e in previous if e not in wanted and e in have and _NAME.fullmatch(e))
        for e in removed:
            conn.execute(f'ALTER TABLE {table} DROP COLUMN "{e}"')
        conn.execute("DELETE FROM structure")
        conn.executemany("INSERT INTO structure (entity, position) VALUES (?, ?)", [(e, i) for i, e in enumerate(ordered, 1)])
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return removed


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
