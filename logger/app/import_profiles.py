"""Import profiles: one file per employer, <id>_import.yml, in <app root>/importer/ (shipped) and appdata/importer/
(copy edited in the web interface, which wins). Shared by all accounts.

A profile only says which header of an airline file goes to which ENTITY (see entities.yml). Values are imported
untouched (the raw database holds raw data). The columns of the raw database are created by the import, from the
entities that the profile uses: name, type and order come from entities.yml.

    name: Jazz Aviation          # shown in the import menu
    sheet: raw                   # optional: sheet to read (default: "raw", else the active sheet)
    columns:                     # header of the file: entity   (several headers may go to the same entity)
      fcv_aircraft_type: aircraft_type
      to_day: count_takeoff_day
    ignored: [deadhead, tail_number]    # optional, documentation only: headers deliberately not imported

A header of the file that is not listed under "columns" is not imported.
"""
import re
from collections import Counter
from pathlib import Path

import yaml

from .config import save_config, technical_name, is_system
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


ENTITIES_FILE = "entities.yml"


def entities_path():
    """The edited copy when there is one, otherwise the shipped file."""
    edited = edited_dir()
    if edited is not None and (edited / ENTITIES_FILE).is_file():
        return edited / ENTITIES_FILE
    return BUNDLED_DIR / ENTITIES_FILE


def parse_entities(data):
    """Checks the content of entities.yml; returns {entity: {entity, group, data_type, display_name}} in file order."""
    items = data.get("entities") if isinstance(data, dict) else None
    if not isinstance(items, list) or not items:
        raise FileImportError("“entities” must be a non-empty list of entities.")
    out = {}
    for i, item in enumerate(items, 1):
        if not isinstance(item, dict) or not isinstance(item.get("entity"), str):
            raise FileImportError(f"Entity no.{i}: “entity” (its name) is required.")
        name = item["entity"]
        try:
            valid = technical_name(name) == name
        except ValueError as exc:
            raise FileImportError(f"Entity no.{i} ({name}): {exc}") from exc
        if not valid:
            raise FileImportError(f"Entity no.{i}: “{name}” must only use lowercase letters, digits and underscores.")
        if name in out:
            raise FileImportError(f"Entity “{name}” is defined twice.")
        data_type = str(item.get("data_type") or "text")
        if data_type not in DATA_TYPES:
            raise FileImportError(f"Entity “{name}”: unknown data_type “{data_type}”.")
        unknown = set(item) - {"entity", "group", "data_type", "display_name"}
        if unknown:
            raise FileImportError(f"Entity “{name}”: unknown key “{sorted(unknown)[0]}”.")
        out[name] = {"entity": name, "group": str(item.get("group") or ""), "data_type": data_type,
                     "display_name": str(item.get("display_name") or name)}
    return out


def load_entities():
    path = entities_path()
    try:
        return parse_entities(yaml.safe_load(path.read_text(encoding="utf-8")) or {})
    except (OSError, yaml.YAMLError) as exc:
        raise FileImportError(f"{path.name} is unreadable.") from exc


def parse_spec(data):
    """Checks the content of one <id>_import.yml; raises FileImportError with a readable message."""
    if not isinstance(data, dict):
        raise FileImportError("The file must contain “name” and “columns” (header: entity).")
    if "groups" in data:
        raise FileImportError("Old format: replace “groups” by “columns”, one line per header, written  header: entity.")
    unknown = set(data) - {"name", "sheet", "columns", "ignored"}
    if unknown:
        raise FileImportError(f"Unknown key “{sorted(unknown)[0]}”.")
    if data.get("name") is not None and not isinstance(data["name"], str):
        raise FileImportError("“name” must be a text.")
    if data.get("sheet") is not None and not isinstance(data["sheet"], str):
        raise FileImportError("“sheet” must be a text.")
    columns = data.get("columns")
    if not isinstance(columns, dict) or not columns:
        raise FileImportError("“columns” must list the headers of the file, one per line, written  header: entity.")
    entities = load_entities()
    for header, entity in columns.items():
        if not str(header).strip():
            raise FileImportError("A header of “columns” is empty.")
        if not isinstance(entity, str) or entity not in entities:
            raise FileImportError(f"Header “{header}”: unknown entity “{entity}” (see entities.yml).")
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
    entities = load_entities()
    columns = [{"header": str(header), "column": entity, "display_name": entities[entity]["display_name"],
                "group": entities[entity]["group"], "data_type": entities[entity]["data_type"]}
               for header, entity in data["columns"].items()]
    return {"id": profile_id, "name": str(data.get("name") or profile_id), "sheet": data.get("sheet") or None, "columns": columns}


def ensure_profile_columns(config, profile, extra=()):
    """Create in the raw database the columns that the profile needs (plus the entities in `extra`) and that do not
    exist yet: name, type and order come from entities.yml. The display name and the order of all the columns follow
    entities.yml at every import (the type of an existing column does not change). Returns the names of the columns created."""
    columns = config["database"]["columns"]
    known = {c["column"] for c in columns}
    entities = load_entities()
    added = []
    for column in [item["column"] for item in profile["columns"]] + [e for e in extra if e in entities]:
        if column in known:
            continue
        columns.append({"column": column, "display_name": entities[column]["display_name"], "position": 0,
                        "data_type": entities[column]["data_type"], "nullable": True, "visible": True, "editable": True})
        known.add(column)
        added.append(column)
    changed = bool(added)
    order = {name: i for i, name in enumerate(entities)}
    system = [c for c in columns if is_system(c)]
    data = [c for c in columns if not is_system(c)]
    for c in data:                                          # the display name follows entities.yml
        entity = entities.get(c["column"])
        if entity and c.get("display_name") != entity["display_name"]:
            c["display_name"] = entity["display_name"]
            changed = True
    ordered = sorted(data, key=lambda c: order.get(c["column"], len(order)))      # the order follows entities.yml
    if [c["column"] for c in ordered] != [c["column"] for c in data] or any(c.get("position") != i for i, c in enumerate(ordered, 1)):
        changed = True
    for i, c in enumerate(ordered, 1):
        c["position"] = i
    columns[:] = system + ordered
    if changed:
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
