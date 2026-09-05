from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from utils.app_settings import load_settings
from utils.resource_paths import find_resource, user_data_dir

COLOR_YAML_NAME = "color.yaml"


def bundled_color_yaml_path() -> Optional[Path]:
    """The read-only color.yaml Briefcase copies into the app bundle."""
    return find_resource(COLOR_YAML_NAME, __file__)


def user_color_yaml_path() -> Path:
    """Writable color.yaml for the user's own profiles - overridable in Advanced settings."""
    override = load_settings().get("color_profiles_dir")
    base = Path(override) if override else user_data_dir()
    base.mkdir(parents=True, exist_ok=True)
    return base / COLOR_YAML_NAME


def _load_yaml(path: Optional[Path]) -> Dict[str, Any]:
    if not path or not path.exists():
        return {}
    try:
        with open(path, "r") as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        print(f"Error loading {path}: {e}")
        return {}


def load_merged_color_profiles() -> Dict[str, Any]:
    """Bundled defaults with the user's own profiles layered on top (same name wins)."""
    data = _load_yaml(bundled_color_yaml_path())
    data.update(_load_yaml(user_color_yaml_path()))
    return data or {"default": {}}


def save_user_profile(name: str, values: Dict[str, Any]) -> None:
    """
    Merge `values` into the user's color.yaml under profile `name`, leaving
    every other profile already in that file untouched. Never touches the
    bundled color.yaml - saving a profile named e.g. "default" simply creates
    a user override that takes precedence over the bundled one.
    """
    path = user_color_yaml_path()
    data = _load_yaml(path)
    data[name] = values
    with open(path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)
