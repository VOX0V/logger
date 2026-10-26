"""Audit of the logbook database (B): dates, identity, flight times and column consistency.
Adapted from the checks of the earlier Excel-based application (chronology, identity, times)."""
import re
import sqlite3
import unicodedata
from collections import defaultdict
from datetime import date

from flask import Blueprint, render_template

from .auth import login_required
from .db import logbook_connect

audit_bp = Blueprint("audit", __name__, url_prefix="/audit")

SEVERITY_ORDER = {"ERREUR": 0, "ANOMALIE": 1, "INFO": 2}
MAX_SHOWN = 200

KNOWN_TYPES = {"RH22", "RH44", "RH66", "AS350", "EC120", "B505", "BH06", "C150", "C152", "A152",
               "C172", "TB10", "PA28", "PA30", "PA31", "CRJ", "SIM"}
COMPATIBLE_TYPES = [{"A152", "C152"}]
TYPOS = [(r"\bINTRUCTEUR\b", "INSTRUCTEUR"), (r"\bRefrest\b", "Refresh"), (r"\bCKS3\b", "CSK3")]
MAX_DURATION = 8.0          # hours on one line
DECIMAL_SUSPECT = 12.0      # a value above this is probably "1,5" typed as 15
AIRLINE_TYPES = {"CRJ"}

SE = ["single_engine_dual_day", "single_engine_pic_day", "single_engine_dual_night", "single_engine_pic_night"]
ME = ["multi_engine_dual_day", "multi_engine_pic_day", "multi_engine_copi_day",
      "multi_engine_dual_night", "multi_engine_pic_night", "multi_engine_copi_night"]
XC = ["cross_country_dual_day", "cross_country_pic_day", "cross_country_dual_night", "cross_country_pic_night"]
OTHER = ["ifr", "hood", "ftd", "ifr_approach", "instruction_day", "instruction_night"]
LANDINGS = ["landings_day", "landings_night"]
DUAL = ["single_engine_dual_day", "single_engine_dual_night", "multi_engine_dual_day",
        "multi_engine_dual_night", "cross_country_dual_day", "cross_country_dual_night"]
TIME_COLS = SE + ME + XC + OTHER
SIM_COLS = ["ftd", "instruction_day", "instruction_night"]       # un vol de simulateur ne comporte que ces temps
EMPTY_MARKERS = {"vide", "empty"}                              # remarque d'une ligne volontairement vide (espacement du logbook)
TEXT_COLS = ("aircraft_type", "registration", "pilot_in_command", "copilot", "departure", "arrival", "remarks")


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def text(v):
    return "" if v is None else str(v)


def is_sim(reg):
    return bool(re.match(r"^(Elite|RB|FRASCA|SIM)", reg, re.I)) or reg in ("F-DMP", "---", "XXX")


def name_key(name):
    plain = unicodedata.normalize("NFD", name)
    plain = "".join(c for c in plain if not unicodedata.combining(c))
    return re.sub(r"[^a-z]", "", plain.lower())


def is_empty_line(r):
    """Ligne volontairement vide : la remarque est uniquement « vide » ou « empty »."""
    return text(r.get("remarks")).strip().lower() in EMPTY_MARKERS


def airport_codes():
    """Codes OACI de la table Aéroports (base commune) ; None si la table n'est pas disponible."""
    try:
        from .refdata import list_airports
        return {text(a["icao_code"]).strip().upper() for a in list_airports() if a["icao_code"]}
    except Exception:
        return None


