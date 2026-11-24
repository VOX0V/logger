"""Import profiles: one file per employer, <id>_import.yml, in <app root>/importer/ (shipped) and appdata/importer/
(copy edited in the web interface, which wins). Shared by all accounts.

A profile only says which header of an airline file goes to which ENTITY (see Data > Entities). Values are imported
untouched (the raw database holds raw data). The columns of the raw database are created by the import, from the
entities that the profile uses: name and order come from the entity list; the type is always text (the work data converts to the right type).

    name: Jazz Aviation          # shown in the import menu
    columns:                     # header of the file: entity   (several headers may go to the same entity)
      fcv_aircraft_type: aircraft_type
      to_day: count_takeoff_day
    ignored: [deadhead, tail_number]    # optional, documentation only: headers deliberately not imported
    filters:                     # optional: rows of the file to import; a row must pass every filter
      - column: fcv_aircraft_type        # a header of the file
        only: [CRJ9, CRJ2]               # keep only the rows whose value is one of these (not case sensitive)
      - column: crew_list
        only_containing: [816505]        # keep only the rows whose value contains one of these texts
      - column: flight_number
        only_matching: '\d{4}'           # keep only the rows whose whole value matches a pattern (regular expression): here 4 digits
      - column: some_header
        exclude: [text]                  # leave out the rows whose value contains one of these texts
      - column: dep_datetime_local
        not_after: today                 # leave out the rows whose date is later than today (or yesterday) (YYYY-MM-DD...)

A header of the file that is not listed under "columns" is not imported. In an Excel file, the sheet named "raw" is read,
otherwise the active sheet.
"""
import re
import shutil
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


SEEDED = ".seeded"


def _seed():
    """The first time, the shipped profiles are copied to appdata/importer; from then on the profiles of that folder are the only
    ones used, so every profile can be edited, renamed or deleted (Data > Import profiles). False when that is not possible."""
    folder = edited_dir()
    if folder is None:
        return False
    if (folder / SEEDED).exists():
        return True
    try:
        folder.mkdir(parents=True, exist_ok=True)
        for path in BUNDLED_DIR.glob("*" + SUFFIX):
            if not (folder / path.name).exists():
                shutil.copy2(path, folder / path.name)
        (folder / SEEDED).write_text("The shipped import profiles were copied here; only the profiles of this folder are used.\n", encoding="utf-8")
    except OSError:
        return False
    return True


def profile_ids():
    folders = (edited_dir(),) if _seed() else (BUNDLED_DIR, edited_dir())
    ids = set()
    for folder in folders:
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
    """The entity list (Data > Entities): {entity: {entity, group, data_type, display_name}} in position order."""
    from .entities import load_entities as _load
    return _load()


FILTER_KINDS = ("only", "only_containing", "only_matching", "exclude", "not_after")


def _check_filters(filters):
    """Checks the optional “filters” list of an import profile; raises FileImportError with a readable message."""
    if filters is None:
        return
    if not isinstance(filters, list) or not filters:
        raise FileImportError("“filters” must be a list of filters, each with a “column” and one of “only”, “only_containing”, “only_matching”, “exclude” or “not_after”.")
    for i, item in enumerate(filters, 1):
        if not isinstance(item, dict):
            raise FileImportError(f"Filter no.{i} must have a “column” and one of “only”, “only_containing”, “only_matching”, “exclude” or “not_after”.")
        unknown = set(item) - {"column", *FILTER_KINDS}
        if unknown:
            raise FileImportError(f"Filter no.{i}: unknown key “{sorted(unknown, key=str)[0]}”.")
        if not isinstance(item.get("column"), str) or not item["column"].strip():
            raise FileImportError(f"Filter no.{i}: “column” (a header of the file) is required.")
        kinds = [k for k in FILTER_KINDS if k in item]
        if len(kinds) != 1:
            raise FileImportError(f"Filter no.{i}: use exactly one of “only”, “only_containing”, “only_matching”, “exclude” or “not_after”.")
        kind = kinds[0]
        if kind == "not_after":
            if item["not_after"] not in ("today", "yesterday"):
                raise FileImportError(f"Filter no.{i}: “not_after” only accepts “today” or “yesterday”.")
            continue
        values = item[kind] if isinstance(item[kind], list) else [item[kind]]
        if not values or any(v is None or isinstance(v, (bool, dict, list)) or not str(v).strip() for v in values):
            raise FileImportError(f"Filter no.{i}: “{kind}” must be a text or a list of texts.")
        if kind == "only_matching":
            for v in values:
                try:
                    re.compile(str(v))
                except re.error as exc:
                    raise FileImportError(f"Filter no.{i}: the pattern “{v}” is not valid ({exc}).")


