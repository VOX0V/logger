"""Export PDF du logbook : deux feuilles Letter paysage par page de logbook (moitié gauche, moitié droite).

Chaque feuille garde une gouttière vide côté reliure (droite pour les pages paires, gauche pour les impaires)
afin de pouvoir perforer. Une page vierge est ajoutée au début pour que les pages se retrouvent face à face.
Tous les réglages sont dans la section `pdf:` de logbook_layout.yml (unité entière : 1 u = 0,01 po)."""
from io import BytesIO

from reportlab.lib.colors import HexColor, black
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas
from reportlab.platypus import Table, TableStyle

PDF_DEFAULTS = {
    "page_width_u": 1100,       # Letter paysage : 11 po
    "page_height_u": 850,       # 8,5 po
    "row_height_u": 22,         # hauteur de TOUTES les lignes (37 lignes = 814 u)
    "offset_top_u": 0,          # décalage du tableau depuis le haut (0 : l'imprimante gère les marges)
    "blank_first_page": True,   # page 1 vierge pour que les pages 2 et 3 se retrouvent face à face
    # gouttières (PDF seulement, pour percer les pages) : chaque feuille doit totaliser page_width_u, gouttière comprise
    "gutter_left_u": 29,        # à droite de la feuille gauche
    "gutter_right_u": 38,       # à gauche de la feuille droite
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
    cfg["left_columns_u"] = [{"key": f"c{i + 1}", "u": w} for i, w in enumerate(widths[:14])] + [{"key": "gutter", "u": int(cfg["gutter_left_u"])}]
    cfg["right_columns_u"] = [{"key": "gutter", "u": int(cfg["gutter_right_u"])}] + [{"key": f"c{i + 15}", "u": w} for i, w in enumerate(widths[14:])]
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
    name = "les colonnes de gauche + gutter_left_u" if side == "left" else "les colonnes de droite + gutter_right_u"
    if sum(int(e["u"]) for e in entries) != cfg["page_width_u"]:
        raise ValueError(f"PDF : {name} totalise {sum(int(e['u']) for e in entries)} u au lieu de {cfg['page_width_u']} (gouttière comprise).")
    data = [e for e in entries if e["key"] != "gutter"]
    if len(data) != (14 if side == "left" else 18):
        raise ValueError(f"PDF : la feuille {'gauche' if side == 'left' else 'droite'} doit contenir {14 if side == 'left' else 18} colonnes de données (hors espaceurs).")
    first = next(i for i, e in enumerate(entries) if e["key"] != "gutter")
    x0 = sum(int(e["u"]) for e in entries[:first]) * U            # gouttière à gauche : la feuille droite démarre après elle
    cw = [int(e["u"]) * U for e in data]
    total_w = sum(cw)
    nc = len(cw)

    fs, hfs = float(st.get("font_size", 10)) * PX, float(st.get("header_font_size", 9)) * PX
    hdr_bg, tot_bg = HexColor(st.get("header_background", "#ffffff")), HexColor(st.get("total_background", "#eeeeee"))
    blocks = st.get("data_blocks") or [{"color": "#ffffff"}]
    alt = bool(st.get("alternate_white", True))

    T0 = 3 + n_rows
    T1, T2, F = T0 + 1, T0 + 2, T0 + 3
    grid = [[""] * nc for _ in range(F + 1)]
    spans, cmds = [], []

    def span(c0, r0, c1, r1):
        spans.append(("SPAN", (c0, r0), (c1, r1)))

    def put(r, c, text, n=1, font="Helvetica", size=fs):
        grid[r][c] = _fit(text, sum(cw[c:c + n]), font, size)
        if n > 1:
            span(c, r, c + n - 1, r)

    def label(r, c, text, n=1):                 # texte d'en-tête (déjà court, jamais tronqué)
        grid[r][c] = text
        if n > 1:
            span(c, r, c + n - 1, r)

    num = lambda d, k: _hours1(d.get(k, ""))
    keys = [c["key"] for c in columns if c.get("group") in RIGHT_GROUPS] if side == "right" else \
           [c["key"] for c in columns if c.get("group") == "single_engine"]
    s1, s2, s3 = (summary + [{}, {}, {}])[:3]

    if side == "left":
        for c, t, n, nr in ((0, "YEAR", 2, 1), (2, "AIRCRAFT", 2, 2), (4, "FLIGHT CREW", 2, 2),
                            (6, "ROUTE OF FLIGHT", 2, 2), (8, "REMARKS", 2, 2), (10, "SINGLE-ENGINE", 4, 1)):
            grid[0][c] = t
            span(c, 0, c + n - 1, nr - 1)
        label(1, 0, str(year), 2)
        label(1, 10, "Day", 2); label(1, 12, "Night", 2)
        for c, t in enumerate(("Month", "Day", "Type", "Registr.", "Pilot", "Co-Pilot", "Departure", "Arrival")):
            label(2, c, t)
        label(2, 8, "Exercise, Mission, Flight Number…", 2)
        for c, t in zip(range(10, 14), ("Dual", "PIC", "Dual", "PIC")):
            label(2, c, t)
        sections = [10]
    else:
        label(0, 0, "MULTI-ENGINE", 6); grid[0][6] = "INSTRUMENTS"; span(6, 0, 9, 1)
        label(0, 10, "CROSS-COUNTRY", 4); label(0, 14, "TAKEOFFS & LANDINGS", 2); label(0, 16, "INSTRUCTION", 2)
        label(1, 0, "Day", 3); label(1, 3, "Night", 3); label(1, 10, "Day", 2); label(1, 12, "Night", 2)
        for c, t in ((14, "Day"), (15, "Night"), (16, "Day"), (17, "Night")):
            label(1, c, t); span(c, 1, c, 2)
        for c, t in enumerate(("Dual", "PIC", "Co-Pilot", "Dual", "PIC", "Co-Pilot", "IFR", "Hood", "FTD", "IFR app",
                               "Dual", "PIC", "Dual", "PIC")):
            label(2, c, t)
        sections = [6, 10, 14, 16]

    for i in range(n_rows):
        r, row = 3 + i, (rows[i] if i < len(rows) else {})
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
        span(0, T0, 3, T1); span(4, T0, 5, T1); span(6, T0, 7, T1)
        grid[T0][4] = _fit(dates[1], cw[4] + cw[5], bold, fs)
        grid[T0][6] = "GRAND TOTAL"
        for r, s, dflt in ((T0, s1, "Page Totals"), (T1, s2, "Totals forwarded"), (T2, s3, "Totals to date")):
            put(r, 8, s.get("remarks", dflt), 2, italic)
            for j, k in enumerate(keys):
                put(r, 10 + j, num(s, k), 1, bold)
        label(T2, 0, "Signature", 3); label(T2, 4, "Date", 2)
        put(T2, 6, _hours1(grand), 2, bold)
    else:
        for r, s in ((T0, s1), (T1, s2), (T2, s3)):
            for j, k in enumerate(keys):
                put(r, j, num(s, k), 1, bold)
    first, last = dates
    mail_c = 10 if side == "left" else 14
    label(F, 0, f"Page : {page_no}", 3)
    label(F, 3, f"Période du : {first} au : {last}", mail_c - 3)
    label(F, mail_c, email or "", nc - mail_c)
    cmds += spans
    cmds += [
        ("FONT", (0, 0), (-1, F), "Helvetica", fs), ("ALIGN", (0, 0), (-1, F), "CENTER"), ("VALIGN", (0, 0), (-1, F), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 1), ("RIGHTPADDING", (0, 0), (-1, -1), 1), ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("FONT", (0, 0), (-1, 2), "Helvetica-Bold", hfs), ("BACKGROUND", (0, 0), (-1, 0), hdr_bg),
        ("BACKGROUND", (0, 1), (-1, 1), HexColor("#d9d9d9")), ("BACKGROUND", (0, 2), (-1, 2), HexColor("#eeeeee")),
        ("BACKGROUND", (0, T0), (-1, T2), tot_bg),
        ("INNERGRID", (0, 0), (-1, T2), 0.5, GREY), ("BOX", (0, 0), (-1, T2), SECTION, black),
        ("LINEABOVE", (0, T0), (-1, T0), SECTION, black), ("LINEABOVE", (0, 3), (-1, 3), SECTION, black),
        ("FONT", (0, F), (-1, F), "Helvetica", 9 * PX), ("ALIGN", (0, F), (0, F), "LEFT"),
        ("LINEBELOW", (0, F), (-1, F), 0, HexColor("#ffffff")),
    ]
    cmds.append(("LEFTPADDING", (0, F), (0, F), 4))
    for c in sections:
        cmds.append(("LINEBEFORE", (c, 0), (c, T2), SECTION, black))
    if side == "left":
        cmds += [("ALIGN", (8, T0), (8, T2), "LEFT"), ("FONT", (6, T0), (6, T0), bold, 14 * PX),
                 ("BACKGROUND", (6, T0), (7, T1), HexColor("#d9d9d9")), ("BACKGROUND", (6, T2), (7, T2), HexColor("#d9d9d9")),
                 ("FONT", (6, T2), (7, T2), bold, 14 * PX), ("ALIGN", (0, T2), (0, T2), "LEFT"), ("LEFTPADDING", (0, T2), (0, T2), 4), ("LEFTPADDING", (8, T0), (8, T2), 4),
                 ("VALIGN", (0, T2), (-1, T2), "BOTTOM"), ("BACKGROUND", (0, T0), (3, T1), hdr_bg)]

    rh = int(cfg["row_height_u"])
    if rh * (F + 1) > cfg["page_height_u"] - int(cfg["offset_top_u"]):
        raise ValueError(f"PDF : {F + 1} lignes de {rh} u dépassent la hauteur de page ({cfg['page_height_u']} u).")
    t = Table(grid, colWidths=cw, rowHeights=[rh * U] * (F + 1))
    t.setStyle(TableStyle(cmds))
    return t, total_w, x0


def build_logbook_pdf(ctx, years, email=""):
    """PDF des années demandées. ctx : contexte de main._logbook_context(). Retourne les octets du PDF."""
    from .main import _fr_date
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
            dates = (_fr_date(rows[0]) if rows else "", _fr_date(rows[-1]) if rows else "")
            number = (ctx["year_page_offset"][y] + idx) * 2 + 2
            for side, page_no in (("left", number), ("right", number + 1)):
                table, tw, x0 = _page_table(side, y, rows, summary, grand, layout, columns, cfg, page_no, dates, email)
                _, th = table.wrapOn(c, tw, H)
                table.drawOn(c, x0, H - cfg["offset_top_u"] * U - th)
                c.showPage()
    c.save()
    return buf.getvalue()
