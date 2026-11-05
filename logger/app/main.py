import re
import io
import zipfile
from datetime import datetime
from flask import Blueprint, flash, g, jsonify, redirect, render_template, request, url_for, send_file
from .auth import login_required, fresh_login_required, clear_confirmed
from .importer import importable_rows
from .import_profiles import list_profiles, load_profile, ensure_profile_columns, detect_profile
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

def _back(default):
    """Redirect to the Data page when the form comes from there (back=hub), otherwise to the page's own default."""
    return redirect(url_for("hubs.data") if request.form.get("back")=="hub" else url_for(default))

def _reposition(items):
    for i,c in enumerate(items,1): c["position"] = i

def _read_logbook_value(row, col):
    part = col.get("date_part")
    if part in {"year","month","day"} and "date" not in row.keys():      # work data with its own year / month / day columns
        return row[part] if part in row.keys() and row[part] is not None else ""
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
    view=load_data_view(config)
    return render_template("index.html",view=view,add_fields=[{"name":v["column"],"label":v["label"]} for v in view])

@main_bp.route("/data/rows")
@login_required
def data_rows():
    columns=[c["column"] for c in configurable_columns(load_config())]
    conn=connect()
    try: return grid_data(conn,"users",columns)
    finally: conn.close()

@main_bp.route("/import/detect",methods=["POST"])
@login_required
def detect_import_profile():
    file=request.files.get("file")
    if not file or not file.filename: return jsonify(profile=None,name=None)
    try: found=detect_profile(file.filename,file.read())
    except Exception: found=None
    return jsonify(profile=found["id"] if found else None,name=found["name"] if found else None)

@main_bp.route("/data/cell",methods=["POST"])
@login_required
def edit_data_cell():
    try:
        row_id=int(request.form.get("row_id","0")); column=safe_identifier(request.form.get("column","")); value=request.form.get("value","")
        if column not in {c["column"] for c in configurable_columns(load_config())}: raise ValueError("Invalid column.")
        conn=connect()
        try:
            conn.execute(f'UPDATE users SET "{column}"=?, updated_at=CURRENT_TIMESTAMP WHERE id=?',(value if value!="" else None,row_id)); conn.commit()
        finally: conn.close()
        return ("",204)
    except Exception as exc:
        return (safe_message(exc),400)

def _row_ids():
    try: ids=[int(x) for x in request.form.get("ids","").split(",") if x.strip()]
    except ValueError: ids=[]
    return ids[:5000]

def _add_row(connection,table,allowed,form):
    values={k:v.strip() for k,v in form.items() if k in allowed and v.strip()!=""}
    if not values: raise ValueError("Fill at least one field.")
    names=",".join(f'"{safe_identifier(k)}"' for k in values)
    conn=connection()
    try: conn.execute(f"INSERT INTO {table} ({names}) VALUES ({','.join('?'*len(values))})",list(values.values())); conn.commit()
    finally: conn.close()

def _delete_rows(connection,table,ids):
    conn=connection()
    try:
        for start in range(0,len(ids),500):
            chunk=ids[start:start+500]; conn.execute(f"DELETE FROM {table} WHERE id IN ({','.join('?'*len(chunk))})",chunk)
        conn.commit()
    finally: conn.close()

@main_bp.route("/data/add",methods=["POST"])
@login_required
def add_data_row():
    try:
        _add_row(connect,"users",{c["column"] for c in configurable_columns(load_config())},request.form); return ("",204)
    except Exception as exc: return (safe_message(exc),400)

@main_bp.route("/data/delete",methods=["POST"])
@login_required
def delete_data_rows():
    ids=_row_ids()
    if not ids: return ("No row selected.",400)
    _delete_rows(connect,"users",ids); log_event("data_destroy",target=f"raw-data:{len(ids)}-rows"); return ("",204)

@main_bp.route("/data/table-export.<fmt>")
@login_required
def data_table_export(fmt):
    view=load_data_view(load_config())
    conn=connect()
    try: return grid_export(conn,"users",[v["column"] for v in view],[v["label"] for v in view],fmt,f"{current_username()}_raw_data")
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

def _date_expr():
    """No computed year / month / day columns any more: the work data has its own date, year, month and day columns."""
    return {}

@main_bp.route("/logbook-db")
@login_required
def logbook_db_page():
    view=load_logbook_view()
    dx=_date_expr()
    fields=[({"name":v["column"],"label":v["label"],"kind":"date"} if v["column"]=="date" else {"name":v["column"],"label":v["label"]}) for v in view if v["column"] not in dx]
    return render_template("logbook_db.html",view=view,add_fields=fields)

@main_bp.route("/logbook-db/rows")
@login_required
def logbook_db_rows():
    columns=[v["column"] for v in load_logbook_view()]
    conn=logbook_connect()
    try: return grid_data(conn,"logbook",columns,expressions=_date_expr())
    finally: conn.close()

