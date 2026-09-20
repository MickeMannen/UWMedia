"""Dive Profile Builder page - PySide6 port of uwmedia/app.py's
_build_dive_profile_fields/_build_dive_profile_section and friends, see
pyside6_rework.md Phase 8.

Hand-builds a synthetic dive (waypoints, gas per waypoint, ascent/descent
rates), simulates NDL/deco live via a real Buhlmann engine, and saves the
result as a UDDF file - exists to unblock HUD verification gaps that no
real dive log exercises (deco clear transitions, sidemount, CCR bailout,
multi-gas switches - see uwmedia/app.py's own docstring for this section).

Reused verbatim: DiveProfilePlan/PlannedGas/PlannedWaypoint
(models.dive_plan), simulate (utils.dive_plan_engine), write_uddf
(parsers.uddf_writer), render_profile_image/time_from_x
(gui.dive_profile_view) - all zero-Toga-dependency engine code.
render_profile_image already renders the NDL/deco/cursor readout text
baked into the returned PIL image itself (not a separate widget), so the
QLabel+QPixmap port needs no extra readout-drawing code of its own -
same "hand the whole raster to draw_image" convention this codebase's
other canvases already use (see color_page.py's own docstring).

Canvas scrubbing reuses the same mouse-event-filter technique Color's own
live preview established (installEventFilter + press/move/release) -
mouseTracking is deliberately left off here (unlike Color's own preview
label) so MouseMove only fires while a button is held, matching Toga
Canvas's own on_drag semantics (button-gated) with no extra drag-state
bookkeeping needed.

One deliberate simplification vs the Toga original: the canvas is a
fixed DIVE_PROFILE_CANVAS_WIDTH x HEIGHT QLabel rather than resizing with
the window (Toga's own on_resize handler let the chart grow to fill the
right column) - consistent with every other ported canvas in this app
(Color, HUD Designer) already being fixed-size in this first pass.

No settings persistence - checked directly against PERSISTED_TEXT_FIELDS/
PERSISTED_SELECTION_FIELDS/PERSISTED_SWITCH_FIELDS in uwmedia/app.py:
none of this page's own fields are in those lists, so the Toga original
doesn't persist this page either.
"""
from pathlib import Path

from pydantic import ValidationError
from PySide6 import QtCore, QtGui, QtWidgets

from gui.dive_profile_view import render_profile_image, time_from_x
from models.dive_plan import DiveProfilePlan, PlannedGas, PlannedWaypoint
from parsers.uddf_writer import write_uddf
from utils.dive_plan_engine import simulate as simulate_dive_plan

DIVE_PLAN_GAS_TYPES = ("Air", "Nitrox", "Trimix", "CCR")
DIVE_PROFILE_CANVAS_WIDTH = 700
DIVE_PROFILE_CANVAS_HEIGHT = 420


