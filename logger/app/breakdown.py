"""“Flight time breakdown” (RAC 401.08 — Personal Logs): hours per aircraft type, built from the logbook database.
Layout taken from the 'Report EN' sheet of the earlier Excel logbook (English only for now).
Page size, column widths and heights come from the user's breakdown.yml, in u (1 u = 0,01 po), like the logbook layout."""
import io
import re
import sqlite3
from datetime import date

from flask import Blueprint, Response, flash, g, redirect, render_template, request, url_for
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfgen import canvas
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import Paragraph, Table, TableStyle

from . import cssafe
from .auth import login_required
from .config import load_breakdown, load_logbook_layout, save_breakdown
from .db import logbook_connect
from .errors import safe_message
from .seclog import log_event

breakdown_bp = Blueprint("breakdown", __name__, url_prefix="/breakdown")
U = 0.72                                   # 1 u en points (1 u = 0,01 po)

# (section, day/night group — "" if none, label, logbook column). Same order as the Excel report.
COLS = (
    [("SINGLE-ENGINE", g, l, f"single_engine_{k}_{d}") for g, d in (("Day", "day"), ("Night", "night"))
     for l, k in (("Dual", "dual"), ("PIC", "pic"))]
    + [("MULTI-ENGINE", g, l, f"multi_engine_{k}_{d}") for g, d in (("Day", "day"), ("Night", "night"))
       for l, k in (("Dual", "dual"), ("PIC", "pic"), ("Co-Pilot", "copi"))]
    + [("INSTRUMENTS", "", "IFR", "ifr"), ("INSTRUMENTS", "", "Hood", "hood"), ("INSTRUMENTS", "", "FTD", "ftd"),
       ("INSTRUMENTS", "", "IFR app", "ifr_approach")]
    + [("CROSS-COUNTRY", g, l, f"cross_country_{k}_{d}") for g, d in (("Day", "day"), ("Night", "night"))
       for l, k in (("Dual", "dual"), ("PIC", "pic"))]
    + [("INSTRUCTION", "", "Day", "instruction_day"), ("INSTRUCTION", "", "Night", "instruction_night")]
)
SECTIONS = list(dict.fromkeys(c[0] for c in COLS))
AIRCRAFT_COLS = [c[3] for c in COLS if c[0] in ("SINGLE-ENGINE", "MULTI-ENGINE")]   # TOTAL = single + multi engine hours
CATEGORY_ORDER = {"helicopter": 0, "airplane": 1, "simulator": 2}
TURBINE_TYPES = {"turbine", "turbofan", "turboprop"}

TITLE = "FLIGHT TIME BREAKDOWN"
RAC_TITLE = "RAC 401.08 - Personal Logs"
RAC_TEXT = [
    "(1) Every applicant for, and every holder of, a flight crew permit, licence or rating shall maintain a personal log "
    "in accordance with subsection (2) and with the personnel licensing standards for the documentation of :",
    "a) experience acquired in respect of the issuance of the flight crew permit, licence or rating; and",
    "b) recency.",
    "(2) A personal log that is maintained for the purposes referred to in paragraphs (1)(a) and (b) shall contain the "
    "holder’s name and the following information in respect of each flight:",
    "a) the date of the flight;", "b) the type of aircraft and its registration mark;",
    "c) the flight crew position in which the holder acted;",
    "d) the flight conditions with respect to day, night, VFR and IFR;",
    "e) in the case of a flight in an aeroplane or helicopter, the place of departure and the place of arrival;",
    "f) in the case of a flight in an aeroplane, all of the intermediate take-offs and landings;",
    "g) the flight time;", "h) in the case of a flight in a glider, the method of launch used for the flight; and",
    "i) in the case of a flight in a balloon, the method of inflation used for the flight.",
    "(3) No person shall make an entry in a personal log unless the person :",
    "a) is the holder of the log; or", "b) has been authorized to make the entry by the holder of the log.",
]
CERTIFY = "I hereby certify that the information contained in this report is accurate."


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def fmt(v):
    return f"{v:.1f}".replace(".", ",")


