"""Dive computers the Dive Profile Builder can pose as when it writes a log
(parsers/uddf_writer.py, parsers/fit_writer.py, parsers/subsurface_writer.py).
One entry per bundled overlay template computer (overlays/templates/<brand>/
<computer>/manifest.json), so a synthetic log can drive that computer's own
templates. Each format names the device the way that computer's real exports
do, which is what UWMedia's parsers then show as Dive.device.
"""
from dataclasses import dataclass
from typing import Dict, Optional


@dataclass(frozen=True)
class DiveComputer:
    label: str  # "Shearwater Perdix 2" - the UI name and the plan's `computer` key
    manufacturer: str  # as in the template manifest
    model: str  # UDDF <divecomputer><name>, e.g. "Perdix 2" / "Descent Mk3i"
    fit_product: Optional[int] = None  # FIT garmin_product id; None = not a FIT (Garmin) device

    @property
    def is_garmin(self) -> bool:
        return self.fit_product is not None


DIVE_COMPUTERS: Dict[str, DiveComputer] = {
    c.label: c
    for c in (
        # 4518 isn't in the FIT SDK's garmin_product table yet - parsers/garmin.py
        # maps it by hand (_UNMAPPED_GARMIN_PRODUCTS).
        DiveComputer("Garmin Descent Mk3i", "Garmin", "Descent Mk3i", fit_product=4223),
        DiveComputer("Garmin Descent X50i", "Garmin", "Descent X50i", fit_product=4518),
        DiveComputer("Shearwater Perdix 2", "Shearwater", "Perdix 2"),
        DiveComputer("Shearwater Perdix 3", "Shearwater", "Perdix 3"),
        DiveComputer("Shearwater Petrel", "Shearwater", "Petrel"),
        DiveComputer("Shearwater Peregrine", "Shearwater", "Peregrine"),
        DiveComputer("Shearwater Teric", "Shearwater", "Teric"),
        DiveComputer("Shearwater Tern", "Shearwater", "Tern"),
    )
}
DEFAULT_DIVE_COMPUTER = "Shearwater Perdix 2"


def dive_computer(label: str) -> DiveComputer:
    """The computer for a plan's `computer` label; unknown labels fall back to
    the default rather than failing a save."""
    return DIVE_COMPUTERS.get(label) or DIVE_COMPUTERS[DEFAULT_DIVE_COMPUTER]
