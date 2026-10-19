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
                  "vertical_align": "middle", "width_scale": 4.7}


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
        "width_scale": lambda v: _num(v, 0.1, 20) is not None,
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
    for key, lo, hi in (("rows_per_page", 1, 200), ("row_height", 1, 200)):
        if key in layout and _num(layout[key], lo, hi) is None:
            out.append(f"{key} : nombre entre {lo} et {hi} attendu.")
    for key in ("header_heights", "gap_widths"):
        if key in layout and not (isinstance(layout[key], list) and all(_num(v, 0, 200) is not None for v in layout[key])):
            out.append(f"{key} : liste de nombres entre 0 et 200 attendue.")
    for key in ("columns", "physical_columns"):
        for i, col in enumerate(layout.get(key, []) or [], 1):
            if isinstance(col, dict) and "width" in col and _num(col["width"], 0, 200) is None:
                out.append(f"{key} n°{i} : width entre 0 et 200 attendu.")
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
    for key, default in (("rows_per_page", 30), ("row_height", 16.95)):
        if _num(cfg.get(key), 1, 200) is None:
            cfg[key] = default
    for key, default in (("header_heights", [16.95] * 4), ("gap_widths", [3.9, 4.9])):
        if not (isinstance(cfg.get(key), list) and all(_num(v, 0, 200) is not None for v in cfg[key])):
            cfg[key] = list(default)
    for key in ("columns", "physical_columns"):
        for col in cfg.get(key, []) or []:
            if isinstance(col, dict) and "width" in col and _num(col["width"], 0, 200) is None:
                col["width"] = 13.0
    return cfg
