"""Audit of the work data (table logbook). The rules are YAML files: <app root>/audit/*.yml (shipped) and
appdata/audit/*.yml (copies edited in the web interface, which win by file name; a new file there is added).
All files are merged in file name order. See the comments at the top of the shipped files for the format.

  name:         shown in the editor
  params:       {name: number}                      constants usable in expressions
  lists:        {name: [columns]}                   for "each"
  vars:         {name: expression}                  computed for every row, in order
  skip_rows:    [expression]                        "empty lines": only rules with skipped_rows: true see them
  rules:        - {name, severity, when, message, each, skipped_rows}
  group_rules:  - {name, severity, kind: one_to_many | spellings, ...}   (rules over several rows)
Expressions are those of the global profiles (columns by name, and/or/not, comparisons, + - * /, functions), plus
valid_date, future_date, num, matches, length, has_stray_spaces, exercise_issues, known_location, known_aircraft."""
import re
import sqlite3
import unicodedata
from collections import defaultdict
from datetime import date
from pathlib import Path

import yaml
from flask import Blueprint, g, render_template

from . import workdb
from .auth import login_required
from .db import logbook_connect

audit_bp = Blueprint("audit", __name__, url_prefix="/audit")

SEVERITY_ORDER = {"ERROR": 0, "ANOMALY": 1, "INFO": 2}
MAX_SHOWN = 200
FILE_ID = re.compile(r"[a-z0-9_-]+")
BUNDLED_DIR = Path(__file__).resolve().parent.parent / "audit"
_STATE = {"today": None, "locations": None, "aircraft": None}


def text(v):
    return "" if v is None else str(v)


def name_key(name):
    plain = unicodedata.normalize("NFD", name)
    plain = "".join(c for c in plain if not unicodedata.combining(c))
    return re.sub(r"[^a-z]", "", plain.lower())


# ---------------- functions added to the expression language ----------------
def _date(y, m, d):
    return date(int(float(y)), int(float(m)), int(float(d)))


def _valid_date(y, m, d):
    try:
        _date(y, m, d)
        return True
    except (TypeError, ValueError):
        return False


def _future_date(y, m, d):
    try:
        return _date(y, m, d) > (_STATE["today"] or date.today())
    except (TypeError, ValueError):
        return False


def _num(v):
    try:
        return float(str(v).strip().replace(",", "."))
    except (TypeError, ValueError):
        return 0.0


def _matches(x, pattern):
    try:
        return re.search(str(pattern), text(x)) is not None
    except re.error as exc:
        raise ValueError(f"invalid pattern ({exc})")


def _length(x):
    return len(text(x).strip())


def _has_stray_spaces(x):
    v = text(x)
    return bool(v) and (v != v.strip() or "  " in v)


def _exercise_issues(remarks):
    """Exercise numbers of a remark such as “EX 3-4-4”: duplicates and numbers above 50."""
    mx = re.match(r"^EX\s+([\d\-]+)", text(remarks))
    if not mx:
        return ""
    seen, issues = set(), []
    for n in (int(x) for x in re.findall(r"\d+", mx.group(1))):
        if n in seen:
            issues.append(f"number {n} duplicate")
        seen.add(n)
        if n > 50:
            issues.append(f"number {n} suspicious (> 50)")
    return " ; ".join(issues)


def _known(table, x):
    codes = _STATE[table]
    return True if codes is None else text(x).strip().upper() in codes      # no table: nothing to compare with


workdb.FUNCS.update({"valid_date": _valid_date, "future_date": _future_date, "num": _num, "matches": _matches,
                     "length": _length, "has_stray_spaces": _has_stray_spaces, "exercise_issues": _exercise_issues,
                     "known_location": lambda x: _known("locations", x), "known_airport": lambda x: _known("locations", x), "known_aircraft": lambda x: _known("aircraft", x),
                     "iif": lambda cond, a, b: a if _truthy(cond) else b})
workdb._ARITY.update({"valid_date": 3, "future_date": 3, "num": 1, "matches": 2, "length": 1, "has_stray_spaces": 1,
                      "exercise_issues": 1, "known_location": 1, "known_airport": 1, "known_aircraft": 1, "iif": 3})