def check_row(r, today, icao=None):
    out = []

    def add(sev, cat, msg):
        out.append((sev, cat, msg))

    if is_empty_line(r):
        try:
            date.fromisoformat(text(r.get("date"))[:10])
        except ValueError:
            add("ANOMALIE", "Ligne vide sans date", "ligne « vide » sans date valide : elle peut se retrouver n'importe où dans le logbook")
        return out                                     # aucun autre test sur une ligne vide

    d = text(r.get("date"))[:10]
    try:
        if date.fromisoformat(d) > today:
            add("INFO", "Date future", f"{d} (vol planifié ?)")
    except ValueError:
        add("ERREUR", "Date manquante ou invalide", repr(r.get("date")))

    typ, reg = text(r.get("aircraft_type")).strip(), text(r.get("registration")).strip()
    cop, dep, arr = text(r.get("copilot")).strip(), text(r.get("departure")).strip(), text(r.get("arrival")).strip()
    times = {c: num(r.get(c)) for c in TIME_COLS}
    has_time = any(times.values())

    for c, v in times.items():
        if v < 0:
            add("ERREUR", "Valeur négative", f"{c} = {v:g}")
        elif v >= DECIMAL_SUSPECT:
            add("ANOMALIE", "Valeur décimale suspecte", f"{c} = {v:g} (1,5 saisi comme 15 ?)")
        elif v > MAX_DURATION:
            add("ANOMALIE", "Durée anormale", f"{c} = {v:g} h (> {MAX_DURATION:g} h)")
    if not has_time and not any(num(r.get(c)) for c in LANDINGS):
        add("ANOMALIE", "Ligne sans temps", "aucun temps ni atterrissage enregistré")
    if typ.upper() == "SIM":                           # simulateur : uniquement du temps FTD (entraînement) ou instruction (formation)
        if not sum(times[c] for c in SIM_COLS):
            add("ANOMALIE", "Simulateur sans FTD ni instruction", "aucun temps FTD ni instruction")
        other = [f"{c} = {v:g}" for c, v in times.items() if c not in SIM_COLS and v > 0]
        if other:
            add("ANOMALIE", "Simulateur avec temps hors FTD / instruction", ", ".join(other))
    elif has_time and not (sum(times[c] for c in SE + ME) or times["ftd"]):
        add("ANOMALIE", "Heures sans catégorie", "temps enregistrés hors mono / multi / FTD")

    if not typ:
        add("ANOMALIE", "Type d'aéronef inconnu", "type vide")
    elif typ not in KNOWN_TYPES:
        add("ANOMALIE", "Type d'aéronef inconnu", f"« {typ} »")

    if reg:
        if not (is_sim(reg) or re.match(r"^C-[A-Z]{4}$", reg) or re.match(r"^[A-Z]{1,2}-[A-Z0-9]{3,5}$", reg)
                or re.match(r"^N\d{1,5}[A-Z]{0,2}$", reg)):
            add("ANOMALIE", "Format d'immatriculation", f"« {reg} »")
    elif has_time and typ != "SIM":
        add("ANOMALIE", "Immatriculation vide", "vol avec temps mais sans immatriculation")

    for field, v in (("departure", dep), ("arrival", arr)):
        if len(v) == 3:
            add("ANOMALIE", "Aérodrome au format suspect", f"{field} : « {v} » (code OACI à 4 caractères attendu, ex. KBNA)")
        elif len(v) == 4 and icao is not None and v.upper() not in icao:
            add("ANOMALIE", "Aérodrome inconnu", f"{field} : « {v} » absent de la table Aéroports")
        # toute autre longueur (nom de lieu, etc.) : pas de test

    pilot = text(r.get("pilot_in_command")).strip()
    if pilot and cop and pilot.lower() == cop.lower():
        add("ANOMALIE", "Pilote et copilote identiques", f"« {pilot} »")
    if not cop:
        if times["instruction_day"] + times["instruction_night"] > 0:
            add("ANOMALIE", "Instruction sans copilote", "instruction enregistrée sans copilote")
        if any(times[c] > 0 for c in DUAL):
            add("ANOMALIE", "Dual sans copilote / instructeur", "temps dual sans copilote renseigné")
    if typ in AIRLINE_TYPES and dep and dep == arr and any(times[c] > 0 for c in XC):
        add("INFO", "Vol sur campagne départ = arrivée", f"{dep} → {arr} (retour mécanique ?)")

    total = sum(times[c] for c in SE + ME)
    if total > 0:
        if times["ifr"] > total + 0.05:
            add("ANOMALIE", "Incohérence entre colonnes", f"IFR {times['ifr']:g} > temps total {total:g}")
        xc = sum(times[c] for c in XC)
        if xc > total + 0.05:
            add("ANOMALIE", "Incohérence entre colonnes", f"vol sur campagne {xc:g} > temps total {total:g}")

    for c in TEXT_COLS:
        v = text(r.get(c))
        if v and (v != v.strip() or "  " in v):
            add("ANOMALIE", "Espaces parasites", f"{c} : « {v} »")

    rem = text(r.get("remarks"))
    for pattern, fix in TYPOS:
        m = re.search(pattern, rem, re.I)
        if m:
            add("ANOMALIE", "Faute d'orthographe", f"« {m.group()} » devrait être « {fix} »")
    mx = re.match(r"^EX\s+([\d\-]+)", rem)
    if mx:
        seen, issues = set(), []
        for n in (int(x) for x in re.findall(r"\d+", mx.group(1))):
            if n in seen:
                issues.append(f"numéro {n} en double")
            seen.add(n)
            if n > 50:
                issues.append(f"numéro {n} suspect (> 50)")
        if issues:
            add("ANOMALIE", "Exercices suspects", " ; ".join(issues))
    return out


