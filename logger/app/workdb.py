"""Definition of the work data (logbook table) from one YAML file: defaults/work_db.yml.

Each key "<position>_<name>" is a column; its "rules" are tried in order and the first one that gives a
non-empty value wins. Expressions are evaluated by a small whitelisted interpreter (no eval): the YAML
file can hold conditions and formulas without any code change. A copy edited in the web interface lives
in appdata/workdb/work_db.yml and wins over the file shipped with the app."""
import ast
import datetime
import math
import re
from pathlib import Path

import yaml

BUNDLED = Path(__file__).resolve().parent.parent / "defaults" / "work_db.yml"
DATA_TYPES = {"integer", "decimal", "boolean", "date", "datetime", "text"}
RESERVED = {"id", "created_at", "updated_at", "import_source", "import_profile"}
KEY = re.compile(r"(\d+)_(.+)")
NAME = re.compile(r"[a-z][a-z0-9_]*")


class SpecError(Exception):
    pass


class ExprError(Exception):
    pass


# ---------------- file location ----------------

def edited_path():
    """Writable copy edited in the web interface (appdata/workdb/work_db.yml); None outside the app."""
    try:
        from .db import appdata_root
        return appdata_root() / "workdb" / "work_db.yml"
    except RuntimeError:
        return None


def spec_path():
    edited = edited_path()
    return edited if edited is not None and edited.is_file() else BUNDLED


# ---------------- expressions ----------------

def _blank(v):
    return v is None or (isinstance(v, str) and not v.strip())


_ISO = re.compile(r"\s*(\d{4})-(\d{1,2})-(\d{1,2})")
_DMY = re.compile(r"\s*(\d{1,2})[/.-](\d{1,2})[/.-](\d{4}|\d{2})(?!\d)")
_MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}
_MDY = re.compile(r"\s*([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})(?!\d)")
_D_MONTH_Y = re.compile(r"\s*(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3,9})\.?,?\s+(\d{4})(?!\d)")


def _ymd(v):
    """(year, month, day) of 2026-09-27, 27/09/2026 or 27/09/26 (two digits: 00-69 = 2000-2069, 70-99 = 1970-1999)."""
    text = "" if v is None else str(v)
    m = _ISO.match(text)
    if m:
        y, mo, d = int(m[1]), int(m[2]), int(m[3])
    else:
        m = _DMY.match(text)
        if m:
            d, mo, y = int(m[1]), int(m[2]), int(m[3])
            if len(m[3]) == 2:
                y += 2000 if y < 70 else 1900
        else:
            named = _MDY.match(text)
            if named:
                mo, d, y = _MONTHS.get(named[1][:3].lower()), int(named[2]), int(named[3])
            else:
                named = _D_MONTH_Y.match(text)
                if not named:
                    return None
                d, mo, y = int(named[1]), _MONTHS.get(named[2][:3].lower()), int(named[3])
            if mo is None:
                return None
    return (y, mo, d) if 1 <= mo <= 12 and 1 <= d <= 31 else None


def _date_part(v, index):
    parts = _ymd(v)
    return None if parts is None else parts[index - 1]


def _date_of(v):
    """YYYY-MM-DD of a date written 2026-09-27, 27/09/2026, Sep 11 2026 or 11 September 2026 (empty when it is not a date)."""
    parts = _ymd(v)
    if parts is None:
        return None
    try:
        return datetime.date(*parts).isoformat()
    except ValueError:
        return None


def _time_24h(v):
    """HH:MM (24 h) of 5:10AM, 5:10 PM, 17:10 or 17:10:00 (empty when there is no time)."""
    m = re.search(r"(?<!\d)(\d{1,2}):(\d{2})(?::\d{2})?(?:\s*([AaPp])\.?[Mm]\.?)?", "" if v is None else str(v))
    if not m:
        return None
    h, mi, ampm = int(m[1]), int(m[2]), m[3]
    if mi > 59 or h > 23:
        return None
    if ampm:
        if not 1 <= h <= 12:
            return None
        h = h % 12 + (12 if ampm.lower() == "p" else 0)
    return f"{h:02d}:{mi:02d}"


def _strip_chars(v, chars):
    """The text without the given characters at both ends: strip_chars("# 0767", "# ") -> 0767."""
    if _blank(v):
        return None
    text = str(v).strip().strip("" if chars is None else str(chars)).strip()
    return text or None


