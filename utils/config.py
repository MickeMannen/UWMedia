import os
import yaml
from pathlib import Path
from typing import Dict, Any, Optional, List

from utils.resource_paths import find_resource

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

    def load_config(self):
        config_name = "config.yaml"
        self._config_path = find_resource(config_name, __file__)

        if self._config_path:
            try:
                with open(self._config_path, 'r') as f:
                    self._config = yaml.safe_load(f) or {}
                print(f"Loaded configuration from: {self._config_path}")
            except Exception as e:
                print(f"Error loading {config_name}: {e}")
                self._config = {}
        else:
            self._config = {}

    def save_config(self, tank_serials: List[str]):
        """Creates or overwrites config.yaml in the current directory with provided tank serials."""
        config_path = Path.cwd() / "config.yaml"
        
        config_data = {
            "tanks": {str(serial): f"Tank {serial}" for serial in sorted(tank_serials)}
        }
        
        try:
            with open(config_path, 'w') as f:
                yaml.dump(config_data, f, default_flow_style=False, sort_keys=False)
            print(f"Successfully created configuration file: {config_path}")
            self._config = config_data
            self._config_path = config_path
        except Exception as e:
            print(f"Error saving config.yaml: {e}")

    def get_tank_mapping(self) -> Dict[str, str]:
        """Returns the tank mapping (serial -> friendly name)."""
        return self._config.get("tanks", {})

    def map_tank_name(self, serial: str) -> str:
        """Maps a serial number to a friendly name, or returns the serial if not found."""
        mapping = self.get_tank_mapping()
        return mapping.get(str(serial), str(serial))


def get_config() -> ConfigManager:
    return ConfigManager()
