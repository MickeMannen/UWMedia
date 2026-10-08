"""Join two Garmin FIT dive logs into one (Log Viewer's "Merge dives", for a
dive the computer split in two: a short surface stop ended the first log
and started a second one).

The merged file is the first log with the second one's samples appended,
written at the record level like parsers/fit_time.py: every message of the
first file is copied byte for byte (GPS, heart rate, Garmin's own
undocumented messages included), so the result stays as close to a native
Descent file as it can be, for Garmin Connect as much as for UWMedia.

Two ways to deal with the surface interval between the logs:

- keep the clock (close_gap=False): the second dive's samples keep their
  real timestamps and the gap is filled with copies of the first dive's last
  sample, one per logging interval. Photos and videos from both dives still
  line up with the log.
- close the gap (close_gap=True): every timestamp of the second log moves
  back so its first sample follows the first dive's last one. The result is
  one continuous dive; media from the second dive no longer matches it.

Either way the merged dive starts when the first did and ends when the
second did. What is taken from the second file: its records, tank updates,
events, GPS and the other messages logged between its first and last
sample; its gases (added to the first file's list when they are new, with
the gas-switch events pointing at the merged list); tank pods and tank
summaries for sensors the first file doesn't have. Its file_id, settings
and summary messages are dropped and the first file's summaries are
patched instead: session/lap/activity timer times, dive_summary depths,
bottom time and end tissue values, tank_summary end pressures. The timer
stop at the end of the first log and the timer start of the second are
dropped so the join doesn't read as a pause.

Garmin Connect sees a file with the first dive's start and the device's
serial as that dive, so the two original activities have to be deleted
there before the merged one is uploaded.
"""
import struct
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from garmin_fit_sdk import Profile

from parsers.fit_time import INVALID_UINT32, MIN_DATE_TIME, TIMESTAMP_FIELD, _Definition, _walk, fit_crc

# Dives further apart than this are two dives, not one that was split.
MAX_GAP_SECONDS = 2 * 3600

_MESG_NUM = {m["name"]: int(num) for num, m in Profile["messages"].items()}


def _mesg(name: str) -> int:
    return _MESG_NUM[name]


def _field(mesg: str, name: str) -> int:
    fields = Profile["messages"][_mesg(mesg)]["fields"]
    return next(int(num) for num, f in fields.items() if f["name"] == name)


FILE_ID, FILE_CREATOR, ACTIVITY, SESSION, LAP = (_mesg(n) for n in ("file_id", "file_creator", "activity", "session", "lap"))
RECORD, EVENT, DEVICE_INFO, TANK_UPDATE, TANK_SUMMARY = (
    _mesg(n) for n in ("record", "event", "device_info", "tank_update", "tank_summary"))
DIVE_GAS, DIVE_SUMMARY, GPS_METADATA = (_mesg(n) for n in ("dive_gas", "dive_summary", "gps_metadata"))
DEVELOPER_DATA_ID, FIELD_DESCRIPTION = _mesg("developer_data_id"), _mesg("field_description")

# Second-file messages that describe the file or the dive as a whole: the
# first file's are kept instead.
SKIPPED_FROM_SECOND = {
    FILE_ID, FILE_CREATOR, ACTIVITY, SESSION, LAP, DIVE_SUMMARY,
    *(_mesg(n) for n in ("time_in_zone", "timestamp_correlation", "device_settings", "user_profile", "sport",
                         "training_settings", "zones_target", "dive_settings", "dive_alarm")),
}
# Second-file messages that are samples, wherever they sit in the file.
# Anything else unknown is kept only when logged between its first and last
# record, so Garmin's undocumented per-sample messages come along while its
# settings-like ones stay behind.
STREAM_FROM_SECOND = {RECORD, EVENT, TANK_UPDATE, GPS_METADATA, _mesg("hr"), _mesg("hrv")}

