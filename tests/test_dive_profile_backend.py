"""
Dive Profile Builder backend (uwmedia/backends/dive_profile_backend.py) -
GF text entry and its persistence across restarts. settings.json is
redirected to tmp_path, never the real Application Support file.
"""
import json
from datetime import datetime

import pytest

from conftest import LOGS_DIR
from parsers.garmin import GarminParser
from parsers.subsurface import SubsurfaceParser
from parsers.uddf import UDDFParser

from utils import app_settings
from uwmedia.backends.dive_profile_backend import GF_HIGH_FIELD, GF_LOW_FIELD, DiveProfileBackend


@pytest.fixture
def settings_file(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    monkeypatch.setattr(app_settings, "settings_path", lambda: path)
    return path


def test_gf_defaults_without_saved_values(settings_file):
    backend = DiveProfileBackend()
    assert (backend.gfLowText, backend.gfHighText) == ("30", "70")
    assert not settings_file.exists()


def test_gf_text_applies_and_is_remembered(settings_file):
    backend = DiveProfileBackend()
    backend.gfLowText = "40"
    backend.gfHighText = "85"
    assert (backend.dive_plan.gf_low, backend.dive_plan.gf_high) == (40, 85)
    fields = json.loads(settings_file.read_text())["fields"]
    assert (fields[GF_LOW_FIELD], fields[GF_HIGH_FIELD]) == (40, 85)

    restarted = DiveProfileBackend()
    assert (restarted.gfLowText, restarted.gfHighText) == ("40", "85")
    assert (restarted.dive_plan.gf_low, restarted.dive_plan.gf_high) == (40, 85)


@pytest.mark.parametrize("low, high", [("80", "70"), ("0", "70"), ("30", "101"), ("abc", "70"), ("", "70")])
def test_invalid_gf_is_rejected_and_not_saved(settings_file, low, high):
    backend = DiveProfileBackend()
    backend.gfLowText = low
    backend.gfHighText = high
    assert backend.gfErrorText
    assert (backend.dive_plan.gf_low, backend.dive_plan.gf_high) == (30, 70)
    assert not settings_file.exists()


def test_error_clears_once_pair_is_valid_again(settings_file):
    backend = DiveProfileBackend()
    backend.gfLowText = "80"  # higher than 70 while typing
    assert backend.gfErrorText
    backend.gfHighText = "90"
    assert backend.gfErrorText == ""
    assert (backend.dive_plan.gf_low, backend.dive_plan.gf_high) == (80, 90)


def test_corrupt_saved_gf_falls_back_to_defaults(settings_file):
    settings_file.write_text(json.dumps({"fields": {GF_LOW_FIELD: 90, GF_HIGH_FIELD: 20}}))
    backend = DiveProfileBackend()
    assert (backend.dive_plan.gf_low, backend.dive_plan.gf_high) == (30, 70)


def test_all_dive_settings_are_remembered(settings_file):
    backend = DiveProfileBackend()
    backend.nameText = "Wreck test"
    backend.descentRateText = "18"
    backend.ascentRateText = "10"
    backend.waterTempText = "12.5"
    backend.bottomPo2Text = "1.3"
    backend.decoPo2Text = "1.5"
    assert backend.defineScale("50", "75") == ""

    restarted = DiveProfileBackend()
    plan = restarted.dive_plan
    assert plan.name == "Wreck test" and restarted.nameText == "Wreck test"
    assert (plan.default_descent_rate, plan.default_ascent_rate, plan.water_temp_c) == (18, 10, 12.5)
    assert (plan.max_po2_bottom, plan.max_po2_deco) == (1.3, 1.5)
    assert (plan.max_depth_m, plan.planned_runtime_sec) == (50, 75 * 60)
    assert (restarted.maxDepthText, restarted.runtimeText) == ("50", "75")
    assert restarted.scaleDefined


def test_invalid_dive_settings_are_not_saved(settings_file):
    backend = DiveProfileBackend()
    backend.descentRateText = "0"
    backend.ascentRateText = "-3"
    backend.bottomPo2Text = "2.5"
    backend.nameText = "   "
    assert not settings_file.exists()
    restarted = DiveProfileBackend()
    assert (restarted.dive_plan.default_descent_rate, restarted.dive_plan.default_ascent_rate) == (20, 9)
    assert restarted.dive_plan.max_po2_bottom == 1.4


def test_hover_readout_lists_full_deco_plan(settings_file):
    from gui.dive_profile_view import xy_of

    backend = DiveProfileBackend()
    backend.defineScale("45", "60")
    backend.gasNameText = "EAN50"
    backend.gasO2Text = "50"
    backend.onGasTypeSelected("Nitrox")
    backend.gasMaxDepthText = "21"
    backend.onGasPhaseSelected("Ascent/deco")
    backend.addGas()
    for minute in (3, 25):
        backend.addWaypointAt(*xy_of(minute * 60, 40, 700, 420, backend._axes()))

    backend.onScrub(xy_of(25 * 60, 40, 700, 420, backend._axes())[0])
    rows = backend.cursorInfo
    stops = [r["value"] for r in rows if r["label"] in ("Deco stops", "")]
    assert len(stops) >= 3
    assert stops[0].startswith("21 m  1 min") and "EAN50" in stops[0]
    assert stops[-1].startswith("3 m")
    assert any(r["label"] == "TTS" for r in rows)


def _add_gas(backend, name, o2):
    backend.newGas()
    backend.gasNameText = name
    backend.gasO2Text = str(o2)
    backend.onGasTypeSelected("Nitrox")
    backend.addGas()


def test_update_edits_selected_gas_even_after_repeated_edits(settings_file):
    backend = DiveProfileBackend()
    backend.selectGasRow(0)  # Air
    backend.gasMaxDepthText = "40"
    backend.addGas()
    assert backend.selectedGasRow == 0  # stays selected, fields stay loaded
    assert backend.gasNameText == "Air"
    backend.gasMaxDepthText = "50"
    backend.addGas()
    assert [g.id for g in backend.dive_plan.gases] == ["Air"]
    assert backend.dive_plan.gases[0].use_max_depth_m == 50


def test_update_renames_gas_and_its_waypoints(settings_file):
    backend = DiveProfileBackend()
    backend.wpTimeText = "5"
    backend.wpDepthText = "20"
    backend.onWpGasSelected("Air")
    backend.addOrUpdateWaypoint()
    backend.selectGasRow(0)
    backend.gasNameText = "Bottom air"
    backend.addGas()
    assert [g.id for g in backend.dive_plan.gases] == ["Bottom air"]
    assert backend.dive_plan.waypoints[0].gas_id == "Bottom air"


def test_add_after_new_creates_gas_and_rejects_duplicates(settings_file):
    backend = DiveProfileBackend()
    backend.selectGasRow(0)
    backend.newGas()
    assert backend.selectedGasRow == -1
    _add_gas(backend, "EAN32", 32)
    assert [g.id for g in backend.dive_plan.gases] == ["Air", "EAN32"]
    _add_gas(backend, "Air", 21)
    assert "already named 'Air'" in backend.gasStatusText
    assert len(backend.dive_plan.gases) == 2


def test_rename_to_existing_name_is_rejected(settings_file):
    backend = DiveProfileBackend()
    _add_gas(backend, "EAN32", 32)
    backend.selectGasRow(1)
    backend.gasNameText = "Air"
    backend.addGas()
    assert "already named 'Air'" in backend.gasStatusText
    assert [g.id for g in backend.dive_plan.gases] == ["Air", "EAN32"]


def test_removing_selected_gas_clears_selection(settings_file):
    backend = DiveProfileBackend()
    _add_gas(backend, "EAN32", 32)
    backend.selectGasRow(1)
    backend.removeGasAtRow(1)
    assert backend.selectedGasRow == -1
    assert backend.gasNameText == ""


def test_tank_volume_and_start_pressure_are_edited_and_drive_pressure(settings_file):
    backend = DiveProfileBackend()
    backend.selectGasRow(0)
    assert (backend.gasVolumeText, backend.gasStartPressureText) == ("11.1", "207")
    backend.gasVolumeText = "12"
    backend.gasStartPressureText = "232"
    backend.addGas()
    gas = backend.dive_plan.gases[0]
    assert (gas.tank_size_l, gas.start_pressure_bar) == (12, 232)
    assert "12L/232" in backend.gasTableRows[0][4]

    backend.newGas()
    backend.gasNameText = "Stage"
    backend.gasVolumeText = "0"  # must be > 0
    backend.addGas()
    assert "Could not add gas" in backend.gasStatusText
    assert len(backend.dive_plan.gases) == 1


def test_generic_sac_drives_tank_pressure_and_is_remembered(settings_file):
    backend = DiveProfileBackend()
    backend.wpTimeText = "30"
    backend.wpDepthText = "20"
    backend.addOrUpdateWaypoint()
    end_at_20 = backend.dive_profile_samples[-1].tank_pressure_bar
    backend.sacText = "10"
    end_at_10 = backend.dive_profile_samples[-1].tank_pressure_bar
    assert end_at_10 > end_at_20  # half the gas used
    start = backend.dive_plan.gases[0].start_pressure_bar
    assert start - end_at_10 == pytest.approx((start - end_at_20) / 2, rel=0.02)

    backend.sacText = "0"  # ignored
    assert backend.dive_plan.sac_lpm == 10
    assert DiveProfileBackend().dive_plan.sac_lpm == 10


def test_new_gases_default_to_al80_on_next_free_tank(settings_file):
    backend = DiveProfileBackend()
    assert backend.dive_plan.gases[0].tank_ref == "T1"
    assert (backend.gasTankText, backend.gasVolumeText, backend.gasStartPressureText) == ("T2", "11.1", "207")
    _add_gas(backend, "EAN50", 50)
    assert backend.gasTankText == "T3"  # editor moves on after Add
    _add_gas(backend, "O2", 100)
    gases = backend.dive_plan.gases
    assert [g.tank_ref for g in gases] == ["T1", "T2", "T3"]
    assert all((g.tank_size_l, g.start_pressure_bar) == (11.1, 207) for g in gases)

    backend.removeGasAtRow(1)  # frees T2
    backend.newGas()
    assert backend.gasTankText == "T2"


# --- Dive type, log details, saving ----------------------------------------

def _with_waypoint(backend, minutes="30", depth="20"):
    backend.wpTimeText = minutes
    backend.wpDepthText = depth
    backend.addOrUpdateWaypoint()


def test_switching_to_ccr_makes_the_first_gas_the_diluent_and_is_remembered(settings_file):
    backend = DiveProfileBackend()
    _with_waypoint(backend)
    backend.onDiveTypeSelected("CCR")
    assert backend.isCcr and backend.diveTypeLabel == "CCR"
    assert backend.dive_plan.gases[0].diluent
    assert backend.gasTableRows[0][1] == "DIL"
    assert {s.divemode for s in backend.dive_profile_samples} == {"closedcircuit"}
    assert not backend.statusIsError

    restarted = DiveProfileBackend()  # fresh Air gas, still a CCR dive - and a working one
    assert restarted.isCcr and restarted.dive_plan.gases[0].diluent


def test_a_new_diluent_replaces_the_old_one(settings_file):
    backend = DiveProfileBackend()
    backend.onDiveTypeSelected("CCR")
    backend.newGas()
    assert not backend.gasDiluent  # the dive already has one
    backend.gasNameText = "Tx18/45"
    backend.gasO2Text = "18"
    backend.gasHeText = "45"
    backend.gasDiluent = True
    backend.addGas()
    assert [g.diluent for g in backend.dive_plan.gases] == [False, True]
    assert [row[1] for row in backend.gasTableRows] == ["BAILOUT", "DIL"]


def test_setpoints_apply_only_as_a_valid_pair(settings_file):
    backend = DiveProfileBackend()
    backend.onDiveTypeSelected("CCR")
    backend.ccrLowSetpointText = "1.4"  # above the 1.3 high while typing
    assert backend.ccrErrorText
    assert backend.dive_plan.ccr_low_setpoint == 0.7
    backend.ccrHighSetpointText = "1.5"
    assert backend.ccrErrorText == ""
    assert (backend.dive_plan.ccr_low_setpoint, backend.dive_plan.ccr_high_setpoint) == (1.4, 1.5)
    assert DiveProfileBackend().dive_plan.ccr_high_setpoint == 1.5


def test_sidemount_needs_a_left_and_a_right_tank_before_the_dive_builds(settings_file):
    backend = DiveProfileBackend()
    _with_waypoint(backend, minutes="40")
    backend.onDiveTypeSelected("Sidemount")
    assert backend.isSidemount and backend.dive_plan.gases[0].side == "left"
    # One side only: nothing is simulated, and the status says why.
    assert not backend.dive_profile_samples
    assert "Left" in backend.statusText and "Right" in backend.statusText
    # The editor offers the right-hand twin of the left tank, in a tank of its own.
    assert backend.gasSideLabel == "Right"
    assert (backend.gasNameText, backend.gasO2Text, backend.gasTankText) == ("Air R", "21", "T2")
    backend.addGas()
    assert backend.gasStatusText == ""
    assert [r[4].split()[:2] for r in backend.gasTableRows] == [["T1", "Left"], ["T2", "Right"]]
    assert backend.dive_profile_samples
    # The right tank is part of the left tank's gas, not a gas of its own.
    assert backend.wpGasChoices == ["Auto", "Air"]
    backend.sidemountSwitchText = "20"
    assert backend.dive_plan.sidemount_switch_bar == 20
    backend.dive_profile_cursor_time = 1200
    backend._update_cursor_info()
    tanks = next(row for row in backend.cursorInfo if row["label"] == "Tanks")
    assert "T1" in tanks["value"] and "T2" in tanks["value"]


def test_sidemount_sides_are_one_each_and_of_the_same_gas(settings_file):
    backend = DiveProfileBackend()
    backend.onDiveTypeSelected("Sidemount")
    # A second left tank is refused.
    backend.newGas()
    backend.onGasSideSelected("Left")
    backend.addGas()
    assert "already the left tank" in backend.gasStatusText
    # A right tank of another gas is refused.
    backend.newGas()
    backend.gasO2Text = "32"
    backend.addGas()
    assert "same gas" in backend.gasStatusText
    assert len(backend.dive_plan.gases) == 1
    # A stage is fine, and changing the left tank's gas changes the right one too.
    backend.newGas()
    backend.addGas()
    backend.onGasSideSelected("Stage")
    backend.gasNameText = "EAN50"
    backend.gasO2Text = "50"
    backend.addGas()
    assert [(g.id, g.side) for g in backend.dive_plan.gases] == [("Air", "left"), ("Air R", "right"), ("EAN50", None)]
    backend.selectGasRow(0)
    backend.gasO2Text = "32"
    backend.addGas()
    assert backend.dive_plan.gases[1].o2_percent == 32


def test_log_details_are_validated_and_computer_is_remembered(settings_file):
    backend = DiveProfileBackend()
    assert backend.computerLabel == "Shearwater Perdix 2"
    backend.onComputerSelected("Garmin Descent X50i")
    backend.serialText = "12ab"
    backend.startTimeText = "20/09/2026"
    assert "digits" in backend.logErrorText and "YYYY-MM-DD" in backend.logErrorText
    backend.serialText = "987654"
    backend.startTimeText = "2026-09-20 10:15"
    assert backend.logErrorText == ""
    assert backend.dive_plan.start_time == datetime(2026, 9, 20, 10, 15)

    restarted = DiveProfileBackend()
    assert (restarted.computerLabel, restarted.serialText) == ("Garmin Descent X50i", "987654")
    assert restarted.startTimeText == ""  # per dive - not remembered


@pytest.mark.parametrize("suffix", [".uddf", ".fit", ".ssrf"])
def test_write_log_picks_the_format_from_the_extension(settings_file, tmp_path, suffix):
    backend = DiveProfileBackend()
    _with_waypoint(backend)
    backend.onComputerSelected("Garmin Descent Mk3i")
    backend.startTimeText = "2026-09-20 10:15"
    path = tmp_path / f"dive{suffix}"
    backend.write_log(path)
    parser = {".uddf": UDDFParser, ".fit": GarminParser, ".ssrf": SubsurfaceParser}[suffix]()
    dive = parser.parse(path)[0]
    assert dive.start_time == datetime(2026, 9, 20, 10, 15)


def test_write_log_refuses_bad_details_and_unknown_formats(settings_file, tmp_path):
    backend = DiveProfileBackend()
    _with_waypoint(backend)
    with pytest.raises(ValueError, match="Unknown log format"):
        backend.write_log(tmp_path / "dive.txt")
    with pytest.raises(ValueError, match="Garmin"):
        backend.write_log(tmp_path / "dive.fit")  # default computer is a Shearwater
    backend.startTimeText = "tomorrow"
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        backend.write_log(tmp_path / "dive.uddf")


def test_hover_shows_ceiling_at_both_gfs_and_chart_gets_stop_schedules(settings_file):
    from gui.dive_profile_view import xy_of

    backend = DiveProfileBackend()
    backend.defineScale("45", "60")
    for minute in (3, 25):
        backend.addWaypointAt(*xy_of(minute * 60, 40, 700, 420, backend._axes()))
    assert backend.dive_deco_schedules

    backend.onScrub(xy_of(25 * 60, 40, 700, 420, backend._axes())[0])
    ceiling = next(r["value"] for r in backend.cursorInfo if r["label"] == "Ceiling")
    assert "(GF 70)" in ceiling and "(GF 30)" in ceiling


def _saved_log(tmp_path, fmt="uddf"):
    from models.dive_plan import DiveProfilePlan, PlannedGas, PlannedWaypoint
    from parsers.uddf_writer import write_uddf
    from parsers.fit_writer import write_fit
    from utils.dive_plan_engine import simulate

    plan = DiveProfilePlan(
        name="Reopen me", gf_low=35, gf_high=80, sac_lpm=18, computer="Garmin Descent X50i", computer_serial="777",
        start_time=datetime(2026, 9, 27, 9, 30), dive_type="oc", max_depth_m=25.0, planned_runtime_sec=2400,
        gases=[PlannedGas(id="Air", gas_type="air", o2_percent=21.0, start_pressure_bar=210)],
        waypoints=[PlannedWaypoint(runtime_sec=90, depth_m=20.0, gas_id="Air"),
                   PlannedWaypoint(runtime_sec=1500, depth_m=20.0, gas_id="Air"),
                   PlannedWaypoint(runtime_sec=1800, depth_m=0.0, gas_id="Air")],
    )
    samples, _ = simulate(plan, resolution_sec=1)
    path = tmp_path / f"reopen.{fmt}"
    (write_fit if fmt == "fit" else write_uddf)(plan, samples, path)
    return plan, path


def test_open_log_restores_the_saved_plan_and_the_settings_texts(settings_file, tmp_path):
    plan, path = _saved_log(tmp_path)
    backend = DiveProfileBackend()
    message = backend.load_log(path)
    assert "restored as saved" in message
    assert backend.dive_plan.model_dump() == plan.model_dump()
    assert backend.nameText == "Reopen me"
    assert (backend.gfLowText, backend.gfHighText) == ("35", "80")
    assert backend.sacText == "18"
    assert backend.computerLabel == "Garmin Descent X50i"
    assert backend.serialText == "777"
    assert backend.startTimeText == "2026-09-27 09:30"
    assert backend.maxDepthText == "25"
    assert len(backend.waypointRows) == 3
    assert len(backend.gasTableRows) == 1
    assert backend.dive_profile_samples  # resimulated
    # the settings pane's values are remembered like typed ones
    fields = json.loads(settings_file.read_text())["fields"]
    assert (fields[GF_LOW_FIELD], fields[GF_HIGH_FIELD]) == (35, 80)
    assert fields["dive_profile_computer"] == "Garmin Descent X50i"


@pytest.mark.parametrize("path, gf, gases", [
    ("fit/489 Camera Bay_new.fit", None, None),
    ("submersion_dives/005_oc-trimix-two-deco-gases--perdix2.uddf", (50, 85), ["CC1", "OC1", "OC2", "OC3"]),
    # Subsurface's own "Buhlmann ZHL-16C 40/85" - not GF 16/40.
    ("ssrf/494.ssrf", (40, 85), ["Air"]),
])
@pytest.mark.requires_media
def test_open_log_imports_logs_uwmedia_did_not_write(settings_file, path, gf, gases):
    backend = DiveProfileBackend()
    message = backend.load_log(str(LOGS_DIR / path))
    assert message.startswith("Imported")
    if gf:
        assert (backend.dive_plan.gf_low, backend.dive_plan.gf_high) == gf
    if gases:
        assert [g.id for g in backend.dive_plan.gases] == gases
    assert backend.waypointRows
    assert backend.dive_profile_samples


@pytest.mark.requires_media
def test_open_log_imports_fit_with_samples_before_its_start(settings_file):
    # The parser gives this older FIT's samples negative times (-6346..-1 s).
    backend = DiveProfileBackend()
    backend.load_log(str(LOGS_DIR / "fit/garmin_2023-10-21-12-13-38.fit"))
    plan = backend.dive_plan
    assert plan.start_time == datetime(2023, 10, 21, 12, 13, 38)
    assert min(w.runtime_sec for w in plan.waypoints) >= 0
    assert max(w.runtime_sec for w in plan.waypoints) > 3600


def test_open_log_refuses_files_it_cannot_read(settings_file, tmp_path):
    backend = DiveProfileBackend()
    before = backend.dive_plan.model_dump()
    other = tmp_path / "notes.csv"
    other.write_text("a,b\n1,2\n")
    with pytest.raises(ValueError, match="Unknown log format"):
        backend.load_log(other)
    assert backend.dive_plan.model_dump() == before


@pytest.mark.requires_media
@pytest.mark.parametrize("suffix", [".xml", ".csv"])
def test_open_log_imports_a_shearwater_cloud_export(settings_file, suffix):
    backend = DiveProfileBackend()
    message = backend.load_log(str(LOGS_DIR / f"alternative_formats/Perdix 2[A5419AC1]#451 2025-10-19 11-42-39{suffix}"))
    assert message.startswith("Imported")
    plan = backend.dive_plan
    assert (plan.gf_low, plan.gf_high) == (40, 85)
    assert [(g.id, g.o2_percent) for g in plan.gases] == [("Air", 21.0)]
    assert plan.gases[0].start_pressure_bar == 194
    assert plan.start_time == datetime(2025, 10, 19, 11, 42, 39)
    assert backend.computerLabel == "Shearwater Perdix 2"
    assert backend.waypointRows


@pytest.mark.requires_media
def test_open_log_rebuilds_an_older_uddf_without_embedded_plan(settings_file):
    backend = DiveProfileBackend()
    message = backend.load_log(str(LOGS_DIR / "DecoTest.uddf"))
    assert "rebuilt" in message
    assert backend.computerLabel == "Garmin Descent X50i"
    assert backend.dive_plan.dive_type == "sidemount"
    assert backend.waypointRows
    assert backend.dive_profile_samples


def test_log_dialogs_start_in_home_then_remember_the_last_folder(settings_file, tmp_path, monkeypatch):
    from pathlib import Path

    from PySide6.QtWidgets import QFileDialog, QMessageBox

    home, logs = tmp_path / "home", tmp_path / "logs"
    home.mkdir()
    logs.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(QMessageBox, "information", lambda *a: None)
    starts = []

    def fake_save(parent, title, start, *rest):
        starts.append(Path(start).parent)
        return str(logs / "dive.uddf"), rest[1]

    def fake_open(parent, title, start, *rest):
        starts.append(Path(start))
        return "", ""

    monkeypatch.setattr(QFileDialog, "getSaveFileName", fake_save)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", fake_open)
    backend = DiveProfileBackend()
    monkeypatch.setattr(backend, "write_log", lambda path: [])

    backend.saveLog()
    backend.openLog()
    assert starts == [home, logs]