def _to_float(v):
    if _blank(v):
        return None
    try:
        return float(str(v).strip().replace(",", "."))
    except ValueError:
        return None


def _is_zero_time(v):
    from .converter.transforms import parse_block, Problem
    if _blank(v):
        return False
    try:
        return parse_block(v) is None
    except Problem:
        return False


def _has_word(text, word):
    if _blank(word):
        return True
    return re.search(rf"\b{re.escape(str(word).strip())}\b", "" if text is None else str(text), re.I) is not None


# ---- times and distances
def _time_of(v):
    """HH:MM of a datetime or a time (2024-10-11 10:00:00 -> 10:00)."""
    m = re.search(r"(?<!\d)(\d{1,2}):(\d{2})", "" if v is None else str(v))
    if not m:
        return None
    h, mi = int(m[1]), int(m[2])
    return f"{h:02d}:{mi:02d}" if h < 24 and mi < 60 else None


def _to_dt(v):
    """A datetime (naive, UTC when the value has a zone) from ISO text or from epoch seconds / milliseconds."""
    if _blank(v):
        return None
    n = _to_float(v)
    if n is not None and abs(n) >= 1e9:
        if abs(n) >= 1e11:
            n /= 1000.0
        return datetime.datetime.fromtimestamp(n, datetime.timezone.utc).replace(tzinfo=None)
    try:
        dt = datetime.datetime.fromisoformat(str(v).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.astimezone(datetime.timezone.utc).replace(tzinfo=None) if dt.tzinfo is not None else dt


def _minutes_between(a, b):
    x, y = _to_dt(a), _to_dt(b)
    if x is None or y is None:
        return None
    m = (y - x).total_seconds() / 60.0
    return m if m >= 0 else None


def _hhmm(minutes):
    value = _to_float(minutes)
    if value is None:
        return None
    total = int(round(value))
    return f"{total // 60:02d}:{total % 60:02d}"


def _minutes(v):
    m = re.fullmatch(r"\s*(\d{1,3}):(\d{2})(?::\d{2})?\s*", "" if v is None else str(v))
    return int(m[1]) * 60 + int(m[2]) if m else None


def _distance_nm(lat1, lon1, lat2, lon2):
    values = [_to_float(x) for x in (lat1, lon1, lat2, lon2)]
    if any(x is None for x in values):
        return None
    p1, l1, p2, l2 = map(math.radians, values)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin((l2 - l1) / 2) ** 2
    return 2 * 3440.065 * math.asin(min(1.0, math.sqrt(a)))


def _round(v, digits):
    x, n = _to_float(v), _to_float(digits)
    return None if x is None or n is None else round(x, int(n))


# ---- flight time in decimal hours (Transport Canada table)
def _tc_rules():
    if ("tc",) not in _cache:
        from .converter.catalog import load_settings
        _cache[("tc",)] = load_settings()["tc_rounding"]["rules"]     # Table 4.1 of Transport Canada, from the converter settings
    return _cache[("tc",)]


def _tc_hours(v):
    """Decimal hours: H:MM[:SS] is converted with the Transport Canada table (1:35 -> 1.6); a number is kept (1,6 -> 1.6).
    Empty, zero or unreadable values give nothing, so that the next rule can apply."""
    from .converter.transforms import parse_block, block_to_decimal, Problem
    try:
        parsed = parse_block(v)
    except Problem:
        return None
    return None if parsed is None else block_to_decimal(parsed, "tc", _tc_rules())


# ---- sun
def _utc_datetime(year, month, day, time_utc, earlier_time):
    """2026-09-27T10:05 from year, month, day and a UTC time (HH:MM). When earlier_time is given and the time is
    before it, the time belongs to the next day (an arrival after midnight UTC)."""
    y, mo, d = _to_float(year), _to_float(month), _to_float(day)
    t = _minutes(time_utc)
    if y is None or mo is None or d is None or t is None:
        return None
    try:
        base = datetime.datetime(int(y), int(mo), int(d))
    except ValueError:
        return None
    ref = _minutes(earlier_time)
    days = 1 if ref is not None and t < ref else 0
    return (base + datetime.timedelta(days=days, minutes=t)).strftime("%Y-%m-%dT%H:%M")


def _sun_angle(lat, lon, when_utc):
    """Geometric angle of the centre of the sun above the horizon, in degrees (0 = horizon, -6 = end of civil twilight)."""
    la, lo, dt = _to_float(lat), _to_float(lon), _to_dt(when_utc)
    if la is None or lo is None or dt is None:
        return None
    import ephem
    observer = ephem.Observer()
    observer.lat, observer.lon, observer.elevation = str(la), str(lo), 0
    observer.pressure = 0                      # no refraction: the geometric angle
    observer.date = dt
    return math.degrees(ephem.Sun(observer).alt)


# ---- people (format P.Nom)
_LETTER_DOT = re.compile(r"[^\W\d_]\.\S")
_CREW = re.compile(r"(CA|FO|CP|SO)\s+([A-ZÀÂÄÉÈÊËÏÎÔÙÛÜÇ-]+),\s*([A-ZÀÂÄÉÈÊËÏÎÔÙÛÜÇ-]+)")


def _is_pilot_format(v):
    s = "" if v is None else str(v).strip()
    return bool(_LETTER_DOT.match(s)) and "," not in s and not any(ch.isdigit() for ch in s)


def _cap(last):
    last = last.strip()
    if last.isupper() or last.islower():
        return "-".join(part.capitalize() for part in last.split("-"))
    return last


def _person(first, last):
    return f"{first[0].upper()}.{_cap(last)}" if first else _cap(last)


def _pilot_format(v):
    """V.Fuzeau from V.Fuzeau, Fuzeau, Vincent / FUZEAU, VINCENT or Vincent Fuzeau."""
    if _blank(v):
        return None
    s = str(v).strip()
    if _is_pilot_format(s):
        return _person(s[0], s[2:])
    if "," in s:
        last, first = (part.strip() for part in s.split(",", 1))
    else:
        parts = s.split()
        if len(parts) < 2:
            return None
        first, last = parts[0], " ".join(parts[1:])
    return _person(first, last) if first and last else None


def _crew_captain(crew):
    for role, last, first in _CREW.findall("" if crew is None else str(crew).upper()):
        if role == "CA":
            return _person(first, last)
    return None


def _crew_copilot(crew, pilot):
    """The FO / CP / SO of the crew list whose family name matches the user's (pilot_name)."""
    pilot = "" if pilot is None else str(pilot).strip().upper()
    text = "" if crew is None else str(crew).upper()
    if not pilot or not text:
        return None
    for role, last, first in _CREW.findall(text):
        if role != "CA" and pilot in last:
            return _person(first, last)
    m = re.search(rf"([A-ZÀÂÄÉÈÊËÏÎÔÙÛÜÇ-]+)\s+{re.escape(pilot)}\b", text)      # "FIRSTNAME FAMILYNAME" without role
    if m and m[1] not in ("CA", "FO", "CP", "SO", "PU", "FA"):
        return _person(m[1], pilot)
    return None


# ---- reference tables (Aircraft and Locations); the cache is emptied each time work_db.yml is loaded
_cache = {}
AIRCRAFT_FIELDS = {"display", "designator", "maker", "model", "category", "engines", "engine_type", "crew", "landing_gear", "mtow_lb", "mtow_kg"}
LOCATION_FIELDS = {"display", "icao", "iata", "company", "name", "country", "latitude", "longitude"}
_LOCATION_COLUMN = {"icao": "icao_code", "iata": "iata_code", "company": "company_code", "name": "full_name"}


def reset_cache():
    _cache.clear()


def _cached(kind, code, finder):
    key = (kind, "" if code is None else str(code).strip().upper())
    if key not in _cache:
        row = finder(key[1]) if key[1] else None
        _cache[key] = dict(row) if row is not None else None
    return _cache[key]


def _registration_format(value):
    """Registration as in the converter (format_registration): upper case, C-GABC for a 5 letter code without dash."""
    raw = str(value or "").strip().upper()
    if raw and "-" not in raw and len(raw) == 5:
        raw = raw[0] + "-" + raw[1:]
    return raw or None


def _aircraft(code, field):
    from .refdata import find_aircraft_type
    row = _cached("aircraft", code, find_aircraft_type)
    if row is None:
        return None
    if field == "display":
        return row.get("display") or row.get("designator")
    return row.get(field) if field in row.keys() else row.get(f"aircraft_{field}")


def _location(code, field):
    from .refdata import find_location
    row = _cached("location", code, find_location)
    if row is None:
        return None
    if field == "display":
        return row.get("display") or row.get("icao_code") or row.get("iata_code") or row.get("company_code")
    column = _LOCATION_COLUMN.get(field, field)
    return row.get(column) if column in row.keys() else row.get(f"location_{field}")


FUNCS = {
    "is_blank": lambda x: _blank(x),
    "year_of": lambda x: _date_part(x, 1),
    "month_of": lambda x: _date_part(x, 2),
    "day_of": lambda x: _date_part(x, 3),
    "is_zero_time": _is_zero_time,
    "has_word": _has_word,
    "time_of": _time_of,
    "minutes_between": _minutes_between,
    "hhmm": _hhmm,
    "minutes": _minutes,
    "distance_nm": _distance_nm,
    "round": _round,
    "tc_hours": _tc_hours,
    "utc_datetime": _utc_datetime,
    "sun_angle": _sun_angle,
    "is_pilot_format": _is_pilot_format,
    "pilot_format": _pilot_format,
    "crew_captain": _crew_captain,
    "crew_copilot": _crew_copilot,
    "registration_format": _registration_format,
    "aircraft": _aircraft,
    "location": _location,
    "airport": _location,       # former name of location(), kept so that edited work_db.yml files keep working
    "date_of": _date_of,
    "time_24h": _time_24h,
    "strip_chars": _strip_chars,
}
_ARITY = {"is_blank": 1, "year_of": 1, "month_of": 1, "day_of": 1, "is_zero_time": 1, "has_word": 2, "time_of": 1,
          "minutes_between": 2, "hhmm": 1, "minutes": 1, "distance_nm": 4, "round": 2, "tc_hours": 1, "utc_datetime": 5, "sun_angle": 3, "is_pilot_format": 1,
          "pilot_format": 1, "crew_captain": 1, "crew_copilot": 2, "aircraft": 2, "location": 2, "registration_format": 1,
          "airport": 2, "date_of": 1, "time_24h": 1, "strip_chars": 2}
_CMP = (ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE)
_ARITH = (ast.Add, ast.Sub, ast.Mult, ast.Div)


def _check(node, where):
    if isinstance(node, ast.Constant):
        if not isinstance(node.value, (str, int, float, bool, type(None))):
            raise SpecError(f"{where}: this kind of value is not allowed.")
    elif isinstance(node, ast.Name):
        pass
    elif isinstance(node, ast.BoolOp):
        for v in node.values: _check(v, where)
    elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.Not, ast.USub, ast.UAdd)):
        _check(node.operand, where)
    elif isinstance(node, ast.BinOp) and isinstance(node.op, _ARITH):
        _check(node.left, where); _check(node.right, where)
    elif isinstance(node, ast.Compare) and all(isinstance(o, _CMP) for o in node.ops):
        _check(node.left, where)
        for c in node.comparators: _check(c, where)
    elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and not node.keywords:
        name = node.func.id
        if name not in FUNCS:
            raise SpecError(f"{where}: unknown function “{name}” (available: {', '.join(sorted(FUNCS))}).")
        if len(node.args) != _ARITY[name]:
            raise SpecError(f"{where}: {name}() takes {_ARITY[name]} argument(s).")
        for a in node.args: _check(a, where)
        if name in ("aircraft", "location") and isinstance(node.args[1], ast.Constant):
            allowed = AIRCRAFT_FIELDS if name == "aircraft" else LOCATION_FIELDS
            if node.args[1].value not in allowed:
                raise SpecError(f"{where}: {name}() has no field “{node.args[1].value}” (available: {', '.join(sorted(allowed))}).")
    else:
        raise SpecError(f"{where}: this expression is not allowed (operators and functions are limited to the documented ones).")


