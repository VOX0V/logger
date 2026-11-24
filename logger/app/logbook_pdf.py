"""Export PDF du logbook : deux feuilles Letter paysage par page de logbook (moitié gauche, moitié droite).

Chaque feuille garde une gouttière vide côté reliure (droite pour les pages paires, gauche pour les impaires)
afin de pouvoir perforer. Une page vierge est ajoutée au début pour que les pages se retrouvent face à face.
Tous les réglages sont dans la section `pdf:` de logbook_layout.yml (unité entière : 1 u = 0,01 po)."""
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib.colors import HexColor, black
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, Table, TableStyle

PDF_DEFAULTS = {
    "page_width_u": 1100,       # Letter paysage : 11 po
    "page_height_u": 850,       # 8,5 po
    "row_height_u": 22,         # hauteur de TOUTES les lignes (37 lignes = 814 u)
    "offset_top_u": 0,          # réglage fin du tableau vers le bas (u) ; avec center_vertical, 0 = exactement centré
    "center_vertical": True,    # tableau centré verticalement sur la page
    "blank_first_page": True,   # page 1 vierge pour que les pages 2 et 3 se retrouvent face à face
    # bande libre côté reliure (PDF seulement, pour percer les pages) : chaque feuille doit totaliser page_width_u
    "gutter_left_u": 29,        # bande libre de la feuille gauche (marge extérieure comprise)
    "gutter_right_u": 38,       # bande libre de la feuille droite (marge extérieure comprise)
    "margin_outer_u": 2,        # marge à gauche de la feuille gauche et à droite de la feuille droite, pour que le trait extérieur reste visible ;
                                # elle est prise sur la bande libre de la même feuille : le total reste page_width_u
}
U = 0.01 * 72                   # 1 unité en points
PX = 0.75                       # 1 px (hauteurs et polices du YAML) en points
SECTION = 1.5
GREY = HexColor("#777777")
RIGHT_GROUPS = ("multi_engine", "instruments", "cross_country", "landings", "instruction")


def pdf_settings(layout):
    layout = layout or {}
    cfg = dict(PDF_DEFAULTS)
    cfg.update(layout.get("pdf") or {})
    cfg["row_height_u"] = int(round(float(layout.get("row_height_u", cfg["row_height_u"]))))
    widths = [int(round(float(c.get("width", 0)))) for c in layout.get("columns", []) if c.get("group") != "spacer"]   # mêmes largeurs que la page web
    margin = max(0, int(cfg["margin_outer_u"]))
    left_gutter, right_gutter = max(0, int(cfg["gutter_left_u"]) - margin), max(0, int(cfg["gutter_right_u"]) - margin)   # la marge est prise sur la bande libre : total inchangé
    cfg["left_columns_u"] = [{"key": "margin", "u": margin}] + [{"key": f"c{i + 1}", "u": w} for i, w in enumerate(widths[:14])] + [{"key": "gutter", "u": left_gutter}]
    cfg["right_columns_u"] = [{"key": "gutter", "u": right_gutter}] + [{"key": f"c{i + 15}", "u": w} for i, w in enumerate(widths[14:])] + [{"key": "margin", "u": margin}]
    return cfg


def _fit(text, width, font, size):
    """Texte tronqué avec … s'il dépasse la largeur de la cellule."""
    text = "" if text is None else str(text)
    avail = width - 3
    if stringWidth(text, font, size) <= avail:
        return text
    while text and stringWidth(text + "…", font, size) > avail:
        text = text[:-1]
    return text + "…" if text else ""


