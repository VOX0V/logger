"""Merge of imported rows into the raw database (A).
An import never replaces or deletes anything: a row that matches a flight already in the database
only fills that flight's EMPTY fields; a row with no matching flight is added as a new flight.
Importing the same file twice therefore changes nothing."""
import io
import re
from collections import Counter
from datetime import date

from openpyxl import load_workbook

FLIGHT_NUM_RE = re.compile(r"([A-Z]{2,3}\d{2,5})")
SE_ME_COLUMNS = ["single_engine_dual_day", "single_engine_pic_day", "single_engine_dual_night",
                 "single_engine_pic_night", "multi_engine_dual_day", "multi_engine_pic_day",
                 "multi_engine_copi_day", "multi_engine_dual_night", "multi_engine_pic_night",
                 "multi_engine_copi_night"]
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
    """ISO date of a flight: from the local departure time, else from year / month / day."""
    d = str(rec.get("departure_local") or "").strip()[:10]
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", d):
        return d
    try:
        return date(int(float(rec.get("year"))), int(float(rec.get("month"))), int(float(rec.get("day")))).isoformat()
    except (TypeError, ValueError):
        return None


def flight_digits(rec):
    """Digits of the flight number (column flight_number, else AC8569-like token of the remarks)."""
    raw = str(rec.get("flight_number") or "").strip()
    if raw:
        digits = re.sub(r"\D", "", raw.split(".")[0])
        if digits:
            return digits
    m = FLIGHT_NUM_RE.search(str(rec.get("remarks") or "").upper())
    return re.sub(r"\D", "", m.group(1)) if m else ""


def norm_remarks(v):
    return re.sub(r"[^A-Z0-9]+", " ", str(v or "").upper()).strip()


def norm_registration(v):
    return re.sub(r"[^A-Z0-9]", "", str(v or "").upper())


def hours(rec):
    block = rec.get("block_time")
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
    return {"types": mapping, "airports": {}}


def canon_airport(v, ctx):
    code = str(v or "").strip().upper()
    if not code:
        return ""
    if code not in ctx["airports"]:
        from .refdata import find_airport
        airport = find_airport(code)
        ctx["airports"][code] = (airport["icao_code"] if airport is not None and airport["icao_code"] else code)
    return ctx["airports"][code]


def norm_type(v, ctx):
    code = str(v or "").strip().upper()
    return ctx["types"].get(code, code)


def same_value(col, a, b, ctx):
    if col == "registration":
        return norm_registration(a) == norm_registration(b)
    if col == "type":
        return norm_type(a, ctx) == norm_type(b, ctx)
    if col in ("departure", "arrival"):
        return canon_airport(a, ctx) == canon_airport(b, ctx)
    try:
        return abs(float(a) - float(b)) < 1e-6
    except (TypeError, ValueError):
        return str(a).strip().casefold() == str(b).strip().casefold()


def find_match(rec, candidates, ctx):
    """The flight of `candidates` (same date, not matched yet) that `rec` describes, or None."""
    digits = flight_digits(rec)
    if digits:
        for e in candidates:
            if flight_digits(e) == digits:
                return e
    remarks = norm_remarks(rec.get("remarks"))
    if remarks:
        for e in candidates:
            if norm_remarks(e.get("remarks")) == remarks:
                return e
    reg, dep, arr = norm_registration(rec.get("registration")), canon_airport(rec.get("departure"), ctx), canon_airport(rec.get("arrival"), ctx)
    if reg and dep and arr:
        for e in candidates:
            if (norm_registration(e.get("registration")) == reg and canon_airport(e.get("departure"), ctx) == dep
                    and canon_airport(e.get("arrival"), ctx) == arr):
                return e
    kind, duration = norm_type(rec.get("type"), ctx), hours(rec)
    if kind and duration:
        for e in candidates:
            other = hours(e)
            if norm_type(e.get("type"), ctx) == kind and other and abs(other - duration) <= HOURS_TOLERANCE:
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
            filled = [c for c in cols if not blank(rec.get(c))]
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
            if blank(old):
                changes[c] = new
                stats["filled"][c] += 1
            elif not same_value(c, old, new, ctx):
                stats["disagreements"] += 1
                if len(stats["samples"]) < MAX_SAMPLES:
                    stats["samples"].append((d or "sans date", c, old, new))
        if changes:
            updates.append((match["id"], changes))
            stats["completed"] += 1
        else:
            stats["unchanged"] += 1
    return inserts, updates, stats


def read_logbook_workbook(filename, data):
    """Rows of a paginated Excel logbook (year sheets with 'GRAND TOTAL' rows), or None for any other file."""
    if not filename.lower().endswith((".xlsx", ".xlsm")):
        return None
    from .export import COL_DAY, COL_MONTH, TEXT_COLUMNS, TIME_COLUMNS, flight_rows, line_is_empty
    try:
        wb = load_workbook(io.BytesIO(data), data_only=True)
    except Exception:
        return None
    sheets = [ws for ws in wb.worksheets if re.fullmatch(r"\d{4}", ws.title) and flight_rows(ws)]
    if not sheets:
        return None
    rows = []
    for ws in sheets:
        for r in flight_rows(ws):
            if line_is_empty(ws, r):
                continue
            rec = {"year": int(ws.title)}
            for key, c in (("month", COL_MONTH), ("day", COL_DAY)):
                try:
                    rec[key] = int(float(str(ws.cell(r, c).value)))
                except (TypeError, ValueError):
                    rec[key] = None
            for name, c in TEXT_COLUMNS.items():
                value = ws.cell(r, c).value
                rec["type" if name == "aircraft_type" else name] = None if blank(value) else str(value).strip()
            for name, c in TIME_COLUMNS.items():
                value = ws.cell(r, c).value
                rec[name] = value if isinstance(value, (int, float)) and value != 0 else None
            rows.append(rec)
    return rows
