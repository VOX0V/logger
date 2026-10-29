"""Monthly flight report (PDF) for a chosen month, year and aircraft type (or all types), built from the logbook database.
Adapted from generer_reports.py of the earlier Excel-based application."""
import io
import re
import sqlite3
from collections import defaultdict
from datetime import date
from xml.sax.saxutils import escape

from flask import Blueprint, Response, flash, g, redirect, render_template, request, url_for
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Table, TableStyle

from .auth import login_required
from .db import logbook_connect

reports_bp = Blueprint("reports", __name__, url_prefix="/reports")

MOIS_FR = {1: "JAN", 2: "FEV", 3: "MAR", 4: "AVR", 5: "MAI", 6: "JUN",
           7: "JUL", 8: "AOU", 9: "SEP", 10: "OCT", 11: "NOV", 12: "DEC"}
ME_DAY = ["multi_engine_dual_day", "multi_engine_pic_day", "multi_engine_copi_day"]
ME_NIGHT = ["multi_engine_dual_night", "multi_engine_pic_night", "multi_engine_copi_night"]

BLACK, GREY, GREY_LT, GREY_BG, WHITE = (colors.black, colors.HexColor("#666666"), colors.HexColor("#CCCCCC"),
                                        colors.HexColor("#F0F0F0"), colors.white)
BLUE_NIGHT, BLUE_NIGHT_ALT = colors.HexColor("#D6E8F7"), colors.HexColor("#C2DCEF")


def ps(name, bold=False, **kw):
    d = dict(fontName="Helvetica-Bold" if bold else "Helvetica", fontSize=7.5, textColor=BLACK, leading=10)
    d.update(kw)
    return ParagraphStyle(name, **d)


S_TITLE = ps("title", True, fontSize=9, spaceAfter=5)
S_HDR, S_HDR_L = ps("hdr", True, alignment=TA_CENTER), ps("hdr_l", True, alignment=TA_LEFT)
S_C, S_L, S_R = ps("c", alignment=TA_CENTER), ps("l", alignment=TA_LEFT), ps("r", alignment=TA_RIGHT)
S_CB, S_LB, S_RB = ps("cb", True, alignment=TA_CENTER), ps("lb", True, alignment=TA_LEFT), ps("rb", True, alignment=TA_RIGHT)


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def text(v):
    return "" if v is None else str(v).strip()


MOIS_LONG = {1: "January", 2: "February", 3: "March", 4: "April", 5: "May", 6: "June", 7: "July", 8: "August",
             9: "September", 10: "October", 11: "November", 12: "December"}
DAY_COLS = ["single_engine_dual_day", "single_engine_pic_day"] + ME_DAY
NIGHT_COLS = ["single_engine_dual_night", "single_engine_pic_night"] + ME_NIGHT


def clean(v):
    return re.sub(r"\s+", " ", text(v))


def fmt_block(val):
    return f"{val:.1f}" if val else "0.0"


def filename_for(year, month, type_code=""):
    base = f"{month:02d}{MOIS_FR.get(month, f'{month:02d}')}{str(year)[2:]}"
    return f"{base}-{re.sub(r'[^A-Za-z0-9_-]', '', type_code) or 'ALL'}.pdf"


def collect_flights(rows, type_code="", today=None):
    """Flights of the logbook grouped by (year, month), for one aircraft type (type_code) or all types ("").
    Future dates and lines without flight time are left out."""
    today, type_code = today or date.today(), type_code.strip().upper()
    by_month = defaultdict(list)
    for r in rows:
        if type_code and text(r.get("aircraft_type")).upper() != type_code:
            continue
        try:
            d = date.fromisoformat(text(r.get("date"))[:10])
        except ValueError:
            continue
        if d > today:
            continue
        day, night = sum(num(r.get(c)) for c in DAY_COLS), sum(num(r.get(c)) for c in NIGHT_COLS)
        block = day + night
        if block <= 0:
            continue
        dn = "N" if night > 0 and (day == 0 or night >= day) else "D"
        landings = int(num(r.get("landings_day")) + num(r.get("landings_night"))) or 1     # a flight has at least one landing
        by_month[(d.year, d.month)].append({
            "remark": clean(r.get("remarks")), "date": f"{d.day:02d}/{d.month:02d}/{str(d.year)[2:]}",
            "sort": (d, r.get("id") or 0), "org": text(r.get("departure")), "des": text(r.get("arrival")),
            "block": block, "lndg": landings, "dn": dn, "pilot": text(r.get("pilot_in_command")),
            "copi": text(r.get("copilot"))})
    return by_month


def totals(by_month, year, month):
    """Cumulative totals: since the start of the year, and to date (since the first flight)."""
    ytd, to_date = ({"block": 0.0, "lndg": 0, "flights": 0} for _ in range(2))
    for (a, m), vols in by_month.items():
        if (a, m) > (year, month):
            continue
        for acc in ([ytd, to_date] if a == year else [to_date]):
            acc["block"] += sum(v["block"] for v in vols)
            acc["lndg"] += sum(v["lndg"] for v in vols)
            acc["flights"] += len(vols)
    return ytd, to_date


def title_text(year, month, type_label, profile):
    name = ", ".join(p.upper() for p in (profile.get("pilot_name"), profile.get("first_name")) if p)
    extra = "   ".join(x for x in (profile.get("employee_number"), name) if x)
    return f"Flight Log Report — {MOIS_FR.get(month, month)}{str(year)[2:]} — {type_label}" + (f"     {extra}" if extra else "")


