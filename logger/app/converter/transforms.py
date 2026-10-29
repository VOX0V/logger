"""Transformations available to converter rules.

Each transformation reads values from one row of database A (a dict of
column -> value) and returns a dict {B column: value}. Night calculation and
Transport Canada rounding reproduce the logic of the earlier project.
"""
import re
from datetime import date, datetime, timedelta, timezone

import ephem

from ..refdata import find_airport, find_aircraft_type

ENGINE_CHOICES = [("any", "All aircraft"), ("single", "Single-engine only"), ("multi", "Multi-engine only")]
ROUNDING_CHOICES = [("tc", "Transport Canada rounding"), ("none", "No rounding (hours + minutes/60)")]

# transform id -> description used to validate rules and to build the admin form.
# inputs/outputs: (slot, label, required); params: (key, label, choices)
TRANSFORMS = {
    "copy": {
        "label": "Copy of a column",
        "inputs": [("source", "Column of A", True)],
        "outputs": [("target", "Column of B", True)],
        "params": [],
    },
    "date_parts": {
        "label": "Date from year / month / day",
        "inputs": [("year", "Year column (A)", True), ("month", "Month column (A)", True), ("day", "Day column (A)", True)],
        "outputs": [("target", "Column of B (date)", True)],
        "params": [],
    },
    "datetime_date": {
        "label": "Date extracted from a date/time",
        "inputs": [("source", "Date/time column (A)", True)],
        "outputs": [("target", "Column of B (date)", True)],
        "params": [],
    },
    "tc_round": {
        "label": "Block time in decimal hours",
        "inputs": [("time", "Block time column (A)", True)],
        "outputs": [("target", "Column of B", True)],
        "params": [("rounding", "Arrondi", ROUNDING_CHOICES)],
    },
    "day_night": {
        "label": "Block time into day or night",
        "inputs": [("time", "Block time column (A)", True),
                   ("utc_ms", "UTC arrival time column (A)", True),
                   ("airport", "Arrival airport column (A)", True),
                   ("date", "Date column (A), when the UTC arrival is a time of day only (hh:mm)", False),
                   ("start", "UTC departure time column (A), to pass midnight", False),
                   ("type", "Aircraft type column (A) — engine filter (default: “type” column)", False)],
        "outputs": [("day", "Column of B for day", True), ("night", "Column of B for night", True)],
        "params": [("engine", "Engine filter", ENGINE_CHOICES), ("rounding", "Arrondi", ROUNDING_CHOICES)],
    },
    "registration": {
        "label": "Registration (upper case, dash added)",
        "inputs": [("source", "Registration column (A)", True)],
        "outputs": [("target", "Column of B", True)],
        "params": [],
    },
    "aircraft_type": {
        "label": "Aircraft type (mapping table)",
        "inputs": [("source", "Type column (A)", True)],
        "outputs": [("target", "Column of B", True)],
        "params": [],
    },
    "icao_code": {
        "label": "Airport as ICAO code",
        "inputs": [("source", "Airport column (A), IATA or ICAO", True)],
        "outputs": [("target", "Column of B", True)],
        "params": [],
    },
    "crew": {
        "label": "Crew from the crew list",
        "inputs": [("crew", "Crew list column (A)", True)],
        "outputs": [("captain", "Column of B for the captain", True), ("copilot", "Column of B for the copilot", True)],
        "params": [],
    },
    "zero_block": {
        "label": "Skip flights with 0:00 block time (not operated)",
        "inputs": [("time", "Block time column (A)", True)],
        "outputs": [],
        "params": [],
    },
    "not_flying": {
        "label": "Skip flights where I am not at the controls",
        "inputs": [("crew", "Crew list column (A)", True), ("deadhead", "Deadhead column (A)", True)],
        "outputs": [],
        "params": [],
    },
    "flight_remarks": {
        "label": "Remarks: prefix + flight number",
        "inputs": [("source", "Flight number column (A)", True)],
        "outputs": [("target", "Column of B", True)],
        "params": [],
    },
}


class Skip(Exception):
    """The rule does not apply to this row (not a problem)."""


class SkipRow(Exception):
    """The whole row is left out of the logbook (not a flight the user piloted)."""


class Problem(Exception):
    """The row's data prevented the rule from being computed (reported as a warning)."""


def blank(value):
    return value is None or str(value).strip() == ""


# ---------------- dates ----------------

