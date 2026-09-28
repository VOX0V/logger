"""Transformations available to converter rules.

Each transformation reads values from one row of database A (a dict of
column -> value) and returns a dict {B column: value}. Night calculation and
Transport Canada rounding reproduce the logic of the earlier project.
"""
import re
from datetime import date, datetime, timedelta, timezone

import ephem

from ..refdata import find_airport, find_aircraft

ENGINE_CHOICES = [("any", "Tous les avions"), ("single", "Monomoteur seulement"), ("multi", "Multimoteur seulement")]
ROUNDING_CHOICES = [("tc", "Arrondi Transport Canada"), ("none", "Aucun arrondi (heures + minutes/60)")]

# transform id -> description used to validate rules and to build the admin form.
# inputs/outputs: (slot, label, required); params: (key, label, choices)
TRANSFORMS = {
    "copy": {
        "label": "Copie d'une colonne",
        "inputs": [("source", "Colonne de A", True)],
        "outputs": [("target", "Colonne de B", True)],
        "params": [],
    },
    "date_parts": {
        "label": "Date à partir de année / mois / jour",
        "inputs": [("year", "Colonne année (A)", True), ("month", "Colonne mois (A)", True), ("day", "Colonne jour (A)", True)],
        "outputs": [("target", "Colonne de B (date)", True)],
        "params": [],
    },
    "datetime_date": {
        "label": "Date extraite d'une date/heure",
        "inputs": [("source", "Colonne date/heure (A)", True)],
        "outputs": [("target", "Colonne de B (date)", True)],
        "params": [],
    },
    "tc_round": {
        "label": "Temps de bloc en heures décimales",
        "inputs": [("time", "Colonne temps de bloc (A)", True)],
        "outputs": [("target", "Colonne de B", True)],
        "params": [("rounding", "Arrondi", ROUNDING_CHOICES)],
    },
    "day_night": {
        "label": "Temps de bloc en jour ou en nuit",
        "inputs": [("time", "Colonne temps de bloc (A)", True),
                   ("utc_ms", "Colonne heure UTC d'arrivée (A)", True),
                   ("airport", "Colonne aéroport d'arrivée (A)", True),
                   ("registration", "Colonne immatriculation (A) — requise si filtre moteur", False)],
        "outputs": [("day", "Colonne de B pour le jour", True), ("night", "Colonne de B pour la nuit", True)],
        "params": [("engine", "Filtre moteur", ENGINE_CHOICES), ("rounding", "Arrondi", ROUNDING_CHOICES)],
    },
}


class Skip(Exception):
    """The rule does not apply to this row (not a problem)."""


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
        raise Problem(f"Temps de bloc illisible : {text}")
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


def day_night(row, rule, settings):
    i, o, p = rule["inputs"], rule["outputs"], rule["params"]
    engine = p.get("engine", "any")
    if engine in ("single", "multi"):
        registration = row.get(i.get("registration"))
        aircraft = find_aircraft(registration)
        if aircraft is None:
            raise Problem(f"Avion inconnu : {str(registration or '').strip() or '(vide)'}")
        if not aircraft["engine"]:
            raise Problem(f"Type de moteur non renseigné pour l'avion : {aircraft['registration']}")
        if aircraft["engine"] != engine:
            raise Skip()
    value = block_to_decimal(parse_block(row.get(i["time"])), p.get("rounding", "tc"), settings["tc_rounding"]["rules"])
    if value is None:
        return {}
    code = str(row.get(i["airport"]) or "").strip()
    airport = find_airport(code)
    if airport is None:
        raise Problem(f"Aéroport inconnu : {code or '(vide)'}")
    arr_utc = parse_utc(row.get(i["utc_ms"]))
    if arr_utc is None:
        raise Problem("Heure UTC d'arrivée absente ou illisible")
    night = is_night(arr_utc, airport["latitude"], airport["longitude"],
                     settings["night"]["after_sunset_minutes"], settings["night"]["before_sunrise_minutes"])
    return {o["day"]: None if night else value, o["night"]: value if night else None}


FUNCTIONS = {"copy": copy, "date_parts": date_parts, "datetime_date": datetime_date,
             "tc_round": tc_round, "day_night": day_night}