def _page_table(side, year, rows, summary, grand, layout, columns, cfg, page_no, dates, email):
    """Tableau d'une moitié ('left' ou 'right') ; retourne (Table, largeur en points)."""
    from .main import _hours1, _two          # import tardif : main importe ce module
    st = layout["styles"]
    n_rows = int(layout.get("rows_per_page", 30))
    entries = cfg["left_columns_u"] if side == "left" else cfg["right_columns_u"]
    name = "the left columns + gutter_left_u" if side == "left" else "the right columns + gutter_right_u"
    if sum(int(e["u"]) for e in entries) != cfg["page_width_u"]:
        raise ValueError(f"PDF : {name} totalise {sum(int(e['u']) for e in entries)} u instead of {cfg['page_width_u']} (gutter and outer margin included).")
    data = [e for e in entries if e["key"] not in ("gutter", "margin")]
    if len(data) != (14 if side == "left" else 18):
        raise ValueError(f"PDF: the sheet {'gauche' if side == 'left' else 'droite'} must contain {14 if side == 'left' else 18} data columns (excluding spacers).")
    first = next(i for i, e in enumerate(entries) if e["key"] not in ("gutter", "margin"))
    x0 = sum(int(e["u"]) for e in entries[:first]) * U            # marge (feuille gauche) ou gouttière (feuille droite) avant le tableau
    cw = [int(e["u"]) * U for e in data]
    total_w = sum(cw)
    nc = len(cw)

    fs, hfs = float(st.get("font_size", 10)) * PX, float(st.get("header_font_size", 9)) * PX
    hdr_bg, tot_bg = HexColor(st.get("header_background", "#ffffff")), HexColor(st.get("total_background", "#eeeeee"))
    blocks = st.get("data_blocks") or [{"color": "#ffffff"}]
    alt = bool(st.get("alternate_white", True))

    HDR = 4                                     # en-tête sur 4 lignes, comme le modèle (lignes 1 à 4 du classeur)
    T0 = HDR + n_rows
    T1, T2, F = T0 + 1, T0 + 2, T0 + 3
    grid = [[""] * nc for _ in range(F + 1)]
    spans, cmds = [], []

    def span(c0, r0, c1, r1):
        spans.append(("SPAN", (c0, r0), (c1, r1)))

    def put(r, c, text, n=1, font="Helvetica", size=fs):
        grid[r][c] = _fit(text, sum(cw[c:c + n]), font, size)
        if n > 1:
            span(c, r, c + n - 1, r)

    def label(r, c, text, n=1, nr=1):           # texte d'en-tête ou de pied de page (déjà court, jamais tronqué)
        grid[r][c] = text
        if n > 1 or nr > 1:
            span(c, r, c + n - 1, r + nr - 1)

    decimals = {c["key"]: c.get("decimals", 1) for c in columns}
    num = lambda d, k: _hours1(d.get(k, ""), decimals.get(k, 1))
    keys = [c["key"] for c in columns if c.get("group") in RIGHT_GROUPS] if side == "right" else \
           [c["key"] for c in columns if c.get("group") == "single_engine"]
    s1, s2, s3 = (summary + [{}, {}, {}])[:3]

    if side == "left":
        for c, t, n, nr in ((0, "YEAR", 2, 2), (2, "AIRCRAFT", 2, 3), (4, "FLIGHT CREW", 2, 3),
                            (6, "ROUTE OF FLIGHT", 2, 3), (8, "REMARKS", 2, 3), (10, "SINGLE-ENGINE", 4, 2)):
            label(0, c, t, n, nr)
        label(2, 0, str(year), 2)
        label(2, 10, "Day", 2); label(2, 12, "Night", 2)
        for c, t in enumerate(("Month", "Day", "Type", "Registr.", "Pilot", "Co-Pilot", "Departure", "Arrival")):
            label(3, c, t)
        label(3, 8, "Exercise, Mission, Flight Number…", 2)
        for c, t in zip(range(10, 14), ("Dual", "PIC", "Dual", "PIC")):
            label(3, c, t)
        sections = [10]
    else:
        label(0, 0, "MULTI-ENGINE", 6, 2); label(0, 6, "INSTRUMENTS", 4, 2); label(0, 10, "CROSS-COUNTRY", 4, 2)
        label(0, 14, "TAKEOFFS & LANDINGS", 2, 2); label(0, 16, "INSTRUCTION", 2, 2)
        label(2, 0, "Day", 3); label(2, 3, "Night", 3); label(2, 10, "Day", 2); label(2, 12, "Night", 2)
        for c, t in ((6, "IFR"), (7, "Hood"), (8, "FTD"), (9, "IFR app"), (14, "Day"), (15, "Night"), (16, "Day"), (17, "Night")):
            label(2, c, t, 1, 2)
        for c, t in enumerate(("Dual", "PIC", "Co-Pilot", "Dual", "PIC", "Co-Pilot")):
            label(3, c, t)
        for c, t in zip(range(10, 14), ("Dual", "PIC", "Dual", "PIC")):
            label(3, c, t)
        sections = [6, 10, 14, 16]

    for i in range(n_rows):
        r, row = HDR + i, (rows[i] if i < len(rows) else {})
        if side == "left":
            for c, k in enumerate(("month", "day")):
                put(r, c, _two(row.get(k, "")))
            for c, k in zip(range(2, 8), ("type", "registration", "pilot", "copilot", "departure", "arrival")):
                put(r, c, row.get(k, ""))
            put(r, 8, row.get("remarks", ""), 2)
            c0 = 10
        else:
            c0 = 0
        for j, k in enumerate(keys):
            put(r, c0 + j, num(row, k))
        if not alt or i % 2 == 0:
            color = blocks[min(i // 10, len(blocks) - 1)].get("color", "#ffffff")
            cmds.append(("BACKGROUND", (0, r), (-1, r), HexColor(color)))

    bold, italic = "Helvetica-Bold", "Helvetica-BoldOblique"
    if side == "left":
        # totaux comme le modèle : A:C vide, D à part, E:F date, G:I GRAND TOTAL, J libellé ; ligne 3 : Signature A:C, D, Date E:F, total G:I, J libellé
        span(0, T0, 2, T1); span(4, T0, 5, T1); span(6, T0, 8, T1)
        grid[T0][4] = _fit(dates[1], cw[4] + cw[5], bold, fs)
        grid[T0][6] = "GRAND TOTAL"
        for r, s, dflt in ((T0, s1, "Page Totals"), (T1, s2, "Totals forwarded"), (T2, s3, "Totals to date")):
            lbl_style = ParagraphStyle("lbl", fontName=italic, fontSize=fs, leading=fs * 1.15, alignment=TA_CENTER)
            grid[r][9] = Paragraph("<u>%s</u>" % escape(_fit(s.get("remarks", dflt), cw[9], italic, fs)), lbl_style)      # centré et souligné
            for j, k in enumerate(keys):
                put(r, 10 + j, num(s, k), 1, bold)
        label(T2, 0, "Signature", 3); label(T2, 4, "Date", 2)
        put(T2, 6, _hours1(grand), 3, bold)
    else:
        for r, s in ((T0, s1), (T1, s2), (T2, s3)):
            for j, k in enumerate(keys):
                put(r, j, num(s, k), 1, bold)
    first, last = dates
    # pied de page : une cellule par texte, comme le modèle (étiquettes à droite, valeurs à gauche, e-mail centré)
    if side == "left":
        footer = ((0, 1, "Page :", "RIGHT"), (1, 2, str(page_no), "LEFT"), (3, 2, "Période du :", "RIGHT"), (5, 2, first, "LEFT"),
                  (7, 1, "au :", "RIGHT"), (8, 2, last, "LEFT"), (10, 4, email or "", "CENTER"))
    else:
        footer = ((0, 1, "Page :", "RIGHT"), (1, 1, str(page_no), "LEFT"), (3, 2, "Période du :", "RIGHT"), (5, 3, first, "LEFT"),
                  (8, 1, "au :", "RIGHT"), (9, 5, last, "LEFT"), (14, 4, email or "", "CENTER"))
    footer_cmds = []
    for c, n, text, align in footer:
        label(F, c, text, n)
        footer_cmds.append(("ALIGN", (c, F), (c, F), align))
        if align == "LEFT":
            footer_cmds.append(("LEFTPADDING", (c, F), (c, F), 4))
        elif align == "RIGHT":
            footer_cmds.append(("RIGHTPADDING", (c, F), (c, F), 4))
    cmds += spans
    cmds += [
        ("FONT", (0, 0), (-1, F), "Helvetica", fs), ("ALIGN", (0, 0), (-1, T2), "CENTER"), ("VALIGN", (0, 0), (-1, F), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 1), ("RIGHTPADDING", (0, 0), (-1, -1), 1), ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("FONT", (0, 0), (-1, HDR - 1), "Helvetica-Bold", hfs), ("BACKGROUND", (0, 0), (-1, 1), hdr_bg),
        ("BACKGROUND", (0, 2), (-1, 2), HexColor("#d9d9d9")), ("BACKGROUND", (0, 3), (-1, 3), HexColor("#eeeeee")),
        ("BACKGROUND", (0, T0), (-1, T2), tot_bg),
        ("INNERGRID", (0, 0), (-1, T2), 0.5, GREY), ("BOX", (0, 0), (-1, F), SECTION, black),
        ("LINEABOVE", (0, T0), (-1, T0), SECTION, black), ("LINEABOVE", (0, HDR), (-1, HDR), SECTION, black),
        ("LINEABOVE", (0, F), (-1, F), SECTION, black),
        ("FONT", (0, F), (-1, F), bold, fs),
    ]
    if side == "left":
        cmds.append(("BACKGROUND", (0, 2), (1, 2), hdr_bg))             # l'année n'a pas de fond, comme le modèle
        cmds.append(("BACKGROUND", (2, 2), (9, 2), hdr_bg))             # cellules fusionnées sur 3 lignes : pas de bande grise
    else:
        cmds += [("BACKGROUND", (6, 3), (9, 3), HexColor("#d9d9d9")), ("BACKGROUND", (14, 3), (17, 3), HexColor("#d9d9d9"))]   # fusionnées sur 2 lignes
    for c in sections:
        cmds.append(("LINEBEFORE", (c, 0), (c, T2), SECTION, black))
    cmds += footer_cmds                                                 # après les marges générales, pour qu'elles ne les écrasent pas
    if side == "left":
        cmds += [("ALIGN", (9, T0), (9, T2), "CENTER"), ("FONT", (6, T0), (6, T0), bold, 14 * PX),
                 ("BACKGROUND", (6, T0), (8, T1), HexColor("#d9d9d9")), ("BACKGROUND", (6, T2), (8, T2), HexColor("#d9d9d9")),
                 ("FONT", (6, T2), (8, T2), bold, 14 * PX), ("ALIGN", (0, T2), (0, T2), "CENTER"), ("ALIGN", (4, T2), (4, T2), "CENTER"),
                 ("VALIGN", (0, T2), (-1, T2), "BOTTOM"), ("BACKGROUND", (0, T0), (3, T1), hdr_bg)]
    rh = int(cfg["row_height_u"])
    if rh * (F + 1) > cfg["page_height_u"] - int(cfg["offset_top_u"]):
        raise ValueError(f"PDF : {F + 1} rows of {rh} u exceed the page height ({cfg['page_height_u']} u).")
    t = Table(grid, colWidths=cw, rowHeights=[rh * U] * (F + 1))
    t.setStyle(TableStyle(cmds))
    return t, total_w, x0


def build_logbook_pdf(ctx, years, email=""):
    """PDF des années demandées. ctx : contexte de main._logbook_context(). Retourne les octets du PDF."""
    from .main import _long_date
    layout, columns = ctx["layout"], ctx["columns"]
    cfg = pdf_settings(layout)
    W, H = cfg["page_width_u"] * U, cfg["page_height_u"] * U
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=(W, H))
    c.setTitle(str(layout.get("title", "Logbook")))
    if cfg.get("blank_first_page", True):
        c.showPage()
    for y in years:
        for idx, rows in enumerate(ctx["year_pages"][y]):
            summary = ctx["year_summaries"][y][idx] if ctx["year_summaries"].get(y) else []
            grand = ctx["year_grand"][y][idx]
            dates = (_long_date(rows[0]) if rows else "", _long_date(rows[-1]) if rows else "")
            number = (ctx["year_page_offset"][y] + idx) * 2 + 2
            for side, page_no in (("left", number), ("right", number + 1)):
                table, tw, x0 = _page_table(side, y, rows, summary, grand, layout, columns, cfg, page_no, dates, email)
                _, th = table.wrapOn(c, tw, H)
                top = ((H - th) / 2 if cfg.get("center_vertical", True) else 0) + cfg["offset_top_u"] * U      # centré sur la hauteur de la page
                table.drawOn(c, x0, H - top - th)
                c.showPage()
    c.save()
    return buf.getvalue()
