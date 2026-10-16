"""Monthly PDF reports of the airline (CRJ) flights, built from the logbook database (B).
Adapted from generer_reports.py of the earlier Excel-based application."""
import io
import re
import sqlite3
import zipfile
from collections import defaultdict
from datetime import date
from xml.sax.saxutils import escape

from flask import Blueprint, Response, abort, g, render_template, url_for
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


def extract_flight_number(rem):
    m = re.search(r"\d+", text(rem))
    return m.group() if m else ""


def fmt_block(val):
    return f"{val:.1f}" if val else "0.0"


def filename_for(year, month):
    return f"{month:02d}{MOIS_FR.get(month, f'{month:02d}')}{str(year)[2:]}.pdf"


def collect_flights(rows, today=None):
    """CRJ flights of the logbook, grouped by (year, month). Future dates and lines without time are left out."""
    today = today or date.today()
    by_month = defaultdict(list)
    for r in rows:
        if text(r.get("aircraft_type")).upper() != "CRJ":
            continue
        try:
            d = date.fromisoformat(text(r.get("date"))[:10])
        except ValueError:
            continue
        if d > today:
            continue
        day, night = sum(num(r.get(c)) for c in ME_DAY), sum(num(r.get(c)) for c in ME_NIGHT)
        block = day + night
        if block <= 0:
            continue
        if night > 0 and day == 0:
            dn = "N"
        elif day > 0 and night == 0:
            dn = "D"
        else:
            dn = "N" if night >= day else "D"
        by_month[(d.year, d.month)].append({
            "flt": extract_flight_number(r.get("remarks")), "date": f"{d.day:02d}/{d.month:02d}/{str(d.year)[2:]}",
            "sort": (d, r.get("id") or 0), "org": text(r.get("departure")), "des": text(r.get("arrival")),
            "block": block, "lndg": 1, "dn": dn, "pilot": text(r.get("pilot_in_command"))})
    return by_month


def totals(by_month, year, month):
    """Cumulative totals: since the start of the year, and since the first CRJ flight."""
    ytd, jazz = ({"block": 0.0, "lndg": 0, "vols": 0} for _ in range(2))
    for (a, m), vols in by_month.items():
        if (a, m) > (year, month):
            continue
        for acc in ([ytd, jazz] if a == year else [jazz]):
            acc["block"] += sum(v["block"] for v in vols)
            acc["lndg"] += sum(v["lndg"] for v in vols)
            acc["vols"] += len(vols)
    return ytd, jazz


def title_text(year, month, profile):
    name = ", ".join(p.upper() for p in (profile.get("pilot_name"), profile.get("first_name")) if p)
    extra = "   ".join(x for x in (profile.get("employee_number"), "FO" if name else "", name) if x)
    return f"Flight Log Report — {MOIS_FR.get(month, month)}{str(year)[2:]}" + (f"     {extra}" if extra else "")


def build_monthly_pdf(year, month, vols, ytd, jazz, profile):
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=1.5 * cm, rightMargin=1.5 * cm,
                            topMargin=1.2 * cm, bottomMargin=1.2 * cm)
    CW = [1.6 * cm, 2.2 * cm, 1.6 * cm, 1.6 * cm, 1.8 * cm, 1.4 * cm, 1.2 * cm, 6.8 * cm]
    story = [Paragraph(escape(title_text(year, month, profile)).replace("   ", "&nbsp;&nbsp;&nbsp;"), S_TITLE)]
    data = [[Paragraph(h, S_HDR_L if h == "EMP NAME" else S_HDR)
             for h in ("FLT", "DATE", "ORG", "DES", "BLOCK", "LNDG", "D/N", "EMP NAME")]]
    row_meta, total_block, total_lndg = [], 0.0, 0
    for i, v in enumerate(sorted(vols, key=lambda x: x["sort"]), 1):
        total_block += v["block"]
        total_lndg += v["lndg"]
        data.append([Paragraph(escape(v["flt"]), S_C), Paragraph(v["date"], S_C), Paragraph(escape(v["org"]), S_C),
                     Paragraph(escape(v["des"]), S_C), Paragraph(fmt_block(v["block"]), S_R),
                     Paragraph(str(v["lndg"]) if v["lndg"] else "", S_C), Paragraph(v["dn"], S_C),
                     Paragraph(escape(v["pilot"]), S_L)])
        row_meta.append((v["dn"] == "N", i))

    def total_row(label, block, lndg, count):
        return [Paragraph("", S_C)] * 3 + [Paragraph(label, ps("t" + label, True, alignment=TA_RIGHT)),
                                          Paragraph(fmt_block(block), S_RB), Paragraph(str(lndg), S_CB),
                                          Paragraph("", S_C), Paragraph(f"{count} vol(s)", S_LB)]

    data.append(total_row("TOTAL", total_block, total_lndg, len(vols)))
    data.append(total_row(f"Total {year}", ytd["block"], ytd["lndg"], ytd["vols"]))
    data.append(total_row("Total Jazz", jazz["block"], jazz["lndg"], jazz["vols"]))
    style = [("BACKGROUND", (0, 0), (-1, 0), GREY_BG), ("LINEBELOW", (0, 0), (-1, 0), 1.2, BLACK),
             ("LINEABOVE", (0, -1), (-1, -1), 1.2, BLACK), ("INNERGRID", (0, 0), (-1, -1), 0.3, GREY_LT),
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


def _pdf(by_month, year, month, profile):
    ytd, jazz = totals(by_month, year, month)
    return build_monthly_pdf(year, month, by_month[(year, month)], ytd, jazz, profile)


@reports_bp.route("/")
@login_required
def index():
    by_month = collect_flights(_load_rows())
    years = defaultdict(list)
    for (a, m), vols in by_month.items():
        years[a].append({"label": f"{MOIS_FR[m]} {a}", "flights": len(vols), "block": sum(v["block"] for v in vols),
                         "url": url_for("reports.month_pdf", year=a, month=m)})
    groups = [(a, sorted(ms, key=lambda x: x["url"], reverse=True), url_for("reports.zip_reports", year=a))
              for a, ms in sorted(years.items(), reverse=True)]
    return render_template("reports.html", groups=groups, zip_all=url_for("reports.zip_reports"),
                           profile=_profile(), total=sum(len(v) for v in by_month.values()))


@reports_bp.route("/<int:year>/<int:month>")
@login_required
def month_pdf(year, month):
    by_month = collect_flights(_load_rows())
    if (year, month) not in by_month:
        abort(404)
    pdf = _pdf(by_month, year, month, _profile())
    return Response(pdf, mimetype="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{filename_for(year, month)}"'})


@reports_bp.route("/zip")
@reports_bp.route("/zip/<int:year>")
@login_required
def zip_reports(year=None):
    by_month = collect_flights(_load_rows())
    profile, buf = _profile(), io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for (a, m) in sorted(by_month):
            if year is None or a == year:
                z.writestr(f"{a}/{filename_for(a, m)}", _pdf(by_month, a, m, profile))
    return Response(buf.getvalue(), mimetype="application/zip", headers={
        "Content-Disposition": f'attachment; filename="reports {year if year else "CRJ"}.zip"'})
