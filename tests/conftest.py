"""Shared fixtures. `isolated_template_roots` gives a test its own copy of the
bundled overlays/templates tree plus an empty user templates dir, patched
into both utils.layouts and utils.template_store, so persistence tests never
touch the real repo files or the real ~/Library/Application Support tree
(CLAUDE.md rule: never write outside the repo/scratch)."""
import shutil
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


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
