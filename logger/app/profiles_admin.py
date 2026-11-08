"""Import profiles and conversion profiles: list, create, edit, rename, delete and export (administrators only).

An import profile is a file <id>_import.yml (appdata/importer): which header of a company file goes to which entity.
A conversion profile is a file <id>_convert.yml (appdata/workdb): the conversion rules, raw data to work data, of the rows
imported with the import profile <id>; they are tried before the global profiles."""
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


# ---------------- global profiles (General, Dates, Aircraft, Crew, Routes, Times) ----------------

def _gpath(gid):
    path = workdb.global_path(gid)
    if path is None or not workdb.PROFILE_ID.fullmatch(gid or "") or not path.is_file():
        abort(404)
    return path


def _gdata(path):
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


def _column_of(key):
    """Normalised column name of a key (the old form <number>_<name> is still read)."""
    m = workdb.KEY.fullmatch(str(key))
    return re.sub(r"[^a-z0-9]+", "_", (m.group(2) if m else str(key)).lower()).strip("_")


def _key_for(data, column):
    return next((k for k in data if k == column or (k != "skip_rows" and _column_of(k) == column)), column)


def _blocks(data, key, create=False):
    """The list of rules of a key (a reference into data)."""
    body = data.get(key)
    if isinstance(body, dict):
        if create and not isinstance(body.get("rules"), list):
            body["rules"] = []
        return body.get("rules") if isinstance(body.get("rules"), list) else []
    if isinstance(body, list):
        return body
    if create:
        data[key] = []
        return data[key]
    return []


def _gentries(data):
    out = []
    for key in data:
        for i, rule in enumerate(_blocks(data, key)):
            if isinstance(rule, dict):
                out.append({"key": key, "column": "skip_rows" if key == "skip_rows" else _column_of(key), "index": i,
                            "name": str(rule.get("name") or ""), "when": str(rule.get("when") or ""), "value": str(rule.get("value") or "")})
    return out


def _gwrite(gid, path, data):
    """Validate the whole profile, then save it (the comment header is kept; the comments inside the rules are not)."""
    workdb.check_rules_data(data, f"{gid}{workdb.GLOBAL_SUFFIX}")
    header, _ = workdb.split_text(path.read_text(encoding="utf-8"))
    body = yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=1000) if data else ""
    _write(path, (header.rstrip("\n") + "\n\n" if header.strip() else "") + body)


def _gtitle(gid):
    return workdb.GLOBAL_TITLES.get(gid, gid)


def _work_columns():
    from .workstructure import columns
    try:
        return [c["column"] for c in columns()]
    except Exception:
        return []


def global_rows():
    rows = []
    for gid, path in workdb.global_files():
        data = _gdata(path)
        rows.append({"id": gid, "title": _gtitle(gid), "count": len(_gentries(data)), "file": path.name})
    return rows


@profiles_bp.route("/global/<gid>")
@admin_required
def global_view(gid):
    path = _gpath(gid)
    return render_template("global_profile.html", gid=gid, title=_gtitle(gid), entries=_gentries(_gdata(path)), file=path.name)


@profiles_bp.route("/global/<gid>/export")
@admin_required
def global_export(gid):
    path = _gpath(gid)
    return _attachment(path.read_text(encoding="utf-8"), path.name)


@profiles_bp.route("/global/<gid>/rule/<key>/<int:index>/export")
@admin_required
def global_rule_export(gid, key, index):
    data = _gdata(_gpath(gid))
    blocks = _blocks(data, key)
    if key not in data or index >= len(blocks):
        abort(404)
    return _attachment(yaml.safe_dump({key: [blocks[index]]}, sort_keys=False, allow_unicode=True, width=1000), f"{gid}_{key}_{index + 1}.yml")


@profiles_bp.route("/global/<gid>/rule/new", methods=["GET", "POST"])
@profiles_bp.route("/global/<gid>/rule/<key>/<int:index>/edit", methods=["GET", "POST"])
@admin_required
def global_rule_edit(gid, key=None, index=None):
    path = _gpath(gid)
    data = _gdata(path)
    creating = key is None
    if not creating:
        blocks = _blocks(data, key)
        if key not in data or index >= len(blocks) or not isinstance(blocks[index], dict):
            abort(404)
        old = blocks[index]
        state = {"column": "skip_rows" if key == "skip_rows" else _column_of(key), "name": str(old.get("name") or ""),
                 "when": str(old.get("when") or ""), "value": str(old.get("value") or "")}
    else:
        state = {"column": "skip_rows" if gid == "general" else "", "name": "", "when": "", "value": ""}
    if request.method == "POST":
        state = {k: request.form.get(k, "").strip() for k in ("column", "name", "when", "value")}
        column = state["column"]
        try:
            if not column:
                raise workdb.SpecError("The column is required (a work column, or skip_rows).")
            if column == "skip_rows" and not state["when"]:
                raise workdb.SpecError("A skip rule needs a condition (when).")
            if column != "skip_rows" and not state["value"]:
                raise workdb.SpecError("A rule needs a value.")
            rule = {k: state[k] for k in (("name", "when") if column == "skip_rows" else ("name", "when", "value")) if state[k]}
            target = "skip_rows" if column == "skip_rows" else _key_for(data, column)
            if creating:
                _blocks(data, target, create=True).append(rule)
            elif target == key:
                blocks[index] = rule
            else:
                del blocks[index]
                if not blocks and isinstance(data.get(key), list):
                    data.pop(key)
                _blocks(data, target, create=True).append(rule)
            _gwrite(gid, path, data)
        except workdb.SpecError as exc:
            flash(str(exc))
        else:
            flash("Rule saved.")
            return redirect(url_for("profiles.global_view", gid=gid))
    return render_template("global_rule_form.html", gid=gid, title=_gtitle(gid), state=state, creating=creating, columns=_work_columns())


@profiles_bp.route("/global/<gid>/rule/<key>/<int:index>/delete", methods=["POST"])
@admin_required
def global_rule_delete(gid, key, index):
    path = _gpath(gid)
    data = _gdata(path)
    blocks = _blocks(data, key)
    if key not in data or index >= len(blocks):
        abort(404)
    del blocks[index]
    if not blocks and isinstance(data.get(key), list):
        data.pop(key)
    try:
        _gwrite(gid, path, data)
    except workdb.SpecError as exc:
        flash(str(exc))
    else:
        log_event("data_destroy", target=f"global-rule:{gid}:{key}")
        flash("Rule deleted.")
    return redirect(url_for("profiles.global_view", gid=gid))
