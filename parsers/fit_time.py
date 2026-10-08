"""Correct the clock of a Garmin FIT dive log: shift every timestamp in the
file by the same amount and set the time zone, keeping every other byte as
it was (Log Viewer's "Adjust time", for a dive computer whose clock was
wrong before the dive).

The file is rewritten at the record level rather than decoded and encoded
again, so fields, developer data and messages the SDK doesn't know survive
unchanged. Shifted: every message's timestamp (field 253) and the other
date_time fields Garmin dive files carry (file_id.time_created,
session.start_time, lap.start_time); activity.local_timestamp is set to the
new activity timestamp plus the new UTC offset, which is where
parsers/garmin.py reads the dive's time zone from. Compressed-timestamp
records get their 5-bit offset shifted along. The file CRC is recomputed.
"""
import struct
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Optional, Tuple

FIT_EPOCH = datetime(1989, 12, 31, tzinfo=timezone.utc)

TIMESTAMP_FIELD = 253
# (global message number, field number) of the other date_time fields.
DATE_TIME_FIELDS = {(0, 4), (18, 2), (19, 2)}  # file_id.time_created, session/lap.start_time
ACTIVITY_MESG = 34
ACTIVITY_LOCAL_TIMESTAMP = 5
UINT32 = 0x86
INVALID_UINT32 = 0xFFFFFFFF
# FIT date_time values below this are seconds since device power-on, not dates.
MIN_DATE_TIME = 0x10000000

_CRC_TABLE = (0x0000, 0xCC01, 0xD801, 0x1400, 0xF001, 0x3C00, 0x2800, 0xE401,
              0xA001, 0x6C00, 0x7800, 0xB401, 0x5000, 0x9C01, 0x8801, 0x4400)


def fit_crc(data: bytes, crc: int = 0) -> int:
    for byte in data:
        for nibble in (byte & 0x0F, byte >> 4):
            tmp = _CRC_TABLE[crc & 0x0F]
            crc = (crc >> 4) & 0x0FFF
            crc = crc ^ tmp ^ _CRC_TABLE[nibble]
    return crc


class _Definition:
    def __init__(self, mesg_num: int, endian: str, fields, dev_size: int, raw: bytes = b""):
        self.mesg_num = mesg_num
        self.endian = endian
        self.fields = fields  # [(field number, size, base type)]
        self.dev_size = dev_size
        self.raw = raw  # the definition message as it is in the file, header byte included

    @property
    def size(self) -> int:
        return sum(size for _, size, _ in self.fields) + self.dev_size


def _walk(data: bytearray, on_message) -> None:
    """Call on_message(definition, offset of the message's fields, header
    offset, compressed) for every data message of every FIT file chained in
    `data`. Raises ValueError for something that isn't a FIT file."""
    pos = 0
    while pos < len(data):
        if len(data) - pos < 12:
            raise ValueError("Not a FIT file (too short)")
        header_size = data[pos]
        data_size = struct.unpack_from("<I", data, pos + 4)[0]
        if header_size not in (12, 14) or bytes(data[pos + 8:pos + 12]) != b".FIT":
            raise ValueError("Not a FIT file")
        end = pos + header_size + data_size
        if end + 2 > len(data):
            raise ValueError("FIT file is truncated")
        definitions: Dict[int, _Definition] = {}
        p = pos + header_size
        while p < end:
            header = data[p]
            if header & 0x80:  # compressed timestamp header: a data message
                definition = definitions.get((header >> 5) & 0x03)
                if definition is None:
                    raise ValueError("FIT data message without a definition")
                on_message(definition, p + 1, p, True)
                p += 1 + definition.size
            elif header & 0x40:  # definition message
                local = header & 0x0F
                endian = ">" if data[p + 2] == 1 else "<"
                mesg_num = struct.unpack_from(endian + "H", data, p + 3)[0]
                count = data[p + 5]
                fields = [(data[p + 6 + 3 * i], data[p + 7 + 3 * i], data[p + 8 + 3 * i]) for i in range(count)]
                q = p + 6 + 3 * count
                dev_size = 0
                if header & 0x20:  # developer fields
                    dev_count = data[q]
                    dev_size = sum(data[q + 2 + 3 * i] for i in range(dev_count))
                    q += 1 + 3 * dev_count
                definitions[local] = _Definition(mesg_num, endian, fields, dev_size, bytes(data[p:q]))
                p = q
            else:
                definition = definitions.get(header & 0x0F)
                if definition is None:
                    raise ValueError("FIT data message without a definition")
                on_message(definition, p + 1, p, False)
                p += 1 + definition.size
        pos = end + 2


