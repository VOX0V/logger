"""Base temporaire (tempdb) et pages de revue des imports et des conversions.

Un import ne touche plus directement la base brute : les lignes du fichier vont dans users/<nom>/<nom>_temp.db,
une page de revue liste ce qui sera ajouté, ce qui est déjà présent et les lignes semblables mais différentes
(choix ligne par ligne), puis la validation transfère le résultat dans la base brute.
Convert suit le même principe entre la base brute et la base de travail.
La tempdb est supprimée à la validation, à l'annulation, quand un nouvel import / une nouvelle conversion la remplace,
et dès que la personne quitte la page de revue.
"""
import json
import sqlite3

from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from . import journal
from .auth import login_required
from .config import load_config, configurable_columns, load_data_view, load_logbook_view
from .converter.engine import build_logbook, insert_work_row
from .db import connect, logbook_connect, current_username, user_file, safe_identifier
from .errors import safe_message
from .merge import blank, hours, merge_context, plan_review, row_date
from .models import ensure_profile_column, sync_user_columns, sync_logbook_columns, drop_unused_logbook_columns
from .seclog import log_event

review_bp = Blueprint("review", __name__, url_prefix="/review")


# ---------------- tempdb ----------------

def temp_path():
    return user_file(f"{current_username()}_temp.db")


def drop_temp():
    base = temp_path()
    for suffix in ("", "-journal", "-wal", "-shm"):
        try:
            base.with_name(base.name + suffix).unlink()
        except OSError:
            pass


def _new_temp(kind, info):
    drop_temp()
    conn = sqlite3.connect(temp_path())
    conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY AUTOINCREMENT, section TEXT NOT NULL, data TEXT NOT NULL)")
    conn.execute("INSERT INTO meta VALUES ('kind', ?)", (kind,))
    conn.execute("INSERT INTO meta VALUES ('info', ?)", (json.dumps(info),))
    return conn


def _add_item(conn, section, data):
    conn.execute("INSERT INTO items (section, data) VALUES (?, ?)", (section, json.dumps(data, default=str)))


def _read_temp(kind):
    """(info, items) of the waiting import / conversion, or None."""
    path = temp_path()
    if not path.exists():
        return None
    conn = sqlite3.connect(path)
    try:
        row = conn.execute("SELECT value FROM meta WHERE key='kind'").fetchone()
        if not row or row[0] != kind:
            return None
        info = json.loads(conn.execute("SELECT value FROM meta WHERE key='info'").fetchone()[0])
        items = [{"id": r[0], "section": r[1], **json.loads(r[2])} for r in conn.execute("SELECT id, section, data FROM items ORDER BY id")]
        return info, items
    except (sqlite3.Error, ValueError, TypeError):
        return None
    finally:
        conn.close()


@review_bp.before_app_request
def drop_temp_when_leaving():
    """The tempdb only lives while its review page is open: any other page navigation deletes it."""
    if g.get("user") is None or request.method != "GET":
        return None
    endpoint = request.endpoint or ""
    if endpoint.startswith("review.") or endpoint == "static":
        return None
    if "text/html" not in request.headers.get("Accept", ""):
        return None
    if temp_path().exists():
        drop_temp()
    return None


# ---------------- staging ----------------

def stage_import(staged, profile_id, profile_name):
    """staged: [(filename, rows, matched_columns)]. Compares the rows with the raw database and fills the tempdb."""
    config = load_config()
    cols = [safe_identifier(c["column"]) for c in configurable_columns(config)]
    incoming, origin = [], []
    for filename, rows, _matched in staged:
        for row in rows:
            incoming.append(row)
            origin.append(filename)
    conn = connect()
    try:
        have = {r[1] for r in conn.execute("PRAGMA table_info(users)")}      # the columns are created when the import is validated
        quoted = "".join("," + chr(34) + c + chr(34) for c in cols if c in have)
        cursor = conn.execute(f"SELECT technical_raw_id AS id{quoted} FROM users ORDER BY technical_raw_id")
        names = [d[0] for d in cursor.description]
        existing = [dict(zip(names, row)) for row in cursor.fetchall()]
    finally:
        conn.close()
    plan = plan_review(existing, incoming, cols, merge_context())
    tmp = _new_temp("import", {"profile": profile_id, "profile_name": profile_name, "files": [f for f, _, _ in staged], "created": journal.now()})
    try:
        for entry, source in zip(plan, origin):
            _add_item(tmp, entry["kind"], {"rec": entry["rec"], "match_id": entry["match_id"], "fills": entry["fills"],
                                           "diffs": {c: list(pair) for c, pair in entry["diffs"].items()}, "repeat": entry["repeat"], "source": source})
        tmp.commit()
    finally:
        tmp.close()
    return {kind: sum(1 for e in plan if e["kind"] == kind) for kind in ("added", "present", "changed")}