MESSAGE_INDEX = 254
F_EVENT, F_EVENT_TYPE, F_EVENT_DATA = _field("event", "event"), _field("event", "event_type"), _field("event", "data")
EVENT_TIMER = int(next(k for k, v in Profile["types"]["event"].items() if v == "timer"))
EVENT_GAS_SWITCHED = int(next(k for k, v in Profile["types"]["event"].items() if v == "dive_gas_switched"))
EVENT_TYPE_START = int(next(k for k, v in Profile["types"]["event_type"].items() if v == "start"))
EVENT_TYPE_MARKER = int(next(k for k, v in Profile["types"]["event_type"].items() if v == "marker"))
EVENT_TYPE_STOPS = {int(k) for k, v in Profile["types"]["event_type"].items() if v in ("stop", "stop_all")}
F_GAS_HE, F_GAS_O2, F_GAS_MODE = _field("dive_gas", "helium_content"), _field("dive_gas", "oxygen_content"), _field("dive_gas", "mode")
F_SERIAL = _field("device_info", "serial_number")
F_SENSOR, F_END_PRESSURE, F_VOLUME_USED = (_field("tank_summary", n) for n in ("sensor", "end_pressure", "volume_used"))
F_DEPTH = _field("record", "depth")
F_START_TIME, F_ELAPSED, F_TIMER = (_field("session", n) for n in ("start_time", "total_elapsed_time", "total_timer_time"))
F_END_LAT, F_END_LONG = _field("session", "end_position_lat"), _field("session", "end_position_long")
F_ACTIVITY_TIMER = _field("activity", "total_timer_time")
F_AVG_DEPTH, F_MAX_DEPTH, F_BOTTOM_TIME = (_field("dive_summary", n) for n in ("avg_depth", "max_depth", "bottom_time"))
F_END_CNS, F_END_N2, F_O2_TOX = (_field("dive_summary", n) for n in ("end_cns", "end_n2", "o2_toxicity"))
F_GPS_UTC = _field("gps_metadata", "utc_timestamp")
# Other date_time fields of the second file that move with its timestamps.
DATE_TIME_FIELDS = {(GPS_METADATA, F_GPS_UTC)}

# FIT base type (low 5 bits) -> struct format, and the value that means "not set".
_INT_FORMATS = {0: "B", 1: "b", 2: "B", 3: "h", 4: "H", 5: "i", 6: "I", 10: "B", 11: "H", 12: "I", 14: "q", 15: "Q", 16: "Q"}
_INVALID = {0: 0xFF, 1: 0x7F, 2: 0xFF, 3: 0x7FFF, 4: 0xFFFF, 5: 0x7FFFFFFF, 6: 0xFFFFFFFF, 10: 0, 11: 0, 12: 0,
            14: 0x7FFFFFFFFFFFFFFF, 15: 0xFFFFFFFFFFFFFFFF, 16: 0}


def _definition(mesg_num: int, fields: List[Tuple[int, int, int]]) -> _Definition:
    """A little-endian definition message for `fields` ((number, size, base type))."""
    raw = bytes([0x40, 0, 0]) + struct.pack("<H", mesg_num) + bytes([len(fields)])
    for num, size, base in fields:
        raw += bytes([num, size, base])
    return _Definition(mesg_num, "<", list(fields), 0, raw)


# An event message of the merge's own: timestamp, event, event_type, data.
_EVENT_DEFINITION = _definition(EVENT, [(TIMESTAMP_FIELD, 4, 0x86), (F_EVENT, 1, 0x00), (F_EVENT_TYPE, 1, 0x00),
                                        (F_EVENT_DATA, 4, 0x86)])


@dataclass
class MergeResult:
    gap_seconds: int  # between the first dive's last sample and the second's first, as logged
    shift_seconds: int  # applied to the second log's timestamps (0 when the clock is kept)
    filled_samples: int  # samples added to bridge the gap (0 when it was closed)
    gases_added: int  # gases the second log had that the first didn't


