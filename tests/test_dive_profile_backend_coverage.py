"""
The Dive Profile Builder backend (uwmedia/backends/dive_profile_backend.py),
the parts test_dive_profile_backend.py leaves out: the Dive settings texts
(rates, temperature, PO2, CCR and sidemount numbers, chart scale) applied,
remembered or refused, the gas and waypoint editors' edge cases, placing,
dragging and removing waypoints on the chart, End dive, the hover readout
on a CCR dive, and Open/Save log with the dialogs and message boxes stubbed.
settings.json is redirected to tmp_path; logs are synthetic.
"""
import json
from datetime import datetime

import pytest
from PySide6.QtGui import QImage

import uwmedia.backends.dive_profile_backend as dpb
from conftest import write_synthetic_log
from gui.dive_profile_view import xy_of
from parsers.plan_embed import LogOrigin
from utils.app_settings import get_fields, set_field
from uwmedia.backends.dive_profile_backend import (
    DIVE_PROFILE_CANVAS_HEIGHT as H,
    DIVE_PROFILE_CANVAS_WIDTH as W,
    LOG_FORMAT_FIELD,
    DiveProfileBackend,
    DiveProfilePreviewImageProvider,
)


@pytest.fixture
def backend(settings_file):
    return DiveProfileBackend()


@pytest.fixture
def dialogs(monkeypatch):
    """Stubbed QFileDialog/QMessageBox: set `open`/`save` to what the
    dialog returns; every message box shown is recorded."""
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    state = {"open": ("", ""), "save": ("", ""), "shown": []}
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: state["open"]))
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: state["save"]))
    for kind in ("warning", "critical", "information"):
        monkeypatch.setattr(QMessageBox, kind,
                            staticmethod(lambda parent, title, text, kind=kind: state["shown"].append((kind, title, text))))
    return state


def _at(backend, minute, depth):
    return xy_of(minute * 60, depth, W, H, backend._axes())


def _waypoint(backend, minutes, depth, gas=""):
    backend.wpTimeText = str(minutes)
    backend.wpDepthText = str(depth)
    backend.onWpGasSelected(gas)
    backend.addOrUpdateWaypoint()


def _gas(backend, name, o2, **texts):
    backend.newGas()
    backend.gasNameText = name
    backend.gasO2Text = str(o2)
    backend.onGasTypeSelected("Nitrox")
    for attr, value in texts.items():
        setattr(backend, attr, value)
    backend.addGas()


# --- Dive settings ---------------------------------------------------------------

def test_typed_settings_apply_and_bad_text_is_kept_but_ignored(backend):
    for attr in ("descentRateText", "ascentRateText", "waterTempText", "sacText", "bottomPo2Text",
                 "decoPo2Text", "maxDepthText", "runtimeText", "ccrSwitchDepthText", "ccrO2SizeText",
                 "ccrO2StartText", "sidemountSwitchText"):
        setattr(backend, attr, "abc")
        assert getattr(backend, attr) == "abc"
    plan = backend.dive_plan
    assert (plan.default_descent_rate, plan.default_ascent_rate, plan.water_temp_c) == (20, 9, plan.water_temp_c)
    assert plan.max_depth_m is None and plan.planned_runtime_sec is None
    assert get_fields() == {}

    backend.maxDepthText = "40"
    backend.runtimeText = "45:30"
    backend.ccrSwitchDepthText = "6"
    backend.ccrO2SizeText = "3"
    backend.ccrO2StartText = "200"
    backend.sidemountSwitchText = "30"
    assert (plan.max_depth_m, plan.planned_runtime_sec) == (40, 45 * 60 + 30)
    assert (plan.ccr_setpoint_switch_depth_m, plan.ccr_o2_tank_size_l, plan.ccr_o2_start_pressure_bar) == (6, 3, 200)
    assert plan.sidemount_switch_bar == 30
    assert backend.scaleDefined

    again = DiveProfileBackend()
    assert (again.maxDepthText, again.runtimeText) == ("40", "45.5")
    assert (again.ccrSwitchDepthText, again.ccrO2SizeText, again.ccrO2StartText) == ("6", "3", "200")
    assert again.sidemountSwitchText == "30"


def test_zero_or_negative_scale_is_refused(backend):
    backend.maxDepthText = "0"
    backend.runtimeText = "-5"
    assert not backend.scaleDefined and get_fields() == {}


