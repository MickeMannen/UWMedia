"""
QML smoke test: start the real app wiring (uwmedia.app.create_engine), load
main.qml off screen and check that every page loads with no QML errors or
warnings. main.qml's StackLayout creates all pages at once, so one load
covers them all. It runs in a child process because Qt allows only one
QApplication per process; the child inherits the per-test config/data/cache
folders (conftest._isolated_user_dirs).
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import REPO_ROOT

CHILD = r"""
import sys
from PySide6.QtCore import QTimer, QUrl, qInstallMessageHandler, QtMsgType
from PySide6.QtQml import QQmlComponent
from PySide6.QtWidgets import QApplication

messages = []
def handler(kind, context, text):
    if kind != QtMsgType.QtDebugMsg:
        messages.append(f"{kind.name}: {text}")
qInstallMessageHandler(handler)

app = QApplication(sys.argv)
from uwmedia.app import QML_MAIN, create_engine
engine = create_engine()
backends = engine._backends
engine.warnings.connect(lambda ws: messages.extend(f"QML: {w.toString()}" for w in ws))

# Every .qml file compiles on its own (also the ones main.qml doesn't use yet).
for qml in sorted(QML_MAIN.parent.glob("*.qml")):
    component = QQmlComponent(engine, QUrl.fromLocalFile(str(qml)))
    if component.isError():
        messages.extend(f"{qml.name}: {e.toString()}" for e in component.errors())
    print("COMPILED", qml.name)

engine.load(QUrl.fromLocalFile(str(QML_MAIN)))
print("ROOTS", len(engine.rootObjects()))
QTimer.singleShot(500, app.quit)  # let the pages' bindings and timers settle
app.exec()
del engine
del backends
for m in messages:
    print("MSG", m)
"""


def test_main_qml_loads_every_page_without_warnings():
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    result = subprocess.run([sys.executable, "-c", CHILD], cwd=REPO_ROOT, env=env,
                            capture_output=True, text=True, timeout=120)
    out = result.stdout + result.stderr
    assert result.returncode == 0, out
    messages = [line[4:] for line in result.stdout.splitlines() if line.startswith("MSG ")]
    # The offscreen platform's default font is named "Sans Serif", which Qt
    # then looks up (and warns about); on Windows it also looks for a font
    # folder PySide6 doesn't ship (the real app uses the system fonts). Both
    # are the test setup, not our QML.
    messages = [m for m in messages if 'missing font family "Sans Serif"' not in m
                and "QFontDatabase: Cannot find font directory" not in m]
    assert not messages, "\n".join(messages)
    assert "ROOTS 1" in result.stdout, out
    compiled = {line.split()[1] for line in result.stdout.splitlines() if line.startswith("COMPILED ")}
    assert compiled == {p.name for p in (REPO_ROOT / "uwmedia" / "qml").glob("*.qml")}


def test_qmllint_finds_nothing():
    """pyside6-qmllint over every page. Its "unqualified" category is off:
    the pages reach their backends through context properties (colorBackend
    and so on, see uwmedia/app.py), which qmllint can't see, so every use of
    one is reported."""
    qmllint = shutil.which("pyside6-qmllint", path=str(Path(sys.executable).parent)) or shutil.which("pyside6-qmllint")
    if not qmllint:
        pytest.skip("pyside6-qmllint not installed")
    files = sorted(str(p) for p in (REPO_ROOT / "uwmedia" / "qml").glob("*.qml"))
    result = subprocess.run([qmllint, "--unqualified", "disable", "--max-warnings", "0", *files],
                            capture_output=True, text=True, timeout=120)
    report = result.stdout + result.stderr
    assert result.returncode == 0 and "Warning:" not in report, report
