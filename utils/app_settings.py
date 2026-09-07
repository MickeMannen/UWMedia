import json
from pathlib import Path
from typing import Any, Dict

from utils.resource_paths import user_data_dir

SETTINGS_FILENAME = "settings.json"

DEFAULT_SETTINGS: Dict[str, Any] = {
    # None means "use the default user_data_dir() location"
    "layouts_dir": None,
    "color_profiles_dir": None,
    # None means "auto-detect from PATH / common install locations"
    "ffmpeg_path": None,
    "exiftool_path": None,
    "filename_formats": [],
    "render_log_filename_formats": [],
    # Last-used value of every persisted Process/Advanced form field, keyed
    # by its widget attribute name (e.g. "source_input", "hw_accel_switch").
    "fields": {},
}


def settings_path() -> Path:
    return user_data_dir() / SETTINGS_FILENAME


def load_settings() -> Dict[str, Any]:
    data = dict(DEFAULT_SETTINGS)
    path = settings_path()
    if path.exists():
        try:
            with open(path, "r") as f:
                data.update(json.load(f) or {})
        except Exception as e:
            print(f"Error loading {path}: {e}")
    return data


def save_settings(data: Dict[str, Any]) -> None:
    path = settings_path()
    try:
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"Error saving {path}: {e}")


def update_settings(**changes: Any) -> Dict[str, Any]:
    data = load_settings()
    data.update(changes)
    save_settings(data)
    return data


def set_field(key: str, value: Any) -> None:
    """Persist the current value of one Process/Advanced form field."""
    data = load_settings()
    fields = dict(data.get("fields") or {})
    fields[key] = value
    data["fields"] = fields
    save_settings(data)


def get_fields() -> Dict[str, Any]:
    return load_settings().get("fields") or {}


def add_unique(key: str, value: str) -> Dict[str, Any]:
    """Append `value` to the settings list at `key` if it isn't already present."""
    data = load_settings()
    items = list(data.get(key) or [])
    if value not in items:
        items.append(value)
    data[key] = items
    save_settings(data)
    return data
