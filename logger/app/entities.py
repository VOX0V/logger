"""Entities: the global catalogue of everything a raw or work database may contain (appdata/db/entities.db),
and the pages where each account chooses which entities are present in its raw and work databases."""
import io
import json
import sqlite3

from flask import Blueprint, Response, abort, flash, jsonify, redirect, render_template, request, url_for
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

from .auth import login_required, admin_required, fresh_login_required, clear_confirmed
from .config import (load_config, save_config, load_logbook_db_config, save_logbook_db_config,
                     is_system, technical_name)
from .db import db_dir, connect, logbook_connect, _open
from .models import sync_columns, drop_unused_columns, drop_unused_logbook_columns
from .seclog import log_event
from .workdb import DATA_TYPES, reset_cache

entities_bp = Blueprint("entities", __name__, url_prefix="/entities")

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
HEADERS = ["position", "group", "name", "entity", "data type", "display name"]
FIELDS = {"group": "group_name", "name": "name", "entity": "entity", "data_type": "data_type", "display_name": "display_name"}
TYPES = [t for t in ("text", "integer", "decimal", "boolean", "date", "datetime") if t in DATA_TYPES]
KINDS = {"raw": "Raw db structure", "work": "Work db structure"}


# ---------------- storage ----------------

def _short(group, entity):
    return entity[len(group) + 1:] if group and entity.startswith(group + "_") else entity


def _seed(conn):
    """First use: the list is taken from the former entities.yml (edited copy or shipped file)."""
    try:
        import yaml
        from .import_profiles import entities_path, parse_entities
        items = list(parse_entities(yaml.safe_load(entities_path().read_text(encoding="utf-8")) or {}).values())
    except Exception:       # no readable former list: the page starts empty
        return
    for i, e in enumerate(items, 1):
        conn.execute("INSERT OR IGNORE INTO entities (position, group_name, name, entity, data_type, display_name) VALUES (?,?,?,?,?,?)",
                     (i, e["group"], _short(e["group"], e["entity"]), e["entity"], e["data_type"], e["display_name"]))


def _conn():
    conn = _open(db_dir() / "entities.db")
    conn.execute("""CREATE TABLE IF NOT EXISTS entities (
        id INTEGER PRIMARY KEY AUTOINCREMENT, position INTEGER NOT NULL,
        group_name TEXT NOT NULL DEFAULT '', name TEXT NOT NULL DEFAULT '',
        entity TEXT NOT NULL UNIQUE, data_type TEXT NOT NULL DEFAULT 'text', display_name TEXT NOT NULL DEFAULT '')""")
    if conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0] == 0:
        _seed(conn)
    conn.commit()
    return conn


def _ordered(conn):
    cur = conn.execute("SELECT id, position, group_name, name, entity, data_type, display_name FROM entities ORDER BY position, id")
    return [{"id": r[0], "position": r[1], "group": r[2], "name": r[3], "entity": r[4], "data_type": r[5], "display_name": r[6]}
            for r in cur.fetchall()]


def _renumber(conn, ids):
    for i, row_id in enumerate(ids, 1):
        conn.execute("UPDATE entities SET position=? WHERE id=?", (i, row_id))


def _changed():
    reset_cache()


def load_entities():
    """{entity: {entity, group, data_type, display_name}} in position order (used by the imports and the work data)."""
    conn = _conn()
    try:
        rows = _ordered(conn)
    finally:
        conn.close()
    if not rows:
        from .importer import FileImportError
        raise FileImportError("The entity list is empty (Data > Entities).")
    return {r["entity"]: {"entity": r["entity"], "group": r["group"], "data_type": r["data_type"],
                          "display_name": r["display_name"]} for r in rows}


def _entity_error(name):
    if not name:
        return "The entity name is required."
    try:
        if technical_name(name) != name:
            raise ValueError
    except ValueError:
        return "An entity name only uses lowercase letters, digits and underscores."
    return ""


def _int_ids(raw):
    try:
        return [int(x) for x in raw.split(",") if x.strip()]
    except ValueError:
        return []


# ---------------- entities page (administrators) ----------------

@entities_bp.route("/")
@admin_required
def index():
    return render_template("entities.html", types=TYPES)


@entities_bp.route("/rows")
@admin_required
def rows():
    conn = _conn()
    try:
        return jsonify(_ordered(conn))
    finally:
        conn.close()


