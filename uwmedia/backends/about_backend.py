"""About page backend - qml_development.md Phase 11 (final page). QObject
exposed to uwmedia/qml/AboutPage.qml as the "aboutBackend"
context property.

Ported close to verbatim from uwmedia/pages/about_page.py (the
old Widgets page, kept as reference only). Reuses the same zero-Toga-
dependency engine code that page already verified live from this same
uwmedia/*/ nesting depth: _bundled_dependency_info's own logic,
bundled_bin_dir/licenses_dir/get_binary_manifest/
current_manifest_platform_key (utils.resource_paths), get_ffmpeg_path/
get_exiftool_path (utils.tool_paths) - this backend lives at
uwmedia/backends/about_backend.py, the same one-level-under-
uwmedia/ depth as the old page, so find_resource()'s walk-up
resolves identically.

Same genuine Qt-vs-Toga difference as the old page: app version comes
from importlib.metadata.version("uwmedia") (falls back to "dev"),
not toga.App's Briefcase-injected self.version.

Same deliberate first-pass simplification: "Check for updates" calls the
GitHub releases API synchronously (urllib.request, 5s timeout) rather
than on a background thread - can briefly block the UI on a slow/dead
connection, matching the old page's own documented trade-off.

Third-party license text and GitHub/YouTube links open via
QDesktopServices.openUrl (Qt's own webbrowser.open equivalent) instead of
Python's webbrowser module - same effect (hands off to the OS), more in
keeping with the rest of this QML port's own QtWidgets/QtGui usage.
"""
import importlib.metadata
import json
import re
import urllib.request

from PySide6.QtCore import Property, QObject, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices

from utils.resource_paths import (
    bundled_bin_dir,
    current_manifest_platform_key,
    get_binary_manifest,
    licenses_dir,
)
from utils.tool_paths import get_exiftool_path, get_ffmpeg_path

AUTHOR_NAME = "Mikael Christersson"
GITHUB_REPO = "MickeMannen/UWMedia"
GITHUB_URL = f"https://github.com/{GITHUB_REPO}"
YOUTUBE_URL = "https://www.youtube.com/@MickeMannen8"

ABOUT_DEPENDENCIES = [
    "Briefcase (packaging)",
    "garmin-fit-sdk",
]

ABOUT_THIRD_PARTY_LICENSES = [
    (
        "FFmpeg",
        "ffmpeg",
        "FFMPEG_LICENSE.txt",
        "GPL v3 or later (bundled build includes libx264/libx265 for HEVC)",
        get_ffmpeg_path,
    ),
    (
        "ExifTool",
        "exiftool",
        "EXIFTOOL_LICENSE.txt",
        "GPL / Perl Artistic License (dual - upstream's choice of terms)",
        get_exiftool_path,
    ),
]


def _resolve_app_version():
    try:
        return importlib.metadata.version("uwmedia")
    except importlib.metadata.PackageNotFoundError:
        return "dev"


class AboutBackend(QObject):
    updateStateChanged = Signal()

    def __init__(self):
        super().__init__()
        self._update_text = ""
        self._update_color = "#9AA0A6"

    # ------------------------------------------------------------------
    # Static display data - read once, no notify signal needed (nothing
    # here changes after construction).
    # ------------------------------------------------------------------

    @Property(str, constant=True)
    def appVersion(self):
        return _resolve_app_version()

    @Property(str, constant=True)
    def authorName(self):
        return AUTHOR_NAME

    @Property("QVariant", constant=True)
    def dependencies(self):
        return list(ABOUT_DEPENDENCIES)

    @Property("QVariant", constant=True)
    def thirdPartyLicenses(self):
        rows = []
        for display_name, manifest_key, license_filename, license_desc, get_path_fn in ABOUT_THIRD_PARTY_LICENSES:
            version_line, license_path = self._bundled_dependency_info(
                display_name, manifest_key, license_filename, get_path_fn
            )
            rows.append({
                "versionLine": version_line,
                "licenseDesc": license_desc if license_path else "",
                "licensePath": str(license_path) if license_path else "",
            })
        return rows

    def _bundled_dependency_info(self, display_name, manifest_key, license_filename, get_path_fn):
        resolved_path = get_path_fn()
        bin_dir = bundled_bin_dir(__file__)
        is_bundled = bool(resolved_path and bin_dir and resolved_path.parent == bin_dir)

        license_path = None
        if is_bundled:
            lic_dir = licenses_dir(__file__)
            candidate = lic_dir / license_filename if lic_dir else None
            if candidate and candidate.exists():
                license_path = candidate

        version = None
        runtime_note = ""
        if is_bundled:
            manifest = get_binary_manifest(__file__)
            plat_key = current_manifest_platform_key()
            if manifest and plat_key:
                entry = manifest.get(manifest_key, {}).get("platforms", {}).get(plat_key)
                if entry:
                    version = entry.get("version")
                    if "system perl" in entry.get("runtime_requirement", ""):
                        runtime_note = ", via system Perl"

        if is_bundled:
            version_part = f" {version}" if version else ""
            line = f"{display_name}{version_part} — packaged with this app{runtime_note}"
        elif resolved_path:
            line = f"{display_name} — using local install ({resolved_path})"
        else:
            line = f"{display_name} — not found"

        return line, license_path

    @Slot(str)
    def openLicense(self, path):
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    @Slot()
    def openGithub(self):
        QDesktopServices.openUrl(QUrl(GITHUB_URL))

    @Slot()
    def openYoutube(self):
        QDesktopServices.openUrl(QUrl(YOUTUBE_URL))

    # ------------------------------------------------------------------
    # Update check - ported from on_check_for_update/_check_for_update/
    # _fetch_latest_release_tag/_version_tuple.
    # ------------------------------------------------------------------

    @staticmethod
    def _version_tuple(value):
        parts = []
        for chunk in re.split(r"[.\-+]", value.lstrip("vV")):
            try:
                parts.append(int(chunk))
            except ValueError:
                break
        return tuple(parts)

    @staticmethod
    def _fetch_latest_release_tag():
        req = urllib.request.Request(
            f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest",
            headers={"Accept": "application/vnd.github+json"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
        return data.get("tag_name")

    @Property(str, notify=updateStateChanged)
    def updateText(self):
        return self._update_text

    @Property(str, notify=updateStateChanged)
    def updateColor(self):
        return self._update_color

    @Slot()
    def checkForUpdate(self):
        self._update_text = "Checking for updates…"
        self._update_color = "#9AA0A6"
        self.updateStateChanged.emit()

        current = _resolve_app_version() or "0.0.0"
        try:
            tag_name = self._fetch_latest_release_tag()
        except Exception:
            self._update_text = "Couldn't check for updates (no connection?)."
            self.updateStateChanged.emit()
            return

        if not tag_name:
            self._update_text = "No releases found on GitHub yet."
            self.updateStateChanged.emit()
            return

        latest = tag_name.lstrip("vV")
        if self._version_tuple(latest) > self._version_tuple(current):
            self._update_text = f"A new version is available: {tag_name} (you have {current})"
            self._update_color = "#F59E0B"
        else:
            self._update_text = f"You're up to date ({current})."
            self._update_color = "#22C55E"
        self.updateStateChanged.emit()
