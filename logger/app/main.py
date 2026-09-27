import re
from flask import Blueprint, flash, redirect, render_template, request, url_for
from .auth import login_required
from .importer import importable_rows
from .models import load_config, list_users, list_logbook, import_rows, save_config, safe_identifier, configurable_columns, refresh_logbook, logbook_config

main_bp = Blueprint("main", __name__)


def technical_name(display_name):
    value = str(display_name or "").strip().lower()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    if not value:
        raise ValueError("Le display_name doit produire un nom de colonne technique valide.")
    if value[0].isdigit():
        value = "_" + value
    safe_identifier(value)
    if value in {"id", "created_at", "updated_at", "import_source"}:
        raise ValueError(f"Nom de colonne réservé: {value}")
    return value


def _category_from_form(form, position, existing=None):
    display_name = form.get("display_name", form.get("affichage", "")).strip()
    group = form.get("group", form.get("groupe", "")).strip()
    new_group = form.get("new_group", form.get("nouveau_groupe", "")).strip()
    if group == "__new__":
        group = new_group
    rules = [r.strip() for r in form.get("import_rules", form.get("import", "")).splitlines() if r.strip()]
    if not display_name or not group or not rules:
        raise ValueError("Display name, groupe et règles d'import sont obligatoires.")
    column = technical_name(display_name)
    def flag(name, default=True):
        values = form.getlist(name)
        return ("1" in values) if values else default

    return {
        "column": column,
        "display_name": display_name,
        "position": position,
        "group": group,
        "data_type": (form.get("data_type") or (existing or {}).get("data_type") or "text").lower(),
        "nullable": flag("nullable"),
        "visible": flag("visible"),
        "editable": flag("editable"),
        "import_rules": rules,
    }


def _columns(config):
    return configurable_columns(config)


@main_bp.route("/")
@login_required
def index():
    config = load_config()
    columns, users = list_users(config)
    return render_template("index.html", categories=_columns(config), columns=columns, users=users)


@main_bp.route("/logbook")
@login_required
def logbook():
    config = load_config()
    lb_config = logbook_config(config)
    columns, rows = list_logbook(config)
    return render_template("logbook.html", categories=[c for c in lb_config["columns"] if c.get("group") != "system"], columns=columns, rows=rows)


@main_bp.route("/logbook/refresh", methods=["POST"])
@login_required
def refresh_logbook_data():
    config = load_config()
    try:
        refresh_logbook(config)
        flash("Logbook actualisé à partir de user.db.")
    except Exception as exc:
        flash(f"Actualisation du logbook impossible — {exc}")
    return redirect(url_for("main.logbook"))


@main_bp.route("/logbook/settings")
@login_required
def logbook_settings():
    config = load_config()
    lb = logbook_config(config)
    categories = [c for c in lb["columns"] if c.get("group") != "system"]
    groups = sorted({c.get("group") for c in categories if c.get("group")})
    return render_template("logbook_settings.html", categories=categories, groups=groups)


@main_bp.route("/logbook/settings/column/new", methods=["GET", "POST"])
@login_required
def new_logbook_column():
    config = load_config(); lb = logbook_config(config)
    categories = [c for c in lb["columns"] if c.get("group") != "system"]
    groups = sorted({c.get("group") for c in categories if c.get("group")})
    positions = list(range(1, len(categories) + 2))
    if request.method == "POST":
        try:
            position=int(request.form.get("position", len(categories)+1))
            if position not in positions: raise ValueError("Position invalide.")
            display=request.form.get("display_name", "").strip(); group=request.form.get("group", "").strip(); new_group=request.form.get("new_group", "").strip()
            if group == "__new__": group=new_group
            source=[x.strip() for x in request.form.get("source", "").splitlines() if x.strip()]
            if not display or not group or not source: raise ValueError("Display name, groupe et source sont obligatoires.")
            item={"column":technical_name(display),"display_name":display,"position":position,"group":group,"data_type":(request.form.get("data_type") or "text").lower(),"nullable":request.form.get("nullable") == "1","visible":request.form.get("visible") == "1","editable":request.form.get("editable") == "1","source":source,"transformation":request.form.get("transformation", "").strip()}
            if any(c["column"] == item["column"] for c in categories): raise ValueError(f"La colonne {item['column']} existe déjà.")
            categories.insert(position-1,item)
            for i,c in enumerate(categories,1): c["position"]=i
            config["logbook"]["columns"]=[c for c in lb["columns"] if c.get("group")=="system"]+categories
            save_config(config); flash("Colonne logbook ajoutée à configuration.yml."); return redirect(url_for("main.logbook_settings"))
        except ValueError as exc: flash(str(exc))
    return render_template("logbook_column_form.html", category=None, groups=groups, positions=positions, action=url_for("main.new_logbook_column"))


