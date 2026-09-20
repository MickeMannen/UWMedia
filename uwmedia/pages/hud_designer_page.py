"""HUD Designer page - PySide6 port of uwmedia/app.py's
_build_hud_designer_fields/_build_hud_designer_section and friends, see
pyside6_rework.md Phase 7.

Business logic (EXIF-matched dive lookup, video/photo frame extraction,
brand/computer/page template resolution, QLabel+QPixmap canvas draw) is
ported close to verbatim, reusing the exact techniques Phase 1's Color
page and Phase 1's AddHudDialog already established for this codebase:
- QLabel+QPixmap instead of toga.Canvas (see color_page.py's own
  docstring/pyside6_rework.md's decision) - _redraw_canvas mirrors
  color_page.py's own _redraw_preview almost line-for-line, minus the
  multi-overlay compositing loop and selection-frame drawing (this page
  only ever previews one resolved template at a time, and has no
  click/drag/resize interaction - the canvas here is read-only).
- QFormLayout.labelForField + setVisible for the Dive-computer row's
  show/hide (only when a brand has >1 computer) - the same technique
  AddHudDialog's own brand/computer/page cascade already uses; this
  page's cascade has no Custom-path/Location escape hatch though, so
  it's simpler (only one row ever needs hiding).

Not shared with Color's own preview state (designer_* vs preview_*
attribute names) - deliberate, matching this codebase's established
"independent state per page, never a shared widget/object" posture (see
pyside6_rework.md's Color/Overlay Generator write-ups on Source/Output/
Dive-logs duplication for the same reasoning). This page ALSO supports a
feature Color's preview doesn't: previewing directly from a picked dive-
log file with no video/photo at all (designer_preview_from_log), and a
TZ-offset slider to compensate for a camera clock that's off from the
dive computer's own clock.

No settings persistence - checked directly against PERSISTED_TEXT_FIELDS/
PERSISTED_SELECTION_FIELDS/PERSISTED_SWITCH_FIELDS in uwmedia/app.py:
none of this page's own fields are in those lists, so the Toga original
doesn't persist this page either.
"""
import copy
import json
from datetime import datetime, timedelta
from pathlib import Path

import cv2
import numpy as np
from PIL import Image as PILImage
from PySide6 import QtCore, QtGui, QtWidgets

from gui.hud_renderer import draw_hud
from metadata.exif import MetadataHandler
from models.dive import Waypoint
from models.manager import DiveManager
from parsers.garmin import GarminParser
from parsers.subsurface import SubsurfaceParser
from parsers.uddf import UDDFParser
from utils.hud_rules_engine import resolve_tank_variant
from utils.layouts import list_templates, resolve_template_state

DESIGNER_CANVAS_WIDTH = 900
SCALE_SLIDER_FACTOR = 100  # QSlider is int-only; 0.20x-4.00x stored as 20-400


def _prettify(key: str) -> str:
    return key.replace("_", " ").title()


class RawWaypointWindow(QtWidgets.QWidget):
    """Ported from on_designer_show_waypoint - a separate top-level window
    dumping the current waypoint's full model as read-only JSON."""

    def __init__(self, data_json: str):
        super().__init__()
        self.setWindowTitle("Current Waypoint Raw Data")
        self.resize(500, 700)
        layout = QtWidgets.QVBoxLayout(self)
        text = QtWidgets.QPlainTextEdit()
        text.setReadOnly(True)
        text.setPlainText(data_json)
        layout.addWidget(text)


