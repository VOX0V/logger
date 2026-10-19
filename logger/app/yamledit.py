"""Éditeur de fichiers YAML dans l'interface web, à la manière de Home Assistant.

Chaque utilisateur édite uniquement SES fichiers (la liste est fixe : aucun chemin n'est jamais
lu dans la requête). Avant d'enregistrer, le contenu est vérifié : YAML valide, puis structure
attendue par l'application. L'ancienne version est gardée dans <fichier>.bak."""
import os
import shutil

import yaml
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort

from . import config as C
from .auth import login_required
from .db import current_username
from .seclog import log_event
from . import cssafe
from .models import init_user_db

yaml_bp = Blueprint("yamledit", __name__, url_prefix="/config")

MAX_BYTES = 256 * 1024
RESERVED = {"id", "created_at", "updated_at", "import_source"}
DATA_TYPES = {"integer", "decimal", "boolean", "date", "datetime", "text"}


class Problem(Exception):
    pass


def _number(value, label, minimum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise Problem(f"{label} doit être un nombre.")
    if minimum is not None and value < minimum:
        raise Problem(f"{label} doit être au moins {minimum}.")


def parse(text):
    if len(text.encode("utf-8")) > MAX_BYTES:
        raise Problem("Fichier trop volumineux (256 Ko maximum).")
    try:
        for event in yaml.parse(text, Loader=yaml.SafeLoader):      # ancres/alias interdits : bombes d'expansion (« billion laughs »)
            if isinstance(event, yaml.AliasEvent) or getattr(event, "anchor", None):
                raise Problem("Les ancres et alias YAML (&nom, *nom) ne sont pas autorisés.")
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        where = f"ligne {mark.line + 1}, colonne {mark.column + 1} : " if mark else ""
        raise Problem(f"YAML invalide — {where}{getattr(exc, 'problem', None) or exc}")
    if not isinstance(data, dict):
        raise Problem("Le fichier doit commencer par des clés (clé: valeur), pas par une liste ni du texte.")
    return data


def _columns_of(data):
    db = data.get("database", data)
    cols = db.get("columns") if isinstance(db, dict) else None
    if not isinstance(cols, list) or not cols or not all(isinstance(c, dict) for c in cols):
        raise Problem("« columns » doit être une liste non vide de colonnes (chaque colonne est un bloc clé: valeur).")
    return cols


def check_structure(data, normalize):
    seen = set()
    for i, raw in enumerate([c for c in _columns_of(data) if c.get("group") != "system"], 1):
        try:
            col = normalize(raw, i)["column"]
        except (ValueError, KeyError, TypeError) as exc:
            raise Problem(f"Colonne n°{i} ({raw.get('column') or raw.get('display_name') or '?'}) : {exc}")
        if col in RESERVED:
            raise Problem(f"Colonne n°{i} : le nom « {col} » est réservé.")
        if col in seen:
            raise Problem(f"Colonne en double : « {col} ».")
        if str(raw.get("data_type", "text")).lower() not in DATA_TYPES:
            raise Problem(f"Colonne « {col} » : data_type doit être parmi {', '.join(sorted(DATA_TYPES))}.")
        seen.add(col)
    if not seen:
        raise Problem("Il faut au moins une colonne de données (en plus des colonnes système).")


def check_data(data): check_structure(data, C._norm_user)
def check_logbook(data): check_structure(data, C._norm_lb)


def check_layout(data):
    problems = cssafe.layout_problems(data)
    if problems:
        raise Problem(" ".join(problems))
    if "rows_per_page" in data:
        _number(data["rows_per_page"], "rows_per_page", 1)
    if "row_height" in data:
        _number(data["row_height"], "row_height", 1)
    if "gap_widths" in data:
        gw = data["gap_widths"]
        if not isinstance(gw, list) or len(gw) != 2:
            raise Problem("gap_widths doit contenir exactement 2 largeurs (les deux colonnes vides).")
        for w in gw: _number(w, "gap_widths", 0)
    for name in ("columns", "physical_columns"):
        if name in data:
            items = data[name]
            if not isinstance(items, list) or not all(isinstance(x, dict) for x in items):
                raise Problem(f"« {name} » doit être une liste de blocs clé: valeur.")
    for i, col in enumerate(data.get("physical_columns", []), 1):
        if "width" not in col: raise Problem(f"physical_columns n°{i} : « width » manquant.")
        _number(col["width"], f"physical_columns n°{i} : width", 0)
    for i, col in enumerate(data.get("columns", []), 1):
        if not isinstance(col.get("key"), str) or not col["key"]:
            raise Problem(f"columns n°{i} : « key » manquant.")
    styles = data.get("styles", {})
    if not isinstance(styles, dict):
        raise Problem("« styles » doit être un bloc clé: valeur.")
    if "width_scale" in styles: _number(styles["width_scale"], "styles.width_scale", 0.1)
    for i, b in enumerate(styles.get("data_blocks", []), 1):
        if not isinstance(b, dict) or not isinstance(b.get("color"), str) or isinstance(b.get("rows"), bool) or not isinstance(b.get("rows"), int):
            raise Problem(f"styles.data_blocks n°{i} : il faut « rows » (entier) et « color » (ex. '#f1dddd').")


def check_view(data):
    cols = data.get("columns")
    if not isinstance(cols, list) or not all(isinstance(c, dict) and isinstance(c.get("column"), str) for c in cols):
        raise Problem("« columns » doit être une liste de blocs avec au moins « column: nom ».")
    for c in cols:
        if "width" in c:
            _number(c["width"], f"{c['column']} : width", 20)
        if c.get("align", "left") not in ("left", "center", "right"):
            raise Problem(f"{c['column']} : align doit être left, center ou right.")
        if "frozen" in c and not isinstance(c["frozen"], bool):
            raise Problem(f"{c['column']} : frozen doit être true ou false.")


# clé -> (libellé, fonction qui donne le chemin du fichier de l'utilisateur, vérification)
FILES = {
    "data": ("Données brutes — structure", C.config_path, check_data),
    "data_view": ("Données brutes — affichage", C.data_view_path, check_view),
    "logbook": ("Données converties — structure", C.logbook_db_config_path, check_logbook),
    "logbook_view": ("Données converties — affichage", C.logbook_view_path, check_view),
    "layout": ("Logbook — mise en page", C.logbook_layout_path, check_layout),
}


def validate(key, text):
    """Retourne None si le contenu est valable, sinon le message d'erreur."""
    try:
        FILES[key][2](parse(text))
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
    if key not in FILES:
        abort(404)
    _ensure_files(username)
    label, path_of, _check = FILES[key]
    path = path_of(username)
    backup = _backup_path(path)
    content = path.read_text(encoding="utf-8")
    error = None
    if request.method == "POST":
        action = request.form.get("action", "validate")
        posted = request.form.get("content", "").replace("\r\n", "\n")
        if action == "restore":
            if backup.exists():
                content = backup.read_text(encoding="utf-8")
                flash("Sauvegarde précédente chargée dans l'éditeur — clique sur Enregistrer pour l'appliquer.")
            else:
                flash("Aucune sauvegarde disponible pour ce fichier.")
        else:
            content = posted
            error = validate(key, posted)
            if error is None and action == "validate":
                flash("Fichier valide.")
            elif error is None and action == "save":
                shutil.copyfile(path, backup)                      # l'ancienne version est gardée
                tmp = path.with_name(path.name + ".tmp")
                tmp.write_text(posted, encoding="utf-8")
                os.replace(tmp, path)
                if key in ("data", "logbook"):
                    init_user_db(username)                         # ajoute les nouvelles colonnes aux bases
                log_event("config_change", target=f"yaml:{key}")
                flash("Fichier enregistré. L'ancienne version est gardée (bouton « Restaurer »).")
                return redirect(url_for("yamledit.editor", file=key))
    return render_template("config_editor.html", files=FILES, key=key, label=label, content=content, error=error,
                           has_backup=backup.exists(), filename=path.name)
