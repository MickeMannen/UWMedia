"""Which parser reads a dive log file - the one place every page, the CLI
and the Dive Profile Builder ask, so a new format is added here once.

.uddf and .fit map straight to their parsers. .xml and .csv are shared
by more than one program's export, so those are told apart by content:

- .xml: Subsurface's <divelog> root vs Shearwater Cloud's
  <dive><diveLog> (any other .xml is tried as Subsurface, as before).
- .csv: Shearwater Cloud's "Dive Number,GF Minimum,..." header vs
  Subsurface's "sample time"/"sample depth" profile columns; any other
  CSV is not a dive log.
"""
from pathlib import Path
from typing import List, Optional

from models.dive import Dive
from parsers.garmin import GarminParser
from parsers.shearwater import ShearwaterParser
from parsers.subsurface import SubsurfaceParser
from parsers.subsurface_csv import SubsurfaceCSVParser, is_subsurface_profile_header
from parsers.uddf import UDDFParser

UDDF = "uddf"
FIT = "fit"
SUBSURFACE_XML = "subsurface_xml"
SUBSURFACE_CSV = "subsurface_csv"
SHEARWATER_XML = "shearwater_xml"
SHEARWATER_CSV = "shearwater_csv"

PARSERS = {
    UDDF: UDDFParser,
    FIT: GarminParser,
    SUBSURFACE_XML: SubsurfaceParser,
    SUBSURFACE_CSV: SubsurfaceCSVParser,
    SHEARWATER_XML: ShearwaterParser,
    SHEARWATER_CSV: ShearwaterParser,
}

LOG_EXTENSIONS = {".uddf", ".fit", ".ssrf", ".xml", ".csv"}
LOG_FILE_FILTER = (
    "Dive logs (*.uddf *.fit *.ssrf *.xml *.csv);;UDDF (*.uddf);;Garmin FIT (*.fit);;"
    "Subsurface (*.ssrf *.xml *.csv);;Shearwater Cloud (*.xml *.csv);;All files (*)"
)


def _head(path: Path, size: int = 4096) -> str:
    with open(path, "rb") as f:
        raw = f.read(size)
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16", errors="ignore")
    return raw.decode("utf-8", errors="ignore").lstrip("﻿")


def detect_log_format(path) -> Optional[str]:
    """The format key for `path`, or None when it isn't a log UWMedia reads."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".uddf":
        return UDDF
    if suffix == ".fit":
        return FIT
    if suffix == ".ssrf":
        return SUBSURFACE_XML
    if suffix not in (".xml", ".csv"):
        return None
    try:
        head = _head(path)
    except OSError:
        return None
    if suffix == ".xml":
        return SHEARWATER_XML if "<diveLog>" in head else SUBSURFACE_XML
    first_line = head.splitlines()[0] if head else ""
    if first_line.startswith("Dive Number,"):
        return SHEARWATER_CSV
    if is_subsurface_profile_header(first_line):
        return SUBSURFACE_CSV
    return None


def is_log_file(path) -> bool:
    return detect_log_format(path) is not None


def parse_log_file(path, log_format: Optional[str] = None) -> Optional[List[Dive]]:
    """The dives in one log file, each tagged with its log_format, or None
    when the file isn't a log format UWMedia reads. Parser errors raise."""
    path = Path(path)
    log_format = log_format or detect_log_format(path)
    if log_format is None:
        return None
    dives = PARSERS[log_format]().parse(path)
    for dive in dives:
        dive.log_format = log_format
    return dives
