"""Shared reference databases: airports (airport.db) and aircraft (aircrafts.db)."""
from pathlib import Path
from flask import current_app
import io
import re, sqlite3, unicodedata
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter
import yaml
from .db import airport_connect, aircrafts_connect
from .importer import _read_table, FileImportError

ENGINES = ("single", "multi")      # legacy table "aircrafts" (by registration), no longer used
OPTION_FIELDS = {"category": "Category", "engines": "Engines", "engine_type": "Engine type", "crew": "Crew", "landing_gear": "Landing gear"}
SHIPPED_OPTIONS = Path(__file__).resolve().parent.parent / "defaults" / "aircraft_options.yml"
OPTION_CODE = re.compile(r"[a-z0-9_-]+")
LB_PER_KG = 2.20462262


# ---------------- choice lists of the aircraft table (aircraft_options.yml, edited by the administrators) ----------------

def edited_options_path():
    return Path(current_app.config["APPDATA_DIR"]) / "aircraft_options.yml"


def options_path():
    try:
        edited = edited_options_path()
        return edited if edited.is_file() else SHIPPED_OPTIONS
    except RuntimeError:
        return SHIPPED_OPTIONS


def parse_options(data):
    """{field: ((code, label), ...)}; raises ValueError with a readable message."""
    if not isinstance(data, dict):
        raise ValueError("The file must contain the lists: " + ", ".join(OPTION_FIELDS) + ".")
    unknown = set(map(str, data)) - set(OPTION_FIELDS)
    if unknown:
        raise ValueError(f"Unknown list “{sorted(unknown)[0]}” (lists: {', '.join(OPTION_FIELDS)}).")
    out = {}
    for field in OPTION_FIELDS:
        entry = data.get(field)
        if not isinstance(entry, dict) or not entry:
            raise ValueError(f"“{field}” must list at least one value (code: Label).")
        pairs = []
        for code, label in entry.items():
            if not isinstance(code, str) or not OPTION_CODE.fullmatch(code):
                raise ValueError(f"{field}: invalid code “{code}” (lower case letters, digits, - and _; put yes / no / on / off between quotes).")
            if not isinstance(label, str) or not label.strip():
                raise ValueError(f"{field}: “{code}” needs a label.")
            pairs.append((code, label.strip()))
        out[field] = tuple(pairs)
    return out


def load_options():
    for path in (options_path(), SHIPPED_OPTIONS):
        try:
            return parse_options(yaml.safe_load(path.read_text(encoding="utf-8")))
        except (OSError, yaml.YAMLError, ValueError):
            continue
    return {f: () for f in OPTION_FIELDS}


def option_pairs(field):
    return load_options()[field]


def used_option_values(field):
    conn = aircrafts_connect()
    try:
        return {r[0] for r in conn.execute(f"SELECT DISTINCT {field} FROM aircraft_types WHERE {field} IS NOT NULL AND {field} != ''")}
    finally:
        conn.close()


def check_options(data):
    """Validation on save: a value still used by an aircraft type cannot disappear."""
    parsed = parse_options(data)
    for field, pairs in parsed.items():
        missing = used_option_values(field) - {c for c, _l in pairs}
        if missing:
            raise ValueError(f"{field}: “{sorted(missing)[0]}” is still used by aircraft types: change them first.")
    return parsed


def _clean(value):
    text = "" if value is None else str(value).strip()
    return text or None


def _float(value, label, lo, hi, required=True):
    if value in (None, ""):
        if required:
            raise ValueError(f"{label} required.")
        return None
    try:
        number = float(str(value).replace(",", "."))
    except ValueError:
        raise ValueError(f"{label} invalid.")
    if not lo <= number <= hi:
        raise ValueError(f"{label}  out of range ({lo}  to  {hi}).")
    return number


# ---------------- airports ----------------

def _drop_if_old(conn, table, new_column):
    """Reference tables with the previous layout are rebuilt (their content comes back from the default files)."""
    columns = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
    if columns and new_column not in columns:
        conn.execute(f"DROP TABLE {table}")


def _load_default(name, importer):
    source = Path(current_app.root_path).parent / "defaults" / name
    if source.exists():
        importer(name, source.read_bytes())