@pytest.mark.parametrize("depth, runtime, error", [
    ("deep", "40", "Enter the max depth in metres"),
    ("0", "40", "Max depth must be greater than 0"),
    ("30", "", "Enter the planned runtime in minutes (or mm:ss)"),
    ("30", "1:xx", "Enter the planned runtime in minutes (or mm:ss)"),
    ("30", "0", "Planned runtime must be greater than 0"),
])
def test_define_scale_explains_a_bad_entry(backend, depth, runtime, error):
    assert backend.defineScale(depth, runtime) == error
    assert not backend.scaleDefined


def test_saved_gf_that_is_not_a_number_is_ignored(settings_file):
    set_field(dpb.GF_LOW_FIELD, "thirty")
    backend = DiveProfileBackend()
    assert (backend.dive_plan.gf_low, backend.dive_plan.gf_high) == (30, 70)


def test_saved_setpoints_in_the_wrong_order_are_made_consistent(settings_file):
    set_field("dive_profile_ccr_low_setpoint", 1.4)
    set_field("dive_profile_ccr_high_setpoint", 1.0)
    set_field("dive_profile_ccr_switch_depth", 0)
    backend = DiveProfileBackend()
    assert (backend.ccrLowSetpointText, backend.ccrHighSetpointText) == ("1", "1")
    assert backend.dive_plan.ccr_setpoint_switch_depth_m == 0


@pytest.mark.parametrize("low, high, error", [
    ("0.2", "1.3", "between 0.4 and 1.6"),
    ("x", "1.3", "as numbers"),
])
def test_bad_setpoints_are_explained(backend, low, high, error):
    backend.ccrLowSetpointText = low
    backend.ccrHighSetpointText = high
    assert error in backend.ccrErrorText
    assert backend.dive_plan.ccr_low_setpoint == 0.7


def test_bad_po2_is_ignored(backend):
    backend.bottomPo2Text = "high"
    backend.decoPo2Text = "1.6"
    assert backend.bottomPo2Text == "high" and backend.decoPo2Text == "1.6"
    assert (backend.dive_plan.max_po2_bottom, backend.dive_plan.max_po2_deco) == (1.4, 1.6)


def test_choice_lists(backend):
    assert backend.diveTypeList == ["Open circuit", "Sidemount", "CCR"]
    assert "Shearwater Perdix 2" in backend.computerList
    assert backend.gasTypeList == ["Air", "Nitrox", "Trimix"]
    assert backend.gasSideList == ["Stage", "Left", "Right"]
    assert backend.gasPhaseList == ["Any", "Descent/bottom", "Ascent/deco"]
    assert backend.gasTableHeaders[0] == "Name" and backend.waypointHeaders[0] == "Time"
    assert backend.gasColorPalette and backend.gasColor in backend.gasColorPalette


def test_choosing_the_same_dive_type_or_an_unknown_computer_changes_nothing(backend):
    backend.onDiveTypeSelected("Open circuit")
    backend.onComputerSelected("Casio watch")
    assert backend.computerLabel == "Shearwater Perdix 2"
    assert get_fields() == {}


def test_changing_dive_type_keeps_the_gas_being_edited(backend):
    backend.selectGasRow(0)
    backend.onDiveTypeSelected("CCR")
    assert backend.selectedGasRow == 0 and backend.gasDiluent  # the Air gas, now the diluent


# --- gases ---------------------------------------------------------------------

def test_gas_editor_fields_and_depth_range_show_in_the_table(backend):
    _gas(backend, "EAN50", 50, gasMinDepthText="3", gasMaxDepthText="21",
         gasStartPressureText="200", gasVolumeText="7", gasTankText="S1")
    backend.selectGasRow(1)
    backend.onGasPhaseSelected("Ascent/deco")
    backend.addGas()
    row = backend.gasTableRows[1]
    assert row[0] == "EAN50" and row[4] == "S1 7L/200" and row[6] == "3-21m ↑"
    assert backend.gasIdList == ["Air", "EAN50"]
    assert (backend.gasType, backend.gasHeText, backend.gasMinDepthText, backend.gasMaxDepthText) == (
        "Nitrox", "0", "3", "21")
    assert backend.gasPhaseLabel == "Ascent/deco"
    assert backend.gasTankText == "S1"


def test_open_ended_depth_range_is_shown_with_infinity(backend):
    _gas(backend, "EAN32", 32, gasMinDepthText="10")
    assert backend.gasTableRows[1][6] == "10-∞m"


def test_gas_range_beyond_its_mod_gets_a_note(backend):
    _gas(backend, "EAN50", 50, gasMaxDepthText="40")
    assert backend.gasStatusText.startswith("Note: EAN50's range goes to 40m but its MOD")


