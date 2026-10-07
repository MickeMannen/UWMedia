"""GarminParser (parsers/garmin.py) beyond the writer round trip: the time
zone from the activity/session local timestamp, the session fallback, raw
FIT-epoch integer timestamps, GPS semicircles, tank updates merged onto
the records (names, gases, carried forward), dive-alert events, files with
no timing or no records, and the tank-serial scan on a synthetic FIT file.
The message dicts stand in for garmin_fit_sdk's decoder output; values and
serials are invented."""
from datetime import datetime, timedelta, timezone

import pytest

import parsers.garmin as garmin
from conftest import synthetic_plan
from parsers.garmin import GarminParser, is_offset_aware, remove_offset, timezone_from_pair

FIT_EPOCH = datetime(1989, 12, 31, tzinfo=timezone.utc)
START_UTC = datetime(2026, 5, 2, 3, 0, 0, tzinfo=timezone.utc)  # 10:00 at UTC+7


def _fit_int(dt):
    """A UTC datetime as raw FIT seconds, as the SDK leaves undecoded fields."""
    return int((dt - FIT_EPOCH).total_seconds())


def _local_int(dt, offset_hours):
    return _fit_int(dt) + offset_hours * 3600


def _decode_as(monkeypatch, messages, errors=()):
    class FakeStream:
        @staticmethod
        def from_file(_name):
            return None

    class FakeDecoder:
        def __init__(self, _stream):
            pass

        def read(self):
            return messages, list(errors)

    monkeypatch.setattr(garmin, "Stream", FakeStream)
    monkeypatch.setattr(garmin, "Decoder", FakeDecoder)


def _records(n=3, step=60, depth=10.0, as_int=False):
    out = []
    for i in range(n):
        ts = START_UTC + timedelta(seconds=i * step)
        out.append({"timestamp": _fit_int(ts) if as_int else ts, "depth": 0.0 if i in (0, n - 1) else depth,
                    "temperature": 27, "ndl_time": 1800, "time_to_surface": 60, "po2": 0.6})
    return out


def _activity(**extra):
    return [{"timestamp": START_UTC, "local_timestamp": _local_int(START_UTC, 7), "total_timer_time": 120.0, **extra}]


def _parse(monkeypatch, tmp_path, messages, errors=()):
    _decode_as(monkeypatch, messages, errors)
    return GarminParser().parse(tmp_path / "dive.fit")


def test_time_helpers():
    aware = datetime(2026, 1, 1, 12, 0, tzinfo=timezone(timedelta(hours=2)))
    assert is_offset_aware(aware)
    assert not is_offset_aware(remove_offset(aware))
    assert remove_offset(None) is None
    utc = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
    assert timezone_from_pair(aware, utc) == timezone(timedelta(hours=2))
    # Rounded to the minute.
    assert timezone_from_pair(datetime(2026, 1, 1, 15, 30, 20), datetime(2026, 1, 1, 10, 0)) == \
        timezone(timedelta(hours=5, minutes=30))


def test_activity_timing_device_and_records(monkeypatch, tmp_path):
    dive, = _parse(monkeypatch, tmp_path, {
        "file_id_mesgs": [{"garmin_product": "descent_mk3i", "manufacturer": "garmin"}],
        "activity_mesgs": _activity(),
        "record_mesgs": _records(),
    })
    assert dive.start_time == datetime(2026, 5, 2, 10, 0, 0)  # local wall clock
    assert dive.end_time == datetime(2026, 5, 2, 10, 2, 0)
    assert dive.timezone == "UTC+07:00"
    assert (dive.device, dive.manufactor) == ("descent_mk3i", "garmin")
    assert dive.start_latitude is None  # no session message
    wps = dive.waypoints
    assert [wp.timestamp for wp in wps] == [datetime(2026, 5, 2, 10, 0) + timedelta(minutes=m) for m in range(3)]
    assert [wp.time_since_start for wp in wps] == [0, 60, 120]
    assert [wp.max_depth for wp in wps] == [0.0, 10.0, 10.0]
    assert (wps[1].temp, wps[1].ndl, wps[1].tts, wps[1].po2) == (27.0, 1800, 60, 0.6)
    assert wps[1].ceiling is not None  # recomputed: FIT logs no ceiling


