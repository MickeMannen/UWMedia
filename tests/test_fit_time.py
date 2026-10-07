"""parsers/fit_time.py: correcting a Garmin FIT log's clock - every timestamp
shifted by one amount, the time zone set, everything else kept - and the Log
Viewer's "Adjust time" around it. Logs are written at run time (the app's
FIT writer, or a few hand-built records); no real log is used."""
import struct
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from garmin_fit_sdk import Decoder, Stream

from conftest import write_synthetic_log
import uwmedia.backends.log_viewer_backend as lvb
from parsers.fit_time import FIT_EPOCH, adjust_fit_time, fit_activity_time, fit_crc
from parsers.garmin import GarminParser
from uwmedia.backends.log_viewer_backend import (
    LogViewerBackend, adjusted_name, format_utc_offset, parse_local_start, parse_utc_offset,
)


@pytest.fixture
def fit_log(tmp_path):
    path = tmp_path / "Dive 12.fit"
    write_synthetic_log(path, datetime(2026, 1, 1, 10, 0), computer="Garmin Descent Mk3i")
    return path


def _decode(path):
    decoder = Decoder(Stream.from_file(str(path)))
    assert decoder.check_integrity()  # header and file CRC
    messages, errors = Decoder(Stream.from_file(str(path))).read()
    assert errors == []
    return messages


def test_shift_moves_every_sample_and_sets_the_time_zone(fit_log, tmp_path):
    before = GarminParser().parse(fit_log)[0]
    old_utc, _ = fit_activity_time(fit_log)  # the writer used this machine's time zone
    out = tmp_path / "fixed.fit"

    delta = adjust_fit_time(fit_log, out, datetime(2026, 3, 5, 14, 23, 7), 7 * 60)

    after = GarminParser().parse(out)[0]
    assert after.start_time == datetime(2026, 3, 5, 14, 23, 7)
    assert after.timezone == "UTC+07:00"
    assert fit_activity_time(out) == (datetime(2026, 3, 5, 7, 23, 7, tzinfo=timezone.utc), 420)
    assert len(after.waypoints) == len(before.waypoints)
    # Local sample times move by the local difference; the data stays.
    local_shift = datetime(2026, 3, 5, 14, 23, 7) - before.start_time
    assert {b.timestamp - a.timestamp for a, b in zip(before.waypoints, after.waypoints)} == {local_shift}
    assert [w.depth for w in after.waypoints] == [w.depth for w in before.waypoints]
    assert after.waypoints[10].tanks == before.waypoints[10].tanks
    assert delta == (datetime(2026, 3, 5, 7, 23, 7, tzinfo=timezone.utc) - old_utc).total_seconds()

    messages = _decode(out)
    for key in ("record_mesgs", "tank_update_mesgs", "session_mesgs"):
        assert messages[key], key
    # Nothing but times changed: same size, original untouched.
    assert out.stat().st_size == fit_log.stat().st_size
    assert GarminParser().parse(fit_log)[0].start_time == before.start_time


def test_only_the_time_zone_changes_when_the_start_is_kept(fit_log, tmp_path):
    out = tmp_path / "tz.fit"
    adjust_fit_time(fit_log, out, datetime(2026, 1, 1, 10, 0), -5 * 60 - 30)
    dive = GarminParser().parse(out)[0]
    assert (dive.start_time, dive.timezone) == (datetime(2026, 1, 1, 10, 0), "UTC-05:30")


def test_not_a_fit_file(tmp_path):
    bad = tmp_path / "bad.fit"
    bad.write_bytes(b"not a fit file at all")
    with pytest.raises(ValueError):
        adjust_fit_time(bad, tmp_path / "out.fit", datetime(2026, 1, 1), 0)


# --- a hand-built file: compressed timestamps and big-endian records --------

def _definition(local, mesg_num, fields, big_endian=False):
    endian = ">" if big_endian else "<"
    out = bytes([0x40 | local, 0, 1 if big_endian else 0]) + struct.pack(endian + "H", mesg_num)
    out += bytes([len(fields)])
    for num, size, base in fields:
        out += bytes([num, size, base])
    return out


def _fit(records: bytes) -> bytes:
    header = struct.pack("<BBHI4s", 12, 0x20, 2100, len(records), b".FIT")
    body = header + records
    return body + struct.pack("<H", fit_crc(body))