@main_bp.route("/logbook/settings/column/<int:position>/edit", methods=["GET", "POST"])
@login_required
def edit_logbook_column(position):
    config=load_config(); lb=logbook_config(config); categories=[c for c in lb["columns"] if c.get("group")!="system"]
    category=next((c for c in categories if int(c.get("position",0))==position),None)
    if category is None: flash("Colonne introuvable."); return redirect(url_for("main.logbook_settings"))
    groups=sorted({c.get("group") for c in categories if c.get("group")}); positions=list(range(1,len(categories)+1))
    if request.method=="POST":
        try:
            newpos=int(request.form.get("position",position)); display=request.form.get("display_name","").strip(); group=request.form.get("group","").strip(); new_group=request.form.get("new_group","").strip(); group=new_group if group=="__new__" else group
            source=[x.strip() for x in request.form.get("source","").splitlines() if x.strip()]
            if newpos not in positions or not display or not group or not source: raise ValueError("Position, display name, groupe et source sont obligatoires.")
            item={"column":technical_name(display),"display_name":display,"position":newpos,"group":group,"data_type":(request.form.get("data_type") or "text").lower(),"nullable":request.form.get("nullable")=="1","visible":request.form.get("visible")=="1","editable":request.form.get("editable")=="1","source":source,"transformation":request.form.get("transformation","").strip()}
            if any(c is not category and c["column"]==item["column"] for c in categories): raise ValueError(f"La colonne {item['column']} existe déjà.")
            categories.remove(category); categories.insert(newpos-1,item)
            for i,c in enumerate(categories,1): c["position"]=i
            config["logbook"]["columns"]=[c for c in lb["columns"] if c.get("group")=="system"]+categories; save_config(config); flash("Colonne logbook modifiée."); return redirect(url_for("main.logbook_settings"))
        except ValueError as exc: flash(str(exc))
    return render_template("logbook_column_form.html", category=category, groups=groups, positions=positions, action=url_for("main.edit_logbook_column",position=position))


@main_bp.route("/logbook/settings/column/<int:position>/delete", methods=["POST"])
@login_required
def delete_logbook_column(position):
    config=load_config(); lb=logbook_config(config); categories=[c for c in lb["columns"] if c.get("group")!="system"]; target=next((c for c in categories if int(c.get("position",0))==position),None)
    if target is None: flash("Colonne introuvable."); return redirect(url_for("main.logbook_settings"))
    categories=[c for c in categories if c is not target]
    for i,c in enumerate(categories,1): c["position"]=i
    config["logbook"]["columns"]=[c for c in lb["columns"] if c.get("group")=="system"]+categories; save_config(config)
    from .models import logbook_connect, drop_unused_logbook_columns
    conn=logbook_connect(); drop_unused_logbook_columns(conn,config); conn.commit(); conn.close(); flash(f"Colonne {target['column']} supprimée du logbook."); return redirect(url_for("main.logbook_settings"))


@main_bp.route("/settings")
@login_required
def settings():
    config = load_config()
    categories = _columns(config)
    groups = sorted({c.get("group") for c in categories if c.get("group")})
    return render_template("settings.html", categories=categories, groups=groups)