def _compile(text, where):
    if text is None or isinstance(text, (bool, int, float)):
        return ast.Constant(text)
    source = str(text).strip()
    try:
        tree = ast.parse(source, mode="eval")
    except SyntaxError as exc:
        raise SpecError(f"{where}: invalid expression “{source}” ({exc.msg}).")
    _check(tree.body, where)
    return tree.body


def _norm(v):
    if v is None:
        return ""
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    s = str(v).strip()
    try:
        return float(s.replace(",", "."))
    except ValueError:
        return s.upper()


def _compare(op, a, b):
    a, b = _norm(a), _norm(b)
    if isinstance(op, ast.Eq): return a == b
    if isinstance(op, ast.NotEq): return a != b
    if a == "" or b == "" or type(a) is not type(b):
        return False
    return {ast.Lt: a < b, ast.LtE: a <= b, ast.Gt: a > b, ast.GtE: a >= b}[type(op)]


def _number(v):
    try:
        return float(str(v).strip().replace(",", "."))
    except ValueError:
        raise ExprError(f"“{v}” is not a number.")


def _entity_names():
    """Names of the entities (entities.yml): a raw column that no import has created yet is empty, not an error."""
    if ("entities",) not in _cache:
        try:
            from .import_profiles import load_entities
            _cache[("entities",)] = set(load_entities())
        except Exception:
            _cache[("entities",)] = set()
    return _cache[("entities",)]


