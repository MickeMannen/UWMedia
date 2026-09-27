"""
User-defined output filename patterns (strftime codes applied to a file's
date taken, as cli_main.py's --filename-format does). Saved from the
Advanced page into settings.json's "filename_formats" list and offered on
the Color page next to its built-in presets.
"""
from datetime import datetime
from typing import List, Optional

from utils.app_settings import add_unique, load_settings, save_settings

SETTINGS_KEY = "filename_formats"
# Hidden (2026-09-28, per the user): the Advanced page's section and the
# Color page's listing of saved patterns are off. The code and settings key
# stay so it can come back with one flag; the tests enable it explicitly.
CUSTOM_FILENAME_FORMATS_ENABLED = False
# Same sample date the Color page's built-in preset labels show.
EXAMPLE_DATETIME = datetime(2026, 9, 5, 14, 30, 0)


def custom_filename_formats() -> List[str]:
    return [p for p in (load_settings().get(SETTINGS_KEY) or []) if isinstance(p, str) and p.strip()]


def pattern_error(pattern: str) -> Optional[str]:
    """Why `pattern` can't be used as a filename pattern, or None."""
    if not pattern.strip():
        return "Enter a pattern, e.g. %Y%m%d_%H%M%S_Bali"
    if "/" in pattern or "\\" in pattern:
        return "A filename pattern can't contain / or \\"
    try:
        example = EXAMPLE_DATETIME.strftime(pattern)
    except ValueError as e:
        return f"Invalid pattern: {e}"
    if example == pattern:
        return "The pattern has no date codes (%Y, %m, %d, %H, %M, %S …), so every file would get the same name"
    return None


def example_filename(pattern: str) -> str:
    try:
        return EXAMPLE_DATETIME.strftime(pattern)
    except ValueError:
        return pattern


def add_filename_format(pattern: str) -> None:
    add_unique(SETTINGS_KEY, pattern)


def remove_filename_format(pattern: str) -> None:
    data = load_settings()
    data[SETTINGS_KEY] = [p for p in (data.get(SETTINGS_KEY) or []) if p != pattern]
    save_settings(data)