def test_gas_range_the_wrong_way_round_is_refused(backend):
    _gas(backend, "EAN32", 32, gasMinDepthText="30", gasMaxDepthText="10")
    assert "the 'from' depth must be shallower" in backend.gasStatusText
    assert len(backend.dive_plan.gases) == 1


def test_unnamed_gas_gets_a_numbered_name_and_a_chosen_colour(backend):
    backend.newGas()
    colour = backend.gasColorPalette[3]
    backend.onGasColorSelected(colour)
    assert backend.gasColor == colour
    backend.addGas()
    assert backend.dive_plan.gases[1].id == "Gas 2"
    assert backend.gasColors[1] == colour


def test_recolouring_a_gas_from_its_swatch(backend):
    colour = backend.gasColorPalette[5]
    backend.setGasColor(0, colour)
    assert backend.gasColors[0] == colour
    backend.setGasColor(9, "#000000")  # no such row
    assert len(backend.gasColors) == 1


def test_selecting_or_removing_a_gas_row_out_of_range_is_ignored(backend):
    backend.selectGasRow(4)
    backend.removeGasAtRow(4)
    assert backend.selectedGasRow == -1 and len(backend.dive_plan.gases) == 1


def test_removing_a_waypoints_gas_switches_it_to_auto(backend):
    _gas(backend, "EAN32", 32)
    _waypoint(backend, 20, 20, gas="EAN32")
    assert backend.waypointRows[0][2] == "EAN32"
    backend.removeGasAtRow(1)
    assert backend.waypointRows[0][2] == "Air (auto)"


def test_sidemount_offers_the_left_tank_first_and_wants_tanks_of_their_own(backend):
    backend.dive_plan.gases[0].use_phase = "ascent"  # nothing on the bottom yet ...
    backend.onDiveTypeSelected("Sidemount")
    assert backend.dive_plan.gases[0].side == "left"  # ... still, the first gas goes left
    backend.dive_plan.gases[0].side = None
    backend.newGas()
    assert backend.gasSideLabel == "Left"
    backend.dive_plan.gases[0].side = "left"
    backend.newGas()
    assert backend.gasSideLabel == "Right"
    backend.gasTankText = "T1"  # the left tank's own
    backend.addGas()
    assert "need tanks of their own" in backend.gasStatusText


# --- waypoints -----------------------------------------------------------------

def test_waypoint_editor_round_trip(backend):
    _waypoint(backend, "5:30", 18)
    backend.wpTimeText = "25"
    backend.wpDepthText = "18"
    backend.wpRateText = "12"
    backend.onWpGasSelected("Air")
    backend.addOrUpdateWaypoint()
    assert backend.waypointRows == [["5:30", "18.0", "Air (auto)", "default"], ["25:00", "18.0", "Air", "12"]]
    assert backend.waypointGasColors == [backend.gasColors[0]] * 2

    backend.selectWaypointRow(1)
    assert (backend.wpTimeText, backend.wpDepthText, backend.wpGasText, backend.wpRateText) == (
        "25:00", "18", "Air", "12")
    backend.selectWaypointRow(0)
    assert backend.wpGasText == "Auto" and backend.wpRateText == ""
    backend.selectWaypointRow(7)  # out of range: unchanged
    assert backend.wpTimeText == "5:30"

    backend.wpDepthText = "20"
    backend.addOrUpdateWaypoint()  # updates the selected one in place
    assert [r[:2] for r in backend.waypointRows] == [["5:30", "20.0"], ["25:00", "18.0"]]
    backend.removeWaypointAtRow(5)
    backend.removeWaypointAtRow(0)
    assert [r[0] for r in backend.waypointRows] == ["25:00"]


def test_waypoint_with_bad_input_is_explained(backend):
    _waypoint(backend, "soon", 10)
    assert backend.wpStatusText.startswith("Could not save waypoint")
    backend.dive_plan.gases = []
    _waypoint(backend, 5, 10)
    assert backend.wpStatusText == "Could not save waypoint: Define a gas first"
    assert backend.waypointRows == []


def test_edited_waypoint_keeps_its_ascent_marking(backend):
    _waypoint(backend, 20, 30)
    backend.endDive()
    ascent_row = next(i for i, wp in enumerate(backend.dive_plan.sorted_waypoints()) if wp.phase == "ascent")
    backend.selectWaypointRow(ascent_row)
    backend.addOrUpdateWaypoint()
    assert backend.dive_plan.sorted_waypoints()[ascent_row].phase == "ascent"


# --- the chart -------------------------------------------------------------------

