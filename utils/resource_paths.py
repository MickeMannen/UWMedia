import sys
from pathlib import Path
from typing import Optional, Union


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