@main_bp.route("/settings/category/new", methods=["GET", "POST"])
@login_required
def new_category():
    config = load_config()
    categories = _columns(config)
    groups = sorted({c.get("group") for c in categories if c.get("group")})
    positions = list(range(1, len(categories) + 2))
    if request.method == "POST":
        try:
            selected_position = int(request.form.get("position", len(categories) + 1))
            if selected_position not in positions:
                raise ValueError("Position invalide.")
            category = _category_from_form(request.form, selected_position)
            if any(c["column"] == category["column"] for c in categories):
                raise ValueError(f"La colonne {category['column']} existe déjà.")
            categories.insert(selected_position - 1, category)
            for i, item in enumerate(categories, 1):
                item["position"] = i
            config["database"]["columns"] = [c for c in config["database"]["columns"] if c.get("group") == "system"] + categories
            save_config(config)
            flash("Colonne ajoutée à configuration.yml.")
            return redirect(url_for("main.settings"))
        except ValueError as exc:
            flash(str(exc))
    return render_template("category_form.html", category=None, groups=groups, positions=positions, next_position=len(categories) + 1, action=url_for("main.new_category"))


@main_bp.route("/settings/category/<int:position>/edit", methods=["GET", "POST"])
@login_required
def edit_category(position):
    config = load_config()
    categories = _columns(config)
    category = next((c for c in categories if int(c.get("position", 0)) == position), None)
    if category is None:
        flash("Colonne introuvable.")
        return redirect(url_for("main.settings"))
    groups = sorted({c.get("group") for c in categories if c.get("group")})
    positions = list(range(1, len(categories) + 1))
    if request.method == "POST":
        try:
            selected_position = int(request.form.get("position", position))
            if selected_position not in positions:
                raise ValueError("Position invalide.")
            updated = _category_from_form(request.form, selected_position, category)
            if any(c is not category and c["column"] == updated["column"] for c in categories):
                raise ValueError(f"La colonne {updated['column']} existe déjà.")
            categories.remove(category)
            categories.insert(selected_position - 1, updated)
            for i, item in enumerate(categories, 1):
                item["position"] = i
            config["database"]["columns"] = [c for c in config["database"]["columns"] if c.get("group") == "system"] + categories
            save_config(config)
            flash("Colonne modifiée dans configuration.yml.")
            return redirect(url_for("main.settings"))
        except (ValueError, StopIteration) as exc:
            flash(str(exc) or "Impossible de modifier la colonne.")
    return render_template("category_form.html", category=category, groups=groups, positions=positions, next_position=position, action=url_for("main.edit_category", position=position))


@main_bp.route("/settings/category/<int:position>/delete", methods=["POST"])
@login_required
def delete_category(position):
    config = load_config()
    categories = _columns(config)
    target = next((c for c in categories if int(c.get("position", 0)) == position), None)
    if target is None:
        flash("Colonne introuvable.")
        return redirect(url_for("main.settings"))
    categories = [c for c in categories if c is not target]
    for i, category in enumerate(categories, 1):
        category["position"] = i
    config["database"]["columns"] = [c for c in config["database"]["columns"] if c.get("group") == "system"] + categories
    save_config(config)
    from .models import connect, drop_unused_columns
    conn = connect()
    drop_unused_columns(conn, config)
    conn.commit()
    conn.close()
    flash(f"Colonne {target['column']} supprimée de la configuration et de user.db.")
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
    categories = _columns(config)
    if request.method == "POST":
        files = [f for f in request.files.getlist("files") if f and f.filename]
        if not files:
            flash("Sélectionnez au moins un fichier Excel.")
            return redirect(url_for("main.import_files"))
        total = 0
        for file in files:
            try:
                rows, matched_columns = importable_rows(file.filename, file.read(), categories)
                import_rows(file.filename, rows, config)
                total += len(rows)
                flash(f"{file.filename}: {len(rows)} ligne(s) importée(s), {matched_columns} colonne(s) reconnue(s).")
            except Exception as exc:
                flash(f"{file.filename}: import impossible — {exc}")
        flash(f"Import terminé: {total} ligne(s).")
        return redirect(url_for("main.index"))
    return render_template("import.html", categories=categories)