def test_without_a_scale_the_chart_takes_no_clicks(backend):
    assert backend._axes() is None
    assert backend.waypointIndexAt(100, 100) == -1
    backend.addWaypointAt(100, 100)
    backend.moveWaypoint(0, 100, 100)
    backend.onScrub(100)
    assert backend.waypointRows == [] and backend.cursorInfo == []


def test_click_needs_a_gas(backend):
    backend.defineScale("30", "40")
    backend.dive_plan.gases = []
    backend.addWaypointAt(*_at(backend, 10, 20))
    assert backend.wpStatusText == "Define a gas first"


def test_click_drag_and_drop_waypoints_on_the_chart(backend):
    backend.defineScale("30", "40")
    backend.addWaypointAt(*_at(backend, 3, 20))
    backend.addWaypointAt(*_at(backend, 20, 20))
    assert [r[:2] for r in backend.waypointRows] == [["3:00", "20.0"], ["20:00", "20.0"]]
    assert backend.waypointIndexAt(*_at(backend, 20, 20)) == 1
    assert backend.waypointIndexAt(*_at(backend, 12, 5)) == -1

    backend.moveWaypoint(1, *_at(backend, 1, 25))  # can't pass the waypoint before it
    assert backend.dive_plan.sorted_waypoints()[1].runtime_sec == 4 * 60
    assert backend.dive_plan.sorted_waypoints()[1].depth_m == 25
    assert backend._dragging
    revision = backend.previewImageSource
    backend.moveWaypoint(1, *_at(backend, 1, 25))  # same spot: no redraw
    assert backend.previewImageSource == revision
    backend.moveWaypoint(0, *_at(backend, 30, 10))  # can't pass the one after it
    assert backend.dive_plan.sorted_waypoints()[0].runtime_sec == 3 * 60
    backend.moveWaypoint(9, 0, 0)  # no such row
    backend.dropWaypoint(1)
    assert not backend._dragging

    # a drop near the end of the time axis grows the planned runtime
    backend.moveWaypoint(1, *_at(backend, 39, 25))
    backend.dropWaypoint(1)
    assert backend.dive_plan.planned_runtime_sec == 50 * 60 and backend.runtimeText == "50"


def test_end_dive_messages(backend, monkeypatch):
    backend.endDive()
    assert backend.endDiveStatusText == "Place at least one waypoint before ending the dive"
    _waypoint(backend, 10, 15)
    backend.endDive()
    assert backend.endDiveStatusText.startswith("No deco needed - 3m/3min safety stop added, surfacing at")
    backend.endDive()
    assert backend.endDiveStatusText.startswith("The dive already ends at the surface")

    backend.removeWaypointAtRow(len(backend.waypointRows) - 1)
    monkeypatch.setattr(dpb, "plan_ascent", lambda plan: ([], False, []))
    backend.endDive()
    assert backend.endDiveStatusText == "Nothing to add - the ascent planner returned no waypoints"

    def broken(plan):
        raise ValueError("no gas reaches the surface")

    monkeypatch.setattr(dpb, "plan_ascent", broken)
    backend.endDive()
    assert backend.endDiveStatusText == "Could not plan the ascent: no gas reaches the surface"


def test_end_dive_lists_the_deco_stops_and_gas_switches(backend):
    backend.defineScale("45", "60")
    backend.newGas()
    backend.gasNameText = "EAN50"
    backend.gasO2Text = "50"
    backend.onGasTypeSelected("Nitrox")
    backend.gasMaxDepthText = "21"
    backend.onGasPhaseSelected("Ascent/deco")
    backend.addGas()
    _waypoint(backend, 3, 40)  # gas Auto, so the ascent may switch
    _waypoint(backend, 25, 40)
    backend.endDive()
    message = backend.endDiveStatusText
    assert message.startswith("Deco ascent added: ") and "EAN50" in message and "surfacing at" in message


def test_ccr_hover_readout_shows_the_loop_and_the_o2_tank(backend):
    backend.defineScale("30", "40")
    _waypoint(backend, 3, 25)
    _waypoint(backend, 20, 25)
    backend.onDiveTypeSelected("CCR")
    backend.onScrub(_at(backend, 15, 25)[0])
    rows = {r["label"]: r["value"] for r in backend.cursorInfo}
    assert rows["Loop"].startswith("SP ")
    assert "Tanks" in rows  # the diluent plus the O2 cylinder
    backend.clearCursor()
    assert backend.cursorInfo == []