def check_global(rows):
    out = []
    rows = [r for r in rows if not is_empty_line(r)]
    types_by_reg, forms_by_reg = defaultdict(set), defaultdict(set)
    forms_by_name, forms_by_aero = defaultdict(set), defaultdict(set)
    for r in rows:
        reg, typ = text(r.get("registration")).strip(), text(r.get("aircraft_type")).strip()
        if reg and not is_sim(reg):
            forms_by_reg[re.sub(r"[^A-Z0-9]", "", reg.upper())].add(reg)
            if typ:
                types_by_reg[reg.upper()].add(typ)
        for c in ("pilot_in_command", "copilot"):
            n = text(r.get(c)).strip()
            if n and n.upper() != "NAME":
                forms_by_name[name_key(n)].add(n)
        for c in ("departure", "arrival"):
            a = text(r.get(c)).strip()
            if a:
                forms_by_aero[re.sub(r"[^A-Z0-9]", "", a.upper())].add(a)
    for reg, types in sorted(types_by_reg.items()):
        if len(types) > 1 and not any(types <= c for c in COMPATIBLE_TYPES):
            out.append(("ANOMALIE", "Immatriculation ↔ type", f"{reg} : {' / '.join(sorted(types))}"))
    for cat, groups in (("Graphies différentes : immatriculation", forms_by_reg),
                        ("Graphies différentes : nom de pilote", forms_by_name),
                        ("Graphies différentes : aérodrome", forms_by_aero)):
        for forms in groups.values():
            if len(forms) > 1:
                out.append(("ANOMALIE", cat, " / ".join(sorted(forms))))
    return out


def run_checks(rows, today=None):
    today = today or date.today()
    findings = []
    icao = airport_codes()
    for r in rows:
        route = f"{text(r.get('departure'))}→{text(r.get('arrival'))}" if r.get("departure") or r.get("arrival") else ""
        label = " ".join(x for x in (text(r.get("registration")).strip(), route, text(r.get("remarks")).strip()[:40]) if x)
        for sev, cat, msg in check_row(r, today, icao):
            findings.append({"sev": sev, "cat": cat, "date": text(r.get("date"))[:10], "label": label, "msg": msg})
    for sev, cat, msg in check_global(rows):
        findings.append({"sev": sev, "cat": cat, "date": "", "label": "plusieurs lignes", "msg": msg})
    return findings


def group_findings(findings):
    by_cat = defaultdict(list)
    for f in findings:
        by_cat[(f["sev"], f["cat"])].append(f)
    groups = [(cat, sev, items[:MAX_SHOWN], max(0, len(items) - MAX_SHOWN))
              for (sev, cat), items in by_cat.items()]
    groups.sort(key=lambda g: (SEVERITY_ORDER[g[1]], g[0]))
    counts = defaultdict(int)
    for f in findings:
        counts[f["sev"]] += 1
    return groups, counts


@audit_bp.route("/")
@login_required
def index():
    try:
        conn = logbook_connect()
        conn.row_factory = sqlite3.Row
        rows = [dict(r) for r in conn.execute("SELECT * FROM logbook ORDER BY id")]
        conn.close()
    except sqlite3.Error:
        rows = []
    groups, counts = group_findings(run_checks(rows))
    return render_template("audit.html", total=len(rows), groups=groups, counts=counts)
