"""
Exercises the Log Viewer backend (uwmedia/backends/log_viewer_backend.py):
the working list (add files / a folder, duplicates skipped, remove, clear),
the selected dive's details and the filtered sample table, against the real
logs under test_data/logs. The backend is built with background=False so
reading happens inline; the tank mapping and settings.json are stubbed so
nothing outside the test's tmp_path is read or written.
"""
from datetime import datetime
from pathlib import Path

import pytest

from conftest import LOGS_DIR
import uwmedia.backends.log_viewer_backend as lvb
from uwmedia.backends.log_viewer_backend import LAST_FOLDER_FIELD, LogViewerBackend

LOGS = LOGS_DIR
FIT = LOGS / "fit" / "451 Tioman Island, Palau Labas.fit"
UDDF = LOGS / "uddf" / "Perdix 2 451 2025-10-19 11-42-39.uddf"
SSRF = LOGS / "ssrf" / "494.ssrf"
CSV = LOGS / "alternative_formats" / "subsurfac_496.csv"


class _Config:
    def get_tank_mapping(self):
        return {"3456789": "Right"}


@pytest.fixture
def backend(settings_file, monkeypatch):
    monkeypatch.setattr(lvb, "get_config", lambda: _Config())
    return LogViewerBackend(background=False)


@pytest.mark.requires_media
def test_add_files_lists_dives_sorted_and_selects_first(backend):
    backend.addFiles([str(SSRF), str(FIT)])
    assert backend.diveCount == 2
    rows = backend.dives
    assert [r["date"] for r in rows] == sorted(r["date"] for r in rows)
    assert rows[0]["file"] == FIT.name
    assert backend.currentRow == 0
    assert backend.selected["file"] == FIT.name
    assert backend.files == sorted([FIT.name, SSRF.name], key=str.lower)
    assert backend.message == "Added 2 dives."


@pytest.mark.requires_media
def test_details_of_a_garmin_fit(backend):
    backend.addFiles([str(FIT)])
    sel = backend.selected
    assert sel["format"] == "Garmin FIT"
    assert sel["start"] == "2025-10-19 11:42:59"
    assert sel["max_depth"] == "12.8 m"
    assert sel["timezone"] == "UTC+08:00"
    assert sel["lat"] and sel["lng"]
    assert sel["temp_min"].endswith("°C")
    assert sel["avg_depth"].endswith(" m")
    # the tank is keyed by its friendly name; the mapping gives the serial back
    tank = sel["tanks"][0]
    assert tank["key"] == "Right"
    assert tank["serial"] == "3456789"
    assert tank["mix"] == "Air"
    assert tank["start_pressure"].endswith("bar")
    assert "heart rate" in sel["channels"] and "tank pressure" in sel["channels"]
    # Garmin's alerts are listed, its "dismissed" noise is not
    assert any("safety stop started" in e for e in sel["events"])
    assert not any("dismissed" in e for e in sel["events"])
    assert sel["sample_count"] == 2612
    assert 1 < len(sel["samples"]) <= lvb.MAX_CHART_POINTS + 1
    assert sel["samples"][-1]["time"] == backend._dives[0].waypoints[-1].time_since_start


@pytest.mark.requires_media
@pytest.mark.parametrize("path, fmt", [(UDDF, "UDDF"), (SSRF, "Subsurface"), (CSV, "Subsurface CSV")])
def test_details_of_other_formats(backend, path, fmt):
    backend.addFiles([str(path)])
    sel = backend.selected
    assert sel["format"] == fmt
    assert sel["file"] == path.name
    assert sel["max_depth"].endswith(" m")
    assert len(sel["samples"]) > 1


@pytest.mark.requires_media
def test_empty_values_are_blank_strings(backend):
    backend.addFiles([str(CSV)])
    sel = backend.selected
    # no device, GPS, tanks or time zone in a Subsurface CSV
    assert sel["device"] == ""
    assert sel["lat"] == "" and sel["exit_lat"] == ""
    assert sel["timezone"] == ""
    assert sel["tanks"] == []