def dmy(iso):
    return f"{iso[8:10]}/{iso[5:7]}/{iso[:4]}" if len(iso) >= 10 else iso


def spaced(n):
    return f"{n:,}".replace(",", " ")


def build_report(rows, types, profile, email, quals, selected, today=None):
    """rows: logbook rows; types: aircraft_types rows (dicts); quals: [{name, expiry, days}]; selected: type code per table line."""
    today = today or date.today()
    zeros = lambda: dict.fromkeys((c[3] for c in COLS), 0.0)
    by_type, dates = {}, []
    for r in rows:
        try:
            d = date.fromisoformat(str(r.get("date") or "")[:10])
        except ValueError:
            continue
        if d > today:                      # same rule as the monthly reports: planned flights are left out
            continue
        code = str(r.get("aircraft_type") or "").strip().upper()
        if not code:
            continue
        dates.append(d)
        acc = by_type.setdefault(code, zeros())
        for c in COLS:
            acc[c[3]] += num(r.get(c[3]))
    known = {t["code"].upper(): t for t in types}
    lines, tot, seen = [], zeros(), set()
    cat = {"airplane": 0.0, "helicopter": 0.0, "turbine": 0.0}
    for code in selected:
        code = (code or "").strip().upper()
        counted = bool(code) and code not in seen          # a type chosen twice is only counted once
        seen.add(code)
        vals = by_type.get(code, zeros()) if counted else zeros()
        total = sum(vals[k] for k in AIRCRAFT_COLS)
        for k, v in vals.items():
            tot[k] += v
        t = known.get(code) or {}
        if t.get("category") in ("airplane", "helicopter"):
            cat[t["category"]] += total
        if t.get("category") != "simulator" and t.get("engine_type") in TURBINE_TYPES:
            cat["turbine"] += total
        lines.append({"code": code, "total": total, "cells": [vals[c[3]] for c in COLS]})
    unassigned = sorted((c, sum(v.values())) for c, v in by_type.items() if c not in seen and any(v.values()))
    return {"lines": lines, "total": sum(tot[k] for k in AIRCRAFT_COLS), "cells_total": [tot[c[3]] for c in COLS],
            "section_totals": [sum(tot[c[3]] for c in COLS if c[0] == s) for s in SECTIONS], "cat": cat,
            "unassigned": unassigned, "name": " ".join(x for x in (profile.get("first_name"), profile.get("pilot_name")) if x),
            "license": profile.get("license_number", ""), "phone": profile.get("phone", ""), "email": email or "",
            "quals": quals, "date": today.isoformat(), "period": (min(dates).isoformat(), max(dates).isoformat()) if dates else None}


def header_rows():
    """Three header rows (without the two left columns Type / TOTAL) as (text, colspan, rowspan) lists."""
    r1 = [(s, sum(1 for c in COLS if c[0] == s), 1) for s in SECTIONS]
    r2, r3 = [], []
    for c in COLS:
        if c[1]:
            if not r2 or r2[-1][3] != (c[0], c[1]):
                r2.append((c[1], sum(1 for x in COLS if x[:2] == c[:2]), 1, (c[0], c[1])))
            r3.append((c[2], 1, 1))
        else:
            r2.append((c[2], 1, 2, (c[0], "")))
    return r1, [x[:3] for x in r2], r3


def column_labels():
    return [("Type", "type"), ("TOTAL", "total")] + [(" ".join(x for x in (c[0].title(), c[1], c[2]) if x), c[3]) for c in COLS]


def row_colors(n, lb_styles):
    """Row background colours: the colour blocks of the logbook layout (same blocks, same alternation)."""
    blocks = [b for b in (lb_styles.get("data_blocks") or []) if isinstance(b, dict) and int(b.get("rows") or 0) > 0]
    alt, out = lb_styles.get("alternate_white", True), []
    while blocks and len(out) < n:
        for b in blocks:
            out += [b["color"] if (not alt or j % 2 == 0) else None for j in range(int(b["rows"]))]
    return out[:n] + [None] * max(0, n - len(out))