class HudDesignerPage(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.designer_layout = None
        self.designer_view_w = 1920.0
        self.designer_view_h = 1080.0
        self.designer_bg_frame = None
        self.designer_video_cap = None
        self.designer_video_fps = 30.0
        self.designer_video_creation_date = None
        self.designer_dive_manager = DiveManager()
        self.designer_current_dive = None
        self.designer_current_waypoint = None
        self.designer_preview_from_log = False
        self.designer_log_file_choices = {}
        self.designer_brand_choices = {}
        self.designer_computer_choices = {}
        self.designer_page_choices = {}
        self._hud_templates = {}
        self._waypoint_window = None

        self._build_ui()
        self._wire_signals()
        self._refresh_brand_choices()
        self._refresh_computer_choices()

    # ------------------------------------------------------------------
    # Layout - ported from _build_hud_designer_section.
    # ------------------------------------------------------------------

    def _build_ui(self):
        root = QtWidgets.QHBoxLayout(self)

        left = QtWidgets.QVBoxLayout()
        self.preview_label = QtWidgets.QLabel()
        self.preview_label.setFixedWidth(DESIGNER_CANVAS_WIDTH)
        self.preview_label.setFixedHeight(round(DESIGNER_CANVAS_WIDTH * 1080 / 1920))
        self.preview_label.setStyleSheet("background-color: #1e1e1e;")
        left.addWidget(self.preview_label)

        slider_row = QtWidgets.QHBoxLayout()
        self.time_slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.time_slider.setEnabled(False)
        slider_row.addWidget(self.time_slider, stretch=1)
        self.time_label = QtWidgets.QLabel("00:00:00")
        self.time_label.setFixedWidth(90)
        slider_row.addWidget(self.time_label)
        left.addLayout(slider_row)

        self.data_label = QtWidgets.QLabel("Depth: -- | Temp: --")
        left.addWidget(self.data_label)
        self.log_label = QtWidgets.QLabel("Current Log: None")
        self.log_label.setStyleSheet("color: gray;")
        left.addWidget(self.log_label)
        self.status_label = QtWidgets.QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("color: gray;")
        left.addWidget(self.status_label)
        left.addStretch(1)
        root.addLayout(left)

        right_scroll = QtWidgets.QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setFixedWidth(380)
        right_container = QtWidgets.QWidget()
        right = QtWidgets.QVBoxLayout(right_container)

        template_group = QtWidgets.QGroupBox("Template")
        template_form = QtWidgets.QFormLayout(template_group)
        self.brand_combo = QtWidgets.QComboBox()
        template_form.addRow("HUD brand", self.brand_combo)
        self.computer_combo = QtWidgets.QComboBox()
        template_form.addRow("Dive computer", self.computer_combo)
        self.computer_row_label = template_form.labelForField(self.computer_combo)
        self.page_combo = QtWidgets.QComboBox()
        template_form.addRow("Page", self.page_combo)
        right.addWidget(template_group)

        size_group = QtWidgets.QGroupBox("Preview Size")
        scale_row = QtWidgets.QHBoxLayout(size_group)
        scale_row.addWidget(QtWidgets.QLabel("Overlay scale:"))
        self.scale_slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.scale_slider.setMinimum(20)
        self.scale_slider.setMaximum(400)
        self.scale_slider.setValue(100)
        scale_row.addWidget(self.scale_slider, stretch=1)
        self.scale_label = QtWidgets.QLabel("1.00x")
        self.scale_label.setFixedWidth(55)
        scale_row.addWidget(self.scale_label)
        right.addWidget(size_group)

        bg_group = QtWidgets.QGroupBox("Background & Logs")
        bg_layout = QtWidgets.QVBoxLayout(bg_group)
        bg_row1 = QtWidgets.QHBoxLayout()
        self.load_bg_button = QtWidgets.QPushButton("Load Video/Photo")
        bg_row1.addWidget(self.load_bg_button)
        self.load_logs_button = QtWidgets.QPushButton("Select Log Directory")
        bg_row1.addWidget(self.load_logs_button)
        bg_layout.addLayout(bg_row1)

        tz_row = QtWidgets.QHBoxLayout()
        tz_row.addWidget(QtWidgets.QLabel("TZ Offset (Log vs Media):"))
        self.tz_slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.tz_slider.setMinimum(-24)
        self.tz_slider.setMaximum(24)
        self.tz_slider.setValue(0)
        tz_row.addWidget(self.tz_slider, stretch=1)
        self.tz_label = QtWidgets.QLabel("0h")
        self.tz_label.setFixedWidth(40)
        tz_row.addWidget(self.tz_label)
        bg_layout.addLayout(tz_row)

        bg_layout.addWidget(QtWidgets.QLabel("Or preview a found log directly (no video needed):"))
        self.log_file_combo = QtWidgets.QComboBox()
        self.log_file_combo.setEnabled(False)
        bg_layout.addWidget(self.log_file_combo)
        right.addWidget(bg_group)

        actions_group = QtWidgets.QGroupBox("Actions")
        actions_layout = QtWidgets.QVBoxLayout(actions_group)
        self.show_waypoint_button = QtWidgets.QPushButton("Show Raw Waypoint Data")
        actions_layout.addWidget(self.show_waypoint_button)
        right.addWidget(actions_group)

        right.addStretch(1)
        right_scroll.setWidget(right_container)
        root.addWidget(right_scroll)

    def _wire_signals(self):
        self.brand_combo.currentTextChanged.connect(self._on_brand_change)
        self.computer_combo.currentTextChanged.connect(self._on_computer_change)
        self.page_combo.currentTextChanged.connect(self._on_page_change)
        self.scale_slider.valueChanged.connect(self._on_scale_change)
        self.time_slider.valueChanged.connect(self._on_time_change)
        self.load_bg_button.clicked.connect(self._on_load_background)
        self.load_logs_button.clicked.connect(self._on_load_logs)
        self.tz_slider.valueChanged.connect(self._on_tz_change)
        self.log_file_combo.currentTextChanged.connect(self._on_log_file_change)
        self.show_waypoint_button.clicked.connect(self._on_show_waypoint)

    # ------------------------------------------------------------------
    # Brand / computer / page selector - same technique as AddHudDialog's
    # own cascade (QFormLayout.labelForField + setVisible), simpler here
    # since there's no Custom-path/Location escape hatch to also hide.
    # ------------------------------------------------------------------

    def _refresh_brand_choices(self):
        self._hud_templates = list_templates()
        self.designer_brand_choices = {_prettify(key): key for key in sorted(self._hud_templates)}
        self.brand_combo.blockSignals(True)
        self.brand_combo.clear()
        self.brand_combo.addItems(list(self.designer_brand_choices.keys()))
        self.brand_combo.blockSignals(False)

    def _current_brand(self):
        return self.designer_brand_choices.get(self.brand_combo.currentText())

    def _current_computer(self):
        brand = self._current_brand()
        if not brand:
            return None
        return self.designer_computer_choices.get(self.computer_combo.currentText())

    def _refresh_computer_row_visibility(self):
        brand = self._current_brand()
        computers = self._hud_templates.get(brand, {}) if brand else {}
        show_computer = len(computers) > 1
        self.computer_row_label.setVisible(show_computer)
        self.computer_combo.setVisible(show_computer)

    def _refresh_computer_choices(self):
        brand = self._current_brand()
        computers = self._hud_templates.get(brand, {}) if brand else {}
        self.designer_computer_choices = {_prettify(key): key for key in sorted(computers)}
        self.computer_combo.blockSignals(True)
        self.computer_combo.clear()
        self.computer_combo.addItems(list(self.designer_computer_choices.keys()))
        self.computer_combo.blockSignals(False)
        self._refresh_computer_row_visibility()
        self._refresh_page_choices()

    def _refresh_page_choices(self):
        brand = self._current_brand()
        computer = self._current_computer()
        manifest = self._hud_templates.get(brand, {}).get(computer) if brand and computer else None
        pages = manifest["pages"] if manifest else []
        self.designer_page_choices = {page["name"]: page["id"] for page in pages}
        self.page_combo.blockSignals(True)
        self.page_combo.clear()
        self.page_combo.addItems(list(self.designer_page_choices.keys()))
        self.page_combo.blockSignals(False)
        self._load_selected_template()

    def _on_brand_change(self, _text):
        self._refresh_computer_choices()

    def _on_computer_change(self, _text):
        self._refresh_page_choices()

    def _on_page_change(self, _text):
        self._load_selected_template()

    def _load_selected_template(self):
        brand = self._current_brand()
        computer = self._current_computer()
        page = self.designer_page_choices.get(self.page_combo.currentText())
        manifest = self._hud_templates.get(brand, {}).get(computer) if brand and computer else None
        page_entry = (
            next((p for p in (manifest or {}).get("pages", []) if p["id"] == page), None) if page else None
        )
        if page_entry is None:
            self.designer_layout = None
            self._redraw_canvas()
            return

        variants = page_entry.get("variants") or []
        variant = None
        if variants:
            # Resolved from the matched dive's own tank count, same as
            # uwmedia/app.py's own comment explains - this preview tool is
            # the one legitimate place to do so since it has a real Dive
            # to resolve against.
            resolved = resolve_tank_variant(self.designer_current_dive)
            variant = resolved if resolved in variants else variants[0]
        state_path = resolve_template_state(brand, computer, page, variant=variant)
        if state_path is None:
            self.designer_layout = None
            self.status_label.setText("Template state file not found.")
            self._redraw_canvas()
            return

        with open(state_path) as f:
            layout = json.load(f)
        hud_skin = layout.setdefault("hud_skin", {})
        skin_path = hud_skin.get("path")
        if skin_path and not Path(skin_path).is_absolute():
            hud_skin["path"] = str((state_path.parent / skin_path).resolve())

        self.designer_layout = layout
        self.status_label.setText(f"Previewing {brand}/{computer}/{page}")
        self._redraw_canvas()

    # ------------------------------------------------------------------
    # Rendering - QLabel+QPixmap, same technique as color_page.py's own
    # _redraw_preview (see this module's own docstring).
    # ------------------------------------------------------------------

    def _scaled_layout(self):
        layout = copy.deepcopy(self.designer_layout)
        factor = self.scale_slider.value() / SCALE_SLIDER_FACTOR
        skin = layout.setdefault("hud_skin", {})
        if skin.get("type") == "shape":
            skin["width"] = skin.get("width", 400) * factor
            skin["height"] = skin.get("height", 200) * factor
        else:
            skin["scale"] = skin.get("scale", 1.0) * factor
        return layout

    def _set_canvas_dimensions(self, width, height):
        self.designer_view_w = float(width)
        self.designer_view_h = float(height)
        self.preview_label.setFixedHeight(round(DESIGNER_CANVAS_WIDTH * height / width))

    def _redraw_canvas(self):
        if self.designer_bg_frame is None:
            self.preview_label.clear()
            return
        frame = self.designer_bg_frame.copy()
        if self.designer_layout:
            wp = self.designer_current_waypoint or Waypoint(
                timestamp=datetime.now(), depth=10.5, temp=22.0, time_since_start=0
            )
            waypoints = self.designer_current_dive.waypoints if self.designer_current_dive else None
            try:
                draw_hud(frame, self._scaled_layout(), wp, waypoints=waypoints)
            except Exception as e:
                print(f"HUD Designer render error: {e}")
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        rgb = np.ascontiguousarray(rgb)
        h, w = rgb.shape[:2]
        qimage = QtGui.QImage(rgb.tobytes(), w, h, w * 3, QtGui.QImage.Format.Format_RGB888)
        pixmap = QtGui.QPixmap.fromImage(qimage)
        disp_h = round(DESIGNER_CANVAS_WIDTH * self.designer_view_h / self.designer_view_w)
        scaled = pixmap.scaled(
            DESIGNER_CANVAS_WIDTH, disp_h,
            QtCore.Qt.AspectRatioMode.IgnoreAspectRatio,
            QtCore.Qt.TransformationMode.SmoothTransformation,
        )
        self.preview_label.setPixmap(scaled)

    # ------------------------------------------------------------------
    # Background / logs - ported from the same-named Toga methods.
    # ------------------------------------------------------------------

    def _on_time_change(self, value):
        if self.designer_preview_from_log:
            seconds = value
            self.time_label.setText(str(timedelta(seconds=int(seconds))))
            self._sync_data_to_frame_by_dive_time(seconds)
            self._redraw_canvas()
            return
        if self.designer_video_cap is None:
            return
        frame_idx = int(value)
        self.designer_video_cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame = self.designer_video_cap.read()
        if not ret:
            return
        frame = cv2.resize(
            frame, (int(self.designer_view_w), int(self.designer_view_h)), interpolation=cv2.INTER_AREA
        )
        self.designer_bg_frame = frame
        seconds = frame_idx / self.designer_video_fps
        self.time_label.setText(str(timedelta(seconds=int(seconds))))
        self._sync_data_to_frame(seconds)
        self._redraw_canvas()

    def _on_load_background(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Select background")
        if not path:
            return
        self._load_background_from_path(Path(path))

    def _load_background_from_path(self, path):
        self.designer_preview_from_log = False
        handler = MetadataHandler()
        try:
            self.designer_video_creation_date = handler.get_local_creation_date(path)
        except Exception:
            self.designer_video_creation_date = datetime.now()

        if path.suffix.lower() in (".mp4", ".mov"):
            self._load_video(path)
        else:
            self._load_image(path)
        self._match_dive_to_media()

    def _load_video(self, path):
        if self.designer_video_cap:
            self.designer_video_cap.release()
        cap = cv2.VideoCapture(str(path))
        ret, frame = cap.read()
        if not ret:
            self.status_label.setText(f"Could not read video: {path}")
            return
        self.designer_video_cap = cap
        self.designer_video_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        total_frames = max(1, int(cap.get(cv2.CAP_PROP_FRAME_COUNT)))
        h, w = frame.shape[:2]
        target_w = 1920
        target_h = int(target_w * h / w)
        self._set_canvas_dimensions(target_w, target_h)
        self.designer_bg_frame = cv2.resize(frame, (target_w, target_h), interpolation=cv2.INTER_AREA)
        self.time_slider.blockSignals(True)
        self.time_slider.setMinimum(0)
        self.time_slider.setMaximum(max(1, total_frames - 1))
        self.time_slider.setValue(0)
        self.time_slider.blockSignals(False)
        self.time_slider.setEnabled(True)
        self.time_label.setText("00:00:00")
        self._redraw_canvas()

    def _load_image(self, path):
        if self.designer_video_cap:
            self.designer_video_cap.release()
            self.designer_video_cap = None
        img = cv2.imread(str(path))
        if img is None:
            try:
                img = cv2.cvtColor(np.array(PILImage.open(path).convert("RGB")), cv2.COLOR_RGB2BGR)
            except Exception:
                img = None
        if img is None:
            self.status_label.setText(f"Could not read image: {path}")
            return
        h, w = img.shape[:2]
        target_w = 1920
        target_h = int(target_w * h / w)
        self._set_canvas_dimensions(target_w, target_h)
        self.designer_bg_frame = cv2.resize(img, (target_w, target_h), interpolation=cv2.INTER_AREA)
        self.time_slider.setEnabled(False)
        self.time_label.setText("Photo Mode")
        self._sync_data_to_frame(0)
        self._redraw_canvas()

    def _on_load_logs(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(self, "Select dive log directory")
        if not path:
            return
        self._load_logs_from_path(Path(path))

    def _load_logs_from_path(self, dir_path):
        self.designer_dive_manager = DiveManager()
        uddf, garmin, subsurface = UDDFParser(), GarminParser(), SubsurfaceParser()
        count = 0
        if not dir_path.exists():
            return
        for path in dir_path.iterdir():
            try:
                if path.suffix == ".uddf":
                    self.designer_dive_manager.add_dives(uddf.parse(path))
                    count += 1
                elif path.suffix == ".fit":
                    self.designer_dive_manager.add_dives(garmin.parse(path))
                    count += 1
                elif path.suffix in (".ssrf", ".xml"):
                    self.designer_dive_manager.add_dives(subsurface.parse(path))
                    count += 1
            except Exception as e:
                print(f"Error parsing {path.name}: {e}")
        self.status_label.setText(f"Loaded {count} log files from {dir_path.name}")
        self._refresh_log_file_choices()
        self._match_dive_to_media()

    def _refresh_log_file_choices(self):
        self.designer_log_file_choices = {}
        seen_counts = {}
        for dive in self.designer_dive_manager.dives.values():
            name = dive.log_filename or "Unknown log"
            when = dive.start_time.strftime("%Y-%m-%d %H:%M") if dive.start_time else "?"
            device = dive.device or dive.manufactor or ""
            base_label = f"{name} — {when}" + (f" ({device})" if device else "")
            seen_counts[base_label] = seen_counts.get(base_label, 0) + 1
            n = seen_counts[base_label]
            label = base_label if n == 1 else f"{base_label} #{n}"
            self.designer_log_file_choices[label] = dive

        self.log_file_combo.blockSignals(True)
        self.log_file_combo.clear()
        self.log_file_combo.addItems(list(self.designer_log_file_choices.keys()))
        self.log_file_combo.blockSignals(False)
        self.log_file_combo.setEnabled(bool(self.designer_log_file_choices))

    def _on_log_file_change(self, label):
        dive = self.designer_log_file_choices.get(label)
        if dive is None or not dive.waypoints:
            return

        if self.designer_video_cap:
            self.designer_video_cap.release()
            self.designer_video_cap = None
        self.designer_preview_from_log = True
        self.designer_current_dive = dive

        self._set_canvas_dimensions(1920, 1080)
        # Plain dark backdrop - there's no video/photo frame to show behind
        # the overlay in this mode, just the skin itself.
        self.designer_bg_frame = np.full((1080, 1920, 3), 30, dtype=np.uint8)

        duration = max(w.time_since_start for w in dive.waypoints)
        self.time_slider.blockSignals(True)
        self.time_slider.setMinimum(0)
        self.time_slider.setMaximum(max(1, duration))
        self.time_slider.setValue(0)
        self.time_slider.blockSignals(False)
        self.time_slider.setEnabled(True)
        self.time_label.setText("00:00:00")

        self._sync_data_to_frame_by_dive_time(0)
        # Re-resolve the page's variant (e.g. single_tank vs sidemount) now
        # that a dive is selected, same as _match_dive_to_media() does for
        # the video-matched path - it also redraws.
        self._load_selected_template()

    def _sync_data_to_frame_by_dive_time(self, offset_seconds):
        if not self.designer_current_dive:
            return
        wp = None
        for w in self.designer_current_dive.waypoints:
            if w.time_since_start >= offset_seconds:
                wp = w
                break
        self.designer_current_waypoint = wp or (
            self.designer_current_dive.waypoints[-1] if self.designer_current_dive.waypoints else None
        )
        wp = self.designer_current_waypoint
        if wp:
            self.data_label.setText(f"Depth: {wp.depth:.1f}m | Temp: {wp.temp:.1f}C")
            self.log_label.setText(f"Current Log: {wp.log_filename or 'Unknown'}")
        else:
            self.data_label.setText("Out of dive range.")
            self.log_label.setText("Current Log: None (No Match)")

    def _on_tz_change(self, value):
        self.tz_label.setText(f"{int(value)}h")
        self._match_dive_to_media()

    def _on_scale_change(self, value):
        self.scale_label.setText(f"{value / SCALE_SLIDER_FACTOR:.2f}x")
        self._redraw_canvas()

    def _match_dive_to_media(self):
        if not self.designer_video_creation_date:
            return
        adjusted = self.designer_video_creation_date + timedelta(hours=self.tz_slider.value())
        self.designer_current_dive = self.designer_dive_manager.find_dive_for_timestamp(adjusted)
        if self.designer_current_dive:
            seconds = self.time_slider.value() / self.designer_video_fps if self.designer_video_cap else 0
            self._sync_data_to_frame(seconds)
            # Re-resolve the page's variant (e.g. single_tank vs sidemount)
            # now that a dive is matched - _load_selected_template() redraws.
            self._load_selected_template()
        else:
            self.data_label.setText("No matching dive found for this date/offset.")

    def _sync_data_to_frame(self, offset_seconds):
        if not self.designer_current_dive or not self.designer_video_creation_date:
            return
        target_ts = self.designer_video_creation_date + timedelta(
            hours=self.tz_slider.value(), seconds=offset_seconds
        )
        wp = None
        for w in self.designer_current_dive.waypoints:
            if w.timestamp >= target_ts:
                wp = w
                break
        self.designer_current_waypoint = wp
        if wp:
            self.data_label.setText(f"Depth: {wp.depth:.1f}m | Temp: {wp.temp:.1f}C")
            self.log_label.setText(f"Current Log: {wp.log_filename or 'Unknown'}")
        else:
            self.data_label.setText("Out of dive range.")
            self.log_label.setText("Current Log: None (No Match)")

    def _on_show_waypoint(self):
        if not self.designer_current_waypoint:
            self.status_label.setText("No waypoint data for current frame.")
            return
        data_json = self.designer_current_waypoint.model_dump_json(indent=4)
        self._waypoint_window = RawWaypointWindow(data_json)
        self._waypoint_window.show()
