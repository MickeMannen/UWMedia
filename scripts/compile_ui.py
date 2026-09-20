#!/usr/bin/env python3
"""
Regenerates *_ui.py modules from Qt Designer .ui files under
uwmedia/ via pyside6-uic.

Per pyside6_rework.md's "Generated UI files" decision: .ui files are the
only thing committed to git - the compiled *_ui.py modules are gitignored
and rebuilt by this script. Run it:
  - after editing any .ui file (in Qt Designer, or by hand)
  - once after a fresh checkout, before `briefcase dev`/`briefcase build`
    will import the app cleanly (there's no committed *_ui.py to fall
    back on)
  - as part of the Briefcase build itself, eventually (not yet wired in -
    Phase 0 only needs a manual run before `briefcase dev`)
"""
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
UI_ROOTS = [REPO_ROOT / "uwmedia"]


def compile_all():
    ui_files = sorted(p for root in UI_ROOTS for p in root.rglob("*.ui"))
    if not ui_files:
        print("No .ui files found under:", ", ".join(str(r) for r in UI_ROOTS))
        return
    for ui_path in ui_files:
        out_path = ui_path.with_name(ui_path.stem + "_ui.py")
        print(f"pyside6-uic {ui_path.relative_to(REPO_ROOT)} -> {out_path.relative_to(REPO_ROOT)}")
        subprocess.run(
            ["pyside6-uic", "-g", "python", str(ui_path), "-o", str(out_path)],
            check=True,
        )


if __name__ == "__main__":
    try:
        compile_all()
    except subprocess.CalledProcessError as e:
        print(f"pyside6-uic failed: {e}", file=sys.stderr)
        sys.exit(1)