def test_record_defaults_for_missing_fields(monkeypatch, tmp_path):
    dive, = _parse(monkeypatch, tmp_path, {
        "activity_mesgs": _activity(),
        "record_mesgs": [{"timestamp": START_UTC}, {"no": "timestamp"}, {"timestamp": START_UTC + timedelta(seconds=10)}],
    })
    assert len(dive.waypoints) == 2
    wp = dive.waypoints[0]
    assert (wp.depth, wp.temp, wp.ndl, wp.tts, wp.cns, wp.heart_rate) == (0.0, 0.0, 0, 0, 0, 0)
    assert wp.po2 == 1.2
    assert wp.tanks == {} and wp.dive_alerts == []
    assert (dive.device, dive.manufactor) == (None, None)


def test_raw_integer_timestamps_are_fit_epoch_seconds(monkeypatch, tmp_path):
    activity = _activity()
    activity[0]["timestamp"] = _fit_int(START_UTC)
    dive, = _parse(monkeypatch, tmp_path, {
        "activity_mesgs": activity,
        "record_mesgs": _records(as_int=True),
        "tank_update_mesgs": [{"timestamp": _fit_int(START_UTC), "sensor": 111, "pressure": 200.0}],
        "event_mesgs": [{"event": "dive_alert", "dive_alert": "ndl_reached", "timestamp": _fit_int(START_UTC + timedelta(seconds=60))}],
    })
    assert dive.start_time == datetime(2026, 5, 2, 10, 0, 0)
    assert dive.waypoints[1].timestamp == datetime(2026, 5, 2, 10, 1, 0)
    assert dive.waypoints[0].tanks["111"].pressure_bar == 200.0
    assert dive.waypoints[1].dive_alerts == ["ndl_reached"]


def test_activity_without_local_time_is_utc(monkeypatch, tmp_path):
    dive, = _parse(monkeypatch, tmp_path, {
        "activity_mesgs": [{"timestamp": START_UTC, "total_timer_time": 60.0}],
        "record_mesgs": _records(2),
    })
    assert dive.start_time == datetime(2026, 5, 2, 3, 0, 0)
    assert dive.timezone == "UTC"


@pytest.mark.parametrize("as_int", [False, True])
def test_session_is_the_fallback_without_an_activity(monkeypatch, tmp_path, as_int):
    start = _fit_int(START_UTC) if as_int else START_UTC
    dive, = _parse(monkeypatch, tmp_path, {
        "session_mesgs": [{"start_time": start, "local_timestamp": _local_int(START_UTC, -5), "total_elapsed_time": 300.0,
                           "start_position_lat": 2 ** 30, "start_position_long": -(2 ** 29),
                           "end_position_lat": 0, "end_position_long": None}],
        "record_mesgs": _records(),
    })
    assert dive.start_time == datetime(2026, 5, 1, 22, 0, 0)
    assert dive.end_time == datetime(2026, 5, 1, 22, 5, 0)
    assert dive.timezone == "UTC-05:00"
    assert (dive.start_latitude, dive.start_longitude) == (90.0, -45.0)
    assert (dive.end_latitude, dive.end_longitude) == (0.0, None)


def test_session_without_local_time_is_utc(monkeypatch, tmp_path):
    dive, = _parse(monkeypatch, tmp_path, {
        "session_mesgs": [{"start_time": START_UTC}],
        "record_mesgs": _records(2),
    })
    assert dive.timezone == "UTC"
    assert dive.end_time == dive.start_time == datetime(2026, 5, 2, 3, 0, 0)


def test_no_timing_messages_gives_no_dive(monkeypatch, tmp_path, capsys):
    assert _parse(monkeypatch, tmp_path, {"record_mesgs": _records()}, errors=["bad crc"]) == []
    out = capsys.readouterr().out
    assert "bad crc" in out and "timing data" in out


def test_no_records_gives_no_dive(monkeypatch, tmp_path):
    assert _parse(monkeypatch, tmp_path, {"activity_mesgs": _activity()}) == []


