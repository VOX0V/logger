"""« Flight time breakdown » (RAC 401.08 — Personal Logs): hours per aircraft type, built from the logbook database.
Layout taken from the 'Report EN' sheet of the earlier Excel logbook. English only for now (the FR report comes later)."""
import io
from datetime import date
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

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
    return f"{v:.1f}"


def build_report(rows, types, profile, email, quals, today=None):
    """rows: logbook rows (dicts); types: aircraft_types rows (dicts); quals: [{name, expiry, days}]."""
    today = today or date.today()
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
        acc = by_type.setdefault(code, dict.fromkeys((c[3] for c in COLS), 0.0))
        for c in COLS:
            acc[c[3]] += num(r.get(c[3]))
    known = {t["code"].upper(): t for t in types}
    order = sorted(known, key=lambda c: CATEGORY_ORDER.get(known[c]["category"], 3))
    order += sorted(c for c in by_type if c not in known)          # types used in the logbook but not in « Types d'appareils »
    lines, tot = [], dict.fromkeys((c[3] for c in COLS), 0.0)
    cat = {"airplane": 0.0, "helicopter": 0.0, "turbine": 0.0}
    for code in order:
        vals = by_type.get(code, dict.fromkeys((c[3] for c in COLS), 0.0))
        total = sum(vals[k] for k in AIRCRAFT_COLS)
        for k, v in vals.items():
            tot[k] += v
        t = known.get(code) or {}
        if t.get("category") in ("airplane", "helicopter"):
            cat[t["category"]] += total
        if t.get("category") != "simulator" and t.get("engine_type") in TURBINE_TYPES:
            cat["turbine"] += total
        lines.append({"code": code, "total": total, "cells": [vals[c[3]] for c in COLS]})
    section_totals = [sum(tot[c[3]] for c in COLS if c[0] == s) for s in SECTIONS]
    uncategorized = [c for c in order if not (known.get(c) or {}).get("category")]
    return {"lines": lines, "total": sum(tot[k] for k in AIRCRAFT_COLS), "cells_total": [tot[c[3]] for c in COLS],
            "section_totals": section_totals, "cat": cat, "uncategorized": uncategorized,
            "name": " ".join(x for x in (profile.get("first_name"), profile.get("pilot_name")) if x),
            "license": profile.get("license_number", ""), "phone": profile.get("phone", ""), "email": email or "",
            "quals": quals, "date": today.isoformat(),
            "period": (min(dates).isoformat(), max(dates).isoformat()) if dates else None}


def header_rows():
    """Three header rows (without the two left columns Type / TOTAL) as (text, colspan, rowspan) lists, shared by the web page and the PDF."""
    r1 = [(s, sum(1 for c in COLS if c[0] == s), 1) for s in SECTIONS]
    r2, r3 = [], []
    prev = None
    for c in COLS:
        if c[1]:
            if prev != (c[0], c[1]):
                r2.append((c[1], sum(1 for x in COLS if x[:2] == c[:2]), 1))
            r3.append((c[2], 1, 1))
        else:
            r2.append((c[2], 1, 2))
        prev = (c[0], c[1])
    return r1, r2, r3


# ---------------------------------------------------------------- PDF

def _ps(name, bold=False, size=6.5, **kw):
    d = dict(fontName="Helvetica-Bold" if bold else "Helvetica", fontSize=size, leading=size + 1.6)
    d.update(kw)
    return ParagraphStyle(name, **d)


