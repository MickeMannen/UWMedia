"""parsers/fit_merge.py: two Garmin FIT logs of one dive joined into a single
log - the clock kept and the gap filled, or the gap closed - and the Log
Viewer's "Merge dives" around it. Synthetic logs from the app's FIT writer
(a second dive written as the continuation of the first) make the default
run; a pair of real Descent logs is checked when test_data is there."""
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from garmin_fit_sdk import Decoder, Stream

from conftest import LOGS_DIR, synthetic_plan, write_synthetic_log
from models.dive_plan import PlannedGas
from parsers.fit_merge import MAX_GAP_SECONDS, merge_fit_dives
from parsers.fit_time import adjust_fit_time
from parsers.fit_writer import write_fit
from parsers.garmin import GarminParser
import uwmedia.backends.log_viewer_backend as lvb
from uwmedia.backends.log_viewer_backend import LogViewerBackend, candidate_label, merge_candidates, merged_name
from utils.dive_plan_engine import simulate

GARMIN = "Garmin Descent Mk3i"
START = datetime(2026, 1, 1, 10, 0)
REAL_FIRST = LOGS_DIR / "fit" / "450 Tioman Island, Palau Labas.fit"
REAL_SECOND = LOGS_DIR / "fit" / "451 Tioman Island, Palau Labas.fit"


def _parse(path):
    return GarminParser().parse(path)[0]


def _decode(path):
    decoder = Decoder(Stream.from_file(str(path)))
    assert decoder.check_integrity(), "header or file CRC"
    messages, errors = Decoder(Stream.from_file(str(path))).read(convert_datetimes_to_dates=False)
    assert errors == []
    return messages


def _write(path, start, o2=21.0, bottom_min=20):
    """A synthetic Garmin dive at `start`; `o2` other than 21 makes it a
    nitrox dive, i.e. a different gas from the default air dive."""
    plan = synthetic_plan(start, GARMIN, bottom_min=bottom_min)
    if o2 != 21.0:
        plan.gases = [PlannedGas(id=f"Nx{o2:.0f}", gas_type="nitrox", o2_percent=o2, start_pressure_bar=200)]
        for wp in plan.waypoints:
            wp.gas_id = plan.gases[0].id
    samples, _ = simulate(plan, resolution_sec=2)
    write_fit(plan, samples, path)
    return path


@pytest.fixture
def pair(tmp_path):
    """Two synthetic FIT logs 30 minutes apart, as a split dive would leave them."""
    first = _write(tmp_path / "Dive 12.fit", START)
    end = _parse(first).end_time
    second = _write(tmp_path / "Dive 13.fit", (end + timedelta(minutes=30)).replace(microsecond=0), o2=32.0)
    return first, second


def test_keep_clock_fills_the_gap_with_the_last_sample(pair, tmp_path):
    first, second = pair
    d1, d2 = _parse(first), _parse(second)
    out = tmp_path / "merged.fit"

    result = merge_fit_dives(first, second, out, close_gap=False)

    merged = _parse(out)
    assert merged.start_time == d1.start_time
    assert merged.end_time == d2.end_time
    assert result.shift_seconds == 0
    assert result.gases_added == 1
    gap = d2.waypoints[0].timestamp - d1.waypoints[-1].timestamp
    assert result.gap_seconds == gap.total_seconds()
    # Samples every 2 s (the logs' interval) across the gap, all copies of the first dive's last sample.
    assert result.filled_samples == gap.total_seconds() // 2 - 1
    assert len(merged.waypoints) == len(d1.waypoints) + result.filled_samples + len(d2.waypoints)
    n1 = len(d1.waypoints)
    filled = merged.waypoints[n1:n1 + result.filled_samples]
    assert {wp.depth for wp in filled} == {d1.waypoints[-1].depth}
    assert [wp.timestamp for wp in filled] == [d1.waypoints[-1].timestamp + timedelta(seconds=2 * k)
                                               for k in range(1, result.filled_samples + 1)]
    # The second dive keeps its clock and its profile.
    tail = merged.waypoints[n1 + result.filled_samples:]
    assert [wp.timestamp for wp in tail] == [wp.timestamp for wp in d2.waypoints]
    assert [wp.depth for wp in tail] == [wp.depth for wp in d2.waypoints]
    assert [wp.depth for wp in merged.waypoints[:n1]] == [wp.depth for wp in d1.waypoints]
    assert merged.max_depth == max(d1.max_depth, d2.max_depth)
    # Dive time runs on through the gap.
    assert tail[0].time_since_start == (d2.waypoints[0].timestamp - d1.start_time).total_seconds()