class _Msg:
    __slots__ = ("definition", "body", "compressed", "header", "timestamp")

    def __init__(self, definition: _Definition, body: bytearray, compressed: bool, header: int, timestamp: Optional[int]):
        self.definition = definition
        self.body = body  # the fields, without the header byte
        self.compressed = compressed
        self.header = header
        self.timestamp = timestamp  # FIT date_time (seconds since the FIT epoch), None when it has none

    @property
    def mesg_num(self) -> int:
        return self.definition.mesg_num

    def _locate(self, num: int) -> Optional[Tuple[int, int, int]]:
        offset = 0
        for field_num, size, base in self.definition.fields:
            if field_num == num:
                return offset, size, base
            offset += size
        return None

    def get(self, num: int) -> Optional[int]:
        """An integer field's value; None when the message lacks it or it is unset."""
        found = self._locate(num)
        if found is None:
            return None
        offset, size, base = found
        fmt = _INT_FORMATS.get(base & 0x1F)
        if fmt is None or struct.calcsize(fmt) != size:
            return None
        value = struct.unpack_from(self.definition.endian + fmt, self.body, offset)[0]
        return None if value == _INVALID[base & 0x1F] else value

    def set(self, num: int, value: int) -> bool:
        """Sets an integer field, clamped to the type's range; False when the
        message lacks the field."""
        found = self._locate(num)
        if found is None:
            return False
        offset, size, base = found
        fmt = _INT_FORMATS.get(base & 0x1F)
        if fmt is None or struct.calcsize(fmt) != size:
            return False
        invalid = _INVALID[base & 0x1F]
        low = -(1 << (8 * size - 1)) if fmt.islower() else 0
        high = (1 << (8 * size - 1)) - 1 if fmt.islower() else (1 << (8 * size)) - 1
        value = max(low, min(high, int(round(value))))
        if value == invalid and invalid != 0:
            value -= 1  # the type's top value means "not set"
        struct.pack_into(self.definition.endian + fmt, self.body, offset, value)
        return True

    def copy(self) -> "_Msg":
        return _Msg(self.definition, bytearray(self.body), self.compressed, self.header, self.timestamp)


def _read_messages(path: Path) -> List[_Msg]:
    data = bytearray(Path(path).read_bytes())
    messages: List[_Msg] = []
    last: List[Optional[int]] = [None]

    def on_message(definition, start, header, compressed):
        body = bytearray(data[start:start + definition.size])
        msg = _Msg(definition, body, compressed, data[header], None)
        if compressed:
            if last[0] is not None:
                ts = (last[0] & ~0x1F) | (data[header] & 0x1F)
                msg.timestamp = ts + 0x20 if ts < last[0] else ts
        else:
            ts = msg.get(TIMESTAMP_FIELD)
            if ts is not None and ts >= MIN_DATE_TIME:
                msg.timestamp = ts
        if msg.timestamp is not None:
            last[0] = msg.timestamp
        messages.append(msg)

    _walk(data, on_message)
    return messages


def _header_of(path: Path) -> bytearray:
    data = Path(path).read_bytes()
    return bytearray(data[:data[0]])


class _Writer:
    """Writes data messages, emitting a definition whenever a message's
    definition isn't in one of the 16 local message slots (0-3 for
    compressed-timestamp messages, which can only address those)."""

    def __init__(self):
        self.out = bytearray()
        self._slots: List[Optional[bytes]] = [None] * 16
        self._used = [0] * 16
        self._tick = 0
        self.developer_fields = False

    def _slot(self, definition: _Definition, compressed: bool) -> int:
        content = definition.raw[1:]
        limit = 4 if compressed else 16
        for i in range(limit):
            if self._slots[i] == content:
                break
        else:
            i = min(range(limit), key=lambda k: self._used[k])
            dev_flag = definition.raw[0] & 0x20
            self.developer_fields = self.developer_fields or bool(dev_flag)
            self.out.append(0x40 | dev_flag | i)
            self.out += content
            self._slots[i] = content
        self._tick += 1
        self._used[i] = self._tick
        return i

    def write(self, msg: _Msg) -> None:
        slot = self._slot(msg.definition, msg.compressed)
        if msg.compressed:
            self.out.append(0x80 | (slot << 5) | (msg.header & 0x1F))
        else:
            self.out.append(slot)
        self.out += msg.body


