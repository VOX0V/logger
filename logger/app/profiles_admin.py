"""Import profiles and conversion profiles: list, create, edit, rename, delete and export (administrators only).

An import profile is a file <id>_import.yml (appdata/importer): which header of a company file goes to which entity.
A conversion profile is a file <id>_convert.yml (appdata/workdb): the conversion rules, raw data to work data, of the rows
imported with the import profile <id>; they are tried before the global rules (work_db.yml)."""
import json
import re

import yaml
from flask import Blueprint, Response, abort, flash, redirect, render_template, request, url_for

from . import import_profiles as ip
from . import workdb
from .auth import admin_required
from .importer import FileImportError
from .seclog import log_event

profiles_bp = Blueprint("profiles", __name__, url_prefix="/profiles")

IMPORT_HEADER = ("# Import profile: one line per header of the file, written  header: entity  (entities: see Data > Entities).\n"
                 "# A header that is not listed here is not imported. Managed from Data > Import profiles.\n")
SKELETON = """# Conversion rules for the import profile “__NAME__” (__ID__).
# They are tried before the global rules of work_db.yml: for a work column, the first rule here whose "when" is true and
# whose "value" is not empty gives the value; if there is none, the global rules apply. The columns, their types and
# their order are set on the Data > Work db structure page.
#
# skip_rows:                    # rows of this profile to leave out (added to the global ones)
#   - name: Not operated
#     when: is_blank(time_flight_hhmm)
#
# aircraft_type:                # the name of a work column, then its rules
#   - when: not is_blank(aircraft_type)
#     value: aircraft(aircraft_type, "display")
"""


def _folder():
    folder = ip.edited_dir()
    if folder is None:
        abort(500)
    folder.mkdir(parents=True, exist_ok=True)
    ip.profile_ids()                        # the shipped profiles are copied here the first time
    return folder


def _write(path, text):
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _known(profile_id):
    if not ip.PROFILE_ID.fullmatch(profile_id or "") or profile_id not in ip.profile_ids():
        abort(404)


def _attachment(text, filename):
    return Response(text, mimetype="text/yaml", headers={"Content-Disposition": f'attachment; filename="{filename}"'})


def _load_data(profile_id):
    try:
        data = yaml.safe_load(ip.profile_path(profile_id).read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


# ---------------- import profiles ----------------

@profiles_bp.route("/import")
@admin_required
def import_list():
    _folder()
    converts = set(workdb.convert_ids())
    rows = []
    for pid in ip.profile_ids():
        data = _load_data(pid)
        try:
            ip._read(pid)
            error = ""
        except FileImportError as exc:
            error = str(exc)
        columns = data.get("columns")
        rows.append({"id": pid, "name": str(data.get("name") or pid), "sheet": str(data.get("sheet") or ""),
                     "count": len(columns) if isinstance(columns, dict) else 0, "error": error, "convert": pid in converts})
    return render_template("import_profiles.html", rows=rows)


def _entity_choices():
    try:
        entities = ip.load_entities()
    except FileImportError:
        entities = {}
    return [{"label": f"{e} — {v['display_name']}", "value": e} for e, v in entities.items()]


def _parse_rows(raw):
    try:
        rows = json.loads(raw or "[]")
    except ValueError:
        raise ValueError("The columns are not readable.")
    if not isinstance(rows, list):
        raise ValueError("The columns are not readable.")
    return [{"header": str(r.get("header", "")).strip(), "entity": str(r.get("entity", "")).strip()} for r in rows if isinstance(r, dict)]


def _save_import(profile_id, folder):
    name = request.form.get("name", "").strip()
    if not name:
        raise ValueError("The name is required.")
    new_id = request.form.get("id", "").strip().lower() or re.sub(r"[^a-z0-9]+", "", name.lower())
    if not ip.PROFILE_ID.fullmatch(new_id):
        raise ValueError("The identifier only uses lowercase letters, digits, - and _.")
    if new_id != profile_id and (new_id in ip.profile_ids() or workdb.convert_path(new_id).exists()):
        raise ValueError(f"The identifier “{new_id}” is already used.")
    columns = {}
    for row in _parse_rows(request.form.get("columns")):
        if not row["header"] and not row["entity"]:
            continue
        if row["header"] in columns:
            raise ValueError(f"The header “{row['header']}” appears twice.")
        columns[row["header"]] = row["entity"]
    data = {"name": name}
    if request.form.get("sheet", "").strip():
        data["sheet"] = request.form["sheet"].strip()
    data["columns"] = columns
    ignored = [h.strip() for h in request.form.get("ignored", "").splitlines() if h.strip()]
    if ignored:
        data["ignored"] = ignored
    ip.parse_spec(data)                     # raises FileImportError with a readable message
    _write(folder / f"{new_id}{ip.SUFFIX}", IMPORT_HEADER + yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=1000))
    if profile_id and new_id != profile_id:  # renamed: the file and its conversion file follow
        (folder / f"{profile_id}{ip.SUFFIX}").unlink(missing_ok=True)
        old = workdb.convert_path(profile_id)
        if old.is_file():
            old.replace(workdb.convert_path(new_id))
    return new_id


