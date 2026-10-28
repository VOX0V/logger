"""Per-airline conversion profiles: <app root>/converter/<import profile id>_convert.yml (shared by all accounts)."""
import re
from pathlib import Path

import yaml

from .catalog import normalize_rule
from .transforms import FUNCTIONS

PROFILE_ID = re.compile(r"[a-z0-9_-]+")


def profile_rules(profile_id):
    """Normalized rules of the conversion profile named like an import profile, or None when it has none."""
    if not profile_id or not PROFILE_ID.fullmatch(str(profile_id)):
        return None
    path = Path(__file__).resolve().parent.parent.parent / "converter" / f"{profile_id}_convert.yml"
    if not path.is_file():
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return None
    rules = [normalize_rule(r) for r in (data.get("rules") or []) if isinstance(r, dict)]
    return [r for r in rules if r["id"] and r["transform"] in FUNCTIONS]