def location_codes():
    """Every code of the Locations table (ICAO, IATA, company code, display); None when the table is not available."""
    try:
        from .refdata import list_locations
        return {text(a[c]).strip().upper() for a in list_locations() for c in ("icao_code", "iata_code", "company_code", "display") if a[c]}
    except Exception:
        return None


def aircraft_codes():
    """Designators and display names of the Aircraft table (global database); None when the table is not available."""
    try:
        from .refdata import list_aircraft_types
        return {text(t[c]).strip().upper() for t in list_aircraft_types() for c in ("designator", "display") if t[c]}
    except Exception:
        return None


def mtow_mismatches(tolerance=0.01):
    """Aircraft whose MTOW in lb and in kg do not agree (both are entered by hand and must be official values)."""
    try:
        from .refdata import list_aircraft_types, LB_PER_KG
        rows = list_aircraft_types()
    except Exception:
        return []
    return [f"{t['designator']} : {t['mtow_lb']:g} lb is {t['mtow_lb'] / LB_PER_KG:.0f} kg, the table says {t['mtow_kg']:g} kg"
            for t in rows if t["mtow_lb"] and t["mtow_kg"] and abs(t["mtow_lb"] / LB_PER_KG - t["mtow_kg"]) > tolerance * t["mtow_kg"]]


# ---------------- the rule files ----------------
def edited_dir():
    try:
        from .db import appdata_root
        return appdata_root() / "audit"
    except RuntimeError:
        return None


def audit_ids():
    ids = set()
    for folder in (BUNDLED_DIR, edited_dir()):
        if folder is not None and folder.is_dir():
            ids |= {p.stem for p in folder.glob("*.yml")}
    return sorted(i for i in ids if FILE_ID.fullmatch(i))


def audit_path(file_id):
    edited = edited_dir()
    if edited is not None and (edited / f"{file_id}.yml").is_file():
        return edited / f"{file_id}.yml"
    return BUNDLED_DIR / f"{file_id}.yml"


def _expr(value, where):
    if not isinstance(value, (str, int, float, bool)) or value == "":
        raise workdb.SpecError(f"{where}: an expression is required.")
    return workdb._compile(value, where)


def _template(value, where):
    """Message split into text and {expression} parts."""
    parts, last = [], 0
    value = str(value)
    for m in re.finditer(r"\{([^{}]+)\}", value):
        parts.append(("t", value[last:m.start()]))
        parts.append(("e", workdb._compile(m.group(1), f"{where} (message)")))
        last = m.end()
    parts.append(("t", value[last:]))
    return parts


RULE_KEYS = {"name", "severity", "when", "message", "each", "skipped_rows"}
GROUP_KEYS = {"name", "severity", "kind", "where", "group_by", "distinct", "allowed_sets", "columns", "key", "ignore_values"}
TOP_KEYS = {"name", "params", "lists", "vars", "skip_rows", "rules", "group_rules"}


def _severity(item, where):
    if item.get("severity") not in SEVERITY_ORDER:
        raise workdb.SpecError(f"{where}: severity must be ERROR, ANOMALY or INFO.")
    return item["severity"]