def _canon(value):
    if blank(value):
        return ""
    try:
        return repr(round(float(value), 9))
    except (TypeError, ValueError):
        return str(value).strip()


def _same(a, b):
    return _canon(a) == _canon(b)


def stage_conversion(config):
    """Converts the raw database in memory and compares the result with the work database; fills the tempdb."""
    result = build_logbook(config, sync_schema=False)
    names, built = result["names"], result["built"]
    conn = logbook_connect()
    try:
        work = [dict(r) for r in conn.execute("SELECT * FROM logbook ORDER BY technical_work_id")]
    finally:
        conn.close()
    by_raw = {w["technical_raw_id"]: w for w in work if w.get("technical_raw_id") is not None}
    legacy = {}                                   # work rows not linked to a raw row yet (before 0.4.2): paired when identical
    for w in work:
        if w.get("technical_raw_id") is None:
            legacy.setdefault(tuple(_canon(w.get(n)) for n in names), []).append(w)
    paired = set()
    tmp = _new_temp("convert", {"messages": result["messages"], "names": names, "created": journal.now()})
    try:
        for source, out in built:
            w = by_raw.get(source["id"])
            if w is None:
                candidates = legacy.get(tuple(_canon(out.get(n)) for n in names)) or []
                w = candidates.pop(0) if candidates else None
            built_values = {n: out.get(n) for n in names}
            if w is None:
                _add_item(tmp, "added", {"built": built_values, "raw_id": source["id"], "source": source["import_source"]})
                continue
            paired.add(w["technical_work_id"])
            diffs = {n: [w.get(n), built_values[n]] for n in names if not _same(w.get(n), built_values[n])}
            _add_item(tmp, "changed" if diffs else "present",
                      {"built": built_values, "work": {n: w.get(n) for n in names}, "diffs": diffs, "raw_id": source["id"],
                       "work_id": w["technical_work_id"], "source": w.get("technical_import_source"), "created_at": w.get("technical_import_date"), "updated_at": w.get("technical_modification_date")})
        for w in work:
            if w["technical_work_id"] not in paired:
                _add_item(tmp, "only_work", {"work": {n: w.get(n) for n in names}, "work_id": w["technical_work_id"], "raw_id": w.get("technical_raw_id"),
                                             "source": w.get("technical_import_source"), "created_at": w.get("technical_import_date"), "updated_at": w.get("technical_modification_date")})
        tmp.commit()
    finally:
        tmp.close()


# ---------------- display helpers ----------------

def _summary(rec):
    duration = hours(rec)
    dep, arr = rec.get("location_departure_code") or "", rec.get("location_arrival_code") or ""
    return {"date": row_date(rec) or "", "type": rec.get("aircraft_type") or "", "reg": rec.get("aircraft_registration") or "",
            "route": f"{dep} → {arr}" if dep or arr else "", "hours": f"{duration:.2f}" if duration else "",
            "remarks": rec.get("misc_remarks") or ""}


def _labels(view):
    return {v["column"]: v["label"] for v in view}


def _text(value):
    return "" if value is None else str(value)


IMPORT_CHOICES = ("ignore", "file", "add")


def _import_default(item):
    """Pre-selected choice of a line of the file: add when it is not the first line matching a database flight,
    otherwise take the file when it only completes empty fields, otherwise ignore."""
    if item.get("repeat"):
        return "add"
    if item["section"] == "changed" and not item["diffs"]:
        return "file"
    return "ignore"


def _import_choice(item):
    value = request.form.get(f"choice_{item['id']}")
    return value if value in IMPORT_CHOICES else _import_default(item)


def _back_to_data():
    return redirect(url_for("hubs.data"))


# ---------------- import review ----------------