def _records(messages: Iterable[_Msg]) -> List[_Msg]:
    return [m for m in messages if m.mesg_num == RECORD and m.timestamp is not None]


def _interval(records: List[_Msg]) -> int:
    diffs = Counter(b.timestamp - a.timestamp for a, b in zip(records, records[1:]) if b.timestamp > a.timestamp)
    return diffs.most_common(1)[0][0] if diffs else 1


def _gas_key(msg: _Msg):
    return msg.get(F_GAS_O2), msg.get(F_GAS_HE), msg.get(F_GAS_MODE)


def _first(messages: List[_Msg], mesg_num: int) -> Optional[_Msg]:
    return next((m for m in messages if m.mesg_num == mesg_num), None)


def _shift(msg: _Msg, delta: int) -> None:
    """Moves the message's timestamp fields by `delta` seconds (in place)."""
    if delta == 0:
        return
    if msg.compressed:
        if msg.timestamp is not None:
            msg.header = (msg.header & 0xE0) | ((msg.timestamp + delta) & 0x1F)
    else:
        ts = msg.get(TIMESTAMP_FIELD)
        if ts is not None and ts >= MIN_DATE_TIME:
            msg.set(TIMESTAMP_FIELD, ts + delta)
    for mesg_num, num in DATE_TIME_FIELDS:
        if msg.mesg_num == mesg_num:
            value = msg.get(num)
            if value is not None and value >= MIN_DATE_TIME:
                msg.set(num, value + delta)
    if msg.timestamp is not None:
        msg.timestamp += delta


def _is_timer(msg: _Msg, event_types) -> bool:
    return msg.mesg_num == EVENT and msg.get(F_EVENT) == EVENT_TIMER and msg.get(F_EVENT_TYPE) in event_types