def _eval(node, env, warn):
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        key = node.id.lower()
        if key not in env:
            if key not in _entity_names():
                warn(f"Unknown name “{node.id}” in work_db.yml (not a raw data column)")
            return None
        return env[key]
    if isinstance(node, ast.BoolOp):
        result = None
        for v in node.values:
            result = _eval(v, env, warn)
            if isinstance(node.op, ast.And) and not _truthy(result): return result
            if isinstance(node.op, ast.Or) and _truthy(result): return result
        return result
    if isinstance(node, ast.UnaryOp):
        v = _eval(node.operand, env, warn)
        if isinstance(node.op, ast.Not): return not (v and not _blank(v))
        if v is None: return None
        return -_number(v) if isinstance(node.op, ast.USub) else _number(v)
    if isinstance(node, ast.BinOp):
        a, b = _eval(node.left, env, warn), _eval(node.right, env, warn)
        if _blank(a) or _blank(b): return None
        if isinstance(node.op, ast.Add) and isinstance(a, str) and isinstance(b, str) and not (_is_num(a) and _is_num(b)):
            return a + b
        x, y = _number(a), _number(b)
        if isinstance(node.op, ast.Add): return x + y
        if isinstance(node.op, ast.Sub): return x - y
        if isinstance(node.op, ast.Mult): return x * y
        return None if y == 0 else x / y
    if isinstance(node, ast.Compare):
        left = _eval(node.left, env, warn)
        for op, comp in zip(node.ops, node.comparators):
            right = _eval(comp, env, warn)
            if not _compare(op, left, right): return False
            left = right
        return True
    if isinstance(node, ast.Call):
        try:
            return FUNCS[node.func.id](*[_eval(a, env, warn) for a in node.args])
        except (ValueError, TypeError, ArithmeticError) as exc:
            raise ExprError(f"{node.func.id}(): {exc}")
    raise ExprError("Unsupported expression.")