@review_bp.route("/import")
@login_required
def import_review():
    stage = _read_temp("import")
    if stage is None:
        flash("No import is waiting for review.")
        return _back_to_data()
    info, items = stage
    labels = _labels(load_data_view(load_config(), existing_only=False))
    sections = {"added": [], "present": [], "changed": []}
    for it in items:
        row = {"id": it["id"], "summary": _summary(it["rec"]), "source": it["source"], "repeat": it.get("repeat", False)}
        if it["section"] != "added":
            row["default"] = _import_default(it)
        if it["section"] == "changed":
            row["fills"] = [{"label": labels.get(c, c), "new": _text(v)} for c, v in it["fills"].items()]
            row["diffs"] = [{"label": labels.get(c, c), "old": _text(p[0]), "new": _text(p[1])} for c, p in it["diffs"].items()]
        sections[it["section"]].append(row)
    return render_template("import_review.html", info=info, sections=sections)


@review_bp.route("/import/apply", methods=["POST"])
@login_required
def import_apply():
    stage = _read_temp("import")
    if stage is None:
        flash("No import is waiting for review.")
        return _back_to_data()
    info, items = stage
    try:
        config = load_config()
        cols = [safe_identifier(c["column"]) for c in configurable_columns(config)]
        quoted = ",".join(chr(34) + c + chr(34) for c in cols)
        conn = connect()
        inserted, updated, kept, present, chosen = [], 0, 0, 0, 0
        try:
            ensure_profile_column(conn)
            sync_user_columns(conn, config)
            for it in items:
                choice = _import_choice(it)
                if it["section"] == "added" or choice == "add":
                    if cols:
                        cursor = conn.execute(f'INSERT INTO users (technical_import_source,technical_import_profile,{quoted}) VALUES (?,?,{",".join("?" for _ in cols)})',
                                              [it["source"], info["profile"] or "default"] + [it["rec"].get(c) for c in cols])
                        inserted.append(cursor.lastrowid)
                        chosen += it["section"] != "added"
                elif it["section"] == "changed" and choice == "file":
                    changes = {**it["fills"], **{c: pair[1] for c, pair in it["diffs"].items()}}
                    sets = ",".join(f'"{safe_identifier(c)}"=?' for c in changes)
                    conn.execute(f"UPDATE users SET {sets}, technical_modification_date=CURRENT_TIMESTAMP WHERE technical_raw_id=?", list(changes.values()) + [it["match_id"]])
                    updated += 1
                elif it["section"] == "changed":
                    kept += 1
                else:
                    present += 1
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        summary = {"added": len(inserted), "added_by_choice": chosen, "file_kept": updated, "database_kept": kept, "present": present, "profile": info["profile_name"]}
        journal.record_import(", ".join(info["files"]), summary, inserted)
        log_event("data_import", target=f"{len(info['files'])} file(s), {len(inserted)} row(s) added")
        drop_temp()
        flash(f"Import validated: {len(inserted)} flight(s) added ({chosen} of them chosen among the similar lines), {updated} line(s) replaced by the file, {kept} kept as in the database, {present} ignored (already present).")
    except Exception as exc:
        flash(f"Import impossible — {safe_message(exc)}")
        return redirect(url_for("review.import_review"))
    return _back_to_data()


# ---------------- conversion review ----------------

def _convert_view_columns():
    return load_logbook_view(existing_only=False)[:8]


@review_bp.route("/convert")
@login_required
def convert_review():
    stage = _read_temp("convert")
    if stage is None:
        flash("No conversion is waiting for review.")
        return _back_to_data()
    info, items = stage
    view = _convert_view_columns()
    labels = _labels(load_logbook_view(existing_only=False))
    sections = {"added": [], "present": [], "changed": [], "only_work": []}
    for it in items:
        values = it.get("work") or it.get("built") or {}
        row = {"id": it["id"], "cells": [_text(values.get(v["column"])) for v in view]}
        if it["section"] == "changed":
            row["diffs"] = [{"label": labels.get(c, c), "old": _text(p[0]), "new": _text(p[1])} for c, p in it["diffs"].items()]
        sections[it["section"]].append(row)
    return render_template("convert_review.html", info=info, sections=sections, headers=[v["label"] for v in view])


