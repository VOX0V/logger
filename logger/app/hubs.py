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
        ("PDF", "Logbook (une année ou complet) et Breakdown.", "hubs.pdf", False),
        ("Reports", "Rapport mensuel des vols : choisis le mois, l'année et le type d'appareil.", "reports.index", False),
        ("Export vers le logbook Excel", "Mettre à jour ton logbook Excel avec les vols.", "export.index", False),
        ("Raw data (Excel)", "Tableau des données brutes au format Excel.", ("main.data_table_export", {"fmt": "xlsx"}), False),
        ("Raw data (CSV)", "Tableau des données brutes au format CSV.", ("main.data_table_export", {"fmt": "csv"}), False),
        ("Work data (Excel)", "Tableau des données converties au format Excel.", ("main.logbook_table_export", {"fmt": "xlsx"}), False),
        ("Work data (CSV)", "Tableau des données converties au format CSV.", ("main.logbook_table_export", {"fmt": "csv"}), False),
        ("Work data (sauvegarde)", "Sauvegarde des données converties (logbook.db).", "main.export_logbook_data", False),
        ("Sauvegarde du dossier utilisateur", "Télécharger une copie de ton dossier utilisateur.", "main.export_user_data", False),
        ("Types d'appareils (Excel)", "Liste des types d'appareils au format Excel (administrateurs).", "converter.aircrafts_export", True),
        ("Aéroports (Excel)", "Liste des aéroports au format Excel (administrateurs).", "converter.airports_export", True)]))


@hubs_bp.route("/pdf")
@login_required
def pdf():
    from .main import _logbook_context
    years = _logbook_context()["years"]
    selected = next((y for y in reversed(years) if y.isdigit()), years[-1] if years else "")
    return render_template("export_pdf.html", years=years, selected=selected)