@profiles_bp.route("/import/new", methods=["GET", "POST"])
@profiles_bp.route("/import/<profile_id>/edit", methods=["GET", "POST"])
@admin_required
def import_edit(profile_id=None):
    folder = _folder()
    if profile_id is not None:
        _known(profile_id)
    state = None
    if request.method == "POST":
        try:
            new_id = _save_import(profile_id, folder)
        except (ValueError, FileImportError) as exc:
            flash(str(exc))
            try:
                rows = _parse_rows(request.form.get("columns"))
            except ValueError:
                rows = []
            state = {"name": request.form.get("name", ""), "id": request.form.get("id", ""), "sheet": request.form.get("sheet", ""),
                     "ignored": request.form.get("ignored", ""), "rows": rows}
        else:
            flash(f"Import profile “{new_id}” saved.")
            return redirect(url_for("profiles.import_list"))
    if state is None:
        data = _load_data(profile_id) if profile_id else {}
        columns = data.get("columns") if isinstance(data.get("columns"), dict) else {}
        state = {"name": str(data.get("name") or "") if profile_id else "", "id": profile_id or "", "sheet": str(data.get("sheet") or ""),
                 "ignored": "\n".join(str(h) for h in (data.get("ignored") or [])),
                 "rows": [{"header": str(h), "entity": str(e)} for h, e in columns.items()]}
    return render_template("import_profile_edit.html", state=state, creating=profile_id is None, entities=_entity_choices())


@profiles_bp.route("/import/<profile_id>/delete", methods=["POST"])
@admin_required
def import_delete(profile_id):
    folder = _folder()
    _known(profile_id)
    (folder / f"{profile_id}{ip.SUFFIX}").unlink(missing_ok=True)
    conversion = workdb.convert_path(profile_id)
    if conversion.is_file():
        conversion.unlink()
    log_event("data_destroy", target=f"import-profile:{profile_id}")
    flash(f"Import profile “{profile_id}” deleted (with its conversion file).")
    return redirect(url_for("profiles.import_list"))


@profiles_bp.route("/import/<profile_id>/export")
@admin_required
def import_export(profile_id):
    _folder()
    _known(profile_id)
    return _attachment(ip.profile_path(profile_id).read_text(encoding="utf-8"), f"{profile_id}{ip.SUFFIX}")


# ---------------- conversion profiles ----------------

@profiles_bp.route("/convert")
@admin_required
def convert_list():
    _folder()
    names = {pid: str(_load_data(pid).get("name") or pid) for pid in ip.profile_ids()}
    existing = set(workdb.convert_ids())
    rows = [{"id": pid, "name": names.get(pid, ""), "exists": pid in existing, "orphan": pid not in names}
            for pid in sorted(set(names) | existing)]
    return render_template("conversion_profiles.html", rows=rows)


def _convert_file(profile_id, must_exist=True):
    if not ip.PROFILE_ID.fullmatch(profile_id or ""):
        abort(404)
    path = workdb.convert_path(profile_id)
    if must_exist and not path.is_file():
        abort(404)
    return path


@profiles_bp.route("/convert/<profile_id>/edit", methods=["GET", "POST"])
@admin_required
def convert_edit(profile_id):
    path = _convert_file(profile_id, must_exist=False)
    name = str(_load_data(profile_id).get("name") or profile_id) if profile_id in ip.profile_ids() else profile_id
    if request.method == "POST":
        content = request.form.get("content", "")
        try:
            workdb.check_rules_data(yaml.safe_load(content), f"{profile_id}{workdb.CONVERT_SUFFIX}")
        except yaml.YAMLError as exc:
            flash(f"The file is not valid YAML: {exc}")
        except workdb.SpecError as exc:
            flash(str(exc))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            _write(path, content if content.endswith("\n") else content + "\n")
            flash(f"Conversion profile “{profile_id}” saved.")
            return redirect(url_for("profiles.convert_list"))
    else:
        content = path.read_text(encoding="utf-8") if path.is_file() else SKELETON.replace("__NAME__", name).replace("__ID__", profile_id)
    return render_template("conversion_edit.html", profile_id=profile_id, name=name, content=content, exists=path.is_file())


@profiles_bp.route("/convert/<profile_id>/rename", methods=["POST"])
@admin_required
def convert_rename(profile_id):
    path = _convert_file(profile_id)
    new_id = request.form.get("new_id", "").strip().lower()
    if not ip.PROFILE_ID.fullmatch(new_id):
        flash("The identifier only uses lowercase letters, digits, - and _.")
    elif workdb.convert_path(new_id).exists():
        flash(f"“{new_id}” already has a conversion file.")
    else:
        path.replace(workdb.convert_path(new_id))
        flash(f"Conversion profile renamed to “{new_id}”.")
    return redirect(url_for("profiles.convert_list"))


@profiles_bp.route("/convert/<profile_id>/delete", methods=["POST"])
@admin_required
def convert_delete(profile_id):
    _convert_file(profile_id).unlink()
    log_event("data_destroy", target=f"conversion-profile:{profile_id}")
    flash(f"Conversion profile “{profile_id}” deleted.")
    return redirect(url_for("profiles.convert_list"))


@profiles_bp.route("/convert/<profile_id>/export")
@admin_required
def convert_export(profile_id):
    path = _convert_file(profile_id)
    return _attachment(path.read_text(encoding="utf-8"), path.name)
