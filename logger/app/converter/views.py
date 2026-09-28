"""The "Convertisseur" tab: rule catalog (admins edit, everyone ticks their own
rules), converter settings, and the shared airport / aircraft reference data."""
from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from ..auth import login_required, admin_required
from ..config import load_config, load_logbook_db_config, configurable_columns
from ..refdata import (list_airports, get_airport, save_airport, delete_airport,
                       list_aircrafts, get_aircraft, save_aircraft, delete_aircraft, ENGINES)
from . import catalog
from .transforms import TRANSFORMS

converter_bp = Blueprint("converter", __name__, url_prefix="/converter")


def _user_columns():
    a = [c["column"] for c in configurable_columns(load_config())]
    b = [c["column"] for c in load_logbook_db_config()["database"]["columns"] if c.get("group") != "system"]
    return a, b


def _summary(rule):
    left = " + ".join(rule["inputs"].values())
    right = ", ".join(rule["outputs"].values())
    extra = ", ".join(f"{k}={v}" for k, v in rule["params"].items() if v not in ("any",))
    return f"{left} → {right}" + (f"  ({extra})" if extra else "")


@converter_bp.route("")
@login_required
def index():
    a, b = _user_columns()
    selected = set(catalog.load_selection())
    groups = {}
    for rule in catalog.load_rules():
        groups.setdefault(rule["group"], []).append({
            "rule": rule, "checked": rule["id"] in selected,
            "missing": catalog.rule_missing_columns(rule, a, b), "summary": _summary(rule),
            "label": TRANSFORMS.get(rule["transform"], {}).get("label", rule["transform"])})
    settings = catalog.load_settings()
    return render_template("converter.html", groups=groups, settings=settings,
                           rounding_text=catalog.rounding_to_text(settings["tc_rounding"]["rules"]))


@converter_bp.route("/select", methods=["POST"])
@login_required
def select():
    catalog.save_selection(request.form.getlist("enabled"))
    flash("Sélection des règles enregistrée. Clique sur Actualiser dans logbook.db pour l'appliquer.")
    return redirect(url_for("converter.index"))


@converter_bp.route("/settings", methods=["POST"])
@admin_required
def save_settings_route():
    try:
        after = int(request.form.get("after_sunset_minutes", ""))
        before = int(request.form.get("before_sunrise_minutes", ""))
        if not (0 <= after <= 180 and 0 <= before <= 180):
            raise ValueError("Les marges de nuit doivent être entre 0 et 180 minutes.")
        rules = catalog.rounding_from_text(request.form.get("tc_rounding", ""))
        current = catalog.load_settings()
        catalog.save_settings({"night": {"after_sunset_minutes": after, "before_sunrise_minutes": before},
                               "tc_rounding": {"comment": current["tc_rounding"].get("comment", ""), "rules": rules}})
        flash("Réglages du convertisseur enregistrés.")
    except ValueError as exc:
        flash(f"Réglages non enregistrés — {exc}")
    return redirect(url_for("converter.index"))


# ---------------- rules (admin) ----------------

def _rule_values(rule):
    values = {"name": rule["name"], "group": rule["group"], "default": "1" if rule["default"] else ""}
    values.update({f"in_{k}": v for k, v in rule["inputs"].items()})
    values.update({f"out_{k}": v for k, v in rule["outputs"].items()})
    values.update({f"param_{k}": v for k, v in rule["params"].items()})
    return values


def _render_rule_form(rule, transform, values, action):
    a, b = _user_columns()
    return render_template("rule_form.html", rule=rule, transform=transform, spec=TRANSFORMS[transform],
                           transforms=TRANSFORMS, values=values, a_columns=a, b_columns=b,
                           groups=sorted({r["group"] for r in catalog.load_rules()}), action=action)


