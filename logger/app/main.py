from flask import Blueprint, flash, redirect, render_template, request, url_for
from .auth import login_required
from .importer import importable_rows
from .models import load_config, list_users, import_rows, save_config, safe_identifier

main_bp = Blueprint("main", __name__)


def _category_from_form(form, position):
    affichage = form.get("affichage", "").strip()
    groupe = form.get("groupe", "").strip()
    new_group = form.get("nouveau_groupe", "").strip()
    if groupe == "__new__":
        groupe = new_group
    technique = form.get("colonne_technique", "").strip()
    rules = [r.strip() for r in form.get("import_rules", "").splitlines() if r.strip()]
    if not affichage or not groupe or not technique or not rules:
        raise ValueError("Tous les champs de la catégorie sont obligatoires.")
    safe_identifier(technique)
    return {"position": position, "affichage": affichage, "groupe": groupe, "colonne_technique": technique, "import": rules}


@main_bp.route("/")
@login_required
def index():
    config = load_config()
    columns, users = list_users()
    return render_template("index.html", categories=config["categories"], columns=columns, users=users)


@main_bp.route("/settings")
@login_required
def settings():
    categories = load_config()["categories"]
    groups = sorted({c.get("groupe") for c in categories if c.get("groupe")})
    return render_template("settings.html", categories=categories, groups=groups)


@main_bp.route("/settings/category/new", methods=["GET", "POST"])
@login_required
def new_category():
    config = load_config()
    groups = sorted({c.get("groupe") for c in config["categories"] if c.get("groupe")})
    positions = list(range(1, len(config["categories"]) + 2))
    if request.method == "POST":
        try:
            selected_position = int(request.form.get("position", len(config["categories"]) + 1))
            category = _category_from_form(request.form, selected_position)
            config["categories"].insert(max(0, selected_position - 1), category)
            for i, item in enumerate(config["categories"], 1):
                item["position"] = i
            save_config(config)
            flash("Catégorie ajoutée à configuration.yml.")
            return redirect(url_for("main.settings"))
        except ValueError as exc:
            flash(str(exc))
    return render_template("category_form.html", category=None, groups=groups, positions=positions, next_position=len(config["categories"]) + 1)


@main_bp.route("/settings/category/<int:position>/delete", methods=["POST"])
@login_required
def delete_category(position):
    config = load_config()
    config["categories"] = [c for c in config["categories"] if int(c.get("position", 0)) != position]
    for i, category in enumerate(config["categories"], 1):
        category["position"] = i
    save_config(config)
    flash("Catégorie supprimée de configuration.yml.")
    return redirect(url_for("main.settings"))


@main_bp.route("/data/clear", methods=["POST"])
@login_required
def clear_data():
    from .models import connect
    conn = connect()
    conn.execute("DELETE FROM users")
    conn.commit()
    conn.close()
    flash("Les données de user.db ont été supprimées. configuration.yml est conservé.")
    return redirect(url_for("main.index"))


@main_bp.route("/import", methods=["GET", "POST"])
@login_required
def import_files():
    config = load_config()
    if request.method == "POST":
        files = [f for f in request.files.getlist("files") if f and f.filename]
        if not files:
            flash("Sélectionnez au moins un fichier Excel.")
            return redirect(url_for("main.import_files"))
        total = 0
        for file in files:
            try:
                rows, matched_columns = importable_rows(file.read(), config["categories"])
                import_rows(file.filename, rows, config["categories"])
                total += len(rows)
                flash(f"{file.filename}: {len(rows)} ligne(s) importée(s), {matched_columns} colonne(s) reconnue(s).")
            except Exception as exc:
                flash(f"{file.filename}: import impossible — {exc}")
        flash(f"Import terminé: {total} ligne(s).")
        return redirect(url_for("main.index"))
    return render_template("import.html", categories=config["categories"])
