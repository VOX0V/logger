"""Entities: the global catalogue of every field (appdata/db/entities.db) and the only source of the columns of the four databases
(raw, work, location, aircraft): see fields.py. A field has a unique technical name (field) and a label."""
import io
import sqlite3

from flask import Blueprint, Response, abort, flash, jsonify, redirect, render_template, request, url_for
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

from . import fields
from .auth import admin_required, fresh_login_required, clear_confirmed
from .config import load_config, load_logbook_db_config, technical_name
from .db import db_dir, connect, logbook_connect, _open
from .models import sync_columns, drop_unused_columns, drop_unused_logbook_columns
from .seclog import log_event
from .workdb import DATA_TYPES, reset_cache

entities_bp = Blueprint("entities", __name__, url_prefix="/entities")

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
HEADERS = ["position", "label", "group", "name", "field", "data type", "visible", "editable", "nullable", "delete"]
FIELDS = {"group": "group_name", "name": "name", "entity": "entity", "data_type": "data_type", "display_name": "display_name"}
TYPES = [t for t in ("text", "integer", "decimal", "boolean", "date", "datetime") if t in DATA_TYPES]
KINDS = fields.DBS


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
    if conn.execute("PRAGMA user_version").fetchone()[0] == 0:       # the list is filled from the former file only once
        if conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0] == 0:
            _seed(conn)
        conn.execute("PRAGMA user_version=1")
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
    fields.invalidate()


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
        return "The field name is required."
    try:
        if technical_name(name) != name:
            raise ValueError
    except ValueError:
        return "A field name only uses lowercase letters, digits and underscores."
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
    old_field = None
    try:
        if column == "entity":
            found = conn.execute("SELECT entity FROM entities WHERE id=?", (row_id,)).fetchone()
            old_field = found[0] if found else None
        conn.execute(f"UPDATE entities SET {FIELDS[column]}=? WHERE id=?", (value, row_id))
        conn.commit()
    except sqlite3.IntegrityError:
        return ("This field already exists.", 409)
    finally:
        conn.close()
    if old_field and old_field != value:
        fields.rename_field(old_field, value)           # the databases, the roles and the YAML files follow the new name
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
        names = [r[0] for r in conn.execute(f"SELECT entity FROM entities WHERE id IN ({','.join('?' * len(ids))})", ids)]
        for name in names:
            used = fields.usage(name)
            if used:
                return (f"“{name}” is still used by: {', '.join(used)}. Remove it from them first.", 409)
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

    start = next((i for i, row in enumerate(table) if "field" in norm(row) or "entity" in norm(row)), None)      # the header may be below a title block
    if start is None:
        raise ValueError("No header row with a “field” column was found (other columns: position, label, group, name, data type).")
    header = norm(table[start])
    col = {h: i for i, h in enumerate(header) if h}

    def cell_of(row, *keys):
        for key in keys:
            i = col.get(key)
            value = row[i] if i is not None and i < len(row) else None
            if value not in (None, ""):
                return str(value).strip()
        return ""

    items, seen = [], set()
    for n, row in enumerate(table[start + 1:], start + 2):
        if not any(v not in (None, "") for v in row):
            continue
        entity = cell_of(row, "field", "entity")
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
                                             "display_name": cell_of(row, "label", "column_name", "display_name", "name") or entity}))
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
        ws.append([r["position"], r["display_name"], r["group"], r["name"], r["entity"], r["data_type"], None, None, None, None])
    for i, width in enumerate((10, 28, 14, 22, 32, 12, 10, 10, 10, 10), 1):
        ws.column_dimensions[get_column_letter(i)].width = width
    buf = io.BytesIO()
    wb.save(buf)
    return Response(buf.getvalue(), mimetype=XLSX, headers={"Content-Disposition": 'attachment; filename="entities.xlsx"'})


# ---------------- structure of the four databases (raw, work, location, aircraft) ----------------

def _kind(kind):
    if kind not in KINDS:
        abort(404)


def _structure_rows(kind):
    have = {c["column"]: c for c in fields.columns(kind)}
    conn = _conn()
    try:
        entities = _ordered(conn)
    finally:
        conn.close()
    out = []
    for e in entities:
        c = have.get(e["entity"])
        out.append({"column": e["entity"], "group": e["group"], "display_name": e["display_name"], "is_entity": True,
                    "present": c is not None, "visible": c["visible"] if c else True,
                    "editable": c["editable"] if c else True, "nullable": c["nullable"] if c else True})
    return out


def _apply_structure(kind):
    """The tables follow the settings: this account for raw and work (the others at their next login), the shared tables for the others."""
    if kind == "raw":
        cfg = load_config()
        db = connect()
        try:
            sync_columns(db, "users", cfg["database"]["columns"])
            drop_unused_columns(db, cfg)
            db.commit()
        finally:
            db.close()
    elif kind == "work":
        cfg = load_logbook_db_config()
        db = logbook_connect()
        try:
            sync_columns(db, "logbook", cfg["database"]["columns"])
            drop_unused_logbook_columns(db, cfg)
            db.commit()
        finally:
            db.close()
    else:
        from .refcolumns import apply
        apply(kind)


@entities_bp.route("/structure/<kind>")
@admin_required
def structure(kind):
    _kind(kind)
    return render_template("structure.html", kind=kind, title=KINDS[kind], rows=_structure_rows(kind), required=fields.required(kind))


@entities_bp.route("/structure/<kind>/save", methods=["POST"])
@admin_required
def structure_save(kind):
    _kind(kind)
    conn = _conn()
    try:
        entities = _ordered(conn)
    finally:
        conn.close()
    wanted = set(request.form.getlist("present"))
    flags = {k: set(request.form.getlist(k)) for k in ("visible", "editable", "nullable")}
    items = [{"field": e["entity"], "visible": e["entity"] in flags["visible"], "editable": e["entity"] in flags["editable"],
              "nullable": e["entity"] in flags["nullable"]} for e in entities if e["entity"] in wanted]
    try:
        removed = fields.save(kind, items)
    except ValueError as exc:
        flash(str(exc))
        return redirect(url_for("entities.structure", kind=kind))
    message = f"{KINDS[kind]} saved."
    try:
        _apply_structure(kind)
    except (sqlite3.Error, OSError, ValueError):
        message += " The tables could not be updated yet; they are updated at the next import, refresh or login."
    if removed:
        log_event("data_destroy", target=f"{kind}-structure:{len(removed)}-columns")
        message += f" {len(removed)} column(s) removed."
    flash(message)
    return redirect(url_for("entities.structure", kind=kind))


# ---------------- roles ----------------

@entities_bp.route("/roles", methods=["GET", "POST"])
@admin_required
def roles():
    """The names the program uses, each bound to one field (defaults/roles.yml)."""
    if request.method == "POST":
        mapping = {r: request.form.get("f_" + r, "").strip() for r in fields.role_map()}
        try:
            fields.save_roles({r: f for r, f in mapping.items() if f})
        except ValueError as exc:
            flash(str(exc))
        else:
            flash("Roles saved.")
            return redirect(url_for("entities.roles"))
    conn = _conn()
    try:
        entities = _ordered(conn)
    finally:
        conn.close()
    return render_template("roles.html", roles=fields.role_map(), entities=entities)
