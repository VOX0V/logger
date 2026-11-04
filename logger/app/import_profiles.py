"""Import profiles: one file per employer, <id>_import.yml, in <app root>/importer/ (shipped) and appdata/importer/
(copy edited in the web interface, which wins). Shared by all accounts.

A profile only maps the headers of an airline file to RAW database columns. Values are imported
untouched (the raw database holds raw data).

    name: Jazz Aviation          # shown in the import menu
    sheet: raw                   # optional: sheet to read (default: "raw", else the active sheet)
    groups:                      # groups are only there to keep the file readable
      - group: aircrafts
        columns:
          - {column: type, header: fcv_aircraft_type}          # header: one name or a list of names
          - {column: takeoff_day, header: to_day, data_type: integer}   # data_type: text (default), integer, ...
    ignored: [deadhead, tail_number]    # headers of the file deliberately not imported (documentation)
"""
import re
from collections import Counter
from pathlib import Path

import yaml

from .config import save_config, technical_name
from .importer import FileImportError

PROFILE_ID = re.compile(r"[a-z0-9_-]+")
SUFFIX = "_import.yml"
DEFAULT_ID = "default"
DATA_TYPES = {"text", "integer", "decimal", "date", "datetime", "boolean"}
BUNDLED_DIR = Path(__file__).resolve().parent.parent / "importer"


def edited_dir():
    """Writable folder of the files edited in the web interface (appdata/importer); None outside the app."""
    try:
        from .db import appdata_root
        return appdata_root() / "importer"
    except RuntimeError:
        return None


def profile_ids():
    ids = set()
    for folder in (BUNDLED_DIR, edited_dir()):
        if folder is not None and folder.is_dir():
            ids |= {p.name[:-len(SUFFIX)] for p in folder.glob("*" + SUFFIX)}
    return sorted(i for i in ids if PROFILE_ID.fullmatch(i))


def profile_path(profile_id):
    """The edited copy when there is one, otherwise the shipped file."""
    edited = edited_dir()
    if edited is not None and (edited / f"{profile_id}{SUFFIX}").is_file():
        return edited / f"{profile_id}{SUFFIX}"
    return BUNDLED_DIR / f"{profile_id}{SUFFIX}"


def parse_spec(data):
    """Checks the content of one <id>_import.yml; raises FileImportError with a readable message."""
    if not isinstance(data, dict):
        raise FileImportError("The file must contain “name”, “groups” and optionally “ignored”.")
    if data.get("name") is not None and not isinstance(data["name"], str):
        raise FileImportError("“name” must be a text.")
    if data.get("sheet") is not None and not isinstance(data["sheet"], str):
        raise FileImportError("“sheet” must be a text.")
    if not isinstance(data.get("groups"), list) or not data["groups"]:
        raise FileImportError("“groups” must be a list of groups.")
    seen = set()
    for group in data["groups"]:
        if not isinstance(group, dict) or not isinstance(group.get("columns"), list):
            raise FileImportError("Each group needs “group” (its name) and a “columns” list.")
        for item in group["columns"]:
            if not isinstance(item, dict) or not item.get("column"):
                raise FileImportError(f"Group “{group.get('group')}”: each column needs a “column” name.")
            try:
                name = technical_name(item["column"])
            except ValueError as exc:
                raise FileImportError(f"Invalid column name “{item['column']}”.") from exc
            if name in seen:
                raise FileImportError(f"Column “{name}” is defined twice.")
            seen.add(name)
            headers = item.get("header")
            if isinstance(headers, str):
                headers = [headers]
            if not isinstance(headers, list) or not headers or not all(isinstance(h, str) and h.strip() for h in headers):
                raise FileImportError(f"Column “{name}”: “header” must be a header of the file or a list of headers.")
            if str(item.get("data_type") or "text") not in DATA_TYPES:
                raise FileImportError(f"Column “{name}”: unknown data_type “{item.get('data_type')}”.")
            unknown = set(item) - {"column", "header", "data_type", "display_name"}
            if unknown:
                raise FileImportError(f"Column “{name}”: unknown key “{sorted(unknown)[0]}”.")
    ignored = data.get("ignored")
    if ignored is not None and not (isinstance(ignored, list) and all(isinstance(h, str) for h in ignored)):
        raise FileImportError("“ignored” must be a list of headers.")