def init_airport_db():
    conn = airport_connect()
    _drop_if_old(conn, "airports", "company_code")
    conn.execute("""CREATE TABLE IF NOT EXISTS airports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        display TEXT,
        icao_code TEXT UNIQUE,
        iata_code TEXT UNIQUE,
        company_code TEXT UNIQUE,
        full_name TEXT,
        country TEXT,
        latitude REAL NOT NULL,
        longitude REAL NOT NULL
    )""")
    empty = conn.execute("SELECT COUNT(*) FROM airports").fetchone()[0] == 0
    conn.commit(); conn.close()
    if empty:
        _load_default("airports.xlsx", import_airports)


def airport_display(airport):
    """Name shown in the logbook: the display column, else the ICAO, IATA or company code."""
    return (airport["display"] or airport["icao_code"] or airport["iata_code"] or airport["company_code"] or "").strip()


def find_airport(code):
    """Look an airport up by IATA code first, then ICAO, then company code. Returns a Row or None."""
    code = (code or "").strip().upper()
    if not code:
        return None
    conn = airport_connect()
    row = None
    for column in ("iata_code", "icao_code", "company_code"):
        row = conn.execute(f"SELECT * FROM airports WHERE {column}=?", (code,)).fetchone()
        if row:
            break
    conn.close()
    return row


def list_airports():
    conn = airport_connect()
    rows = conn.execute("SELECT * FROM airports ORDER BY COALESCE(icao_code, iata_code, company_code)").fetchall()
    conn.close(); return rows


def get_airport(airport_id):
    conn = airport_connect()
    row = conn.execute("SELECT * FROM airports WHERE id=?", (airport_id,)).fetchone()
    conn.close(); return row


def save_airport(airport_id, form):
    icao = (_clean(form.get("icao_code")) or "").upper() or None
    iata = (_clean(form.get("iata_code")) or "").upper() or None
    company = (_clean(form.get("company_code")) or "").upper() or None
    if not (icao or iata or company):
        raise ValueError("An ICAO, IATA or company code is required.")
    lat = _float(form.get("latitude"), "Latitude", -90, 90)
    lon = _float(form.get("longitude"), "Longitude", -180, 180)
    values = (_clean(form.get("display")), icao, iata, company, _clean(form.get("full_name")), _clean(form.get("country")), lat, lon)
    conn = airport_connect()
    try:
        if airport_id:
            conn.execute("UPDATE airports SET display=?, icao_code=?, iata_code=?, company_code=?, full_name=?, country=?, latitude=?, longitude=? WHERE id=?", values + (airport_id,))
        else:
            conn.execute("INSERT INTO airports (display, icao_code, iata_code, company_code, full_name, country, latitude, longitude) VALUES (?,?,?,?,?,?,?,?)", values)
        conn.commit()
    except Exception as exc:
        conn.rollback()
        if "UNIQUE" in str(exc):
            raise ValueError("This ICAO, IATA or company code already exists.")
        raise
    finally:
        conn.close()