def test_compressed_timestamps_and_big_endian_messages(tmp_path):
    t0 = 1_100_000_000  # seconds since the FIT epoch
    records = (
        _definition(0, 20, [(253, 4, 0x86), (3, 1, 0x02)])  # record: timestamp, heart rate
        + _definition(1, 20, [(3, 1, 0x02)])  # record without a timestamp (compressed)
        + _definition(2, 34, [(253, 4, 0x86), (5, 4, 0x86)], big_endian=True)  # activity
        + bytes([0x00]) + struct.pack("<IB", t0, 60)
        + bytes([0x80 | (1 << 5) | ((t0 + 5) & 0x1F)]) + bytes([61])
        + bytes([0x80 | (1 << 5) | ((t0 + 9) & 0x1F)]) + bytes([62])
        + bytes([0x02]) + struct.pack(">II", t0, t0 + 3600)
    )
    src = tmp_path / "hand.fit"
    src.write_bytes(_fit(records))
    out = tmp_path / "hand_fixed.fit"

    start = (FIT_EPOCH + timedelta(seconds=t0 + 1234)).replace(tzinfo=None)
    adjust_fit_time(src, out, start + timedelta(hours=2), 120)

    # garmin_fit_sdk can't read compressed timestamps, so decode the three
    # records here: data starts after the 12-byte header and 33 bytes of
    # definitions; a compressed time is last + ((offset - last) & 0x1F).
    data = out.read_bytes()
    assert Decoder(Stream.from_file(str(out))).check_integrity()
    first = struct.unpack_from("<I", data, 46)[0]
    second = first + (((data[51] & 0x1F) - first) & 0x1F)
    third = second + (((data[53] & 0x1F) - second) & 0x1F)
    new_t0 = FIT_EPOCH + timedelta(seconds=t0 + 1234)
    assert [FIT_EPOCH + timedelta(seconds=v) for v in (first, second, third)] == [
        new_t0, new_t0 + timedelta(seconds=5), new_t0 + timedelta(seconds=9)]
    assert fit_activity_time(out) == (new_t0, 120)


# --- the Log Viewer's dialog -------------------------------------------------

@pytest.mark.parametrize("text, minutes", [
    ("+07:00", 420), ("-5:30", -330), ("+7", 420), ("UTC+08:00", 480), ("gmt-3", -180), ("0", 0), ("+0545", 345),
])
def test_parse_utc_offset(text, minutes):
    assert parse_utc_offset(text) == minutes


@pytest.mark.parametrize("text", ["", "seven", "+15:00", "-13", "+07:75", "+1:2:3"])
def test_parse_utc_offset_rejects(text):
    with pytest.raises(ValueError):
        parse_utc_offset(text)


def test_start_and_offset_text():
    assert parse_local_start("2026-03-05  14:23") == datetime(2026, 3, 5, 14, 23)
    assert parse_local_start("2026-03-05 14:23:07") == datetime(2026, 3, 5, 14, 23, 7)
    with pytest.raises(ValueError):
        parse_local_start("5 March")
    assert format_utc_offset(-330) == "-05:30" and format_utc_offset(0) == "+00:00"
    assert adjusted_name(Path("logs") / "Dive 12.fit") == Path("logs") / "Dive 12 (adjusted).fit"


class _Config:
    def get_tank_mapping(self):
        return {}


@pytest.fixture
def viewer(settings_file, monkeypatch):
    monkeypatch.setattr(lvb, "get_config", lambda: _Config())
    return LogViewerBackend(background=False)


def test_viewer_adjusts_a_fit_dive_into_a_new_file(viewer, fit_log, tmp_path, monkeypatch):
    viewer.addFiles([str(fit_log)])
    assert viewer.canAdjustTime
    offset = fit_activity_time(fit_log)[1]
    assert (viewer.adjustStartText, viewer.adjustOffsetText) == ("2026-01-01 10:00:00", format_utc_offset(offset))

    asked = []
    target = tmp_path / "out" / "corrected"
    target.parent.mkdir()
    monkeypatch.setattr(viewer, "_dialog_save", lambda suggested: asked.append(suggested) or str(target))
    assert viewer.adjustTime("2026-03-05 14:23:07", "+07:00") == ""

    assert asked == [fit_log.with_name("Dive 12 (adjusted).fit")]
    saved = target.with_name("corrected.fit")  # .fit added
    assert saved.exists()
    assert viewer.diveCount == 2
    assert sorted((row["date"], row["time"]) for row in viewer.dives) == [
        ("2026-01-01", "10:00"), ("2026-03-05", "14:23")]


def test_viewer_adjust_errors_and_cancel(viewer, fit_log, tmp_path, monkeypatch):
    viewer.addFiles([str(fit_log)])
    assert "YYYY-MM-DD" in viewer.adjustTime("tomorrow", "+07:00")
    assert "UTC offset" in viewer.adjustTime("2026-03-05 14:23", "Bangkok")

    monkeypatch.setattr(viewer, "_dialog_save", lambda suggested: "")
    assert viewer.adjustTime("2026-03-05 14:23", "+07:00") == ""  # cancelled
    assert viewer.diveCount == 1

    monkeypatch.setattr(viewer, "_dialog_save", lambda suggested: str(fit_log))
    assert "new name" in viewer.adjustTime("2026-03-05 14:23", "+07:00")
    assert GarminParser().parse(fit_log)[0].start_time == datetime(2026, 1, 1, 10, 0)


def test_viewer_only_adjusts_fit_logs(viewer, tmp_path):
    uddf = tmp_path / "dive.uddf"
    write_synthetic_log(uddf, datetime(2026, 1, 1, 10, 0))
    viewer.addFiles([str(uddf)])
    assert not viewer.canAdjustTime
    assert viewer.adjustOffsetText == ""
    assert "Garmin FIT" in viewer.adjustTime("2026-03-05 14:23", "+07:00")
