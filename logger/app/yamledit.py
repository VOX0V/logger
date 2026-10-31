"""Éditeur de fichiers YAML dans l'interface web, à la manière de Home Assistant.

Chaque utilisateur édite uniquement SES fichiers (la liste est fixe : aucun chemin n'est jamais
lu dans la requête). Avant d'enregistrer, le contenu est vérifié : YAML valide, puis structure
attendue par l'application. L'ancienne version est gardée dans <fichier>.bak."""
import os
import shutil

import yaml
from flask import Blueprint, g, render_template, request, redirect, url_for, flash, abort

from . import config as C
from .auth import login_required
from .db import current_username
from .seclog import log_event
from . import cssafe
from .converter.profiles import BUNDLED_DIR, PROFILE_ID, edited_dir
from .converter.transforms import FUNCTIONS
from .models import init_user_db

yaml_bp = Blueprint("yamledit", __name__, url_prefix="/config")

MAX_BYTES = 256 * 1024
RESERVED = {"id", "created_at", "updated_at", "import_source"}
DATA_TYPES = {"integer", "decimal", "boolean", "date", "datetime", "text"}


class Problem(Exception):
    pass


def _number(value, label, minimum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise Problem(f"{label} must be a number.")
    if minimum is not None and value < minimum:
        raise Problem(f"{label} must be at least {minimum}.")


def parse(text):
    if len(text.encode("utf-8")) > MAX_BYTES:
        raise Problem("File too large (256 KB maximum).")
    try:
        for event in yaml.parse(text, Loader=yaml.SafeLoader):      # ancres/alias interdits : bombes d'expansion (“billion laughs”)
            if isinstance(event, yaml.AliasEvent) or getattr(event, "anchor", None):
                raise Problem("YAML anchors and aliases (&name, *name) are not allowed.")
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        where = f"line {mark.line + 1}, column {mark.column + 1} : " if mark else ""
        raise Problem(f"Invalid YAML — {where}{getattr(exc, 'problem', None) or exc}")
    except RecursionError:
        raise Problem("YAML nested too deeply.")
    if not isinstance(data, dict):
        raise Problem("The file must start with keys (key: value), not with a list or text.")
    return data


def _columns_of(data):
    db = data.get("database", data)
    cols = db.get("columns") if isinstance(db, dict) else None
    if not isinstance(cols, list) or not cols or not all(isinstance(c, dict) for c in cols):
        raise Problem("“columns” must be a non-empty list of columns (each column is a key: value block).")
    return cols


def check_structure(data, normalize):
    seen = set()
    for i, raw in enumerate([c for c in _columns_of(data) if c.get("group") != "system"], 1):
        try:
            col = normalize(raw, i)["column"]
        except (ValueError, KeyError, TypeError) as exc:
            raise Problem(f"Column no.{i} ({raw.get('column') or raw.get('display_name') or '?'}) : {exc}")
        if col in RESERVED:
            raise Problem(f"Column no.{i} : the name “ {col} ” is reserved.")
        if col in seen:
            raise Problem(f"Duplicate column: “ {col}”.")
        if str(raw.get("data_type", "text")).lower() not in DATA_TYPES:
            raise Problem(f"Column “ {col} ”: data_type must be one of {', '.join(sorted(DATA_TYPES))}.")
        seen.add(col)
    if not seen:
        raise Problem("At least one data column is required (in addition to the system columns).")


def check_data(data): check_structure(data, C._norm_user)
def check_logbook(data): check_structure(data, C._norm_lb)


def check_layout(data):
    if "rows_per_page" in data:
        _number(data["rows_per_page"], "rows_per_page", 1)
    if "row_height_u" in data:
        _number(data["row_height_u"], "row_height_u", 5)
    if "columns" in data:
        items = data["columns"]
        if not isinstance(items, list) or not all(isinstance(x, dict) for x in items):
            raise Problem("“columns” must be a list of key: value blocks.")
    for i, col in enumerate(data.get("columns", []), 1):
        if "width" in col: _number(col["width"], f"columns n°{i} : width", 0)
    for i, col in enumerate(data.get("columns", []), 1):
        if not isinstance(col.get("key"), str) or not col["key"]:
            raise Problem(f"columns n°{i} : “key” manquant.")
    styles = data.get("styles", {})
    if not isinstance(styles, dict):
        raise Problem("“styles” must be a key: value block.")
    for i, b in enumerate(styles.get("data_blocks", []), 1):
        if not isinstance(b, dict) or not isinstance(b.get("color"), str) or isinstance(b.get("rows"), bool) or not isinstance(b.get("rows"), int):
            raise Problem(f"styles.data_blocks no.{i} : “rows” (integer) and “color” (e.g. #f1dddd) are required.")
    problems = cssafe.layout_problems(data)          # sécurité : après les contrôles d'origine, pour garder leurs messages
    if problems:
        raise Problem(" ".join(problems))


def check_breakdown(data):
    if not isinstance(data, dict):
        raise Problem("The file must be a key: value block.")
    problems = cssafe.breakdown_problems(data)
    if problems:
        raise Problem(" ".join(problems))


def check_view(data):
    cols = data.get("columns")
    if not isinstance(cols, list) or not all(isinstance(c, dict) and isinstance(c.get("column"), str) for c in cols):
        raise Problem("“columns” must be a list of blocks with at least “column: name”.")
    for c in cols:
        if "width" in c:
            _number(c["width"], f"{c['column']} : width", 20)
        if c.get("align", "left") not in ("left", "center", "right"):
            raise Problem(f"{c['column']} : align must be left, center or right.")
        if "frozen" in c and not isinstance(c["frozen"], bool):
            raise Problem(f"{c['column']} : frozen must be true or false.")


# clé -> (libellé, fonction qui donne le chemin du fichier de l'utilisateur, vérification)
FILES = {
    "data": ("Raw data — structure", C.config_path, check_data),
    "data_view": ("Raw data — display", C.data_view_path, check_view),
    "logbook": ("Work data — structure", C.logbook_db_config_path, check_logbook),
    "logbook_view": ("Work data — display", C.logbook_view_path, check_view),
    "layout": ("Logbook — layout", C.logbook_layout_path, check_layout),
    "breakdown": ("Breakdown — layout", C.breakdown_path, check_breakdown),
}


def check_convert(data):
    rules = data.get("rules")
    if not isinstance(rules, list) or not all(isinstance(r, dict) and r.get("id") and r.get("transform") for r in rules):
        raise Problem("“rules” must be a list of blocks that each have at least “id” and “transform”.")
    for r in rules:
        if r["transform"] not in FUNCTIONS:
            raise Problem(f"{r['id']} : unknown transform “{r['transform']}”.")


def converter_files():
    """Conversion profiles (<id>_convert.yml), shared by all accounts: the list comes from the folders, never from the request."""
    ids = set()
    for folder in (BUNDLED_DIR, edited_dir()):
        if folder is not None and folder.is_dir():
            ids |= {p.name[:-len("_convert.yml")] for p in folder.glob("*_convert.yml")}
    out = {}
    for pid in sorted(i for i in ids if PROFILE_ID.fullmatch(i)):
        edited = edited_dir() / f"{pid}_convert.yml"
        out[f"convert_{pid}"] = (f"Converter — {pid}", lambda _u, e=edited, b=BUNDLED_DIR / f"{pid}_convert.yml": e if e.is_file() else b, check_convert)
    return out


def _registry():
    """Files the current account may edit: its own YAML files, plus the converter profiles for administrators."""
    files = dict(FILES)
    if g.get("role") == "admin":
        files.update(converter_files())
    return files


def _write_target(key, path):
    """Where a save goes: converter profiles are saved to a writable copy in appdata (the shipped file stays untouched)."""
    if key.startswith("convert_"):
        folder = edited_dir()
        folder.mkdir(parents=True, exist_ok=True)
        return folder / path.name
    return path


def validate(key, text):
    """Retourne None si le contenu est valable, sinon le message d'erreur."""
    try:
        (FILES.get(key) or converter_files()[key])[2](parse(text))
    except Problem as exc:
        return str(exc)
    return None


def _ensure_files(username):
    C.ensure_configs(username)
    C.load_data_view(C.load_config(username), username)
    C.load_logbook_view(username)


def _backup_path(path):
    return path.with_name(path.name + ".bak")


@yaml_bp.route("", methods=["GET", "POST"])
@login_required
def editor():
    username = current_username()
    key = request.values.get("file", "data")
    files = _registry()
    if key not in files:
        abort(404)
    _ensure_files(username)
    label, path_of, _check = files[key]
    path = path_of(username)
    target = _write_target(key, path)
    backup = _backup_path(target)
    content = path.read_text(encoding="utf-8")
    error = None
    if request.method == "POST":
        action = request.form.get("action", "validate")
        posted = request.form.get("content", "").replace("\r\n", "\n")
        if action == "restore":
            if backup.exists():
                content = backup.read_text(encoding="utf-8")
                flash("Previous backup loaded in the editor — click Save to apply it.")
            else:
                flash("No backup available for this file.")
        else:
            content = posted
            error = validate(key, posted)
            if error is None and action == "validate":
                flash("Valid file.")
            elif error is None and action == "save":
                shutil.copyfile(path, backup)                      # the previous version is kept
                tmp = target.with_name(target.name + ".tmp")
                tmp.write_text(posted, encoding="utf-8")
                os.replace(tmp, target)
                if key in ("data", "logbook"):
                    init_user_db(username)                         # ajoute les nouvelles colonnes aux bases
                log_event("config_change", target=f"yaml:{key}")
                flash("File saved. The previous version is kept (“Restore” button).")
                return redirect(url_for("yamledit.editor", file=key))
    return render_template("config_editor.html", files=files, key=key, label=label, content=content, error=error,
                           has_backup=backup.exists(), filename=path.name)