def _read(profile_id):
    path = profile_path(profile_id)
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise FileImportError(f"{path.name} is unreadable.") from exc
    try:
        parse_spec(data)
    except FileImportError as exc:
        raise FileImportError(f"{path.name}: {exc}") from exc
    return data


def list_profiles(include_default=False):
    """[{id, name}] of the import profiles, sorted by name (the default profile only on request)."""
    found = []
    for profile_id in profile_ids():
        if profile_id == DEFAULT_ID and not include_default:
            continue
        try:
            data = _read(profile_id)
        except FileImportError:
            continue
        found.append({"id": profile_id, "name": str(data.get("name") or profile_id)})
    return sorted(found, key=lambda p: p["name"].lower())


def load_profile(profile_id):
    if not PROFILE_ID.fullmatch(profile_id or "") or profile_id not in profile_ids():
        raise FileImportError("Unknown import profile.")
    data = _read(profile_id)
    columns = []
    for group in data["groups"]:
        for item in group["columns"]:
            headers = item["header"] if isinstance(item["header"], list) else [item["header"]]
            column = technical_name(item["column"])
            for header in headers:
                columns.append({"header": str(header), "column": column, "display_name": str(item.get("display_name") or column),
                                "group": str(group.get("group") or ""), "data_type": str(item.get("data_type") or "text")})
    return {"id": profile_id, "name": str(data.get("name") or profile_id), "sheet": data.get("sheet") or None, "columns": columns}


def ensure_profile_columns(config, profile):
    """Add to the user's database the columns of the profile that do not exist yet. Returns their names."""
    columns = config["database"]["columns"]
    known = {c["column"] for c in columns}
    added = []
    for item in profile["columns"]:
        if item["column"] in known:
            continue
        data_type = str(item.get("data_type") or "text")
        if data_type not in DATA_TYPES:
            raise FileImportError(f"Import profile '{profile['id']}': invalid data_type '{data_type}' for '{item['column']}'.")
        position = len([c for c in columns if not c.get("system")]) + 1
        columns.append({"column": item["column"], "display_name": str(item.get("display_name") or item["header"]),
                        "position": position, "data_type": data_type,
                        "nullable": True, "visible": True, "editable": True})
        known.add(item["column"])
        added.append(item["column"])
    if added:
        save_config(config)
    return added


def detect_profile(filename, file_bytes):
    """Import profile whose headers best match the column headers of a file: {id, name}, or None when no profile
    clearly matches. A header found in several profiles weighs less than one that belongs to a single profile."""
    from .importer import _read_table, normalize
    profiles = []
    for item in list_profiles():
        try:
            profile = load_profile(item["id"])
        except FileImportError:
            continue
        profiles.append((profile, {normalize(c["header"]) for c in profile["columns"]} - {""}))
    if not profiles:
        return None
    shared = Counter(h for _profile, headers in profiles for h in headers)
    file_headers, scored = {}, []
    for profile, headers in profiles:
        sheet = profile.get("sheet")
        if sheet not in file_headers:
            try:
                file_headers[sheet] = {normalize(v) for v in _read_table(filename, file_bytes, sheet)[0]}
            except Exception:
                file_headers[sheet] = set()
        total = sum(1 / shared[h] for h in headers)
        hit = sum(1 / shared[h] for h in headers if h in file_headers[sheet])
        scored.append((hit / total if total else 0, profile))
    scored.sort(key=lambda s: s[0], reverse=True)
    if scored[0][0] < 0.5 or (len(scored) > 1 and scored[0][0] - scored[1][0] < 0.1):
        return None
    return {"id": scored[0][1]["id"], "name": scored[0][1]["name"]}
