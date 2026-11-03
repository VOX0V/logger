"""Import profiles: a single file <app root>/importer/import.yml (groups -> RAW columns -> header per profile), shared by all accounts.

A profile only maps the headers of an airline file to database columns. Values are imported
untouched (the raw database holds raw data)."""
import re
from collections import Counter
from pathlib import Path

import yaml

from .config import save_config, technical_name
from .importer import FileImportError

PROFILE_ID = re.compile(r"[a-z0-9_-]+")
FILE_NAME = "import.yml"
DEFAULT_ID = "default"
DATA_TYPES = {"text", "integer", "decimal", "date", "datetime", "boolean"}


def profiles_path():
    return Path(__file__).resolve().parent.parent / "importer" / FILE_NAME


def _read():
    path = profiles_path()
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise FileImportError(f"{FILE_NAME} is unreadable.") from exc
    if not isinstance(data, dict) or not isinstance(data.get("profiles"), dict):
        raise FileImportError(f"{FILE_NAME} is invalid.")
    return data


def _profile_info(data, profile_id):
    info = data["profiles"].get(profile_id)
    if info is None or not PROFILE_ID.fullmatch(str(profile_id)):
        return None
    return info if isinstance(info, dict) else {}


def list_profiles(include_default=False):
    """[{id, name}] of the profiles of import.yml, sorted by name (the default profile only on request)."""
    try:
        data = _read()
    except FileImportError:
        return []
    found = []
    for profile_id in data["profiles"]:
        if profile_id == DEFAULT_ID and not include_default:
            continue
        info = _profile_info(data, profile_id)
        if info is not None:
            found.append({"id": str(profile_id), "name": str(info.get("name") or profile_id)})
    return sorted(found, key=lambda p: p["name"].lower())


def load_profile(profile_id):
    data = _read()
    info = _profile_info(data, profile_id) if PROFILE_ID.fullmatch(profile_id or "") else None
    if info is None:
        raise FileImportError("Unknown import profile.")
    columns = []
    for group in data.get("groups") or []:
        for item in (group or {}).get("columns") or []:
            headers = item.get(profile_id) if isinstance(item, dict) else None
            if not headers:
                continue
            try:
                column = technical_name(item.get("column"))
            except ValueError as exc:
                raise FileImportError(f"{FILE_NAME}: invalid column name '{item.get('column')}'.") from exc
            for header in headers if isinstance(headers, list) else [headers]:
                columns.append({"header": str(header), "column": column, "display_name": column,
                                "group": str(group.get("group") or ""), "data_type": str(item.get("data_type") or "text")})
    if not columns:
        raise FileImportError(f"Import profile '{profile_id}' has no columns.")
    return {"id": profile_id, "name": str(info.get("name") or profile_id), "sheet": info.get("sheet") or None, "columns": columns}


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