def clear_airports():
    conn = airport_connect()
    conn.execute("DELETE FROM airports")
    conn.commit(); conn.close()


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
    )""")   # legacy table by registration: kept as is, no longer used
    _drop_if_old(conn, "aircraft_types", "designator")
    row = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='aircraft_types'").fetchone()
    existed = row is not None
    migrate = existed and "CHECK" in (row[0] or "")
    if migrate:       # older versions froze the lists with CHECK constraints: rebuild the table without them
        conn.execute("ALTER TABLE aircraft_types RENAME TO aircraft_types_old")
    conn.execute("""CREATE TABLE IF NOT EXISTS aircraft_types (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        display TEXT,
        designator TEXT NOT NULL UNIQUE,
        maker TEXT,
        model TEXT,
        category TEXT,
        engines TEXT,
        engine_type TEXT,
        crew TEXT,
        landing_gear TEXT,
        mtow_lb REAL,
        mtow_kg REAL
    )""")
    if migrate:
        conn.execute("""INSERT INTO aircraft_types (id, display, designator, maker, model, category, engines, engine_type, crew, mtow_lb, mtow_kg)
                        SELECT id, display, designator, maker, model, category, engines, engine_type, crew, mtow_lb, mtow_kg FROM aircraft_types_old""")
        conn.execute("DROP TABLE aircraft_types_old")
    if "landing_gear" not in {r[1] for r in conn.execute("PRAGMA table_info(aircraft_types)")}:
        conn.execute("ALTER TABLE aircraft_types ADD COLUMN landing_gear TEXT")
    conn.commit(); conn.close()
    if not existed:
        _load_default("aircrafts.xlsx", import_aircraft_types)


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
        raise ValueError("Registration required.")
    engine = _clean(form.get("engine"))
    if engine not in (None,) + ENGINES:
        raise ValueError("Invalid engine type.")
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
            raise ValueError("This registration already exists.")
        raise
    finally:
        conn.close()


def delete_aircraft(aircraft_id):
    conn = aircrafts_connect()
    conn.execute("DELETE FROM aircrafts WHERE id=?", (aircraft_id,))
    conn.commit(); conn.close()


# ---------------- aircraft types (global: one row per type, never per registration) ----------------

def find_aircraft_type(code):
    """Aircraft type by designator (DH1, CR9, C172...), else by display name (DHC8, CRJ: the first row that has it)."""
    code = (code or "").strip().upper()
    if not code:
        return None
    conn = aircrafts_connect()
    row = conn.execute("SELECT * FROM aircraft_types WHERE UPPER(designator)=?", (code,)).fetchone() \
        or conn.execute("SELECT * FROM aircraft_types WHERE UPPER(display)=? ORDER BY id LIMIT 1", (code,)).fetchone()
    conn.close(); return row


def list_aircraft_types():
    conn = aircrafts_connect()
    rows = conn.execute("SELECT * FROM aircraft_types ORDER BY category, designator").fetchall()
    conn.close(); return rows


def list_logbook_types():
    """One entry per logbook name (display); its 'code' is that name. DH1 and DH3 both give DHC8, CR2 and CR9 give CRJ."""
    seen = {}
    for row in list_aircraft_types():
        name = (row["display"] or row["designator"]).strip()
        if name.upper() not in seen:
            entry = dict(row)
            entry["code"] = name
            seen[name.upper()] = entry
    return list(seen.values())


def get_aircraft_type(type_id):
    conn = aircrafts_connect()
    row = conn.execute("SELECT * FROM aircraft_types WHERE id=?", (type_id,)).fetchone()
    conn.close(); return row


def _choice(value, pairs, label):
    text = _clean(value)
    if text is None:
        return None
    key = _code_for(text, pairs)
    if key is None:
        raise ValueError(f"Invalid {label}.")
    return key


def _weight(value, label):
    text = _clean(value)
    if text is None:
        return None
    try:
        number = float(text.replace(",", "."))
    except ValueError:
        raise ValueError(f"{label} invalid.")
    if number <= 0:
        raise ValueError(f"{label} must be positive.")
    return number


def _fill_mtow(lb, kg):
    """Both weights are entered by hand; only an empty one is calculated from the other."""
    if lb is None and kg is not None:
        lb = float(round(kg * LB_PER_KG))
    if kg is None and lb is not None:
        kg = float(round(lb / LB_PER_KG))
    return lb, kg


def save_aircraft_type(type_id, form):
    designator = (_clean(form.get("designator")) or "").upper()
    if not designator:
        raise ValueError("Designator required.")
    category = _choice(form.get("category"), option_pairs("category"), "category")
    engines = _choice(form.get("engines"), option_pairs("engines"), "number of engines")
    engine_type = _choice(form.get("engine_type"), option_pairs("engine_type"), "engine type")
    crew = _choice(form.get("crew"), option_pairs("crew"), "crew")
    landing_gear = _choice(form.get("landing_gear"), option_pairs("landing_gear"), "landing gear")
    lb, kg = _fill_mtow(_weight(form.get("mtow_lb"), "MTOW (lb)"), _weight(form.get("mtow_kg"), "MTOW (kg)"))
    values = (_clean(form.get("display")) or designator, designator, _clean(form.get("maker")), _clean(form.get("model")),
              category, engines, engine_type, crew, landing_gear, lb, kg)
    conn = aircrafts_connect()
    try:
        if type_id:
            conn.execute("UPDATE aircraft_types SET display=?, designator=?, maker=?, model=?, category=?, engines=?, engine_type=?, crew=?, landing_gear=?, mtow_lb=?, mtow_kg=? WHERE id=?",
                         values + (type_id,))
        else:
            conn.execute("INSERT INTO aircraft_types (display, designator, maker, model, category, engines, engine_type, crew, landing_gear, mtow_lb, mtow_kg) VALUES (?,?,?,?,?,?,?,?,?,?,?)", values)
        conn.commit()
    except Exception as exc:
        conn.rollback()
        if "UNIQUE" in str(exc):
            raise ValueError("This designator already exists.")
        raise
    finally:
        conn.close()


def clear_aircraft_types():
    conn = aircrafts_connect()
    conn.execute("DELETE FROM aircraft_types")
    conn.commit(); conn.close()


def delete_aircraft_type(type_id):
    conn = aircrafts_connect()
    conn.execute("DELETE FROM aircraft_types WHERE id=?", (type_id,))
    conn.commit(); conn.close()


# ---------------- Excel export ----------------

def _xlsx(sheet, headers, rows):
    wb = Workbook()
    ws = wb.active
    ws.title = sheet
    ws.append(headers)
    for row in rows:
        ws.append(list(row))
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for index, header in enumerate(headers, 1):
        longest = max([len(str(header))] + [len(str(r[index - 1] if r[index - 1] is not None else "")) for r in rows])
        ws.column_dimensions[get_column_letter(index)].width = min(max(12, longest + 2), 60)
    ws.freeze_panes = "A2"
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def export_aircraft_types_xlsx():
    opts = {f: dict(option_pairs(f)) for f in OPTION_FIELDS}
    rows = [(t["display"], t["designator"], t["maker"], t["model"], opts["category"].get(t["category"], ""), opts["engines"].get(t["engines"], ""),
             opts["engine_type"].get(t["engine_type"], ""), opts["crew"].get(t["crew"], ""), opts["landing_gear"].get(t["landing_gear"], ""),
             t["mtow_lb"], t["mtow_kg"]) for t in list_aircraft_types()]
    return _xlsx("Aircraft", ["display", "designator", "maker", "model", "Category", "Engines", "Engine type", "crew", "Landing gear", "MTOWlb", "MTOWkg"], rows)


def export_airports_xlsx():
    conn = airport_connect()
    rows = [(r["display"], r["icao_code"], r["iata_code"], r["company_code"], r["full_name"], r["country"], r["latitude"], r["longitude"])
            for r in conn.execute("SELECT * FROM airports ORDER BY COALESCE(icao_code, iata_code, company_code, '')")]
    conn.close()
    return _xlsx("Airports", ["display", "ICAO", "IATA", "company", "name", "country", "latitude", "longitude"], rows)


# ---------------- Excel import ----------------

AIRPORT_COLUMNS = {
    "display": ("display",), "icao_code": ("icao", "icao_code"), "iata_code": ("iata", "iata_code"),
    "company_code": ("company", "company code", "company_code"), "full_name": ("name", "full_name"),
    "country": ("country", "pays"), "latitude": ("latitude", "lat"), "longitude": ("longitude", "lon", "lng")}
AIRCRAFT_COLUMNS = {
    "display": ("display",), "designator": ("designator", "code"), "maker": ("maker", "make", "marque"),
    "model": ("model", "modele"), "category": ("category", "categorie"), "engines": ("engines",),
    "engine_type": ("engine type", "engine_type"), "crew": ("crew",), "landing_gear": ("landing gear", "landing_gear", "gear"), "mtow_lb": ("mtowlb", "mtow lb"), "mtow_kg": ("mtowkg", "mtow kg")}


def _hdr(value):
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _file_rows(filename, data, aliases):
    headers, rows = _read_table(filename, data)
    lookup = {_hdr(a): f for f, names in aliases.items() for a in names}
    cols = {i: lookup[_hdr(h)] for i, h in enumerate(headers) if _hdr(h) in lookup}
    out = []
    for values in rows:
        d = {}
        for i, field in cols.items():
            if i < len(values) and field not in d and _clean(values[i]) is not None:
                d[field] = _clean(values[i])
        if d:
            out.append(d)
    return out, set(cols.values())


def _code_for(value, pairs):
    key = _hdr(value)
    for code, label in pairs:
        if key in (_hdr(code), _hdr(label)):
            return code
    return None


def import_airports(filename, data):
    rows, present = _file_rows(filename, data, AIRPORT_COLUMNS)
    if not ({"icao_code", "iata_code", "company_code"} & present):
        raise FileImportError("ICAO, IATA or company column not found in the file.")
    added = updated = skipped = 0
    conn = airport_connect()
    try:
        for d in rows:
            icao = d.get("icao_code", "").upper() or None
            iata = d.get("iata_code", "").upper() or None
            company = d.get("company_code", "").upper() or None
            if not (icao or iata or company):
                skipped += 1; continue
            try:
                lat = _float(d.get("latitude"), "Latitude", -90, 90, required=False)
                lon = _float(d.get("longitude"), "Longitude", -180, 180, required=False)
            except ValueError:
                skipped += 1; continue
            display = d.get("display")
            if display and display.startswith("="):          # a formula that was not calculated: ignore it
                display = None
            new = {"display": display, "icao_code": icao, "iata_code": iata, "company_code": company,
                   "full_name": d.get("full_name"), "country": d.get("country"), "latitude": lat, "longitude": lon}
            hits = [r for r in (
                conn.execute("SELECT * FROM airports WHERE icao_code=?", (icao,)).fetchone() if icao else None,
                conn.execute("SELECT * FROM airports WHERE iata_code=?", (iata,)).fetchone() if iata else None,
                conn.execute("SELECT * FROM airports WHERE company_code=?", (company,)).fetchone() if company else None) if r]
            if len({r["id"] for r in hits}) > 1:
                skipped += 1; continue
            try:
                if hits:
                    gaps = {k: v for k, v in new.items() if v is not None and hits[0][k] in (None, "")}
                    if gaps:
                        conn.execute(f"UPDATE airports SET {', '.join(k + '=?' for k in gaps)} WHERE id=?",
                                     (*gaps.values(), hits[0]["id"]))
                        updated += 1
                elif lat is not None and lon is not None:
                    conn.execute(f"INSERT INTO airports ({', '.join(new)}) VALUES ({','.join('?' * len(new))})", tuple(new.values()))
                    added += 1
                else:
                    skipped += 1
            except sqlite3.IntegrityError:
                skipped += 1
        conn.commit()
    finally:
        conn.close()
    return added, updated, skipped


def import_aircraft_types(filename, data):
    rows, present = _file_rows(filename, data, AIRCRAFT_COLUMNS)
    if "designator" not in present:
        raise FileImportError("Column “designator” not found in the file.")
    added = updated = skipped = 0
    conn = aircrafts_connect()
    try:
        for d in rows:
            code = d.get("designator", "").upper()
            if not code:
                skipped += 1; continue
            try:
                lb, kg = _fill_mtow(_weight(d.get("mtow_lb"), "MTOW (lb)"), _weight(d.get("mtow_kg"), "MTOW (kg)"))
            except ValueError:
                lb = kg = None
            new = {"display": d.get("display") or code, "designator": code, "maker": d.get("maker"), "model": d.get("model"),
                   "category": _code_for(d.get("category"), option_pairs("category")),
                   "engines": _code_for(d.get("engines"), option_pairs("engines")),
                   "engine_type": _code_for(d.get("engine_type"), option_pairs("engine_type")),
                   "crew": _code_for(d.get("crew"), option_pairs("crew")),
                   "landing_gear": _code_for(d.get("landing_gear"), option_pairs("landing_gear")), "mtow_lb": lb, "mtow_kg": kg}
            row = conn.execute("SELECT * FROM aircraft_types WHERE UPPER(designator)=?", (code,)).fetchone()
            try:
                if row:
                    gaps = {k: v for k, v in new.items() if v is not None and row[k] in (None, "")}
                    if gaps:
                        conn.execute(f"UPDATE aircraft_types SET {', '.join(k + '=?' for k in gaps)} WHERE id=?",
                                     (*gaps.values(), row["id"]))
                        updated += 1
                else:
                    conn.execute(f"INSERT INTO aircraft_types ({', '.join(new)}) VALUES ({','.join('?' * len(new))})", tuple(new.values()))
                    added += 1
            except sqlite3.IntegrityError:
                skipped += 1
        conn.commit()
    finally:
        conn.close()
    return added, updated, skipped
