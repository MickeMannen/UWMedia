"""Phase 0 spike (qml_development.md): does the real draw_hud()/PIL compositing
pipeline stay responsive when redrawn on every mouse-move of a live QML
drag? This is the one open rendering/hit-test question qml_development.md
flagged for Color specifically - Qt Quick has no built-in QLabel+QPixmap
equivalent, so this proves a QQuickImageProvider (regenerate a QImage on
demand, keyed by a cache-busting query string) works end to end against
the REAL engine functions Color's own click/drag logic already uses
(resolve_overlay_instance_layout, draw_hud - gui.hud_renderer), not a
synthetic placeholder - before Phase 1 commits to this approach.

Throwaway: static single overlay, position-drag only (no click-to-select,
no corner-resize - that's Phase 1's own scope, ported from
uwmedia/pages/color_page.py's existing 4-corner math). Not wired
into the real app.

Run directly:
    .venv/bin/python -m uwmedia.prototypes.qml_color_preview_spike
"""
import sys
from datetime import datetime
from pathlib import Path

import cv2
from PySide6.QtCore import QObject, Property, QUrl, Signal, Slot
from PySide6.QtGui import QGuiApplication, QImage
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickImageProvider

REPO_ROOT = Path(__file__).resolve().parents[2]
QML_DIR = Path(__file__).resolve().parent / "qml"
SAMPLE_FRAME_PATH = REPO_ROOT / "test_data" / "color_correction" / "DSC06641.JPG"

sys.path.insert(0, str(REPO_ROOT))
from gui.hud_renderer import draw_hud, resolve_overlay_instance_layout  # noqa: E402
from models.dive import Waypoint  # noqa: E402
from utils.layouts import resolve_template_state  # noqa: E402


def _load_real_overlay_layout():
    """Same real template + same relative-path-resolution technique
    OverlayGeneratorPage._compose_hud_layout_path already uses - see that
    method's own comment for why the skin path must be resolved to
    absolute before draw_hud() can cv2.imread() it."""
    import json

    state_path = resolve_template_state("garmin", "x50i", "main", variant="single_tank")
    with open(state_path) as f:
        layout = json.load(f)
    hud_skin = layout.setdefault("hud_skin", {})
    skin_path = hud_skin.get("path")
    if skin_path and not Path(skin_path).is_absolute():
        hud_skin["path"] = str((state_path.parent / skin_path).resolve())
    return layout


class PreviewBackend(QObject):
    changed = Signal()

    def __init__(self):
        super().__init__()
        self._frame_bgr = cv2.imread(str(SAMPLE_FRAME_PATH))
        self._raw_layout = _load_real_overlay_layout()
        self._x = 0.1
        self._y = 0.6
        self._scale = 1.0
        self._revision = 0
        self._waypoint = Waypoint(timestamp=datetime.now(), depth=18.4, temp=21.0, time_since_start=612)

    def _bump(self):
        self._revision += 1
        self.changed.emit()

    @Slot(float, float)
    def setOverlayPosition(self, rel_x, rel_y):
        self._x = min(max(rel_x, 0.0), 1.0)
        self._y = min(max(rel_y, 0.0), 1.0)
        self._bump()

    @Property(str, notify=changed)
    def imageSource(self):
        # Cache-busting query string - QQuickImageProvider.requestImage is
        # only re-invoked when the *source URL string* changes, even
        # though the provider id ("frame") never does.
        return f"image://overlaypreview/frame?r={self._revision}"

    @Property(str, notify=changed)
    def statusText(self):
        return f"x={self._x:.3f}  y={self._y:.3f}  (redraw #{self._revision})"

    def render_current_frame(self):
        """Called by the QQuickImageProvider - real pipeline, same
        functions Color's own _redraw_preview calls today."""
        frame = self._frame_bgr.copy()
        frame_h, frame_w = frame.shape[:2]
        resolved = resolve_overlay_instance_layout(self._raw_layout, self._x, self._y, self._scale, frame_w, frame_h)
        draw_hud(frame, resolved, self._waypoint)
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w = rgb.shape[:2]
        qimage = QImage(rgb.data, w, h, rgb.strides[0], QImage.Format.Format_RGB888)
        return qimage.copy()  # detach from the numpy buffer before it's freed


class OverlayImageProvider(QQuickImageProvider):
    def __init__(self, backend: PreviewBackend):
        super().__init__(QQuickImageProvider.ImageType.Image)
        self._backend = backend

    def requestImage(self, id, size, requestedSize):
        image = self._backend.render_current_frame()
        return image


def main():
    app = QGuiApplication(sys.argv)
    engine = QQmlApplicationEngine()

    backend = PreviewBackend()
    engine.addImageProvider("overlaypreview", OverlayImageProvider(backend))
    engine.rootContext().setContextProperty("backend", backend)

    engine.load(QUrl.fromLocalFile(str(QML_DIR / "color_preview_spike.qml")))
    if not engine.rootObjects():
        sys.exit(-1)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
