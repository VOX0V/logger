from flask import Blueprint, flash, redirect, render_template, request, url_for
from .auth import login_required
from .models import get_db, list_categories, list_rules_by_category, find_conflicting_rules, create_category, update_category, delete_category, db_path

admin_bp = Blueprint("admin", __name__, url_prefix="/settings")


def _parse_rules(raw):
    result = []
    seen = set()
    for line in (raw or "").splitlines():
        rule = line.strip()
        key = rule.lower()
        if rule and key not in seen:
            result.append(rule)
            seen.add(key)
    return result


@admin_bp.route("")
@login_required
def settings():
    db = get_db()
    categories = list_categories(db)
    rules = list_rules_by_category(db)
    db.close()
    return render_template("settings.html", categories=categories, rules_by_cat=rules)


@admin_bp.route("/categories/new", methods=["GET", "POST"])
@admin_bp.route("/categories/<int:category_id>/edit", methods=["GET", "POST"])
@login_required
def category_edit(category_id=None):
    db = get_db()
    category = db.execute("SELECT * FROM categories WHERE id=?", (category_id,)).fetchone() if category_id else None
    if category_id and category is None:
        db.close(); return redirect(url_for("admin.settings"))
    count = db.execute("SELECT COUNT(*) FROM categories").fetchone()[0]
    max_position = count if category else count + 1
    rules = list_rules_by_category(db)
    current_rules = rules.get(category_id, []) if category else []
    values = {
        "display_name": category["display_name"] if category else "",
        "group_name": category["group_name"] if category else "",
        "position": category["position"] if category else max_position,
        "rules_text": "\n".join(current_rules),
    }
    if request.method == "POST":
        values["display_name"] = request.form.get("display_name", "").strip()
        values["group_name"] = request.form.get("group_name", "").strip()
        values["rules_text"] = request.form.get("rules", "")
        try: values["position"] = int(request.form.get("position", max_position))
        except ValueError: values["position"] = max_position
        parsed = _parse_rules(values["rules_text"])
        error = None
        if not values["display_name"]: error = "L'affichage est obligatoire."
        if not parsed: error = error or "Ajoutez au moins une règle d'import."
        conflicts = find_conflicting_rules(db, parsed, category_id)
        if conflicts:
            error = "Règle(s) déjà utilisée(s) : " + ", ".join(conflicts.keys())
        if error:
            db.close()
            return render_template("category_form.html", category=category, max_position=max_position, error=error, **values)
        if category:
            update_category(db, category_id, values["display_name"], values["position"], values["group_name"], parsed)
        else:
            create_category(db, values["display_name"], values["position"], values["group_name"], parsed)
        db.close()
        return redirect(url_for("admin.settings"))
    db.close()
    return render_template("category_form.html", category=category, max_position=max_position, error=None, **values)


@admin_bp.route("/categories/<int:category_id>/delete", methods=["POST"])
@login_required
def category_delete(category_id):
    db = get_db(); delete_category(db, category_id); db.close()
    flash("Catégorie supprimée.")
    return redirect(url_for("admin.settings"))