class DiveProfilePage(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.dive_plan = self._dp_default_plan()
        self.dive_profile_samples = []
        self.dive_profile_warnings = []
        self.dive_profile_cursor_time = None
        self.dp_canvas_width = DIVE_PROFILE_CANVAS_WIDTH
        self.dp_canvas_height = DIVE_PROFILE_CANVAS_HEIGHT
        self._dp_editing_runtime = None

        self._build_ui()
        self._wire_signals()
        self._dp_refresh_gas_table()
        self._dp_refresh_waypoint_table()

    def _dp_default_plan(self):
        return DiveProfilePlan(gases=[PlannedGas(id="Air", gas_type="air", o2_percent=21.0)])

    # ------------------------------------------------------------------
    # Layout - ported from _build_dive_profile_section.
    # ------------------------------------------------------------------

    def _build_ui(self):
        root = QtWidgets.QHBoxLayout(self)

        left_scroll = QtWidgets.QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setFixedWidth(380)
        left_container = QtWidgets.QWidget()
        left = QtWidgets.QVBoxLayout(left_container)

        settings_group = QtWidgets.QGroupBox("Dive settings")
        settings_form = QtWidgets.QFormLayout(settings_group)
        self.dp_name_input = QtWidgets.QLineEdit(self.dive_plan.name)
        settings_form.addRow("Name", self.dp_name_input)

        gf_row = QtWidgets.QHBoxLayout()
        self.dp_gf_low_slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.dp_gf_low_slider.setMinimum(10)
        self.dp_gf_low_slider.setMaximum(99)
        self.dp_gf_low_slider.setValue(int(self.dive_plan.gf_low))
        gf_row.addWidget(self.dp_gf_low_slider)
        self.dp_gf_high_slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.dp_gf_high_slider.setMinimum(10)
        self.dp_gf_high_slider.setMaximum(99)
        self.dp_gf_high_slider.setValue(int(self.dive_plan.gf_high))
        gf_row.addWidget(self.dp_gf_high_slider)
        self.dp_gf_label = QtWidgets.QLabel(f"{int(self.dive_plan.gf_low)}/{int(self.dive_plan.gf_high)}")
        self.dp_gf_label.setFixedWidth(50)
        gf_row.addWidget(self.dp_gf_label)
        settings_form.addRow("GF Low/High", gf_row)

        self.dp_descent_rate_input = QtWidgets.QLineEdit(str(self.dive_plan.default_descent_rate))
        settings_form.addRow("Descent rate (m/min)", self.dp_descent_rate_input)
        self.dp_ascent_rate_input = QtWidgets.QLineEdit(str(self.dive_plan.default_ascent_rate))
        settings_form.addRow("Ascent rate (m/min)", self.dp_ascent_rate_input)
        self.dp_water_temp_input = QtWidgets.QLineEdit(str(self.dive_plan.water_temp_c))
        settings_form.addRow("Water temp (°C)", self.dp_water_temp_input)
        left.addWidget(settings_group)

        gases_group = QtWidgets.QGroupBox("Gases")
        gases_layout = QtWidgets.QVBoxLayout(gases_group)
        self.dp_gas_table = QtWidgets.QTableWidget(0, 7)
        self.dp_gas_table.setHorizontalHeaderLabels(
            ["Name", "Type", "O2%", "He%", "Setpoint", "Tank", "MOD (m)"]
        )
        self.dp_gas_table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.dp_gas_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.dp_gas_table.setFixedHeight(140)
        gases_layout.addWidget(self.dp_gas_table)

        gas_add_row1 = QtWidgets.QHBoxLayout()
        self.dp_gas_name_input = QtWidgets.QLineEdit()
        self.dp_gas_name_input.setPlaceholderText("e.g. Bottom")
        gas_add_row1.addWidget(self.dp_gas_name_input)
        self.dp_gas_type_select = QtWidgets.QComboBox()
        self.dp_gas_type_select.addItems(list(DIVE_PLAN_GAS_TYPES))
        gas_add_row1.addWidget(self.dp_gas_type_select)
        gases_layout.addLayout(gas_add_row1)

        gas_add_row2 = QtWidgets.QHBoxLayout()
        gas_add_row2.addWidget(QtWidgets.QLabel("O2%"))
        self.dp_gas_o2_input = QtWidgets.QLineEdit("21")
        self.dp_gas_o2_input.setFixedWidth(60)
        gas_add_row2.addWidget(self.dp_gas_o2_input)
        gas_add_row2.addWidget(QtWidgets.QLabel("He%"))
        self.dp_gas_he_input = QtWidgets.QLineEdit("0")
        self.dp_gas_he_input.setFixedWidth(60)
        gas_add_row2.addWidget(self.dp_gas_he_input)
        gas_add_row2.addWidget(QtWidgets.QLabel("SP"))
        self.dp_gas_setpoint_input = QtWidgets.QLineEdit("1.3")
        self.dp_gas_setpoint_input.setFixedWidth(60)
        self.dp_gas_setpoint_input.setEnabled(False)
        gas_add_row2.addWidget(self.dp_gas_setpoint_input)
        gas_add_row2.addWidget(QtWidgets.QLabel("Tank"))
        self.dp_gas_tank_input = QtWidgets.QLineEdit("T1")
        self.dp_gas_tank_input.setFixedWidth(60)
        gas_add_row2.addWidget(self.dp_gas_tank_input)
        gas_add_row2.addStretch(1)
        gases_layout.addLayout(gas_add_row2)

        gas_buttons_row = QtWidgets.QHBoxLayout()
        self.dp_add_gas_button = QtWidgets.QPushButton("Add Gas")
        gas_buttons_row.addWidget(self.dp_add_gas_button)
        self.dp_remove_gas_button = QtWidgets.QPushButton("Remove Selected")
        gas_buttons_row.addWidget(self.dp_remove_gas_button)
        gas_buttons_row.addStretch(1)
        gases_layout.addLayout(gas_buttons_row)

        self.dp_gas_status_label = QtWidgets.QLabel("")
        self.dp_gas_status_label.setWordWrap(True)
        self.dp_gas_status_label.setStyleSheet("color: gray;")
        gases_layout.addWidget(self.dp_gas_status_label)
        left.addWidget(gases_group)

        wps_group = QtWidgets.QGroupBox("Waypoints")
        wps_layout = QtWidgets.QVBoxLayout(wps_group)
        self.dp_wp_table = QtWidgets.QTableWidget(0, 4)
        self.dp_wp_table.setHorizontalHeaderLabels(["Time", "Depth (m)", "Gas", "Rate (m/min)"])
        self.dp_wp_table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.dp_wp_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.dp_wp_table.setFixedHeight(200)
        wps_layout.addWidget(self.dp_wp_table)

        wp_add_row = QtWidgets.QHBoxLayout()
        self.dp_wp_time_input = QtWidgets.QLineEdit()
        self.dp_wp_time_input.setPlaceholderText("mm:ss or minutes")
        wp_add_row.addWidget(self.dp_wp_time_input)
        self.dp_wp_depth_input = QtWidgets.QLineEdit()
        self.dp_wp_depth_input.setPlaceholderText("meters")
        wp_add_row.addWidget(self.dp_wp_depth_input)
        self.dp_wp_gas_select = QtWidgets.QComboBox()
        self.dp_wp_gas_select.addItems(["Air"])
        wp_add_row.addWidget(self.dp_wp_gas_select)
        self.dp_wp_rate_input = QtWidgets.QLineEdit()
        self.dp_wp_rate_input.setPlaceholderText("default")
        wp_add_row.addWidget(self.dp_wp_rate_input)
        wps_layout.addLayout(wp_add_row)

        wp_buttons_row = QtWidgets.QHBoxLayout()
        self.dp_add_wp_button = QtWidgets.QPushButton("Add / Update")
        wp_buttons_row.addWidget(self.dp_add_wp_button)
        self.dp_remove_wp_button = QtWidgets.QPushButton("Remove Selected")
        wp_buttons_row.addWidget(self.dp_remove_wp_button)
        wp_buttons_row.addStretch(1)
        wps_layout.addLayout(wp_buttons_row)

        self.dp_wp_status_label = QtWidgets.QLabel("")
        self.dp_wp_status_label.setWordWrap(True)
        self.dp_wp_status_label.setStyleSheet("color: gray;")
        wps_layout.addWidget(self.dp_wp_status_label)
        left.addWidget(wps_group)

        left.addStretch(1)
        left_scroll.setWidget(left_container)
        root.addWidget(left_scroll)

        right = QtWidgets.QVBoxLayout()
        hint = QtWidgets.QLabel("Click and drag across the chart to scrub NDL/deco")
        hint.setStyleSheet("color: gray;")
        right.addWidget(hint)

        self.canvas_label = QtWidgets.QLabel()
        self.canvas_label.setFixedSize(DIVE_PROFILE_CANVAS_WIDTH, DIVE_PROFILE_CANVAS_HEIGHT)
        self.canvas_label.installEventFilter(self)
        right.addWidget(self.canvas_label)

        self.dp_status_label = QtWidgets.QLabel("Add waypoints to preview the profile")
        self.dp_status_label.setStyleSheet("color: gray;")
        right.addWidget(self.dp_status_label)

        self.dp_save_button = QtWidgets.QPushButton("Save as UDDF…")
        self.dp_save_button.setFixedWidth(200)
        right.addWidget(self.dp_save_button)

        right.addStretch(1)
        root.addLayout(right, stretch=1)

    def _wire_signals(self):
        self.dp_gf_low_slider.valueChanged.connect(self._on_dp_gf_change)
        self.dp_gf_high_slider.valueChanged.connect(self._on_dp_gf_change)
        self.dp_descent_rate_input.textChanged.connect(self._on_dp_rate_change)
        self.dp_ascent_rate_input.textChanged.connect(self._on_dp_rate_change)
        self.dp_water_temp_input.textChanged.connect(self._on_dp_water_temp_change)
        self.dp_gas_type_select.currentTextChanged.connect(self._on_dp_gas_type_change)
        self.dp_add_gas_button.clicked.connect(self._on_dp_add_gas)
        self.dp_remove_gas_button.clicked.connect(self._on_dp_remove_gas)
        self.dp_wp_table.itemSelectionChanged.connect(self._on_dp_wp_select)
        self.dp_add_wp_button.clicked.connect(self._on_dp_add_or_update_waypoint)
        self.dp_remove_wp_button.clicked.connect(self._on_dp_remove_waypoint)
        self.dp_save_button.clicked.connect(self._on_dp_save_uddf)

    def eventFilter(self, obj, event):
        if obj is self.canvas_label:
            et = event.type()
            if et in (
                QtCore.QEvent.Type.MouseButtonPress,
                QtCore.QEvent.Type.MouseMove,
                QtCore.QEvent.Type.MouseButtonRelease,
            ):
                self._dp_scrub(event.position().x())
                return True
        return super().eventFilter(obj, event)

    # ------------------------------------------------------------------
    # Gas table - ported from _dp_refresh_gas_table/on_dp_gas_type_change/
    # on_dp_add_gas/on_dp_remove_gas.
    # ------------------------------------------------------------------

    def _dp_refresh_gas_table(self):
        self.dp_gas_table.setRowCount(len(self.dive_plan.gases))
        for i, g in enumerate(self.dive_plan.gases):
            values = [
                g.id,
                g.gas_type.upper(),
                f"{g.o2_percent:.0f}",
                f"{g.he_percent:.0f}",
                f"{g.ccr_setpoint:.2f}" if g.ccr_setpoint else "-",
                g.tank_ref,
                f"{g.mod_m:.0f}",
            ]
            for j, v in enumerate(values):
                self.dp_gas_table.setItem(i, j, QtWidgets.QTableWidgetItem(v))

        gas_ids = [g.id for g in self.dive_plan.gases]
        current = self.dp_wp_gas_select.currentText()
        self.dp_wp_gas_select.blockSignals(True)
        self.dp_wp_gas_select.clear()
        self.dp_wp_gas_select.addItems(gas_ids)
        self.dp_wp_gas_select.blockSignals(False)
        if current in gas_ids:
            self.dp_wp_gas_select.setCurrentText(current)
        elif gas_ids:
            self.dp_wp_gas_select.setCurrentText(gas_ids[0])

    def _on_dp_gas_type_change(self, text):
        self.dp_gas_setpoint_input.setEnabled(text == "CCR")

    def _on_dp_add_gas(self):
        name = self.dp_gas_name_input.text().strip() or f"Gas {len(self.dive_plan.gases) + 1}"
        if any(g.id == name for g in self.dive_plan.gases):
            self.dp_gas_status_label.setText(f"A gas named '{name}' already exists")
            return
        try:
            gas_type = self.dp_gas_type_select.currentText().lower()
            setpoint = None
            if gas_type == "ccr":
                setpoint = float(self.dp_gas_setpoint_input.text())
            gas = PlannedGas(
                id=name,
                gas_type=gas_type,
                o2_percent=float(self.dp_gas_o2_input.text()),
                he_percent=float(self.dp_gas_he_input.text() or 0.0),
                ccr_setpoint=setpoint,
                tank_ref=(self.dp_gas_tank_input.text() or "T1").strip(),
            )
        except (TypeError, ValueError, ValidationError) as e:
            self.dp_gas_status_label.setText(f"Could not add gas: {e}")
            return
        self.dive_plan.gases.append(gas)
        self.dp_gas_name_input.clear()
        self.dp_gas_status_label.setText("")
        self._dp_refresh_gas_table()
        self._dp_resimulate()

    def _on_dp_remove_gas(self):
        row = self.dp_gas_table.currentRow()
        if row < 0:
            return
        name = self.dp_gas_table.item(row, 0).text()
        self.dive_plan.gases = [g for g in self.dive_plan.gases if g.id != name]
        self._dp_refresh_gas_table()
        self._dp_resimulate()

    # ------------------------------------------------------------------
    # Waypoint table - ported from _dp_refresh_waypoint_table/
    # on_dp_wp_select/on_dp_add_or_update_waypoint/on_dp_remove_waypoint.
    # ------------------------------------------------------------------

    @staticmethod
    def _dp_format_mmss(seconds):
        seconds = max(0, int(seconds))
        return f"{seconds // 60}:{seconds % 60:02d}"

    @staticmethod
    def _dp_parse_time_to_seconds(text):
        text = (text or "").strip()
        if not text:
            raise ValueError("Enter a time")
        if ":" in text:
            minutes_str, seconds_str = text.split(":", 1)
            return int(minutes_str) * 60 + int(seconds_str)
        return int(round(float(text) * 60))

    def _dp_refresh_waypoint_table(self):
        wps = self.dive_plan.sorted_waypoints()
        self.dp_wp_table.setRowCount(len(wps))
        for i, wp in enumerate(wps):
            values = [
                self._dp_format_mmss(wp.runtime_sec),
                f"{wp.depth_m:.1f}",
                wp.gas_id,
                f"{wp.rate_m_per_min:.0f}" if wp.rate_m_per_min else "default",
            ]
            for j, v in enumerate(values):
                item = QtWidgets.QTableWidgetItem(v)
                if j == 0:
                    item.setData(QtCore.Qt.ItemDataRole.UserRole, wp.runtime_sec)
                self.dp_wp_table.setItem(i, j, item)

    def _dp_clear_waypoint_inputs(self):
        self._dp_editing_runtime = None
        self.dp_wp_time_input.clear()
        self.dp_wp_depth_input.clear()
        self.dp_wp_rate_input.clear()

    def _on_dp_wp_select(self):
        row = self.dp_wp_table.currentRow()
        if row < 0:
            return
        item = self.dp_wp_table.item(row, 0)
        runtime_sec = item.data(QtCore.Qt.ItemDataRole.UserRole)
        wp = next((w for w in self.dive_plan.waypoints if w.runtime_sec == runtime_sec), None)
        if wp is None:
            return
        self._dp_editing_runtime = wp.runtime_sec
        self.dp_wp_time_input.setText(self._dp_format_mmss(wp.runtime_sec))
        self.dp_wp_depth_input.setText(f"{wp.depth_m:g}")
        self.dp_wp_gas_select.setCurrentText(wp.gas_id)
        self.dp_wp_rate_input.setText(f"{wp.rate_m_per_min:g}" if wp.rate_m_per_min else "")

    def _on_dp_add_or_update_waypoint(self):
        try:
            runtime_sec = self._dp_parse_time_to_seconds(self.dp_wp_time_input.text())
            depth = float(self.dp_wp_depth_input.text())
            gas_id = self.dp_wp_gas_select.currentText()
            if not gas_id:
                raise ValueError("Define a gas first")
            rate_text = self.dp_wp_rate_input.text().strip()
            rate = float(rate_text) if rate_text else None
            new_wp = PlannedWaypoint(runtime_sec=runtime_sec, depth_m=depth, gas_id=gas_id, rate_m_per_min=rate)
        except (TypeError, ValueError, ValidationError) as e:
            self.dp_wp_status_label.setText(f"Could not save waypoint: {e}")
            return

        editing = self._dp_editing_runtime
        self.dive_plan.waypoints = [
            w for w in self.dive_plan.waypoints if w.runtime_sec not in (editing, runtime_sec)
        ]
        self.dive_plan.waypoints.append(new_wp)
        self.dp_wp_status_label.setText("")
        self._dp_clear_waypoint_inputs()
        self._dp_refresh_waypoint_table()
        self._dp_resimulate()

    def _on_dp_remove_waypoint(self):
        row = self.dp_wp_table.currentRow()
        if row < 0:
            return
        runtime_sec = self.dp_wp_table.item(row, 0).data(QtCore.Qt.ItemDataRole.UserRole)
        self.dive_plan.waypoints = [w for w in self.dive_plan.waypoints if w.runtime_sec != runtime_sec]
        self._dp_clear_waypoint_inputs()
        self._dp_refresh_waypoint_table()
        self._dp_resimulate()

    # ------------------------------------------------------------------
    # Settings - ported from on_dp_gf_change/on_dp_rate_change/
    # on_dp_water_temp_change.
    # ------------------------------------------------------------------

    def _on_dp_gf_change(self, _value):
        self.dive_plan.gf_low = self.dp_gf_low_slider.value()
        self.dive_plan.gf_high = self.dp_gf_high_slider.value()
        self.dp_gf_label.setText(f"{int(self.dive_plan.gf_low)}/{int(self.dive_plan.gf_high)}")
        self._dp_resimulate()

    def _on_dp_rate_change(self, _text):
        try:
            self.dive_plan.default_descent_rate = float(self.dp_descent_rate_input.text())
        except (TypeError, ValueError):
            pass
        try:
            self.dive_plan.default_ascent_rate = float(self.dp_ascent_rate_input.text())
        except (TypeError, ValueError):
            pass
        self._dp_resimulate()

    def _on_dp_water_temp_change(self, _text):
        try:
            self.dive_plan.water_temp_c = float(self.dp_water_temp_input.text())
        except (TypeError, ValueError):
            pass

    # ------------------------------------------------------------------
    # Simulation / canvas - ported from _dp_resimulate/
    # _redraw_dive_profile_canvas/_dp_scrub. QLabel+QPixmap instead of
    # toga.Canvas (see this module's own docstring).
    # ------------------------------------------------------------------

    def _dp_resimulate(self):
        try:
            samples, warnings = simulate_dive_plan(self.dive_plan, resolution_sec=60)
        except ValueError as e:
            samples, warnings = [], [str(e)]
        self.dive_profile_samples = samples
        self.dive_profile_warnings = warnings
        if warnings:
            self.dp_status_label.setText(" | ".join(warnings))
            self.dp_status_label.setStyleSheet("color: #EF4444;")
        elif samples:
            max_depth = max(s.depth_m for s in samples)
            self.dp_status_label.setText(
                f"{len(samples)} samples · max depth {max_depth:.0f}m · "
                f"runtime {self._dp_format_mmss(samples[-1].time_sec)}"
            )
            self.dp_status_label.setStyleSheet("color: gray;")
        else:
            self.dp_status_label.setText("Add waypoints to preview the profile")
            self.dp_status_label.setStyleSheet("color: gray;")
        self._redraw_canvas()

    def _redraw_canvas(self):
        width, height = self.dp_canvas_width, self.dp_canvas_height
        image = render_profile_image(
            self.dive_plan, self.dive_profile_samples, width, height, cursor_time=self.dive_profile_cursor_time
        )
        rgb = image.convert("RGB")
        rgb_bytes = rgb.tobytes("raw", "RGB")
        qimage = QtGui.QImage(
            rgb_bytes, rgb.width, rgb.height, rgb.width * 3, QtGui.QImage.Format.Format_RGB888
        )
        self.canvas_label.setPixmap(QtGui.QPixmap.fromImage(qimage))

    def _dp_scrub(self, x):
        if not self.dive_profile_samples:
            return
        max_time = max(s.time_sec for s in self.dive_profile_samples) or 1
        self.dive_profile_cursor_time = time_from_x(x, self.dp_canvas_width, max_time)
        self._redraw_canvas()

    # ------------------------------------------------------------------
    # Save - ported from on_dp_save_uddf.
    # ------------------------------------------------------------------

    def _on_dp_save_uddf(self):
        self.dive_plan.name = self.dp_name_input.text() or self.dive_plan.name
        try:
            samples, warnings = simulate_dive_plan(self.dive_plan, resolution_sec=1)
        except ValueError as e:
            QtWidgets.QMessageBox.critical(self, "Cannot save", str(e))
            return
        if not samples:
            QtWidgets.QMessageBox.critical(self, "Cannot save", "Add at least one waypoint first")
            return

        suggested = f"{self.dive_plan.name.strip().replace(' ', '_') or 'dive_profile'}.uddf"
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save dive profile as UDDF", suggested, "UDDF files (*.uddf)"
        )
        if not path:
            return

        try:
            write_uddf(self.dive_plan, samples, Path(path))
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Save failed", str(e))
            return

        message = f"Dive profile written to:\n{path}"
        if warnings:
            message += f"\n\n{len(warnings)} warning(s):\n" + "\n".join(warnings)
        QtWidgets.QMessageBox.information(self, "Saved", message)
