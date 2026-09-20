"""About page - PySide6 port of uwmedia/app.py's About-related fields/
_build_about_section and friends, see pyside6_rework.md Phase 11 - the
final page, completing every entry in SECTIONS.

Reused verbatim: _bundled_dependency_info's own logic (which binary is
actually resolved right now vs. just bundled - see its own docstring),
bundled_bin_dir/licenses_dir/get_binary_manifest/current_manifest_
platform_key (utils.resource_paths), get_ffmpeg_path/get_exiftool_path
(utils.tool_paths) - all zero-Toga-dependency engine code, eleven phases
in and still holding. Verified live that these resolve correctly from
this page's own uwmedia/pages/ nesting depth (one level deeper
than uwmedia/app.py itself) in both dev and packaged-build layouts - the
underlying find_resource() walk-up has enough max_depth budget for the
extra level.

One genuine Qt-vs-Toga difference: toga.App exposes `self.version`
directly (from Briefcase-injected app metadata). Qt has no equivalent -
this page resolves it via `importlib.metadata.version("uwmedia")`
instead (confirmed correct in both `briefcase dev` and the packaged
`.app`, which both have a real uwmedia-<version>.dist-info),
falling back to "dev" on PackageNotFoundError the same way the Toga
original falls back to "dev" when `self.version` is falsy.

One deliberate first-pass simplification: "Check for updates" calls the
GitHub releases API synchronously (`urllib.request`, 5s timeout) rather
than on a background thread - the Toga original uses
`loop.run_in_executor` to keep its own async event loop responsive
during the request. A real QThread worker would be the correct fix but
is more infrastructure than this button warrants for a first pass (same
"simple first, thread later if it matters" call already made for Tag
Editor's batch loop and Log Viewer's single-file parse) - the UI can
briefly block for up to 5s on a slow/dead connection, matching this
button's own low-frequency, user-initiated, already-slow-network-call
nature.
"""
import importlib.metadata
import json
import re
import urllib.request
import webbrowser

from PySide6 import QtWidgets

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

# (name, BINARY_MANIFEST.json key, license text filename, short license
# description, the utils.tool_paths getter that resolves which actual
# binary is in use right now) - see _bundled_dependency_info's own
# docstring for why FFmpeg/ExifTool get their own card instead of a
# plain name in ABOUT_DEPENDENCIES.
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