@review_bp.route("/convert/apply", methods=["POST"])
@login_required
def convert_apply():
    stage = _read_temp("convert")
    if stage is None:
        flash("No conversion is waiting for review.")
        return _back_to_data()
    info, items = stage
    names = info["names"]
    now = journal.now()
    final, counts = [], {"added": 0, "present": 0, "rebuilt": 0, "work_kept": 0, "only_work_kept": 0, "only_work_deleted": 0}
    for it in items:
        section = it["section"]
        if section == "added":
            final.append({"values": it["built"], "raw_id": it["raw_id"], "source": it["source"], "created_at": now, "updated_at": now, "order": it["raw_id"]})
            counts["added"] += 1
        elif section == "present":
            final.append({"values": it["work"], "raw_id": it["raw_id"], "source": it["source"], "created_at": it["created_at"], "updated_at": it["updated_at"], "order": it["raw_id"]})
            counts["present"] += 1
        elif section == "changed":
            if request.form.get(f"choice_{it['id']}", "work") == "built":
                final.append({"values": it["built"], "raw_id": it["raw_id"], "source": it["source"], "created_at": it["created_at"], "updated_at": now, "order": it["raw_id"]})
                counts["rebuilt"] += 1
            else:
                final.append({"values": it["work"], "raw_id": it["raw_id"], "source": it["source"], "created_at": it["created_at"], "updated_at": it["updated_at"], "order": it["raw_id"]})
                counts["work_kept"] += 1
        else:
            if request.form.get(f"choice_{it['id']}", "keep") == "delete":
                counts["only_work_deleted"] += 1
            else:
                final.append({"values": it["work"], "raw_id": it["raw_id"], "source": it["source"], "created_at": it["created_at"], "updated_at": it["updated_at"], "order": 10 ** 12 + it["work_id"]})
                counts["only_work_kept"] += 1

    def key(row):
        v = row["values"]
        return (v.get("year") is None, v.get("year") or 0, v.get("month") or 0, v.get("day") or 0, row["order"])

    final.sort(key=key)
    snapshot = None
    try:
        snapshot = journal.snapshot_work_db()
        conn = logbook_connect()
        try:
            sync_logbook_columns(conn, None)
            drop_unused_logbook_columns(conn, None)
            conn.commit()
            conn.execute("DELETE FROM logbook")
            if names:
                for row in final:
                    insert_work_row(conn, names, row["values"], row["source"], row["raw_id"], row["created_at"], row["updated_at"])
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        journal.record_conversion(counts, snapshot)
        log_event("data_convert", target=f"{len(final)} row(s)")
        drop_temp()
        flash(f"Conversion validated: {len(final)} row(s) in the work data ({counts['added']} added, {counts['rebuilt']} rebuilt, "
              f"{counts['work_kept']} kept as they were, {counts['only_work_kept']} work-only kept, {counts['only_work_deleted']} work-only deleted).")
        for message in info.get("messages", []):
            flash(f"Warning — {message}")
    except Exception as exc:
        if snapshot:
            journal._remove_snapshot(snapshot)
        flash(f"Conversion impossible — {safe_message(exc)}")
        return redirect(url_for("review.convert_review"))
    return _back_to_data()


@review_bp.route("/cancel", methods=["POST"])
@login_required
def cancel():
    drop_temp()
    flash("Review cancelled: nothing was changed.")
    return _back_to_data()


# ---------------- journal ----------------

@review_bp.route("/journal")
@login_required
def journal_page():
    return redirect(url_for("review.journal_import_page"))


@review_bp.route("/journal/import")
@login_required
def journal_import_page():
    return render_template("journal_import.html", imports=journal.list_entries("import"), limits=journal.limits())


@review_bp.route("/journal/convert")
@login_required
def journal_convert_page():
    return render_template("journal_convert.html", conversions=journal.list_entries("convert"), limits=journal.limits())


@review_bp.route("/journal/<int:entry_id>/undo-import", methods=["POST"])
@login_required
def journal_undo_import(entry_id):
    try:
        removed = journal.undo_import(entry_id)
        log_event("data_destroy", target=f"raw-data:undo-import-{removed}-rows")
        flash(f"Import cancelled: {removed} row(s) removed from the raw data.")
    except Exception as exc:
        flash(f"Cancel impossible — {safe_message(exc)}")
    return redirect(url_for("review.journal_import_page"))


@review_bp.route("/journal/<int:entry_id>/undo-convert", methods=["POST"])
@login_required
def journal_undo_convert(entry_id):
    try:
        journal.undo_conversion(entry_id)
        log_event("data_destroy", target="work-data:undo-conversion")
        flash("Conversion cancelled: the work data is back to its state before that conversion.")
    except Exception as exc:
        flash(f"Cancel impossible — {safe_message(exc)}")
    return redirect(url_for("review.journal_convert_page"))