def merge_fit_dives(first: Path, second: Path, dest: Path, close_gap: bool) -> MergeResult:
    """Writes `first` and `second` (Garmin FIT dive logs, `second` logged
    after `first`, within MAX_GAP_SECONDS) as one dive to `dest`. See the
    module docstring for what the two modes do. Raises ValueError when the
    files aren't FIT dive logs or aren't close enough."""
    first, second, dest = Path(first), Path(second), Path(dest)
    msgs1, msgs2 = _read_messages(first), _read_messages(second)
    records1, records2 = _records(msgs1), _records(msgs2)
    if not records1:
        raise ValueError(f"{first.name} has no samples")
    if not records2:
        raise ValueError(f"{second.name} has no samples")
    last1, first2 = records1[-1].timestamp, records2[0].timestamp
    gap = first2 - last1
    if gap <= 0:
        raise ValueError("The second dive starts before the first one ends; merge them the other way round")
    if gap > MAX_GAP_SECONDS:
        raise ValueError(f"The dives are {gap / 3600:.1f} hours apart; only dives within "
                         f"{MAX_GAP_SECONDS // 3600} hours of each other can be merged")

    interval = _interval(records1)
    delta = (last1 + interval) - first2 if close_gap else 0

    # Gases: the first file's list, plus the second's new ones.
    gases1 = [m for m in msgs1 if m.mesg_num == DIVE_GAS]
    gas_index = {_gas_key(m): m.get(MESSAGE_INDEX) for m in reversed(gases1)}
    next_index = max([m.get(MESSAGE_INDEX) or 0 for m in gases1], default=-1) + 1
    gas_map: Dict[int, int] = {}
    new_gases: List[_Msg] = []
    for gas in (m for m in msgs2 if m.mesg_num == DIVE_GAS):
        old = gas.get(MESSAGE_INDEX)
        if old is None:
            continue
        key = _gas_key(gas)
        if key not in gas_index:
            added = gas.copy()
            added.set(MESSAGE_INDEX, next_index)
            gas_index[key] = next_index
            new_gases.append(added)
            next_index += 1
        gas_map[old] = gas_index[key]

    # Tank pods and tank summaries the first file doesn't have.
    serials1 = {m.get(F_SERIAL) for m in msgs1 if m.mesg_num == DEVICE_INFO} - {None}
    new_pods = [m for m in msgs2 if m.mesg_num == DEVICE_INFO and m.get(F_SERIAL) not in serials1 | {None}]
    sensors1 = {m.get(F_SENSOR) for m in msgs1 if m.mesg_num == TANK_SUMMARY}
    summaries2 = {m.get(F_SENSOR): m for m in msgs2 if m.mesg_num == TANK_SUMMARY}

    # The second file's samples, in its order.
    rec_positions = [i for i, m in enumerate(msgs2) if m.mesg_num == RECORD]
    span = range(rec_positions[0], rec_positions[-1] + 1)
    stream2: List[_Msg] = []
    for i, msg in enumerate(msgs2):
        num = msg.mesg_num
        if num in SKIPPED_FROM_SECOND or num in (DIVE_GAS, DEVICE_INFO):
            continue
        if num == TANK_SUMMARY and msg.get(F_SENSOR) in sensors1:
            continue
        if num not in STREAM_FROM_SECOND and num not in (TANK_SUMMARY, DEVELOPER_DATA_ID, FIELD_DESCRIPTION) and i not in span:
            continue
        if _is_timer(msg, {EVENT_TYPE_START}) and (msg.timestamp is None or msg.timestamp <= first2):
            continue  # the second log's timer start: the merged dive's timer is already running
        msg = msg.copy()
        if num == EVENT and msg.get(F_EVENT) == EVENT_GAS_SWITCHED:
            data = msg.get(F_EVENT_DATA)
            if data in gas_map:
                msg.set(F_EVENT_DATA, gas_map[data])
        _shift(msg, delta)
        stream2.append(msg)
    # A dive that starts on another gas than the first one ended on, without
    # a switch event of its own to say so (Garmin logs one at the start of
    # every dive; other writers may not): record the switch at the join.
    switches1 = [m.get(F_EVENT_DATA) for m in msgs1 if m.mesg_num == EVENT and m.get(F_EVENT) == EVENT_GAS_SWITCHED]
    gas_before = switches1[-1] if switches1 else 0
    switched_at_start = any(m.mesg_num == EVENT and m.get(F_EVENT) == EVENT_GAS_SWITCHED
                            and m.timestamp is not None and m.timestamp <= first2 for m in msgs2)
    gas_after = gas_map.get(0, gas_before)
    if not switched_at_start and gas_after != gas_before:
        switch = _Msg(_EVENT_DEFINITION, bytearray(_EVENT_DEFINITION.size), False, 0, first2 + delta)
        switch.set(TIMESTAMP_FIELD, first2 + delta)
        switch.set(F_EVENT, EVENT_GAS_SWITCHED)
        switch.set(F_EVENT_TYPE, EVENT_TYPE_MARKER)
        switch.set(F_EVENT_DATA, gas_after)
        stream2.insert(0, switch)

    additions = list(new_gases)  # the second file's new gases and tank pods, in the first file's preamble
    for pod in new_pods:
        pod = pod.copy()
        _shift(pod, delta)
        additions.append(pod)

    # Bridge the gap with the first dive's last sample.
    filler: List[_Msg] = []
    if not close_gap:
        template = next((m for m in reversed(records1) if not m.compressed), None)
        if template is None:
            raise ValueError(f"{first.name} logs its samples without full timestamps; the gap can't be filled")
        ts = last1 + interval
        while ts < first2:
            sample = template.copy()
            sample.set(TIMESTAMP_FIELD, ts)
            sample.timestamp = ts
            filler.append(sample)
            ts += interval

    # The first file's summaries now describe the merged dive.
    session1, session2 = _first(msgs1, SESSION), _first(msgs2, SESSION)
    start1 = (session1.get(F_START_TIME) if session1 else None) or records1[0].timestamp
    start2 = (session2.get(F_START_TIME) if session2 else None) or first2
    timer2 = (session2.get(F_TIMER) if session2 else None)
    end2 = start2 + delta + (timer2 / 1000 if timer2 is not None else records2[-1].timestamp - start2)
    total_ms = int(round((end2 - start1) * 1000))
    depths = [m.get(F_DEPTH) for m in records1 + filler + records2]
    depths = [d for d in depths if d is not None]
    summary2 = _first(msgs2, DIVE_SUMMARY)
    for msg in msgs1:
        if msg.mesg_num in (SESSION, LAP):
            msg.set(F_ELAPSED, total_ms)
            msg.set(F_TIMER, total_ms)
            if msg.mesg_num == SESSION and session2 is not None:
                for num in (F_END_LAT, F_END_LONG):
                    value = session2.get(num)
                    if value is not None:
                        msg.set(num, value)
        elif msg.mesg_num == ACTIVITY:
            msg.set(F_ACTIVITY_TIMER, total_ms)
        elif msg.mesg_num == DIVE_SUMMARY:
            if depths:
                msg.set(F_AVG_DEPTH, sum(depths) / len(depths))
                msg.set(F_MAX_DEPTH, max(depths))
            if summary2 is not None:
                for num in (F_BOTTOM_TIME, F_O2_TOX):
                    a, b = msg.get(num), summary2.get(num)
                    if a is not None and b is not None:
                        msg.set(num, a + b)
                for num in (F_END_CNS, F_END_N2):
                    value = summary2.get(num)
                    if value is not None:
                        msg.set(num, value)
        elif msg.mesg_num == TANK_SUMMARY and msg.get(F_SENSOR) in summaries2:
            other = summaries2[msg.get(F_SENSOR)]
            end = other.get(F_END_PRESSURE)
            if end is not None:
                msg.set(F_END_PRESSURE, end)
            a, b = msg.get(F_VOLUME_USED), other.get(F_VOLUME_USED)
            if a is not None and b is not None:
                msg.set(F_VOLUME_USED, a + b)

    writer = _Writer()
    # Where the second file's gases and pods go: after the first file's last
    # gas, or before its first sample when it lists none.
    insert_after = max((i for i, m in enumerate(msgs1) if m.mesg_num == DIVE_GAS), default=None)
    first_record = next(i for i, m in enumerate(msgs1) if m.mesg_num == RECORD)
    for i, msg in enumerate(msgs1):
        if insert_after is None and i == first_record:
            for added in additions:
                writer.write(added)
        if _is_timer(msg, EVENT_TYPE_STOPS) and (msg.timestamp is None or msg.timestamp >= last1):
            continue  # the first log's timer stop: the dive goes on
        writer.write(msg)
        if insert_after is not None and i == insert_after:
            for added in additions:
                writer.write(added)
    for msg in filler + stream2:
        writer.write(msg)

    header = _header_of(first)
    struct.pack_into("<I", header, 4, len(writer.out))
    if writer.developer_fields and header[1] < 0x20:
        header[1] = 0x20  # developer fields need protocol 2.0
    if len(header) == 14:
        struct.pack_into("<H", header, 12, fit_crc(header[:12]))
    data = bytes(header) + bytes(writer.out)
    dest.write_bytes(data + struct.pack("<H", fit_crc(data)))
    return MergeResult(gap_seconds=gap, shift_seconds=delta, filled_samples=len(filler),
                       gases_added=len(new_gases))