def geometry(cfg):
    """Checks that the layout fits the page and returns the positions (in u, from the top of the page)."""
    m, W, H = cfg["margin_u"], cfg["page_width_u"], cfg["page_height_u"]
    inner, widths = W - 2 * m, [c["width"] for c in cfg["columns"]]
    if abs(sum(widths) - inner) > 0.01:
        raise ValueError(f"Breakdown: the columns total {sum(widths):g} u instead of {inner:g} u (page_width_u - 2 x margin_u).")
    tw = cfg["top_widths_u"]
    if abs(tw["left"] + tw["middle"] + tw["right"] - inner) > 0.01:
        raise ValueError(f"Breakdown : top_widths_u totalise {tw['left'] + tw['middle'] + tw['right']:g} u instead of {inner:g} u.")
    n_table = 3 + len(cfg["rows"]) + 2
    y_top = m + cfg["title_height_u"] + cfg["rac_bar_height_u"] + cfg["gap_u"]
    y_table = y_top + cfg["top_height_u"] + cfg["gap_u"]
    bottom = y_table + n_table * cfg["row_height_u"] + m
    if bottom > H:
        raise ValueError(f"Breakdown: the layout requires {bottom:g} u of height for a page of {H:g} u "
                         "(reduce row_height_u, top_height_u or the number of rows).")
    return {"m": m, "W": W, "H": H, "inner": inner, "widths": widths, "tw": tw, "y_title": m,
            "y_rac": m + cfg["title_height_u"], "y_top": y_top, "y_table": y_table, "n_table": n_table}


# ---------------------------------------------------------------- PDF

def _border(styles):
    mo = re.match(r"^(\d{1,2})px (\w+) (#[0-9A-Fa-f]{3,8})$", str(styles.get("border", "")))
    return None if not mo or mo.group(2) == "none" else (0.5 * int(mo.group(1)), colors.HexColor(mo.group(3)))


