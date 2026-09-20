"""Display-only path contraction shared by the Color/Overlay Generator/
Convertion pages' Source & output text fields. Never mutates or returns
anything the backends actually store/use for real work (build_args,
browse dialogs, ffmpeg invocations, etc. all keep using the untouched
original path) - this only feeds what the QML TextFields display.
"""
from pathlib import Path


def contract_home_path(path):
    """/Users/<name>/... -> ~/... for display only."""
    if not path:
        return path
    try:
        home = str(Path.home())
    except Exception:
        return path
    if path == home:
        return "~"
    if path.startswith(home + "/"):
        return "~" + path[len(home):]
    return path
