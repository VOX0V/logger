"""Definition of the work data (logbook table) from one YAML file: defaults/work_db.yml.

Each key "<position>_<name>" is a column; its "rules" are tried in order and the first one that gives a
non-empty value wins. Expressions are evaluated by a small whitelisted interpreter (no eval): the YAML
file can hold conditions and formulas without any code change. A copy edited in the web interface lives
in appdata/workdb/work_db.yml and wins over the file shipped with the app."""
import ast
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


def _date_part(v, index):
    m = re.match(r"\s*(\d{4})-(\d{2})-(\d{2})", "" if v is None else str(v))
    return int(m.group(index)) if m else None


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


FUNCS = {
    "is_blank": lambda x: _blank(x),
    "year_of": lambda x: _date_part(x, 1),
    "month_of": lambda x: _date_part(x, 2),
    "day_of": lambda x: _date_part(x, 3),
    "is_zero_time": _is_zero_time,
    "has_word": _has_word,
}
_ARITY = {"is_blank": 1, "year_of": 1, "month_of": 1, "day_of": 1, "is_zero_time": 1, "has_word": 2}
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


def _eval(node, env, warn):
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        key = node.id.lower()
        if key not in env:
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
        return FUNCS[node.func.id](*[_eval(a, env, warn) for a in node.args])
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
    return {"skip": skip, "columns": columns}


def load_spec():
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
                break
    return out