def _is_num(s):
    try:
        float(s.strip().replace(",", ".")); return True
    except ValueError:
        return False


def _truthy(v):
    return bool(v) and not _blank(v)


def _coerce(v, data_type):
    if _blank(v):
        return None
    try:
        if data_type == "integer": return int(float(str(v).strip().replace(",", ".")))
        if data_type == "decimal": return float(str(v).strip().replace(",", "."))
        if data_type == "boolean": return 1 if _truthy(v) else 0
        if data_type == "date":
            m = re.match(r"\s*(\d{4}-\d{2}-\d{2})", str(v))
            if not m: raise ValueError(v)
            return m.group(1)
    except (ValueError, OverflowError):
        raise ExprError(f"“{v}” cannot be used as {data_type}.")
    return str(v)


# ---------------- specification ----------------

def parse_spec(data):
    """Validate the YAML content (already loaded) and return {"skip": [...], "columns": [...]}; raises SpecError."""
    if not isinstance(data, dict):
        raise SpecError("The file must start with keys (key: value).")
    skip, columns, numbers, names = [], [], set(), set()
    for key, body in data.items():
        if key == "skip_rows":
            if body is None: continue
            if not isinstance(body, list) or not all(isinstance(r, dict) and "when" in r for r in body):
                raise SpecError("skip_rows must be a list of blocks that each have a “when”.")
            for i, r in enumerate(body, 1):
                skip.append({"name": str(r.get("name") or f"skip rule {i}"), "when": _compile(r["when"], f"skip_rows no.{i}")})
            continue
        m = KEY.fullmatch(str(key))
        if not m:
            raise SpecError(f"Unknown key “{key}”: a column key looks like 1_year (position, underscore, name).")
        number, name = int(m.group(1)), re.sub(r"[^a-z0-9]+", "_", m.group(2).lower()).strip("_")
        if not NAME.fullmatch(name) or name in RESERVED:
            raise SpecError(f"{key}: “{name}” is not a valid column name (letters, digits and underscores; not reserved).")
        if number in numbers: raise SpecError(f"{key}: position {number} is used twice.")
        if name in names: raise SpecError(f"{key}: duplicate column “{name}”.")
        numbers.add(number); names.add(name)
        if not isinstance(body, dict) or not set(body) <= {"type", "display_name", "rules"}:
            raise SpecError(f"{key}: expected a block with type, display_name and rules.")
        data_type = str(body.get("type", "text")).lower()
        if data_type not in DATA_TYPES:
            raise SpecError(f"{key}: type must be one of {', '.join(sorted(DATA_TYPES))}.")
        rules = body.get("rules")
        if not isinstance(rules, list) or not rules or not all(isinstance(r, dict) and "value" in r and set(r) <= {"name", "when", "value"} for r in rules):
            raise SpecError(f"{key}: “rules” must be a non-empty list of blocks with a “value” (and optionally “when”, “name”).")
        compiled = [{"when": _compile(r["when"], f"{key} rule no.{i}") if "when" in r else None,
                     "value": _compile(r["value"], f"{key} rule no.{i}")} for i, r in enumerate(rules, 1)]
        columns.append({"number": number, "column": name, "type": data_type,
                        "display_name": str(body.get("display_name") or name.replace("_", " ")), "rules": compiled})
    if not columns:
        raise SpecError("At least one column is required (for example 1_year).")
    columns.sort(key=lambda c: c["number"])
    numbers_of = {c["column"]: c["number"] for c in columns}
    for c in columns:
        for rule in c["rules"]:
            for tree in (rule["when"], rule["value"]):
                for node in (ast.walk(tree) if tree is not None else ()):
                    if isinstance(node, ast.Name) and node.id.lower().startswith("w_"):
                        target = node.id.lower()[2:]
                        if target not in numbers_of:
                            raise SpecError(f"{c['number']}_{c['column']}: “{node.id}” refers to a work column that does not exist.")
                        if numbers_of[target] >= c["number"]:
                            raise SpecError(f"{c['number']}_{c['column']}: “{node.id}” can only use a column with a lower number.")
    return {"skip": skip, "columns": columns}


