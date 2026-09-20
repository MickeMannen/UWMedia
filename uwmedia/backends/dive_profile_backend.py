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

Canvas scrubbing forwards raw press/move/release x-coordinates from a
QML MouseArea, same mechanism Color's own preview and Phase 0's spike
established - mouseTracking is deliberately not requested here (button-
gated only), matching the old Widgets page's own eventFilter semantics.

No settings persistence - matches the old Widgets page's own docstring
(checked directly against PERSISTED_TEXT_FIELDS/PERSISTED_SELECTION_FIELDS/
PERSISTED_SWITCH_FIELDS in uwmedia/app.py: none of this page's fields are
persisted in the Toga app either).
"""
from pathlib import Path

from pydantic import ValidationError
from PySide6.QtCore import Property, QObject, Signal, Slot
from PySide6.QtGui import QImage
from PySide6.QtQuick import QQuickImageProvider

from gui.dive_profile_view import render_profile_image, time_from_x
from models.dive_plan import DiveProfilePlan, PlannedGas, PlannedWaypoint
from parsers.uddf_writer import write_uddf
from utils.dive_plan_engine import simulate as simulate_dive_plan

DIVE_PLAN_GAS_TYPES = ("Air", "Nitrox", "Trimix", "CCR")
DIVE_PROFILE_CANVAS_WIDTH = 700
DIVE_PROFILE_CANVAS_HEIGHT = 420


def _default_plan():
    return DiveProfilePlan(gases=[PlannedGas(id="Air", gas_type="air", o2_percent=21.0)])


def _format_mmss(seconds):
    seconds = max(0, int(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


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

    def __init__(self):
        super().__init__()

        self.dive_plan = _default_plan()
        self.dive_profile_samples = []
        self.dive_profile_warnings = []
        self.dive_profile_cursor_time = None
        self._preview_revision = 0

        self._name_text = self.dive_plan.name
        self._gf_low = int(self.dive_plan.gf_low)
        self._gf_high = int(self.dive_plan.gf_high)
        self._descent_rate_text = str(self.dive_plan.default_descent_rate)
        self._ascent_rate_text = str(self.dive_plan.default_ascent_rate)
        self._water_temp_text = str(self.dive_plan.water_temp_c)

        self._gas_name_text = ""
        self._gas_type = "Air"
        self._gas_o2_text = "21"
        self._gas_he_text = "0"
        self._gas_setpoint_text = "1.3"
        self._gas_tank_text = "T1"
        self._gas_status_text = ""

        self._wp_time_text = ""
        self._wp_depth_text = ""
        self._wp_gas_text = ""
        self._wp_rate_text = ""
        self._wp_status_text = ""
        self._editing_runtime = None

        self._status_text = "Add waypoints to preview the profile"
        self._status_is_error = False

        self._redraw()

    # ------------------------------------------------------------------
    # Dive settings
    # ------------------------------------------------------------------

    @Property(str, notify=settingsChanged)
    def nameText(self):
        return self._name_text

    @nameText.setter
    def nameText(self, value):
        self._name_text = value
        self.settingsChanged.emit()

    @Property(int, notify=settingsChanged)
    def gfLow(self):
        return self._gf_low

    @Property(int, notify=settingsChanged)
    def gfHigh(self):
        return self._gf_high

    @Property(str, notify=settingsChanged)
    def gfLabel(self):
        return f"{self._gf_low}/{self._gf_high}"

    @Slot(int, int)
    def onGfChanged(self, low, high):
        self._gf_low = low
        self._gf_high = high
        self.dive_plan.gf_low = low
        self.dive_plan.gf_high = high
        self.settingsChanged.emit()
        self._resimulate()

    @Property(str, notify=settingsChanged)
    def descentRateText(self):
        return self._descent_rate_text

    @descentRateText.setter
    def descentRateText(self, value):
        self._descent_rate_text = value
        try:
            self.dive_plan.default_descent_rate = float(value)
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
            self.dive_plan.default_ascent_rate = float(value)
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
        except (TypeError, ValueError):
            pass
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
        for g in self.dive_plan.gases:
            rows.append([
                g.id,
                g.gas_type.upper(),
                f"{g.o2_percent:.0f}",
                f"{g.he_percent:.0f}",
                f"{g.ccr_setpoint:.2f}" if g.ccr_setpoint else "-",
                g.tank_ref,
                f"{g.mod_m:.0f}",
            ])
        return rows

    @Property(list, notify=gasesChanged)
    def gasTableHeaders(self):
        return ["Name", "Type", "O2%", "He%", "Setpoint", "Tank", "MOD (m)"]

    @Property(list, notify=gasesChanged)
    def gasIdList(self):
        return [g.id for g in self.dive_plan.gases]

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
    def setpointEnabled(self):
        return self._gas_type == "CCR"

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
    def gasSetpointText(self):
        return self._gas_setpoint_text

    @gasSetpointText.setter
    def gasSetpointText(self, value):
        self._gas_setpoint_text = value
        self.gasFieldsChanged.emit()

    @Property(str, notify=gasFieldsChanged)
    def gasTankText(self):
        return self._gas_tank_text

    @gasTankText.setter
    def gasTankText(self, value):
        self._gas_tank_text = value
        self.gasFieldsChanged.emit()

    @Property(str, notify=statusChanged)
    def gasStatusText(self):
        return self._gas_status_text

    @Slot()
    def addGas(self):
        name = self._gas_name_text.strip() or f"Gas {len(self.dive_plan.gases) + 1}"
        if any(g.id == name for g in self.dive_plan.gases):
            self._gas_status_text = f"A gas named '{name}' already exists"
            self.statusChanged.emit()
            return
        try:
            gas_type = self._gas_type.lower()
            setpoint = None
            if gas_type == "ccr":
                setpoint = float(self._gas_setpoint_text)
            gas = PlannedGas(
                id=name,
                gas_type=gas_type,
                o2_percent=float(self._gas_o2_text),
                he_percent=float(self._gas_he_text or 0.0),
                ccr_setpoint=setpoint,
                tank_ref=(self._gas_tank_text or "T1").strip(),
            )
        except (TypeError, ValueError, ValidationError) as e:
            self._gas_status_text = f"Could not add gas: {e}"
            self.statusChanged.emit()
            return
        self.dive_plan.gases.append(gas)
        self._gas_name_text = ""
        self._gas_status_text = ""
        self.gasFieldsChanged.emit()
        self.statusChanged.emit()
        self.gasesChanged.emit()
        self._resimulate()

    @Slot(int)
    def removeGasAtRow(self, row):
        if row < 0 or row >= len(self.dive_plan.gases):
            return
        name = self.dive_plan.gases[row].id
        self.dive_plan.gases = [g for g in self.dive_plan.gases if g.id != name]
        self.gasesChanged.emit()
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
                wp.gas_id,
                f"{wp.rate_m_per_min:.0f}" if wp.rate_m_per_min else "default",
            ])
        return rows

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
        self._wp_gas_text = wp.gas_id
        self._wp_rate_text = f"{wp.rate_m_per_min:g}" if wp.rate_m_per_min else ""
        self.waypointFieldsChanged.emit()

    @Slot()
    def addOrUpdateWaypoint(self):
        try:
            runtime_sec = _parse_time_to_seconds(self._wp_time_text)
            depth = float(self._wp_depth_text)
            gas_id = self._wp_gas_text
            if not gas_id:
                raise ValueError("Define a gas first")
            rate_text = self._wp_rate_text.strip()
            rate = float(rate_text) if rate_text else None
            new_wp = PlannedWaypoint(runtime_sec=runtime_sec, depth_m=depth, gas_id=gas_id, rate_m_per_min=rate)
        except (TypeError, ValueError, ValidationError) as e:
            self._wp_status_text = f"Could not save waypoint: {e}"
            self.statusChanged.emit()
            return

        editing = self._editing_runtime
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

    def _resimulate(self):
        try:
            samples, warnings = simulate_dive_plan(self.dive_plan, resolution_sec=60)
        except ValueError as e:
            samples, warnings = [], [str(e)]
        self.dive_profile_samples = samples
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
            self._status_text = "Add waypoints to preview the profile"
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
        )
        rgb = image.convert("RGB")
        w, h = rgb.width, rgb.height
        qimage = QImage(rgb.tobytes("raw", "RGB"), w, h, w * 3, QImage.Format.Format_RGB888)
        return qimage.copy()

    @Slot(float)
    def onScrub(self, x):
        if not self.dive_profile_samples:
            return
        max_time = max(s.time_sec for s in self.dive_profile_samples) or 1
        self.dive_profile_cursor_time = time_from_x(x, DIVE_PROFILE_CANVAS_WIDTH, max_time)
        self._redraw()

    # ------------------------------------------------------------------
    # Save - ported close to verbatim from on_dp_save_uddf.
    # ------------------------------------------------------------------

    @Slot()
    def saveAsUddf(self):
        from PySide6.QtWidgets import QFileDialog, QMessageBox

        self.dive_plan.name = self._name_text or self.dive_plan.name
        try:
            samples, warnings = simulate_dive_plan(self.dive_plan, resolution_sec=1)
        except ValueError as e:
            QMessageBox.critical(None, "Cannot save", str(e))
            return
        if not samples:
            QMessageBox.critical(None, "Cannot save", "Add at least one waypoint first")
            return

        suggested = f"{self.dive_plan.name.strip().replace(' ', '_') or 'dive_profile'}.uddf"
        path, _ = QFileDialog.getSaveFileName(None, "Save dive profile as UDDF", suggested, "UDDF files (*.uddf)")
        if not path:
            return

        try:
            write_uddf(self.dive_plan, samples, Path(path))
        except Exception as e:
            QMessageBox.critical(None, "Save failed", str(e))
            return

        message = f"Dive profile written to:\n{path}"
        if warnings:
            message += f"\n\n{len(warnings)} warning(s):\n" + "\n".join(warnings)
        QMessageBox.information(None, "Saved", message)


class DiveProfilePreviewImageProvider(QQuickImageProvider):
    def __init__(self, backend: DiveProfileBackend):
        super().__init__(QQuickImageProvider.ImageType.Image)
        self._backend = backend

    def requestImage(self, id, size, requestedSize):
        return self._backend.render_current_frame()
