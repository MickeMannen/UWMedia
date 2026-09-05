from pathlib import Path
from typing import List, Optional, Tuple

from utils.app_settings import load_settings
from utils.resource_paths import find_resource, user_data_dir

LAYOUT_SUFFIXES = (".zip", ".json")


def bundled_layouts_dir() -> Optional[Path]:
    """The read-only 'overlays' folder Briefcase copies into the app bundle."""
    return find_resource("overlays", __file__)


def user_layouts_dir() -> Path:
    """Writable folder for the user's own HUD packages - overridable in Advanced settings."""
    override = load_settings().get("layouts_dir")
    path = Path(override) if override else user_data_dir() / "layouts"
    path.mkdir(parents=True, exist_ok=True)
    return path


def list_layouts() -> List[Tuple[str, Path]]:
    """
    (display_name, path) pairs for every bundled or user-supplied HUD
    layout/package, sorted by name. A user file with the same stem as a
    bundled one takes precedence.
    """
    entries = {}

    bundled = bundled_layouts_dir()
    if bundled and bundled.exists():
        for path in sorted(bundled.iterdir()):
            if path.suffix.lower() in LAYOUT_SUFFIXES:
                entries[path.stem] = path

    user_dir = user_layouts_dir()
    if user_dir.exists():
        for path in sorted(user_dir.iterdir()):
            if path.suffix.lower() in LAYOUT_SUFFIXES:
                entries[path.stem] = path

    return sorted(entries.items())