def load_spec():
    reset_cache()                                   # Aircraft / Locations data are read again at each refresh
    return parse_spec(yaml.safe_load(spec_path().read_text(encoding="utf-8")))


def config_columns(spec=None):
    """The columns in the format of the user's work data configuration (<user>_logbook.yml)."""
    spec = spec or load_spec()
    return [{"column": c["column"], "display_name": c["display_name"], "position": i, "data_type": c["type"],
             "nullable": True, "visible": True, "editable": True} for i, c in enumerate(spec["columns"], 1)]


def apply_to_user(username=None):
    """Make the user's work data configuration follow work_db.yml (the file is the only source of the columns).
    Returns True when it changed. An invalid file leaves the configuration untouched."""
    from .config import load_logbook_db_config, save_logbook_db_config
    try:
        wanted = config_columns()
    except (SpecError, OSError, yaml.YAMLError):
        return False
    current = [(c["column"], c["display_name"], c["data_type"]) for c in load_logbook_db_config(username)["database"]["columns"] if not c.get("system")]
    if current == [(w["column"], w["display_name"], w["data_type"]) for w in wanted]:
        return False
    save_logbook_db_config({"database": {"columns": wanted}}, username)
    return True


def convert_row(spec, source, pilot_name, warn):
    """Work data values of one raw row: a dict, or None when a skip rule leaves the row out."""
    env = {str(k).lower(): v for k, v in source.items()}
    env.update(pilot_name=pilot_name, true=True, false=False)
    env.update({"w_" + c["column"]: None for c in spec["columns"]})     # w_<column>: the value computed for an earlier column
    for rule in spec["skip"]:
        try:
            if _truthy(_eval(rule["when"], env, lambda _m: None)):      # a raw column that does not exist is simply empty here
                return None
        except ExprError as exc:
            warn(f"Skip rule “{rule['name']}”: {exc}")
    out = {}
    for col in spec["columns"]:
        for rule in col["rules"]:
            try:
                if rule["when"] is not None and not _truthy(_eval(rule["when"], env, warn)):
                    continue
                value = _coerce(_eval(rule["value"], env, warn), col["type"])
            except ExprError as exc:
                warn(f"Column {col['column']}: {exc}")
                continue
            if value is not None:
                out[col["column"]] = value
                env["w_" + col["column"]] = value
                break
    return out
