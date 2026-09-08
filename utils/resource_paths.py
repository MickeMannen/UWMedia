import json
import os
import platform
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Union


def user_data_dir(app_name: str = "UWMedia") -> Path:
    """
    Per-OS, per-user writable data directory for the app - the same location
    Toga's `app.paths.data` reports, computed standalone so non-GUI code
    (cli_main.py, ffmpeg/color.py) can use it without a toga.App instance.

    User-editable resources (custom HUD layouts, custom color profiles,
    settings) live here so they survive app reinstalls/updates, unlike
    anything under the bundled, effectively read-only install location.
    """
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    elif sys.platform.startswith("win"):
        base = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share")))
    path = base / app_name
    path.mkdir(parents=True, exist_ok=True)
    return path


def find_resource(filename: str, start: Union[str, Path], max_depth: int = 3) -> Optional[Path]:
    """
    Locate a bundled resource file (e.g. color.yaml, hud_rules.json, config.yaml)
    across every way this project gets run: from source, as a PyInstaller
    onefile bundle, or as a Briefcase-packaged app.

    `start` should be the caller's `__file__`. PyInstaller bundles set
    `sys.frozen`/`sys._MEIPASS`, which point straight at the bundle root.
    Briefcase sets neither - it copies each `sources` entry as a sibling
    directory under the app's install root, so the file is found by walking
    up from the calling module (this also covers running directly from a
    source checkout, since the project root is just a few parents up).
    """
    candidates = [Path.cwd() / filename]

    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).parent / filename)
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(Path(meipass) / filename)

    directory = Path(start).resolve().parent
    for _ in range(max_depth):
        candidates.append(directory / filename)
        directory = directory.parent

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


# Each of these is a top-level `sources` entry in pyproject.toml
# (resources/bin_macos, resources/bin_windows, resources/bin_linux) - named
# with a "bin_" prefix rather than just "macos"/"windows"/"linux" because
# Briefcase bundles every `sources` entry as a sibling directory named after
# its *basename only* (verified empirically: "resources/bin_macos" lands at
# Contents/Resources/app/bin_macos, not resources/bin_macos), so a bare
# "macos" would be an oddly generic, collision-prone name to go looking for
# with find_resource().
_PLATFORM_BIN_DIRS = {
    "Darwin": "bin_macos",
    "Windows": "bin_windows",
    "Linux": "bin_linux",
}


# Matches the "platforms" keys used in resources/licenses/BINARY_MANIFEST.json,
# which are lowercase OS names rather than platform.system()'s Darwin/Windows/Linux.
_MANIFEST_PLATFORM_KEYS = {
    "Darwin": "macos",
    "Windows": "windows",
    "Linux": "linux",
}


def current_manifest_platform_key() -> Optional[str]:
    """The BINARY_MANIFEST.json "platforms" key for the current OS, or None."""
    return _MANIFEST_PLATFORM_KEYS.get(platform.system())


def bundled_bin_dir(start: Union[str, Path]) -> Optional[Path]:
    """
    Locate this platform's vendored ffmpeg/ffprobe/exiftool directory (see
    solve_dependencies.md and resources/licenses/BINARY_MANIFEST.json for
    what's in it and where it came from), the same way find_resource()
    locates any other bundled resource.

    Only present in a Briefcase-packaged build. Returns None when running
    from a source checkout (nothing to find) or on a platform.system() we
    don't vendor binaries for - callers should fall back to PATH/system
    installs in that case, which is also exactly what running from source
    does today.
    """
    dirname = _PLATFORM_BIN_DIRS.get(platform.system())
    if not dirname:
        return None
    found = find_resource(dirname, start, max_depth=4)
    return found if found and found.is_dir() else None


def licenses_dir(start: Union[str, Path]) -> Optional[Path]:
    """
    Locate the bundled `resources/licenses` directory (BINARY_MANIFEST.json
    plus the ffmpeg/exiftool/GPL license text) - `resources/licenses` is a
    shared top-level `sources` entry in pyproject.toml, so like
    bundled_bin_dir() this is only present in a packaged build.
    """
    found = find_resource("licenses", start, max_depth=4)
    return found if found and found.is_dir() else None


def get_binary_manifest(start: Union[str, Path]) -> Optional[Dict[str, Any]]:
    """
    Parsed contents of the bundled BINARY_MANIFEST.json (vendored ffmpeg/
    exiftool versions, sources, checksums - see solve_dependencies.md),
    for the About screen to read version strings from.

    Returns None in source-run mode (nothing bundled to read) or if the
    file is somehow missing/corrupt - callers should treat that as "no
    bundled version info available" rather than an error.
    """
    directory = licenses_dir(start)
    if not directory:
        return None
    manifest_path = directory / "BINARY_MANIFEST.json"
    try:
        with open(manifest_path, "r") as f:
            return json.load(f)
    except Exception:
        return None