@entities_bp.route("/cell", methods=["POST"])
@admin_required
def cell():
    try:
        row_id = int(request.form["row_id"])
    except (KeyError, ValueError):
        return ("Invalid request.", 400)
    column = request.form.get("column", "")
    value = request.form.get("value", "").strip()
    if column not in FIELDS:
        return ("Unknown column.", 400)
    if column == "entity" and _entity_error(value):
        return (_entity_error(value), 400)
    if column == "data_type" and value not in TYPES:
        return ("Unknown data type.", 400)
    conn = _conn()
    try:
        conn.execute(f"UPDATE entities SET {FIELDS[column]}=? WHERE id=?", (value, row_id))
        conn.commit()
    except sqlite3.IntegrityError:
        return ("This entity already exists.", 409)
    finally:
        conn.close()
    _changed()
    return ("", 204)


@entities_bp.route("/add", methods=["POST"])
@admin_required
def add():
    group = request.form.get("group", "").strip()
    name = request.form.get("name", "").strip()
    entity = request.form.get("entity", "").strip()
    if not entity:
        try:
            entity = technical_name("_".join(x for x in (group, name) if x))
        except ValueError:
            entity = ""
    if _entity_error(entity):
        return (_entity_error(entity), 400)
    data_type = (request.form.get("data_type", "") or "text").strip()
    if data_type not in TYPES:
        return ("Unknown data type.", 400)
    display = request.form.get("display_name", "").strip() or name or entity
    conn = _conn()
    try:
        position = conn.execute("SELECT COALESCE(MAX(position), 0) + 1 FROM entities").fetchone()[0]
        conn.execute("INSERT INTO entities (position, group_name, name, entity, data_type, display_name) VALUES (?,?,?,?,?,?)",
                     (position, group, name or _short(group, entity), entity, data_type, display))
        conn.commit()
    except sqlite3.IntegrityError:
        return ("This entity already exists.", 409)
    finally:
        conn.close()
    _changed()
    return ("", 204)


@entities_bp.route("/delete", methods=["POST"])
@admin_required
def delete():
    ids = _int_ids(request.form.get("ids", ""))
    if not ids:
        return ("No row selected.", 400)
    conn = _conn()
    try:
        conn.execute(f"DELETE FROM entities WHERE id IN ({','.join('?' * len(ids))})", ids)
        _renumber(conn, [r["id"] for r in _ordered(conn)])
        conn.commit()
    finally:
        conn.close()
    log_event("data_destroy", target=f"entities:{len(ids)}-rows")
    _changed()
    return ("", 204)


@entities_bp.route("/move", methods=["POST"])
@admin_required
def move():
    """The dragged row takes the target number; the rows from there on are pushed down."""
    try:
        row_id = int(request.form["id"])
        target = int(request.form["position"])
    except (KeyError, ValueError):
        return ("Invalid request.", 400)
    conn = _conn()
    try:
        ids = [r["id"] for r in _ordered(conn)]
        if row_id not in ids:
            return ("Entity not found.", 404)
        ids.remove(row_id)
        ids.insert(max(0, min(target - 1, len(ids))), row_id)
        _renumber(conn, ids)
        conn.commit()
    finally:
        conn.close()
    _changed()
    return ("", 204)


def _read_xlsx(stream):
    try:
        wb = load_workbook(stream, read_only=True, data_only=True)
        ws = wb["Entities"] if "Entities" in wb.sheetnames else wb.active
        table = [list(r) for r in ws.iter_rows(values_only=True)]
        wb.close()
    except Exception as exc:        # unreadable or not an Excel file
        raise ValueError("The file cannot be read: use an Excel workbook (.xlsx).") from exc
    if not table:
        raise ValueError("The file is empty.")
    def norm(row):
        return [str(h or "").strip().lower().replace(" ", "_") for h in row]

    start = next((i for i, row in enumerate(table) if "entity" in norm(row)), None)      # the header may be below a title block
    if start is None:
        raise ValueError("No header row with an “entity” column was found (other columns: position, group, name, data type, display name).")
    header = norm(table[start])
    col = {h: i for i, h in enumerate(header) if h}

    def cell_of(row, key):
        i = col.get(key)
        value = row[i] if i is not None and i < len(row) else None
        return "" if value is None else str(value).strip()

    items, seen = [], set()
    for n, row in enumerate(table[start + 1:], start + 2):
        if not any(v not in (None, "") for v in row):
            continue
        entity = cell_of(row, "entity")
        error = _entity_error(entity)
        if error:
            raise ValueError(f"Row {n}: {error}")
        if entity in seen:
            raise ValueError(f"Row {n}: “{entity}” is defined twice.")
        seen.add(entity)
        data_type = (cell_of(row, "data_type") or "text").lower()
        if data_type not in TYPES:
            raise ValueError(f"Row {n}: unknown data type “{data_type}”.")
        group = cell_of(row, "group")
        try:
            position = float(cell_of(row, "position"))
        except ValueError:
            position = float("inf")
        items.append((position, len(items), {"group": group, "name": cell_of(row, "name") or _short(group, entity),
                                             "entity": entity, "data_type": data_type,
                                             "display_name": cell_of(row, "display_name") or cell_of(row, "name") or entity}))
    if not items:
        raise ValueError("The file has no entity.")
    items.sort(key=lambda t: (t[0], t[1]))
    return [t[2] for t in items]