def test_close_gap_moves_the_second_dive_back(pair, tmp_path):
    first, second = pair
    d1, d2 = _parse(first), _parse(second)
    out = tmp_path / "merged.fit"

    result = merge_fit_dives(first, second, out, close_gap=True)

    merged = _parse(out)
    assert result.filled_samples == 0
    assert result.shift_seconds == -(result.gap_seconds - 2)
    assert len(merged.waypoints) == len(d1.waypoints) + len(d2.waypoints)
    assert merged.start_time == d1.start_time
    n1 = len(d1.waypoints)
    assert merged.waypoints[n1].timestamp == d1.waypoints[-1].timestamp + timedelta(seconds=2)
    shift = timedelta(seconds=result.shift_seconds)
    assert [wp.timestamp for wp in merged.waypoints[n1:]] == [wp.timestamp + shift for wp in d2.waypoints]
    assert [wp.depth for wp in merged.waypoints] == [wp.depth for wp in d1.waypoints + d2.waypoints]
    assert merged.end_time == d2.end_time + shift
    # The originals are untouched.
    assert _parse(first).end_time == d1.end_time and _parse(second).start_time == d2.start_time


def test_merged_file_decodes_with_both_gases_and_one_timer(pair, tmp_path):
    first, second = pair
    out = tmp_path / "merged.fit"
    merge_fit_dives(first, second, out, close_gap=True)

    messages = _decode(out)
    gases = [(g["message_index"], g["oxygen_content"]) for g in messages["dive_gas_mesgs"]]
    assert gases == [(0, 21), (1, 32)]
    # The second log starts on Nx32 without saying so (the app's writer logs a
    # switch only mid-dive), so the merge records the switch at the join.
    switches = [(e["timestamp"], e["data"]) for e in messages["event_mesgs"] if e.get("event") == "dive_gas_switched"]
    second_record = messages["record_mesgs"][len(_parse(first).waypoints)]
    assert switches == [(second_record["timestamp"], 1)]
    timers = [(e["event_type"]) for e in messages["event_mesgs"] if e.get("event") == "timer"]
    assert timers == ["start", "stop_all"]
    assert len(messages["session_mesgs"]) == len(messages["activity_mesgs"]) == len(messages["file_id_mesgs"]) == 1
    d1, d2 = _parse(first), _parse(second)
    merged = _parse(out)
    assert messages["session_mesgs"][0]["total_timer_time"] == pytest.approx(
        (merged.end_time - merged.start_time).total_seconds())
    summary = messages["dive_summary_mesgs"][0]
    assert summary["max_depth"] == pytest.approx(max(d1.max_depth, d2.max_depth), abs=0.001)
    first_summary = _decode(first)["dive_summary_mesgs"][0]
    second_summary = _decode(second)["dive_summary_mesgs"][0]
    assert summary["bottom_time"] == pytest.approx(first_summary["bottom_time"] + second_summary["bottom_time"])
    # The writer gives both logs the same tank pod, so one summary spans the merged dive.
    tank, = messages["tank_summary_mesgs"]
    assert tank["start_pressure"] == _decode(first)["tank_summary_mesgs"][0]["start_pressure"]
    assert tank["end_pressure"] == _decode(second)["tank_summary_mesgs"][0]["end_pressure"]
    assert tank["volume_used"] == pytest.approx(_decode(first)["tank_summary_mesgs"][0]["volume_used"]
                                                + _decode(second)["tank_summary_mesgs"][0]["volume_used"], abs=0.02)
    assert merged.waypoints[-1].primary_tank_pressure == pytest.approx(tank["end_pressure"])


