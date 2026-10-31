"""The "Converter" tab: rule catalog (admins edit, everyone ticks their own
rules), converter settings, and the shared airport / aircraft reference data."""
from flask import Blueprint, Response, flash, g, redirect, render_template, request, url_for

from ..auth import login_required, admin_required, fresh_login_required, clear_confirmed
from ..seclog import log_event
from ..gridview import grid_data
from ..db import airport_connect, aircrafts_connect
from ..config import load_config, load_logbook_db_config, configurable_columns
from ..refdata import (list_airports, get_airport, save_airport, delete_airport,
                       list_aircraft_types, get_aircraft_type, save_aircraft_type, delete_aircraft_type, ENGINES,
    CATEGORIES, ENGINE_TYPES, ENGINE_LABELS, export_aircraft_types_xlsx, export_airports_xlsx,
    import_airports, import_aircraft_types, clear_airports, clear_aircraft_types)
from ..importer import FileImportError
from . import catalog
from .transforms import TRANSFORMS

converter_bp = Blueprint("converter", __name__, url_prefix="/converter")


def _user_columns():
    a = [c["column"] for c in configurable_columns(load_config())]
    b = [c["column"] for c in load_logbook_db_config()["database"]["columns"] if not c.get("system")]
    return a, b


def _summary(rule):
    left = " + ".join(rule["inputs"].values())
    right = ", ".join(rule["outputs"].values())
    extra = ", ".join(f"{k}={v}" for k, v in rule["params"].items() if v not in ("any",))
    return f"{left} → {right}" + (f"  ({extra})" if extra else "")


@converter_bp.route("")
@login_required
def index():
    a, b = _user_columns()
    selected = set(catalog.load_selection())
    rules = []
    for rule in catalog.load_rules():
        rules.append({
            "rule": rule, "checked": rule["id"] in selected,
            "missing": catalog.rule_missing_columns(rule, a, b), "summary": _summary(rule),
            "label": TRANSFORMS.get(rule["transform"], {}).get("label", rule["transform"])})
    settings = catalog.load_settings()
    return render_template("converter.html", rules=rules, settings=settings,
                           rounding_text=catalog.rounding_to_text(settings["tc_rounding"]["rules"]))


@converter_bp.route("/select", methods=["POST"])
@login_required
def select():
    catalog.save_selection(request.form.getlist("enabled"))
    flash("Rule selection saved. Click Refresh in logbook.db to apply it.")
    return redirect(url_for("converter.index"))


@converter_bp.route("/settings")
@admin_required
def settings_page():
    settings = catalog.load_settings()
    return render_template("converter_settings.html", settings=settings,
                           rounding_text=catalog.rounding_to_text(settings["tc_rounding"]["rules"]))


@converter_bp.route("/settings", methods=["POST"])
@admin_required
def save_settings_route():
    try:
        after = int(request.form.get("after_sunset_minutes", ""))
        before = int(request.form.get("before_sunrise_minutes", ""))
        if not (0 <= after <= 180 and 0 <= before <= 180):
            raise ValueError("Night margins must be between 0 and 180 minutes.")
        rules = catalog.rounding_from_text(request.form.get("tc_rounding", ""))
        current = catalog.load_settings()
        catalog.save_settings({**current, "night": {"after_sunset_minutes": after, "before_sunrise_minutes": before},
                               "tc_rounding": {"comment": current["tc_rounding"].get("comment", ""), "rules": rules}})
        log_event("config_change", target="converter:reglages")
        flash("Converter settings saved.")
    except ValueError as exc:
        flash(f"Settings not saved — {exc}")
    return redirect(url_for("converter.settings_page"))


# ---------------- rules (admin) ----------------

def _rule_values(rule):
    values = {"name": rule["name"], "default": "1" if rule["default"] else ""}
    values.update({f"in_{k}": v for k, v in rule["inputs"].items()})
    values.update({f"out_{k}": v for k, v in rule["outputs"].items()})
    values.update({f"param_{k}": v for k, v in rule["params"].items()})
    return values


def _render_rule_form(rule, transform, values, action):
    a, b = _user_columns()
    return render_template("rule_form.html", rule=rule, transform=transform, spec=TRANSFORMS[transform],
                           transforms=TRANSFORMS, values=values, a_columns=a, b_columns=b,
                           action=action)


@converter_bp.route("/rule/new", methods=["GET", "POST"])
@admin_required
def rule_new():
    transform = request.values.get("transform", "copy")
    if transform not in TRANSFORMS:
        transform = "copy"
    if request.method == "POST" and request.form.get("save") == "1":
        try:
            rules = catalog.load_rules()
            rule_id = catalog.rule_id_from_name(request.form.get("name", ""), {r["id"] for r in rules})
            rules.append(catalog.build_rule(request.form, transform, rule_id))
            catalog.save_rules(rules)
            log_event("config_change", target=f"converter:regle-ajoutee:{rule_id}")
            flash("Rule added to the catalog.")
            return redirect(url_for("converter.index"))
        except ValueError as exc:
            flash(str(exc))
    return _render_rule_form(None, transform, request.form if request.method == "POST" else {}, url_for("converter.rule_new"))


