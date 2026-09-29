import re
import io
import zipfile
from datetime import datetime
from flask import Blueprint, flash, redirect, render_template, request, url_for, send_file
from .auth import login_required
from .importer import importable_rows
from .db import safe_identifier, connect, logbook_connect, user_root, current_username
from .config import (load_config, save_config, configurable_columns, load_logbook_db_config,
                      load_logbook_layout, save_logbook_layout,
                      logbook_columns, technical_name, load_data_view, load_logbook_view)
from .converter import refresh_logbook, list_logbook_rows, update_logbook_cell
from .models import import_rows, drop_unused_columns
from .gridview import grid_data, grid_export

main_bp = Blueprint("main", __name__)

def _columns(config): return configurable_columns(config)

def _reposition(items):
    for i,c in enumerate(items,1): c["position"] = i

def _read_logbook_value(row, col):
    if col.get("db_column") == "date":
        value = row["date"] if "date" in row.keys() else None
        if not value: return ""
        try:
            dt=datetime.fromisoformat(str(value)[:10]); part=col.get("date_part")
            return getattr(dt,part) if part in {"year","month","day"} else value
        except ValueError: return ""
    db=col.get("db_column")
    if not db or db not in row.keys(): return ""
    return row[db] if row[db] is not None else ""

def _num(v):
    try: return float(str(v).strip().replace(",",".")) if str(v).strip() else 0.0
    except (ValueError,TypeError): return 0.0

def _is_numeric_layout(col):
    return bool(col.get("db_column")) and col.get("group") not in {"date","aircraft","crew","route","remarks","spacer"}

