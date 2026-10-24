"""Validation des réglages d'affichage du logbook avant qu'ils finissent dans du CSS (<style>) ou un PDF.

Les valeurs viennent du YAML éditable par l'utilisateur : on n'accepte que des formes strictement
connues, sinon injection CSS possible (exfiltration par url(), défiguration).
"""
import math
import re

HEX = re.compile(r"^#[0-9A-Fa-f]{3,8}$")
FONT = re.compile(r"^[A-Za-z0-9 ,_-]{1,80}$")
BORDER = re.compile(r"^\d{1,2}px (solid|dashed|dotted|double|none) #[0-9A-Fa-f]{3,8}$")
ALIGN = {"left", "center", "right"}
VALIGN = {"top", "middle", "bottom"}
DEFAULT_STYLES = {"font_family": "Arial", "font_size": 10, "header_font_size": 9, "border": "1px solid #000000",
                  "header_background": "#ffffff", "total_background": "#eeeeee", "text_align": "center",
                  "vertical_align": "middle"}


def _num(value, lo, hi):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not lo <= value <= hi:
        return None
    return value


def style_problems(styles):
    """Liste des problèmes (vide = valide) pour le bloc `styles` d'un layout."""
    out = []
    if not isinstance(styles, dict):
        return ["« styles » doit être un bloc clé: valeur."]
    checks = {
        "font_family": lambda v: isinstance(v, str) and FONT.match(v),
        "font_size": lambda v: _num(v, 4, 40) is not None, "header_font_size": lambda v: _num(v, 4, 40) is not None,
        "border": lambda v: isinstance(v, str) and BORDER.match(v),
        "header_background": lambda v: isinstance(v, str) and HEX.match(v),
        "total_background": lambda v: isinstance(v, str) and HEX.match(v),
        "text_align": lambda v: v in ALIGN, "vertical_align": lambda v: v in VALIGN,
    }
    for key, ok in checks.items():
        if key in styles and not ok(styles[key]):
            out.append(f"styles.{key} : valeur non autorisée (lettres/chiffres/espaces pour la police, #RRGGBB pour les couleurs, "
                       "« 1px solid #000000 » pour la bordure).")
    for i, block in enumerate(styles.get("data_blocks", []) or [], 1):
        if isinstance(block, dict) and not (isinstance(block.get("color"), str) and HEX.match(block["color"])):
            out.append(f"styles.data_blocks n°{i} : couleur #RRGGBB attendue.")
    return out


def layout_problems(layout):
    out = style_problems(layout.get("styles", {}))
    for key, lo, hi in (("rows_per_page", 1, 200), ("row_height_u", 5, 200)):
        if key in layout and _num(layout[key], lo, hi) is None:
            out.append(f"{key} : nombre entre {lo} et {hi} attendu.")
    for i, col in enumerate(layout.get("columns", []) or [], 1):
        if isinstance(col, dict) and "width" in col and _num(col["width"], 0, 1100) is None:
            out.append(f"columns n°{i} : width entre 0 et 1100 attendu.")
    return out


def sanitize_layout(cfg):
    """Défense en profondeur au rendu : toute valeur invalide retombe sur la valeur par défaut."""
    styles = cfg.setdefault("styles", {})
    for key, default in DEFAULT_STYLES.items():
        if style_problems({key: styles.get(key, default)}):
            styles[key] = default
    blocks = styles.get("data_blocks")
    if isinstance(blocks, list):
        styles["data_blocks"] = [b if isinstance(b, dict) and isinstance(b.get("color"), str) and HEX.match(b["color"])
                                 else {**(b if isinstance(b, dict) else {}), "color": "#ffffff"} for b in blocks]
    for key, default in (("rows_per_page", 30), ("row_height_u", 22)):
        if _num(cfg.get(key), 1, 200) is None:
            cfg[key] = default
    for col in cfg.get("columns", []) or []:
        if isinstance(col, dict) and "width" in col and _num(col["width"], 0, 1100) is None:
            col["width"] = 51
    return cfg


BD_NUMBERS = {"page_width_u": (300, 3000), "page_height_u": (300, 3000), "margin_u": (0, 200), "gap_u": (0, 100),
              "row_height_u": (5, 100), "title_height_u": (10, 300), "title_font_size": (8, 80), "rac_bar_height_u": (8, 100),
              "top_height_u": (50, 800), "cert_height_u": (30, 400), "qual_row_height_u": (6, 60), "photo_height_u": (0, 600),
              "totals_height_u": (20, 300)}


def breakdown_problems(cfg):
    """Problèmes (liste vide = valide) d'un breakdown.yml."""
    out = style_problems(cfg.get("styles", {}))
    zc = (cfg.get("styles") or {}).get("zero_color", "#cccccc")
    if not (isinstance(zc, str) and HEX.match(zc)):
        out.append("styles.zero_color : couleur #RRGGBB attendue.")
    for key, (lo, hi) in BD_NUMBERS.items():
        if key in cfg and _num(cfg[key], lo, hi) is None:
            out.append(f"{key} : nombre entre {lo} et {hi} attendu.")
    tw = cfg.get("top_widths_u", {})
    if not isinstance(tw, dict) or any(_num(tw.get(k), 10, 3000) is None for k in ("left", "middle", "right")):
        out.append("top_widths_u : left, middle et right doivent être des nombres entre 10 et 3000.")
    for i, col in enumerate(cfg.get("columns", []) or [], 1):
        if not isinstance(col, dict) or not isinstance(col.get("key"), str) or _num(col.get("width"), 0, 3000) is None:
            out.append(f"columns n°{i} : « key » et « width » (0 à 3000) attendus.")
    rows = cfg.get("rows", [])
    if not isinstance(rows, list) or len(rows) > 60 or any(not isinstance(x, (str, type(None))) or len(str(x or "")) > 20 for x in rows):
        out.append("rows : liste de 60 codes de types au plus (20 caractères max chacun, vide = ligne libre).")
    return out


def sanitize_breakdown(cfg):
    from .config import DEFAULT_BREAKDOWN as D
    styles = cfg["styles"]
    for key, default in {**DEFAULT_STYLES, "zero_color": "#cccccc"}.items():
        if key == "zero_color":
            if not (isinstance(styles.get(key), str) and HEX.match(styles[key])):
                styles[key] = D["styles"]["zero_color"]
        elif style_problems({key: styles.get(key, default)}):
            styles[key] = D["styles"].get(key, default)
    for key, (lo, hi) in BD_NUMBERS.items():
        if _num(cfg.get(key), lo, hi) is None:
            cfg[key] = D[key]
    for k in ("left", "middle", "right"):
        if _num(cfg["top_widths_u"].get(k), 10, 3000) is None:
            cfg["top_widths_u"][k] = D["top_widths_u"][k]
    for col, dflt in zip(cfg["columns"], D["columns"]):
        if _num(col.get("width"), 0, 3000) is None:
            col["width"] = dflt["width"]
    return cfg
