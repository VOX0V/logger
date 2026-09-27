import re
from flask import Blueprint, flash, redirect, render_template, request, url_for
from .auth import login_required
from .importer import importable_rows
from .models import load_config, list_users, import_rows, save_config, safe_identifier

main_bp = Blueprint("main", __name__)


def technical_name(affichage):
    """Generate the SQLite column name from the display label."""
    value = str(affichage or "").strip().lower()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    if not value:
        raise ValueError("L'affichage doit produire un nom de colonne technique valide.")
    if value[0].isdigit():
        value = "_" + value
    safe_identifier(value)
    if value in {"id", "import_source"}:
        raise ValueError(f"Nom de colonne réservé: {value}")
    return value


def _category_from_form(form, position):
    affichage = form.get("affichage", "").strip()
    groupe = form.get("groupe", "").strip()
    new_group = form.get("nouveau_groupe", "").strip()
    if groupe == "__new__":
        groupe = new_group
    rules = [r.strip() for r in form.get("import_rules", "").splitlines() if r.strip()]
    if not affichage or not groupe or not rules:
        raise ValueError("Affichage, groupe et règles d'import sont obligatoires.")
    technique = technical_name(affichage)
    return {
        "position": position,
        "affichage": affichage,
        "groupe": groupe,
        "colonne_technique": technique,
        "import": rules,
    }


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
            if selected_position not in positions:
                raise ValueError("Position invalide.")
            category = _category_from_form(request.form, selected_position)
            config["categories"].insert(max(0, selected_position - 1), category)
            for i, item in enumerate(config["categories"], 1):
                item["position"] = i
            save_config(config)
            flash("Catégorie ajoutée à configuration.yml.")
            return redirect(url_for("main.settings"))
        except ValueError as exc:
            flash(str(exc))
    return render_template("category_form.html", category=None, groups=groups, positions=positions, next_position=len(config["categories"]) + 1, action=url_for("main.new_category"))


@main_bp.route("/settings/category/<int:position>/edit", methods=["GET", "POST"])
@login_required
def edit_category(position):
    config = load_config()
    categories = config["categories"]
    category = next((c for c in categories if int(c.get("position", 0)) == position), None)
    if category is None:
        flash("Catégorie introuvable.")
        return redirect(url_for("main.settings"))

    groups = sorted({c.get("groupe") for c in categories if c.get("groupe")})
    positions = list(range(1, len(categories) + 1))
    if request.method == "POST":
        try:
            selected_position = int(request.form.get("position", position))
            if selected_position not in positions:
                raise ValueError("Position invalide.")
            updated = _category_from_form(request.form, selected_position)
            old_technique = category.get("colonne_technique")
            category.clear()
            category.update(updated)
            categories.sort(key=lambda c: int(c.get("position", 0)))
            # Reassign contiguous positions after moving the category.
            moved = categories.pop(next(i for i, c in enumerate(categories) if c is category))
            categories.insert(selected_position - 1, moved)
            for i, item in enumerate(categories, 1):
                item["position"] = i
            save_config(config)
            if old_technique and old_technique != updated["colonne_technique"]:
                flash("Catégorie modifiée dans configuration.yml. L'ancienne colonne reste dans user.db pour préserver les données existantes.")
            else:
                flash("Catégorie modifiée dans configuration.yml.")
            return redirect(url_for("main.settings"))
        except (ValueError, StopIteration) as exc:
            flash(str(exc) or "Impossible de modifier la catégorie.")

    return render_template("category_form.html", category=category, groups=groups, positions=positions, next_position=position, action=url_for("main.edit_category", position=position))


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
                rows, matched_columns = importable_rows(file.filename, file.read(), config["categories"])
                import_rows(file.filename, rows, config["categories"])
                total += len(rows)
                flash(f"{file.filename}: {len(rows)} ligne(s) importée(s), {matched_columns} colonne(s) reconnue(s).")
            except Exception as exc:
                flash(f"{file.filename}: import impossible — {exc}")
        flash(f"Import terminé: {total} ligne(s).")
        return redirect(url_for("main.index"))
    return render_template("import.html", categories=config["categories"])
