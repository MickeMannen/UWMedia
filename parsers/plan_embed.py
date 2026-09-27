"""The Dive Profile Builder's own mark on the logs it writes, and the plan
it embeds in them so a saved log can be opened again and edited
(uwmedia/backends/dive_profile_backend.py's Open log).

Every writer (parsers/uddf_writer.py, subsurface_writer.py, fit_writer.py)
stamps two things: a marker that says "UWMedia wrote this" and, since
0.8, the DiveProfilePlan itself as JSON. Each format keeps them where
that format expects application data, so other software ignores them:

- UDDF: <generator><name>UWMedia Dive Profile Builder</name> (the marker
  every UWMedia UDDF has carried from the start) and, under the <dive>,
  <applicationdata><uwmedia><plan>...</plan></uwmedia></applicationdata>.
- Subsurface XML: the dive's <notes> naming the builder (the original
  marker) and an <extradata key="UWMedia plan" value="..."/> on the
  divecomputer - Subsurface's own key/value slot for computer data.
- Garmin FIT: a developer_data_id whose application_id is UWMedia's
  FIT_APPLICATION_ID, with the plan spread over developer string fields
  of the file_creator message - FIT limits a field to 255 bytes, so the
  JSON is zlib-compressed, base64-encoded and cut into FIT_CHUNK_BYTES
  chunks named uwmedia_plan_0, uwmedia_plan_1, ...

read_log_origin() is the single entry point for reading: whether a file
was written by UWMedia at all, and the embedded plan when it has one. A
file with the marker but no plan (saved before 0.8) is still UWMedia's -
the builder then rebuilds a plan from the samples instead
(utils/dive_plan_import.py).
"""
import base64
import json
import uuid
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from lxml import etree
from pydantic import ValidationError

from models.dive_plan import DiveProfilePlan

PLAN_FORMAT = "uwmedia_dive_plan"
PLAN_FORMAT_VERSION = 1

GENERATOR_NAME = "UWMedia Dive Profile Builder"
SUBSURFACE_NOTES_MARK = "UWMedia Dive Profile Builder"
SUBSURFACE_PLAN_KEY = "UWMedia plan"
# Fixed id for UWMedia as a FIT "developer" - any file whose developer_data_id
# carries it was written by UWMedia. Never change it: old files are matched by it.
FIT_APPLICATION_ID = uuid.UUID("2b0c3d64-7a1e-4f2b-9c5d-8e6f1a2b3c4d")
FIT_PLAN_FIELD_PREFIX = "uwmedia_plan_"
FIT_CHUNK_BYTES = 250
FIT_STRING_BASE_TYPE = 7  # fit_base_type_id of a string
FIT_DEVELOPER_DATA_INDEX = 0

SUBSURFACE_SUFFIXES = {".ssrf", ".xml"}


@dataclass(frozen=True)
class LogOrigin:
    """What read_log_origin() found: whether UWMedia wrote the file, and its
    embedded plan when there is one."""
    created_by_uwmedia: bool
    plan: Optional[DiveProfilePlan] = None


# ---------------------------------------------------------------------------
# The plan as text
# ---------------------------------------------------------------------------

def plan_to_json(plan: DiveProfilePlan) -> str:
    """Compact JSON envelope round-tripped by plan_from_json()."""
    payload = {"format": PLAN_FORMAT, "version": PLAN_FORMAT_VERSION, "plan": plan.model_dump(mode="json")}
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


def plan_from_json(text: Optional[str]) -> Optional[DiveProfilePlan]:
    """The plan in a plan_to_json() envelope; None when the text isn't one
    (or no longer validates, e.g. from a newer version's fields)."""
    if not text:
        return None
    try:
        payload = json.loads(text)
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict) or payload.get("format") != PLAN_FORMAT:
        return None
    try:
        return DiveProfilePlan.model_validate(payload.get("plan") or {})
    except ValidationError:
        return None


# ---------------------------------------------------------------------------
# UDDF
# ---------------------------------------------------------------------------

def add_uddf_plan(dive_el, plan: DiveProfilePlan, ns: str) -> None:
    """<applicationdata><uwmedia><plan>json</plan></uwmedia></applicationdata>
    under a UDDF <dive> element (namespace `ns`)."""
    appdata = etree.SubElement(dive_el, f"{{{ns}}}applicationdata")
    uwmedia = etree.SubElement(appdata, f"{{{ns}}}uwmedia")
    plan_el = etree.SubElement(uwmedia, f"{{{ns}}}plan")
    plan_el.text = plan_to_json(plan)


def _uddf_origin(path: Path) -> LogOrigin:
    root = etree.parse(str(path)).getroot()
    generator = root.xpath("string(.//*[local-name()='generator']/*[local-name()='name'])")
    created = GENERATOR_NAME.lower() in (generator or "").lower()
    plan_text = root.xpath(
        "string(.//*[local-name()='applicationdata']/*[local-name()='uwmedia']/*[local-name()='plan'])"
    )
    plan = plan_from_json(plan_text)
    return LogOrigin(created or plan is not None, plan)


