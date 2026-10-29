import re
import io
import zipfile
from datetime import datetime
from flask import Blueprint, flash, g, redirect, render_template, request, url_for, send_file
from .auth import login_required, fresh_login_required
from .importer import importable_rows
from .import_profiles import list_profiles, load_profile, ensure_profile_columns
from .merge import read_logbook_workbook
from .db import safe_identifier, connect, logbook_connect, user_root, current_username, backup_sqlite, db_path as user_db_path
from .config import (load_config, save_config, configurable_columns, load_logbook_db_config,
                      load_logbook_layout, save_logbook_layout,
                      logbook_columns, technical_name, load_data_view, load_logbook_view)
from .converter import refresh_logbook, list_logbook_rows, update_logbook_cell, update_logbook_date_part
from .models import import_rows, drop_unused_columns
from .gridview import grid_data, grid_export
from .logbook_pdf import build_logbook_pdf
from .errors import safe_message
from .seclog import log_event
from . import cssafe

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

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

_MONTHS = ("January","February","March","April","May","June","July","August","September","October","November","December")

@main_bp.app_template_filter("long_date")
def _long_date(row):
    """Date of a logbook row in words: June 5, 2013. Empty when incomplete."""
    try: y,m,d=int(row.get("year")),int(row.get("month")),int(row.get("day"))
    except (TypeError,ValueError): return ""
    if not 1<=m<=12: return ""
    return f"{_MONTHS[m-1]} {d}, {y}"

@main_bp.app_template_filter("two")
def _two(value):
    """Mois et jours toujours sur 2 chiffres : 5 -> 05. Vide reste vide."""
    try: return f"{int(value):02d}"
    except (TypeError, ValueError): return "" if value in (None,"") else str(value)

@main_bp.app_template_filter("hours1")
def _hours1(value):
    """Heures de vol à la française, toujours une décimale : 6.38 -> 6,4 ; 1234.5 -> 1 234,5. Vide reste vide."""
    if value is None or str(value).strip() in ("", "None"): return ""
    try: d = Decimal(str(value).strip().replace("\u00a0", "").replace(" ", "").replace(",", ".")).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError): return str(value)
    return f"{d:,.1f}".replace(",", "\u00a0").replace(".", ",")      # 1234.5 -> 1 234,5 (espace insécable, virgule)

def _is_numeric_layout(col):
    return bool(col.get("db_column")) and col.get("group") not in {"date","aircraft","crew","route","remarks","spacer","remarks_cont"}

def _num(v):
    try: return float(str(v).strip().replace(",",".")) if str(v).strip() not in ("","None") else 0.0
    except (ValueError,TypeError): return 0.0

def _grand_totals(summaries,engine_keys):
    """GRAND TOTAL de chaque page = somme de "Totals to date" sur les colonnes monomoteur et multimoteur
    uniquement (=SUM(L38:W38) dans le modèle Excel) ; instruments, vol sur campagne, atterrissages et
    instruction ne comptent pas."""
    out=[]
    for page in summaries:
        to_date=next(r for r in page if r["_kind"]=="to_date")
        out.append(round(sum(_num(to_date.get(k)) for k in engine_keys),1))
    return out

def _page_summary_rows(pages,numeric_keys,label_key,start=None):
    cumulative=dict(start) if start else {k:0.0 for k in numeric_keys}
    out=[]
    for page in pages:
        totals={k:round(sum(_num(row.get(k)) for row in page),1) for k in numeric_keys}
        forwarded={k:round(cumulative[k],1) for k in numeric_keys}
        to_date={k:round(forwarded[k]+totals[k],1) for k in numeric_keys}
        cumulative=dict(to_date)
        rows=[]
        for kind,values in (("page_total",totals),("forwarded",forwarded),("to_date",to_date)):
            row={k:"" for k in numeric_keys}; row.update(values); row["_kind"]=kind; row["id"]=None
            row[label_key]={"page_total":"Page Totals","forwarded":"Totals forwarded","to_date":"Totals to date"}[kind]
            rows.append(row)
        out.append(rows)
    return out,cumulative

@main_bp.route("/")
@login_required
def home():
    """Page d'accueil : le Logbook, sur l'année actuelle (ou la plus récente qui contient des vols)."""
    return redirect(url_for("main.logbook"))

