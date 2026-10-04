"""Dive Profile Builder page backend - qml_development.md Phase 8. QObject
exposed to uwmedia/qml/DiveProfilePage.qml as the
"diveProfileBackend" context property, plus a QQuickImageProvider for
the profile chart canvas - same cache-busting-URL mechanism Color's own
backend and Phase 0's spike already established.

Ported close to verbatim from uwmedia/pages/dive_profile_page.py
(the old Widgets page, kept as reference only) - DiveProfilePlan/
PlannedGas/PlannedWaypoint (models.dive_plan), simulate
(utils.dive_plan_engine), write_uddf (parsers.uddf_writer),
render_profile_image/time_from_x (gui.dive_profile_view) all reused
unchanged. render_profile_image already bakes the NDL/deco/cursor
readout text into the returned PIL image itself, so this backend needs
no extra readout-drawing code of its own.

Waypoints can also be placed on the chart itself: max depth / planned
runtime (asked for in a popup on the first click) fix the chart's axes,
and addWaypointAt/moveWaypoint/waypointIndexAt map canvas pixels through
gui.dive_profile_view's chart_axes/point_from_xy/xy_of - the same mapping
the renderer draws with. Clicked waypoints get their gas automatically
from each gas's depth range + phase (utils.dive_plan_engine.
apply_auto_gases), re-derived on every resimulate.

Canvas scrubbing forwards raw press/move/release x-coordinates from a
QML MouseArea, same mechanism Color's own preview and Phase 0's spike
established - mouseTracking is deliberately not requested here (button-
gated only), matching the old Widgets page's own eventFilter semantics.

The Dive settings pane is persisted (utils.app_settings set_field/
get_fields): GF low/high under GF_LOW_FIELD/GF_HIGH_FIELD, everything else
in PERSISTED_PLAN_FIELDS - dive type, CCR/sidemount settings and the dive
computer included. Gases, waypoints and the start time start fresh each
launch.

Save log writes the profile as UDDF, Garmin FIT or Subsurface XML
(LOG_FORMATS), posing as the chosen dive computer, with the plan itself
embedded (parsers/plan_embed.py). Open log takes such a file back: only
logs the builder wrote are accepted (read_log_origin), the embedded plan
is restored as saved, and an older file without one is rebuilt from its
own gases, switches and samples (utils/dive_plan_import.py).
"""
from datetime import datetime
from pathlib import Path

from pydantic import ValidationError
from PySide6.QtCore import Property, QObject, Signal, Slot
from PySide6.QtGui import QImage
from PySide6.QtQuick import QQuickImageProvider

import math

from gui.dive_profile_view import (
    GAS_COLORS,
    chart_axes,
    gas_color,
    nearest_sample,
    next_free_gas_color,
    point_from_xy,
    render_profile_image,
    xy_of,
)
from models.dive_plan import DiveProfilePlan, PlannedGas, PlannedWaypoint
from parsers.fit_writer import write_fit
from parsers.plan_embed import read_log_origin
from parsers.registry import detect_log_format, parse_log_file
from parsers.subsurface_writer import write_subsurface
from parsers.uddf_writer import write_uddf
from utils.app_settings import get_fields, set_field
from utils.dive_computers import DIVE_COMPUTERS
from utils.dive_plan_engine import (
    DECO_SCHEDULE_INTERVAL_SEC,
    apply_auto_gases,
    ascent_from_time,
    deco_schedule_timeline,
    plan_ascent,
    waypoint_phases,
)
from utils.dive_plan_engine import simulate as simulate_dive_plan
from utils.dive_plan_import import plan_from_log

DIVE_PLAN_GAS_TYPES = ("Air", "Nitrox", "Trimix")
# DiveProfilePlan.dive_type <-> display label
DIVE_TYPE_LABELS = {"oc": "Open circuit", "sidemount": "Sidemount", "ccr": "CCR"}
# PlannedGas.side <-> the sidemount Side picker's label ("" = a stage tank)
GAS_SIDE_LABELS = {"": "Stage", "left": "Left", "right": "Right"}
# Save dialog filter -> (extension, writer). The chosen file's own
# extension wins when it's one of these.
LOG_FORMATS = {
    "UDDF (*.uddf)": (".uddf", write_uddf),
    "Garmin FIT (*.fit)": (".fit", write_fit),
    "Subsurface XML (*.ssrf)": (".ssrf", write_subsurface),
}
LOG_FORMAT_FIELD = "dive_profile_log_format"
# Open dialog filter. A log the builder wrote with its plan embedded
# opens as saved; any other log UWMedia reads (an older builder log,
# another program's UDDF/FIT/SSRF, a Shearwater Cloud or Subsurface CSV
# export) is imported, the plan rebuilt from its samples.
LOG_OPEN_FILTER = (
    "Dive logs (*.uddf *.fit *.ssrf *.xml *.csv);;UDDF (*.uddf);;Garmin FIT (*.fit);;"
    "Subsurface (*.ssrf *.xml *.csv);;Shearwater Cloud (*.xml *.csv)"
)
START_TIME_FORMATS = ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S")
# settings.json "fields" keys the last-used gradient factors are kept under.
GF_LOW_FIELD = "dive_profile_gf_low"
GF_HIGH_FIELD = "dive_profile_gf_high"
# AL80 - same default as PlannedGas.tank_size_l/start_pressure_bar.
DEFAULT_TANK_VOLUME_TEXT = "11.1"
DEFAULT_START_PRESSURE_TEXT = "207"