def date_parts(row, rule, settings):
    i = rule["inputs"]
    try:
        y, m, d = (int(float(str(row.get(i[k])).strip())) for k in ("year", "month", "day"))
        return {rule["outputs"]["target"]: date(y, m, d).isoformat()}
    except (TypeError, ValueError):
        return {}


def datetime_date(row, rule, settings):
    text = str(row.get(rule["inputs"]["source"]) or "").strip()
    if re.match(r"\d{4}-\d{2}-\d{2}", text):
        return {rule["outputs"]["target"]: text[:10]}
    return {}


def copy(row, rule, settings):
    value = row.get(rule["inputs"]["source"])
    return {rule["outputs"]["target"]: None if blank(value) else value}


# ---------------- block time ----------------

def parse_block(value):
    """('hm', hours, minutes) for 'H:MM[:SS]', ('dec', hours) for a plain number, None if empty/zero."""
    if blank(value):
        return None
    text = str(value).strip()
    m = re.search(r"(\d{1,2}):(\d{2})(?::(\d{2}))?", text)
    if m:
        hours, minutes = int(m.group(1)), int(m.group(2))
        return None if hours == 0 and minutes == 0 else ("hm", hours, minutes)
    try:
        number = float(text.replace(",", "."))
    except ValueError:
        raise Problem(f"Unreadable block time: {text}")
    return None if number == 0 else ("dec", number)


def block_to_decimal(parsed, rounding, tc_rules):
    if parsed is None:
        return None
    if parsed[0] == "dec":
        return round(parsed[1], 1)
    _, hours, minutes = parsed
    if rounding != "tc":
        return round(hours + minutes / 60, 2)
    dec, add = 0.0, False
    for r in tc_rules:
        if r["min"] <= minutes <= r["max"]:
            dec, add = r["decimal"], r.get("add_hour", False)
            break
    return round(hours + (1 if add else 0) + dec, 1)


def tc_round(row, rule, settings):
    parsed = parse_block(row.get(rule["inputs"]["time"]))
    value = block_to_decimal(parsed, rule["params"].get("rounding", "tc"), settings["tc_rounding"]["rules"])
    return {rule["outputs"]["target"]: value}


# ---------------- day / night ----------------

def parse_utc(value):
    """Naive UTC datetime from epoch milliseconds/seconds or an ISO date/time text."""
    if blank(value):
        return None
    text = str(value).strip()
    if re.fullmatch(r"\d{9,13}(\.0+)?", text):
        number = float(text)
        seconds = number / 1000 if number >= 1e11 else number
        return datetime.fromtimestamp(seconds, timezone.utc).replace(tzinfo=None)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def is_night(arr_utc, lat, lon, after_sunset_min, before_sunrise_min):
    """Night = from `after_sunset_min` after sunset to `before_sunrise_min` before sunrise."""
    obs = ephem.Observer()
    obs.lat, obs.lon = str(lat), str(lon)
    obs.date = arr_utc
    sun = ephem.Sun()
    try:
        prev_sunset = obs.previous_setting(sun).datetime()
        next_sunrise = obs.next_rising(sun).datetime()
        prev_sunrise = obs.previous_rising(sun).datetime()
    except ephem.AlwaysUpError:
        return False
    except ephem.NeverUpError:
        return True
    if prev_sunrise > prev_sunset:      # the sun is up
        return False
    night_start = prev_sunset + timedelta(minutes=after_sunset_min)
    night_end = next_sunrise - timedelta(minutes=before_sunrise_min)
    return night_start <= arr_utc <= night_end


def utc_from_date_time(date_value, time_value, start_value=None):
    """UTC datetime from a date (dd/mm/yy, dd/mm/yyyy or ISO) and a time of day (H:MM[:SS]).
    When `start_value` (a time of day) is later than `time_value`, the time belongs to the next day."""
    if blank(date_value) or blank(time_value):
        return None
    text = str(date_value).strip()
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{2}|\d{4})", text)
    try:
        if m:
            year = int(m.group(3))
            day = date(year + 2000 if year < 100 else year, int(m.group(2)), int(m.group(1)))
        else:
            day = date.fromisoformat(text[:10])
    except ValueError:
        return None

    def clock(value):
        t = re.fullmatch(r"(\d{1,2}):(\d{2})(?::(\d{2}))?", str(value).strip())
        if not t or int(t.group(1)) > 23 or int(t.group(2)) > 59:
            return None
        return int(t.group(1)), int(t.group(2)), int(t.group(3) or 0)

    end = clock(time_value)
    if end is None:
        return None
    begin = None if blank(start_value) else clock(start_value)
    result = datetime(day.year, day.month, day.day, *end)
    if begin is not None and end < begin:
        result += timedelta(days=1)
    return result


