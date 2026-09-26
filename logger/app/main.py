import sqlite3
from pathlib import Path
from flask import Blueprint, current_app, request, redirect, url_for, render_template, flash
from werkzeug.utils import secure_filename
from .auth import login_required
from .importer import read_excel_files, build_records
from .models import get_db, list_categories, list_rules_by_category, table_columns

main_bp = Blueprint("main", __name__)
TMP_DIR = "import_tmp"


def _tmp_path(token):
    path = Path(current_app.instance_path) / TMP_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path / f"{token}.bin"


@main_bp.route("/")
@login_required
def index():
    db = get_db()
    categories = list_categories(db)
    existing = set(table_columns(db))
    visible_categories = [c for c in categories if c["column_name"] in existing]
    columns = ["id"] + [c["column_name"] for c in visible_categories]
    rows = db.execute(f'SELECT {", ".join(chr(34)+c+chr(34) for c in columns)} FROM users ORDER BY id').fetchall()
    count = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    db.close()
    return render_template("index.html", categories=visible_categories, rows=rows, count=count)


@main_bp.route("/import", methods=["GET", "POST"])
@login_required
def import_users():
    if request.method == "GET":
        return render_template("import_form.html")
    uploads = [f for f in request.files.getlist("files") if f and f.filename]
    if not uploads:
        return render_template("import_form.html", error="Sélectionnez au moins un fichier Excel.")
    files = []
    for upload in uploads:
        filename = secure_filename(upload.filename) or "import.xlsx"
        if not filename.lower().endswith((".xlsx", ".xlsm")):
            return render_template("import_form.html", error="Seuls les fichiers .xlsx et .xlsm sont acceptés.")
        files.append((filename, upload.read()))
    db = get_db()
    categories = list_categories(db)
    rules = list_rules_by_category(db)
    if not categories:
        db.close()
        return render_template("import_form.html", error="Créez d'abord au moins une catégorie dans Settings.")
    try:
        sources = read_excel_files(files)
        existing = set(table_columns(db))
        importable_categories = [c for c in categories if c["column_name"] in existing]
        records, report = build_records(sources, importable_categories, rules)

        # Replace the previous import for each uploaded filename.
        # Data that has no matching configured/database column is simply ignored.
        db.execute("BEGIN")
        filenames = {filename for filename, _sheet, _headers, _rows in sources}
        for filename in filenames:
            db.execute("DELETE FROM users WHERE import_source = ?", (filename,))

        columns = [c["column_name"] for c in importable_categories]
        columns_sql = columns + ["import_source"]
        placeholders = ",".join("?" for _ in columns_sql)
        if columns:
            sql = f'INSERT INTO users ({", ".join(chr(34)+c+chr(34) for c in columns_sql)}) VALUES ({placeholders})'
            for record in records:
                values = [record.get(c) for c in columns] + [record.get("_import_source")]
                db.execute(sql, values)
        db.commit()
        db.close()
    except ValueError as exc:
        db.close()
        return render_template("import_form.html", error=str(exc))
    except sqlite3.Error as exc:
        db.rollback()
        db.close()
        return render_template("import_form.html", error=f"Import impossible : {exc}")
    flash(f"Import terminé : {len(records)} ligne(s) importée(s). Les fichiers réimportés ont remplacé leur import précédent.")
    return render_template("import_done.html", count=len(records), report=report)
