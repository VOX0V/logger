"""Import profiles: one YAML file per airline in <app root>/import_profiles/, shared by all accounts.

A profile only maps the headers of an airline file to database columns. Values are imported
untouched (the raw database holds raw data). A profile replaces the default import rules."""
import re
from pathlib import Path

import yaml

from .config import save_config, technical_name
from .importer import FileImportError

PROFILE_ID = re.compile(r"[a-z0-9_-]+")
DATA_TYPES = {"text", "integer", "decimal", "date", "datetime", "boolean"}


def profiles_dir():
    return Path(__file__).resolve().parent.parent / "import_profiles"


def _read(path):
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise FileImportError(f"Import profile {path.name} is unreadable.") from exc
    if not isinstance(data, dict):
        raise FileImportError(f"Import profile {path.name} is invalid.")
    return data


def list_profiles():
    """[{id, name}] of the available profiles, sorted by name."""
    folder, found = profiles_dir(), []
    if folder.is_dir():
        for path in folder.glob("*.yml"):
            if not PROFILE_ID.fullmatch(path.stem):
                continue
            try:
                found.append({"id": path.stem, "name": str(_read(path).get("name") or path.stem)})
            except FileImportError:
                continue
    return sorted(found, key=lambda p: p["name"].lower())


def load_profile(profile_id):
    if not PROFILE_ID.fullmatch(profile_id or "") or profile_id not in {p["id"] for p in list_profiles()}:
        raise FileImportError("Unknown import profile.")
    data = _read(profiles_dir() / f"{profile_id}.yml")
    columns = []
    for item in data.get("columns") or []:
        if not isinstance(item, dict) or not item.get("header") or not item.get("column"):
            raise FileImportError(f"Import profile '{profile_id}': each column needs a header and a column.")
        try:
            column = technical_name(item["column"])
        except ValueError as exc:
            raise FileImportError(f"Import profile '{profile_id}': invalid column name '{item['column']}'.") from exc
        columns.append({**item, "column": column})
    if not columns:
        raise FileImportError(f"Import profile '{profile_id}' has no columns.")
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
        position = len([c for c in columns if c.get("group") != "system"]) + 1
        columns.append({"column": item["column"], "display_name": str(item.get("display_name") or item["header"]),
                        "position": position, "group": str(item.get("group") or "profile"), "data_type": data_type,
                        "nullable": True, "visible": True, "editable": True, "import_rules": []})
        known.add(item["column"])
        added.append(item["column"])
    if added:
        save_config(config)
    return added