def test_same_gas_is_not_listed_twice(tmp_path):
    first = _write(tmp_path / "a.fit", START)
    end = _parse(first).end_time
    second = _write(tmp_path / "b.fit", (end + timedelta(minutes=5)).replace(microsecond=0))
    result = merge_fit_dives(first, second, tmp_path / "m.fit", close_gap=False)
    assert result.gases_added == 0
    messages = _decode(tmp_path / "m.fit")
    assert len(messages["dive_gas_mesgs"]) == 1
    # Neither synthetic log switches gas, so nothing is added at the join either.
    assert [e for e in messages["event_mesgs"] if e.get("event") == "dive_gas_switched"] == []


def test_refuses_dives_too_far_apart_or_in_the_wrong_order(pair, tmp_path):
    first, second = pair
    with pytest.raises(ValueError, match="other way round"):
        merge_fit_dives(second, first, tmp_path / "m.fit", close_gap=False)
    with pytest.raises(ValueError, match="other way round"):
        merge_fit_dives(first, first, tmp_path / "m.fit", close_gap=False)
    far = tmp_path / "far.fit"
    adjust_fit_time(second, far, _parse(first).end_time + timedelta(seconds=MAX_GAP_SECONDS + 60), 0)
    with pytest.raises(ValueError, match="hours apart"):
        merge_fit_dives(first, far, tmp_path / "m.fit", close_gap=False)
    assert not (tmp_path / "m.fit").exists()


def test_not_a_fit_file(pair, tmp_path):
    first, _ = pair
    other = tmp_path / "dive.uddf"
    write_synthetic_log(other, START + timedelta(hours=1))
    with pytest.raises(ValueError):
        merge_fit_dives(first, other, tmp_path / "m.fit", close_gap=False)


@pytest.mark.requires_media
@pytest.mark.parametrize("close_gap", [False, True])
def test_real_descent_logs(tmp_path, close_gap):
    d1, d2 = _parse(REAL_FIRST), _parse(REAL_SECOND)
    out = tmp_path / "merged.fit"
    result = merge_fit_dives(REAL_FIRST, REAL_SECOND, out, close_gap=close_gap)

    messages = _decode(out)
    merged = _parse(out)
    assert merged.start_time == d1.start_time
    assert merged.max_depth == max(d1.max_depth, d2.max_depth)
    assert merged.device == d1.device
    expected = len(d1.waypoints) + len(d2.waypoints) + result.filled_samples
    assert len(merged.waypoints) == len(messages["record_mesgs"]) == expected
    if close_gap:
        assert result.filled_samples == 0
        assert merged.end_time == d2.end_time + timedelta(seconds=result.shift_seconds)
    else:
        assert result.filled_samples > 0
        assert merged.end_time == d2.end_time
        # Mid-interval the merged log shows the surface, as the first dive ended.
        at = merged.get_waypoint_at(d1.end_time + timedelta(minutes=10))
        assert at.depth == d1.waypoints[-1].depth
    # Garmin's own messages come along: GPS from both, one summary set.
    assert len(messages["gps_metadata_mesgs"]) == (len(_decode(REAL_FIRST)["gps_metadata_mesgs"])
                                                   + len(_decode(REAL_SECOND)["gps_metadata_mesgs"]))
    assert len(messages["session_mesgs"]) == 1
    tank = messages["tank_summary_mesgs"][0]
    assert tank["start_pressure"] == _decode(REAL_FIRST)["tank_summary_mesgs"][0]["start_pressure"]
    assert tank["end_pressure"] == _decode(REAL_SECOND)["tank_summary_mesgs"][0]["end_pressure"]
    assert messages["dive_summary_mesgs"][0]["dive_number"] == 450


