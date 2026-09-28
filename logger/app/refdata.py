"""Shared reference databases: airports (airport.db) and aircraft (aircrafts.db)."""
from pathlib import Path
from flask import current_app
from openpyxl import load_workbook
from .db import airport_connect, aircrafts_connect

ENGINES = ("single", "multi")


def _clean(value):
    text = "" if value is None else str(value).strip()
    return text or None


def _float(value, label, lo, hi, required=True):
    if value in (None, ""):
        if required:
            raise ValueError(f"{label} obligatoire.")
        return None
    try:
        number = float(str(value).replace(",", "."))
    except ValueError:
        raise ValueError(f"{label} invalide.")
    if not lo <= number <= hi:
        raise ValueError(f"{label} hors limites ({lo} à {hi}).")
    return number


# ---------------- airports ----------------

def init_airport_db():
    conn = airport_connect()
    conn.execute("""CREATE TABLE IF NOT EXISTS airports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        icao_code TEXT UNIQUE,
        iata_code TEXT UNIQUE,
        full_name TEXT,
        country TEXT,
        latitude REAL NOT NULL,
        longitude REAL NOT NULL,
        elevation REAL,
        timezone TEXT,
        notes TEXT
    )""")
    empty = conn.execute("SELECT COUNT(*) FROM airports").fetchone()[0] == 0
    conn.commit(); conn.close()
    if empty:
        _import_default_airports()


def _import_default_airports():
    source = Path(current_app.root_path).parent / "defaults" / "airports.xlsx"
    if not source.exists():
        return
    wb = load_workbook(source, read_only=True, data_only=True)
    ws = wb["airports"] if "airports" in wb.sheetnames else wb.active
    rows = list(ws.iter_rows(values_only=True))
    wb.close()
    if not rows:
        return
    header = [str(h or "").strip() for h in rows[0]]
    conn = airport_connect()
    for row in rows[1:]:
        d = dict(zip(header, row))
        try:
            lat = _float(d.get("latitude"), "Latitude", -90, 90)
            lon = _float(d.get("longitude"), "Longitude", -180, 180)
        except ValueError:
            continue
        icao, iata = _clean(d.get("icao_code")), _clean(d.get("iata_code"))
        if not (icao or iata):
            continue
        conn.execute(
            "INSERT OR IGNORE INTO airports (icao_code, iata_code, full_name, country, latitude, longitude, elevation, timezone, notes) VALUES (?,?,?,?,?,?,?,?,?)",
            (icao.upper() if icao else None, iata.upper() if iata else None, _clean(d.get("full_name")), _clean(d.get("country")),
             lat, lon, _float(d.get("elevation"), "Altitude", -1000, 20000, required=False), _clean(d.get("timezone")), _clean(d.get("notes"))))
    conn.commit(); conn.close()


def find_airport(code):
    """Look an airport up by IATA code first, then ICAO. Returns a Row or None."""
    code = (code or "").strip().upper()
    if not code:
        return None
    conn = airport_connect()
    row = conn.execute("SELECT * FROM airports WHERE iata_code=?", (code,)).fetchone() \
        or conn.execute("SELECT * FROM airports WHERE icao_code=?", (code,)).fetchone()
    conn.close()
    return row


def list_airports():
    conn = airport_connect()
    rows = conn.execute("SELECT * FROM airports ORDER BY COALESCE(icao_code, iata_code)").fetchall()
    conn.close(); return rows


def get_airport(airport_id):
    conn = airport_connect()
    row = conn.execute("SELECT * FROM airports WHERE id=?", (airport_id,)).fetchone()
    conn.close(); return row


def save_airport(airport_id, form):
    icao = (_clean(form.get("icao_code")) or "").upper() or None
    iata = (_clean(form.get("iata_code")) or "").upper() or None
    if not (icao or iata):
        raise ValueError("Un code ICAO ou IATA est obligatoire.")
    lat = _float(form.get("latitude"), "Latitude", -90, 90)
    lon = _float(form.get("longitude"), "Longitude", -180, 180)
    elev = _float(form.get("elevation"), "Altitude", -1000, 20000, required=False)
    values = (icao, iata, _clean(form.get("full_name")), _clean(form.get("country")), lat, lon, elev,
              _clean(form.get("timezone")), _clean(form.get("notes")))
    conn = airport_connect()
    try:
        if airport_id:
            conn.execute("UPDATE airports SET icao_code=?, iata_code=?, full_name=?, country=?, latitude=?, longitude=?, elevation=?, timezone=?, notes=? WHERE id=?", values + (airport_id,))
        else:
            conn.execute("INSERT INTO airports (icao_code, iata_code, full_name, country, latitude, longitude, elevation, timezone, notes) VALUES (?,?,?,?,?,?,?,?,?)", values)
        conn.commit()
    except Exception as exc:
        conn.rollback()
        if "UNIQUE" in str(exc):
            raise ValueError("Ce code ICAO ou IATA existe déjà.")
        raise
    finally:
        conn.close()


def delete_airport(airport_id):
    conn = airport_connect()
    conn.execute("DELETE FROM airports WHERE id=?", (airport_id,))
    conn.commit(); conn.close()


# ---------------- aircraft ----------------

def init_aircrafts_db():
    conn = aircrafts_connect()
    conn.execute("""CREATE TABLE IF NOT EXISTS aircrafts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        registration TEXT NOT NULL UNIQUE,
        type TEXT,
        engine TEXT CHECK (engine IN ('single','multi')),
        notes TEXT
    )""")
    conn.commit(); conn.close()


def find_aircraft(registration):
    registration = (registration or "").strip().upper()
    if not registration:
        return None
    conn = aircrafts_connect()
    row = conn.execute("SELECT * FROM aircrafts WHERE registration=?", (registration,)).fetchone()
    conn.close(); return row


def list_aircrafts():
    conn = aircrafts_connect()
    rows = conn.execute("SELECT * FROM aircrafts ORDER BY registration").fetchall()
    conn.close(); return rows


def get_aircraft(aircraft_id):
    conn = aircrafts_connect()
    row = conn.execute("SELECT * FROM aircrafts WHERE id=?", (aircraft_id,)).fetchone()
    conn.close(); return row


def save_aircraft(aircraft_id, form):
    registration = (_clean(form.get("registration")) or "").upper()
    if not registration:
        raise ValueError("Immatriculation obligatoire.")
    engine = _clean(form.get("engine"))
    if engine not in (None,) + ENGINES:
        raise ValueError("Type de moteur invalide.")
    values = (registration, _clean(form.get("type")), engine, _clean(form.get("notes")))
    conn = aircrafts_connect()
    try:
        if aircraft_id:
            conn.execute("UPDATE aircrafts SET registration=?, type=?, engine=?, notes=? WHERE id=?", values + (aircraft_id,))
        else:
            conn.execute("INSERT INTO aircrafts (registration, type, engine, notes) VALUES (?,?,?,?)", values)
        conn.commit()
    except Exception as exc:
        conn.rollback()
        if "UNIQUE" in str(exc):
            raise ValueError("Cette immatriculation existe déjà.")
        raise
    finally:
        conn.close()


def delete_aircraft(aircraft_id):
    conn = aircrafts_connect()
    conn.execute("DELETE FROM aircrafts WHERE id=?", (aircraft_id,))
    conn.commit(); conn.close()