@converter_bp.route("/rule/<rule_id>/edit", methods=["GET", "POST"])
@admin_required
def rule_edit(rule_id):
    rules = catalog.load_rules()
    rule = next((r for r in rules if r["id"] == rule_id), None)
    if not rule:
        flash("Rule not found."); return redirect(url_for("converter.index"))
    if request.method == "POST":
        try:
            updated = catalog.build_rule(request.form, rule["transform"], rule_id)
            catalog.save_rules([updated if r["id"] == rule_id else r for r in rules])
            log_event("config_change", target=f"converter:regle-modifiee:{rule_id}")
            flash("Rule updated.")
            return redirect(url_for("converter.index"))
        except ValueError as exc:
            flash(str(exc))
    return _render_rule_form(rule, rule["transform"], request.form if request.method == "POST" else _rule_values(rule),
                             url_for("converter.rule_edit", rule_id=rule_id))


@converter_bp.route("/rule/<rule_id>/delete", methods=["POST"])
@admin_required
@fresh_login_required
def rule_delete(rule_id):
    rules = catalog.load_rules()
    catalog.save_rules([r for r in rules if r["id"] != rule_id])
    log_event("data_destroy", target=f"converter:regle-supprimee:{rule_id}")
    flash("Rule deleted from the catalog (it is also unticked for all accounts).")
    return redirect(url_for("converter.index"))


# ---------------- airports (admin) ----------------

AIRPORT_FIELDS = ("icao_code", "iata_code", "full_name", "country", "latitude", "longitude", "elevation", "timezone", "notes")
AIRPORT_COLUMNS = [
    {"field": "icao_code", "title": "ICAO", "width": 90}, {"field": "iata_code", "title": "IATA", "width": 80},
    {"field": "full_name", "title": "Name", "width": 260}, {"field": "country", "title": "Country", "width": 110},
    {"field": "latitude", "title": "Latitude", "width": 110, "sorter": "number"},
    {"field": "longitude", "title": "Longitude", "width": 110, "sorter": "number"},
    {"field": "elevation", "title": "Elevation", "width": 100, "sorter": "number"},
    {"field": "timezone", "title": "Time zone", "width": 160}, {"field": "notes", "title": "Notes", "width": 220}]
AIRCRAFT_FIELDS = ("code", "make", "model", "category", "engines", "engine_type", "notes")


def _lookup(field, title, labels, width):
    return {"field": field, "title": title, "width": width, "editor": "list",
            "editorParams": {"values": dict(labels), "clearable": True}, "formatter": "lookup", "formatterParams": dict(labels)}


AIRCRAFT_COLUMNS = [
    {"field": "code", "title": "Code", "width": 90}, {"field": "make", "title": "Make", "width": 170},
    {"field": "model", "title": "Model", "width": 170}, _lookup("category", "Category", CATEGORIES, 130),
    _lookup("engines", "Engines", ENGINE_LABELS, 140), _lookup("engine_type", "Engine type", ENGINE_TYPES, 150),
    {"field": "notes", "title": "Notes", "width": 220}]


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


@converter_bp.route("/airports")
@admin_required
def airports():
    return render_template("refdata_grid.html", title="Airports", columns=AIRPORT_COLUMNS, add_fields=_fields(AIRPORT_COLUMNS),
                           note="The arrival code of flights is looked up in IATA first, then in ICAO.",
                           rows_url=url_for("converter.airports_rows"), cell_url=url_for("converter.airports_cell"),
                           add_url=url_for("converter.airports_add"), delete_url=url_for("converter.airports_delete"),
                           export_url=url_for("converter.airports_export"))


@converter_bp.route("/airports/rows")
@admin_required
def airports_rows():
    conn = airport_connect()
    try:
        return grid_data(conn, "airports", list(AIRPORT_FIELDS))
    finally:
        conn.close()


@converter_bp.route("/airports/cell", methods=["POST"])
@admin_required
def airports_cell():
    return _cell_update(get_airport, save_airport, AIRPORT_FIELDS)


@converter_bp.route("/airports/add", methods=["POST"])
@admin_required
def airports_add():
    return _add_update(save_airport)


@converter_bp.route("/airports/delete", methods=["POST"])
@admin_required
def airports_delete():
    return _delete(delete_airport, "airports")


