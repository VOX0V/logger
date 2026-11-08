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
    conn = logbook_connect()
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(logbook)")}
        missing = [c for c in NEEDED if c not in cols]
        if missing:
            return jsonify(error="The work data has no column: " + ", ".join(missing) + " (see the global profiles).")
        year = "year" if "year" in cols else "NULL"
        dname = "departure_name" if "departure_name" in cols else "''"
        aname = "arrival_name" if "arrival_name" in cols else "''"
        rows = conn.execute(
            f"SELECT departure_code, {dname}, departure_latitude, departure_longitude, "
            f"arrival_code, {aname}, arrival_latitude, arrival_longitude, {year}, COUNT(*) FROM logbook "
            "WHERE departure_code IS NOT NULL AND arrival_code IS NOT NULL AND departure_code != '' AND arrival_code != '' "
            "AND departure_latitude IS NOT NULL AND departure_longitude IS NOT NULL "
            "AND arrival_latitude IS NOT NULL AND arrival_longitude IS NOT NULL "
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