def build_pdf(rep, cfg, geo, lb_styles):
    st, m = cfg["styles"], geo["m"]
    W, H = geo["W"] * U, geo["H"] * U
    X = lambda u: u * U
    Y = lambda u: H - u * U
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(W, H))
    c.setTitle(cfg.get("title") or TITLE)
    line = _border(st)
    c.setLineWidth(line[0] if line else 0.5)
    c.setStrokeColor(line[1] if line else colors.black)

    def box(x, y, w, h):
        c.rect(X(x), Y(y + h), X(w), X(h))

    def text(x, y, s, size=7.5, bold=False, align="l"):
        c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        {"l": c.drawString, "r": c.drawRightString, "c": c.drawCentredString}[align](X(x), Y(y), s)

    tw, tl, tm = geo["tw"], cfg["top_widths_u"]["left"], cfg["top_widths_u"]["middle"]
    top_h, y_top = cfg["top_height_u"], geo["y_top"]
    xl, xm, xr = m, m + tl, m + tl + tm
    # title + RAC bar
    t = (cfg.get("title") or TITLE).upper()
    size = cfg["title_font_size"]
    base = geo["y_title"] + cfg["title_height_u"] - 14
    text(W / U / 2, base, t, size, True, "c")
    half = stringWidth(t, "Helvetica-Bold", size) / U / 2
    c.line(X(W / U / 2 - half), Y(base - 3), X(W / U / 2 + half), Y(base - 3))
    box(m, geo["y_rac"], tl + tm, cfg["rac_bar_height_u"])
    text(m + (tl + tm) / 2, geo["y_rac"] + cfg["rac_bar_height_u"] - 4, RAC_TITLE, 8, True, "c")
    # left block: image area (empty for now), contact, totals
    box(xl, y_top, tl, top_h)
    yc = y_top + cfg["photo_height_u"]
    for i, (label, val) in enumerate((("Phone number :", rep["phone"]), ("Email address :", rep["email"]))):
        text(xl + tl * 0.40, yc + 16 + i * 14, label, 7.5, False, "r")
        text(xl + tl * 0.44, yc + 16 + i * 14, val, 7.5)
    ty = y_top + top_h - cfg["totals_height_u"]
    c.line(X(xl), Y(ty), X(xl + tl), Y(ty))
    cat = rep["cat"]
    for i, (label, val) in enumerate((("Airplane total:", cat["airplane"]), ("Helicopter total:", cat["helicopter"]),
                                      ("Jet engine / turboshaft total:", cat["turbine"]))):
        yy = ty + (i + 1) * cfg["totals_height_u"] / 4
        text(xl + tl * 0.66, yy, label, 7.5, True, "r")
        text(xl + tl * 0.69, yy, fmt(val), 7.5, True)
    # middle block: regulation text, font shrinks until it fits
    box(xm, y_top, tm, top_h)
    avail_w, avail_h = X(tm - 8), X(top_h - 6)
    size = 8.0
    while True:
        paras = [Paragraph(s.replace("&", "&amp;"), ParagraphStyle("r", fontName="Helvetica-Bold", fontSize=size, leading=size * 1.3,
                           spaceBefore=size * 0.9 if s[:3] in ("(2)", "(3)") else 0)) for s in RAC_TEXT]
        sizes = [p.wrap(avail_w, 10000)[1] + p.style.spaceBefore for p in paras]
        if sum(sizes) <= avail_h or size <= 4:
            break
        size -= 0.25
    cur = Y(y_top + 3)
    for p, h in zip(paras, sizes):
        cur -= h
        p.drawOn(c, X(xm + 4), cur)
    # right block: certification + qualifications
    cert = cfg["cert_height_u"]
    box(xr, y_top, tw["right"], cert)
    text(xr + tw["right"] / 2, y_top + 11, CERTIFY, 6.5, True, "c")
    for i, (label, val) in enumerate((("Name :", rep["name"]), ("License number :", rep["license"]), ("Date:", dmy(rep["date"])))):
        yy = y_top + 28 + i * 16
        text(xr + tw["right"] * 0.34, yy, label, 7.5, False, "r")
        text(xr + tw["right"] * 0.37, yy, val, 9, True)
    text(xr + tw["right"] * 0.34, y_top + cert - 8, "Signature:", 7.5, False, "r")
    n_q = len(rep["quals"])
    qrh = min(cfg["qual_row_height_u"], (top_h - cert - 4) / (n_q + 2))
    if qrh < 7:
        raise ValueError("Breakdown: too many qualifications for the top block (increase top_height_u or reduce cert_height_u).")
    q = [["Qualifications tracking", "", ""], ["Qualification", "Expiry date", "Days remaining"]]
    q += [[x["name"], dmy(x["expiry"]), spaced(x["days"])] for x in rep["quals"]]
    qt = Table(q, colWidths=[X(tw["right"]) * p for p in (0.42, 0.29, 0.29)], rowHeights=[X(qrh)] * len(q))
    qt.setStyle(TableStyle([("SPAN", (0, 0), (-1, 0)), ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 7),
                            ("ALIGN", (0, 0), (-1, -1), "CENTER"), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("BOX", (0, 0), (-1, -1), 0.5, colors.black),
                            ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.black), ("TOPPADDING", (0, 0), (-1, -1), 0),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
    qt.wrapOn(c, W, H)
    qt.drawOn(c, X(xr), Y(y_top + top_h))
    # matrix
    ncol = 2 + len(COLS)
    data = [[None] * ncol for _ in range(3)]
    spans = [("SPAN", (0, 0), (1, 1))]
    r1, r2, r3 = header_rows()
    for row, items in enumerate((r1, r2, r3)):
        col = 2
        for label, cs, rs in items:
            while data[row][col] is not None:
                col += 1
            data[row][col] = label
            for rr in range(row, row + rs):
                for cc in range(col, col + cs):
                    if (rr, cc) != (row, col):
                        data[rr][cc] = ""
            if cs > 1 or rs > 1:
                spans.append(("SPAN", (col, row), (col + cs - 1, row + rs - 1)))
            col += cs
    data[0][0], data[0][1], data[1][0], data[1][1], data[2][0], data[2][1] = "AIRCRAFT", "", "", "", "Type", "TOTAL"
    for ln in rep["lines"]:
        data.append([ln["code"], fmt(ln["total"])] + [fmt(v) for v in ln["cells"]])
    data.append(["TOTAL", fmt(rep["total"])] + [fmt(v) for v in rep["cells_total"]])
    sub = ["", ""]
    col = 2
    for s, v in zip(SECTIONS, rep["section_totals"]):
        n = sum(1 for x in COLS if x[0] == s)
        sub += [fmt(v)] + [""] * (n - 1)
        spans.append(("SPAN", (col, len(data)), (col + n - 1, len(data))))
        col += n
    data.append(sub)
    last, first = len(data) - 1, 3
    rh = cfg["row_height_u"] * U
    tbl = Table(data, colWidths=[w * U for w in geo["widths"]], rowHeights=[rh] * len(data))
    fs, hfs = st["font_size"] * 0.75, st["header_font_size"] * 0.75
    style = [("FONTNAME", (0, 0), (-1, -1), "Helvetica"), ("FONTSIZE", (0, 0), (-1, -1), fs), ("ALIGN", (0, 0), (-1, -1), st["text_align"].upper()),
             ("VALIGN", (0, 0), (-1, -1), st["vertical_align"].upper()), ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
             ("LEFTPADDING", (0, 0), (-1, -1), 1), ("RIGHTPADDING", (0, 0), (-1, -1), 1),
             ("FONTNAME", (0, 0), (-1, 2), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, 2), hfs),
             ("BACKGROUND", (0, 0), (-1, 2), colors.HexColor(st["header_background"])),
             ("FONTNAME", (0, first), (0, last), "Helvetica-Bold"), ("FONTNAME", (0, last - 1), (-1, last), "Helvetica-Bold"),
             ("BACKGROUND", (0, last - 1), (-1, last), colors.HexColor(st["total_background"])),
             ("FONTSIZE", (0, 0), (1, 0), hfs * 1.4)] + spans
    if line:
        style.append(("GRID", (0, 0), (-1, -1), line[0], line[1]))
    for i, color in enumerate(row_colors(len(rep["lines"]), lb_styles)):
        if color:
            style.append(("BACKGROUND", (0, first + i), (-1, first + i), colors.HexColor(color)))
        for j, v in enumerate(rep["lines"][i]["cells"] + [rep["lines"][i]["total"]]):
            if not v:
                style.append(("TEXTCOLOR", (j + 2 if j < len(COLS) else 1, first + i), (j + 2 if j < len(COLS) else 1, first + i),
                              colors.HexColor(st["zero_color"])))
    pos = 2
    for s in SECTIONS[:-1]:
        pos += sum(1 for x in COLS if x[0] == s)
        style.append(("LINEBEFORE", (pos, 0), (pos, last), 1.2, colors.black))
    tbl.setStyle(TableStyle(style))
    _, th = tbl.wrapOn(c, W, H)
    tbl.drawOn(c, X(m), Y(geo["y_table"]) - th)
    c.showPage()
    c.save()
    return buf.getvalue()


