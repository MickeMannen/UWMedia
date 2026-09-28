import json
import os
import platform
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from platformdirs import PlatformDirs


# --- Per-user writable locations (CLAUDE.md "Desktop File System & Path
# Architecture Guidelines", 2026-09-28) ---------------------------------------
#
# Resolved through platformdirs, never spelled out:
#
#                config                        data                          cache
#   macOS    ~/Library/Application Support/org.christersson.uwmedia/   (same)   ~/Library/Caches/org.christersson.uwmedia/
#   Windows  %APPDATA%\Christersson\UWMedia\   %LOCALAPPDATA%\Christersson\UWMedia\   %LOCALAPPDATA%\Christersson\UWMedia\Cache\
#   Linux    $XDG_CONFIG_HOME/uwmedia/          $XDG_DATA_HOME/uwmedia/          $XDG_CACHE_HOME/uwmedia/
#
# config: settings.json, config.yaml, color.yaml. data: templates/, layouts/.
# cache: the temp folders a run creates (app_temp_dir). Nothing is ever
# written into the install location.
#
# Earlier versions kept everything in one folder - "org.christersson.uwmedia"
# and before that "UWMedia" - under Application Support / %APPDATA% /
# $XDG_DATA_HOME. The first time a target folder is created its contents are
# copied (not moved) from the first of those that exists; the old folder is
# left as it was so an older install keeps working.

APP_ID = "org.christersson.uwmedia"
APP_NAME = "UWMedia"
APP_AUTHOR = "Christersson"
APP_SLUG = "uwmedia"
LEGACY_DATA_DIR_NAMES = (APP_ID, "UWMedia")
# The files that belong in the config folder; everything else is data.
CONFIG_FILENAMES = ("settings.json", "config.yaml", "color.yaml")
TEMP_DIR_NAME = "tmp"
TEMP_MAX_AGE_SECONDS = 24 * 3600

# Kept for callers/tests that still refer to the old names.
APP_DATA_DIR_NAME = APP_ID
LEGACY_APP_DATA_DIR_NAME = "UWMedia"


def _platform() -> str:
    if sys.platform == "darwin":
        return "darwin"
    if sys.platform.startswith("win"):
        return "win"
    return "linux"


def _app_dirs_kwargs(plat: Optional[str] = None) -> Dict[str, Any]:
    """platformdirs naming per OS: the bundle id on macOS, Vendor/App on
    Windows, the plain slug on Linux."""
    plat = plat or _platform()
    if plat == "darwin":
        return {"appname": APP_ID, "appauthor": False}
    if plat == "win":
        return {"appname": APP_NAME, "appauthor": APP_AUTHOR}
    return {"appname": APP_SLUG, "appauthor": False}


# Environment overrides (UWMEDIA_CONFIG_DIR / UWMEDIA_DATA_DIR /
# UWMEDIA_CACHE_DIR): a portable or sandboxed install, and the test suite,
# which points them at a temp folder so a CLI run in a subprocess never
# touches the real folders either (tests/conftest.py).
ENV_CONFIG_DIR = "UWMEDIA_CONFIG_DIR"
ENV_DATA_DIR = "UWMEDIA_DATA_DIR"
ENV_CACHE_DIR = "UWMEDIA_CACHE_DIR"


def _env_dir(name: str) -> Optional[Path]:
    value = os.environ.get(name, "").strip()
    return Path(value).expanduser() if value else None


def _config_base() -> Path:
    return _env_dir(ENV_CONFIG_DIR) or Path(PlatformDirs(roaming=True, **_app_dirs_kwargs()).user_config_dir)


def _data_base() -> Path:
    return _env_dir(ENV_DATA_DIR) or Path(PlatformDirs(**_app_dirs_kwargs()).user_data_dir)


def _cache_base() -> Path:
    return _env_dir(ENV_CACHE_DIR) or Path(PlatformDirs(**_app_dirs_kwargs()).user_cache_dir)


def _legacy_data_base() -> Path:
    """Where the single pre-split folder lived."""
    plat = _platform()
    if plat == "darwin":
        return Path.home() / "Library" / "Application Support"
    if plat == "win":
        return Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
    return Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share")))


def _legacy_dirs(target: Path) -> List[Path]:
    base = _legacy_data_base()
    return [base / name for name in LEGACY_DATA_DIR_NAMES if (base / name) != target]


def _is_config_entry(entry: Path) -> bool:
    return entry.is_file() and entry.name in CONFIG_FILENAMES


def _ensure_dir(target: Path, select) -> Path:
    """Create `target`, first copying the entries `select` accepts from the
    first legacy folder that exists. A failed copy is rolled back to an
    empty folder rather than left half done."""
    if not target.exists():
        for legacy in _legacy_dirs(target):
            if legacy.is_dir():
                _copy_entries(legacy, target, select)
                break
    target.mkdir(parents=True, exist_ok=True)
    return target


def _copy_entries(legacy: Path, target: Path, select) -> None:
    try:
        target.mkdir(parents=True, exist_ok=True)
        for entry in sorted(legacy.iterdir()):
            if select is not None and not select(entry):
                continue
            if entry.is_dir():
                shutil.copytree(entry, target / entry.name)
            else:
                shutil.copy2(entry, target / entry.name)
    except Exception as e:
        print(f"Could not migrate {legacy} to {target}: {e}")
        shutil.rmtree(target, ignore_errors=True)


def user_config_dir() -> Path:
    """settings.json, config.yaml, color.yaml (see the table above)."""
    target = _config_base()
    # On macOS config and data are one folder: migrate everything together.
    select = None if target == _data_base() else _is_config_entry
    return _ensure_dir(target, select)


def user_data_dir() -> Path:
    """templates/, layouts/ and any other user data (see the table above).
    Standalone so non-GUI code (cli_main.py, ffmpeg/color.py) can use it."""
    target = _data_base()
    select = None if target == _config_base() else (lambda e: not _is_config_entry(e))
    return _ensure_dir(target, select)


def user_cache_dir() -> Path:
    path = _cache_base()
    path.mkdir(parents=True, exist_ok=True)
    return path


def app_temp_dir(prefix: str = "uwmedia_") -> Path:
    """A fresh working folder under the cache directory (rendered overlays,
    LUTs, overlays.json for a run…) instead of the system temp dir. Callers
    that finish cleanly remove it; prune_temp_dirs() sweeps the rest."""
    base = user_cache_dir() / TEMP_DIR_NAME
    base.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=prefix, dir=base))


def prune_temp_dirs(max_age_seconds: float = TEMP_MAX_AGE_SECONDS) -> int:
    """Remove app_temp_dir() folders older than `max_age_seconds` (a day by
    default); called at startup. Returns how many were removed."""
    base = _cache_base() / TEMP_DIR_NAME
    if not base.is_dir():
        return 0
    cutoff = time.time() - max_age_seconds
    removed = 0
    for entry in base.iterdir():
        try:
            if entry.stat().st_mtime < cutoff:
                shutil.rmtree(entry, ignore_errors=True) if entry.is_dir() else entry.unlink()
                removed += 1
        except OSError:
            continue
    return removed


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
