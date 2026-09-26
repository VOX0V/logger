import io
import re
from openpyxl import load_workbook


def normalize(value):
    if value is None:
        return ""
    text = str(value).strip().lower()
    text = re.sub(r"\s+", " ", text)
    return text


def importable_rows(file_bytes, categories):
    wb = load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
    ws = wb["raw"] if "raw" in wb.sheetnames else wb.active
    iterator = ws.iter_rows(values_only=True)
    try:
        header = next(iterator)
    except StopIteration:
        raise ValueError("Le fichier Excel est vide.")

    rule_map = {}
    for category in categories:
        for rule in category.get("import", []) or []:
            rule_map[normalize(rule)] = category["colonne_technique"]

    source_indexes = {}
    for idx, value in enumerate(header):
        key = normalize(value)
        if key in rule_map:
            source_indexes[idx] = rule_map[key]

    rows = []
    for values in iterator:
        if not any(v not in (None, "") for v in values):
            continue
        row = {}
        for idx, destination in source_indexes.items():
            if destination not in row and idx < len(values) and values[idx] not in (None, ""):
                row[destination] = values[idx]
        if row:
            rows.append(row)
    return rows, len(source_indexes)