# -- the Log Viewer around it ----------------------------------------------


class _Config:
    def get_tank_mapping(self):
        return {}


@pytest.fixture
def viewer(settings_file, monkeypatch):
    monkeypatch.setattr(lvb, "get_config", lambda: _Config())
    return LogViewerBackend(background=False)


def test_candidates_are_later_fit_dives_within_the_limit(pair, tmp_path):
    first, second = pair
    d1, d2 = _parse(first), _parse(second)
    far = tmp_path / "far.fit"
    adjust_fit_time(second, far, d2.end_time + timedelta(seconds=MAX_GAP_SECONDS + 60), 0)
    d3 = _parse(far)
    uddf = tmp_path / "u.uddf"
    write_synthetic_log(uddf, (d1.end_time + timedelta(minutes=10)).replace(microsecond=0))
    d4 = lvb.read_logs([uddf])[0][0]
    for d, p in ((d1, first), (d2, second), (d3, far)):
        d.log_path, d.log_filename, d.log_format = str(p), p.name, "fit"
    dives = [d1, d2, d3, d4]
    assert merge_candidates(dives, d1) == [d2]  # d3 is too far, the UDDF dive isn't FIT
    assert merge_candidates(dives, d2) == []  # d3 is too far, d1 is earlier
    assert candidate_label(d1, d2) == f"{d2.start_time:%H:%M} · Dive 13.fit (30 min after this dive)"
    assert merged_name(Path("/x/Dive 12.fit")) == Path("/x/Dive 12 (merged).fit")


def test_viewer_merges_the_selected_dive_with_the_next(viewer, pair, tmp_path, monkeypatch):
    first, second = pair
    viewer.addFiles([str(first)])
    assert not viewer.canMerge
    assert viewer.mergeCandidates == []
    viewer.addFiles([str(second)])
    viewer.select(0)
    assert viewer.canMerge
    assert viewer.mergeCandidates == [candidate_label(_parse(first), _parse(second))]
    viewer.select(1)
    assert not viewer.canMerge  # nothing follows the second dive
    viewer.select(0)

    asked = []
    target = tmp_path / "out" / "joined"
    target.parent.mkdir()
    monkeypatch.setattr(viewer, "_dialog_save", lambda suggested, title="": asked.append(suggested) or str(target))
    assert viewer.mergeDives(0, False) == ""

    assert asked == [first.with_name("Dive 12 (merged).fit")]
    saved = target.with_name("joined.fit")
    assert saved.exists()
    assert viewer.diveCount == 3
    merged = _parse(saved)
    assert merged.start_time == _parse(first).start_time and merged.end_time == _parse(second).end_time
    assert viewer.selected["file"] == "Dive 12.fit"  # the selection stays


def test_viewer_merge_errors_and_cancel(viewer, pair, tmp_path, monkeypatch):
    first, second = pair
    viewer.addFiles([str(first), str(second)])
    viewer.select(0)
    assert "Pick the dive" in viewer.mergeDives(5, True)

    monkeypatch.setattr(viewer, "_dialog_save", lambda suggested, title="": "")
    assert viewer.mergeDives(0, True) == ""  # cancelled
    assert viewer.diveCount == 2

    monkeypatch.setattr(viewer, "_dialog_save", lambda suggested, title="": str(second))
    assert "new name" in viewer.mergeDives(0, True)
    assert _parse(second).start_time == _parse(second).start_time

    viewer.select(1)
    assert "within 2 hours" in viewer.mergeDives(0, True)

    uddf = tmp_path / "dive.uddf"
    write_synthetic_log(uddf, START + timedelta(days=1))
    viewer.addFiles([str(uddf)])
    viewer.select(viewer.diveCount - 1)
    assert not viewer.canMerge