@converter_bp.route("/airports/new", methods=["GET", "POST"])
@converter_bp.route("/airports/<int:airport_id>/edit", methods=["GET", "POST"])
@admin_required
def airport_form(airport_id=None):
    airport = get_airport(airport_id) if airport_id else None
    if airport_id and not airport:
        flash("Airport not found."); return redirect(url_for("converter.airports"))
    if request.method == "POST":
        try:
            save_airport(airport_id, request.form)
            flash("Airport saved.")
            return redirect(url_for("converter.airports"))
        except ValueError as exc:
            flash(str(exc))
    return render_template("airport_form.html", airport=airport, form=request.form if request.method == "POST" else None)


@converter_bp.route("/airports/<int:airport_id>/delete", methods=["POST"])
@admin_required
def airport_delete(airport_id):
    delete_airport(airport_id)
    log_event("data_destroy", target=f"airport:{airport_id}")
    flash("Airport deleted.")
    return redirect(url_for("converter.airports"))


# ---------------- aircraft (admin) ----------------

@converter_bp.route("/aircrafts")
@admin_required
def aircrafts():
    return render_template("refdata_grid.html", title="Aircraft", columns=AIRCRAFT_COLUMNS, add_fields=_fields(AIRCRAFT_COLUMNS),
                           note="The flight is linked to its type by the “type” column (CRJ9, CRJ7 and CRJ2 are reduced to CRJ). "
                                "The number of engines is used by the day/night rules, and the audit checks the types against this table.",
                           rows_url=url_for("converter.aircrafts_rows"), cell_url=url_for("converter.aircrafts_cell"),
                           add_url=url_for("converter.aircrafts_add"), delete_url=url_for("converter.aircrafts_delete"),
                           export_url=url_for("converter.aircrafts_export"))


@converter_bp.route("/aircrafts/rows")
@admin_required
def aircrafts_rows():
    conn = aircrafts_connect()
    try:
        return grid_data(conn, "aircraft_types", list(AIRCRAFT_FIELDS))
    finally:
        conn.close()


@converter_bp.route("/aircrafts/cell", methods=["POST"])
@admin_required
def aircrafts_cell():
    return _cell_update(get_aircraft_type, save_aircraft_type, AIRCRAFT_FIELDS)


@converter_bp.route("/aircrafts/add", methods=["POST"])
@admin_required
def aircrafts_add():
    return _add_update(save_aircraft_type)


@converter_bp.route("/aircrafts/delete", methods=["POST"])
@admin_required
def aircrafts_delete():
    return _delete(delete_aircraft_type, "aircraft-types")


@converter_bp.route("/aircrafts/new", methods=["GET", "POST"])
@converter_bp.route("/aircrafts/<int:aircraft_id>/edit", methods=["GET", "POST"])
@admin_required
def aircraft_form(aircraft_id=None):
    aircraft = get_aircraft_type(aircraft_id) if aircraft_id else None
    if aircraft_id and not aircraft:
        flash("Type not found."); return redirect(url_for("converter.aircrafts"))
    if request.method == "POST":
        try:
            save_aircraft_type(aircraft_id, request.form)
            flash("Type saved.")
            return redirect(url_for("converter.aircrafts"))
        except ValueError as exc:
            flash(str(exc))
    return render_template("aircraft_form.html", aircraft=aircraft, engines=ENGINES, categories=CATEGORIES,
                           engine_types=ENGINE_TYPES, engine_labels=ENGINE_LABELS,
                           form=request.form if request.method == "POST" else None)


@converter_bp.route("/aircrafts/<int:aircraft_id>/delete", methods=["POST"])
@admin_required
def aircraft_delete(aircraft_id):
    delete_aircraft_type(aircraft_id)
    log_event("data_destroy", target=f"aircraft:{aircraft_id}")
    flash("Type deleted.")
    return redirect(url_for("converter.aircrafts"))


XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@converter_bp.route("/aircrafts/export")
@admin_required
def aircrafts_export():
    return Response(export_aircraft_types_xlsx(), mimetype=XLSX,
                    headers={"Content-Disposition": 'attachment; filename="aircraft_types.xlsx"'})


@converter_bp.route("/airports/export")
@admin_required
def airports_export():
    return Response(export_airports_xlsx(), mimetype=XLSX,
                    headers={"Content-Disposition": 'attachment; filename="airports.xlsx"'})


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


@converter_bp.route("/airports/clear", methods=["POST"])
@admin_required
@fresh_login_required
def airports_clear():
    if not clear_confirmed():
        flash("Nothing was deleted: type CLEAR to confirm.")
    else:
        clear_airports(); log_event("data_destroy", target="airports:all-rows"); flash("All airports were deleted.")
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


@converter_bp.route("/airports/import", methods=["POST"])
@admin_required
def airports_import():
    return _do_import(import_airports, "converter.airports")


@converter_bp.route("/aircrafts/import", methods=["POST"])
@admin_required
def aircrafts_import():
    return _do_import(import_aircraft_types, "converter.aircrafts")