def day_night(row, rule, settings):
    i, o, p = rule["inputs"], rule["outputs"], rule["params"]
    engine = p.get("engine", "any")
    if engine in ("single", "multi"):
        raw = str(row.get(i.get("type") or "type") or "").strip().upper()
        mapping = {str(k).strip().upper(): str(v).strip().upper() for k, v in (settings.get("aircraft_types") or {}).items()}
        code = mapping.get(raw, raw)
        aircraft_type = find_aircraft_type(code)
        if aircraft_type is None:
            raise Problem(f"Unknown aircraft type: {code or '(empty)'}")
        if not aircraft_type["engines"]:
            if aircraft_type["category"] == "simulator":
                raise Skip()                    # a simulator has no engine filter to match
            raise Problem(f"Number of engines not set for type: {code}")
        if aircraft_type["engines"] != engine:
            raise Skip()
    value = block_to_decimal(parse_block(row.get(i["time"])), p.get("rounding", "tc"), settings["tc_rounding"]["rules"])
    if value is None:
        return {}
    code = str(row.get(i["airport"]) or "").strip()
    airport = find_airport(code)
    if airport is None:
        raise Problem(f"Unknown airport: {code or '(empty)'}")
    arr_utc = parse_utc(row.get(i["utc_ms"]))
    if arr_utc is None and i.get("date"):       # time of day only: combine it with the date column
        arr_utc = utc_from_date_time(row.get(i["date"]), row.get(i["utc_ms"]), row.get(i.get("start") or ""))
    if arr_utc is None:
        raise Problem("UTC arrival time missing or unreadable")
    night = is_night(arr_utc, airport["latitude"], airport["longitude"],
                     settings["night"]["after_sunset_minutes"], settings["night"]["before_sunrise_minutes"])
    return {o["day"]: None if night else value, o["night"]: value if night else None}


# ---------------- aircraft / airports / crew / remarks ----------------

def format_registration(row, rule, settings):
    raw = str(row.get(rule["inputs"]["source"]) or "").strip().upper()
    if raw and "-" not in raw and len(raw) == 5:
        raw = raw[0] + "-" + raw[1:]
    return {rule["outputs"]["target"]: raw or None}


def normalize_type(row, rule, settings):
    raw = str(row.get(rule["inputs"]["source"]) or "").strip().upper()
    mapping = {str(k).strip().upper(): str(v).strip() for k, v in (settings.get("aircraft_types") or {}).items()}
    return {rule["outputs"]["target"]: mapping.get(raw, raw) or None}


def to_icao(row, rule, settings):
    code = str(row.get(rule["inputs"]["source"]) or "").strip().upper()
    if not code:
        return {rule["outputs"]["target"]: None}
    airport = find_airport(code)
    icao = airport["icao_code"] if airport is not None and airport["icao_code"] else code
    return {rule["outputs"]["target"]: icao}


CREW_PATTERN = re.compile(r"(CA|FO|CP|SO)\s+([A-ZÀÂÄÉÈÊËÏÎÔÙÛÜÇ-]+),\s*([A-ZÀÂÄÉÈÊËÏÎÔÙÛÜÇ-]+)")


def _person(first, last):
    return f"{first[0]}.{last.capitalize()}" if first else last.capitalize()


def crew_from_list(row, rule, settings):
    """Captain = the CA line; copilot = the FO/CP/SO line matching the user's family name.
    No crew list or no match: captain 'NAME' and the user as copilot (as in the earlier project)."""
    pilot = str(settings.get("pilot_name") or "").strip()
    if not pilot:
        raise Problem("Pilot family name not set (My account page): crew list not read")
    crew = str(row.get(rule["inputs"]["crew"]) or "").strip().upper()
    captain, copilot = "NAME", f"{pilot[0].upper()}.{pilot.capitalize()}"
    found = False
    for role, last, first in CREW_PATTERN.findall(crew):
        if role == "CA":
            captain = _person(first, last)
        elif pilot.upper() in last:
            copilot, found = _person(first, last), True
    if not found:   # listed as "?? FIRSTNAME FAMILYNAME" (no role, no comma): take the initial from the first name
        m = re.search(rf"([A-ZÀÂÄÉÈÊËÏÎÔÙÛÜÇ-]+)\s+{re.escape(pilot.upper())}\b", crew)
        if m and m.group(1) not in ("CA", "FO", "CP", "SO", "PU", "FA"):
            copilot = _person(m.group(1), pilot)
    o = rule["outputs"]
    return {o["captain"]: captain, o["copilot"]: copilot}