def _is_positive(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_po2(value):
    return _is_number(value) and 0.5 <= value <= 2.0


def _is_setpoint(value):
    return _is_number(value) and 0.4 <= value <= 1.6


def _is_non_negative(value):
    return _is_number(value) and value >= 0


# DiveProfilePlan attribute -> (settings.json "fields" key, validity check).
# A stored value failing its check is ignored on load.
PERSISTED_PLAN_FIELDS = {
    "name": ("dive_profile_name", lambda v: isinstance(v, str) and v.strip() != ""),
    "default_descent_rate": ("dive_profile_descent_rate", _is_positive),
    "default_ascent_rate": ("dive_profile_ascent_rate", _is_positive),
    "water_temp_c": ("dive_profile_water_temp", _is_number),
    "sac_lpm": ("dive_profile_sac_lpm", _is_positive),
    "max_po2_bottom": ("dive_profile_max_po2_bottom", _is_po2),
    "max_po2_deco": ("dive_profile_max_po2_deco", _is_po2),
    "max_depth_m": ("dive_profile_max_depth", _is_positive),
    "planned_runtime_sec": ("dive_profile_planned_runtime_sec", _is_positive),
    "dive_type": ("dive_profile_dive_type", lambda v: v in DIVE_TYPE_LABELS),
    "ccr_low_setpoint": ("dive_profile_ccr_low_setpoint", _is_setpoint),
    "ccr_high_setpoint": ("dive_profile_ccr_high_setpoint", _is_setpoint),
    "ccr_setpoint_switch_depth_m": ("dive_profile_ccr_switch_depth", _is_non_negative),
    "ccr_o2_tank_size_l": ("dive_profile_ccr_o2_tank_size", _is_positive),
    "ccr_o2_start_pressure_bar": ("dive_profile_ccr_o2_start_pressure", _is_positive),
    "sidemount_switch_bar": ("dive_profile_sidemount_switch_bar", _is_positive),
    "computer": ("dive_profile_computer", lambda v: v in DIVE_COMPUTERS),
    "computer_serial": ("dive_profile_computer_serial", lambda v: isinstance(v, str) and v.isdigit()),
}
# Display label <-> PlannedGas.use_phase
GAS_PHASE_LABELS = {"any": "Any", "descent": "Descent/bottom", "ascent": "Ascent/deco"}
GAS_PHASE_ARROWS = {"any": "", "descent": " ↓", "ascent": " ↑"}
AUTO_GAS_LABEL = "Auto"
# Click-to-place snapping (whole minutes / metres) and the pixel radius a
# press has to land within to grab an existing waypoint instead.
SNAP_TIME_SEC = 60
SNAP_DEPTH_M = 1.0
WAYPOINT_HIT_RADIUS_PX = 9
# A click/drop in the last 10% of the time axis grows the planned runtime by
# 25% (rounded up to 5 min) so there is always room to keep placing points.
RUNTIME_GROW_THRESHOLD = 0.9
RUNTIME_GROW_FACTOR = 1.25
DIVE_PROFILE_CANVAS_WIDTH = 700
DIVE_PROFILE_CANVAS_HEIGHT = 420


def _default_plan():
    return DiveProfilePlan(gases=[PlannedGas(id="Air", gas_type="air", o2_percent=21.0)])


def _format_mmss(seconds):
    seconds = max(0, int(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


def _gf_pair_error(low, high):
    if not (1 <= low <= 100 and 1 <= high <= 100):
        return "GF low and high must be between 1 and 100"
    if low > high:
        return "GF low can't be higher than GF high"
    return None


def _format_minutes(seconds):
    return f"{seconds / 60:g}"


def _format_gas_use(gas):
    if not gas.has_depth_range and gas.use_phase == "any":
        return "any"
    low = f"{gas.use_min_depth_m:g}" if gas.use_min_depth_m is not None else "0"
    high = f"{gas.use_max_depth_m:g}" if gas.use_max_depth_m is not None else "∞"
    return f"{low}-{high}m{GAS_PHASE_ARROWS[gas.use_phase]}"


def _parse_optional_depth(text):
    text = (text or "").strip()
    return float(text) if text else None


def _setpoint_pair_error(low, high):
    if not (0.4 <= low <= 1.6 and 0.4 <= high <= 1.6):
        return "Setpoints must be between 0.4 and 1.6 bar"
    if low > high:
        return "The low setpoint can't be higher than the high one"
    return None


def _parse_start_time(text):
    """None for blank (= the time of saving); ValueError if unparseable."""
    text = (text or "").strip()
    if not text:
        return None
    for fmt in START_TIME_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass
    raise ValueError("Enter the start as YYYY-MM-DD HH:MM, or leave it blank for the time of saving")


def _parse_time_to_seconds(text):
    text = (text or "").strip()
    if not text:
        raise ValueError("Enter a time")
    if ":" in text:
        minutes_str, seconds_str = text.split(":", 1)
        return int(minutes_str) * 60 + int(seconds_str)
    return int(round(float(text) * 60))


class DiveProfileBackend(QObject):
    settingsChanged = Signal()
    gasFieldsChanged = Signal()
    gasesChanged = Signal()
    waypointFieldsChanged = Signal()
    waypointsChanged = Signal()
    statusChanged = Signal()
    previewChanged = Signal()
    cursorChanged = Signal()

    def __init__(self):
        super().__init__()

        self.dive_plan = _default_plan()
        self.dive_profile_samples = []
        self.dive_profile_warnings = []
        self.dive_deco_schedules = []  # deco_schedule_timeline(), for the chart's stop shading
        self.dive_profile_cursor_time = None
        self._preview_revision = 0

        self._load_persisted_plan_fields()
        self._apply_dive_type_defaults()
        self._load_persisted_gf()
        self._sync_texts_from_plan()

        self._gas_name_text = ""
        self._gas_type = "Air"
        self._gas_o2_text = "21"
        self._gas_he_text = "0"
        self._gas_diluent = False
        self._gas_side = ""
        self._gas_tank_text = self._next_free_tank()
        self._gas_volume_text = DEFAULT_TANK_VOLUME_TEXT
        self._gas_start_pressure_text = DEFAULT_START_PRESSURE_TEXT
        self._gas_min_depth_text = ""
        self._gas_max_depth_text = ""
        self._gas_phase = "any"
        self._gas_color = ""  # "" = next free palette colour on add
        self._gas_status_text = ""
        self._editing_gas_id = None

        self._wp_time_text = ""
        self._wp_depth_text = ""
        self._wp_gas_text = ""
        self._wp_rate_text = ""
        self._wp_status_text = ""
        self._editing_runtime = None
        self._dragging = False
        self._end_dive_status_text = ""
        self._cursor_info = []
        self._deco_plan_cache = {}  # sample time -> ascent_from_time(), cleared on resimulate

        self._status_text = "Click in the chart to place the first waypoint"
        self._status_is_error = False

        self._redraw()

    def _sync_texts_from_plan(self):
        """The Dive settings texts as the plan has them - on start-up and
        after Open log replaces the plan."""
        plan = self.dive_plan
        self._name_text = plan.name
        self._gf_low_text = f"{plan.gf_low:g}"
        self._gf_high_text = f"{plan.gf_high:g}"
        self._gf_error_text = ""
        self._descent_rate_text = str(plan.default_descent_rate)
        self._ascent_rate_text = str(plan.default_ascent_rate)
        self._water_temp_text = str(plan.water_temp_c)
        self._sac_text = f"{plan.sac_lpm:g}"
        self._max_depth_text = f"{plan.max_depth_m:g}" if plan.max_depth_m else ""
        self._bottom_po2_text = f"{plan.max_po2_bottom:g}"
        self._deco_po2_text = f"{plan.max_po2_deco:g}"
        self._runtime_text = _format_minutes(plan.planned_runtime_sec) if plan.planned_runtime_sec else ""
        if plan.ccr_low_setpoint > plan.ccr_high_setpoint:
            plan.ccr_low_setpoint = plan.ccr_high_setpoint
        self._ccr_low_text = f"{plan.ccr_low_setpoint:g}"
        self._ccr_high_text = f"{plan.ccr_high_setpoint:g}"
        self._ccr_error_text = ""
        self._ccr_switch_depth_text = f"{plan.ccr_setpoint_switch_depth_m:g}"
        self._ccr_o2_size_text = f"{plan.ccr_o2_tank_size_l:g}"
        self._ccr_o2_start_text = f"{plan.ccr_o2_start_pressure_bar:g}"
        self._sidemount_switch_text = f"{plan.sidemount_switch_bar:g}"
        self._serial_text = plan.computer_serial
        self._start_time_text = plan.start_time.strftime(START_TIME_FORMATS[0]) if plan.start_time else ""
        self._log_error_text = ""

    # ------------------------------------------------------------------
    # Open log - a log the builder saved back into the editor, or any
    # other log imported as a plan
    # ------------------------------------------------------------------

    def load_log(self, path):
        """Replaces the plan with the one in `path`: the embedded plan as
        saved for a log the builder wrote with it, otherwise one rebuilt
        from the log's gases, switches and samples (an older builder log,
        or any other program's log UWMedia reads). Returns a status line;
        raises ValueError for a file it can't read."""
        path = Path(path)
        if not path.is_file():
            raise ValueError(f"{path} does not exist")
        log_format = detect_log_format(path)
        if log_format is None:
            raise ValueError(
                f"Unknown log format '{path.suffix}' - use .uddf, .fit, .ssrf or a Shearwater/Subsurface .xml/.csv export"
            )
        origin = read_log_origin(path)
        if origin.plan is not None:
            self._apply_plan(origin.plan)
            return f"Opened {path.name}: plan restored as saved"
        dives = parse_log_file(path, log_format)
        if not dives:
            raise ValueError(f"No dive found in {path.name}")
        self._apply_plan(plan_from_log(path, dives[0], self.dive_plan))
        if origin.created_by_uwmedia:
            return f"Opened {path.name}: saved before UWMedia kept the plan, so rebuilt from its samples - check the waypoints"
        return f"Imported {path.name}: plan rebuilt from its samples - check the gases and waypoints"

    def _apply_plan(self, plan):
        self.dive_plan = plan
        self._apply_dive_type_defaults()
        for attr in PERSISTED_PLAN_FIELDS:
            self._persist(attr)
        set_field(GF_LOW_FIELD, plan.gf_low)
        set_field(GF_HIGH_FIELD, plan.gf_high)
        self._sync_texts_from_plan()
        self._check_log_details()
        self.newGas()
        self._clear_waypoint_inputs()
        self.settingsChanged.emit()
        self.gasesChanged.emit()
        self.waypointsChanged.emit()
        self._update_cursor_info()
        self._resimulate()

    @Slot()
    def openLog(self):
        from PySide6.QtWidgets import QFileDialog, QMessageBox

        path, _ = QFileDialog.getOpenFileName(None, "Open dive log", "", LOG_OPEN_FILTER)
        if not path:
            return
        try:
            message = self.load_log(path)
        except Exception as e:
            QMessageBox.warning(None, "Could not open log", str(e))
            return
        self._end_dive_status_text = message
        self.statusChanged.emit()

    # ------------------------------------------------------------------
    # Dive settings
    # ------------------------------------------------------------------

    @Property(str, notify=settingsChanged)
    def nameText(self):
        return self._name_text

    @nameText.setter
    def nameText(self, value):
        self._name_text = value
        if value.strip():
            self.dive_plan.name = value
            self._persist("name")
        self.settingsChanged.emit()

    # Persistence of the other Dive settings - see PERSISTED_PLAN_FIELDS.

    def _load_persisted_plan_fields(self):
        fields = get_fields()
        for attr, (key, is_valid) in PERSISTED_PLAN_FIELDS.items():
            value = fields.get(key)
            if value is not None and is_valid(value):
                setattr(self.dive_plan, attr, int(value) if attr == "planned_runtime_sec" else value)

    def _persist(self, attr):
        key, _ = PERSISTED_PLAN_FIELDS[attr]
        set_field(key, getattr(self.dive_plan, attr))

    # Gradient factors - typed as text, applied (and remembered across
    # restarts) only once both form a valid pair.

    def _load_persisted_gf(self):
        fields = get_fields()
        try:
            low = float(fields.get(GF_LOW_FIELD, self.dive_plan.gf_low))
            high = float(fields.get(GF_HIGH_FIELD, self.dive_plan.gf_high))
        except (TypeError, ValueError):
            return
        if _gf_pair_error(low, high) is None:
            self.dive_plan.gf_low = low
            self.dive_plan.gf_high = high

    @Property(str, notify=settingsChanged)
    def gfLowText(self):
        return self._gf_low_text

    @gfLowText.setter
    def gfLowText(self, value):
        self._gf_low_text = value
        self._apply_gf()

    @Property(str, notify=settingsChanged)
    def gfHighText(self):
        return self._gf_high_text

    @gfHighText.setter
    def gfHighText(self, value):
        self._gf_high_text = value
        self._apply_gf()

    @Property(str, notify=settingsChanged)
    def gfErrorText(self):
        return self._gf_error_text

    def _apply_gf(self):
        try:
            low, high = float(self._gf_low_text), float(self._gf_high_text)
            error = _gf_pair_error(low, high)
        except (TypeError, ValueError):
            error = "Enter GF low and high as numbers, e.g. 30 and 70"
        self._gf_error_text = error or ""
        self.settingsChanged.emit()
        if error:
            return
        if (low, high) == (self.dive_plan.gf_low, self.dive_plan.gf_high):
            return
        self.dive_plan.gf_low = low
        self.dive_plan.gf_high = high
        set_field(GF_LOW_FIELD, low)
        set_field(GF_HIGH_FIELD, high)
        self._resimulate()

    @Property(str, notify=settingsChanged)
    def descentRateText(self):
        return self._descent_rate_text

    @descentRateText.setter
    def descentRateText(self, value):
        self._descent_rate_text = value
        try:
            rate = float(value)
            if rate > 0:
                self.dive_plan.default_descent_rate = rate
                self._persist("default_descent_rate")
        except (TypeError, ValueError):
            pass
        self.settingsChanged.emit()
        self._resimulate()

    @Property(str, notify=settingsChanged)
    def ascentRateText(self):
        return self._ascent_rate_text

    @ascentRateText.setter
    def ascentRateText(self, value):
        self._ascent_rate_text = value
        try:
            rate = float(value)
            if rate > 0:
                self.dive_plan.default_ascent_rate = rate
                self._persist("default_ascent_rate")
        except (TypeError, ValueError):
            pass
        self.settingsChanged.emit()
        self._resimulate()

    @Property(str, notify=settingsChanged)
    def waterTempText(self):
        return self._water_temp_text

    @waterTempText.setter
    def waterTempText(self, value):
        self._water_temp_text = value
        try:
            self.dive_plan.water_temp_c = float(value)
            self._persist("water_temp_c")
        except (TypeError, ValueError):
            pass
        self.settingsChanged.emit()

    @Property(str, notify=settingsChanged)
    def sacText(self):
        return self._sac_text

    @sacText.setter
    def sacText(self, value):
        self._sac_text = value
        try:
            sac = float(value)
            if sac > 0:
                self.dive_plan.sac_lpm = sac
                self._persist("sac_lpm")
        except (TypeError, ValueError):
            pass
        self.settingsChanged.emit()
        self._resimulate()

    # PO2 limits - the user's own acceptable PO2 on the bottom and on deco,
    # which set every gas's MOD (gas table, auto gas choice, End dive's
    # gas-switch depths).
    def _set_po2(self, attr, value):
        try:
            po2 = float(value)
            if 0.5 <= po2 <= 2.0:
                setattr(self.dive_plan, attr, po2)
                self._persist(attr)
        except (TypeError, ValueError):
            pass
        self.settingsChanged.emit()
        self.gasesChanged.emit()
        self._resimulate()

    @Property(str, notify=settingsChanged)
    def bottomPo2Text(self):
        return self._bottom_po2_text

    @bottomPo2Text.setter
    def bottomPo2Text(self, value):
        self._bottom_po2_text = value
        self._set_po2("max_po2_bottom", value)

    @Property(str, notify=settingsChanged)
    def decoPo2Text(self):
        return self._deco_po2_text

    @decoPo2Text.setter
    def decoPo2Text(self, value):
        self._deco_po2_text = value
        self._set_po2("max_po2_deco", value)

    # ------------------------------------------------------------------
    # Dive type - open circuit, sidemount (paired tanks alternated every
    # sidemount_switch_bar) or CCR (the diluent is the loop, held at the
    # low/high setpoint either side of the switch depth; other gases are
    # bailout).
    # ------------------------------------------------------------------

    @Property(list, constant=True)
    def diveTypeList(self):
        return list(DIVE_TYPE_LABELS.values())

    @Property(str, notify=settingsChanged)
    def diveTypeLabel(self):
        return DIVE_TYPE_LABELS[self.dive_plan.dive_type]

    @Property(bool, notify=settingsChanged)
    def isCcr(self):
        return self.dive_plan.dive_type == "ccr"

    @Property(bool, notify=settingsChanged)
    def isSidemount(self):
        return self.dive_plan.dive_type == "sidemount"

    @Slot(str)
    def onDiveTypeSelected(self, label):
        dive_type = next((k for k, v in DIVE_TYPE_LABELS.items() if v == label), "oc")
        if dive_type == self.dive_plan.dive_type:
            return
        self.dive_plan.dive_type = dive_type
        self._persist("dive_type")
        self._apply_dive_type_defaults()
        editing = self._editing_gas_index()
        if editing >= 0:
            self._load_gas_fields(self.dive_plan.gases[editing])
        else:
            self.newGas()
        self.settingsChanged.emit()
        self.gasesChanged.emit()
        self._update_cursor_info()
        self._resimulate()

    def _apply_dive_type_defaults(self):
        """Makes the dive type do something straight away: a CCR dive needs
        a diluent, a sidemount dive a left and a right tank - the first
        (bottom) gas goes on the left, and the gas editor then offers its
        right-hand twin (newGas)."""
        gases = self.dive_plan.gases
        if self.dive_plan.is_ccr and gases and self.dive_plan.diluent_gas() is None:
            gases[0].diluent = True
        if self.dive_plan.dive_type == "sidemount" and gases and not any(g.side for g in gases):
            bottom = next((g for g in gases if g.use_phase != "ascent"), gases[0])
            bottom.side = "left"

    def _set_plan_number(self, attr, value, is_valid):
        """Applies a typed number to the plan (and remembers it) when
        valid; the text itself is kept either way."""
        try:
            number = float(value)
        except (TypeError, ValueError):
            return
        if is_valid(number):
            setattr(self.dive_plan, attr, number)
            self._persist(attr)

    @Property(str, notify=settingsChanged)
    def ccrLowSetpointText(self):
        return self._ccr_low_text

    @ccrLowSetpointText.setter
    def ccrLowSetpointText(self, value):
        self._ccr_low_text = value
        self._apply_setpoints()

    @Property(str, notify=settingsChanged)
    def ccrHighSetpointText(self):
        return self._ccr_high_text

    @ccrHighSetpointText.setter
    def ccrHighSetpointText(self, value):
        self._ccr_high_text = value
        self._apply_setpoints()

    @Property(str, notify=settingsChanged)
    def ccrErrorText(self):
        return self._ccr_error_text

    def _apply_setpoints(self):
        """Same pattern as _apply_gf: applied only once both form a valid pair."""
        try:
            low, high = float(self._ccr_low_text), float(self._ccr_high_text)
            error = _setpoint_pair_error(low, high)
        except (TypeError, ValueError):
            error = "Enter the setpoints as numbers, e.g. 0.7 and 1.3"
        self._ccr_error_text = error or ""
        self.settingsChanged.emit()
        if error:
            return
        self.dive_plan.ccr_low_setpoint = low
        self.dive_plan.ccr_high_setpoint = high
        self._persist("ccr_low_setpoint")
        self._persist("ccr_high_setpoint")
        self._resimulate()

    @Property(str, notify=settingsChanged)
    def ccrSwitchDepthText(self):
        return self._ccr_switch_depth_text

    @ccrSwitchDepthText.setter
    def ccrSwitchDepthText(self, value):
        self._ccr_switch_depth_text = value
        self._set_plan_number("ccr_setpoint_switch_depth_m", value, lambda v: v >= 0)
        self.settingsChanged.emit()
        self._resimulate()

    @Property(str, notify=settingsChanged)
    def ccrO2SizeText(self):
        return self._ccr_o2_size_text

    @ccrO2SizeText.setter
    def ccrO2SizeText(self, value):
        self._ccr_o2_size_text = value
        self._set_plan_number("ccr_o2_tank_size_l", value, lambda v: v > 0)
        self.settingsChanged.emit()
        self._resimulate()

    @Property(str, notify=settingsChanged)
    def ccrO2StartText(self):
        return self._ccr_o2_start_text

    @ccrO2StartText.setter
    def ccrO2StartText(self, value):
        self._ccr_o2_start_text = value
        self._set_plan_number("ccr_o2_start_pressure_bar", value, lambda v: v > 0)
        self.settingsChanged.emit()
        self._resimulate()

    @Property(str, notify=settingsChanged)
    def sidemountSwitchText(self):
        return self._sidemount_switch_text

    @sidemountSwitchText.setter
    def sidemountSwitchText(self, value):
        self._sidemount_switch_text = value
        self._set_plan_number("sidemount_switch_bar", value, lambda v: v > 0)
        self.settingsChanged.emit()
        self._resimulate()

    # ------------------------------------------------------------------
    # Log details - what the saved file says about the dive beyond its
    # profile: the computer it poses as (utils.dive_computers), its serial
    # and the start time (matched against media timestamps).
    # ------------------------------------------------------------------

    @Property(list, constant=True)
    def computerList(self):
        return list(DIVE_COMPUTERS)

    @Property(str, notify=settingsChanged)
    def computerLabel(self):
        return self.dive_plan.computer

    @Slot(str)
    def onComputerSelected(self, label):
        if label in DIVE_COMPUTERS:
            self.dive_plan.computer = label
            self._persist("computer")
            self.settingsChanged.emit()

    @Property(str, notify=settingsChanged)
    def serialText(self):
        return self._serial_text

    @serialText.setter
    def serialText(self, value):
        self._serial_text = value
        if value.strip().isdigit():
            self.dive_plan.computer_serial = value.strip()
            self._persist("computer_serial")
        self._check_log_details()

    @Property(str, notify=settingsChanged)
    def startTimeText(self):
        return self._start_time_text

    @startTimeText.setter
    def startTimeText(self, value):
        self._start_time_text = value
        try:
            self.dive_plan.start_time = _parse_start_time(value)
        except ValueError:
            pass
        self._check_log_details()

    @Property(str, notify=settingsChanged)
    def logErrorText(self):
        return self._log_error_text

    def _check_log_details(self):
        errors = []
        try:
            _parse_start_time(self._start_time_text)
        except ValueError as e:
            errors.append(str(e))
        if not self._serial_text.strip().isdigit():
            errors.append("The serial number must be digits only")
        self._log_error_text = " · ".join(errors)
        self.settingsChanged.emit()

    # ------------------------------------------------------------------
    # Chart scale - max depth / planned runtime fix the chart's axes so
    # waypoints can be placed by clicking. Asked for in a popup on the
    # first chart click (DiveProfilePage.qml's scaleDialog), editable in
    # Dive settings afterwards.
    # ------------------------------------------------------------------

    @Property(bool, notify=settingsChanged)
    def scaleDefined(self):
        return bool(self.dive_plan.max_depth_m and self.dive_plan.planned_runtime_sec)

    @Property(str, notify=settingsChanged)
    def maxDepthText(self):
        return self._max_depth_text

    @maxDepthText.setter
    def maxDepthText(self, value):
        self._max_depth_text = value
        try:
            depth = float(value)
            if depth > 0:
                self.dive_plan.max_depth_m = depth
                self._persist("max_depth_m")
        except (TypeError, ValueError):
            pass
        self.settingsChanged.emit()
        self._resimulate()

    @Property(str, notify=settingsChanged)
    def runtimeText(self):
        return self._runtime_text

    @runtimeText.setter
    def runtimeText(self, value):
        self._runtime_text = value
        try:
            seconds = _parse_time_to_seconds(value)
            if seconds > 0:
                self.dive_plan.planned_runtime_sec = seconds
                self._persist("planned_runtime_sec")
        except (TypeError, ValueError):
            pass
        self.settingsChanged.emit()
        self._resimulate()

    @Slot(str, str, result=str)
    def defineScale(self, max_depth_text, runtime_text):
        """Popup OK handler. Returns an error message, or "" on success."""
        try:
            depth = float(max_depth_text)
        except (TypeError, ValueError):
            return "Enter the max depth in metres"
        if depth <= 0:
            return "Max depth must be greater than 0"
        try:
            seconds = _parse_time_to_seconds(runtime_text)
        except (TypeError, ValueError):
            return "Enter the planned runtime in minutes (or mm:ss)"
        if seconds <= 0:
            return "Planned runtime must be greater than 0"
        self.dive_plan.max_depth_m = depth
        self.dive_plan.planned_runtime_sec = seconds
        self._persist("max_depth_m")
        self._persist("planned_runtime_sec")
        self._max_depth_text = f"{depth:g}"
        self._runtime_text = _format_minutes(seconds)
        self.settingsChanged.emit()
        self._resimulate()
        return ""

    def _grow_runtime_for(self, runtime_sec):
        planned = self.dive_plan.planned_runtime_sec
        if not planned or runtime_sec < planned * RUNTIME_GROW_THRESHOLD:
            return
        grown = int(math.ceil(max(planned, runtime_sec) * RUNTIME_GROW_FACTOR / 300.0) * 300)
        self.dive_plan.planned_runtime_sec = grown
        self._persist("planned_runtime_sec")
        self._runtime_text = _format_minutes(grown)
        self.settingsChanged.emit()

    # ------------------------------------------------------------------
    # Gas table - ported close to verbatim from _dp_refresh_gas_table/
    # on_dp_gas_type_change/on_dp_add_gas/on_dp_remove_gas.
    # ------------------------------------------------------------------

    @Property(list, constant=True)
    def gasTypeList(self):
        return list(DIVE_PLAN_GAS_TYPES)

    @Property("QVariant", notify=gasesChanged)
    def gasTableRows(self):
        rows = []
        plan = self.dive_plan
        for g in plan.gases:
            if plan.is_ccr:
                kind = "DIL" if g.diluent else "BAILOUT"
            else:
                kind = g.gas_type.upper()
            tanks = g.tank_ref
            if plan.dive_type == "sidemount" and g.side:
                tanks += f" {GAS_SIDE_LABELS[g.side]}"
            rows.append([
                g.id,
                kind,
                f"{g.o2_percent:.0f}",
                f"{g.he_percent:.0f}",
                f"{tanks} {g.tank_size_l:g}L/{g.start_pressure_bar:g}",
                f"{self.dive_plan.gas_display_mod_m(g):.0f}",
                _format_gas_use(g),
            ])
        return rows

    @Property(list, notify=gasesChanged)
    def gasTableHeaders(self):
        return ["Name", "Type", "O2%", "He%", "Tank L/bar", "MOD", "Use"]

    @Property(list, notify=gasesChanged)
    def gasIdList(self):
        return [g.id for g in self.dive_plan.breathed_gases()]

    @Property(str, notify=gasFieldsChanged)
    def gasNameText(self):
        return self._gas_name_text

    @gasNameText.setter
    def gasNameText(self, value):
        self._gas_name_text = value
        self.gasFieldsChanged.emit()

    @Property(str, notify=gasFieldsChanged)
    def gasType(self):
        return self._gas_type

    @Slot(str)
    def onGasTypeSelected(self, value):
        self._gas_type = value
        self.gasFieldsChanged.emit()

    @Property(bool, notify=gasFieldsChanged)
    def gasDiluent(self):
        return self._gas_diluent

    @gasDiluent.setter
    def gasDiluent(self, value):
        self._gas_diluent = bool(value)
        self.gasFieldsChanged.emit()

    @Property(list, constant=True)
    def gasSideList(self):
        return list(GAS_SIDE_LABELS.values())

    @Property(str, notify=gasFieldsChanged)
    def gasSideLabel(self):
        return GAS_SIDE_LABELS[self._gas_side]

    @Slot(str)
    def onGasSideSelected(self, label):
        self._gas_side = next((k for k, v in GAS_SIDE_LABELS.items() if v == label), "")
        self.gasFieldsChanged.emit()

    @Property(str, notify=gasFieldsChanged)
    def gasO2Text(self):
        return self._gas_o2_text

    @gasO2Text.setter
    def gasO2Text(self, value):
        self._gas_o2_text = value
        self.gasFieldsChanged.emit()

    @Property(str, notify=gasFieldsChanged)
    def gasHeText(self):
        return self._gas_he_text

    @gasHeText.setter
    def gasHeText(self, value):
        self._gas_he_text = value
        self.gasFieldsChanged.emit()

    @Property(str, notify=gasFieldsChanged)
    def gasTankText(self):
        return self._gas_tank_text

    @gasTankText.setter
    def gasTankText(self, value):
        self._gas_tank_text = value
        self.gasFieldsChanged.emit()

    @Property(str, notify=gasFieldsChanged)
    def gasVolumeText(self):
        return self._gas_volume_text

    @gasVolumeText.setter
    def gasVolumeText(self, value):
        self._gas_volume_text = value
        self.gasFieldsChanged.emit()

    @Property(str, notify=gasFieldsChanged)
    def gasStartPressureText(self):
        return self._gas_start_pressure_text

    @gasStartPressureText.setter
    def gasStartPressureText(self, value):
        self._gas_start_pressure_text = value
        self.gasFieldsChanged.emit()

    @Property(str, notify=gasFieldsChanged)
    def gasMinDepthText(self):
        return self._gas_min_depth_text

    @gasMinDepthText.setter
    def gasMinDepthText(self, value):
        self._gas_min_depth_text = value
        self.gasFieldsChanged.emit()

    @Property(str, notify=gasFieldsChanged)
    def gasMaxDepthText(self):
        return self._gas_max_depth_text

    @gasMaxDepthText.setter
    def gasMaxDepthText(self, value):
        self._gas_max_depth_text = value
        self.gasFieldsChanged.emit()

    @Property(list, constant=True)
    def gasPhaseList(self):
        return list(GAS_PHASE_LABELS.values())

    @Property(str, notify=gasFieldsChanged)
    def gasPhaseLabel(self):
        return GAS_PHASE_LABELS[self._gas_phase]

    @Slot(str)
    def onGasPhaseSelected(self, label):
        self._gas_phase = next((k for k, v in GAS_PHASE_LABELS.items() if v == label), "any")
        self.gasFieldsChanged.emit()

    @Property(list, constant=True)
    def gasColorPalette(self):
        return list(GAS_COLORS)

    @Property(list, notify=gasesChanged)
    def gasColors(self):
        """Line colour per gas-table row (parallel to gasTableRows)."""
        return [gas_color(self.dive_plan, g.id) for g in self.dive_plan.gases]

    @Property(str, notify=gasFieldsChanged)
    def gasColor(self):
        return self._gas_color or next_free_gas_color(self.dive_plan)

    @Slot(str)
    def onGasColorSelected(self, color):
        self._gas_color = color
        self.gasFieldsChanged.emit()

    @Slot(int, str)
    def setGasColor(self, row, color):
        """Recolours an existing gas straight from its table swatch."""
        if 0 <= row < len(self.dive_plan.gases):
            self.dive_plan.gases[row].color = color
            self.gasesChanged.emit()
            self.waypointsChanged.emit()
            self.gasFieldsChanged.emit()
            self._update_cursor_info()
            self._redraw()

    # Gas editor - a selected table row is edited in place by Update
    # (renames included); with nothing selected (newGas) Add always adds.
    # Keyed by gas id so removing another gas can't shift the selection.

    def _editing_gas_index(self):
        if self._editing_gas_id is None:
            return -1
        return next((i for i, g in enumerate(self.dive_plan.gases) if g.id == self._editing_gas_id), -1)

    @Property(int, notify=gasFieldsChanged)
    def selectedGasRow(self):
        return self._editing_gas_index()

    @Slot(int)
    def selectGasRow(self, row):
        """Loads a gas into the entry fields and selects it for Update."""
        if row < 0 or row >= len(self.dive_plan.gases):
            return
        g = self.dive_plan.gases[row]
        self._editing_gas_id = g.id
        self._load_gas_fields(g)
        self._gas_status_text = ""
        self.statusChanged.emit()

    def _load_gas_fields(self, g):
        self._gas_name_text = g.id
        self._gas_type = next((t for t in DIVE_PLAN_GAS_TYPES if t.lower() == g.gas_type), "Air")
        self._gas_o2_text = f"{g.o2_percent:g}"
        self._gas_he_text = f"{g.he_percent:g}"
        self._gas_diluent = g.diluent
        self._gas_side = g.side or ""
        self._gas_tank_text = g.tank_ref
        self._gas_volume_text = f"{g.tank_size_l:g}"
        self._gas_start_pressure_text = f"{g.start_pressure_bar:g}"
        self._gas_min_depth_text = f"{g.use_min_depth_m:g}" if g.use_min_depth_m is not None else ""
        self._gas_max_depth_text = f"{g.use_max_depth_m:g}" if g.use_max_depth_m is not None else ""
        self._gas_phase = g.use_phase
        self._gas_color = gas_color(self.dive_plan, g.id)
        self.gasFieldsChanged.emit()

    def _next_free_tank(self):
        """First of T1, T2, ... no gas uses yet - each new gas gets its own
        tank, since UDDF tank pressures are recorded per tank name."""
        used = {g.tank_ref for g in self.dive_plan.gases}
        n = 1
        while f"T{n}" in used:
            n += 1
        return f"T{n}"

    @Slot()
    def newGas(self):
        """Deselects the table so the next Add creates a new gas."""
        self._editing_gas_id = None
        self._gas_name_text = ""
        self._gas_type = "Air"
        self._gas_o2_text = "21"
        self._gas_he_text = "0"
        # A new gas is the diluent when the dive has none yet.
        self._gas_diluent = self.dive_plan.is_ccr and self.dive_plan.diluent_gas() is None
        self._gas_side = ""
        if self.dive_plan.dive_type == "sidemount":
            # The sidemount side still missing: left first, then the right
            # tank, offered as a twin of the left one so one Add completes it.
            left = next((g for g in self.dive_plan.gases if g.side == "left"), None)
            right = next((g for g in self.dive_plan.gases if g.side == "right"), None)
            if left is None:
                self._gas_side = "left"
            elif right is None:
                self._gas_side = "right"
                self._gas_name_text = f"{left.id} R"
                self._gas_type = next((t for t in DIVE_PLAN_GAS_TYPES if t.lower() == left.gas_type), "Air")
                self._gas_o2_text = f"{left.o2_percent:g}"
                self._gas_he_text = f"{left.he_percent:g}"
        self._gas_tank_text = self._next_free_tank()
        self._gas_volume_text = DEFAULT_TANK_VOLUME_TEXT
        self._gas_start_pressure_text = DEFAULT_START_PRESSURE_TEXT
        self._gas_min_depth_text = ""
        self._gas_max_depth_text = ""
        self._gas_phase = "any"
        self._gas_color = ""  # "" = next free palette colour on add
        self._gas_status_text = ""
        self.gasFieldsChanged.emit()
        self.statusChanged.emit()

    @Property(str, notify=statusChanged)
    def gasStatusText(self):
        return self._gas_status_text

    def _gas_error(self, message):
        self._gas_status_text = message
        self.statusChanged.emit()

    @Slot()
    def addGas(self):
        """Add/Update button: updates the selected gas, or adds a new one
        when nothing is selected."""
        editing = self._editing_gas_index()
        action = "update" if editing >= 0 else "add"
        name = self._gas_name_text.strip() or (
            self.dive_plan.gases[editing].id if editing >= 0 else f"Gas {len(self.dive_plan.gases) + 1}"
        )
        clash = next((i for i, g in enumerate(self.dive_plan.gases) if g.id == name), None)
        if clash is not None and clash != editing:
            self._gas_error(f"Could not {action} gas: another gas is already named '{name}'")
            return
        try:
            fields = dict(
                id=name,
                gas_type=self._gas_type.lower(),
                o2_percent=float(self._gas_o2_text),
                he_percent=float(self._gas_he_text or 0.0),
                diluent=self._gas_diluent,
                side=self._gas_side or None,
                tank_ref=self._gas_tank_text.strip() or self._next_free_tank(),
                tank_size_l=float(self._gas_volume_text),
                start_pressure_bar=float(self._gas_start_pressure_text),
                use_min_depth_m=_parse_optional_depth(self._gas_min_depth_text),
                use_max_depth_m=_parse_optional_depth(self._gas_max_depth_text),
                use_phase=self._gas_phase,
                color=self._gas_color or next_free_gas_color(self.dive_plan),
            )
            # Update keeps what the editor doesn't show (a per-gas SAC
            # override) from the gas being edited.
            base = self.dive_plan.gases[editing].model_dump() if editing >= 0 else {}
            gas = PlannedGas(**{**base, **fields})
            if (gas.use_min_depth_m is not None and gas.use_max_depth_m is not None
                    and gas.use_min_depth_m > gas.use_max_depth_m):
                raise ValueError("the 'from' depth must be shallower than the 'to' depth")
        except (TypeError, ValueError, ValidationError) as e:
            self._gas_error(f"Could not {action} gas: {e}")
            return

        if self.dive_plan.dive_type == "sidemount" and gas.side:
            error = self._sidemount_side_error(gas, editing)
            if error:
                self._gas_error(f"Could not {action} gas: {error}")
                return

        if gas.diluent:
            # One loop per dive - the new diluent replaces the old one.
            for other in self.dive_plan.gases:
                other.diluent = False

        if editing >= 0:
            old_id = self.dive_plan.gases[editing].id
            self.dive_plan.gases[editing] = gas
            twin = self._sidemount_twin(gas)
            if twin is not None:
                # Both sides hold the same gas - a new mix goes into both.
                twin.gas_type, twin.o2_percent, twin.he_percent = gas.gas_type, gas.o2_percent, gas.he_percent
            if old_id != gas.id:
                for wp in self.dive_plan.waypoints:
                    if wp.gas_id == old_id:
                        wp.gas_id = gas.id
            self._editing_gas_id = gas.id  # stays selected for further edits
            self._load_gas_fields(gas)
            self.waypointsChanged.emit()  # name / colour may have changed
        else:
            self.dive_plan.gases.append(gas)
            self.newGas()

        self._gas_status_text = ""
        # MOD at the user's own PO2 limit for the phase the gas is used in;
        # auto gas choice caps the range there anyway.
        phase = "ascent" if gas.use_phase == "ascent" else "descent"
        mod = self.dive_plan.gas_mod_m(gas, phase)
        if mod is not None and gas.use_max_depth_m is not None and gas.use_max_depth_m > mod:
            self._gas_status_text = (
                f"Note: {name}'s range goes to {gas.use_max_depth_m:g}m but its MOD at PO2 "
                f"{self.dive_plan.max_po2_for(phase):g} is {mod:g}m - it will only be used from {mod:g}m"
            )
        self.gasFieldsChanged.emit()
        self.statusChanged.emit()
        self.gasesChanged.emit()
        self._resimulate()

    def _sidemount_twin(self, gas):
        """The other sidemount tank of `gas` (by side), if there is one."""
        if self.dive_plan.dive_type != "sidemount" or not gas.side:
            return None
        other = "right" if gas.side == "left" else "left"
        return next((g for g in self.dive_plan.gases if g.side == other and g.id != gas.id), None)

    def _sidemount_side_error(self, gas, editing):
        """One left and one right tank per dive, of the same gas, in tanks
        of their own."""
        side = GAS_SIDE_LABELS[gas.side].lower()
        taken = next((g for i, g in enumerate(self.dive_plan.gases) if g.side == gas.side and i != editing), None)
        if taken is not None:
            return f"{taken.id} is already the {side} tank"
        twin = self._sidemount_twin(gas)
        if twin is None:
            return None
        if twin.tank_ref == gas.tank_ref:
            return f"the left and right tanks need tanks of their own ({twin.id} is in {twin.tank_ref})"
        if editing < 0 and (twin.o2_percent, twin.he_percent) != (gas.o2_percent, gas.he_percent):
            return (
                f"the left and right tanks must hold the same gas - {twin.id} is "
                f"{twin.o2_percent:g}/{twin.he_percent:g}"
            )
        return None

    @Slot(int)
    def removeGasAtRow(self, row):
        if row < 0 or row >= len(self.dive_plan.gases):
            return
        name = self.dive_plan.gases[row].id
        self.dive_plan.gases = [g for g in self.dive_plan.gases if g.id != name]
        for wp in self.dive_plan.waypoints:
            if wp.gas_id == name:
                wp.gas_auto = True
        if self._editing_gas_id == name:
            self.newGas()
        self.gasFieldsChanged.emit()
        self.gasesChanged.emit()
        self.waypointsChanged.emit()
        self._resimulate()

    # ------------------------------------------------------------------
    # Waypoint table - ported close to verbatim from
    # _dp_refresh_waypoint_table/on_dp_wp_select/
    # on_dp_add_or_update_waypoint/on_dp_remove_waypoint.
    # ------------------------------------------------------------------

    @Property(list, constant=True)
    def waypointHeaders(self):
        return ["Time", "Depth (m)", "Gas", "Rate (m/min)"]

    @Property("QVariant", notify=waypointsChanged)
    def waypointRows(self):
        rows = []
        for wp in self.dive_plan.sorted_waypoints():
            rows.append([
                _format_mmss(wp.runtime_sec),
                f"{wp.depth_m:.1f}",
                f"{wp.gas_id} (auto)" if wp.gas_auto else wp.gas_id,
                f"{wp.rate_m_per_min:.0f}" if wp.rate_m_per_min else "default",
            ])
        return rows

    @Property(list, notify=waypointsChanged)
    def waypointGasColors(self):
        """Line colour of each waypoint's gas (parallel to waypointRows)."""
        return [gas_color(self.dive_plan, wp.gas_id) for wp in self.dive_plan.sorted_waypoints()]

    @Property(str, notify=waypointFieldsChanged)
    def wpTimeText(self):
        return self._wp_time_text

    @wpTimeText.setter
    def wpTimeText(self, value):
        self._wp_time_text = value
        self.waypointFieldsChanged.emit()

    @Property(str, notify=waypointFieldsChanged)
    def wpDepthText(self):
        return self._wp_depth_text

    @wpDepthText.setter
    def wpDepthText(self, value):
        self._wp_depth_text = value
        self.waypointFieldsChanged.emit()

    @Property(list, notify=gasesChanged)
    def wpGasChoices(self):
        return [AUTO_GAS_LABEL] + [g.id for g in self.dive_plan.breathed_gases()]

    @Property(str, notify=waypointFieldsChanged)
    def wpGasText(self):
        return self._wp_gas_text

    @Slot(str)
    def onWpGasSelected(self, value):
        self._wp_gas_text = value
        self.waypointFieldsChanged.emit()

    @Property(str, notify=waypointFieldsChanged)
    def wpRateText(self):
        return self._wp_rate_text

    @wpRateText.setter
    def wpRateText(self, value):
        self._wp_rate_text = value
        self.waypointFieldsChanged.emit()

    @Property(str, notify=statusChanged)
    def wpStatusText(self):
        return self._wp_status_text

    def _clear_waypoint_inputs(self):
        self._editing_runtime = None
        self._end_dive_status_text = ""
        self._wp_time_text = ""
        self._wp_depth_text = ""
        self._wp_rate_text = ""
        self.waypointFieldsChanged.emit()

    @Slot(int)
    def selectWaypointRow(self, row):
        wps = self.dive_plan.sorted_waypoints()
        if row < 0 or row >= len(wps):
            return
        wp = wps[row]
        self._editing_runtime = wp.runtime_sec
        self._wp_time_text = _format_mmss(wp.runtime_sec)
        self._wp_depth_text = f"{wp.depth_m:g}"
        self._wp_gas_text = AUTO_GAS_LABEL if wp.gas_auto else wp.gas_id
        self._wp_rate_text = f"{wp.rate_m_per_min:g}" if wp.rate_m_per_min else ""
        self.waypointFieldsChanged.emit()

    @Slot()
    def addOrUpdateWaypoint(self):
        try:
            runtime_sec = _parse_time_to_seconds(self._wp_time_text)
            depth = float(self._wp_depth_text)
            if not self.dive_plan.gases:
                raise ValueError("Define a gas first")
            gas_auto = self._wp_gas_text in ("", AUTO_GAS_LABEL)
            gas_id = self.dive_plan.breathed_gases()[0].id if gas_auto else self._wp_gas_text
            rate_text = self._wp_rate_text.strip()
            rate = float(rate_text) if rate_text else None
            new_wp = PlannedWaypoint(
                runtime_sec=runtime_sec, depth_m=depth, gas_id=gas_id, rate_m_per_min=rate, gas_auto=gas_auto,
            )
        except (TypeError, ValueError, ValidationError) as e:
            self._wp_status_text = f"Could not save waypoint: {e}"
            self.statusChanged.emit()
            return

        editing = self._editing_runtime
        edited = next((w for w in self.dive_plan.waypoints if w.runtime_sec == editing), None)
        if edited is not None:
            new_wp.phase = edited.phase  # keep End dive's "ascent" marking
        self.dive_plan.waypoints = [
            w for w in self.dive_plan.waypoints if w.runtime_sec not in (editing, runtime_sec)
        ]
        self.dive_plan.waypoints.append(new_wp)
        self._wp_status_text = ""
        self.statusChanged.emit()
        self._clear_waypoint_inputs()
        self.waypointsChanged.emit()
        self._resimulate()

    @Slot(int)
    def removeWaypointAtRow(self, row):
        wps = self.dive_plan.sorted_waypoints()
        if row < 0 or row >= len(wps):
            return
        runtime_sec = wps[row].runtime_sec
        self.dive_plan.waypoints = [w for w in self.dive_plan.waypoints if w.runtime_sec != runtime_sec]
        self._clear_waypoint_inputs()
        self.waypointsChanged.emit()
        self._resimulate()

    # ------------------------------------------------------------------
    # Simulation / canvas - ported close to verbatim from _dp_resimulate/
    # _redraw_dive_profile_canvas/_dp_scrub.
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Click-to-place on the chart. QML's chart MouseArea decides what a
    # gesture is: press on a waypoint + drag -> moveWaypoint, short click on
    # empty space -> addWaypointAt, drag on empty space -> onScrub,
    # right-click on a waypoint -> removeWaypointAtRow. Indices are into
    # sorted_waypoints(), same as the table.
    # ------------------------------------------------------------------

    def _axes(self):
        return chart_axes(self.dive_plan, self.dive_profile_samples)

    def _snapped_point(self, x, y):
        axes = self._axes()
        if axes is None:
            return None
        time_sec, depth = point_from_xy(x, y, DIVE_PROFILE_CANVAS_WIDTH, DIVE_PROFILE_CANVAS_HEIGHT, axes)
        time_sec = int(round(time_sec / SNAP_TIME_SEC) * SNAP_TIME_SEC)
        depth = round(depth / SNAP_DEPTH_M) * SNAP_DEPTH_M
        return time_sec, depth

    @Slot(float, float, result=int)
    def waypointIndexAt(self, x, y):
        axes = self._axes()
        if axes is None:
            return -1
        best, best_dist = -1, WAYPOINT_HIT_RADIUS_PX
        for i, wp in enumerate(self.dive_plan.sorted_waypoints()):
            wx, wy = xy_of(wp.runtime_sec, wp.depth_m, DIVE_PROFILE_CANVAS_WIDTH, DIVE_PROFILE_CANVAS_HEIGHT, axes)
            dist = math.hypot(wx - x, wy - y)
            if dist <= best_dist:
                best, best_dist = i, dist
        return best

    @Slot(float, float)
    def addWaypointAt(self, x, y):
        if not self.dive_plan.gases:
            self._wp_status_text = "Define a gas first"
            self.statusChanged.emit()
            return
        point = self._snapped_point(x, y)
        if point is None:
            return
        runtime_sec, depth = point
        self.dive_plan.waypoints = [w for w in self.dive_plan.waypoints if w.runtime_sec != runtime_sec]
        self.dive_plan.waypoints.append(
            PlannedWaypoint(runtime_sec=runtime_sec, depth_m=depth, gas_id=self.dive_plan.breathed_gases()[0].id, gas_auto=True)
        )
        self._grow_runtime_for(runtime_sec)
        self._wp_status_text = ""
        self.statusChanged.emit()
        self._clear_waypoint_inputs()
        self.waypointsChanged.emit()
        self._resimulate()

    @Slot(int, float, float)
    def moveWaypoint(self, row, x, y):
        """Drag handler. Time is kept strictly between the neighbouring
        waypoints so the dragged point never swaps order (row stays valid for
        the whole drag); the axes are left alone until dropWaypoint."""
        wps = self.dive_plan.sorted_waypoints()
        if row < 0 or row >= len(wps):
            return
        point = self._snapped_point(x, y)
        if point is None:
            return
        runtime_sec, depth = point
        low = wps[row - 1].runtime_sec + SNAP_TIME_SEC if row > 0 else 0
        high = wps[row + 1].runtime_sec - SNAP_TIME_SEC if row + 1 < len(wps) else None
        runtime_sec = max(low, runtime_sec)
        if high is not None:
            runtime_sec = min(high, runtime_sec)
        wp = wps[row]
        if (wp.runtime_sec, wp.depth_m) == (runtime_sec, depth):
            return
        wp.runtime_sec = runtime_sec
        wp.depth_m = depth
        self._dragging = True
        self.waypointsChanged.emit()
        self._redraw()

    @Slot(int)
    def dropWaypoint(self, row):
        self._dragging = False
        wps = self.dive_plan.sorted_waypoints()
        if 0 <= row < len(wps):
            self._grow_runtime_for(wps[row].runtime_sec)
        self._clear_waypoint_inputs()
        self._resimulate()

    @Property(str, notify=statusChanged)
    def endDiveStatusText(self):
        return self._end_dive_status_text

    @Slot()
    def endDive(self):
        """Appends the ascent from the last waypoint to the surface:
        3m/3min safety stop when no deco is needed, otherwise the deco
        schedule (utils.dive_plan_engine.plan_ascent)."""
        wps = self.dive_plan.sorted_waypoints()
        if not wps:
            message = "Place at least one waypoint before ending the dive"
        elif wps[-1].depth_m <= 0:
            message = "The dive already ends at the surface - remove the last waypoint(s) to re-plan the ascent"
        else:
            message = "Nothing to add - the ascent planner returned no waypoints"
            try:
                ascent, deco_needed, stops = plan_ascent(self.dive_plan)
            except ValueError as e:
                ascent, deco_needed, stops = [], False, []
                message = f"Could not plan the ascent: {e}"
            if ascent:
                self.dive_plan.waypoints.extend(ascent)
                self._grow_runtime_for(ascent[-1].runtime_sec)
                surfaced = _format_mmss(ascent[-1].runtime_sec)
                if deco_needed:
                    parts, current_gas = [], wps[-1].gas_id
                    for d, sec, gas_id in stops:
                        switch = f" {gas_id}" if gas_id != current_gas else ""
                        current_gas = gas_id
                        parts.append(f"{d:g}m {sec // 60}min{switch}")
                    stop_list = ", ".join(parts)
                    message = f"Deco ascent added: {stop_list} - surfacing at {surfaced}"
                else:
                    message = f"No deco needed - 3m/3min safety stop added, surfacing at {surfaced}"
                self._clear_waypoint_inputs()
                self.waypointsChanged.emit()
                self._resimulate()
        self._end_dive_status_text = message
        self.statusChanged.emit()

    def _resimulate(self):
        self._deco_plan_cache = {}
        before = [wp.gas_id for wp in self.dive_plan.sorted_waypoints()]
        gas_warnings = apply_auto_gases(self.dive_plan)
        if [wp.gas_id for wp in self.dive_plan.sorted_waypoints()] != before:
            self.waypointsChanged.emit()
        try:
            samples, warnings = simulate_dive_plan(self.dive_plan, resolution_sec=10)
        except ValueError as e:
            samples, warnings = [], [str(e)]
        warnings = gas_warnings + warnings
        self.dive_profile_samples = samples
        self.dive_deco_schedules = (
            deco_schedule_timeline(self.dive_plan) if any(s.ceiling_m > 0 for s in samples) else []
        )
        self.dive_profile_warnings = warnings
        if warnings:
            self._status_text = " | ".join(warnings)
            self._status_is_error = True
        elif samples:
            max_depth = max(s.depth_m for s in samples)
            self._status_text = (
                f"{len(samples)} samples · max depth {max_depth:.0f}m · "
                f"runtime {_format_mmss(samples[-1].time_sec)}"
            )
            self._status_is_error = False
        else:
            self._status_text = "Click in the chart to place the first waypoint"
            self._status_is_error = False
        self.statusChanged.emit()
        self._redraw()

    @Property(str, notify=statusChanged)
    def statusText(self):
        return self._status_text

    @Property(bool, notify=statusChanged)
    def statusIsError(self):
        return self._status_is_error

    def _redraw(self):
        self._preview_revision += 1
        self.previewChanged.emit()

    @Property(str, notify=previewChanged)
    def previewImageSource(self):
        return f"image://diveprofilepreview/frame?r={self._preview_revision}"

    def render_current_frame(self):
        image = render_profile_image(
            self.dive_plan, self.dive_profile_samples,
            DIVE_PROFILE_CANVAS_WIDTH, DIVE_PROFILE_CANVAS_HEIGHT,
            cursor_time=self.dive_profile_cursor_time,
            waypoints_only=self._dragging,
            show_readout=False,
            deco_schedules=self.dive_deco_schedules,
            deco_schedule_interval_sec=DECO_SCHEDULE_INTERVAL_SEC,
        )
        rgb = image.convert("RGB")
        w, h = rgb.width, rgb.height
        qimage = QImage(rgb.tobytes("raw", "RGB"), w, h, w * 3, QImage.Format.Format_RGB888)
        return qimage.copy()

    # ------------------------------------------------------------------
    # Hover readout - the QML page shows cursorInfo in a box next to the
    # mouse; the image only draws the cursor line/marker.
    # ------------------------------------------------------------------

    @Property("QVariant", notify=cursorChanged)
    def cursorInfo(self):
        """[{label, value, color}] for the sample under the cursor; empty
        when the mouse isn't over the profile."""
        return self._cursor_info

    def _phase_at(self, time_sec):
        wps = self.dive_plan.sorted_waypoints()
        for wp, phase in zip(wps, waypoint_phases(wps)):
            if wp.runtime_sec >= time_sec:
                return phase
        return "ascent"

    def _update_cursor_info(self):
        sample = None
        if self.dive_profile_cursor_time is not None:
            sample = nearest_sample(self.dive_profile_samples, self.dive_profile_cursor_time)
        if sample is None:
            self._cursor_info = []
            self.cursorChanged.emit()
            return
        normal, good, bad = "#E0E0E0", "#22C55E", "#EF4444"
        gas = self.dive_plan.gas_by_id(sample.gas_id)
        phase = self._phase_at(sample.time_sec)
        po2_limit = self.dive_plan.max_po2_for(phase)
        on_loop = gas is not None and self.dive_plan.on_loop(gas)
        po2_over = gas is not None and not on_loop and sample.po2 > po2_limit + 0.005
        info = [
            {"label": "Time", "value": _format_mmss(sample.time_sec), "color": normal},
            {"label": "Depth", "value": f"{sample.depth_m:.1f} m", "color": normal},
            {"label": "Gas", "value": sample.gas_id, "color": gas_color(self.dive_plan, sample.gas_id)},
            {"label": "PO2", "value": f"{sample.po2:.2f} bar (max {po2_limit:g})", "color": bad if po2_over else normal},
        ]
        if self.dive_plan.is_ccr:
            loop = f"SP {self.dive_plan.setpoint_at(sample.depth_m):g}" if on_loop else "Bailout (OC)"
            info.append({"label": "Loop", "value": loop, "color": normal if on_loop else bad})
        if sample.ceiling_m > 0:
            # Full schedule if the ascent started here - End dive's planner,
            # gas switches included (sample.stop_* only has the first stop).
            if sample.time_sec not in self._deco_plan_cache:
                try:
                    self._deco_plan_cache[sample.time_sec] = ascent_from_time(self.dive_plan, sample.time_sec)
                except ValueError:
                    self._deco_plan_cache[sample.time_sec] = (False, [], sample.tts_sec)
            _, stops, tts = self._deco_plan_cache[sample.time_sec]
            # GF high decides whether the diver may surface (the chart's red
            # area); GF low places the first stop - so the stops below can
            # sit deeper than the GF-high ceiling.
            info.append({
                "label": "Ceiling",
                "value": f"{sample.ceiling_m:.1f} m (GF {self.dive_plan.gf_high:g}) · "
                         f"{sample.ceiling_gf_low_m:.1f} m (GF {self.dive_plan.gf_low:g})",
                "color": bad,
            })
            current_gas = sample.gas_id
            for i, (depth, seconds, gas_id) in enumerate(stops):
                switch = f"  → {gas_id}" if gas_id != current_gas else ""
                current_gas = gas_id
                info.append({
                    "label": "Deco stops" if i == 0 else "",
                    "value": f"{depth:g} m  {seconds // 60} min{switch}",
                    "color": gas_color(self.dive_plan, gas_id) if switch else bad,
                })
            info.append({"label": "TTS", "value": _format_mmss(tts), "color": normal})
        else:
            ndl = "99+ min" if sample.ndl_sec is None else f"{sample.ndl_sec // 60} min"
            info.append({"label": "NDL", "value": ndl, "color": good})
        info += [
            {"label": "CNS", "value": f"{sample.cns_pct:.0f} %", "color": normal},
        ]
        # The tanks of the gas breathed (both of a sidemount pair, the one in
        # use marked) plus a CCR's O2 cylinder while on the loop.
        refs = self.dive_plan.tank_refs_for(gas) if gas is not None else [sample.tank_ref]
        if on_loop:
            refs = [t.ref for t in self.dive_plan.tank_specs() if t.role == "oxygen"] + refs
        tanks = [
            f"{'▸' if ref == sample.tank_ref and len(refs) > 1 else ''}{ref} {sample.tank_pressures[ref]:.0f}"
            for ref in refs if ref in sample.tank_pressures
        ]
        info.append({
            "label": "Tanks" if len(tanks) > 1 else "Tank",
            "value": ("  ".join(tanks) + " bar") if tanks else f"{sample.tank_pressure_bar:.0f} bar",
            "color": normal,
        })
        self._cursor_info = info
        self.cursorChanged.emit()

    @Slot()
    def clearCursor(self):
        self.dive_profile_cursor_time = None
        self._update_cursor_info()
        self._redraw()

    @Slot(float)
    def onScrub(self, x):
        axes = self._axes()
        if not self.dive_profile_samples or axes is None:
            return
        self.dive_profile_cursor_time, _ = point_from_xy(
            x, 0.0, DIVE_PROFILE_CANVAS_WIDTH, DIVE_PROFILE_CANVAS_HEIGHT, axes
        )
        self._update_cursor_info()
        self._redraw()

    # ------------------------------------------------------------------
    # Save - the profile as a dive log file, format by LOG_FORMATS.
    # ------------------------------------------------------------------

    def write_log(self, path):
        """Simulates the plan at full resolution and writes it to `path`,
        in the format its extension names (LOG_FORMATS). Returns the
        simulation warnings; raises ValueError when it can't be written."""
        writer = next((w for ext, w in LOG_FORMATS.values() if ext == Path(path).suffix.lower()), None)
        if writer is None:
            raise ValueError(f"Unknown log format '{Path(path).suffix}' - use .uddf, .fit or .ssrf")
        if self._log_error_text:
            raise ValueError(self._log_error_text)
        self.dive_plan.name = self._name_text.strip() or self.dive_plan.name
        samples, warnings = simulate_dive_plan(self.dive_plan, resolution_sec=1)
        if not samples:
            raise ValueError("Add at least one waypoint first")
        writer(self.dive_plan, samples, Path(path))
        return warnings

    @Slot()
    def saveLog(self):
        from PySide6.QtWidgets import QFileDialog, QMessageBox

        chosen = get_fields().get(LOG_FORMAT_FIELD)
        if chosen not in LOG_FORMATS:
            chosen = next(iter(LOG_FORMATS))
        base = self._name_text.strip().replace(" ", "_") or "dive_profile"
        path, chosen = QFileDialog.getSaveFileName(
            None, "Save dive log", base + LOG_FORMATS[chosen][0], ";;".join(LOG_FORMATS), chosen,
        )
        if not path:
            return
        if chosen in LOG_FORMATS:
            set_field(LOG_FORMAT_FIELD, chosen)
            if Path(path).suffix.lower() not in {ext for ext, _ in LOG_FORMATS.values()}:
                path += LOG_FORMATS[chosen][0]

        try:
            warnings = self.write_log(path)
        except Exception as e:
            QMessageBox.critical(None, "Save failed", str(e))
            return

        message = f"Dive log written to:\n{path}"
        if warnings:
            message += f"\n\n{len(warnings)} warning(s):\n" + "\n".join(warnings)
        QMessageBox.information(None, "Saved", message)


class DiveProfilePreviewImageProvider(QQuickImageProvider):
    def __init__(self, backend: DiveProfileBackend):
        super().__init__(QQuickImageProvider.ImageType.Image)
        self._backend = backend

    def requestImage(self, id, size, requestedSize):
        return self._backend.render_current_frame()