@pytest.mark.requires_media
def test_reopening_a_file_skips_its_dives(backend):
    backend.addFiles([str(FIT)])
    backend.addFiles([str(FIT), str(UDDF)])
    assert backend.diveCount == 2
    assert backend.message == "Added 1 dive, 1 already in the list."


@pytest.mark.requires_media
def test_one_dive_in_two_files_opened_together(backend, tmp_path):
    # Two copies of one dive compare equal field by field; pydantic's == on
    # them recursed through Waypoint._dive until RecursionError.
    a, b = tmp_path / "a.ssrf", tmp_path / "b.ssrf"
    a.write_bytes(SSRF.read_bytes())
    b.write_bytes(SSRF.read_bytes())
    backend.addFiles([str(a), str(b)])
    assert backend.diveCount == 2
    assert backend.currentRow == 0
    backend.select(1)
    backend.removeSelected()
    assert backend.diveCount == 1


@pytest.mark.requires_media
def test_selection_is_kept_when_dives_are_added(backend):
    backend.addFiles([str(SSRF)])
    backend.addFiles([str(FIT)])  # an earlier dive, sorts in above
    assert backend.dives[0]["file"] == FIT.name
    assert backend.currentRow == 1
    assert backend.selected["file"] == SSRF.name


@pytest.mark.requires_media
def test_select_ignores_rows_out_of_range(backend):
    backend.addFiles([str(FIT), str(SSRF)])
    backend.select(1)
    backend.select(5)
    backend.select(-1)
    assert backend.currentRow == 1


@pytest.mark.requires_media
def test_remove_selected_moves_to_the_next_dive(backend):
    backend.addFiles([str(FIT), str(UDDF), str(SSRF)])
    backend.select(1)
    removed = backend.selected["file"]
    backend.removeSelected()
    assert backend.diveCount == 2
    assert removed not in backend.files
    assert backend.currentRow == 1
    backend.removeSelected()
    assert backend.currentRow == 0  # the last row went; the one above is picked
    backend.removeSelected()
    assert backend.diveCount == 0
    assert backend.currentRow == -1
    assert backend.selected == {}
    assert backend.tableRows == []


def test_clear_empties_everything(backend, tmp_path):
    bad = tmp_path / "broken.fit"
    bad.write_bytes(b"not a fit file")
    backend.addFiles([str(FIT), str(bad)])
    assert backend.warnings
    backend.clear()
    assert backend.diveCount == 0
    assert backend.files == [] and backend.warnings == []
    assert backend.selected == {}


@pytest.mark.requires_media
def test_unreadable_file_gives_a_warning(backend, tmp_path):
    bad = tmp_path / "broken.fit"
    bad.write_bytes(b"not a fit file")
    backend.addFiles([str(bad), str(SSRF)])
    assert backend.diveCount == 1
    assert len(backend.warnings) == 1
    assert backend.warnings[0].startswith("broken.fit:")


@pytest.mark.requires_media
def test_add_folder_reads_every_log_and_remembers_it(backend, settings_file):
    folder = LOGS / "ssrf"
    backend.addFolder(str(folder))
    assert backend.diveCount == 2
    assert lvb.get_fields()[LAST_FOLDER_FIELD] == str(folder)
    assert backend._dialog_folder() == str(folder)


def test_add_folder_without_logs(backend, tmp_path):
    (tmp_path / "notes.txt").write_text("hello")
    backend.addFolder(str(tmp_path))
    assert backend.diveCount == 0
    assert backend.message == f"No dive logs in {tmp_path.name}."


