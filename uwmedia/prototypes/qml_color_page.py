"""Visual prototype: the Color page re-skinned with Qt Quick / QML (Qt
Quick Controls 2, Material style) instead of plain QWidget/QListWidget.

Throwaway design exploration, not wired into the real app
(uwmedia/app.py, pages/color_page.py) - static sample data only,
no engine calls. See qml_development.md for the real migration plan this
prototype informed (QML was chosen over PySide6-Fluent-Widgets - see that
file's own "Licensing" section for why).

Run directly:
    .venv/bin/python -m uwmedia.prototypes.qml_color_page
"""
import sys
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

REPO_ROOT = Path(__file__).resolve().parents[2]
QML_DIR = Path(__file__).resolve().parent / "qml"
SAMPLE_PREVIEW_IMAGE = REPO_ROOT / "test_data" / "color_correction" / "DSC06641.JPG"


def main():
    app = QGuiApplication(sys.argv)
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty(
        "previewImageUrl", QUrl.fromLocalFile(str(SAMPLE_PREVIEW_IMAGE)).toString()
    )
    engine.load(QUrl.fromLocalFile(str(QML_DIR / "main.qml")))
    if not engine.rootObjects():
        sys.exit(-1)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
