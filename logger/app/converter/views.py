"""The shared location / aircraft reference data (grids, import, export, clear)."""

from flask import Blueprint, Response, flash, redirect, render_template, request, url_for

from ..auth import admin_required, fresh_login_required, clear_confirmed
from ..seclog import log_event
from ..gridview import grid_data
from ..db import location_connect, aircrafts_connect
from ..refdata import get_location, save_location, delete_location, get_aircraft_type, save_aircraft_type, delete_aircraft_type, option_pairs, OPTION_FIELDS, export_aircraft_types_xlsx, export_locations_xlsx, import_locations, import_aircraft_types, clear_locations, clear_aircraft_types
from ..importer import FileImportError
from .. import refcolumns

converter_bp = Blueprint("converter", __name__, url_prefix="/converter")


# ---------------- rules (admin) ----------------

# ---------------- locations (admin) ----------------

LOCATION_FIELDS = ("display", "icao_code", "iata_code", "company_code", "full_name", "country", "latitude", "longitude")
LOCATION_COLUMNS = [
    {"field": "display", "title": "Display"}, {"field": "icao_code", "title": "ICAO"},
    {"field": "iata_code", "title": "IATA"}, {"field": "company_code", "title": "Company code"},
    {"field": "full_name", "title": "Name"}, {"field": "country", "title": "Country"},
    {"field": "latitude", "title": "Latitude", "sorter": "number"},
    {"field": "longitude", "title": "Longitude", "sorter": "number"}]
AIRCRAFT_FIELDS = ("display", "designator", "maker", "model", "category", "engines", "engine_type", "crew", "landing_gear", "mtow_lb", "mtow_kg")


def _lookup(field, title, labels):
    return {"field": field, "title": title, "editor": "list",
            "editorParams": {"values": dict(labels), "clearable": True}, "formatter": "lookup", "formatterParams": dict(labels)}


def aircraft_columns():
    """The choice lists come from aircraft_options.yml, so they are read for every page."""
    return [
        {"field": "display", "title": "Display"}, {"field": "designator", "title": "Designator"},
        {"field": "maker", "title": "Maker"}, {"field": "model", "title": "Model"},
        *[_lookup(f, t, option_pairs(f)) for f, t in OPTION_FIELDS.items()],
        {"field": "mtow_lb", "title": "MTOW (lb)", "sorter": "number"}, {"field": "mtow_kg", "title": "MTOW (kg)", "sorter": "number"}]


def _grid_columns(kind, core_specs):
    """The columns of the grid in the order chosen on the structure page; the added entities are plain columns."""
    by_field = {c["field"]: c for c in core_specs}
    out = []
    for c in refcolumns.columns(kind):
        if not c["visible"]:
            continue
        if c["core"]:
            out.append({**(by_field.get(c["field"]) or {"field": c["field"]}), "title": c["title"]})
        else:
            item = {"field": c["field"], "title": c["title"]}
            if c["data_type"] in ("integer", "decimal"):
                item["sorter"] = "number"
            out.append(item)
    return out


def _cols(kind):
    return _grid_columns(kind, LOCATION_COLUMNS if kind == "location" else aircraft_columns())


def _fields_of(kind):
    return [c["field"] for c in _cols(kind)]


def _ids():
    try:
        ids = [int(x) for x in request.form.get("ids", "").split(",") if x.strip()]
    except ValueError:
        ids = []
    return ids[:5000]


def _cell_update(get, save, fields):
    """Edit one cell: the whole row goes through the same validation as the old form."""
    try:
        row_id, column = int(request.form.get("row_id", "0")), request.form.get("column", "")
        if column not in fields:
            raise ValueError("Invalid column.")
        row = get(row_id)
        if not row:
            raise ValueError("Row not found.")
        values = dict(row)
        values[column] = request.form.get("value", "")
        save(row_id, values)
        return ("", 204)
    except ValueError as exc:
        return (str(exc), 400)
    except Exception:
        return ("The change could not be saved.", 400)


def _add_update(save):
    try:
        save(None, request.form)
        return ("", 204)
    except ValueError as exc:
        return (str(exc), 400)
    except Exception:
        return ("The row could not be added.", 400)


def _delete(delete, target):
    ids = _ids()
    if not ids:
        return ("No row selected.", 400)
    for row_id in ids:
        delete(row_id)
    log_event("data_destroy", target=f"{target}:{len(ids)}-rows")
    return ("", 204)


def _fields(columns):
    out = []
    for c in columns:
        item = {"name": c["field"], "label": c["title"]}
        if c.get("editor") == "list":
            item["options"] = list(c["editorParams"]["values"].items())
        out.append(item)
    return out


@converter_bp.route("/locations")
@admin_required
def locations():
    return render_template("refdata_grid.html", title="Locations", columns=_cols("location"), add_fields=_fields(_cols("location")), structure_url=url_for("entities.structure", kind="location"),
                           note="A code is looked up in IATA first, then ICAO, then company code. The logbook shows the display name, or the ICAO code when it is empty.",
                           rows_url=url_for("converter.locations_rows"), cell_url=url_for("converter.locations_cell"),
                           add_url=url_for("converter.locations_add"), delete_url=url_for("converter.locations_delete"),
                           export_url=url_for("converter.locations_export"))