# ---------------------------------------------------------------- routes

def _quals():
    from .converter import catalog
    out = []
    for q in catalog.load_qualifications(g.username):
        try:
            out.append(dict(q, days=(date.fromisoformat(q["expiry"]) - date.today()).days))
        except ValueError:
            continue
    return out


def _context():
    from .converter import catalog
    from .refdata import list_aircraft_types
    cfg = load_breakdown()
    try:
        conn = logbook_connect()
        conn.row_factory = sqlite3.Row
        rows = [dict(r) for r in conn.execute("SELECT * FROM logbook ORDER BY id")]
        conn.close()
    except sqlite3.Error:
        rows = []
    try:
        email = g.user["email"]
    except (KeyError, IndexError, TypeError):
        email = ""
    types = [dict(t) for t in list_aircraft_types()]
    rep = build_report(rows, types, catalog.load_profile(g.username), email, _quals(), cfg["rows"])
    return cfg, rep, types


@breakdown_bp.route("/")
@login_required
def index():
    cfg, rep, types = _context()
    lb = load_logbook_layout()["styles"]
    try:
        geo, error = geometry(cfg), None
    except ValueError as exc:
        geo, error = None, str(exc)
    codes = [t["code"] for t in types]
    r1, r2, r3 = header_rows()
    return render_template("breakdown.html", cfg=cfg, geo=geo, error=error, rep=rep, codes=codes, headers=(r1, r2, r3),
                           colors=row_colors(len(rep["lines"]), lb), rac_title=RAC_TITLE, rac_text=RAC_TEXT, certify=CERTIFY,
                           title=cfg.get("title") or TITLE, sections=SECTIONS, cols=COLS, dmy=dmy, spaced=spaced, fmt=fmt)