def parse_spec(data):
    """Checks the content of one <id>_import.yml; raises FileImportError with a readable message."""
    if not isinstance(data, dict):
        raise FileImportError("The file must contain “name” and “columns” (header: entity).")
    if "groups" in data:
        raise FileImportError("Old format: replace “groups” by “columns”, one line per header, written  header: entity.")
    unknown = set(data) - {"name", "columns", "ignored", "filters"}
    if unknown:
        raise FileImportError(f"Unknown key “{sorted(unknown)[0]}”.")
    if data.get("name") is not None and not isinstance(data["name"], str):
        raise FileImportError("“name” must be a text.")
    columns = data.get("columns")
    if not isinstance(columns, dict) or not columns:
        raise FileImportError("“columns” must list the headers of the file, one per line, written  header: entity.")
    entities = load_entities()
    for header, entity in columns.items():
        if not str(header).strip():
            raise FileImportError("A header of “columns” is empty.")
        if not isinstance(entity, str) or entity not in entities:
            raise FileImportError(f"Header “{header}”: unknown entity “{entity}” (see Data > Entities).")
    ignored = data.get("ignored")
    if ignored is not None and not (isinstance(ignored, list) and all(isinstance(h, str) for h in ignored)):
        raise FileImportError("“ignored” must be a list of headers.")
    _check_filters(data.get("filters"))


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


def broken_profiles():
    """[(file, reason)] of the import profiles that cannot be used (unknown entity, syntax...)."""
    found = []
    for profile_id in profile_ids():
        try:
            _read(profile_id)
        except FileImportError as exc:
            found.append((profile_id, str(exc)))
    return found


def load_profile(profile_id):
    if not PROFILE_ID.fullmatch(profile_id or "") or profile_id not in profile_ids():
        raise FileImportError("Unknown import profile.")
    data = _read(profile_id)
    entities = load_entities()
    columns = [{"header": str(header), "column": entity, "display_name": entities[entity]["display_name"],
                "group": entities[entity]["group"], "data_type": entities[entity]["data_type"]}
               for header, entity in data["columns"].items()]
    filters = []
    for item in data.get("filters") or []:
        entry = {"column": item["column"].strip()}
        for kind in FILTER_KINDS:
            if kind in item:
                entry[kind] = item[kind] if kind == "not_after" else [str(v) for v in (item[kind] if isinstance(item[kind], list) else [item[kind]])]
        filters.append(entry)
    return {"id": profile_id, "name": str(data.get("name") or profile_id), "columns": columns, "filters": filters}


def ensure_profile_columns(config, profile, extra=()):
    """Create in the raw database the columns that the profile needs (plus the entities in `extra`) and that do not
    exist yet: name and order come from the entity list; the type is always text (the work data converts to the right type). The display name and the order of all the columns follow
    entities.yml at every import (the type of an existing column does not change). Returns the names of the columns created."""
    columns = config["database"]["columns"]
    known = {c["column"] for c in columns}
    entities = load_entities()
    added = []
    for column in [item["column"] for item in profile["columns"]] + [e for e in extra if e in entities]:
        if column in known:
            continue
        columns.append({"column": column, "display_name": entities[column]["display_name"], "position": 0,
                        "data_type": "text", "nullable": True, "visible": True, "editable": True})
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
    try:
        file_headers = {normalize(v) for v in _read_table(filename, file_bytes)[0]}
    except Exception:
        file_headers = set()
    scored = []
    for profile, headers in profiles:
        total = sum(1 / shared[h] for h in headers)
        hit = sum(1 / shared[h] for h in headers if h in file_headers)
        scored.append((hit / total if total else 0, profile))
    scored.sort(key=lambda s: s[0], reverse=True)
    if scored[0][0] < 0.5 or (len(scored) > 1 and scored[0][0] - scored[1][0] < 0.1):
        return None
    return {"id": scored[0][1]["id"], "name": scored[0][1]["name"]}