@converter_bp.route("/locations/rows")
@admin_required
def locations_rows():
    conn = location_connect()
    try:
        return grid_data(conn, "locations", _fields_of("location"))
    finally:
        conn.close()


@converter_bp.route("/locations/cell", methods=["POST"])
@admin_required
def locations_cell():
    return _cell_update(get_location, save_location, _fields_of("location"))


@converter_bp.route("/locations/add", methods=["POST"])
@admin_required
def locations_add():
    return _add_update(save_location)


@converter_bp.route("/locations/delete", methods=["POST"])
@admin_required
def locations_delete():
    return _delete(delete_location, "locations")


@converter_bp.route("/locations/new", methods=["GET", "POST"])
@converter_bp.route("/locations/<int:location_id>/edit", methods=["GET", "POST"])
@admin_required
def location_form(location_id=None):
    location = get_location(location_id) if location_id else None
    if location_id and not location:
        flash("Location not found."); return redirect(url_for("converter.locations"))
    if request.method == "POST":
        try:
            save_location(location_id, request.form)
            flash("Location saved.")
            return redirect(url_for("converter.locations"))
        except ValueError as exc:
            flash(str(exc))
    return render_template("location_form.html", location=location, form=request.form if request.method == "POST" else None,
                           extras=refcolumns.extras("location"))


@converter_bp.route("/locations/<int:location_id>/delete", methods=["POST"])
@admin_required
def location_delete(location_id):
    delete_location(location_id)
    log_event("data_destroy", target=f"location:{location_id}")
    flash("Location deleted.")
    return redirect(url_for("converter.locations"))


# ---------------- aircraft (admin) ----------------

@converter_bp.route("/aircrafts")
@admin_required
def aircrafts():
    return render_template("refdata_grid.html", title="Aircraft", columns=_cols("aircraft"), add_fields=_fields(_cols("aircraft")), structure_url=url_for("entities.structure", kind="aircraft"), edit_lists_url=url_for("yamledit.editor", file="aircraft_options"),
                           note="The flight is linked to its type by the designator (DH1, CR9...); the logbook shows the display name (DHC8, CRJ...), "
                                "which several designators can share. Both MTOW values are official data, entered by hand. "
                                "The number of engines is used by the day/night rules, and the audit checks the types against this table.",
                           rows_url=url_for("converter.aircrafts_rows"), cell_url=url_for("converter.aircrafts_cell"),
                           add_url=url_for("converter.aircrafts_add"), delete_url=url_for("converter.aircrafts_delete"),
                           export_url=url_for("converter.aircrafts_export"))


@converter_bp.route("/aircrafts/rows")
@admin_required
def aircrafts_rows():
    conn = aircrafts_connect()
    try:
        return grid_data(conn, "aircraft_types", _fields_of("aircraft"))
    finally:
        conn.close()


@converter_bp.route("/aircrafts/cell", methods=["POST"])
@admin_required
def aircrafts_cell():
    return _cell_update(get_aircraft_type, save_aircraft_type, _fields_of("aircraft"))


@converter_bp.route("/aircrafts/add", methods=["POST"])
@admin_required
def aircrafts_add():
    return _add_update(save_aircraft_type)


@converter_bp.route("/aircrafts/delete", methods=["POST"])
@admin_required
def aircrafts_delete():
    return _delete(delete_aircraft_type, "aircraft-types")


XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@converter_bp.route("/aircrafts/export")
@admin_required
def aircrafts_export():
    return Response(export_aircraft_types_xlsx(), mimetype=XLSX,
                    headers={"Content-Disposition": 'attachment; filename="aircraft_types.xlsx"'})


@converter_bp.route("/locations/export")
@admin_required
def locations_export():
    return Response(export_locations_xlsx(), mimetype=XLSX,
                    headers={"Content-Disposition": 'attachment; filename="locations.xlsx"'})


def _do_import(importer, back):
    f = request.files.get("file")
    if not f or not f.filename:
        flash("Choose a file to import.")
    else:
        try:
            added, updated, skipped = importer(f.filename, f.read())
            flash(f"Import complete: {added} added, {updated} updated, {skipped} ignored.")
        except FileImportError as exc:
            flash(str(exc))
    return redirect(url_for("hubs.data") if request.form.get("back") == "hub" else url_for(back))


@converter_bp.route("/locations/clear", methods=["POST"])
@admin_required
@fresh_login_required
def locations_clear():
    if not clear_confirmed():
        flash("Nothing was deleted: type CLEAR to confirm.")
    else:
        clear_locations(); log_event("data_destroy", target="locations:all-rows"); flash("All locations were deleted.")
    return redirect(url_for("hubs.data"))


@converter_bp.route("/aircrafts/clear", methods=["POST"])
@admin_required
@fresh_login_required
def aircrafts_clear():
    if not clear_confirmed():
        flash("Nothing was deleted: type CLEAR to confirm.")
    else:
        clear_aircraft_types(); log_event("data_destroy", target="aircrafts:all-rows"); flash("All aircraft types were deleted.")
    return redirect(url_for("hubs.data"))


@converter_bp.route("/locations/import", methods=["POST"])
@admin_required
def locations_import():
    return _do_import(import_locations, "converter.locations")


@converter_bp.route("/aircrafts/import", methods=["POST"])
@admin_required
def aircrafts_import():
    return _do_import(import_aircraft_types, "converter.aircrafts")
