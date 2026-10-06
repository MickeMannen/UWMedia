"""Shared fixtures. `isolated_template_roots` gives a test its own copy of the
bundled overlays/templates tree plus an empty user templates dir, patched
into both utils.layouts and utils.template_store, so persistence tests never
touch the real repo files or the real ~/Library/Application Support tree
(CLAUDE.md rule: never write outside the repo/scratch).

Also the shared paths and helpers for tests that use the local test media:
TEST_DATA (git-ignored, so absent on a fresh clone or in CI; the
UWMEDIA_TEST_DATA environment variable points it elsewhere) and run_cli()."""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import utils.app_settings as app_settings

REPO_ROOT = Path(__file__).resolve().parent.parent
TEST_DATA = Path(os.environ.get("UWMEDIA_TEST_DATA") or REPO_ROOT / "test_data")
RELEASE_MEDIA = TEST_DATA / "release_test"
LOGS_DIR = TEST_DATA / "logs"
# Markers whose tests read TEST_DATA - skipped when it is missing.
MEDIA_MARKERS = ("requires_media", "render", "release")


def run_cli(*args):
    """cli_main.py in a subprocess with this interpreter (not whatever
    `python3` is on PATH), from the repo root, output captured."""
    return subprocess.run([sys.executable, str(REPO_ROOT / "cli_main.py"), *map(str, args)],
                          capture_output=True, text=True, cwd=REPO_ROOT)


def pytest_collection_modifyitems(config, items):
    if TEST_DATA.is_dir():
        return
    skip = pytest.mark.skip(reason=f"needs the local test media in {TEST_DATA} (not in git)")
    for item in items:
        if any(item.get_closest_marker(name) for name in MEDIA_MARKERS):
            item.add_marker(skip)


@pytest.fixture
def isolated_template_roots(tmp_path, monkeypatch):
    import utils.layouts as layouts
    import utils.template_store as store

    bundled = tmp_path / "repo" / "overlays" / "templates"
    shutil.copytree(REPO_ROOT / "overlays" / "templates", bundled)
    user = tmp_path / "user_templates"
    user.mkdir()

    monkeypatch.setattr(layouts, "bundled_templates_dir", lambda: bundled)
    monkeypatch.setattr(layouts, "user_templates_dir", lambda: user)
    monkeypatch.setattr(store, "bundled_templates_dir", lambda: bundled)
    monkeypatch.setattr(store, "user_templates_dir", lambda: user)
    monkeypatch.delenv(store.ENV_TARGET, raising=False)
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    # The copied tree has no .git/pyproject.toml beside it -> "release" mode
    # unless a test marks it as a checkout or sets the env override.
    return {"bundled": bundled, "user": user, "repo": tmp_path / "repo"}


def mark_as_checkout(roots):
    (roots["repo"] / ".git").mkdir(exist_ok=True)
    (roots["repo"] / "pyproject.toml").write_text("[tool.briefcase]\n")


@pytest.fixture(autouse=True)
def _isolated_user_dirs(tmp_path, monkeypatch):
    """Every test gets its own config / data / cache folders (CLAUDE.md rule:
    never write the real Application Support / Caches tree). ffmpeg/color.py
    and the backends put their working folders under the cache dir, so
    without this a render test would create ~/Library/Caches/... for real."""
    import utils.resource_paths as rp

    # The env overrides also reach a CLI run in a subprocess, which inherits them.
    monkeypatch.setattr(rp, "_legacy_data_base", lambda: tmp_path / "legacy_base")
    monkeypatch.setenv(rp.ENV_CONFIG_DIR, str(tmp_path / "user_config"))
    monkeypatch.setenv(rp.ENV_DATA_DIR, str(tmp_path / "user_data"))
    monkeypatch.setenv(rp.ENV_CACHE_DIR, str(tmp_path / "user_cache"))


@pytest.fixture
def settings_file(tmp_path, monkeypatch):
    """A throwaway settings.json for backends that persist form fields
    (CLAUDE.md rule: never write the real Application Support one)."""
    path = tmp_path / "settings.json"
    monkeypatch.setattr(app_settings, "settings_path", lambda: path)
    return path