@breakdown_bp.route("/rows", methods=["POST"])
@login_required
def save_rows():
    from .refdata import list_aircraft_types
    cfg = load_breakdown()
    allowed = {t["code"].upper(): t["code"] for t in list_aircraft_types()}
    chosen = [allowed.get(request.form.get(f"row_{i}", "").strip().upper(), "") for i in range(len(cfg["rows"]))]
    dup = sorted({c for c in chosen if c and chosen.count(c) > 1})
    if dup:
        flash("A type can only appear on one row: " + ", ".join(dup) + ". Nothing was saved.")
        return redirect(url_for("breakdown.index"))
    cfg["rows"] = chosen
    save_breakdown(cfg)
    log_event("config_change", target="breakdown:lignes")
    flash("Report types saved.")
    return redirect(url_for("breakdown.index"))


@breakdown_bp.route("/pdf")
@login_required
def pdf():
    cfg, rep, _types = _context()
    try:
        out = build_pdf(rep, cfg, geometry(cfg), load_logbook_layout()["styles"])
    except ValueError as exc:
        flash(str(exc))
        return redirect(url_for("breakdown.index"))
    return Response(out, mimetype="application/pdf", headers={
        "Content-Disposition": f'inline; filename="flight-time-breakdown-{date.today().isoformat()}.pdf"'})


@breakdown_bp.route("/settings")
@login_required
def settings():
    cfg = load_breakdown()
    return render_template("breakdown_settings.html", cfg=cfg, labels=dict((k, l) for l, k in column_labels()),
                           numbers=cssafe.BD_NUMBERS)


@breakdown_bp.route("/settings/save", methods=["POST"])
@login_required
def save_settings():
    cfg, f = load_breakdown(), request.form
    try:
        for key in cssafe.BD_NUMBERS:
            if key in f:
                cfg[key] = int(float(f[key]))
        for key in ("font_family", "border", "header_background", "total_background", "zero_color", "text_align", "vertical_align"):
            cfg["styles"][key] = f.get(key, cfg["styles"][key])
        for key in ("font_size", "header_font_size"):
            cfg["styles"][key] = int(float(f.get(key, cfg["styles"][key])))
        for k in ("left", "middle", "right"):
            cfg["top_widths_u"][k] = int(float(f.get("top_" + k, cfg["top_widths_u"][k])))
        for col in cfg["columns"]:
            col["width"] = int(float(f.get("width_" + col["key"], col["width"])))
        problems = cssafe.breakdown_problems(cfg)
        if problems:
            raise ValueError(" ".join(problems))
        geometry(cfg)
        save_breakdown(cfg)
        log_event("config_change", target="layout:breakdown")
        flash("Breakdown report configuration saved.")
    except Exception as exc:
        flash(f"Configuration impossible — {safe_message(exc)}")
    return redirect(url_for("breakdown.settings"))