def _prepare_pages(rows, layout):
    cols=layout["columns"]; per_page=max(1,int(layout.get("rows_per_page",30))); pages=[]
    numeric_cols=[c for c in cols if _is_numeric_layout(c)]
    cumulative={c["key"]:0.0 for c in numeric_cols}
    def _with_total(totals):
        for c in cols:
            if c.get("total"): totals[c["key"]]=sum(totals.get(x["key"],0) for x in numeric_cols)
        return totals
    for start in range(0,len(rows),per_page):
        chunk=rows[start:start+per_page]
        totals=_with_total({c["key"]:sum(_num(_read_logbook_value(r,c)) for r in chunk) for c in numeric_cols})
        forwarded=_with_total(dict(cumulative))
        to_date=_with_total({k:forwarded.get(k,0)+totals.get(k,0) for k in totals})
        pages.append({"rows":chunk,"totals":totals,"forwarded":forwarded,"to_date":to_date,"number":start//per_page+1})
        cumulative={k:to_date.get(k,cumulative[k]) for k in cumulative}
    if not pages:
        zero=_with_total({c["key"]:0 for c in numeric_cols})
        pages=[{"rows":[],"totals":zero,"forwarded":dict(zero),"to_date":dict(zero),"number":1}]
    grand={c["key"]:sum(_num(_read_logbook_value(r,c)) for r in rows) for c in cols if _is_numeric_layout(c)}
    for c in cols:
        if c.get("total"): grand[c["key"]]=sum(grand.get(x["key"],0) for x in cols if _is_numeric_layout(x))
    return pages,grand

@main_bp.route("/")
@login_required
def index():
    config=load_config()
    return render_template("index.html",view=load_data_view(config))

@main_bp.route("/data/rows")
@login_required
def data_rows():
    columns=[c["column"] for c in configurable_columns(load_config())]
    conn=connect()
    try: return grid_data(conn,"users",columns)
    finally: conn.close()

@main_bp.route("/data/table-export.<fmt>")
@login_required
def data_table_export(fmt):
    view=load_data_view(load_config())
    conn=connect()
    try: return grid_export(conn,"users",[v["column"] for v in view],[v["label"] for v in view],fmt,f"{current_username()}_donnees_brutes")
    except ValueError as exc: flash(str(exc)); return redirect(url_for("main.index"))
    finally: conn.close()

@main_bp.route("/export")
@login_required
def export_user_data():
    username=current_username(); folder=user_root(username)
    buf=io.BytesIO()
    with zipfile.ZipFile(buf,"w",zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(folder.iterdir()):
            if f.is_file(): zf.write(f,arcname=f.name)
    buf.seek(0)
    stamp=datetime.now().strftime("%Y%m%d-%H%M%S")
    return send_file(buf,mimetype="application/zip",as_attachment=True,download_name=f"{username}_backup_{stamp}.zip")

@main_bp.route("/logbook-db")
@login_required
def logbook_db_page():
    return render_template("logbook_db.html",view=load_logbook_view())

@main_bp.route("/logbook-db/rows")
@login_required
def logbook_db_rows():
    columns=[c["column"] for c in logbook_columns(load_config())]
    conn=logbook_connect()
    try: return grid_data(conn,"logbook",columns)
    finally: conn.close()

@main_bp.route("/logbook-db/table-export.<fmt>")
@login_required
def logbook_table_export(fmt):
    view=load_logbook_view()
    conn=logbook_connect()
    try: return grid_export(conn,"logbook",[v["column"] for v in view],[v["label"] for v in view],fmt,f"{current_username()}_donnees_converties")
    except ValueError as exc: flash(str(exc)); return redirect(url_for("main.logbook_db_page"))
    finally: conn.close()

@main_bp.route("/logbook-db/export")
@login_required
def export_logbook_data():
    from .db import logbook_db_path
    from .config import logbook_db_config_path
    username=current_username()
    buf=io.BytesIO()
    with zipfile.ZipFile(buf,"w",zipfile.ZIP_DEFLATED) as zf:
        for f in (logbook_db_path(),logbook_db_config_path()):
            if f.exists(): zf.write(f,arcname=f.name)
    buf.seek(0)
    stamp=datetime.now().strftime("%Y%m%d-%H%M%S")
    return send_file(buf,mimetype="application/zip",as_attachment=True,download_name=f"{username}_donnees_converties_{stamp}.zip")

@main_bp.route("/logbook")
@login_required
def logbook():
    all_rows=list_logbook_rows()
    years=sorted({str(r["date"])[:4] for r in all_rows if r["date"]},reverse=True)
    selected_year=request.args.get("year","")
    if selected_year not in years: selected_year=years[0] if years else ""
    rows=[r for r in all_rows if selected_year=="" or (r["date"] or "").startswith(selected_year)]
    layout=load_logbook_layout(); dbcols=logbook_columns(load_config()); pages,grand=_prepare_pages(rows,layout)
    cols=layout["columns"]
    groups=[]; i=0
    while i < len(cols):
        g=cols[i].get("group"); j=i+1
        while j < len(cols) and cols[j].get("group")==g: j+=1
        groups.append({"group":g,"span":j-i,"label":layout.get("group_labels",{}).get(g,g)})
        i=j
    subgroups=[]; i=0
    while i < len(cols):
        g=cols[i].get("group")
        if g in {"single_engine","multi_engine","cross_country"}:
            sg=cols[i].get("subgroup"); j=i+1
            while j < len(cols) and cols[j].get("group")==g and cols[j].get("subgroup")==sg: j+=1
            subgroups.append({"span":j-i,"label":sg or ""})
            i=j
        else:
            j=i+1
            while j < len(cols) and cols[j].get("group")==g: j+=1
            subgroups.append({"span":j-i,"label":""})
            i=j
    label_colspan=next((i for i,c in enumerate(cols) if c.get("group") not in {"date","aircraft","crew","route","remarks","remarks_cont"}),len(cols))
    return render_template("logbook.html",layout=layout,pages=pages,grand=grand,dbcols=dbcols,read_value=_read_logbook_value,header_groups=groups,header_subgroups=subgroups,label_colspan=label_colspan,years=years,selected_year=selected_year)

@main_bp.route("/logbook/refresh",methods=["POST"])
@login_required
def refresh_logbook_data():
    try:
        result=refresh_logbook(load_config()); flash(f"logbook.db actualisé à partir de user.db ({result['rows']} ligne(s)).")
        for warning in result["warnings"]: flash(f"Attention — {warning}")
    except Exception as exc: flash(f"Actualisation du logbook impossible — {exc}")
    return redirect(url_for("main.logbook_db_page"))

@main_bp.route("/logbook/cell",methods=["POST"])
@login_required
def edit_logbook_cell():
    try:
        row_id=int(request.form.get("row_id","0")); column=safe_identifier(request.form.get("column","")); value=request.form.get("value","")
        allowed={c["column"] for c in logbook_columns(load_config())}
        if column not in allowed: raise ValueError("Colonne logbook invalide.")
        update_logbook_cell(row_id,column,value if value != "" else None); flash("Modification enregistrée.")
    except Exception as exc: flash(f"Modification impossible — {exc}")
    return redirect(url_for("main.logbook"))

@main_bp.route("/logbook/settings")
@login_required
def logbook_settings():
    layout=load_logbook_layout()
    return render_template("logbook_settings.html",layout=layout)

@main_bp.route("/logbook/settings/save",methods=["POST"])
@login_required
def save_logbook_settings():
    layout=load_logbook_layout()
    try:
        layout["rows_per_page"]=max(1,int(request.form.get("rows_per_page",30)))
        layout["row_height"]=float(request.form.get("row_height",16.95))
        layout["styles"]["font_family"]=request.form.get("font_family","Arial")
        layout["styles"]["font_size"]=int(request.form.get("font_size",10))
        layout["styles"]["header_font_size"]=int(request.form.get("header_font_size",9))
        layout["styles"]["header_background"]=request.form.get("header_background",layout["styles"].get("header_background","#ffffff"))
        layout["styles"]["total_background"]=request.form.get("total_background",layout["styles"].get("total_background","#eeeeee"))
        layout["styles"]["border"]=request.form.get("border",layout["styles"].get("border","1px solid #000000"))
        layout["styles"]["text_align"]=request.form.get("text_align",layout["styles"].get("text_align","center"))
        layout["styles"]["vertical_align"]=request.form.get("vertical_align",layout["styles"].get("vertical_align","middle"))
        heights=[]
        for i in range(4): heights.append(float(request.form.get(f"header_height_{i}",layout.get("header_heights",[16.95]*4)[i])))
        layout["header_heights"]=heights
        for c in layout["columns"]:
            c["width"]=float(request.form.get("width_"+c["key"],c.get("width",13)))
        save_logbook_layout(layout); flash("Configuration d'affichage du logbook enregistrée.")
    except Exception as exc: flash(f"Configuration impossible — {exc}")
    return redirect(url_for("main.logbook_settings"))

@main_bp.route("/logbook/settings/layout-column/<key>/delete",methods=["POST"])
@login_required
def delete_layout_column(key):
    layout=load_logbook_layout(); before=len(layout["columns"])
    layout["columns"]=[c for c in layout["columns"] if c["key"]!=key]
    if len(layout["columns"])==before: flash("Colonne introuvable.")
    else: save_logbook_layout(layout); flash("Colonne retirée de l'affichage du Logbook.")
    return redirect(url_for("main.logbook_settings"))

# Existing user database settings/import routes.
@main_bp.route("/settings")
@login_required
def settings():
    config=load_config(); categories=_columns(config); return render_template("settings.html",categories=categories,groups=sorted({c.get("group") for c in categories if c.get("group")}))

@main_bp.route("/settings/category/new",methods=["GET","POST"])
@login_required
def new_category():
    config=load_config(); categories=_columns(config)
    if request.method=="POST":
        try:
            display=request.form.get("display_name",request.form.get("affichage","")).strip(); group=request.form.get("group","").strip(); new_group=request.form.get("new_group","").strip(); group=new_group if group=="__new__" else group; rules=[x.strip() for x in request.form.get("import_rules",request.form.get("import","")).splitlines() if x.strip()]
            if not display or not group or not rules: raise ValueError("Display name, groupe et règles d'import sont obligatoires.")
            item={"column":technical_name(display),"display_name":display,"position":len(categories)+1,"group":group,"data_type":request.form.get("data_type","text"),"nullable":request.form.get("nullable","1")=="1","visible":request.form.get("visible","1")=="1","editable":request.form.get("editable","1")=="1","import_rules":rules}; categories.append(item); config["database"]["columns"]=config["database"]["columns"][:4]+categories; save_config(config); flash("Colonne ajoutée à userdb.yml."); return redirect(url_for("main.settings"))
        except ValueError as exc: flash(str(exc))
    return render_template("category_form.html",category=None,groups=sorted({c.get("group") for c in categories}),positions=[len(categories)+1],action=url_for("main.new_category"))

@main_bp.route("/settings/category/<int:position>/edit",methods=["GET","POST"])
@login_required
def edit_category(position):
    config=load_config(); categories=_columns(config); category=next((c for c in categories if int(c["position"])==position),None)
    if not category: flash("Colonne introuvable."); return redirect(url_for("main.settings"))
    if request.method=="POST":
        try:
            display=request.form.get("display_name","").strip(); group=request.form.get("group","").strip(); group=request.form.get("new_group","").strip() if group=="__new__" else group; rules=[x.strip() for x in request.form.get("import_rules","").splitlines() if x.strip()]
            if not display or not group or not rules: raise ValueError("Display name, groupe et règles d'import sont obligatoires.")
            item={"column":technical_name(display),"display_name":display,"position":position,"group":group,"data_type":request.form.get("data_type","text"),"nullable":request.form.get("nullable")=="1","visible":request.form.get("visible")=="1","editable":request.form.get("editable")=="1","import_rules":rules}; categories[categories.index(category)]=item; _reposition(categories); config["database"]["columns"]=config["database"]["columns"][:4]+categories; save_config(config); flash("Colonne modifiée dans userdb.yml."); return redirect(url_for("main.settings"))
        except ValueError as exc: flash(str(exc))
    return render_template("category_form.html",category=category,groups=sorted({c.get("group") for c in categories}),positions=list(range(1,len(categories)+1)),action=url_for("main.edit_category",position=position))

@main_bp.route("/settings/category/<int:position>/delete",methods=["POST"])
@login_required
def delete_category(position):
    config=load_config(); categories=_columns(config); target=next((c for c in categories if int(c["position"])==position),None)
    if not target: flash("Colonne introuvable."); return redirect(url_for("main.settings"))
    categories.remove(target); _reposition(categories); config["database"]["columns"]=config["database"]["columns"][:4]+categories; save_config(config); conn=connect(); drop_unused_columns(conn,config); conn.commit(); conn.close(); flash(f"Colonne {target['column']} supprimée de user.db."); return redirect(url_for("main.settings"))

@main_bp.route("/data/clear",methods=["POST"])
@login_required
def clear_data():
    conn=connect(); conn.execute("DELETE FROM users"); conn.commit(); conn.close(); flash("Les données de user.db ont été supprimées. Les YAML sont conservés."); return redirect(url_for("main.index"))

@main_bp.route("/import",methods=["GET","POST"])
@login_required
def import_files():
    config=load_config(); categories=_columns(config)
    if request.method=="POST":
        files=[f for f in request.files.getlist("files") if f and f.filename]
        if not files: flash("Sélectionnez au moins un fichier Excel."); return redirect(url_for("main.import_files"))
        total=0
        for file in files:
            try:
                rows,matched=importable_rows(file.filename,file.read(),categories); import_rows(file.filename,rows,config); total+=len(rows); flash(f"{file.filename}: {len(rows)} ligne(s) importée(s), {matched} colonne(s) reconnue(s).")
            except Exception as exc: flash(f"{file.filename}: import impossible — {exc}")
        flash(f"Import terminé: {total} ligne(s)."); return redirect(url_for("main.index"))
    return render_template("import.html",categories=categories)