def build_pdf(rep):
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(letter), leftMargin=0.4 * inch, rightMargin=0.4 * inch,
                            topMargin=0.35 * inch, bottomMargin=0.35 * inch, title=TITLE)
    width = landscape(letter)[0] - 0.8 * inch
    p, pb = _ps("p"), _ps("pb", True)
    small = _ps("s", size=5.8, leading=7.2)
    story = [Paragraph(TITLE, _ps("t", True, 12, leading=14)), Paragraph(RAC_TITLE, _ps("r", True, 8, leading=10)),
             Spacer(1, 4)]
    # left: regulation text; right: certification + qualifications
    left = [Paragraph(escape(t), small) for t in RAC_TEXT]
    ident = [[Paragraph(a, pb), Paragraph(escape(b), p)] for a, b in (
        ("Name :", rep["name"]), ("License number :", rep["license"]), ("Phone number :", rep["phone"]),
        ("Email address :", rep["email"]), ("Date :", rep["date"]), ("Signature :", ""))]
    id_tbl = Table(ident, colWidths=[1.0 * inch, 2.1 * inch], rowHeights=[None] * 5 + [20])
    id_tbl.setStyle(TableStyle([("LINEBELOW", (1, 5), (1, 5), 0.6, colors.black), ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
                                ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1)]))
    q_rows = [[Paragraph("Qualification", pb), Paragraph("Expiry date", pb), Paragraph("Days remaining", pb)]]
    q_rows += [[Paragraph(escape(q["name"]), p), Paragraph(q["expiry"], p), Paragraph(str(q["days"]), p)]
               for q in rep["quals"]]
    q_tbl = Table(q_rows, colWidths=[1.9 * inch, 0.9 * inch, 0.9 * inch])
    q_tbl.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#999999")),
                               ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eeeeee")),
                               ("TOPPADDING", (0, 0), (-1, -1), 0.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 0.5)]))
    right = [Paragraph(CERTIFY, p), Spacer(1, 3), id_tbl, Spacer(1, 5), Paragraph("Qualifications tracking", pb), q_tbl]
    top = Table([[left, right]], colWidths=[width - 4.1 * inch, 4.1 * inch])
    top.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    story += [top, Spacer(1, 4)]
    cat = rep["cat"]
    story += [Paragraph(f"<b>Airplane total :</b> {fmt(cat['airplane'])} &nbsp;&nbsp; <b>Helicopter total :</b> "
                        f"{fmt(cat['helicopter'])} &nbsp;&nbsp; <b>Jet engine / turboshaft total :</b> {fmt(cat['turbine'])}", p),
              Spacer(1, 4)]
    # matrix
    c = _ps("c", size=6, alignment=TA_CENTER, leading=7)
    cb = _ps("cb", True, 6, alignment=TA_CENTER, leading=7)
    ncol = 2 + len(COLS)
    r1, r2, r3 = header_rows()
    data = [[None] * ncol for _ in range(3)]
    spans = []

    def place(row, items, start):
        col = start
        for text, cs, rs in items:
            while data[row][col] is not None:
                col += 1
            data[row][col] = Paragraph(escape(text), cb)
            for rr in range(row, row + rs):
                for cc in range(col, col + cs):
                    if (rr, cc) != (row, col):
                        data[rr][cc] = ""
            if cs > 1 or rs > 1:
                spans.append(("SPAN", (col, row), (col + cs - 1, row + rs - 1)))
            col += cs

    place(0, r1, 2)
    place(1, r2, 2)
    place(2, r3, 2)
    data[0][0], data[0][1] = Paragraph("AIRCRAFT", cb), ""
    data[1][0] = data[1][1] = ""
    data[2][0], data[2][1] = Paragraph("Type", cb), Paragraph("TOTAL", cb)
    spans.append(("SPAN", (0, 0), (1, 1)))
    for ln in rep["lines"]:
        data.append([Paragraph(escape(ln["code"]), cb), Paragraph(fmt(ln["total"]), c)] + [Paragraph(fmt(v), c) for v in ln["cells"]])
    data.append([Paragraph("TOTAL", cb), Paragraph(fmt(rep["total"]), cb)] + [Paragraph(fmt(v), cb) for v in rep["cells_total"]])
    sub = [Paragraph("", c), Paragraph("", c)]
    for s, v in zip(SECTIONS, rep["section_totals"]):
        n = sum(1 for x in COLS if x[0] == s)
        sub += [Paragraph(fmt(v), cb)] + [Paragraph("", c)] * (n - 1)
    data.append(sub)
    last, col = len(data) - 1, 2
    for s in SECTIONS:
        n = sum(1 for x in COLS if x[0] == s)
        spans.append(("SPAN", (col, last), (col + n - 1, last)))
        col += n
    tw = [0.55 * inch, 0.5 * inch] + [(width - 1.05 * inch) / len(COLS)] * len(COLS)
    tbl = Table(data, colWidths=tw, repeatRows=3)
    style = [("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#888888")), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
             ("BACKGROUND", (0, 0), (-1, 2), colors.HexColor("#eeeeee")),
             ("BACKGROUND", (0, last - 1), (-1, last), colors.HexColor("#eeeeee")),
             ("TOPPADDING", (0, 0), (-1, -1), 0.8), ("BOTTOMPADDING", (0, 0), (-1, -1), 0.8),
             ("LEFTPADDING", (0, 0), (-1, -1), 1), ("RIGHTPADDING", (0, 0), (-1, -1), 1)] + spans
    sec_col = 2
    for s in SECTIONS[:-1]:              # thicker line between sections
        sec_col += sum(1 for x in COLS if x[0] == s)
        style.append(("LINEBEFORE", (sec_col, 0), (sec_col, last), 1.0, colors.black))
    tbl.setStyle(TableStyle(style))
    story.append(tbl)
    doc.build(story)
    return buf.getvalue()
