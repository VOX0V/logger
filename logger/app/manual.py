"""Saisie manuelle d'un vol : la ligne est ajoutée aux données brutes (colonne import_source = “Saisie manuelle”).
Elle apparaît dans le Logbook après un clic sur “Actualiser” (données converties)."""
from datetime import date

from flask import Blueprint, flash, redirect, render_template, request, url_for

from . import models
from .auth import login_required
from .config import load_config
from .errors import safe_message
from .seclog import log_event

manual_bp = Blueprint("manual", __name__, url_prefix="/flight")
SOURCE = "Manual entry"
UPPER = ("type", "registration", "departure", "arrival")
GROUPS = [
    ("Flight", [("type", "Aircraft type"), ("registration", "Immatriculation"), ("pilot_in_command", "PIC (pilot)"),
             ("copilot", "Copilote"), ("departure", "Departure"), ("arrival", "Arrival"), ("remarks", "Remarques")]),
    ("Single-engine — day", [("single_engine_dual_day", "Dual"), ("single_engine_pic_day", "PIC")]),
    ("Single-engine — night", [("single_engine_dual_night", "Dual"), ("single_engine_pic_night", "PIC")]),
    ("Multi-engine — day", [("multi_engine_dual_day", "Dual"), ("multi_engine_pic_day", "PIC"), ("multi_engine_copi_day", "Co-Pilot")]),
    ("Multi-engine — night", [("multi_engine_dual_night", "Dual"), ("multi_engine_pic_night", "PIC"), ("multi_engine_copi_night", "Co-Pilot")]),
    ("Instruments", [("ifr", "IFR"), ("hood", "Hood"), ("ftd", "FTD"), ("ifr_approach", "IFR app")]),
    ("Cross-country — day", [("cross_country_dual_day", "Dual"), ("cross_country_pic_day", "PIC")]),
    ("Cross-country — night", [("cross_country_dual_night", "Dual"), ("cross_country_pic_night", "PIC")]),
    ("Instruction", [("instruction_day", "Day"), ("instruction_night", "Nuit")]),
    ("Atterrissages", [("landings_day", "Day"), ("landings_night", "Nuit")]),
]
TEXT_FIELDS = {c for c, _ in GROUPS[0][1]}
INT_FIELDS = {"landings_day", "landings_night"}
LABELS = {c: f"{title} — {label}" for title, fields in GROUPS for c, label in fields}


def _parse(form, present):
    try:
        d = date.fromisoformat(form.get("date", "").strip())
    except ValueError:
        raise ValueError("Enter a valid date.")
    row = {"year": d.year, "month": d.month, "day": d.day}
    for col in LABELS:
        value = form.get(col, "").strip()
        if not value or col not in present:
            continue
        if col in TEXT_FIELDS:
            row[col] = (value.upper() if col in UPPER else value)[:300 if col == "remarks" else 100]
        elif col in INT_FIELDS:
            try:
                n = int(value)
            except ValueError:
                raise ValueError(f"{LABELS[col]} : integer expected.")
            if not 0 <= n <= 99:
                raise ValueError(f"{LABELS[col]} : between 0 and 99.")
            row[col] = n
        else:
            try:
                h = float(value.replace(",", "."))
            except ValueError:
                raise ValueError(f"{LABELS[col]} : number expected (e.g. 1.5).")
            if not 0 <= h <= 24:
                raise ValueError(f"{LABELS[col]} : between 0 and 24 hours.")
            row[col] = round(h, 2)
    return row


def _insert(row, config):
    conn = models.connect()
    try:
        models.sync_user_columns(conn, config)
        names = [c for c in row if c in {x["column"] for x in models.configurable_columns(config)}]
        quoted = ",".join(chr(34) + models.safe_identifier(c) + chr(34) for c in names)
        conn.execute(f"INSERT INTO users (import_source,{quoted}) VALUES (?,{','.join('?' for _ in names)})",
                     [SOURCE] + [row[c] for c in names])
        conn.commit()
    finally:
        conn.close()


@manual_bp.route("/new", methods=["GET", "POST"])
@login_required
def new_flight():
    from .refdata import list_aircraft_types
    config = load_config()
    present = {c["column"] for c in models.configurable_columns(config)}
    groups = [(title, [(c, label) for c, label in fields if c in present]) for title, fields in GROUPS]
    values = request.form if request.method == "POST" else {}
    if request.method == "POST":
        try:
            _insert(_parse(request.form, present), config)
        except ValueError as exc:
            flash(str(exc))
        except Exception as exc:
            flash(f"Flight not added — {safe_message(exc)}")
        else:
            log_event("data_import", target="manual entry")
            flash("Flight added to the raw data (source “Manual entry”). Click Refresh in Work data to show it in the Logbook.")
            return redirect(url_for("main.index"))
    return render_template("flight_form.html", groups=[g for g in groups if g[1]], values=values,
                           types=[t["code"] for t in list_aircraft_types()], today=date.today().isoformat())
