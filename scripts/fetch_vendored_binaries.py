#!/usr/bin/env python3
"""
Downloads this platform's vendored ffmpeg/ffprobe/exiftool from the
project's "deps" GitHub release into resources/bin_<platform>/, verifying
each file's sha256 against resources/licenses/BINARY_MANIFEST.json before
use rather than trusting the download blindly.

Run before `briefcase create`/`briefcase build` - Briefcase's per-platform
`sources` entries only bundle whatever's already on disk under
resources/bin_<platform>/ at that point. See solve_dependencies.md for how
these binaries were originally vendored and why they live in a dedicated
GitHub release rather than git history or a live third-party URL.

The destination filenames matter: utils/dependency_check.py looks for
exactly "ffmpeg"/"ffprobe"/"exiftool" (plus ".exe" on Windows), so this
script renames archive contents to match (e.g. ExifTool's Windows package
ships "exiftool(-k).exe", which gets renamed to "exiftool.exe" here).
"""
import hashlib
import json
import os
import platform
import shutil
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = REPO_ROOT / "resources" / "licenses" / "BINARY_MANIFEST.json"

PLATFORM_KEYS = {"Darwin": "macos", "Windows": "windows", "Linux": "linux"}
BIN_DIRNAMES = {"Darwin": "bin_macos", "Windows": "bin_windows", "Linux": "bin_linux"}


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url: str, dest: Path) -> None:
    print(f"Downloading {url}")
    with urllib.request.urlopen(url) as resp, open(dest, "wb") as out:
        shutil.copyfileobj(resp, out)


def verify(path: Path, expected_sha256: str) -> None:
    actual = sha256_of(path)
    if actual != expected_sha256:
        sys.exit(
            f"CHECKSUM MISMATCH for {path.name}:\n"
            f"  expected {expected_sha256}\n"
            f"  actual   {actual}\n"
            "Refusing to use this file - the deps release asset may have "
            "changed or been corrupted in transit."
        )
    print(f"  sha256 OK: {path.name}")


def fetch_asset(release_url_base: str, asset_name: str, expected_sha256: str, dest_dir: Path) -> Path:
    dest = dest_dir / asset_name
    download(f"{release_url_base}/{asset_name}", dest)
    verify(dest, expected_sha256)
    return dest


def replace(src: Path, dest: Path) -> None:
    if dest.exists():
        if dest.is_dir():
            shutil.rmtree(dest)
        else:
            dest.unlink()
    shutil.move(str(src), str(dest))


def main() -> None:
    system = platform.system()
    plat_key = PLATFORM_KEYS.get(system)
    bin_dirname = BIN_DIRNAMES.get(system)
    if not plat_key:
        sys.exit(f"Unsupported platform.system(): {system}")

    manifest = json.loads(MANIFEST_PATH.read_text())
    repo = os.environ.get("GITHUB_REPOSITORY", "MickeMannen/UWMedia")
    release_url_base = f"https://github.com/{repo}/releases/download/{manifest['deps_release_tag']}"

    bin_dir = REPO_ROOT / "resources" / bin_dirname
    bin_dir.mkdir(parents=True, exist_ok=True)
    exe_suffix = ".exe" if system == "Windows" else ""

    # --- ffmpeg + ffprobe: plain binaries, just need the right filename ---
    ffmpeg_entry = manifest["ffmpeg"]["platforms"][plat_key]
    ffmpeg_download = fetch_asset(release_url_base, ffmpeg_entry["asset"], ffmpeg_entry["sha256"], bin_dir)
    replace(ffmpeg_download, bin_dir / f"ffmpeg{exe_suffix}")

    ffprobe_download = fetch_asset(
        release_url_base, ffmpeg_entry["ffprobe_asset"], ffmpeg_entry["ffprobe_sha256"], bin_dir
    )
    replace(ffprobe_download, bin_dir / f"ffprobe{exe_suffix}")

    # --- exiftool: an archive that needs extracting ---
    exiftool_entry = manifest["exiftool"]["platforms"][plat_key]
    exiftool_archive = fetch_asset(release_url_base, exiftool_entry["asset"], exiftool_entry["sha256"], bin_dir)

    extract_dir = bin_dir / "_extract"
    if extract_dir.exists():
        shutil.rmtree(extract_dir)

    if system == "Windows":
        # exiftool-windows-*.zip contains exiftool-13.59_64/{exiftool(-k).exe, exiftool_files/}.
        # Renamed to exiftool.exe per exiftool's own install instructions -
        # and to match what utils/dependency_check.py looks for.
        with zipfile.ZipFile(exiftool_archive) as zf:
            zf.extractall(extract_dir)
        extracted_root = next(extract_dir.iterdir())
        replace(extracted_root / "exiftool(-k).exe", bin_dir / "exiftool.exe")
        replace(extracted_root / "exiftool_files", bin_dir / "exiftool_files")
    else:
        # exiftool-unix-*.tar.gz contains Image-ExifTool-13.59/{exiftool, lib/}.
        # "lib" must keep that exact name - the exiftool script's own BEGIN
        # block hardcodes dirname($0)/lib to find its Image::ExifTool modules.
        with tarfile.open(exiftool_archive) as tf:
            tf.extractall(extract_dir, filter="data")
        extracted_root = next(extract_dir.iterdir())
        replace(extracted_root / "exiftool", bin_dir / "exiftool")
        replace(extracted_root / "lib", bin_dir / "lib")

    shutil.rmtree(extract_dir)
    exiftool_archive.unlink()

    if system != "Windows":
        for name in ("ffmpeg", "ffprobe", "exiftool"):
            path = bin_dir / name
            path.chmod(path.stat().st_mode | 0o111)

    print(f"Vendored binaries ready in {bin_dir}")


if __name__ == "__main__":
    main()