@pytest.mark.requires_media
def test_sample_table_and_filter(backend):
    backend.addFiles([str(FIT)])
    rows = backend.tableRows
    assert len(rows) == 2612
    assert len(rows[0]) == len(backend.tableHeaders)
    assert "Right (3456789)" in rows[100][-1]  # the Tanks column comes last
    backend.filterText = "12:05:18"
    assert len(backend.tableRows) == 1
    # a new selection clears the filter
    backend.addFiles([str(SSRF)])
    backend.select(1)
    assert backend.filterText == ""


@pytest.mark.requires_media
def test_chart_samples_are_thinned_but_keep_both_ends(backend):
    backend.addFiles([str(SSRF)])
    dive = backend._dives[0]
    samples = lvb._chart_samples(dive)
    assert len(samples) <= lvb.MAX_CHART_POINTS + 1
    assert samples[0]["time"] == dive.waypoints[0].time_since_start
    assert samples[-1]["time"] == dive.waypoints[-1].time_since_start


def test_numbers_and_headers_follow_the_unit_system():
    from utils import units as U
    with U.units_override("imperial"):
        assert lvb._num(10.0, "m") == "32.8 ft" and lvb._num(207.0, "bar", 0) == "3002 psi" and lvb._num(27.0, "°C") == "80.6 °F"
        assert lvb.table_headers()[1:3] == ["Depth (ft)", "Temp (°F)"]
    with U.units_override("metric"):
        assert lvb._num(10.0, "m") == "10.0 m" and lvb.table_headers()[1:3] == ["Depth (m)", "Temp (°C)"]


@pytest.mark.requires_media
def test_units_change_refreshes_the_selected_dive(backend):
    from utils import units as U
    backend.addFiles([str(FIT)])
    metric_depth = backend.selected["max_depth"]
    with U.units_override("imperial"):
        backend.unitsChanged()
        assert backend.selected["max_depth"].endswith(" ft") and backend.selected["depth_unit"] == "ft"
        assert backend.tableHeaders[1] == "Depth (ft)"
        assert backend.currentRow == 0
    with U.units_override("metric"):
        backend.unitsChanged()
    assert backend.selected["max_depth"] == metric_depth


def test_a_ccr_dive_shows_its_po2_strip_columns_events_and_rebreather_line():
    from conftest import synthetic_ccr_plan
    from parsers.uddf_writer import write_uddf
    from utils.dive_plan_engine import simulate
    import tempfile
    from pathlib import Path
    from parsers.registry import parse_log_file

    plan = synthetic_ccr_plan(datetime(2026, 3, 1, 9, 0))
    samples, _ = simulate(plan, resolution_sec=2)
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "ccr.uddf"
        write_uddf(plan, samples, path)
        dive, = parse_log_file(path)
    details = lvb.dive_details(dive, {})
    assert details["rebreather"].startswith("CCR, diluent Tx 18/45, setpoint 0.7 / 1.3, bailout ")
    strip = details["po2_samples"]
    assert strip and any(p["bailout"] for p in strip) and all(p["setpoint"] == -1 for p in strip if p["bailout"])
    assert {"setpoint", "ppO₂ cells"} <= set(details["channels"])
    events = details["events"]
    assert any("setpoint 0.7 → 1.3" in e for e in events) and any("bailout to open circuit" in e for e in events)
    assert any("back on the loop" in e for e in events) and any("gas change: 18/45 → Nx50" in e for e in events)
    row = next(r for r in lvb.sample_rows(dive, {}) if r["circuit"] == "CC" and r["setpoint"] == "1.3")
    assert row["gas"] == "18/45" and len(row["cells"].split(" / ")) == 3
    assert len(lvb.table_headers()) == len(lvb.TABLE_COLUMNS)


def test_an_open_circuit_dive_has_no_po2_strip():
    from parsers.registry import parse_log_file
    from conftest import write_synthetic_log
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as folder:
        dive, = parse_log_file(write_synthetic_log(Path(folder) / "oc.uddf", datetime(2026, 3, 1, 9, 0)))
    details = lvb.dive_details(dive, {})
    assert details["po2_samples"] == [] and details["rebreather"] == ""
