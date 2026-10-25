"""Pages d'accueil des catégories de l'en-tête : Data et Export."""
from flask import Blueprint, g, render_template, url_for

from .auth import login_required

hubs_bp = Blueprint("hubs", __name__, url_prefix="/hub")


def _items(rows):
    return [{"label": label, "text": text, "url": url_for(endpoint)} for label, text, endpoint, admin in rows
            if not admin or g.role == "admin"]


@hubs_bp.route("/data")
@login_required
def data():
    return render_template("hub.html", title="Data", items=_items([
        ("Import", "Importer des fichiers (Excel, CSV de la compagnie, logbook Excel) dans les données brutes.", "main.import_files", False),
        ("Raw data", "Données brutes : tous les vols importés, tels quels.", "main.index", False),
        ("Convertisseur", "Règles qui transforment les données brutes en données converties.", "converter.index", False),
        ("Work data", "Données converties (logbook.db) : la base utilisée par le Logbook et les rapports.", "main.logbook_db_page", False),
        ("Types d'appareils", "Liste commune à toute l'application (administrateurs).", "converter.aircrafts", True),
        ("Aéroports", "Liste commune à toute l'application (administrateurs).", "converter.airports", True)]))


@hubs_bp.route("/export")
@login_required
def export():
    return render_template("hub.html", title="Export", items=_items([
        ("Reports", "Rapports mensuels des vols de ligne.", "reports.index", False),
        ("Export vers le logbook Excel", "Mettre à jour ton logbook Excel avec les vols.", "export.index", False),
        ("Sauvegarde du dossier utilisateur", "Télécharger une copie de ton dossier utilisateur.", "main.export_user_data", False)]))
