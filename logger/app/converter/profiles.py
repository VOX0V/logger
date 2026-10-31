"""Per-airline conversion profiles: <app root>/converter/<import profile id>_convert.yml (shared by all accounts; a copy edited in the web interface lives in appdata/converter/ and wins)."""
import re
from pathlib import Path

import yaml

from .catalog import normalize_rule
from .transforms import FUNCTIONS

PROFILE_ID = re.compile(r"[a-z0-9_-]+")
BUNDLED_DIR = Path(__file__).resolve().parent.parent.parent / "converter"


def edited_dir():
    """Writable folder for conversion files edited in the web interface (appdata/converter/); None outside the app."""
    try:
        from ..db import appdata_root
        return appdata_root() / "converter"
    except RuntimeError:
        return None


def profile_path(profile_id):
    """File of a conversion profile: the edited copy in appdata when there is one, else the file shipped with the app."""
    if not profile_id or not PROFILE_ID.fullmatch(str(profile_id)):
        return None
    name = f"{profile_id}_convert.yml"
    folder = edited_dir()
    if folder is not None and (folder / name).is_file():
        return folder / name
    shipped = BUNDLED_DIR / name
    return shipped if shipped.is_file() else None


def profile_rules(profile_id):
    """Normalized rules of the conversion profile named like an import profile, or None when it has none."""
    path = profile_path(profile_id)
    if path is None:
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return None
    rules = [normalize_rule(r) for r in (data.get("rules") or []) if isinstance(r, dict)]
    return [r for r in rules if r["id"] and r["transform"] in FUNCTIONS]
