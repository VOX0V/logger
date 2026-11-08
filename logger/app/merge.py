"""Merge of imported rows into the raw database (A).
An import never replaces or deletes anything: a row that matches a flight already in the database
only fills that flight's EMPTY fields; a row with no matching flight is added as a new flight.
Importing the same file twice therefore changes nothing."""
import re
from collections import Counter
from datetime import date


FLIGHT_NUM_RE = re.compile(r"([A-Z]{2,3}\d{2,5})")
SE_ME_COLUMNS = ["time_se_dual_day", "time_se_pic_day", "time_se_dual_night", "time_se_pic_night", "time_me_dual_day", "time_me_pic_day",
                 "time_me_copi_day", "time_me_dual_night", "time_me_pic_night", "time_me_copi_night"]
HOURS_TOLERANCE = 0.15
MAX_SAMPLES = 10


def blank(v):
    return v is None or (isinstance(v, str) and not v.strip())


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def row_date(rec):
    """ISO date of a flight: from date_date, else from date_year / date_month / date_day."""
    d = str(rec.get("date_date") or "").strip()[:10]
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", d):
        return d
    try:
        return date(int(float(rec.get("date_year"))), int(float(rec.get("date_month"))), int(float(rec.get("date_day")))).isoformat()
    except (TypeError, ValueError):
        return None


def flight_digits(rec):
    """Digits of the flight number (column flight_number, else AC8569-like token of the remarks)."""
    raw = str(rec.get("flight_number") or "").strip()
    if raw:
        digits = re.sub(r"\D", "", raw.split(".")[0])
        if digits:
            return digits
    m = FLIGHT_NUM_RE.search(str(rec.get("misc_remarks") or "").upper())
    return re.sub(r"\D", "", m.group(1)) if m else ""


def norm_remarks(v):
    return re.sub(r"[^A-Z0-9]+", " ", str(v or "").upper()).strip()


def norm_registration(v):
    return re.sub(r"[^A-Z0-9]", "", str(v or "").upper())


def hours(rec):
    block = rec.get("time_flight_hhmm")
    if not blank(block):
        text = str(block).strip()
        m = re.fullmatch(r"(\d+):(\d{2})(?::\d{2})?", text)
        if m:
            return int(m.group(1)) + int(m.group(2)) / 60
        try:
            return float(text.replace(",", "."))
        except ValueError:
            pass
    return sum(num(rec.get(c)) for c in SE_ME_COLUMNS) or None


def merge_context():
    from .converter.catalog import load_settings
    mapping = {str(k).strip().upper(): str(v).strip().upper() for k, v in (load_settings().get("aircraft_types") or {}).items()}
    try:
        from .refdata import list_aircraft_types
        for t in list_aircraft_types():
            mapping.setdefault(t["designator"].strip().upper(), (t["display"] or t["designator"]).strip().upper())
    except Exception:
        pass
    return {"types": mapping, "locations": {}}


def canon_location(v, ctx):
    code = str(v or "").strip().upper()
    if not code:
        return ""
    if code not in ctx["locations"]:
        from .refdata import find_location
        location = find_location(code)
        ctx["locations"][code] = (location["icao_code"] or location["company_code"] or code) if location is not None else code
    return ctx["locations"][code]


def norm_type(v, ctx):
    code = str(v or "").strip().upper()
    return ctx["types"].get(code, code)


def same_value(col, a, b, ctx):
    if col == "aircraft_registration":
        return norm_registration(a) == norm_registration(b)
    if col == "aircraft_type":
        return norm_type(a, ctx) == norm_type(b, ctx)
    if col in ("location_departure_code", "location_arrival_code"):
        return canon_location(a, ctx) == canon_location(b, ctx)
    try:
        return abs(float(a) - float(b)) < 1e-6
    except (TypeError, ValueError):
        return str(a).strip().casefold() == str(b).strip().casefold()


def _conflicts(rec, e, ctx):
    """Preuve contraire : deux vols portant des identifiants différents ne sont jamais le même vol."""
    a, b = flight_digits(rec), flight_digits(e)
    if a and b and a != b:
        return True
    ra, rb = norm_registration(rec.get("aircraft_registration")), norm_registration(e.get("aircraft_registration"))
    if ra and rb and ra != rb:
        return True
    for col in ("location_departure_code", "location_arrival_code"):
        x, y = canon_location(rec.get(col), ctx), canon_location(e.get(col), ctx)
        if x and y and x != y:
            return True
    return False


def find_match(rec, candidates, ctx):
    """The flight of `candidates` (same date, not matched yet) that `rec` describes, or None."""
    digits = flight_digits(rec)
    if digits:
        for e in candidates:
            if flight_digits(e) == digits:
                return e
    remarks = norm_remarks(rec.get("misc_remarks"))
    if remarks:
        for e in candidates:
            if norm_remarks(e.get("misc_remarks")) == remarks and not _conflicts(rec, e, ctx):
                return e
    reg, dep, arr = norm_registration(rec.get("aircraft_registration")), canon_location(rec.get("location_departure_code"), ctx), canon_location(rec.get("location_arrival_code"), ctx)
    if reg and dep and arr:
        for e in candidates:
            if (norm_registration(e.get("aircraft_registration")) == reg and canon_location(e.get("location_departure_code"), ctx) == dep
                    and canon_location(e.get("location_arrival_code"), ctx) == arr):
                return e
    kind, duration = norm_type(rec.get("aircraft_type"), ctx), hours(rec)
    if kind and duration:
        for e in candidates:
            other = hours(e)
            if norm_type(e.get("aircraft_type"), ctx) == kind and other and abs(other - duration) <= HOURS_TOLERANCE and not _conflicts(rec, e, ctx):
                return e
    return None


def plan_merge(existing, incoming, cols, ctx):
    """existing: rows of A (dicts with id). incoming: rows of the file. Returns (inserts, updates, stats)."""
    by_date, undated = {}, []
    for e in existing:
        d = row_date(e)
        (by_date.setdefault(d, []) if d else undated).append(e)
    used, inserts, updates = set(), [], []
    stats = {"read": len(incoming), "added": 0, "completed": 0, "unchanged": 0, "filled": Counter(),
             "disagreements": 0, "samples": []}
    for rec in incoming:
        d = row_date(rec)
        if d:
            pool = [e for e in by_date.get(d, []) if e["id"] not in used]
            match = find_match(rec, pool, ctx)
        else:      # no date: only an identical row counts as the same flight
            filled = [c for c in cols if c != "crew_operator" and not blank(rec.get(c))]      # the employer never decides whether two rows are the same flight
            match = next((e for e in undated if e["id"] not in used and filled
                          and all(not blank(e.get(c)) and same_value(c, e.get(c), rec.get(c), ctx) for c in filled)), None)
        if match is None:
            inserts.append(rec)
            stats["added"] += 1
            continue
        used.add(match["id"])
        changes = {}
        for c in cols:
            new, old = rec.get(c), match.get(c)
            if blank(new):
                continue
            if blank(old) or (c == "crew_operator" and old == "undefined"):      # "undefined" is a placeholder: a real employer replaces it
                changes[c] = new
                stats["filled"][c] += 1
            elif not same_value(c, old, new, ctx):
                stats["disagreements"] += 1
                if len(stats["samples"]) < MAX_SAMPLES:
                    stats["samples"].append((d or "no date", c, old, new))
        if changes:
            updates.append((match["id"], changes))
            stats["completed"] += 1
        else:
            stats["unchanged"] += 1
    return inserts, updates, stats