def test_hover_readout_survives_an_ascent_the_planner_cannot_make(backend, monkeypatch):
    backend.defineScale("45", "60")
    _waypoint(backend, 3, 40)
    _waypoint(backend, 30, 40)

    def broken(plan, time_sec):
        raise ValueError("stuck")

    monkeypatch.setattr(dpb, "ascent_from_time", broken)
    backend.onScrub(_at(backend, 30, 40)[0])
    labels = [r["label"] for r in backend.cursorInfo]
    assert "Ceiling" in labels and "TTS" in labels and "Deco stops" not in labels


def test_phase_after_the_last_waypoint_is_the_ascent(backend):
    _waypoint(backend, 10, 15)
    assert backend._phase_at(10 ** 6) == "ascent"


def test_the_chart_image_is_rendered(backend):
    _waypoint(backend, 10, 15)
    image = DiveProfilePreviewImageProvider(backend).requestImage("frame", None, None)
    assert isinstance(image, QImage) and (image.width(), image.height()) == (W, H)
    assert backend.previewImageSource.startswith("image://diveprofilepreview/frame?r=")


# --- Open and Save log -------------------------------------------------------------

def test_open_log_reports_what_it_did(backend, dialogs, tmp_path):
    log = write_synthetic_log(tmp_path / "dive.uddf", datetime(2026, 1, 2, 9, 0))
    dialogs["open"] = (str(log), "")
    backend.openLog()
    assert backend.endDiveStatusText == "Opened dive.uddf: plan restored as saved"
    assert get_fields()["dive_profile_log_dir"] == str(tmp_path)
    assert dialogs["shown"] == []


def test_open_log_rebuilds_a_plan_from_the_samples(backend, monkeypatch, tmp_path):
    log = write_synthetic_log(tmp_path / "dive.uddf", datetime(2026, 1, 2, 9, 0))
    monkeypatch.setattr(dpb, "read_log_origin", lambda path: LogOrigin(True, None))
    assert "saved before UWMedia kept the plan" in backend.load_log(log)
    monkeypatch.setattr(dpb, "read_log_origin", lambda path: LogOrigin(False, None))
    assert backend.load_log(log).startswith("Imported dive.uddf")
    assert backend.waypointRows and backend.dive_profile_samples


def test_open_log_errors_are_shown_in_a_message_box(backend, dialogs, tmp_path):
    dialogs["open"] = (str(tmp_path / "missing.uddf"), "")
    backend.openLog()
    (shown,) = dialogs["shown"]
    assert shown[0] == "warning" and "does not exist" in shown[2]
    empty = tmp_path / "empty.uddf"
    empty.write_text("<uddf/>")
    with pytest.raises(ValueError, match="No dive found in empty.uddf"):
        backend.load_log(empty)


def test_save_log_writes_the_file_and_remembers_the_format(backend, dialogs, tmp_path):
    _waypoint(backend, 20, 18)
    dialogs["save"] = (str(tmp_path / "my dive"), "Subsurface XML (*.ssrf)")
    backend.saveLog()
    assert (tmp_path / "my dive.ssrf").is_file()  # the filter's extension is added
    (shown,) = dialogs["shown"]
    assert shown[0] == "information" and str(tmp_path / "my dive.ssrf") in shown[2]
    assert get_fields()[LOG_FORMAT_FIELD] == "Subsurface XML (*.ssrf)"


def test_save_log_lists_warnings_and_reports_failures(backend, dialogs, monkeypatch, tmp_path):
    set_field(LOG_FORMAT_FIELD, "Garmin FIT (*.fit)")
    dialogs["save"] = (str(tmp_path / "d.uddf"), "UDDF (*.uddf)")
    real_write_log = backend.write_log
    monkeypatch.setattr(backend, "write_log", lambda path: ["Air exceeds its MOD"])
    backend.saveLog()
    assert dialogs["shown"][-1][2].endswith("1 warning(s):\nAir exceeds its MOD")

    monkeypatch.setattr(backend, "write_log", real_write_log)
    dialogs["save"] = (str(tmp_path / "d.uddf"), "UDDF (*.uddf)")
    backend.saveLog()  # no waypoints yet
    kind, title, text = dialogs["shown"][-1]
    assert (kind, title) == ("critical", "Save failed") and text


def test_cancelled_save_writes_nothing(backend, dialogs, tmp_path):
    backend.saveLog()
    assert dialogs["shown"] == [] and list(tmp_path.glob("*.uddf")) == []


def test_write_log_needs_a_waypoint(backend, tmp_path):
    with pytest.raises(ValueError):
        backend.write_log(tmp_path / "d.uddf")
    assert not (tmp_path / "d.uddf").exists()
