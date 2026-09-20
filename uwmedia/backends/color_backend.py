"""Color page backend - qml_development.md Phase 1 (Pass 1). QObject exposed
to uwmedia/qml/ColorPage.qml as the "colorBackend" context
property, plus a QQuickImageProvider for the live preview - the same
mechanism qml_development.md's Phase 0 spike
(prototypes/qml_color_preview_spike.py) proved live before this page
committed to it.

Business logic (EXIF/scrub-slider dive matching, overlay compositing/
hit-test math, resolve_new_color_overlay) is ported close to verbatim
from uwmedia/pages/color_page.py (the old Widgets page, kept as
reference only - not used by this shell, see qml_development.md's Phase 0
write-up) - only the widget-facing edges change: QLabel+QPixmap -> a
QQuickImageProvider redraw loop, direct .text()/.setText() ->
Property/Signal/Slot, an eventFilter on a QLabel -> a QML MouseArea
forwarding press/drag/release coordinates.

Settings persist through utils/app_settings.py under the SAME keys the
Toga app and the old Widgets page both already use (source_input/
output_input/logs_input/color_switch/color_profile/
filename_format_select/color_overlay_instances) - this page reads/writes
the exact same settings.json, deliberate, not an oversight (see
color_page.py's own docstring for the full reasoning, unchanged here).

Pass 1 shipped source/output/dive-logs/color-correction/output-filename/
overlay-list/Add-HUD/click-to-select/drag-to-move, all live-verified
against the user's real settings and real dive footage (see
qml_development.md's Phase 1 write-up). Pass 2 adds 4-corner resize and the
real Start/Abort + QProcess run pipeline - both ported close to verbatim
from color_page.py's own _hit_test_overlay/_on_preview_drag "resize"
branch + _OPPOSITE_CORNER math, and its build_args/build_command/
_on_start/_kill_process_tree section.

Still deliberately deferred: Add HUD's custom-path escape hatch
(cascade-only, matching every other first-pass page in
pyside6_rework.md's own "deliberately deferred" convention).

_handle_progress_line restores UWMEDIA_FFMPEG_PROGRESS percentage display
- ported from uwmedia/app.py's own method of the same name
(qml_development.md's Toga-removal cutover flagged its absence here as an
undocumented Pass 2 simplification; see tests/test_progress_line.py,
which exercises it directly).
"""
import json
import math
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import cv2
from PySide6.QtCore import Property, QObject, QProcess, Signal, Slot
from PySide6.QtGui import QImage
from PySide6.QtQuick import QQuickImageProvider

from gui.hud_renderer import draw_hud, overlay_pixel_bbox, resolve_overlay_instance_layout
from metadata.exif import MetadataHandler
from models.dive import Waypoint
from models.manager import DiveManager
from parsers.garmin import GarminParser
from parsers.subsurface import SubsurfaceParser
from parsers.uddf import UDDFParser
from utils.app_settings import get_fields, set_field
from utils.color_profiles import load_merged_color_profiles
from utils.display_paths import contract_home_path
from utils.layouts import list_templates, page_display_name, resolve_template_state

from uwmedia.pages.add_hud_dialog import HUD_LOCATION_PRESETS

PREVIEW_WORKING_WIDTH = 1920
PREVIEW_DISPLAY_WIDTH = 528  # must match ColorPage.qml's root.previewWidth
PREVIEW_DISPLAY_HEIGHT = int(PREVIEW_DISPLAY_WIDTH * 9 / 16)
RESIZE_HANDLE_DISPLAY_PX = 16

SELECTION_COLOR = (59, 130, 246)  # #3B82F6, BGR-agnostic - drawn via cv2 below

# Opposite corner for each corner name - the fixed anchor point a resize
# drag pivots around (see _on_preview_press/_on_preview_drag).
_OPPOSITE_CORNER = {
    "top_left": "bottom_right",
    "top_right": "bottom_left",
    "bottom_left": "top_right",
    "bottom_right": "top_left",
}

PROGRESS_LINE_RE = re.compile(r"UWMEDIA_PROGRESS (\d+)/(\d+) (\S+) (.*)$")
# Trailing filename group is optional - ffmpeg/color.py's plain
# color-correction path (process_video_lut, run via ffmpeg_class.py's own
# progress_label param) tags every line with the file it belongs to, so
# several files' percentages can be told apart and aggregated even when
# they're being encoded concurrently in a real batch; other emitters of
# this same marker (cli_main.py's HUD render-log frame loops) don't pass a
# label and keep working exactly as before (self._progress_pct fallback).
FFMPEG_PROGRESS_RE = re.compile(r"UWMEDIA_FFMPEG_PROGRESS (\d+(?:\.\d+)?)(?:\s+(.+))?$")
# Printed once a worker thread actually starts a file in a real parallel
# batch (cli_main.py's _parallel_worker) - lets the Progress card show how
# many files are genuinely in flight at once, not just an indeterminate
# spinner with no further information.
ACTIVE_LINE_RE = re.compile(r"UWMEDIA_PROGRESS_ACTIVE (.*)$")

