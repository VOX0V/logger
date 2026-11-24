"""World map: every location of the work data and the legs flown between them (drawn as great circles in the browser)."""
from flask import Blueprint, jsonify, render_template

from .auth import login_required
from .db import logbook_connect

worldmap_bp = Blueprint("worldmap", __name__, url_prefix="/map")

NEEDED = ("departure_code", "arrival_code", "departure_latitude", "departure_longitude",
          "arrival_latitude", "arrival_longitude")


@worldmap_bp.route("")
@login_required
def index():
    return render_template("worldmap.html")


@worldmap_bp.route("/data")
@login_required
def data():
    """Locations {code: name, lat, lon} and legs [from, to, year, count] grouped by pair of locations and year."""
    from . import fields as efields
    f = {r: efields.field_of(r) for r in list(NEEDED) + ["year", "departure_name", "arrival_name"]}
    conn = logbook_connect()
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(logbook)")}
        missing = [r for r in NEEDED if f[r] not in cols]
        if missing:
            return jsonify(error="The work data has no column: " + ", ".join(f[r] for r in missing) + " (see the global profiles).")
        year = f'"{f["year"]}"' if f["year"] in cols else "NULL"
        dname = f'"{f["departure_name"]}"' if f["departure_name"] in cols else "''"
        aname = f'"{f["arrival_name"]}"' if f["arrival_name"] in cols else "''"
        dc, dla, dlo = (f'"{f[r]}"' for r in ("departure_code", "departure_latitude", "departure_longitude"))
        ac, ala, alo = (f'"{f[r]}"' for r in ("arrival_code", "arrival_latitude", "arrival_longitude"))
        rows = conn.execute(
            f"SELECT {dc}, {dname}, {dla}, {dlo}, {ac}, {aname}, {ala}, {alo}, {year}, COUNT(*) FROM logbook "
            f"WHERE {dc} IS NOT NULL AND {ac} IS NOT NULL AND {dc} != '' AND {ac} != '' "
            f"AND {dla} IS NOT NULL AND {dlo} IS NOT NULL AND {ala} IS NOT NULL AND {alo} IS NOT NULL "
            "GROUP BY 1, 2, 3, 4, 5, 6, 7, 8, 9").fetchall()
    finally:
        conn.close()
    locations, legs = {}, []
    for dc, dn, dla, dlo, ac, an, ala, alo, yr, n in rows:
        try:
            locations.setdefault(str(dc), {"name": str(dn or ""), "lat": float(dla), "lon": float(dlo)})
            locations.setdefault(str(ac), {"name": str(an or ""), "lat": float(ala), "lon": float(alo)})
        except (TypeError, ValueError):
            continue
        try:
            yr = int(yr) if yr not in (None, "") else None
        except (TypeError, ValueError):
            yr = None
        legs.append([str(dc), str(ac), yr, int(n)])
    return jsonify(locations=locations, legs=legs)