def _fields(definition: _Definition, start: int):
    """(field number, offset, size, base type) of each field of a message."""
    offset = start
    for num, size, base in definition.fields:
        yield num, offset, size, base
        offset += size


def _read_u32(data, offset: int, endian: str) -> int:
    return struct.unpack_from(endian + "I", data, offset)[0]


def fit_activity_time(path: Path) -> Tuple[datetime, Optional[int]]:
    """The activity message's timestamp (UTC, aware) and its UTC offset in
    minutes (None when the file has no local_timestamp)."""
    data = bytearray(Path(path).read_bytes())
    found = {}

    def on_message(definition, start, _header, _compressed):
        if definition.mesg_num != ACTIVITY_MESG or "utc" in found:
            return
        for num, offset, size, base in _fields(definition, start):
            if size == 4 and num == TIMESTAMP_FIELD:
                found["utc"] = _read_u32(data, offset, definition.endian)
            elif size == 4 and num == ACTIVITY_LOCAL_TIMESTAMP:
                found["local"] = _read_u32(data, offset, definition.endian)

    _walk(data, on_message)
    if "utc" not in found or found["utc"] in (INVALID_UINT32,):
        raise ValueError("The FIT file has no activity time to adjust")
    utc = FIT_EPOCH + timedelta(seconds=found["utc"])
    local = found.get("local")
    offset = None
    if local not in (None, INVALID_UINT32):
        offset = round((local - found["utc"]) / 60)
    return utc, offset


def adjust_fit_time(src: Path, dest: Path, local_start: datetime, utc_offset_minutes: int) -> int:
    """Write `src` to `dest` with its activity starting at `local_start` (naive,
    the dive site's local time) in UTC`utc_offset_minutes`. Returns the shift
    applied to every timestamp, in seconds."""
    old_utc, _ = fit_activity_time(src)
    new_utc = (local_start - timedelta(minutes=utc_offset_minutes)).replace(tzinfo=timezone.utc)
    delta = int((new_utc - old_utc).total_seconds())
    data = bytearray(Path(src).read_bytes())

    def shift(offset: int, endian: str) -> Optional[int]:
        value = _read_u32(data, offset, endian)
        if value == INVALID_UINT32 or value < MIN_DATE_TIME:
            return None
        value += delta
        if not MIN_DATE_TIME <= value < INVALID_UINT32:
            raise ValueError("The adjusted time is out of the FIT file's range")
        struct.pack_into(endian + "I", data, offset, value)
        return value

    def on_message(definition, start, header, compressed):
        if compressed:
            # The 5-bit time offset is relative to the last full timestamp,
            # which moves by `delta` too.
            data[header] = (data[header] & 0xE0) | ((data[header] + delta) & 0x1F)
        new_timestamp, local_offset = None, None
        for num, offset, size, base in _fields(definition, start):
            if size != 4 or base & 0x1F != UINT32 & 0x1F:
                continue
            if num == TIMESTAMP_FIELD:
                new_timestamp = shift(offset, definition.endian)
            elif (definition.mesg_num, num) in DATE_TIME_FIELDS:
                shift(offset, definition.endian)
            elif definition.mesg_num == ACTIVITY_MESG and num == ACTIVITY_LOCAL_TIMESTAMP:
                local_offset = offset
        if local_offset is not None and new_timestamp is not None:
            struct.pack_into(definition.endian + "I", data, local_offset,
                             new_timestamp + utc_offset_minutes * 60)

    _walk(data, on_message)

    # Recompute each chained file's CRC over its header and records.
    pos = 0
    while pos < len(data):
        header_size = data[pos]
        end = pos + header_size + struct.unpack_from("<I", data, pos + 4)[0]
        struct.pack_into("<H", data, end, fit_crc(data[pos:end]))
        pos = end + 2

    Path(dest).write_bytes(bytes(data))
    return delta