def parse_audit(data):
    """Validates and compiles one audit file; raises workdb.SpecError with a readable message."""
    if not isinstance(data, dict):
        raise workdb.SpecError("The file must contain “rules” and/or “group_rules” (see the shipped files).")
    unknown = set(data) - TOP_KEYS
    if unknown:
        raise workdb.SpecError(f"Unknown key “{sorted(unknown)[0]}” (allowed: {', '.join(sorted(TOP_KEYS))}).")
    out = {"params": {}, "lists": {}, "vars": [], "skips": [], "rules": [], "group_rules": []}
    params = data.get("params") or {}
    if not isinstance(params, dict) or not all(isinstance(v, (int, float, str, bool)) for v in params.values()):
        raise workdb.SpecError("“params” must map a name to a number or a text.")
    out["params"] = {str(k).lower(): v for k, v in params.items()}
    lists = data.get("lists") or {}
    if not isinstance(lists, dict) or not all(isinstance(v, list) for v in lists.values()):
        raise workdb.SpecError("“lists” must map a name to a list of columns.")
    out["lists"] = {str(k): [str(c) for c in v] for k, v in lists.items()}
    vars_ = data.get("vars") or {}
    if not isinstance(vars_, dict):
        raise workdb.SpecError("“vars” must map a name to an expression.")
    out["vars"] = [(str(k).lower(), _expr(v, f"vars.{k}")) for k, v in vars_.items()]
    skips = data.get("skip_rows") or []
    for i, e in enumerate(skips if isinstance(skips, list) else [skips], 1):
        out["skips"].append(_expr(e, f"skip_rows #{i}"))
    for i, rule in enumerate(data.get("rules") or [], 1):
        where = f"rule #{i}"
        if not isinstance(rule, dict) or not rule.get("name"):
            raise workdb.SpecError(f"{where}: each rule needs a “name”.")
        where = f"rule “{rule['name']}”"
        if set(rule) - RULE_KEYS:
            raise workdb.SpecError(f"{where}: unknown key “{sorted(set(rule) - RULE_KEYS)[0]}”.")
        each = rule.get("each")
        if each is not None and not (isinstance(each, str) or (isinstance(each, list) and all(isinstance(c, str) for c in each))):
            raise workdb.SpecError(f"{where}: “each” is a list of columns or the name of a list.")
        out["rules"].append({"name": str(rule["name"]), "sev": _severity(rule, where), "when": _expr(rule.get("when"), f"{where} (when)"),
                             "message": _template(rule.get("message", ""), where), "each": each, "skipped": bool(rule.get("skipped_rows"))})
    for i, rule in enumerate(data.get("group_rules") or [], 1):
        if not isinstance(rule, dict) or not rule.get("name"):
            raise workdb.SpecError(f"group rule #{i}: each rule needs a “name”.")
        where = f"group rule “{rule['name']}”"
        if set(rule) - GROUP_KEYS:
            raise workdb.SpecError(f"{where}: unknown key “{sorted(set(rule) - GROUP_KEYS)[0]}”.")
        kind = rule.get("kind")
        if kind == "one_to_many":
            if not (rule.get("group_by") and rule.get("distinct")):
                raise workdb.SpecError(f"{where}: one_to_many needs “group_by” and “distinct” (columns).")
        elif kind == "spellings":
            if not (isinstance(rule.get("columns"), list) and rule["columns"]) or rule.get("key", "alnum") not in ("alnum", "letters"):
                raise workdb.SpecError(f"{where}: spellings needs “columns” (a list) and key alnum or letters.")
        else:
            raise workdb.SpecError(f"{where}: kind must be one_to_many or spellings.")
        out["group_rules"].append({**rule, "sev": _severity(rule, where), "kind": kind,
                                   "where_ast": _expr(rule["where"], f"{where} (where)") if rule.get("where") else None})
    return out


def load_rules():
    """Merged rules of every file, and the problems met while reading them."""
    spec = {"params": {}, "lists": {}, "vars": [], "skips": [], "rules": [], "group_rules": []}
    problems = []
    for file_id in audit_ids():
        try:
            part = parse_audit(yaml.safe_load(audit_path(file_id).read_text(encoding="utf-8")))
        except (OSError, yaml.YAMLError, workdb.SpecError) as exc:
            problems.append(f"{file_id}.yml : {exc}")
            continue
        spec["params"].update(part["params"]); spec["lists"].update(part["lists"])
        for key in ("vars", "skips", "rules", "group_rules"):
            spec[key] += part[key]
    return spec, problems


# ---------------- checks ----------------
def _fmt(v):
    if v is None:
        return ""
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, float):
        return f"{v:g}"
    return str(v)


def _truthy(v):
    return bool(v) and not (isinstance(v, str) and not v.strip())


def row_date(r):
    try:
        return _date(r.get("year"), r.get("month"), r.get("day"))
    except (TypeError, ValueError):
        return None


