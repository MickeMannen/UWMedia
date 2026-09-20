"""Color page - PySide6 port of uwmedia/app.py's Color-related methods
(_build_color_section and friends), see pyside6_rework.md Phase 1.

Business logic (EXIF/scrub-slider dive matching, overlay compositing/
hit-test/4-corner-resize math, CLI arg building) is ported close to
verbatim from uwmedia/app.py - only the widget-facing edges change:
toga.Canvas -> QLabel+QPixmap (per pyside6_rework.md's own decision),
Toga on_change/on_press -> Qt signals/slots, asyncio subprocess -> QProcess.

Settings are persisted through utils/app_settings.py under the SAME keys
uwmedia/app.py's own PERSISTED_TEXT_FIELDS/PERSISTED_SELECTION_FIELDS/
PERSISTED_SWITCH_FIELDS and _persist_color_overlay_instances already use
(source_input/output_input/logs_input/color_switch/color_profile/
filename_format_select/color_overlay_instances) - deliberate, not an
oversight: this page reads/writes the exact same settings.json the Toga
app does, so switching between the two apps during the migration doesn't
lose or fork a user's Source/Output/overlay setup.

Deliberately deferred in this first pass (see pyside6_rework.md for the
full list): the custom-filename-pattern escape hatch, --hw-accel/--debug/
--summary flags (Advanced-page-adjacent, not part of Color's own page and
that page isn't ported yet).

Process-tree kill on abort is NOT deferred, despite an early draft of this
docstring saying so - live-tested (see pyside6_rework.md) and found that
plain QProcess.kill() only kills the immediate `python -m uwmedia`
process, leaving its ffmpeg child running orphaned (confirmed: 3 ffmpeg
processes still consuming 200%+ CPU each after clicking Abort). PySide6
6.11's QProcess has no setChildProcessModifier (added in Qt 6.6, not
present in this build's Python bindings) to put the child in its own
session the way the Toga app's _terminate_process_tree does via
start_new_session=True - `pkill -P <pid>` (kill-by-parent-pid) is the
portable-enough stand-in used here instead, sufficient for this app's
actual one-level-deep process tree (uwmedia -> ffmpeg).
"""
import json
import math
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import cv2
from PIL import Image as PILImage
from PIL import ImageDraw
from PySide6 import QtCore, QtGui, QtWidgets

from gui.hud_renderer import draw_hud, overlay_pixel_bbox, resolve_overlay_instance_layout
from metadata.exif import MetadataHandler
from models.dive import Waypoint
from models.manager import DiveManager
from parsers.garmin import GarminParser
from parsers.subsurface import SubsurfaceParser
from parsers.uddf import UDDFParser
from utils.app_settings import get_fields, set_field
from utils.color_profiles import load_merged_color_profiles
from utils.layouts import list_templates, resolve_template_state

from uwmedia.pages.add_hud_dialog import HUD_LOCATION_PRESETS, AddHudDialog
from uwmedia.pages.color_page_ui import Ui_ColorPage

PREVIEW_WORKING_WIDTH = 1920  # working frame-buffer width - matches uwmedia/app.py's COLOR_PREVIEW_WORKING_WIDTH
PREVIEW_DISPLAY_WIDTH = 480
PREVIEW_DISPLAY_HEIGHT = int(PREVIEW_DISPLAY_WIDTH * 9 / 16)  # fixed 16:9 box, same call as the Toga rework's

RESIZE_HANDLE_DISPLAY_PX = 16
SELECTION_COLOR = "#3B82F6"
SELECTION_STROKE_DISPLAY_PX = 2
SELECTION_HANDLE_DISPLAY_PX = 5

FILENAME_FORMAT_PRESETS = [
    ("Keep original filename", ""),
    ("Date taken", "%Y%m%d"),
    ("Date + time (20260905_143000)", "%Y%m%d_%H%M%S"),
    ("Date + time + color (20260905_143000_color)", "%Y%m%d_%H%M%S_color"),
]