@converter_bp.route("/rule/new", methods=["GET", "POST"])
@admin_required
def rule_new():
    transform = request.values.get("transform", "copy")
    if transform not in TRANSFORMS:
        transform = "copy"
    if request.method == "POST" and request.form.get("save") == "1":
        try:
            rules = catalog.load_rules()
            rule_id = catalog.rule_id_from_name(request.form.get("name", ""), {r["id"] for r in rules})
            rules.append(catalog.build_rule(request.form, transform, rule_id))
            catalog.save_rules(rules)
            flash("Règle ajoutée au catalogue.")
            return redirect(url_for("converter.index"))
        except ValueError as exc:
            flash(str(exc))
    return _render_rule_form(None, transform, request.form if request.method == "POST" else {}, url_for("converter.rule_new"))


@converter_bp.route("/rule/<rule_id>/edit", methods=["GET", "POST"])
@admin_required
def rule_edit(rule_id):
    rules = catalog.load_rules()
    rule = next((r for r in rules if r["id"] == rule_id), None)
    if not rule:
        flash("Règle introuvable."); return redirect(url_for("converter.index"))
    if request.method == "POST":
        try:
            updated = catalog.build_rule(request.form, rule["transform"], rule_id)
            catalog.save_rules([updated if r["id"] == rule_id else r for r in rules])
            flash("Règle modifiée.")
            return redirect(url_for("converter.index"))
        except ValueError as exc:
            flash(str(exc))
    return _render_rule_form(rule, rule["transform"], request.form if request.method == "POST" else _rule_values(rule),
                             url_for("converter.rule_edit", rule_id=rule_id))


@converter_bp.route("/rule/<rule_id>/delete", methods=["POST"])
@admin_required
def rule_delete(rule_id):
    rules = catalog.load_rules()
    catalog.save_rules([r for r in rules if r["id"] != rule_id])
    flash("Règle supprimée du catalogue (elle est aussi décochée chez tous les comptes).")
    return redirect(url_for("converter.index"))


# ---------------- airports (admin) ----------------

@converter_bp.route("/airports")
@admin_required
def airports():
    return render_template("airports.html", airports=list_airports())


@converter_bp.route("/airports/new", methods=["GET", "POST"])
@converter_bp.route("/airports/<int:airport_id>/edit", methods=["GET", "POST"])
@admin_required
def airport_form(airport_id=None):
    airport = get_airport(airport_id) if airport_id else None
    if airport_id and not airport:
        flash("Aéroport introuvable."); return redirect(url_for("converter.airports"))
    if request.method == "POST":
        try:
            save_airport(airport_id, request.form)
            flash("Aéroport enregistré.")
            return redirect(url_for("converter.airports"))
        except ValueError as exc:
            flash(str(exc))
    return render_template("airport_form.html", airport=airport, form=request.form if request.method == "POST" else None)


@converter_bp.route("/airports/<int:airport_id>/delete", methods=["POST"])
@admin_required
def airport_delete(airport_id):
    delete_airport(airport_id)
    flash("Aéroport supprimé.")
    return redirect(url_for("converter.airports"))


# ---------------- aircraft (admin) ----------------

@converter_bp.route("/aircrafts")
@admin_required
def aircrafts():
    return render_template("aircrafts.html", aircrafts=list_aircrafts())


@converter_bp.route("/aircrafts/new", methods=["GET", "POST"])
@converter_bp.route("/aircrafts/<int:aircraft_id>/edit", methods=["GET", "POST"])
@admin_required
def aircraft_form(aircraft_id=None):
    aircraft = get_aircraft(aircraft_id) if aircraft_id else None
    if aircraft_id and not aircraft:
        flash("Avion introuvable."); return redirect(url_for("converter.aircrafts"))
    if request.method == "POST":
        try:
            save_aircraft(aircraft_id, request.form)
            flash("Avion enregistré.")
            return redirect(url_for("converter.aircrafts"))
        except ValueError as exc:
            flash(str(exc))
    return render_template("aircraft_form.html", aircraft=aircraft, engines=ENGINES,
                           form=request.form if request.method == "POST" else None)


@converter_bp.route("/aircrafts/<int:aircraft_id>/delete", methods=["POST"])
@admin_required
def aircraft_delete(aircraft_id):
    delete_aircraft(aircraft_id)
    flash("Avion supprimé.")
    return redirect(url_for("converter.aircrafts"))
