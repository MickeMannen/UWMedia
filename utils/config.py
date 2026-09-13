import yaml
from pathlib import Path
from typing import Dict, Any, Optional, List

from utils.resource_paths import find_resource, user_data_dir

CONFIG_YAML_NAME = "config.yaml"


def bundled_config_yaml_path() -> Optional[Path]:
    """A repo-root/dev-checkout config.yaml, if one exists (legacy location, source-run only)."""
    return find_resource(CONFIG_YAML_NAME, __file__)


def user_config_yaml_path() -> Path:
    """Writable config.yaml alongside the app's other user data (settings.json, layouts, color profiles)."""
    return user_data_dir() / CONFIG_YAML_NAME


class ConfigManager:
    _instance = None
    _config: Dict[str, Any] = {}
    _config_path: Optional[Path] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ConfigManager, cls).__new__(cls)
            cls._instance.load_config()
        return cls._instance

    def is_loaded(self) -> bool:
        """Returns True if a config file was found and loaded."""
        return self._config_path is not None

    def _load_yaml(self, path: Optional[Path]) -> Dict[str, Any]:
        if not path or not path.exists():
            return {}
        try:
            with open(path, 'r') as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            print(f"Error loading {path}: {e}")
            return {}

    def load_config(self):
        user_path = user_config_yaml_path()
        if user_path.exists():
            self._config_path = user_path
        else:
            self._config_path = bundled_config_yaml_path()

        self._config = self._load_yaml(self._config_path)
        if self._config_path:
            print(f"Loaded configuration from: {self._config_path}")

    def _write(self):
        path = user_config_yaml_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w') as f:
            yaml.dump(self._config, f, default_flow_style=False, sort_keys=False)
        self._config_path = path

    def save_config(self, tank_serials: List[str]):
        """Adds any newly discovered tank serials to the mapping (leaving already-named
        tanks untouched) and writes the result to the user's writable config.yaml."""
        tanks = dict(self.get_tank_mapping())
        for serial in tank_serials:
            tanks.setdefault(str(serial), f"Tank {serial}")
        self._config["tanks"] = dict(sorted(tanks.items()))

        try:
            self._write()
            print(f"Successfully saved configuration file: {self._config_path}")
        except Exception as e:
            print(f"Error saving config.yaml: {e}")

    def set_tank_name(self, serial: str, name: str):
        """Sets the friendly name for one tank serial and saves immediately."""
        tanks = dict(self.get_tank_mapping())
        tanks[str(serial)] = name
        self._config["tanks"] = tanks
        self._write()

    def remove_tank(self, serial: str):
        """Removes a tank serial from the mapping and saves immediately."""
        tanks = dict(self.get_tank_mapping())
        tanks.pop(str(serial), None)
        self._config["tanks"] = tanks
        self._write()

    def get_tank_mapping(self) -> Dict[str, str]:
        """Returns the tank mapping (serial -> friendly name)."""
        return self._config.get("tanks", {})

    def map_tank_name(self, serial: str) -> str:
        """Maps a serial number to a friendly name, or returns the serial if not found."""
        mapping = self.get_tank_mapping()
        return mapping.get(str(serial), str(serial))


def get_config() -> ConfigManager:
    return ConfigManager()