def run_checks(rows, today=None):
    _STATE.update(today=today or date.today(), locations=location_codes(), aircraft=aircraft_codes())
    spec, problems = load_rules()
    findings = [{"sev": "ERROR", "cat": "Audit rule problem", "date": "", "label": "audit/", "msg": p} for p in problems]
    unknown, failed = set(), set()

    def warn(message):
        m = re.search(r"“([^”]+)”", message)
        unknown.add(m.group(1) if m else message)

    def ev(tree, env, where):
        try:
            return workdb._eval(tree, env, warn)
        except workdb.ExprError as exc:
            if where not in failed:
                failed.add(where)
                findings.append({"sev": "ERROR", "cat": "Audit rule problem", "date": "", "label": "audit/", "msg": f"{where} : {exc}"})
            return None

    def render(parts, env, where):
        return "".join(v if k == "t" else _fmt(ev(v, env, where)) for k, v in parts)

    envs = []
    for r in rows:
        env = dict(spec["params"])
        env.update({str(k).lower(): v for k, v in r.items()})
        for name, tree in spec["vars"]:
            env[name] = ev(tree, env, f"variable {name}")
        skipped = any(_truthy(ev(t, env, "skip_rows")) for t in spec["skips"])
        envs.append((r, env, skipped))
        route = f"{text(r.get('departure_code'))}→{text(r.get('arrival_code'))}" if r.get("departure_code") or r.get("arrival_code") else ""
        label = " ".join(x for x in (text(r.get("registration")).strip(), route, text(r.get("remarks")).strip()[:40]) if x)
        d = row_date(r)
        for rule in spec["rules"]:
            if rule["skipped"] != skipped:
                continue
            each = rule["each"]
            if isinstance(each, str):
                if each not in spec["lists"]:
                    if rule["name"] not in failed:
                        failed.add(rule["name"])
                        findings.append({"sev": "ERROR", "cat": "Audit rule problem", "date": "", "label": "audit/", "msg": f"rule “{rule['name']}” : unknown list “{each}”."})
                    continue
                each = spec["lists"][each]
            for column in (each if each is not None else [None]):
                e = env if column is None else {**env, "column": column, "value": env.get(column.lower())}
                where = f"rule “{rule['name']}”"
                if _truthy(ev(rule["when"], e, where)):
                    findings.append({"sev": rule["sev"], "cat": rule["name"], "date": d.isoformat() if d else "", "label": label,
                                     "msg": render(rule["message"], e, where)})

    live = [env for _r, env, skipped in envs if not skipped]
    for rule in spec["group_rules"]:
        where = f"group rule “{rule['name']}”"
        if rule["where_ast"] is not None:
            pool = [e for e in live if _truthy(ev(rule["where_ast"], e, where))]
        else:
            pool = live
        if rule["kind"] == "one_to_many":
            allowed = [{str(x).upper() for x in s} for s in rule.get("allowed_sets") or []]
            buckets = defaultdict(set)
            for e in pool:
                key, val = text(e.get(str(rule["group_by"]).lower())).strip().upper(), text(e.get(str(rule["distinct"]).lower())).strip()
                if key and val:
                    buckets[key].add(val)
            for key, vals in sorted(buckets.items()):
                if len(vals) > 1 and not any({v.upper() for v in vals} <= s for s in allowed):
                    findings.append({"sev": rule["sev"], "cat": rule["name"], "date": "", "label": "several rows", "msg": f"{key} : {' / '.join(sorted(vals))}"})
        else:
            ignore = {str(x).upper() for x in rule.get("ignore_values") or []}
            kf = (lambda v: re.sub(r"[^A-Z0-9]", "", v.upper())) if rule.get("key", "alnum") == "alnum" else name_key
            forms = defaultdict(set)
            for e in pool:
                for c in rule["columns"]:
                    v = text(e.get(str(c).lower())).strip()
                    if v and v.upper() not in ignore and kf(v):
                        forms[kf(v)].add(v)
            for group in forms.values():
                if len(group) > 1:
                    findings.append({"sev": rule["sev"], "cat": rule["name"], "date": "", "label": "several rows", "msg": " / ".join(sorted(group))})
    for name in sorted(unknown):
        findings.append({"sev": "INFO", "cat": "Audit rule problem", "date": "", "label": "audit/",
                         "msg": f"unknown name “{name}” in a rule (not a work data column, parameter or variable)"})
    for msg in mtow_mismatches():
        findings.append({"sev": "ANOMALY", "cat": "MTOW differs between lb and kg", "date": "", "label": "Aircraft table", "msg": msg})
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
    edit_files = []
    if g.get("role") == "admin":
        for file_id in audit_ids():
            try:
                label = str(yaml.safe_load(audit_path(file_id).read_text(encoding="utf-8")).get("name") or file_id)
            except Exception:
                label = file_id
            edit_files.append((f"audit_{file_id}", label))
    return render_template("audit.html", total=len(rows), groups=groups, counts=counts, edit_files=edit_files)
