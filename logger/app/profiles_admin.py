"""Import profiles and conversion profiles: list, create, edit, rename, delete and export (administrators only).

An import profile is a file <id>_import.yml (appdata/importer): which header of a company file goes to which entity.
A conversion profile is a file <id>_convert.yml (appdata/workdb): the conversion rules, raw data to work data, of the rows
imported with the import profile <id>; they are tried before the global profiles."""
import re

import yaml
from flask import Blueprint, Response, abort, flash, redirect, render_template, request, url_for

from . import import_profiles as ip
from . import workdb, yamledit
from .auth import admin_required
from .importer import FileImportError
from .seclog import log_event

profiles_bp = Blueprint("profiles", __name__, url_prefix="/profiles")

IMPORT_SKELETON = """# Import profile: one line per header of the file, written  header: entity  (entities: see Data > Entities).
# A header that is not listed under "columns" is not imported. The columns of the raw database are created by the import.
name: Company name
columns:
  header_of_the_file: entity

# Optional: rows of the file to import (a row must pass every filter).
# filters:
#   - column: header_of_the_file
#     only: [value1, value2]        # keep only the rows whose value is one of these
#   - column: header_of_the_file
#     only_containing: [text]       # keep only the rows whose value contains one of these texts
#   - column: header_of_the_file
#     exclude: [text]               # leave out the rows whose value contains one of these texts
#   - column: header_of_the_file
#     not_after: today              # leave out the rows whose date is later than today
"""
SKELETON = """# Conversion rules for the import profile “__NAME__” (__ID__).
# They are tried before the rules of the global profiles: for a work column, the first rule here whose "when" is true and
# whose "value" is not empty gives the value; if there is none, the global rules apply. The columns, their types and
# their order are set on the Data > Work DB settings page.
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
        rows.append({"id": pid, "name": str(data.get("name") or pid), "count": len(columns) if isinstance(columns, dict) else 0, "error": error, "convert": pid in converts})
    return render_template("import_profiles.html", rows=rows)


@profiles_bp.route("/import/new", methods=["GET", "POST"])
@profiles_bp.route("/import/<profile_id>/edit", methods=["GET", "POST"])
@admin_required
def import_edit(profile_id=None):
    folder = _folder()
    creating = profile_id is None
    if not creating:
        _known(profile_id)
    posting = request.method == "POST"
    if creating:
        new_id = request.form.get("new_id", "").strip().lower() if posting else ""
        content = request.form.get("content", "") if posting else IMPORT_SKELETON
    else:
        new_id = profile_id
        content = request.form.get("content", "") if posting else ip.profile_path(profile_id).read_text(encoding="utf-8")
    if posting:
        try:
            if creating:
                if not ip.PROFILE_ID.fullmatch(new_id):
                    raise ValueError("The identifier is required and only uses lowercase letters, digits, - and _.")
                if new_id in ip.profile_ids() or workdb.convert_path(new_id).exists():
                    raise ValueError(f"The identifier “{new_id}” is already used.")
            ip.parse_spec(yamledit.parse(content))
        except (yamledit.Problem, ValueError, FileImportError) as exc:
            flash(str(exc))
        else:
            _write(folder / f"{new_id}{ip.SUFFIX}", content if content.endswith("\n") else content + "\n")
            flash(f"Import profile “{new_id}” saved.")
            return redirect(url_for("profiles.import_list"))
    return render_template("import_profile_edit.html", profile_id=profile_id, new_id=new_id, content=content, creating=creating)


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
    return render_template("conversion_profiles.html", rows=rows, global_profiles=global_rows())


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


# ---------------- global profiles: files <id>_global.yml (create, import, edit, export, delete) ----------------

GLOBAL_SKELETON = """# Global profile “__ID__”: conversion rules, raw data to work data. Every key is the name of a work column followed by
# its list of rules (the expressions that can be used are listed in the General profile). Rules of the conversion profile
# of the company are tried first; then the rules of all the global profiles, in the order of the list.
#
# aircraft_type:                # the name of a work column, then its rules
#   - when: not is_blank(aircraft_type)
#     value: aircraft(aircraft_type, "display")
"""


def _gpath(gid, must_exist=True):
    path = workdb.global_path(gid)
    if path is None or not workdb.PROFILE_ID.fullmatch(gid or "") or (must_exist and not path.is_file()):
        abort(404)
    return path


def _check_global(gid, content):
    """Validate the text of a global profile; raises yamledit.Problem or workdb.SpecError (messages meant for the page)."""
    if all(not line.strip() or line.lstrip().startswith("#") for line in content.splitlines()):
        if len(content.encode("utf-8")) > yamledit.MAX_BYTES:
            raise yamledit.Problem("File too large (256 KB maximum).")
        data = {}
    else:
        data = yamledit.parse(content)
    workdb.check_rules_data(data, f"{gid}{workdb.GLOBAL_SUFFIX}")


def global_rows():
    return [{"id": gid, "title": workdb.GLOBAL_TITLES.get(gid, gid), "file": path.name} for gid, path in workdb.global_files()]


@profiles_bp.route("/global/new", methods=["GET", "POST"])
@profiles_bp.route("/global/<gid>/edit", methods=["GET", "POST"])
@admin_required
def global_edit(gid=None):
    creating = gid is None
    if creating:
        new_id = request.form.get("new_id", "").strip().lower() if request.method == "POST" else ""
        content = request.form.get("content", "") if request.method == "POST" else GLOBAL_SKELETON.replace("__ID__", "name")
        path = None
    else:
        path = _gpath(gid)
        new_id = gid
        content = request.form.get("content", "") if request.method == "POST" else path.read_text(encoding="utf-8")
    if request.method == "POST":
        try:
            if creating:
                if not workdb.PROFILE_ID.fullmatch(new_id):
                    raise workdb.SpecError("The identifier is required and only uses lowercase letters, digits, - and _.")
                path = _gpath(new_id, must_exist=False)
                if path.exists():
                    raise workdb.SpecError(f"“{new_id}” already exists.")
            _check_global(new_id, content)
        except (yamledit.Problem, workdb.SpecError) as exc:
            flash(str(exc))
        else:
            _write(path, content if content.endswith("\n") else content + "\n")
            flash(f"Global profile “{new_id}” saved.")
            return redirect(url_for("profiles.convert_list"))
    return render_template("global_edit.html", gid=gid, new_id=new_id, content=content, creating=creating)


@profiles_bp.route("/global/import", methods=["POST"])
@admin_required
def global_import():
    file = request.files.get("file")
    name = (file.filename or "") if file else ""
    stem, dot, ext = name.rpartition(".")
    if not file or not dot or ext.lower() not in ("yml", "yaml"):
        flash("Choose a .yml file.")
        return redirect(url_for("profiles.convert_list"))
    gid = re.sub(r"[^a-z0-9_-]+", "-", stem.lower()).strip("-")
    if gid.endswith("_global"):
        gid = gid[:-len("_global")]
    try:
        if not workdb.PROFILE_ID.fullmatch(gid):
            raise workdb.SpecError("The file name must give an identifier (letters, digits, - and _).")
        raw = file.read(yamledit.MAX_BYTES + 1)
        try:
            content = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise workdb.SpecError("The file must be UTF-8 text.")
        path = _gpath(gid, must_exist=False)
        if path.exists():
            raise workdb.SpecError(f"A global profile “{gid}” already exists: delete it first, or rename the file.")
        _check_global(gid, content)
    except (yamledit.Problem, workdb.SpecError) as exc:
        flash(f"Import refused: {exc}")
    else:
        _write(path, content if content.endswith("\n") else content + "\n")
        flash(f"Global profile “{gid}” imported.")
    return redirect(url_for("profiles.convert_list"))


@profiles_bp.route("/global/<gid>/export")
@admin_required
def global_export(gid):
    path = _gpath(gid)
    return _attachment(path.read_text(encoding="utf-8"), path.name)


@profiles_bp.route("/global/<gid>/delete", methods=["POST"])
@admin_required
def global_delete(gid):
    _gpath(gid).unlink()
    log_event("data_destroy", target=f"global-profile:{gid}")
    flash(f"Global profile “{gid}” deleted.")
    return redirect(url_for("profiles.convert_list"))
