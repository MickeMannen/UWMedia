"""utils/config.py: config.yaml with the tank serial -> name mapping. The
user's copy in the config folder (a tmp folder, conftest) wins over a
checkout's legacy one; every change is written to the user's copy."""
import pytest
import yaml

import utils.config as config


@pytest.fixture
def fresh(tmp_path, monkeypatch):
    """A new ConfigManager each test (it is a singleton) and no legacy file."""
    monkeypatch.setattr(config.ConfigManager, "_instance", None)
    monkeypatch.setattr(config, "bundled_config_yaml_path", lambda: None)
    return config.user_config_yaml_path()


def _read(path):
    return yaml.safe_load(path.read_text())


def test_nothing_to_load(fresh):
    cfg = config.get_config()
    assert not cfg.is_loaded()
    assert cfg.get_tank_mapping() == {}
    assert cfg.map_tank_name("123") == "123"
    assert config.get_config() is cfg


def test_user_file_wins_over_legacy(fresh, tmp_path, monkeypatch):
    legacy = tmp_path / "legacy_config.yaml"
    legacy.write_text("tanks: {'1': Legacy}")
    monkeypatch.setattr(config, "bundled_config_yaml_path", lambda: legacy)
    assert config.get_config().map_tank_name("1") == "Legacy"

    monkeypatch.setattr(config.ConfigManager, "_instance", None)
    fresh.write_text("tanks: {'1': Mine}")
    cfg = config.get_config()
    assert cfg.is_loaded() and cfg.map_tank_name(1) == "Mine"


def test_save_adds_new_serials_and_keeps_names(fresh):
    fresh.write_text("tanks: {'200': Left}\nother: kept\n")
    config.get_config().save_config(["300", 200, "100"])
    data = _read(fresh)
    assert data["tanks"] == {"100": "Tank 100", "200": "Left", "300": "Tank 300"}
    assert list(data["tanks"]) == ["100", "200", "300"]
    assert data["other"] == "kept"


def test_rename_and_remove_write_through(fresh):
    cfg = config.get_config()
    cfg.set_tank_name(555, "Stage")
    assert _read(fresh)["tanks"] == {"555": "Stage"}
    assert cfg.is_loaded()

    cfg.remove_tank("555")
    cfg.remove_tank("never-there")
    assert _read(fresh)["tanks"] == {}


def test_broken_yaml_loads_as_empty(fresh, capsys):
    fresh.write_text("tanks: [unclosed")
    assert config.get_config().get_tank_mapping() == {}
    assert "Error loading" in capsys.readouterr().out