# ---------------------------------------------------------------------------
# Subsurface XML
# ---------------------------------------------------------------------------

def add_subsurface_plan(divecomputer_el, plan: DiveProfilePlan) -> None:
    etree.SubElement(divecomputer_el, "extradata", key=SUBSURFACE_PLAN_KEY, value=plan_to_json(plan))


def _subsurface_origin(path: Path) -> LogOrigin:
    root = etree.parse(str(path)).getroot()
    notes = " ".join(root.xpath(".//dive/notes/text()"))
    created = SUBSURFACE_NOTES_MARK.lower() in notes.lower()
    values = root.xpath(f".//divecomputer/extradata[@key='{SUBSURFACE_PLAN_KEY}']/@value")
    plan = plan_from_json(values[0]) if values else None
    return LogOrigin(created or plan is not None, plan)


# ---------------------------------------------------------------------------
# Garmin FIT
# ---------------------------------------------------------------------------

def _fit_chunks(plan: DiveProfilePlan) -> List[str]:
    packed = base64.b64encode(zlib.compress(plan_to_json(plan).encode("utf-8"), 9)).decode("ascii")
    return [packed[i:i + FIT_CHUNK_BYTES] for i in range(0, len(packed), FIT_CHUNK_BYTES)]


def _fit_unpack(chunks: List[str]) -> Optional[DiveProfilePlan]:
    try:
        text = zlib.decompress(base64.b64decode("".join(chunks))).decode("utf-8")
    except (ValueError, zlib.error, UnicodeDecodeError):
        return None
    return plan_from_json(text)


def fit_plan_messages(encoder, plan: DiveProfilePlan, mesg_num_of) -> Tuple[List[dict], Dict[str, str]]:
    """Registers UWMedia's developer fields on a garmin_fit_sdk Encoder and
    returns (messages, developer_fields): the developer_data_id and
    field_description messages to write before the carrying message, and
    the `developer_fields` dict to put on that message (the file_creator).
    `mesg_num_of(name)` resolves a profile message name to its number."""
    dev_id = {
        "mesg_num": mesg_num_of("developer_data_id"),
        "developer_data_index": FIT_DEVELOPER_DATA_INDEX,
        "application_id": list(FIT_APPLICATION_ID.bytes),
        "application_version": PLAN_FORMAT_VERSION,
    }
    messages = [dev_id]
    developer_fields: Dict[str, str] = {}
    for i, chunk in enumerate(_fit_chunks(plan)):
        key = f"{FIT_PLAN_FIELD_PREFIX}{i}"
        description = {
            "mesg_num": mesg_num_of("field_description"),
            "developer_data_index": FIT_DEVELOPER_DATA_INDEX,
            "field_definition_number": i,
            "fit_base_type_id": FIT_STRING_BASE_TYPE,
            "field_name": key,
        }
        encoder.add_developer_field(key, dev_id, description)
        messages.append(description)
        developer_fields[key] = chunk
    return messages, developer_fields


def _fit_origin(path: Path) -> LogOrigin:
    from garmin_fit_sdk import Decoder, Stream

    messages, _errors = Decoder(Stream.from_file(str(path))).read()
    wanted = list(FIT_APPLICATION_ID.bytes)
    created = any(
        list(m.get("application_id") or []) == wanted for m in messages.get("developer_data_id_mesgs", [])
    )
    if not created:
        return LogOrigin(False, None)
    # Developer field values come back keyed by the field_description's
    # position in the file; map that back to the chunk names.
    name_of_key = {
        m.get("key"): m.get("field_name") for m in messages.get("field_description_mesgs", [])
        if str(m.get("field_name", "")).startswith(FIT_PLAN_FIELD_PREFIX)
    }
    chunks: Dict[int, str] = {}
    for creator in messages.get("file_creator_mesgs", []):
        for key, value in (creator.get("developer_fields") or {}).items():
            name = name_of_key.get(key)
            if name and isinstance(value, str):
                chunks[int(name[len(FIT_PLAN_FIELD_PREFIX):])] = value
    plan = _fit_unpack([chunks[i] for i in sorted(chunks)]) if chunks else None
    return LogOrigin(True, plan)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def read_log_origin(path) -> LogOrigin:
    """Whether `path` is a log the Dive Profile Builder wrote, and its
    embedded plan when it carries one. A file that can't be read at all
    (wrong format, corrupt) counts as not UWMedia's."""
    path = Path(path)
    suffix = path.suffix.lower()
    try:
        if suffix == ".uddf":
            return _uddf_origin(path)
        if suffix in SUBSURFACE_SUFFIXES:
            return _subsurface_origin(path)
        if suffix == ".fit":
            return _fit_origin(path)
    except Exception:
        return LogOrigin(False, None)
    return LogOrigin(False, None)