@main_bp.route("/logbook-db/add",methods=["POST"])
@login_required
def add_logbook_row():
    try:
        _add_row(logbook_connect,"logbook",{c["column"] for c in logbook_columns(load_config())}|{"date"},request.form); return ("",204)
    except Exception as exc: return (safe_message(exc),400)

@main_bp.route("/logbook-db/delete",methods=["POST"])
@login_required
def delete_logbook_rows():
    ids=_row_ids()
    if not ids: return ("No row selected.",400)
    _delete_rows(logbook_connect,"logbook",ids); log_event("data_destroy",target=f"work-data:{len(ids)}-rows"); return ("",204)

@main_bp.route("/logbook-db/table-export.<fmt>")
@login_required
def logbook_table_export(fmt):
    view=load_logbook_view()
    conn=logbook_connect()
    try: return grid_export(conn,"logbook",[v["column"] for v in view],[v["label"] for v in view],fmt,f"{current_username()}_work_data",expressions=_date_expr())
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
        for warning in result["warnings"]: flash(f"Warning — {warning}")
    except Exception as exc: flash(f"Logbook refresh impossible — {safe_message(exc)}")
    return _back("main.logbook_db_page")

@main_bp.route("/logbook-db/clear",methods=["POST"])
@login_required
@fresh_login_required
def clear_logbook_data():
    if not clear_confirmed(): flash("Nothing was deleted: type CLEAR to confirm."); return redirect(url_for("hubs.data"))
    conn=logbook_connect(); conn.execute("DELETE FROM logbook"); conn.commit(); conn.close(); log_event("data_destroy", target="work-data:all-rows"); flash("The work data was deleted. The YAML files are kept."); return redirect(url_for("hubs.data"))

@main_bp.route("/logbook/cell",methods=["POST"])
@login_required
def edit_logbook_cell():
    try:
        row_id=int(request.form.get("row_id","0")); column=safe_identifier(request.form.get("column","")); value=request.form.get("value","")
        if column in _date_expr():
            update_logbook_date_part(row_id,column,value); return ("",204)
        allowed={c["column"] for c in logbook_columns(load_config())}
        if column not in allowed: raise ValueError("Invalid logbook column.")
        update_logbook_cell(row_id,column,value if value != "" else None)
        return ("",204)
    except Exception as exc:
        return (safe_message(exc),400)

@main_bp.route("/data/clear",methods=["POST"])
@login_required
@fresh_login_required
def clear_data():
    if not clear_confirmed(): flash("Nothing was deleted: type CLEAR to confirm."); return redirect(url_for("hubs.data"))
    from .config import is_system
    config=load_config(); config["database"]["columns"]=[c for c in config["database"]["columns"] if is_system(c)]; save_config(config)
    conn=connect(); conn.execute("DELETE FROM users"); conn.execute("DELETE FROM sqlite_sequence WHERE name='users'"); drop_unused_columns(conn,config); conn.commit(); conn.close()
    log_event("data_destroy", target="raw-data:all-rows-and-columns"); flash("The raw data and its columns were deleted. The import profiles are kept."); return redirect(url_for("hubs.data"))

@main_bp.route("/import",methods=["GET","POST"])
@login_required
def import_files():
    config=load_config(); categories=_columns(config)
    if request.method=="POST":
        files=[f for f in request.files.getlist("files")+request.files.getlist("file") if f and f.filename]
        if not files: flash("Select a file to import."); return _back("main.import_files")
        profile_id=request.form.get("profile","").strip()
        if not profile_id: flash("Select an import profile."); return _back("main.import_files")
        try:
            profile=load_profile(profile_id); added=ensure_profile_columns(config,profile,extra=("crew_company",))
        except Exception as exc: flash(f"Import profile error: {safe_message(exc)}"); return _back("main.import_files")
        if added: flash("Columns added to the database for this profile: "+", ".join(added)+".")
        total=0
        for file in files:
            try:
                data=file.read(); rows,matched=importable_rows(file.filename,data,profile=profile)
                company="undefined" if profile["id"]=="default" else profile["name"]        # an empty company gets the profile name
                for r in rows:
                    if not r.get("crew_company"): r["crew_company"]=company
                stats=import_rows(file.filename,rows,config,profile=profile["id"]); total+=len(rows)
                flash(f"{file.filename}: {stats['read']} row(s) read, {matched} recognized column(s) — {stats['added']} flight(s) added, {stats['completed']} flight(s) completed ({sum(stats['filled'].values())} field(s) filled), {stats['unchanged']} unchanged, {stats['disagreements']} disagreement(s).")
                if stats["filled"]: flash("Completed fields: "+", ".join(f"{c} ×{n}" for c,n in stats["filled"].most_common(8)))
                for d,c,old,new in stats["samples"][:3]: flash(f"Disagreement (database value kept) — {d}, {c} : base “{old} ”, file “ {new}”.")
            except Exception as exc: flash(f"{file.filename}: import impossible — {safe_message(exc)}")
        log_event("data_import", target=f"{len(files)} file(s), {total} row(s) read"); flash(f"Import complete: {total} row(s) read."); return _back("main.index")
    return render_template("import.html",profiles=list_profiles(include_default=True))