@main_bp.route("/data")
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
    log_event("data_export", target="user folder (backup)")
    buf=io.BytesIO()
    with zipfile.ZipFile(buf,"w",zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(folder.iterdir()):
            if f.is_file(): zf.write(f,arcname=f.name)
    buf.seek(0)
    stamp=datetime.now().strftime("%Y%m%d-%H%M%S")
    return send_file(buf,mimetype="application/zip",as_attachment=True,download_name=f"{username}_backup_{stamp}.zip")

# année / mois / jour extraits de la date ISO (AAAA-MM-JJ) : colonnes calculées de la grille Données converties
DATE_EXPR={"year":'substr("date",1,4)',"month":'substr("date",6,2)',"day":'substr("date",9,2)'}

@main_bp.route("/logbook-db")
@login_required
def logbook_db_page():
    return render_template("logbook_db.html",view=load_logbook_view())

@main_bp.route("/logbook-db/rows")
@login_required
def logbook_db_rows():
    columns=[v["column"] for v in load_logbook_view()]
    conn=logbook_connect()
    try: return grid_data(conn,"logbook",columns,expressions=DATE_EXPR)
    finally: conn.close()

@main_bp.route("/logbook-db/table-export.<fmt>")
@login_required
def logbook_table_export(fmt):
    view=load_logbook_view()
    conn=logbook_connect()
    try: return grid_export(conn,"logbook",[v["column"] for v in view],[v["label"] for v in view],fmt,f"{current_username()}_donnees_converties",expressions=DATE_EXPR)
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

def _logbook_context():
    """Données du logbook (toutes les années) partagées par l'affichage et l'export PDF."""
    rows=list_logbook_rows()
    layout=load_logbook_layout()
    dbcols=logbook_columns(load_config())
    editable={d["column"]:d["editable"] for d in dbcols}
    columns=[c for c in layout["columns"] if c.get("key")!="total"]
    for c in columns:
        c["numeric"]=_is_numeric_layout(c)
        c["editable"]=bool(c.get("db_column")) and not c.get("date_part") and editable.get(c.get("db_column"),False)
    data=[{"id":row["id"],**{c["key"]:_read_logbook_value(row,c) for c in columns}} for row in rows]
    by_year={}
    for item in data:
        y=str(item.get("year") or "No date")
        by_year.setdefault(y,[]).append(item)
    years=sorted(by_year,key=lambda v:(v.isdigit(),v))   # croissant ; "Sans date" en premier (à gauche)
    year_pages={y:[by_year[y][i:i+30] for i in range(0,len(by_year[y]),30)] for y in years}
    numeric_keys=[c["key"] for c in columns if c["numeric"]]
    label_key=next((c["key"] for c in columns if c["key"]=="remarks"),columns[-1]["key"] if columns else "id")
    # Les totaux se suivent d'année en année : on parcourt les années dans l'ordre chronologique et le
    # "forwarded" de la 1re page d'une année reprend le "to date" de la dernière page de l'année précédente.
    # La numérotation des pages suit aussi d'année en année : une année qui commence après 3 pages démarre à la 4e.
    year_summaries={}; carry=None; year_page_offset={}; pages_before=0
    for y in sorted(years,key=lambda v:(not v.isdigit(),v)):
        if not y.isdigit():   # "Sans date" : cumul et numérotation à part
            year_summaries[y],_=_page_summary_rows(year_pages[y],numeric_keys,label_key); year_page_offset[y]=0; continue
        year_summaries[y],carry=_page_summary_rows(year_pages[y],numeric_keys,label_key,carry)
        year_page_offset[y]=pages_before; pages_before+=len(year_pages[y])
    engine_keys=[c["key"] for c in columns if c["numeric"] and c.get("group") in ("single_engine","multi_engine")]
    year_grand={y:_grand_totals(year_summaries[y],engine_keys) for y in years}
    return dict(layout=layout,columns=columns,years=years,year_pages=year_pages,year_summaries=year_summaries,year_grand=year_grand,year_page_offset=year_page_offset)

@main_bp.route("/logbook")
@login_required
def logbook():
    ctx=_logbook_context(); years=ctx["years"]
    requested=request.args.get("year","")
    current=str(datetime.now().year)
    active_year=requested if requested in years else (current if current in years else (years[-1] if years else ""))
    only=lambda d:{active_year:d[active_year]} if active_year in d else {}   # on n'envoie au navigateur que l'année affichée
    return render_template("logbook.html",layout=ctx["layout"],columns=ctx["columns"],years=years,year_pages=only(ctx["year_pages"]),year_summaries=only(ctx["year_summaries"]),year_grand=only(ctx["year_grand"]),active_year=active_year,year_page_offset=ctx["year_page_offset"])

@main_bp.route("/logbook/pdf")
@login_required
def logbook_pdf():
    """Export PDF : une année (?year=2019) ou toutes (?year=all). Réglages : section pdf: du layout YAML."""
    ctx=_logbook_context(); requested=request.args.get("year","")
    years=ctx["years"] if requested=="all" else ([requested] if requested in ctx["years"] else [])
    if not years:
        flash("No data to export for this year."); return redirect(url_for("main.logbook"))
    user=g.user
    email=(user["email"] if hasattr(user,"keys") and "email" in user.keys() else getattr(user,"email","")) if user else ""
    try: pdf=build_logbook_pdf(ctx,years,email or "")
    except ValueError as exc:
        flash(str(exc)); return redirect(url_for("main.logbook"))
    name=f"{current_username()}_logbook_{'all-years' if requested=='all' else requested}.pdf"
    return send_file(io.BytesIO(pdf),mimetype="application/pdf",as_attachment=True,download_name=name)

@main_bp.route("/logbook/refresh",methods=["POST"])
@login_required
def refresh_logbook_data():
    try:
        result=refresh_logbook(load_config()); flash(f"logbook.db refreshed from user.db ({result['rows']} row(s)).")
        for warning in result["warnings"]: flash(f"Attention — {warning}")
    except Exception as exc: flash(f"Logbook refresh impossible — {safe_message(exc)}")
    return redirect(url_for("main.logbook_db_page"))

@main_bp.route("/logbook/cell",methods=["POST"])
@login_required
def edit_logbook_cell():
    try:
        row_id=int(request.form.get("row_id","0")); column=safe_identifier(request.form.get("column","")); value=request.form.get("value","")
        if column in DATE_EXPR:
            update_logbook_date_part(row_id,column,value); return ("",204)
        allowed={c["column"] for c in logbook_columns(load_config())}
        if column not in allowed: raise ValueError("Invalid logbook column.")
        update_logbook_cell(row_id,column,value if value != "" else None)
        return ("",204)
    except Exception as exc:
        return (safe_message(exc),400)

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
        layout["row_height_u"]=int(float(request.form.get("row_height_u",layout.get("row_height_u",22))))
        layout["styles"]["font_family"]=request.form.get("font_family","Arial")
        layout["styles"]["font_size"]=int(request.form.get("font_size",10))
        layout["styles"]["header_font_size"]=int(request.form.get("header_font_size",9))
        layout["styles"]["header_background"]=request.form.get("header_background",layout["styles"].get("header_background","#ffffff"))
        layout["styles"]["total_background"]=request.form.get("total_background",layout["styles"].get("total_background","#eeeeee"))
        layout["styles"]["border"]=request.form.get("border",layout["styles"].get("border","1px solid #000000"))
        layout["styles"]["text_align"]=request.form.get("text_align",layout["styles"].get("text_align","center"))
        layout["styles"]["vertical_align"]=request.form.get("vertical_align",layout["styles"].get("vertical_align","middle"))
        for c in layout["columns"]:
            c["width"]=int(float(request.form.get("width_"+c["key"],c.get("width",51))))
        problems=cssafe.layout_problems(layout)
        if problems: raise ValueError(" ".join(problems))
        save_logbook_layout(layout); log_event("config_change", target="layout:logbook"); flash("Logbook display configuration saved.")
    except Exception as exc: flash(f"Configuration impossible — {safe_message(exc)}")
    return redirect(url_for("main.logbook_settings"))

@main_bp.route("/logbook/settings/layout-column/<key>/delete",methods=["POST"])
@login_required
def delete_layout_column(key):
    layout=load_logbook_layout(); before=len(layout["columns"])
    layout["columns"]=[c for c in layout["columns"] if c["key"]!=key]
    if len(layout["columns"])==before: flash("Column not found.")
    else: save_logbook_layout(layout); log_event("config_change", target=f"layout:colonne-retiree:{key}"); flash("Column removed from the Logbook display.")
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
            if not display or not group or not rules: raise ValueError("Display name, group and import rules are required.")
            item={"column":technical_name(display),"display_name":display,"position":len(categories)+1,"group":group,"data_type":request.form.get("data_type","text"),"nullable":request.form.get("nullable","1")=="1","visible":request.form.get("visible","1")=="1","editable":request.form.get("editable","1")=="1","import_rules":rules}; categories.append(item); config["database"]["columns"]=config["database"]["columns"][:4]+categories; save_config(config); log_event("config_change", target=f"colonne-ajoutee:{item['column']}"); flash("Column added to userdb.yml."); return redirect(url_for("main.settings"))
        except ValueError as exc: flash(str(exc))
    return render_template("category_form.html",category=None,groups=sorted({c.get("group") for c in categories}),positions=[len(categories)+1],action=url_for("main.new_category"))

@main_bp.route("/settings/category/<int:position>/edit",methods=["GET","POST"])
@login_required
def edit_category(position):
    config=load_config(); categories=_columns(config); category=next((c for c in categories if int(c["position"])==position),None)
    if not category: flash("Column not found."); return redirect(url_for("main.settings"))
    if request.method=="POST":
        try:
            display=request.form.get("display_name","").strip(); group=request.form.get("group","").strip(); group=request.form.get("new_group","").strip() if group=="__new__" else group; rules=[x.strip() for x in request.form.get("import_rules","").splitlines() if x.strip()]
            if not display or not group or not rules: raise ValueError("Display name, group and import rules are required.")
            technical_name(display); item={"column":category["column"],"display_name":display,"position":position,"group":group,"data_type":request.form.get("data_type","text"),"nullable":request.form.get("nullable")=="1","visible":request.form.get("visible")=="1","editable":request.form.get("editable")=="1","import_rules":rules}; categories[categories.index(category)]=item; _reposition(categories); config["database"]["columns"]=config["database"]["columns"][:4]+categories; save_config(config); log_event("config_change", target=f"colonne-modifiee:{item['column']}"); flash("Column updated in userdb.yml."); return redirect(url_for("main.settings"))
        except ValueError as exc: flash(str(exc))
    return render_template("category_form.html",category=category,groups=sorted({c.get("group") for c in categories}),positions=list(range(1,len(categories)+1)),action=url_for("main.edit_category",position=position))

@main_bp.route("/settings/category/<int:position>/delete",methods=["POST"])
@login_required
@fresh_login_required
def delete_category(position):
    config=load_config(); categories=_columns(config); target=next((c for c in categories if int(c["position"])==position),None)
    if not target: flash("Column not found."); return redirect(url_for("main.settings"))
    categories.remove(target); _reposition(categories); config["database"]["columns"]=config["database"]["columns"][:4]+categories; save_config(config); backup_sqlite(user_db_path(),"pre-drop"); conn=connect(); drop_unused_columns(conn,config); conn.commit(); conn.close(); log_event("data_destroy", target=f"colonne-supprimee:{target['column']}"); flash(f"Column {target['column']} deleted from user.db."); return redirect(url_for("main.settings"))

@main_bp.route("/data/clear",methods=["POST"])
@login_required
@fresh_login_required
def clear_data():
    conn=connect(); conn.execute("DELETE FROM users"); conn.commit(); conn.close(); log_event("data_destroy", target="donnees-brutes:toutes-les-lignes"); flash("The user.db data was deleted. The YAML files are kept."); return redirect(url_for("main.index"))

@main_bp.route("/import",methods=["GET","POST"])
@login_required
def import_files():
    config=load_config(); categories=_columns(config)
    if request.method=="POST":
        files=[f for f in request.files.getlist("files") if f and f.filename]
        if not files: flash("Select at least one Excel file."); return redirect(url_for("main.import_files"))
        profile=None; profile_id=request.form.get("profile","").strip()
        if profile_id:
            try:
                profile=load_profile(profile_id); added=ensure_profile_columns(config,profile)
            except Exception as exc: flash(f"Import profile error: {safe_message(exc)}"); return redirect(url_for("main.import_files"))
            if added: flash("Columns added to the database for this profile: "+", ".join(added)+".")
        total=0
        for file in files:
            try:
                data=file.read(); rows=None if profile else read_logbook_workbook(file.filename,data)
                if rows is not None: matched=len({k for r in rows for k,v in r.items() if v not in (None,"")})
                else: rows,matched=importable_rows(file.filename,data,categories,profile=profile)
                stats=import_rows(file.filename,rows,config,profile=profile["id"] if profile else None); total+=len(rows)
                flash(f"{file.filename}: {stats['read']} row(s) read, {matched} recognized column(s) — {stats['added']} flight(s) added, {stats['completed']} flight(s) completed ({sum(stats['filled'].values())} field(s) filled), {stats['unchanged']} unchanged, {stats['disagreements']} disagreement(s).")
                if stats["filled"]: flash("Completed fields: "+", ".join(f"{c} ×{n}" for c,n in stats["filled"].most_common(8)))
                for d,c,old,new in stats["samples"][:3]: flash(f"Disagreement (database value kept) — {d}, {c} : base “{old} ”, file “ {new}”.")
            except Exception as exc: flash(f"{file.filename}: import impossible — {safe_message(exc)}")
        log_event("data_import", target=f"{len(files)} file(s), {total} row(s) read"); flash(f"Import complete: {total} row(s) read."); return redirect(url_for("main.index"))
    return render_template("import.html",categories=categories,profiles=list_profiles())