class AboutPage(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()
        self._wire_signals()

    # ------------------------------------------------------------------
    # Layout - ported from _build_about_section.
    # ------------------------------------------------------------------

    def _build_ui(self):
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        container = QtWidgets.QWidget()
        root = QtWidgets.QVBoxLayout(container)

        app_version = _resolve_app_version()
        uwmedia_group = QtWidgets.QGroupBox("UWMedia")
        uwmedia_layout = QtWidgets.QVBoxLayout(uwmedia_group)
        version_label = QtWidgets.QLabel(f"Version {app_version}")
        version_label.setStyleSheet("font-weight: bold;")
        uwmedia_layout.addWidget(version_label)
        description_label = QtWidgets.QLabel(
            "Underwater media processor - color correction and dive "
            "telemetry overlays for videos and photos."
        )
        description_label.setWordWrap(True)
        description_label.setStyleSheet("color: gray;")
        uwmedia_layout.addWidget(description_label)
        root.addWidget(uwmedia_group)

        updates_group = QtWidgets.QGroupBox("Updates")
        updates_layout = QtWidgets.QVBoxLayout(updates_group)
        self.check_update_button = QtWidgets.QPushButton("Check for updates")
        self.check_update_button.setFixedWidth(200)
        updates_layout.addWidget(self.check_update_button)
        self.about_update_label = QtWidgets.QLabel("")
        self.about_update_label.setWordWrap(True)
        self.about_update_label.setStyleSheet("color: gray;")
        updates_layout.addWidget(self.about_update_label)
        root.addWidget(updates_group)

        license_group = QtWidgets.QGroupBox("License")
        license_layout = QtWidgets.QVBoxLayout(license_group)
        mit_label = QtWidgets.QLabel("MIT License")
        mit_label.setStyleSheet("font-weight: bold;")
        license_layout.addWidget(mit_label)
        copyright_label = QtWidgets.QLabel(
            f"Copyright (c) 2025 {AUTHOR_NAME}. See the LICENSE file in the "
            "repository for the full text."
        )
        copyright_label.setWordWrap(True)
        copyright_label.setStyleSheet("color: gray;")
        license_layout.addWidget(copyright_label)
        root.addWidget(license_group)

        third_party_group = QtWidgets.QGroupBox("Third-Party Licenses")
        third_party_layout = QtWidgets.QVBoxLayout(third_party_group)
        intro_label = QtWidgets.QLabel(
            "UWMedia invokes these as separate external programs, not linked "
            "libraries - this does not affect UWMedia's own MIT license above."
        )
        intro_label.setWordWrap(True)
        intro_label.setStyleSheet("color: gray;")
        third_party_layout.addWidget(intro_label)
        for display_name, manifest_key, license_filename, license_desc, get_path_fn in ABOUT_THIRD_PARTY_LICENSES:
            version_line, license_path = self._bundled_dependency_info(
                display_name, manifest_key, license_filename, get_path_fn
            )
            version_label = QtWidgets.QLabel(version_line)
            version_label.setStyleSheet("font-weight: bold;")
            version_label.setWordWrap(True)
            third_party_layout.addWidget(version_label)
            if license_path:
                # Only known/shown when actually running the bundled
                # build - a local install could be a differently-
                # licensed build.
                desc_label = QtWidgets.QLabel(license_desc)
                desc_label.setWordWrap(True)
                desc_label.setStyleSheet("color: gray;")
                third_party_layout.addWidget(desc_label)
                view_button = QtWidgets.QPushButton("View license text")
                view_button.setFixedWidth(160)
                view_button.clicked.connect(lambda checked=False, p=license_path: webbrowser.open(f"file://{p}"))
                third_party_layout.addWidget(view_button)
        root.addWidget(third_party_group)

        deps_group = QtWidgets.QGroupBox("Dependencies")
        deps_layout = QtWidgets.QVBoxLayout(deps_group)
        for dep in ABOUT_DEPENDENCIES:
            dep_label = QtWidgets.QLabel(f"- {dep}")
            dep_label.setStyleSheet("color: gray;")
            deps_layout.addWidget(dep_label)
        root.addWidget(deps_group)

        links_group = QtWidgets.QGroupBox("Links")
        links_layout = QtWidgets.QVBoxLayout(links_group)
        by_label = QtWidgets.QLabel(f"By {AUTHOR_NAME}")
        links_layout.addWidget(by_label)
        links_row = QtWidgets.QHBoxLayout()
        self.github_button = QtWidgets.QPushButton("GitHub")
        links_row.addWidget(self.github_button)
        self.youtube_button = QtWidgets.QPushButton("YouTube")
        links_row.addWidget(self.youtube_button)
        links_row.addStretch(1)
        links_layout.addLayout(links_row)
        root.addWidget(links_group)

        root.addStretch(1)
        scroll.setWidget(container)
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    def _wire_signals(self):
        self.check_update_button.clicked.connect(self._on_check_for_update)
        self.github_button.clicked.connect(lambda: webbrowser.open(GITHUB_URL))
        self.youtube_button.clicked.connect(lambda: webbrowser.open(YOUTUBE_URL))

    # ------------------------------------------------------------------
    # Third-party dependency info - ported verbatim from
    # _bundled_dependency_info.
    # ------------------------------------------------------------------

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

    def _on_check_for_update(self):
        self.about_update_label.setText("Checking for updates…")
        self.about_update_label.setStyleSheet("color: gray;")
        current = _resolve_app_version() or "0.0.0"
        try:
            tag_name = self._fetch_latest_release_tag()
        except Exception:
            self.about_update_label.setText("Couldn't check for updates (no connection?).")
            return

        if not tag_name:
            self.about_update_label.setText("No releases found on GitHub yet.")
            return

        latest = tag_name.lstrip("vV")
        if self._version_tuple(latest) > self._version_tuple(current):
            self.about_update_label.setText(f"A new version is available: {tag_name} (you have {current})")
            self.about_update_label.setStyleSheet("color: #F59E0B;")
        else:
            self.about_update_label.setText(f"You're up to date ({current}).")
            self.about_update_label.setStyleSheet("color: #22C55E;")
