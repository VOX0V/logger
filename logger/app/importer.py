import csv
import io
import re
from datetime import date, datetime, time
from openpyxl import load_workbook

from .uploads import check_xlsx


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


def _select_sheet(workbook):
    for name in workbook.sheetnames:
        if normalize(name) == "raw":
            return workbook[name]
    return workbook.active


def _read_table(filename, file_bytes):
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext in ("xlsx", "xlsm"):
        try:
            check_xlsx(file_bytes)
        except ValueError as exc:
            raise FileImportError(str(exc)) from exc
        try:
            workbook = load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
            sheet = _select_sheet(workbook)
            rows = list(sheet.iter_rows(values_only=True))
        except Exception as exc:
            raise FileImportError("The Excel file is unreadable or corrupted.") from exc
        finally:
            try:
                workbook.close()
            except Exception:
                pass
        if not rows:
            raise FileImportError("The Excel file is empty.")
        return list(rows[0]), rows[1:]
    if ext == "csv":
        try:
            rows = list(csv.reader(io.StringIO(file_bytes.decode("utf-8-sig"))))
        except UnicodeDecodeError as exc:
            raise FileImportError("The CSV file is not UTF-8 encoded.") from exc
        if not rows:
            raise FileImportError("The CSV file is empty.")
        return rows[0], rows[1:]
    raise FileImportError("Unsupported file format: use an .xlsx, .xlsm or .csv file.")


def _cell_text(value):
    return "" if value is None else str(value).strip().casefold()


def _cell_date(value, line):
    """Date of a cell (datetime, date, or text starting with YYYY-MM-DD); None for an empty cell."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        pass
    match = re.match(r"\d{4}-\d{2}-\d{2}", text)
    if match:
        try:
            return date.fromisoformat(match.group())
        except ValueError:
            pass
    raise FileImportError(f"Line {line} of the file: the date “{text}” cannot be read (expected YYYY-MM-DD).")


def _compile_filters(filters, headers):
    """Filters of the import profile with the position of their column in the file: [(index, kind, values)]."""
    positions = {}
    for idx, value in enumerate(headers):
        positions.setdefault(normalize(value), idx)
    compiled = []
    for item in filters:
        idx = positions.get(normalize(item["column"]))
        if idx is None:
            raise FileImportError(f"The column “{item['column']}” of a filter does not exist in this file.")
        for kind in ("only", "exclude", "not_after"):
            if kind in item:
                values = None if kind == "not_after" else {str(v).strip().casefold() for v in item[kind]}
                compiled.append((idx, kind, values))
    return compiled


def _kept(compiled, values, line, today):
    """True when the row passes every filter of the import profile."""
    for idx, kind, wanted in compiled:
        value = values[idx] if idx < len(values) else None
        if kind == "not_after":
            day = _cell_date(value, line)
            if day is not None and day > today:
                return False
            continue
        text = _cell_text(value)
        if kind == "only" and text not in wanted:
            return False
        if kind == "exclude" and any(part in text for part in wanted):
            return False
    return True


def importable_rows(filename, file_bytes, categories=None, profile=None):
    """Rows to import, using the header mapping and the filters of an import profile (importer/<id>_import.yml)."""
    if profile is None:
        raise FileImportError("Select an import profile.")
    headers, rows = _read_table(filename, file_bytes)
    rule_map = {}
    for item in profile["columns"]:
        rule_map.setdefault(normalize(item["header"]), item["column"])

    source_indexes = {}
    for idx, value in enumerate(headers):
        key = normalize(value)
        if key in rule_map:
            source_indexes[idx] = rule_map[key]

    if not source_indexes:
        raise FileImportError(f"No column of this file matches the headers of the '{profile['name']}' import profile.")

    filters = _compile_filters(profile.get("filters") or [], headers)
    today = date.today()
    rows_out, left_out = [], 0
    for line, values in enumerate(rows, start=2):
        if not any(v not in (None, "") for v in values):
            continue
        if not _kept(filters, values, line, today):
            left_out += 1
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
        if left_out:
            raise FileImportError("No row left to import: the filters of the import profile left out every row of the file.")
        raise FileImportError("No data to import in the file.")
    return rows_out, len(source_indexes)
