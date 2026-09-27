"""user_data_dir() naming and the one-time copy from the legacy "UWMedia"
folder. The per-OS base is patched to tmp_path so nothing here touches the
real Application Support / %APPDATA% / ~/.local/share tree."""
import pytest

import utils.resource_paths as rp


@pytest.fixture
def base(tmp_path, monkeypatch):
    monkeypatch.setattr(rp, "_user_data_base", lambda: tmp_path)
    return tmp_path


def test_uses_reverse_dns_folder_name(base):
    path = rp.user_data_dir()
    assert path == base / "org.christersson.uwmedia"
    assert path.is_dir()


def test_copies_legacy_folder_once_and_keeps_original(base):
    legacy = base / "UWMedia"
    (legacy / "templates").mkdir(parents=True)
    (legacy / "settings.json").write_text('{"a": 1}')
    (legacy / "templates" / "t.json").write_text("{}")

    path = rp.user_data_dir()

    assert (path / "settings.json").read_text() == '{"a": 1}'
    assert (path / "templates" / "t.json").exists()
    assert (legacy / "settings.json").exists()

    # Once the new folder exists, later changes to the legacy one are ignored.
    (legacy / "settings.json").write_text('{"a": 2}')
    rp.user_data_dir()
    assert (path / "settings.json").read_text() == '{"a": 1}'


def test_existing_new_folder_is_not_overwritten(base):
    (base / "UWMedia").mkdir()
    (base / "UWMedia" / "settings.json").write_text("old")
    new = base / "org.christersson.uwmedia"
    new.mkdir()

    rp.user_data_dir()

    assert not (new / "settings.json").exists()


def test_failed_copy_leaves_empty_new_folder(base, monkeypatch):
    (base / "UWMedia").mkdir()
    (base / "UWMedia" / "settings.json").write_text("old")

    def boom(src, dst):
        dst.mkdir()
        (dst / "partial").write_text("x")
        raise OSError("disk full")

    monkeypatch.setattr(rp.shutil, "copytree", boom)
    path = rp.user_data_dir()

    assert path.is_dir()
    assert list(path.iterdir()) == []
