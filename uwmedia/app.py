"""UWMedia - QML/PySide6 GUI, see qml_development.md.

Promoted from the former uwmedia_qt_beta side-install to the production
uwmedia app at cutover (qml_development.md's Toga-removal section), once
every page had a working QML counterpart - Phases 1-11 (backends/*.py +
qml/*.py, Option B: whole-app QML shell, decided by the user directly)
all shipped, see that doc's own per-phase write-ups. A
QQmlApplicationEngine loads uwmedia/qml/main.qml; no PlaceholderPage
remains in its StackLayout.

uwmedia/pages/*.py (an earlier PySide6 Widgets pass, Phases 1-11 of the
now-superseded pyside6_rework.md) is unused by this shell (Option B has
no QQuickWidget bridge) but stays in the tree as reference material each
qml_development.md phase ported its business logic from, not deleted.

QApplication (QtWidgets), not plain QGuiApplication - QFileDialog
(color_backend.py's browse slots, and every later page's own file/folder
pickers) is a QtWidgets class and needs a real QApplication instance to
function correctly, confirmed live (see qml_development.md's Phase 1
write-up) - QApplication is a QGuiApplication too, so this has no
downside for the otherwise-pure-QML pages.
"""
import sys
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtWidgets import QApplication

from uwmedia.backends.color_backend import ColorBackend, ColorPreviewImageProvider
from uwmedia.backends.color_tuning_backend import ColorTuningBackend, ColorTuningImageProvider
from uwmedia.backends.convertion_backend import ConvertionBackend
from uwmedia.backends.advanced_backend import AdvancedBackend
from uwmedia.backends.about_backend import AboutBackend
from uwmedia.backends.dive_profile_backend import DiveProfileBackend, DiveProfilePreviewImageProvider
from uwmedia.backends.overlay_designer_backend import OverlayDesignerBackend, OverlayDesignerPreviewImageProvider
from uwmedia.backends.log_viewer_backend import LogViewerBackend
from uwmedia.backends.tag_editor_backend import TagEditorBackend
from uwmedia.backends.overlay_generator_backend import OverlayGeneratorBackend

QML_MAIN = Path(__file__).resolve().parent / "qml" / "main.qml"


def main():
    app = QApplication(sys.argv)
    engine = QQmlApplicationEngine()

    color_backend = ColorBackend()
    engine.addImageProvider("colorpreview", ColorPreviewImageProvider(color_backend))
    engine.rootContext().setContextProperty("colorBackend", color_backend)

    overlay_generator_backend = OverlayGeneratorBackend()
    engine.rootContext().setContextProperty("overlayGeneratorBackend", overlay_generator_backend)

    convertion_backend = ConvertionBackend()
    engine.rootContext().setContextProperty("convertionBackend", convertion_backend)

    color_tuning_backend = ColorTuningBackend()
    engine.addImageProvider(
        "colortuningoriginal", ColorTuningImageProvider(color_tuning_backend.render_original_frame)
    )
    engine.addImageProvider(
        "colortuningresult", ColorTuningImageProvider(color_tuning_backend.render_result_frame)
    )
    engine.rootContext().setContextProperty("colorTuningBackend", color_tuning_backend)

    tag_editor_backend = TagEditorBackend()
    engine.rootContext().setContextProperty("tagEditorBackend", tag_editor_backend)

    log_viewer_backend = LogViewerBackend()
    engine.rootContext().setContextProperty("logViewerBackend", log_viewer_backend)

    overlay_designer_backend = OverlayDesignerBackend()
    engine.addImageProvider(
        "overlaydesignerpreview", OverlayDesignerPreviewImageProvider(overlay_designer_backend)
    )
    engine.rootContext().setContextProperty("overlayDesignerBackend", overlay_designer_backend)
    # A template saved/created in the Overlay Designer shows up in the other
    # two template pickers right away (overlay_rework.md §5.4).
    overlay_designer_backend.templatesChanged.connect(color_backend.reloadTemplates)
    overlay_designer_backend.templatesChanged.connect(overlay_generator_backend.reloadTemplates)

    dive_profile_backend = DiveProfileBackend()
    engine.addImageProvider(
        "diveprofilepreview", DiveProfilePreviewImageProvider(dive_profile_backend)
    )
    engine.rootContext().setContextProperty("diveProfileBackend", dive_profile_backend)

    advanced_backend = AdvancedBackend()
    engine.rootContext().setContextProperty("advancedBackend", advanced_backend)

    about_backend = AboutBackend()
    engine.rootContext().setContextProperty("aboutBackend", about_backend)

    engine.load(QUrl.fromLocalFile(str(QML_MAIN)))
    if not engine.rootObjects():
        sys.exit(-1)
    exit_code = app.exec()
    # Explicitly tear down the QML engine (and every page's bindings to
    # colorBackend/advancedBackend/etc.) before this function returns and
    # its local backend variables go out of scope. Without this, Python's
    # end-of-function cleanup can garbage-collect the backend QObjects and
    # the engine in either order - if a backend gets deleted first, every
    # QML page still holding a live binding to it (StackLayout keeps all
    # 11 pages instantiated at once, not just the current one) re-evaluates
    # against a now-null context property, producing a "Cannot read
    # property X of null" TypeError per binding on quit. Deleting the
    # engine here, while every backend is still alive, tears down the
    # whole QML component tree cleanly first.
    del engine
    sys.exit(exit_code)
