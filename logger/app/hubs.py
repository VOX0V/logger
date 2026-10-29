"""Landing pages for the header categories: Data and Export (and the Export > PDF page)."""
from flask import Blueprint, g, render_template, url_for

from .auth import login_required

hubs_bp = Blueprint("hubs", __name__, url_prefix="/hub")


def _url(endpoint):
    return url_for(endpoint[0], **endpoint[1]) if isinstance(endpoint, tuple) else url_for(endpoint)


def _links(rows):
    """Build (label, url) entries; admin-only rows are hidden from other roles."""
    return [{"label": label, "url": _url(endpoint)} for label, endpoint, admin_only in rows
            if not admin_only or g.role == "admin"]


def _items(rows):
    return [{"label": label, "text": text, "url": _url(endpoint)} for label, text, endpoint, admin in rows
            if not admin or g.role == "admin"]


@hubs_bp.route("/data")
@login_required
def data():
    user_links = _links([
        ("Import", "main.import_files", False),
        ("Raw data", "main.index", False),
        ("Converter", "converter.index", False),
        ("Work data", "main.logbook_db_page", False)])
    app_links = _links([
        ("Airports", "converter.airports", True),
        ("Aircrafts", "converter.aircrafts", True)])
    return render_template("data.html", user_links=user_links, app_links=app_links)


@hubs_bp.route("/export")
@login_required
def export():
    return render_template("hub.html", title="Export", items=_items([
        ("PDF", "Logbook (one year or full) and Breakdown.", "hubs.pdf", False),
        ("Reports", "Monthly flight report: choose the month, the year and the aircraft type.", "reports.index", False),
        ("Export to the Excel logbook", "Update your Excel logbook with the flights.", "export.index", False),
        ("Raw data (Excel)", "Raw data table in Excel format.", ("main.data_table_export", {"fmt": "xlsx"}), False),
        ("Raw data (CSV)", "Raw data table in CSV format.", ("main.data_table_export", {"fmt": "csv"}), False),
        ("Work data (Excel)", "Work data table in Excel format.", ("main.logbook_table_export", {"fmt": "xlsx"}), False),
        ("Work data (CSV)", "Work data table in CSV format.", ("main.logbook_table_export", {"fmt": "csv"}), False),
        ("Work data (backup)", "Backup of the work data (logbook.db).", "main.export_logbook_data", False),
        ("User folder backup", "Download a copy of your user folder.", "main.export_user_data", False),
        ("Aircraft types (Excel)", "List of aircraft types in Excel format (administrators).", "converter.aircrafts_export", True),
        ("Airports (Excel)", "List of airports in Excel format (administrators).", "converter.airports_export", True)]))


@hubs_bp.route("/pdf")
@login_required
def pdf():
    from .main import _logbook_context
    years = _logbook_context()["years"]
    selected = next((y for y in reversed(years) if y.isdigit()), years[-1] if years else "")
    return render_template("export_pdf.html", years=years, selected=selected)