# Matches cli_main.py's own is_video suffix check exactly (e.g. its build_args
# batch loop) - anything else non-hidden is counted as a photo, same as the
# real batch pipeline's own implicit classification.
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".mkv", ".avi"}

FILENAME_FORMAT_PRESETS = [
    ("Keep original filename", ""),
    ("Date taken", "%Y%m%d"),
    ("Date + time (20260905_143000)", "%Y%m%d_%H%M%S"),
    ("Date + time + color (20260905_143000_color)", "%Y%m%d_%H%M%S_color"),
]


def _load_color_profiles():
    try:
        data = load_merged_color_profiles()
        return list(data.keys()) or ["default"]
    except Exception:
        return ["default"]


def _prettify(key: str) -> str:
    return key.replace("_", " ").title()


class ColorBackend(QObject):
    sourceChanged = Signal()
    outputChanged = Signal()
    logsChanged = Signal()
    colorCheckedChanged = Signal()
    hwAccelChanged = Signal()
    colorProfileChanged = Signal()
    filenameFormatChanged = Signal()
    scrubChanged = Signal()
    previewChanged = Signal()
    overlaysChanged = Signal()
    addHudCascadeChanged = Signal()
    addHudErrorChanged = Signal()
    runStateChanged = Signal()
    dragBoxChanged = Signal()

    def __init__(self):
        super().__init__()

        # -- state (mirrors color_page.py's own instance attrs) --
        self.color_overlay_instances = []
        self._color_overlay_next_id = 0
        self._color_overlay_layout_cache = {}
        self.color_selected_overlay_id = None
        self._drag_state = None
        self._drag_box = {"visible": False, "x": 0.0, "y": 0.0, "w": 0.0, "h": 0.0, "label": ""}

        self.preview_frame = None
        self.preview_view_w = float(PREVIEW_WORKING_WIDTH)
        self.preview_view_h = float(PREVIEW_WORKING_WIDTH) * 9.0 / 16.0
        self.preview_video_cap = None
        self.preview_video_fps = 30.0
        self.preview_creation_date = None
        self.preview_current_dive = None
        self.preview_current_waypoint = None
        self._preview_revision = 0

        self.dive_manager = DiveManager()
        self._hud_templates = list_templates()

        self.process = None  # QProcess, set while a run is active
        self._status_text = "No batch running"
        self._progress_total = 0
        self._progress_done = 0
        self._progress_current_target = None
        self._progress_pct = 0.0
        self._active_files = []
        self._file_progress = {}  # filename -> last-known percent (0-100)

        self._source_text = ""
        self._output_text = ""
        self._logs_text = ""
        self._color_checked = True
        self._hw_accel = True
        self._color_profiles = _load_color_profiles()
        self._color_profile = self._color_profiles[0]
        self._filename_format_by_label = dict(FILENAME_FORMAT_PRESETS)
        self._filename_format = FILENAME_FORMAT_PRESETS[0][0]

        self._scrub_value = 0
        self._scrub_min = 0
        self._scrub_max = 0
        self._scrub_enabled = False
        self._scrub_time_text = "--"

        # Add HUD cascade state
        self._brand_choices = {_prettify(k): k for k in sorted(self._hud_templates)}
        self._computer_choices = {}
        self._page_choices = {}
        self._selected_brand_key = None
        self._selected_computer_key = None
        self._selected_page_id = None
        self._add_hud_error = ""

        self._restore_fields()
        self._restore_overlay_instances()
        self._extract_preview_frame()

    # ------------------------------------------------------------------
    # Simple text/choice properties
    # ------------------------------------------------------------------

    def _restore_fields(self):
        fields = get_fields()
        self._source_text = fields.get("source_input", "") or ""
        self._output_text = fields.get("output_input", "") or ""
        self._logs_text = fields.get("logs_input", "") or ""
        self._color_checked = fields.get("color_switch", True)
        self._hw_accel = fields.get("hw_accel_switch", True)
        profile = fields.get("color_profile")
        if profile and profile in self._color_profiles:
            self._color_profile = profile
        fmt_label = fields.get("filename_format_select")
        if fmt_label and fmt_label in self._filename_format_by_label:
            self._filename_format = fmt_label

    @Property(str, notify=sourceChanged)
    def sourceText(self):
        return self._source_text

    @sourceText.setter
    def sourceText(self, value):
        if value == self._source_text:
            return
        self._source_text = value
        set_field("source_input", value)
        self.sourceChanged.emit()
        self._extract_preview_frame()

    @Property(str, notify=sourceChanged)
    def sourceCountText(self):
        """Shown in the Progress card - counts every non-hidden file a real
        batch run over this same source would pick up, using the identical
        directory listing _first_source_file() already does (sorted,
        dotfiles skipped) and the same video-vs-photo split cli_main.py's
        own is_video check uses, so this never drifts from what Start
        would actually process."""
        value = self._source_text.strip()
        if not value:
            return ""
        path = Path(value)
        if path.is_dir():
            try:
                files = [f for f in path.iterdir() if f.is_file() and not f.name.startswith(".")]
            except OSError:
                return ""
        elif path.is_file():
            files = [path]
        else:
            return ""
        if not files:
            return "No media files found"
        videos = sum(1 for f in files if f.suffix.lower() in VIDEO_EXTENSIONS)
        photos = len(files) - videos
        parts = []
        if videos:
            parts.append(f"{videos} video{'s' if videos != 1 else ''}")
        if photos:
            parts.append(f"{photos} photo{'s' if photos != 1 else ''}")
        return ", ".join(parts) + " found"

    @Property(str, notify=outputChanged)
    def outputText(self):
        return self._output_text

    @outputText.setter
    def outputText(self, value):
        if value == self._output_text:
            return
        self._output_text = value
        set_field("output_input", value)
        self.outputChanged.emit()

    @Property(str, notify=logsChanged)
    def logsText(self):
        return self._logs_text

    @logsText.setter
    def logsText(self, value):
        if value == self._logs_text:
            return
        self._logs_text = value
        set_field("logs_input", value)
        self.logsChanged.emit()
        self._load_dive_logs()

    @Property(bool, notify=colorCheckedChanged)
    def colorChecked(self):
        return self._color_checked

    @colorChecked.setter
    def colorChecked(self, value):
        if value == self._color_checked:
            return
        self._color_checked = value
        set_field("color_switch", value)
        self.colorCheckedChanged.emit()

    @Property(bool, notify=hwAccelChanged)
    def hwAccel(self):
        # Used to live only on the Advanced page (a single, easy-to-miss
        # global toggle) - moved here (and to Overlay Generator/
        # Convertion's own pages) at the user's request, since it's
        # specifically each page's own Start button that needs to read it
        # when building that run's CLI args. Same persisted
        # "hw_accel_switch" key as before, just read/written from each
        # page's own backend now instead of one shared AdvancedBackend
        # property.
        return self._hw_accel

    @hwAccel.setter
    def hwAccel(self, value):
        if value == self._hw_accel:
            return
        self._hw_accel = value
        set_field("hw_accel_switch", value)
        self.hwAccelChanged.emit()

    @Property(list, constant=True)
    def colorProfileList(self):
        return self._color_profiles

    @Property(str, notify=colorProfileChanged)
    def colorProfile(self):
        return self._color_profile

    @colorProfile.setter
    def colorProfile(self, value):
        if value == self._color_profile:
            return
        self._color_profile = value
        set_field("color_profile", value)
        self.colorProfileChanged.emit()

    @Property(list, constant=True)
    def filenameFormatList(self):
        return list(self._filename_format_by_label.keys())

    @Property(str, notify=filenameFormatChanged)
    def filenameFormat(self):
        return self._filename_format

    @filenameFormat.setter
    def filenameFormat(self, value):
        if value == self._filename_format:
            return
        self._filename_format = value
        set_field("filename_format_select", value)
        self.filenameFormatChanged.emit()

    # ------------------------------------------------------------------
    # File/folder browse - real native dialogs, called from QML buttons.
    # QFileDialog is a QtWidgets class - fine to use from a QGuiApplication
    # process as long as QtWidgets is imported (pulls in the platform
    # plugin support it needs); no QApplication/widget tree required for
    # just the static dialog functions.
    # ------------------------------------------------------------------

    @Slot()
    def browseSourceFile(self):
        from PySide6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getOpenFileName(None, "Select file")
        if path:
            self.sourceText = path

    @Slot()
    def browseSourceFolder(self):
        from PySide6.QtWidgets import QFileDialog

        path = QFileDialog.getExistingDirectory(None, "Select folder")
        if path:
            self.sourceText = path

    @Slot()
    def browseOutputFile(self):
        from PySide6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getOpenFileName(None, "Select file")
        if path:
            self.outputText = path

    @Slot()
    def browseOutputFolder(self):
        from PySide6.QtWidgets import QFileDialog

        path = QFileDialog.getExistingDirectory(None, "Select folder")
        if path:
            self.outputText = path

    @Slot()
    def browseLogsFolder(self):
        from PySide6.QtWidgets import QFileDialog

        path = QFileDialog.getExistingDirectory(None, "Select folder")
        if path:
            self.logsText = path

    @Slot(str, result=str)
    def contractPath(self, path):
        """Display-only formatting: /Users/<name>/... -> ~/... . Never
        stores/returns this - sourceText/outputText/logsText themselves
        stay real absolute paths (build_args, browse dialogs, etc. all
        still use the untouched originals); this only feeds the QML
        TextFields' own display text. Shared with OverlayGeneratorBackend/
        ConvertionBackend's own contractPath - see utils/display_paths.py."""
        return contract_home_path(path)

    # ------------------------------------------------------------------
    # Preview frame extraction + dive matching - ported close to verbatim
    # from color_page.py's own _extract_preview_frame/_load_dive_logs/
    # _match_dive_to_media/_sync_waypoint/_on_scrub_changed.
    # ------------------------------------------------------------------

    def _first_source_file(self):
        value = self._source_text.strip()
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
        dir_path = Path(self._logs_text.strip()) if self._logs_text.strip() else None
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
            elapsed = self._scrub_value / self.preview_video_fps if self.preview_video_cap else 0
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
            self._set_scrub(enabled=False, minimum=0, maximum=0, value=0, time_text="--")
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
            self._set_scrub(
                enabled=True, minimum=0, maximum=max(1, total_frames - 1), value=frame_idx,
                time_text=str(timedelta(seconds=int(frame_idx / self.preview_video_fps))),
            )
        else:
            frame = cv2.imread(str(source_file))
            if frame is None:
                self.preview_frame = None
                self._redraw_preview()
                return
            self._set_scrub(enabled=False, minimum=0, maximum=0, value=0, time_text="Photo")

        h, w = frame.shape[:2]
        target_w = PREVIEW_WORKING_WIDTH
        target_h = int(target_w * h / w)
        self.preview_frame = cv2.resize(frame, (target_w, target_h), interpolation=cv2.INTER_AREA)
        self.preview_view_w = float(target_w)
        self.preview_view_h = float(target_h)
        self._load_dive_logs()
        self._match_dive_to_media()
        self._redraw_preview()

    def _set_scrub(self, enabled, minimum, maximum, value, time_text):
        self._scrub_enabled = enabled
        self._scrub_min = minimum
        self._scrub_max = maximum
        self._scrub_value = value
        self._scrub_time_text = time_text
        self.scrubChanged.emit()

    @Property(bool, notify=scrubChanged)
    def scrubEnabled(self):
        return self._scrub_enabled

    @Property(int, notify=scrubChanged)
    def scrubMinimum(self):
        return self._scrub_min

    @Property(int, notify=scrubChanged)
    def scrubMaximum(self):
        return self._scrub_max

    @Property(int, notify=scrubChanged)
    def scrubValue(self):
        return self._scrub_value

    @Property(str, notify=scrubChanged)
    def scrubTimeText(self):
        return self._scrub_time_text

    @Slot(int)
    def onScrubChanged(self, value):
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
        self._scrub_value = frame_idx
        self._scrub_time_text = str(timedelta(seconds=int(elapsed)))
        self.scrubChanged.emit()
        self._sync_waypoint(elapsed)
        self._redraw_preview()

    # ------------------------------------------------------------------
    # Overlay instances - ported close to verbatim from color_page.py's
    # own _load_overlay_layout/resolve_new_color_overlay/_on_add_hud/
    # _refresh_overlay_list/_on_remove_overlay/_persist_overlay_instances/
    # _restore_overlay_instances.
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

    def _resolve_new_color_overlay(self, brand, computer, page, location_label):
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

    @Property(list, notify=overlaysChanged)
    def overlayLabels(self):
        return [instance["label"] for instance in self.color_overlay_instances]

    @Slot(int)
    def removeOverlayAtIndex(self, row):
        if row < 0 or row >= len(self.color_overlay_instances):
            return
        removed = self.color_overlay_instances[row]
        del self.color_overlay_instances[row]
        if self.color_selected_overlay_id == removed["id"]:
            self.color_selected_overlay_id = None
        self._persist_overlay_instances()
        self.overlaysChanged.emit()
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

    # ------------------------------------------------------------------
    # Add HUD cascade - ported close to verbatim from add_hud_dialog.py's
    # AddHudDialog (brand/computer/page cascade + Location preset).
    # Custom-path escape hatch deliberately deferred, see module docstring.
    # ------------------------------------------------------------------

    @Property(list, notify=addHudCascadeChanged)
    def addHudBrandList(self):
        return list(self._brand_choices.keys())

    @Slot()
    def reloadTemplates(self):
        """Re-read the template tree - wired (app.py) to the Overlay
        Designer's templatesChanged so a page saved there is offered by the
        Add Overlay picker immediately. Already-placed overlay instances are
        snapshots (temp copies) and are deliberately left alone."""
        self._hud_templates = list_templates()
        self._brand_choices = {_prettify(k): k for k in sorted(self._hud_templates)}
        self.resetAddHudCascade()

    @Property(list, notify=addHudCascadeChanged)
    def addHudComputerList(self):
        return list(self._computer_choices.keys())

    @Property(bool, notify=addHudCascadeChanged)
    def addHudComputerVisible(self):
        brand = self._selected_brand_key
        computers = self._hud_templates.get(brand, {}) if brand else {}
        return len(computers) > 1

    @Property(list, notify=addHudCascadeChanged)
    def addHudPageList(self):
        return list(self._page_choices.keys())

    @Property(str, notify=addHudErrorChanged)
    def addHudError(self):
        return self._add_hud_error

    @Slot(str)
    def onAddHudBrandSelected(self, brand_display_name):
        self._selected_brand_key = self._brand_choices.get(brand_display_name)
        brand = self._selected_brand_key
        computers = self._hud_templates.get(brand, {}) if brand else {}
        self._computer_choices = {_prettify(k): k for k in sorted(computers)}
        self._selected_computer_key = next(iter(self._computer_choices.values()), None)
        self._refresh_page_choices()
        self._add_hud_error = ""
        self.addHudCascadeChanged.emit()
        self.addHudErrorChanged.emit()

    @Slot(str)
    def onAddHudComputerSelected(self, computer_display_name):
        self._selected_computer_key = self._computer_choices.get(computer_display_name)
        self._refresh_page_choices()
        self.addHudCascadeChanged.emit()

    def _refresh_page_choices(self):
        brand, computer = self._selected_brand_key, self._selected_computer_key
        manifest = self._hud_templates.get(brand, {}).get(computer) if brand and computer else None
        pages = manifest["pages"] if manifest else []
        self._page_choices = {page_display_name(page): page["id"] for page in pages}
        self._selected_page_id = next(iter(self._page_choices.values()), None)

    @Slot(str)
    def onAddHudPageSelected(self, page_display_name):
        self._selected_page_id = self._page_choices.get(page_display_name)

    @Slot()
    def resetAddHudCascade(self):
        self._add_hud_error = ""
        self.addHudErrorChanged.emit()
        if self._brand_choices:
            first_brand = next(iter(self._brand_choices.keys()))
            self.onAddHudBrandSelected(first_brand)

    @Slot(result=bool)
    def confirmAddHud(self):
        # No Location picker any more - overlays are freely draggable once
        # placed (Pass 2's 4-corner resize/move), so a placement preset up
        # front just added a redundant step. Always seed at "Bottom Left"
        # (the same default the picker itself used to default to) and let
        # the user drag it wherever they actually want it.
        instance = self._resolve_new_color_overlay(
            self._selected_brand_key, self._selected_computer_key, self._selected_page_id, "Bottom Left"
        )
        if instance is None:
            self._add_hud_error = "Could not resolve a layout for that choice."
            self.addHudErrorChanged.emit()
            return False
        self.color_overlay_instances.append(instance)
        self._color_overlay_next_id += 1
        self._persist_overlay_instances()
        self.overlaysChanged.emit()
        self._redraw_preview()
        return True

    # ------------------------------------------------------------------
    # Live preview - QQuickImageProvider instead of QLabel+QPixmap, same
    # redraw-on-demand/cache-busting-URL mechanism qml_development.md's own
    # Phase 0 spike proved live before Phase 1 committed to it. Ported
    # from color_page.py's own _redraw_preview/_corner_points/_draw_selection.
    # ------------------------------------------------------------------

    def _corner_points(self, bbox):
        x0, y0, x1, y1 = bbox
        return {
            "top_left": (x0, y0),
            "top_right": (x1, y0),
            "bottom_left": (x0, y1),
            "bottom_right": (x1, y1),
        }

    def _redraw_preview(self):
        self._preview_revision += 1
        self.previewChanged.emit()

    @Property(str, notify=previewChanged)
    def previewImageSource(self):
        return f"image://colorpreview/frame?r={self._preview_revision}"

    # -- Drag box: cheap, QML-native visual feedback for an in-progress
    # move/resize (see onPreviewDragged) - only pure arithmetic, no
    # cv2/PIL/disk I/O, so it can update at full mouse-move frequency
    # without the per-frame cost (and per-frame Image texture reload)
    # that made baking the drag into previewImage itself feel stuck. ----

    def _update_drag_box(self, instance):
        raw_layout = self._load_overlay_layout(instance["layout_path"])
        frame_w = int(self.preview_view_w) or 1
        frame_h = int(self.preview_view_h) or 1
        if raw_layout is None:
            self._drag_box["visible"] = False
            self.dragBoxChanged.emit()
            return
        x0, y0, x1, y1 = overlay_pixel_bbox(
            raw_layout, instance["x"], instance["y"], instance["scale"], frame_w, frame_h
        )
        to_display = PREVIEW_DISPLAY_WIDTH / frame_w
        self._drag_box = {
            "visible": True,
            "x": x0 * to_display,
            "y": y0 * to_display,
            "w": (x1 - x0) * to_display,
            "h": (y1 - y0) * to_display,
            "label": instance["label"],
        }
        self.dragBoxChanged.emit()

    @Property(bool, notify=dragBoxChanged)
    def dragBoxVisible(self):
        return self._drag_box["visible"]

    @Property(float, notify=dragBoxChanged)
    def dragBoxX(self):
        return self._drag_box["x"]

    @Property(float, notify=dragBoxChanged)
    def dragBoxY(self):
        return self._drag_box["y"]

    @Property(float, notify=dragBoxChanged)
    def dragBoxW(self):
        return self._drag_box["w"]

    @Property(float, notify=dragBoxChanged)
    def dragBoxH(self):
        return self._drag_box["h"]

    @Property(str, notify=dragBoxChanged)
    def dragBoxLabel(self):
        return self._drag_box["label"]

    def render_current_frame(self):
        if self.preview_frame is None:
            # 1x1 black placeholder - QQuickImageProvider must return a
            # valid QImage, and PREVIEW_DISPLAY_WIDTH/HEIGHT below stretch
            # it to fill the same fixed 16:9 box a real frame would.
            return QImage(1, 1, QImage.Format.Format_RGB888)

        frame = self.preview_frame.copy()
        frame_h, frame_w = frame.shape[:2]
        # render_current_frame() is expensive (~30-40ms for a real HUD -
        # ~100 individual PIL text draws plus a fresh cv2.imread() of the
        # skin PNG, see ui_update_log.md) and, worse, every call also forces
        # Qt Quick to reload/re-upload a brand new texture for previewImage
        # (cache:false, asynchronous:false) - which is the real per-frame
        # cost during a drag, not just the Python-side render. So this is
        # deliberately NOT called on every onPreviewDragged step any more;
        # dragBox*/onPreviewDragged below drives a plain QML Rectangle for
        # live visual feedback instead (cheap, GPU-composited, no texture
        # reload), and this only runs again once on press (if selection
        # changed) and once on release, baking the final result in.
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

        selected = next(
            (i for i in self.color_overlay_instances if i["id"] == self.color_selected_overlay_id), None
        )
        if selected is not None:
            raw_layout = self._load_overlay_layout(selected["layout_path"])
            if raw_layout is not None:
                bbox = overlay_pixel_bbox(
                    raw_layout, selected["x"], selected["y"], selected["scale"], frame_w, frame_h
                )
                self._draw_selection_cv2(frame, bbox)

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w = rgb.shape[:2]
        qimage = QImage(rgb.data, w, h, rgb.strides[0], QImage.Format.Format_RGB888)
        return qimage.copy()

    def _draw_selection_cv2(self, frame, bbox):
        x0, y0, x1, y1 = [int(round(v)) for v in bbox]
        frame_w = frame.shape[1]
        scale_up = frame_w / PREVIEW_DISPLAY_WIDTH
        stroke_w = max(1, round(2 * scale_up))
        handle_half = max(2, round(5 * scale_up))
        cv2.rectangle(frame, (x0, y0), (x1, y1), SELECTION_COLOR, stroke_w)
        for cx, cy in self._corner_points((x0, y0, x1, y1)).values():
            cx, cy = int(cx), int(cy)
            cv2.rectangle(
                frame, (cx - handle_half, cy - handle_half), (cx + handle_half, cy + handle_half),
                (255, 255, 255), -1,
            )
            cv2.rectangle(
                frame, (cx - handle_half, cy - handle_half), (cx + handle_half, cy + handle_half),
                SELECTION_COLOR, stroke_w,
            )

    # ------------------------------------------------------------------
    # Click/select/drag/resize - Pass 2 adds the resize branch. Ported
    # close to verbatim from color_page.py's own _hit_test_overlay/
    # _on_preview_press/_on_preview_drag/_on_preview_release, driven by a
    # QML MouseArea instead of an eventFilter on a QLabel.
    # ------------------------------------------------------------------

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

    @Slot(float, float)
    def onPreviewPressed(self, x, y):
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
        self._update_drag_box(instance)

    @Slot(float, float)
    def onPreviewDragged(self, x, y):
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
        self._update_drag_box(instance)

    @Slot()
    def onPreviewReleased(self):
        if self._drag_state:
            self._drag_state = None
            self._drag_box["visible"] = False
            self.dragBoxChanged.emit()
            self._redraw_preview()
            self._persist_overlay_instances()

    # ------------------------------------------------------------------
    # Start/Progress - Pass 2. Ported close to verbatim from
    # color_page.py's own build_args/build_command/_on_start/
    # _on_process_output/_on_process_finished/_kill_process_tree, using
    # the same QProcess + pkill-by-parent-pid process-tree-kill approach
    # (plain QProcess.kill() leaves ffmpeg running orphaned - see that
    # module's own docstring for why this isn't deferred either).
    # ------------------------------------------------------------------

    def _build_args(self):
        args = []
        source = self._source_text.strip()
        output = self._output_text.strip()
        if source:
            args.append(source)
        if output:
            args.append(output)
        if self._logs_text.strip():
            args += ["--logs", self._logs_text.strip()]
        if self._color_checked:
            args += ["--color", self._color_profile]
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
        pattern = self._filename_format_by_label.get(self._filename_format)
        if pattern:
            args += ["--filename-format", pattern]
        # --hw-accel defaults to False in cli_main.py's argparse if never
        # passed - this used to never be appended at all (a long-deferred
        # gap, see hwAccel's own docstring above for history), silently
        # running every batch in software encoding regardless of the
        # toggle's value.
        if self._hw_accel:
            args.append("--hw-accel")
        return args

    def _build_command(self, args):
        exe = Path(sys.executable)
        if "python" in exe.name.lower():
            return [sys.executable, "-m", "uwmedia", *args]
        return [sys.executable, *args]

    @Property(str, notify=runStateChanged)
    def statusText(self):
        return self._status_text

    @Property(bool, notify=runStateChanged)
    def isRunning(self):
        return self.process is not None

    @Property(int, notify=runStateChanged)
    def progressFilesDone(self):
        return self._progress_done

    @Property(int, notify=runStateChanged)
    def progressFilesTotal(self):
        return self._progress_total

    @Property(float, notify=runStateChanged)
    def progressOverallFraction(self):
        return (self._progress_done / self._progress_total) if self._progress_total else 0.0

    @Property(bool, notify=runStateChanged)
    def progressCurrentDeterminate(self):
        # A bare, unlabeled UWMEDIA_FFMPEG_PROGRESS percentage can't be
        # pinned to any one file once a real batch runs several ffmpeg
        # encodes in parallel (ThreadPoolExecutor) - see
        # _handle_progress_line - so that case still falls back to an
        # indeterminate (spinning) bar. But the plain color-correction path
        # (ffmpeg/color.py) tags every line with its filename, so as long
        # as at least one has been seen there's real, attributable data to
        # show a true aggregate percentage instead - see
        # progressCurrentFraction.
        if self._file_progress and self._progress_total:
            return True
        return self._progress_total in (0, 1)

    @Property(float, notify=runStateChanged)
    def progressCurrentFraction(self):
        # Aggregate of the whole batch's real encoding progress, not just
        # "files completed": each tracked file contributes its own last-
        # known percent (100 once it's finished, whatever ffmpeg last
        # reported while it's still running, implicitly 0 if it hasn't
        # started yet - simply absent from the dict). Requires at least
        # one labeled UWMEDIA_FFMPEG_PROGRESS line to have been seen (see
        # progressCurrentDeterminate) - otherwise this is the older
        # single-value fallback for the (unlabeled) render-log paths.
        if self._file_progress and self._progress_total:
            return sum(self._file_progress.values()) / (self._progress_total * 100.0)
        return self._progress_pct / 100.0

    @Property(int, notify=runStateChanged)
    def activeFilesCount(self):
        # How many files a real parallel batch is genuinely working on
        # right now (not just "submitted") - see ACTIVE_LINE_RE/
        # cli_main.py's _parallel_worker. The user flagged that an
        # indeterminate spinner alone gave no sense that e.g. 3 files were
        # being processed simultaneously.
        return len(self._active_files)

    @Property(str, notify=runStateChanged)
    def activeFilesText(self):
        return ", ".join(self._active_files)

    def _set_status(self, text):
        self._status_text = text
        self.runStateChanged.emit()

    @Slot()
    def onStartClicked(self):
        if self.process is not None:
            self._kill_process_tree()
            return

        args = self._build_args()
        cmd = self._build_command(args)
        # Not the full command line - see color_page.py's own docstring
        # for the real bug this avoided (a long --overlays-file temp path
        # made the window balloon to 3115px wide).
        self._progress_total = 0
        self._progress_done = 0
        self._progress_current_target = None
        self._progress_pct = 0.0
        self._active_files = []
        self._file_progress = {}
        # Defensive: the preview MouseArea disables itself while isRunning
        # (ColorPage.qml), but that can't retroactively cancel a drag that
        # was already in progress the instant Start was clicked - clear it
        # here too so the translucent drag-box indicator can never be left
        # stuck on screen for a run's whole duration.
        self._drag_state = None
        self._drag_box["visible"] = False
        self.dragBoxChanged.emit()
        self._set_status("Starting…")

        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.process.readyReadStandardOutput.connect(self._on_process_output)
        self.process.finished.connect(self._on_process_finished)
        self.process.start(cmd[0], cmd[1:])
        self.runStateChanged.emit()

    def _on_process_output(self):
        if self.process is None:
            return
        text = bytes(self.process.readAllStandardOutput()).decode(errors="replace").strip()
        if text:
            for line in text.splitlines():
                # No raw-line fallback any more (used to be
                # `self._set_status(line)` for anything _handle_progress_line
                # didn't recognize) - that was the cause of the Progress
                # card visibly "jumping around": a real multi-file batch
                # runs several ffmpeg encodes in parallel worker threads, so
                # their stdout interleaves (per-file UWMEDIA_FFMPEG_PROGRESS
                # lines that can't be attributed to one file, "Starting
                # parallel batch..." banners, LUT-generation/debug prints,
                # etc.) and every single one of those was briefly flashed up
                # as THE status line. Only curated, structured status now
                # reaches the UI - see progressFilesDone/Total/
                # OverallFraction/CurrentFraction/activeFiles* below.
                self._handle_progress_line(line)

    def _handle_progress_line(self, line):
        """Ported from uwmedia/app.py's own _handle_progress_line.
        Sequential-only: a multi-file batch runs several renders in
        parallel (ThreadPoolExecutor), so a bare UWMEDIA_FFMPEG_PROGRESS
        percentage can't be attributed to any one file - only trust it
        when there's at most one file in play (total is 0 for a
        --render-log-style single-shot run that never emits a batch
        marker at all, or 1 for a real batch of exactly one file, still
        handled sequentially). _on_process_output no longer cares about
        the return value (see its own comment on why the raw-line
        fallback was removed), but the existing test suite
        (tests/test_progress_line.py) still asserts on it directly."""
        stripped = line.strip()
        active_match = ACTIVE_LINE_RE.search(stripped)
        if active_match:
            filename = active_match.group(1)
            if filename not in self._active_files:
                self._active_files.append(filename)
                self.runStateChanged.emit()
            return True

        match = PROGRESS_LINE_RE.search(stripped)
        if match:
            done, total, status, filename = match.groups()
            self._progress_done = int(done)
            self._progress_total = int(total)
            if filename in self._active_files:
                self._active_files.remove(filename)
            if status != "start":
                # Credit this file as fully done even if its last labeled
                # UWMEDIA_FFMPEG_PROGRESS line reported under 100% (the
                # 1%-throttled emit in ffmpeg_class.py/cli_main.py's render
                # loops can plausibly miss the very last tick) - otherwise
                # progressCurrentFraction's aggregate would understate
                # completed work forever for that file.
                self._file_progress[filename] = 100.0
            if status == "start":
                self._progress_current_target = None
                self._set_status(f"Starting — 0 of {total} files…")
            elif self._progress_done >= self._progress_total:
                self._progress_current_target = None
                self._progress_pct = 100.0
                self._active_files = []
                self._set_status(f"Finished — last file: {filename}")
            else:
                self._progress_current_target = filename
                self._progress_pct = 0.0
                self._set_status(f"Processing: {filename}")
            return True

        ffmpeg_match = FFMPEG_PROGRESS_RE.search(stripped)
        if ffmpeg_match:
            pct = float(ffmpeg_match.group(1))
            label = ffmpeg_match.group(2)
            if label:
                # Labeled line (color-correction path) - always usable,
                # even in a real parallel batch, since it's tied to a
                # specific file rather than being a bare, unattributable
                # percentage. Drives progressCurrentFraction's aggregate.
                self._file_progress[label] = pct
                self.runStateChanged.emit()
                return True

            attributable = self._progress_total in (0, 1)
            if attributable and (not self._progress_total or self._progress_done < self._progress_total):
                self._progress_pct = pct
                if self._progress_current_target:
                    self._set_status(f"Processing: {self._progress_current_target} — {pct:.0f}%")
                else:
                    self._set_status(f"Rendering — {pct:.0f}%")
            return attributable

        return False

    def _on_process_finished(self, exit_code, _exit_status):
        self._set_status(
            f"Finished (exit code {exit_code})" if exit_code == 0 else f"Failed (exit code {exit_code})"
        )
        self.process = None
        self.runStateChanged.emit()

    def _kill_process_tree(self):
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


class ColorPreviewImageProvider(QQuickImageProvider):
    def __init__(self, backend: ColorBackend):
        super().__init__(QQuickImageProvider.ImageType.Image)
        self._backend = backend

    def requestImage(self, id, size, requestedSize):
        return self._backend.render_current_frame()