@entities_bp.route("/import", methods=["POST"])
@admin_required
def import_xlsx():
    file = request.files.get("file")
    if not file or not file.filename:
        flash("Select an Excel file to import.")
        return redirect(url_for("entities.index"))
    try:
        items = _read_xlsx(file.stream)
    except ValueError as exc:
        flash(f"Nothing was imported. {exc}")
        return redirect(url_for("entities.index"))
    conn = _conn()
    try:
        conn.execute("DELETE FROM entities")
        for i, e in enumerate(items, 1):
            conn.execute("INSERT INTO entities (position, group_name, name, entity, data_type, display_name) VALUES (?,?,?,?,?,?)",
                         (i, e["group"], e["name"], e["entity"], e["data_type"], e["display_name"]))
        conn.commit()
    finally:
        conn.close()
    log_event("data_destroy", target=f"entities:replaced-by-{len(items)}-rows")
    _changed()
    from .import_profiles import broken_profiles
    message = f"{len(items)} entities imported (the previous list was replaced)."
    bad = broken_profiles()
    if bad:
        message += f" Warning: {len(bad)} import profile(s) no longer work ({', '.join(p for p, _ in bad)}). First error: {bad[0][1]}"
    flash(message)
    return redirect(url_for("entities.index"))


@entities_bp.route("/clear", methods=["POST"])
@admin_required
@fresh_login_required
def clear():
    if not clear_confirmed():
        flash("Nothing was deleted: type CLEAR to confirm.")
        return redirect(url_for("hubs.data"))
    conn = _conn()
    try:
        conn.execute("DELETE FROM entities")
        conn.commit()
    finally:
        conn.close()
    log_event("data_destroy", target="entities:all-rows")
    _changed()
    flash("All entities were deleted.")
    return redirect(url_for("hubs.data"))


@entities_bp.route("/export")
@admin_required
def export():
    conn = _conn()
    try:
        data = _ordered(conn)
    finally:
        conn.close()
    wb = Workbook()
    ws = wb.active
    ws.title = "Entities"
    ws.append(HEADERS)
    for c in ws[1]:
        c.font = Font(bold=True)
    for r in data:
        ws.append([r["position"], r["group"], r["name"], r["entity"], r["data_type"], r["display_name"]])
    for i, width in enumerate((10, 14, 22, 32, 12, 28), 1):
        ws.column_dimensions[get_column_letter(i)].width = width
    buf = io.BytesIO()
    wb.save(buf)
    return Response(buf.getvalue(), mimetype=XLSX, headers={"Content-Disposition": 'attachment; filename="entities.xlsx"'})


# ---------------- raw / work db structure (each account) ----------------

def _kind(kind):
    if kind not in KINDS:
        abort(404)


def _load(kind):
    return load_config() if kind == "raw" else load_logbook_db_config()


def _structure_rows(kind):
    columns = [c for c in _load(kind)["database"]["columns"] if not is_system(c)]
    by = {c["column"]: c for c in columns}
    conn = _conn()
    try:
        entities = _ordered(conn)
    finally:
        conn.close()
    out, names = [], set()
    for e in entities:
        names.add(e["entity"])
        c = by.get(e["entity"])
        out.append({"column": e["entity"], "group": e["group"], "display_name": e["display_name"], "is_entity": True,
                    "present": c is not None, "visible": c["visible"] if c else True,
                    "editable": c["editable"] if c else True, "nullable": c["nullable"] if c else True})
    for c in columns:
        if c["column"] not in names:
            out.append({"column": c["column"], "group": "", "display_name": c["display_name"], "is_entity": False,
                        "present": True, "visible": c["visible"], "editable": c["editable"], "nullable": c["nullable"]})
    return out