def build_monthly_pdf(year, month, type_label, vols, ytd, to_date, profile):
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=1.5 * cm, rightMargin=1.5 * cm,
                            topMargin=1.2 * cm, bottomMargin=1.2 * cm)
    CW = [1.6 * cm, 4.0 * cm, 1.4 * cm, 1.4 * cm, 1.3 * cm, 1.0 * cm, 0.9 * cm, 3.2 * cm, 3.2 * cm]
    story = [Paragraph(escape(title_text(year, month, type_label, profile)).replace("   ", "&nbsp;&nbsp;&nbsp;"), S_TITLE)]
    left = ("FLIGHT/REMARK", "PIC", "COPI")
    data = [[Paragraph(h, S_HDR_L if h in left else S_HDR)
             for h in ("DATE", "FLIGHT/REMARK", "ORG", "DEST", "TIME", "LDG", "D/N", "PIC", "COPI")]]
    row_meta, total_block, total_lndg = [], 0.0, 0
    for i, v in enumerate(sorted(vols, key=lambda x: x["sort"]), 1):
        total_block += v["block"]
        total_lndg += v["lndg"]
        data.append([Paragraph(v["date"], S_C), Paragraph(escape(v["remark"]), S_L), Paragraph(escape(v["org"]), S_C),
                     Paragraph(escape(v["des"]), S_C), Paragraph(fmt_block(v["block"]), S_R),
                     Paragraph(str(v["lndg"]), S_C), Paragraph(v["dn"], S_C),
                     Paragraph(escape(v["pilot"]), S_L), Paragraph(escape(v["copi"]), S_L)])
        row_meta.append((v["dn"] == "N", i))

    def total_row(label, block, lndg, count):
        return [Paragraph("", S_C)] * 3 + [Paragraph(label, ps("t" + label, True, alignment=TA_RIGHT)),
                                          Paragraph(fmt_block(block), S_RB), Paragraph(str(lndg), S_CB),
                                          Paragraph("", S_C), Paragraph(f"{count} flight(s)", S_LB), Paragraph("", S_C)]

    data.append(total_row("TOTAL", total_block, total_lndg, len(vols)))
    data.append(total_row(f"Total {year}", ytd["block"], ytd["lndg"], ytd["flights"]))
    data.append(total_row("Total to date", to_date["block"], to_date["lndg"], to_date["flights"]))
    style = [("BACKGROUND", (0, 0), (-1, 0), GREY_BG), ("LINEBELOW", (0, 0), (-1, 0), 1.2, BLACK),
             ("LINEABOVE", (0, -3), (-1, -3), 1.2, BLACK), ("INNERGRID", (0, 0), (-1, -1), 0.3, GREY_LT),
             ("BOX", (0, 0), (-1, -1), 0.5, GREY), ("TOPPADDING", (0, 0), (-1, -1), 2),
             ("BOTTOMPADDING", (0, 0), (-1, -1), 2), ("LEFTPADDING", (0, 0), (-1, -1), 4),
             ("RIGHTPADDING", (0, 0), (-1, -1), 4), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]
    for idx, (is_night, num_vol) in enumerate(row_meta):
        bg = (BLUE_NIGHT_ALT if idx % 2 == 0 else BLUE_NIGHT) if is_night else (GREY_BG if idx % 2 == 0 else WHITE)
        style.append(("BACKGROUND", (0, idx + 1), (-1, idx + 1), bg))
        if num_vol % 10 == 0:
            style.append(("LINEBELOW", (0, idx + 1), (-1, idx + 1), 0.8, GREY))
    tbl = Table(data, colWidths=CW, repeatRows=1)
    tbl.setStyle(TableStyle(style))
    story.append(tbl)
    doc.build(story)
    return buf.getvalue()


def _load_rows():
    try:
        conn = logbook_connect()
        conn.row_factory = sqlite3.Row
        rows = [dict(r) for r in conn.execute("SELECT * FROM logbook ORDER BY id")]
        conn.close()
    except sqlite3.Error:
        rows = []
    return rows


def _profile():
    from .converter import catalog
    return catalog.load_profile(g.username)


def _int_arg(name, default=None):
    try:
        return int(request.args.get(name, ""))
    except ValueError:
        return default


@reports_bp.route("/")
@login_required
def index():
    from .refdata import list_aircraft_types
    rows = _load_rows()
    by_month = collect_flights(rows)
    types = {text(t["code"]).upper(): text(t["code"]) for t in list_aircraft_types()}
    types.update({text(r.get("aircraft_type")).upper(): text(r.get("aircraft_type")).upper() for r in rows if text(r.get("aircraft_type"))})
    latest = max(by_month) if by_month else (date.today().year, date.today().month)
    return render_template("reports.html", years=sorted({a for a, _ in by_month}, reverse=True),
                           months=list(MOIS_LONG.items()), types=[types[k] for k in sorted(types)],
                           sel_year=_int_arg("year", latest[0]), sel_month=_int_arg("month", latest[1]),
                           sel_type=request.args.get("type", "all").strip().upper() or "ALL", total=sum(len(v) for v in by_month.values()))


@reports_bp.route("/pdf")
@login_required
def pdf():
    year, month = _int_arg("year"), _int_arg("month")
    if not year or month not in MOIS_LONG:
        flash("Choose a month and a year.")
        return redirect(url_for("reports.index"))
    raw_type = request.args.get("type", "all").strip()
    type_code = "" if raw_type.lower() == "all" else raw_type.upper()
    by_month = collect_flights(_load_rows(), type_code)
    vols = by_month.get((year, month))
    if not vols:
        flash(f"No flights in {MOIS_LONG[month]} {year} for {type_code or 'all types'}.")
        return redirect(url_for("reports.index", year=year, month=month, type=raw_type or "all"))
    ytd, to_date = totals(by_month, year, month)
    out = build_monthly_pdf(year, month, type_code or "ALL TYPES", vols, ytd, to_date, _profile())
    return Response(out, mimetype="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{filename_for(year, month, type_code)}"'})