def skip_zero_block(row, rule, settings):
    """A block time that is filled but equal to zero means the flight was not operated."""
    value = row.get(rule["inputs"]["time"])
    if blank(value):
        return {}
    try:
        parsed = parse_block(value)
    except Problem:
        return {}
    if parsed is None:
        raise SkipRow()
    return {}


def skip_not_flying(row, rule, settings):
    """Leave out deadhead / training lines (deadhead column filled) and flights whose crew list
    does not contain the user's family name anywhere (whatever the role or the name format)."""
    if not blank(row.get(rule["inputs"]["deadhead"])):
        raise SkipRow()
    pilot = str(settings.get("pilot_name") or "").strip().upper()
    crew = str(row.get(rule["inputs"]["crew"]) or "").strip().upper()
    if pilot and crew and not re.search(rf"\b{re.escape(pilot)}\b", crew):
        raise SkipRow()
    return {}


def flight_remarks(row, rule, settings):
    number = str(row.get(rule["inputs"]["source"]) or "").strip()
    if re.fullmatch(r"\d+\.0+", number):
        number = number.split(".")[0]
    prefix = str(settings.get("airline_prefix") or "")
    return {rule["outputs"]["target"]: f"{prefix}{number}" if number else None}


def date_dmy(row, rule, settings):
    """Text date dd/mm/yy or dd/mm/yyyy -> ISO date."""
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{2}|\d{4})", str(row.get(rule["inputs"]["source"]) or "").strip())
    if not m:
        return {}
    day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        return {rule["outputs"]["target"]: date(year + 2000 if year < 100 else year, month, day).isoformat()}
    except ValueError:
        return {}


def last_first_name(row, rule, settings):
    """'GALLANT, ETIENNE' -> 'E.Gallant'. Any other format is copied trimmed."""
    raw = " ".join(str(row.get(rule["inputs"]["source"]) or "").split())
    if "," in raw:
        last, first = (part.strip() for part in raw.split(",", 1))
        if last:
            raw = _person(first.upper(), last.upper())
    return {rule["outputs"]["target"]: raw or None}


def time_by_landing(row, rule, settings):
    """Copy a time into the day column when a day landing is flagged, into the night column when a night landing is."""
    i, o = rule["inputs"], rule["outputs"]
    value = row.get(i["time"])
    if blank(value):
        return {}
    if rule["params"].get("rounding") == "tc":
        value = block_to_decimal(parse_block(value), "tc", settings["tc_rounding"]["rules"])
        if value is None:
            return {}
    out = {}
    if not blank(row.get(i["landing_day"])):
        out[o["day"]] = value
    if not blank(row.get(i["landing_night"])):
        out[o["night"]] = value
    return out


def skip_blank(row, rule, settings):
    """Leave out the rows where the column is empty."""
    if blank(row.get(rule["inputs"]["source"])):
        raise SkipRow()
    return {}


FUNCTIONS = {"copy": copy, "date_parts": date_parts, "datetime_date": datetime_date,
             "tc_round": tc_round, "day_night": day_night, "registration": format_registration,
             "aircraft_type": normalize_type, "icao_code": to_icao, "crew": crew_from_list,
             "flight_remarks": flight_remarks,
             "not_flying": skip_not_flying, "zero_block": skip_zero_block,
             "date_dmy": date_dmy, "last_first_name": last_first_name,
             "time_by_landing": time_by_landing, "skip_blank": skip_blank}

TRANSFORMS.update({
    "date_dmy": {"label": "Date from text dd/mm/yy", "inputs": [("source", "Date column (A)", True)],
                 "outputs": [("target", "Column of B (date)", True)], "params": []},
    "last_first_name": {"label": "Name 'LAST, FIRST' to 'F.Last'", "inputs": [("source", "Name column (A)", True)],
                        "outputs": [("target", "Column of B", True)], "params": []},
    "time_by_landing": {"label": "Time to day/night column from landing flags",
                        "inputs": [("time", "Time column (A)", True), ("landing_day", "Day landing column (A)", True),
                                   ("landing_night", "Night landing column (A)", True)],
                        "outputs": [("day", "Day column of B", True), ("night", "Night column of B", True)],
                        "params": [("rounding", "Rounding", ROUNDING_CHOICES)]},
    "skip_blank": {"label": "Skip rows where a column is empty", "inputs": [("source", "Column (A)", True)],
                   "outputs": [], "params": []},
})