def test_tank_updates_merge_onto_records(monkeypatch, tmp_path):
    t = lambda s: START_UTC + timedelta(seconds=s)  # noqa: E731
    dive, = _parse(monkeypatch, tmp_path, {
        "activity_mesgs": _activity(),
        "record_mesgs": _records(4),
        "device_info_mesgs": [{"serial_number": 111, "descriptor": "Left"},
                              {"serial_number": 222, "product_name": "Tank Pod"},
                              {"serial_number": None, "descriptor": "watch"}],
        "dive_gas_mesgs": [{"message_index": 0, "oxygen_content": 32, "helium_content": 0, "status": "enabled"},
                           {"message_index": 1, "oxygen_content": 18, "helium_content": 45, "status": "disabled",
                            "mode": "closed_circuit_diluent"},
                           {"oxygen_content": 50}],  # no index: ignored
        "tank_update_mesgs": [
            # Tank 222 is first heard from at 60 s - before that it shows its first reading.
            {"timestamp": t(0), "sensor": 111, "pressure": 210.0, "gas_type_index": 0},
            {"timestamp": t(60), "sensor": 111, "pressure": 200.0, "gas_type_index": 0},
            {"timestamp": t(60), "sensor": 222, "pressure": 190.0, "gas_type_index": 1},
            {"timestamp": t(120), "gas_type_index": 7, "pressure": 180.0},  # no sensor: keyed by gas index
        ],
    })
    w0, w1, w2, w3 = dive.waypoints
    assert set(w0.tanks) == {"111", "222", "7"}
    assert (w0.tanks["111"].pressure_bar, w0.tanks["222"].pressure_bar, w0.tanks["7"].pressure_bar) == (210.0, 190.0, 180.0)
    assert (w1.tanks["111"].pressure_bar, w1.tanks["222"].pressure_bar) == (200.0, 190.0)
    assert w3.tanks["111"].pressure_bar == 200.0  # carried forward

    left = w1.tanks["111"]
    assert (left.name, left.o2_percent, left.he_percent, left.mode, left.enabled) == ("Left", 32.0, 0.0, "open_circuit", True)
    pod = w1.tanks["222"]
    assert (pod.name, pod.o2_percent, pod.he_percent, pod.mode, pod.enabled) == ("Tank Pod", 18.0, 45.0, "closed_circuit_diluent", False)
    unknown = w2.tanks["7"]
    assert (unknown.name, unknown.o2_percent, unknown.enabled) == (None, 21.0, True)


def test_dive_alerts_land_on_the_next_record(monkeypatch, tmp_path):
    t = lambda s: START_UTC + timedelta(seconds=s)  # noqa: E731
    dive, = _parse(monkeypatch, tmp_path, {
        "activity_mesgs": _activity(),
        "record_mesgs": _records(3),
        "event_mesgs": [
            {"event": "dive_alert", "dive_alert": "safety_stop_started", "timestamp": t(90)},
            {"event": "dive_alert", "dive_alert": 59, "timestamp": t(30)},  # undecoded enum
            {"event": "dive_alert", "dive_alert": "ndl_reached", "timestamp": t(60)},
            {"event": "timer", "timestamp": t(60)},
            {"event": "dive_alert", "dive_alert": None, "timestamp": t(60)},
            {"event": "dive_alert", "dive_alert": "deco_ceiling_broken"},
        ],
    })
    assert [wp.dive_alerts for wp in dive.waypoints] == [[], ["59", "ndl_reached"], ["safety_stop_started"]]


def test_unmapped_product_id_is_named(monkeypatch, tmp_path):
    dive, = _parse(monkeypatch, tmp_path, {
        "file_id_mesgs": [{"garmin_product": 4518, "manufacturer": "garmin"}],
        "activity_mesgs": _activity(),
        "record_mesgs": _records(2),
    })
    assert dive.device == "descent_x50i"


def test_a_failed_ceiling_recompute_keeps_the_dive(monkeypatch, tmp_path, capsys):
    class Broken:
        def __init__(self, *args, **kwargs):
            pass

        def process_waypoints(self, *args):
            raise RuntimeError("engine down")

    monkeypatch.setattr(garmin, "DiveDecompressor", Broken)
    dive, = _parse(monkeypatch, tmp_path, {"activity_mesgs": _activity(), "record_mesgs": _records()})
    assert dive.max_depth == 10.0
    assert all(wp.ceiling is None for wp in dive.waypoints)
    assert "engine down" in capsys.readouterr().out


def test_unique_tank_serials_of_a_synthetic_fit(tmp_path):
    from parsers.fit_writer import TANK_SENSOR_BASE, write_fit
    from utils.dive_plan_engine import simulate

    plan = synthetic_plan(datetime(2026, 5, 2, 10, 0), computer="Garmin Descent Mk3i", bottom_min=5, depth_m=10.0)
    samples, _ = simulate(plan, resolution_sec=10)
    path = tmp_path / "dive.fit"
    write_fit(plan, samples, path)
    assert GarminParser().get_unique_tank_serials(path) == [str(TANK_SENSOR_BASE)]
    dive, = GarminParser().parse(path)
    assert set(dive.waypoints[0].tanks) == {str(TANK_SENSOR_BASE)}
