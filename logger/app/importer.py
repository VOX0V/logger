import csv
import io
import re
from datetime import date, datetime, time
from openpyxl import load_workbook


class FileImportError(Exception):
    pass


def normalize(value):
    """Normalize Excel headers/import rules to a common comparison form."""
    if value is None:
        return ""
    text = str(value).strip().lower()
    # Treat punctuation/separators (hyphens, underscores, dots, slashes, etc.)
    # like spaces so aliases such as ``SE-DUAL-DAY`` and ``se dual day`` match.
    text = re.sub(r"[^\w]+", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def sqlite_value(value):
    """Convert Excel/openpyxl values to SQLite-compatible values."""
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, time):
        return value.isoformat()
    return value


def _select_sheet(workbook, sheet_name=None):
    if sheet_name:
        if sheet_name not in workbook.sheetnames:
            raise FileImportError(f'La feuille "{sheet_name}" n\'existe pas dans ce fichier.')
        return workbook[sheet_name]
    for name in workbook.sheetnames:
        if normalize(name) == "raw":
            return workbook[name]
    return workbook.active


def _read_table(filename, file_bytes, sheet_name=None):
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext in ("xlsx", "xlsm"):
        try:
            workbook = load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
            sheet = _select_sheet(workbook, sheet_name)
            rows = list(sheet.iter_rows(values_only=True))
        except Exception as exc:
            raise FileImportError("Le fichier Excel est illisible ou corrompu.") from exc
        finally:
            try:
                workbook.close()
            except Exception:
                pass
        if not rows:
            raise FileImportError("Le fichier Excel est vide.")
        return list(rows[0]), rows[1:]
    if ext == "csv":
        try:
            rows = list(csv.reader(io.StringIO(file_bytes.decode("utf-8-sig"))))
        except UnicodeDecodeError as exc:
            raise FileImportError("Le fichier CSV n'est pas encodé en UTF-8.") from exc
        if not rows:
            raise FileImportError("Le fichier CSV est vide.")
        return rows[0], rows[1:]
    raise FileImportError("Format de fichier non supporté : utilisez un fichier .xlsx, .xlsm ou .csv.")


def importable_rows(filename, file_bytes, categories, sheet_name=None):
    headers, rows = _read_table(filename, file_bytes, sheet_name)

    rule_map = {}
    for category in categories:
        destination = category.get("colonne_technique")
        for rule in category.get("import", []) or []:
            rule_map[normalize(rule)] = destination

    source_indexes = {}
    for idx, value in enumerate(headers):
        key = normalize(value)
        if key in rule_map:
            source_indexes[idx] = rule_map[key]

    if not source_indexes:
        raise FileImportError("Aucune colonne de ce fichier ne correspond à une règle d'import configurée dans Settings.")

    rows_out = []
    for values in rows:
        if not any(v not in (None, "") for v in values):
            continue
        row = {}
        for idx, destination in source_indexes.items():
            if idx < len(values) and values[idx] not in (None, ""):
                # If two source columns use aliases for the same destination,
                # keep the first non-empty value encountered.
                if destination not in row:
                    row[destination] = sqlite_value(values[idx])
        if row:
            rows_out.append(row)
    if not rows_out:
        raise FileImportError("Aucune donnée à importer dans le fichier.")
    return rows_out, len(source_indexes)
