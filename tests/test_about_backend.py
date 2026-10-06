"""
The About page backend (uwmedia/backends/about_backend.py): the version
compare and "Check for updates" (the GitHub request is stubbed, nothing goes
on the network) and the FFmpeg / ExifTool lines for a bundled, a local and a
missing tool.
"""

import pytest

import uwmedia.backends.about_backend as ab
from uwmedia.backends.about_backend import AboutBackend


@pytest.fixture
def backend(settings_file):
    return AboutBackend()


@pytest.mark.parametrize("value, expected", [
    ("v0.7.13", (0, 7, 13)),
    ("0.7.13-beta", (0, 7, 13)),
    ("V1.2", (1, 2)),
    ("dev", ()),
])
def test_version_tuple(value, expected):
    assert AboutBackend._version_tuple(value) == expected


@pytest.mark.parametrize("latest, text, color", [
    ("v0.8.0", "A new version is available: v0.8.0 (you have 0.7.13)", "#F59E0B"),
    ("v0.7.13", "You're up to date (0.7.13).", "#22C55E"),
    ("v0.7.9", "You're up to date (0.7.13).", "#22C55E"),  # 13 > 9, not a string compare
    (None, "No releases found on GitHub yet.", "#9AA0A6"),
])
def test_check_for_update(backend, monkeypatch, latest, text, color):
    monkeypatch.setattr(ab, "_resolve_app_version", lambda: "0.7.13")
    monkeypatch.setattr(AboutBackend, "_fetch_latest_release_tag", staticmethod(lambda: latest))
    seen = []
    backend.updateStateChanged.connect(lambda: seen.append(backend.updateText))
    backend.checkForUpdate()
    assert seen[0] == "Checking for updates…"
    assert backend.updateText == text
    assert backend.updateColor == color


def test_check_for_update_offline(backend, monkeypatch):
    def offline():
        raise OSError("no network")
    monkeypatch.setattr(AboutBackend, "_fetch_latest_release_tag", staticmethod(offline))
    backend.checkForUpdate()
    assert backend.updateText == "Couldn't check for updates (no connection?)."


def test_static_page_data(backend):
    assert backend.authorName == ab.AUTHOR_NAME
    assert backend.dependencies == ab.ABOUT_DEPENDENCIES
    assert backend.appVersion  # "dev" in a checkout without an installed package
    rows = backend.thirdPartyLicenses
    assert [r["versionLine"].split(" ")[0] for r in rows] == ["FFmpeg", "ExifTool"]


def test_dependency_line_for_a_local_install(backend, tmp_path):
    local = tmp_path / "ffmpeg"
    line, license_path = backend._bundled_dependency_info("FFmpeg", "ffmpeg", "FFMPEG_LICENSE.txt", lambda: local)
    assert line == f"FFmpeg — using local install ({local})"
    assert license_path is None


def test_dependency_line_for_a_missing_tool(backend):
    line, license_path = backend._bundled_dependency_info("ExifTool", "exiftool", "EXIFTOOL_LICENSE.txt", lambda: None)
    assert line == "ExifTool — not found"
    assert license_path is None


def test_dependency_line_for_a_bundled_tool(backend, monkeypatch, tmp_path):
    bin_dir = tmp_path / "bin_test"
    bin_dir.mkdir()
    lic_dir = tmp_path / "licenses"
    lic_dir.mkdir()
    (lic_dir / "EXIFTOOL_LICENSE.txt").write_text("license")
    manifest = {"exiftool": {"platforms": {"testos": {"version": "13.10",
                                                      "runtime_requirement": "system perl 5"}}}}
    monkeypatch.setattr(ab, "bundled_bin_dir", lambda _f: bin_dir)
    monkeypatch.setattr(ab, "licenses_dir", lambda _f: lic_dir)
    monkeypatch.setattr(ab, "get_binary_manifest", lambda _f: manifest)
    monkeypatch.setattr(ab, "current_manifest_platform_key", lambda: "testos")
    line, license_path = backend._bundled_dependency_info(
        "ExifTool", "exiftool", "EXIFTOOL_LICENSE.txt", lambda: bin_dir / "exiftool")
    assert line == "ExifTool 13.10 — packaged with this app, via system Perl"
    assert license_path == lic_dir / "EXIFTOOL_LICENSE.txt"
