"""The per-user folders in utils/resource_paths.py (CLAUDE.md path
guidelines): config / data / cache resolved through platformdirs, the
one-time copy from the old single folder ("org.christersson.uwmedia", and
"UWMedia" before it), and the temp folders under the cache dir. Every base
is patched to tmp_path so nothing touches the real Application Support /
%APPDATA% / ~/.local/share tree."""
import os
import time

import pytest

import utils.resource_paths as rp


@pytest.fixture
def split(tmp_path, monkeypatch):
    """Windows/Linux shape: config, data and cache are three folders; the
    old single folder lived under `legacy`."""
    monkeypatch.setattr(rp, "_config_base", lambda: tmp_path / "config" / "uwmedia")
    monkeypatch.setattr(rp, "_data_base", lambda: tmp_path / "data" / "uwmedia")
    monkeypatch.setattr(rp, "_cache_base", lambda: tmp_path / "cache" / "uwmedia")
    monkeypatch.setattr(rp, "_legacy_data_base", lambda: tmp_path / "data")
    return tmp_path


@pytest.fixture
def shared(tmp_path, monkeypatch):
    """macOS shape: config and data are the same folder, next to the legacy ones."""
    base = tmp_path / "Application Support"
    monkeypatch.setattr(rp, "_config_base", lambda: base / rp.APP_ID)
    monkeypatch.setattr(rp, "_data_base", lambda: base / rp.APP_ID)
    monkeypatch.setattr(rp, "_cache_base", lambda: tmp_path / "Caches" / rp.APP_ID)
    monkeypatch.setattr(rp, "_legacy_data_base", lambda: base)
    return base


def _fill_legacy(legacy):
    (legacy / "templates").mkdir(parents=True)
    (legacy / "layouts").mkdir()
    (legacy / "settings.json").write_text('{"a": 1}')
    (legacy / "color.yaml").write_text("profiles: {}")
    (legacy / "templates" / "t.json").write_text("{}")


def test_platform_naming():
    assert rp._app_dirs_kwargs("darwin") == {"appname": "org.christersson.uwmedia", "appauthor": False}
    assert rp._app_dirs_kwargs("win") == {"appname": "UWMedia", "appauthor": "Christersson"}
    assert rp._app_dirs_kwargs("linux") == {"appname": "uwmedia", "appauthor": False}


def test_split_layout_creates_three_folders(split):
    assert rp.user_config_dir() == split / "config" / "uwmedia"
    assert rp.user_data_dir() == split / "data" / "uwmedia"
    assert rp.user_cache_dir() == split / "cache" / "uwmedia"
    for d in (rp.user_config_dir(), rp.user_data_dir(), rp.user_cache_dir()):
        assert d.is_dir()


def test_split_migration_sorts_config_files_from_data(split):
    legacy = split / "data" / rp.APP_ID
    _fill_legacy(legacy)

    config, data = rp.user_config_dir(), rp.user_data_dir()

    assert (config / "settings.json").read_text() == '{"a": 1}'
    assert (config / "color.yaml").exists()
    assert not (config / "templates").exists()
    assert (data / "templates" / "t.json").exists()
    assert (data / "layouts").is_dir()
    assert not (data / "settings.json").exists()
    # the old folder is left as it was
    assert (legacy / "settings.json").exists() and (legacy / "templates" / "t.json").exists()


def test_older_uwmedia_folder_is_the_fallback_source(split):
    _fill_legacy(split / "data" / "UWMedia")
    assert (rp.user_config_dir() / "settings.json").read_text() == '{"a": 1}'
    assert (rp.user_data_dir() / "templates" / "t.json").exists()


def test_shared_layout_migrates_everything_from_uwmedia_folder(shared):
    _fill_legacy(shared / "UWMedia")
    path = rp.user_config_dir()
    assert path == rp.user_data_dir() == shared / rp.APP_ID
    assert (path / "settings.json").read_text() == '{"a": 1}'
    assert (path / "templates" / "t.json").exists()
    # Once the new folder exists, later changes to the legacy one are ignored.
    (shared / "UWMedia" / "settings.json").write_text('{"a": 2}')
    rp.user_data_dir()
    assert (path / "settings.json").read_text() == '{"a": 1}'


def test_existing_target_is_not_overwritten(shared):
    (shared / "UWMedia").mkdir(parents=True)
    (shared / "UWMedia" / "settings.json").write_text("old")
    (shared / rp.APP_ID).mkdir()
    rp.user_config_dir()
    assert not (shared / rp.APP_ID / "settings.json").exists()


def test_failed_copy_leaves_empty_new_folder(split, monkeypatch):
    _fill_legacy(split / "data" / rp.APP_ID)

    def boom(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(rp.shutil, "copytree", boom)
    data = rp.user_data_dir()
    assert data.is_dir() and list(data.iterdir()) == []


def test_temp_dirs_live_under_cache_and_old_ones_are_pruned(split):
    fresh = rp.app_temp_dir("uwmedia_test_")
    assert fresh.is_dir() and fresh.parent == rp.user_cache_dir() / rp.TEMP_DIR_NAME
    assert fresh.name.startswith("uwmedia_test_")
    stale = rp.app_temp_dir("uwmedia_stale_")
    old = time.time() - 3 * 24 * 3600
    os.utime(stale, (old, old))
    assert rp.prune_temp_dirs() == 1
    assert fresh.is_dir() and not stale.exists()


def test_environment_overrides_win(tmp_path, monkeypatch):
    monkeypatch.setenv(rp.ENV_CONFIG_DIR, str(tmp_path / "c"))
    monkeypatch.setenv(rp.ENV_DATA_DIR, str(tmp_path / "d"))
    monkeypatch.setenv(rp.ENV_CACHE_DIR, str(tmp_path / "k"))
    assert rp.user_config_dir() == tmp_path / "c"
    assert rp.user_data_dir() == tmp_path / "d"
    assert rp.app_temp_dir("x_").parent == tmp_path / "k" / rp.TEMP_DIR_NAME