@entities_bp.route("/structure/work")
@admin_required
def work_structure():
    """Structure of the work data (columns, types, order), the same for all accounts."""
    from .workstructure import columns
    present = columns()
    have = {c["column"] for c in present}
    conn = _conn()
    try:
        entities = _ordered(conn)
    finally:
        conn.close()
    return render_template("work_structure.html", title=KINDS["work"], types=TYPES,
                           rows=[{k: c[k] for k in ("column", "display_name", "data_type", "visible", "editable", "nullable")} for c in present],
                           available=[{"entity": e["entity"], "title": e["display_name"], "data_type": e["data_type"]}
                                      for e in entities if e["entity"] not in have])


@entities_bp.route("/structure/work/save", methods=["POST"])
@admin_required
def work_structure_save():
    from .workstructure import save
    from .workdb import apply_to_user
    try:
        removed = save(json.loads(request.form.get("columns", "[]")))
    except (ValueError, sqlite3.Error) as exc:
        flash(str(exc))
        return redirect(url_for("entities.work_structure"))
    message = "Work db structure saved."
    apply_to_user()                                    # this account follows the structure now, the others at their next login or refresh
    cfg = load_logbook_db_config()
    db = logbook_connect()
    try:
        sync_columns(db, "logbook", cfg["database"]["columns"])
        drop_unused_logbook_columns(db, cfg)
        db.commit()
    except sqlite3.OperationalError:
        db.rollback()
        message += " The table could not be updated yet; it is updated by the next refresh."
    finally:
        db.close()
    if removed:
        log_event("data_destroy", target=f"work-structure:{len(removed)}-columns")
        message += f" {len(removed)} column(s) removed."
    flash(message)
    return redirect(url_for("entities.work_structure"))


@entities_bp.route("/structure/<kind>")
@login_required
def structure(kind):
    _kind(kind)
    return render_template("structure.html", kind=kind, title=KINDS[kind], rows=_structure_rows(kind))


@entities_bp.route("/structure/<kind>/save", methods=["POST"])
@login_required
def structure_save(kind):
    _kind(kind)
    cfg = _load(kind)
    system = [c for c in cfg["database"]["columns"] if is_system(c)]
    old = [c for c in cfg["database"]["columns"] if not is_system(c)]
    existing = {c["column"]: c for c in old}
    conn = _conn()
    try:
        entities = _ordered(conn)
    finally:
        conn.close()
    wanted = set(request.form.getlist("present"))
    flags = {k: set(request.form.getlist(k)) for k in ("visible", "editable", "nullable")}

    def build(column, display, data_type):
        return {"column": column, "display_name": display, "position": 0, "data_type": data_type,
                "nullable": column in flags["nullable"], "visible": column in flags["visible"],
                "editable": column in flags["editable"]}

    new = []
    entity_names = {e["entity"] for e in entities}
    for e in entities:                      # the entities first, in the order of the entity list
        if e["entity"] in wanted:
            new.append(build(e["entity"], e["display_name"], (existing.get(e["entity"]) or {}).get("data_type") or ("text" if kind == "raw" else e["data_type"])))
    for c in old:                           # then the columns that are not entities
        if c["column"] not in entity_names and c["column"] in wanted:
            new.append(build(c["column"], c["display_name"], c["data_type"]))
    for i, c in enumerate(new, 1):
        c["position"] = i
    kept = {c["column"] for c in new}
    removed = [c["column"] for c in old if c["column"] not in kept]
    cfg["database"]["columns"] = system + new
    if kind == "raw":
        save_config(cfg)
    else:
        save_logbook_db_config(cfg)
    message = f"{KINDS[kind]} saved."
    db = connect() if kind == "raw" else logbook_connect()
    try:
        if kind == "raw":
            sync_columns(db, "users", cfg["database"]["columns"])
            drop_unused_columns(db, cfg)
        else:
            sync_columns(db, "logbook", cfg["database"]["columns"])
            drop_unused_logbook_columns(db, cfg)
        db.commit()
    except sqlite3.OperationalError:
        db.rollback()
        message += " The table could not be updated yet; it is updated by the next import or refresh."
    finally:
        db.close()
    if removed:
        log_event("data_destroy", target=f"{kind}-structure:{len(removed)}-columns")
        message += f" {len(removed)} column(s) removed."
    flash(message)
    return redirect(url_for("entities.structure", kind=kind))