# Opposite corner for each corner name - the fixed anchor point a resize
# drag pivots around (see _on_preview_press/_on_preview_drag).
_OPPOSITE_CORNER = {
    "top_left": "bottom_right",
    "top_right": "bottom_left",
    "bottom_left": "top_right",
    "bottom_right": "top_left",
}


def load_color_profiles():
    try:
        data = load_merged_color_profiles()
        return list(data.keys()) or ["default"]
    except Exception:
        return ["default"]


class ColorPage(QtWidgets.QWidget, Ui_ColorPage):
    def __init__(self):
        super().__init__()
        self.setupUi(self)

        # -- state (mirrors the Toga app's own Color-related instance attrs) --
        self.color_overlay_instances = []
        self._color_overlay_next_id = 0
        self._color_overlay_layout_cache = {}
        self.color_selected_overlay_id = None
        self._drag_state = None

        self.preview_frame = None  # working-resolution BGR ndarray
        self.preview_view_w = float(PREVIEW_WORKING_WIDTH)
        self.preview_view_h = float(PREVIEW_WORKING_WIDTH) * 9.0 / 16.0
        self.preview_video_cap = None
        self.preview_video_fps = 30.0
        self.preview_creation_date = None
        self.preview_current_dive = None
        self.preview_current_waypoint = None

        self.dive_manager = DiveManager()
        self._hud_templates = list_templates()

        self.process = None  # QProcess, set while a run is active

        self.preview_label.setFixedSize(PREVIEW_DISPLAY_WIDTH, PREVIEW_DISPLAY_HEIGHT)
        self.preview_label.installEventFilter(self)
        self.preview_label.setMouseTracking(True)

        self.color_profile_combo.addItems(load_color_profiles())
        self._filename_format_by_label = dict(FILENAME_FORMAT_PRESETS)
        self.filename_format_combo.addItems(list(self._filename_format_by_label.keys()))

        self.progress_bar.setRange(0, 0)
        self.progress_bar.setVisible(False)

        self._restore_fields()
        self._restore_overlay_instances()
        self._wire_signals()
        self._extract_preview_frame()

    # ------------------------------------------------------------------
    # Persistence - utils/app_settings.py, same module/keys the Toga app
    # already uses (see this module's own docstring).
    # ------------------------------------------------------------------

    def _restore_fields(self):
        fields = get_fields()
        self.source_input.setText(fields.get("source_input", ""))
        self.output_input.setText(fields.get("output_input", ""))
        self.logs_input.setText(fields.get("logs_input", ""))
        self.color_checkbox.setChecked(fields.get("color_switch", True))
        profile = fields.get("color_profile")
        items = [self.color_profile_combo.itemText(i) for i in range(self.color_profile_combo.count())]
        if profile and profile in items:
            self.color_profile_combo.setCurrentText(profile)
        fmt_label = fields.get("filename_format_select")
        if fmt_label and fmt_label in self._filename_format_by_label:
            self.filename_format_combo.setCurrentText(fmt_label)

    def _wire_signals(self):
        self.source_input.textChanged.connect(self._on_source_changed)
        self.output_input.textChanged.connect(lambda text: set_field("output_input", text))
        self.logs_input.textChanged.connect(self._on_logs_changed)
        self.color_checkbox.toggled.connect(lambda checked: set_field("color_switch", checked))
        self.color_profile_combo.currentTextChanged.connect(lambda text: set_field("color_profile", text))
        self.filename_format_combo.currentTextChanged.connect(lambda text: set_field("filename_format_select", text))

        self.source_file_button.clicked.connect(lambda: self._browse_file(self.source_input))
        self.source_folder_button.clicked.connect(lambda: self._browse_folder(self.source_input))
        self.output_file_button.clicked.connect(lambda: self._browse_file(self.output_input))
        self.output_folder_button.clicked.connect(lambda: self._browse_folder(self.output_input))
        self.logs_browse_button.clicked.connect(lambda: self._browse_folder(self.logs_input))

        self.add_hud_button.clicked.connect(self._on_add_hud)
        self.remove_overlay_button.clicked.connect(self._on_remove_overlay)
        self.scrub_slider.valueChanged.connect(self._on_scrub_changed)
        self.start_button.clicked.connect(self._on_start)

    def _browse_file(self, target_input):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Select file")
        if path:
            target_input.setText(path)

    def _browse_folder(self, target_input):
        path = QtWidgets.QFileDialog.getExistingDirectory(self, "Select folder")
        if path:
            target_input.setText(path)

    def _on_source_changed(self, text):
        set_field("source_input", text)
        self._extract_preview_frame()

    def _on_logs_changed(self, text):
        set_field("logs_input", text)
        self._load_dive_logs()

    # ------------------------------------------------------------------
    # Preview frame extraction + dive matching - ported close to verbatim
    # from _extract_color_preview_frame/_load_color_preview_logs/
    # _color_preview_match_dive_to_media/_color_preview_sync_waypoint/
    # on_color_preview_time_change.
    # ------------------------------------------------------------------

    def _first_source_file(self):
        value = self.source_input.text().strip()
        if not value:
            return None
        path = Path(value)
        if path.is_dir():
            files = [f for f in sorted(path.iterdir()) if f.is_file() and not f.name.startswith(".")]
            return files[0] if files else None
        if path.is_file():
            return path
        return None

    def _load_dive_logs(self):
        self.dive_manager = DiveManager()
        dir_path = Path(self.logs_input.text().strip()) if self.logs_input.text().strip() else None
        if dir_path and dir_path.is_dir():
            uddf, garmin, subsurface = UDDFParser(), GarminParser(), SubsurfaceParser()
            for path in dir_path.iterdir():
                try:
                    if path.suffix == ".uddf":
                        self.dive_manager.add_dives(uddf.parse(path))
                    elif path.suffix == ".fit":
                        self.dive_manager.add_dives(garmin.parse(path))
                    elif path.suffix in (".ssrf", ".xml"):
                        self.dive_manager.add_dives(subsurface.parse(path))
                except Exception as e:
                    print(f"Error parsing {path.name}: {e}")
        self._match_dive_to_media()
        self._redraw_preview()

    def _match_dive_to_media(self):
        if not self.preview_creation_date:
            return
        self.preview_current_dive = self.dive_manager.find_dive_for_timestamp(self.preview_creation_date)
        if self.preview_current_dive:
            elapsed = self.scrub_slider.value() / self.preview_video_fps if self.preview_video_cap else 0
            self._sync_waypoint(elapsed)
        else:
            self.preview_current_waypoint = None

    def _sync_waypoint(self, elapsed_seconds):
        if not self.preview_current_dive or not self.preview_creation_date:
            self.preview_current_waypoint = None
            return
        target_ts = self.preview_creation_date + timedelta(seconds=elapsed_seconds)
        wp = None
        for w in self.preview_current_dive.waypoints:
            if w.timestamp >= target_ts:
                wp = w
                break
        self.preview_current_waypoint = wp

    def _extract_preview_frame(self):
        if self.preview_video_cap is not None:
            self.preview_video_cap.release()
            self.preview_video_cap = None

        source_file = self._first_source_file()
        if source_file is None:
            self.preview_frame = None
            self.preview_current_dive = None
            self.preview_current_waypoint = None
            self.scrub_slider.setEnabled(False)
            self.scrub_time_label.setText("--")
            self._redraw_preview()
            return

        try:
            self.preview_creation_date = MetadataHandler().get_local_creation_date(source_file)
        except Exception:
            self.preview_creation_date = datetime.now()

        if source_file.suffix.lower() in (".mp4", ".mov"):
            cap = cv2.VideoCapture(str(source_file))
            total_frames = max(1, int(cap.get(cv2.CAP_PROP_FRAME_COUNT)))
            self.preview_video_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
            frame_idx = min(10, total_frames - 1)
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            ret, frame = cap.read()
            if not ret:
                cap.release()
                self.preview_frame = None
                self._redraw_preview()
                return
            self.preview_video_cap = cap
            self.scrub_slider.blockSignals(True)
            self.scrub_slider.setMinimum(0)
            self.scrub_slider.setMaximum(max(1, total_frames - 1))
            self.scrub_slider.setValue(frame_idx)
            self.scrub_slider.blockSignals(False)
            self.scrub_slider.setEnabled(True)
            self.scrub_time_label.setText(str(timedelta(seconds=int(frame_idx / self.preview_video_fps))))
        else:
            frame = cv2.imread(str(source_file))
            if frame is None:
                self.preview_frame = None
                self._redraw_preview()
                return
            self.scrub_slider.setEnabled(False)
            self.scrub_time_label.setText("Photo")

        h, w = frame.shape[:2]
        target_w = PREVIEW_WORKING_WIDTH
        target_h = int(target_w * h / w)
        self.preview_frame = cv2.resize(frame, (target_w, target_h), interpolation=cv2.INTER_AREA)
        self.preview_view_w = float(target_w)
        self.preview_view_h = float(target_h)
        self._load_dive_logs()
        self._match_dive_to_media()
        self._redraw_preview()

    def _on_scrub_changed(self, value):
        if self.preview_video_cap is None:
            return
        frame_idx = int(value)
        self.preview_video_cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame = self.preview_video_cap.read()
        if not ret:
            return
        self.preview_frame = cv2.resize(
            frame, (int(self.preview_view_w), int(self.preview_view_h)), interpolation=cv2.INTER_AREA
        )
        elapsed = frame_idx / self.preview_video_fps
        self.scrub_time_label.setText(str(timedelta(seconds=int(elapsed))))
        self._sync_waypoint(elapsed)
        self._redraw_preview()

    # ------------------------------------------------------------------
    # Overlay instances - ported from _load_color_overlay_layout/
    # _resolve_new_color_overlay/_add_color_overlay/on_remove_color_overlay/
    # _persist_color_overlay_instances/_restore_color_overlay_instances.
    # ------------------------------------------------------------------

    def _load_overlay_layout(self, layout_path):
        key = str(layout_path)
        if key not in self._color_overlay_layout_cache:
            try:
                with open(layout_path) as f:
                    self._color_overlay_layout_cache[key] = json.load(f)
            except Exception as e:
                print(f"Could not load overlay layout {layout_path}: {e}")
                self._color_overlay_layout_cache[key] = None
        return self._color_overlay_layout_cache[key]

    def resolve_new_color_overlay(self, brand, computer, page, custom_path, location_label):
        custom_path = (custom_path or "").strip()
        if custom_path:
            layout_path = Path(custom_path)
            label = layout_path.stem.replace("_", " ")
            raw_layout = self._load_overlay_layout(layout_path)
            if raw_layout is None:
                return None
        else:
            if not (brand and computer and page):
                return None
            manifest = self._hud_templates.get(brand, {}).get(computer) or {}
            page_entry = next((p for p in manifest.get("pages", []) if p["id"] == page), None)
            if page_entry is None:
                return None
            variant = page_entry["variants"][0] if page_entry.get("variants") else None
            state_path = resolve_template_state(brand, computer, page, variant=variant)
            if state_path is None:
                return None

            with open(state_path) as f:
                raw_layout = json.load(f)
            hud_skin = raw_layout.setdefault("hud_skin", {})
            skin_path = hud_skin.get("path")
            if skin_path and not Path(skin_path).is_absolute():
                hud_skin["path"] = str((state_path.parent / skin_path).resolve())

            name_parts = [brand]
            if len(self._hud_templates.get(brand, {})) > 1:
                name_parts.append(computer)
            name_parts.append(page)
            out_dir = Path(tempfile.mkdtemp(prefix="uwmedia_qt_color_overlay_"))
            layout_path = out_dir / f"{'_'.join(name_parts)}.json"
            with open(layout_path, "w") as f:
                json.dump(raw_layout, f, indent=2)
            self._color_overlay_layout_cache[str(layout_path)] = raw_layout

            label = f"{manifest.get('manufacturer', brand)} {manifest.get('model', computer)} - {page_entry['name']}"

        anchor = dict(HUD_LOCATION_PRESETS).get(location_label, "BOTTOM_LEFT")
        multiplier = 1.0
        view_w = int(self.preview_view_w) if self.preview_view_w else PREVIEW_WORKING_WIDTH
        view_h = int(self.preview_view_h) if self.preview_view_h else int(PREVIEW_WORKING_WIDTH * 9 / 16)
        x0, y0, x1, y1 = overlay_pixel_bbox(raw_layout, 0.0, 0.0, multiplier, view_w, view_h)
        seed_w = (x1 - x0) / view_w if view_w else 0.0
        seed_h = (y1 - y0) / view_h if view_h else 0.0
        seed_x, seed_y = 0.0, 0.0
        if "RIGHT" in anchor:
            seed_x = max(0.0, 1.0 - seed_w)
        elif "CENTER" in anchor:
            seed_x = max(0.0, (1.0 - seed_w) / 2.0)
        if "BOTTOM" in anchor:
            seed_y = max(0.0, 1.0 - seed_h)
        elif "MIDDLE" in anchor:
            seed_y = max(0.0, (1.0 - seed_h) / 2.0)

        return {
            "id": self._color_overlay_next_id,
            "layout_path": layout_path,
            "label": label,
            "x": seed_x,
            "y": seed_y,
            "scale": multiplier,
        }

    def _on_add_hud(self):
        dialog = AddHudDialog(self._hud_templates, self.resolve_new_color_overlay, parent=self)
        if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted and dialog.result_instance:
            instance = dialog.result_instance
            self.color_overlay_instances.append(instance)
            self._color_overlay_next_id += 1
            self._persist_overlay_instances()
            self._refresh_overlay_list()
            self._redraw_preview()

    def _refresh_overlay_list(self):
        self.overlay_list.clear()
        for instance in self.color_overlay_instances:
            self.overlay_list.addItem(instance["label"])

    def _on_remove_overlay(self):
        row = self.overlay_list.currentRow()
        if row < 0:
            return
        removed = self.color_overlay_instances[row]
        del self.color_overlay_instances[row]
        if self.color_selected_overlay_id == removed["id"]:
            self.color_selected_overlay_id = None
        self._persist_overlay_instances()
        self._refresh_overlay_list()
        self._redraw_preview()

    def _persist_overlay_instances(self):
        set_field("color_overlay_instances", [
            {
                "layout_path": str(instance["layout_path"]),
                "label": instance["label"],
                "x": instance["x"],
                "y": instance["y"],
                "scale": instance["scale"],
            }
            for instance in self.color_overlay_instances
        ])

    def _restore_overlay_instances(self):
        saved = get_fields().get("color_overlay_instances") or []
        self.color_overlay_instances = []
        for entry in saved:
            layout_path = Path(entry["layout_path"])
            if not layout_path.exists():
                print(f"Skipping saved HUD overlay - layout no longer exists: {layout_path}")
                continue
            self.color_overlay_instances.append({
                "id": self._color_overlay_next_id,
                "layout_path": layout_path,
                "label": entry.get("label", layout_path.stem),
                "x": entry.get("x", 0.0),
                "y": entry.get("y", 0.0),
                "scale": entry.get("scale", 1.0),
            })
            self._color_overlay_next_id += 1
        self._refresh_overlay_list()

    # ------------------------------------------------------------------
    # Live preview drawing - QLabel+QPixmap instead of toga.Canvas (see
    # this module's own docstring / pyside6_rework.md's decision). Ported
    # from _redraw_color_preview_canvas.
    # ------------------------------------------------------------------

    def _corner_points(self, bbox):
        x0, y0, x1, y1 = bbox
        return {
            "top_left": (x0, y0),
            "top_right": (x1, y0),
            "bottom_left": (x0, y1),
            "bottom_right": (x1, y1),
        }

    def _draw_selection(self, pil_img, bbox, frame_w):
        scale_up = frame_w / PREVIEW_DISPLAY_WIDTH
        stroke_w = max(1, round(SELECTION_STROKE_DISPLAY_PX * scale_up))
        handle_half = max(2, round(SELECTION_HANDLE_DISPLAY_PX * scale_up))
        draw = ImageDraw.Draw(pil_img)
        x0, y0, x1, y1 = bbox
        draw.rectangle([x0, y0, x1, y1], outline=SELECTION_COLOR, width=stroke_w)
        for cx, cy in self._corner_points(bbox).values():
            draw.rectangle(
                [cx - handle_half, cy - handle_half, cx + handle_half, cy + handle_half],
                fill="white", outline=SELECTION_COLOR, width=stroke_w,
            )

    def _redraw_preview(self):
        if self.preview_frame is None:
            self.preview_label.clear()
            return
        frame = self.preview_frame.copy()
        frame_h, frame_w = frame.shape[:2]
        for instance in self.color_overlay_instances:
            raw_layout = self._load_overlay_layout(instance["layout_path"])
            if raw_layout is None:
                continue
            resolved = resolve_overlay_instance_layout(
                raw_layout, instance["x"], instance["y"], instance["scale"], frame_w, frame_h
            )
            wp = self.preview_current_waypoint or Waypoint(
                timestamp=datetime.now(), depth=10.5, temp=22.0, time_since_start=0
            )
            waypoints = self.preview_current_dive.waypoints if self.preview_current_dive else None
            try:
                draw_hud(frame, resolved, wp, waypoints=waypoints)
            except Exception as e:
                print(f"Color preview overlay render error ({instance['label']}): {e}")

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        pil_img = PILImage.fromarray(rgb)
        selected = next(
            (i for i in self.color_overlay_instances if i["id"] == self.color_selected_overlay_id), None
        )
        if selected is not None:
            raw_layout = self._load_overlay_layout(selected["layout_path"])
            if raw_layout is not None:
                bbox = overlay_pixel_bbox(
                    raw_layout, selected["x"], selected["y"], selected["scale"], frame_w, frame_h
                )
                self._draw_selection(pil_img, bbox, frame_w)

        rgb_bytes = pil_img.convert("RGB").tobytes("raw", "RGB")
        qimage = QtGui.QImage(rgb_bytes, pil_img.width, pil_img.height, pil_img.width * 3, QtGui.QImage.Format.Format_RGB888)
        pixmap = QtGui.QPixmap.fromImage(qimage)
        # Fixed 16:9 display box (see PREVIEW_DISPLAY_WIDTH/HEIGHT) -
        # stretch-fits the frame regardless of its own native aspect, same
        # call the Toga rework already made ("standard video format").
        scaled = pixmap.scaled(
            PREVIEW_DISPLAY_WIDTH, PREVIEW_DISPLAY_HEIGHT,
            QtCore.Qt.AspectRatioMode.IgnoreAspectRatio,
            QtCore.Qt.TransformationMode.SmoothTransformation,
        )
        self.preview_label.setPixmap(scaled)

    # ------------------------------------------------------------------
    # Click/drag/resize - ported from _hit_test_color_overlay/
    # on_color_preview_press/_drag/_release. Wired via an event filter on
    # preview_label rather than subclassing QLabel (avoids needing to
    # promote a custom widget class in the .ui file for Phase 1) - mouse
    # events after a press stay routed to preview_label even if the
    # pointer leaves its bounds mid-drag, standard Qt widget-grab behavior
    # while a button is held, so no extra grabMouse() bookkeeping needed.
    # ------------------------------------------------------------------

    def eventFilter(self, obj, event):
        if obj is self.preview_label:
            et = event.type()
            if et == QtCore.QEvent.Type.MouseButtonPress:
                pos = event.position()
                self._on_preview_press(pos.x(), pos.y())
                return True
            if et == QtCore.QEvent.Type.MouseMove:
                pos = event.position()
                self._on_preview_drag(pos.x(), pos.y())
                return True
            if et == QtCore.QEvent.Type.MouseButtonRelease:
                self._on_preview_release()
                return True
        return super().eventFilter(obj, event)

    def _hit_test_overlay(self, canvas_x, canvas_y):
        if not self.preview_view_w or not self.preview_view_h:
            return None
        display_w, display_h = PREVIEW_DISPLAY_WIDTH, PREVIEW_DISPLAY_HEIGHT
        frame_w = int(self.preview_view_w)
        frame_h = int(self.preview_view_h)
        frame_x = canvas_x * frame_w / display_w
        frame_y = canvas_y * frame_h / display_h
        handle_frame_px = RESIZE_HANDLE_DISPLAY_PX * frame_w / display_w

        selected = next(
            (i for i in self.color_overlay_instances if i["id"] == self.color_selected_overlay_id), None
        )
        if selected is not None:
            raw_layout = self._load_overlay_layout(selected["layout_path"])
            if raw_layout is not None:
                bbox = overlay_pixel_bbox(
                    raw_layout, selected["x"], selected["y"], selected["scale"], frame_w, frame_h
                )
                for corner, (cx, cy) in self._corner_points(bbox).items():
                    if abs(frame_x - cx) <= handle_frame_px and abs(frame_y - cy) <= handle_frame_px:
                        return selected, "resize", corner

        for instance in reversed(self.color_overlay_instances):
            raw_layout = self._load_overlay_layout(instance["layout_path"])
            if raw_layout is None:
                continue
            x0, y0, x1, y1 = overlay_pixel_bbox(
                raw_layout, instance["x"], instance["y"], instance["scale"], frame_w, frame_h
            )
            if x0 - 0.5 <= frame_x <= x1 + 0.5 and y0 - 0.5 <= frame_y <= y1 + 0.5:
                return instance, "move", None
        return None

    def _on_preview_press(self, x, y):
        hit = self._hit_test_overlay(x, y)
        if hit is None:
            if self.color_selected_overlay_id is not None:
                self.color_selected_overlay_id = None
                self._redraw_preview()
            self._drag_state = None
            return
        instance, mode, corner = hit
        was_selected = self.color_selected_overlay_id == instance["id"]
        self.color_selected_overlay_id = instance["id"]
        if not was_selected:
            self._redraw_preview()

        frame_w = int(self.preview_view_w)
        frame_h = int(self.preview_view_h)
        raw_layout = self._load_overlay_layout(instance["layout_path"])
        bbox = overlay_pixel_bbox(raw_layout, instance["x"], instance["y"], instance["scale"], frame_w, frame_h)

        if mode == "move":
            self._drag_state = {
                "id": instance["id"], "mode": "move",
                "start_x": x, "start_y": y,
                "orig_x": instance["x"], "orig_y": instance["y"],
            }
        else:
            corners = self._corner_points(bbox)
            anchor_x, anchor_y = corners[_OPPOSITE_CORNER[corner]]
            orig_diag = math.hypot(bbox[2] - bbox[0], bbox[3] - bbox[1])
            self._drag_state = {
                "id": instance["id"], "mode": "resize", "corner": corner,
                "anchor_x": anchor_x, "anchor_y": anchor_y,
                "orig_diag": max(1.0, orig_diag),
                "orig_scale": instance["scale"],
                "orig_w": bbox[2] - bbox[0], "orig_h": bbox[3] - bbox[1],
                "frame_w": frame_w, "frame_h": frame_h,
            }

    def _on_preview_drag(self, x, y):
        state = self._drag_state
        if not state:
            return
        instance = next((i for i in self.color_overlay_instances if i["id"] == state["id"]), None)
        if instance is None:
            return
        display_w, display_h = PREVIEW_DISPLAY_WIDTH, PREVIEW_DISPLAY_HEIGHT

        if state["mode"] == "move":
            dx = x - state["start_x"]
            dy = y - state["start_y"]
            instance["x"] = max(-0.5, min(1.5, state["orig_x"] + dx / display_w))
            instance["y"] = max(-0.5, min(1.5, state["orig_y"] + dy / display_h))
        else:
            frame_w, frame_h = state["frame_w"], state["frame_h"]
            frame_x = x * frame_w / display_w
            frame_y = y * frame_h / display_h
            new_diag = math.hypot(frame_x - state["anchor_x"], frame_y - state["anchor_y"])
            factor = max(0.05, new_diag / state["orig_diag"])
            instance["scale"] = max(0.1, state["orig_scale"] * factor)
            new_w = state["orig_w"] * factor
            new_h = state["orig_h"] * factor
            anchor_corner = _OPPOSITE_CORNER[state["corner"]]
            x0 = state["anchor_x"] - new_w if "right" in anchor_corner else state["anchor_x"]
            y0 = state["anchor_y"] - new_h if "bottom" in anchor_corner else state["anchor_y"]
            instance["x"] = max(-0.5, min(1.5, x0 / frame_w))
            instance["y"] = max(-0.5, min(1.5, y0 / frame_h))
        self._redraw_preview()

    def _on_preview_release(self):
        if self._drag_state:
            self._drag_state = None
            self._persist_overlay_instances()

    # ------------------------------------------------------------------
    # Start/Progress - ported from build_args/build_command/
    # _run_one_invocation/on_run, using QProcess instead of asyncio
    # subprocess. See this module's own docstring for what's deferred.
    # ------------------------------------------------------------------

    def _build_args(self):
        args = []
        source = self.source_input.text().strip()
        output = self.output_input.text().strip()
        if source:
            args.append(source)
        if output:
            args.append(output)
        if self.logs_input.text().strip():
            args += ["--logs", self.logs_input.text().strip()]
        if self.color_checkbox.isChecked():
            args += ["--color", self.color_profile_combo.currentText()]
        if self.color_overlay_instances:
            overlays_data = [
                {
                    "layout_path": str(instance["layout_path"]),
                    "x": instance["x"],
                    "y": instance["y"],
                    "scale": instance["scale"],
                }
                for instance in self.color_overlay_instances
            ]
            overlays_dir = Path(tempfile.mkdtemp(prefix="uwmedia_qt_overlays_"))
            overlays_path = overlays_dir / "overlays.json"
            with open(overlays_path, "w") as f:
                json.dump(overlays_data, f, indent=2)
            args += ["--overlays-file", str(overlays_path)]
        pattern = self._filename_format_by_label.get(self.filename_format_combo.currentText())
        if pattern:
            args += ["--filename-format", pattern]
        return args

    def _build_command(self, args):
        exe = Path(sys.executable)
        if "python" in exe.name.lower():
            return [sys.executable, "-m", "uwmedia", *args]
        return [sys.executable, *args]

    def _on_start(self):
        if self.process is not None:
            self._kill_process_tree()
            return

        args = self._build_args()
        cmd = self._build_command(args)
        # Not the full command line - a long --overlays-file temp path (or
        # a long Source/Output path) makes one giant unbroken line, and a
        # QLabel with no explicit wrap-width forces its *window* to grow to
        # fit that line rather than wrapping (found live: the window jumped
        # to 3115px wide on Start). Status text stays short on purpose;
        # _on_process_output below carries the real per-line detail.
        self.status_label.setText("Starting…")
        self.progress_bar.setVisible(True)
        self.start_button.setText("Abort")

        self.process = QtCore.QProcess(self)
        self.process.setProcessChannelMode(QtCore.QProcess.ProcessChannelMode.MergedChannels)
        self.process.readyReadStandardOutput.connect(self._on_process_output)
        self.process.finished.connect(self._on_process_finished)
        self.process.start(cmd[0], cmd[1:])

    def _on_process_output(self):
        if self.process is None:
            return
        text = bytes(self.process.readAllStandardOutput()).decode(errors="replace").strip()
        if text:
            # Last non-empty line only, to keep this a single-line status
            # (no stat chips/log pane in this first pass - see docstring).
            self.status_label.setText(text.splitlines()[-1])

    def _on_process_finished(self, exit_code, _exit_status):
        self.status_label.setText(f"Finished (exit code {exit_code})" if exit_code == 0 else f"Failed (exit code {exit_code})")
        self.progress_bar.setVisible(False)
        self.start_button.setText("Start")
        self.process = None

    def _kill_process_tree(self):
        # See this module's own docstring - plain QProcess.kill() leaves
        # ffmpeg (cli_main.py's own child) running orphaned.
        if self.process is None:
            return
        pid = self.process.processId()
        if pid:
            try:
                subprocess.run(["pkill", "-9", "-P", str(pid)], capture_output=True)
            except Exception:
                pass
        self.process.kill()
        # self.process is cleared by _on_process_finished (fired once the
        # kill actually completes) - not here, to avoid a race where a
        # quick second click sees self.process as None and starts a new
        # run before the killed one has actually exited.
