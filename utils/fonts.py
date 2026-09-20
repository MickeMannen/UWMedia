"""Font registry for the HUD renderer and the Overlay Designer -
overlay_rework.md Phase 2 (decision Q7).

Families available to a template's `font_family` element attribute:

- "Arial" (the default, and what every template without the attribute has
  always rendered with): the platform's own Arial where present (macOS,
  Windows), else the bundled metric-compatible Liberation Sans, else the
  Linux DejaVu/Liberation system fonts the renderer used to look for.
- The bundled set under resources/fonts/ (a top-level Briefcase `sources`
  entry, so it lands beside `overlays`/`licenses` in a packaged app):
  DejaVu Sans, Liberation Sans, Roboto, Roboto Mono, DSEG7 Classic - each
  as Regular + Bold, OFL/Apache/Bitstream-licensed (license texts under
  resources/licenses/*_FONT_LICENSE.txt). Family names are read from the
  font files themselves, so a new .ttf dropped into that folder registers
  itself.

Everything degrades to today's behaviour: unknown family -> Arial, missing
Bold -> Regular, no Arial anywhere -> PIL's own fallback in get_font().
"""
import os
import platform
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional

from PIL import ImageFont

from utils.resource_paths import find_resource

DEFAULT_FAMILY = "Arial"
WEIGHT_REGULAR = "regular"
WEIGHT_BOLD = "bold"
WEIGHTS = (WEIGHT_REGULAR, WEIGHT_BOLD)
FONT_SUFFIXES = (".ttf", ".otf")


def _system_arial_candidates() -> Dict[str, List[str]]:
    system = platform.system()
    if system == "Windows":
        fonts = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        return {
            WEIGHT_REGULAR: [str(fonts / "arial.ttf")],
            WEIGHT_BOLD: [str(fonts / "arialbd.ttf")],
        }
    if system == "Darwin":
        return {
            WEIGHT_REGULAR: ["/System/Library/Fonts/Supplemental/Arial.ttf", "/Library/Fonts/Arial.ttf"],
            WEIGHT_BOLD: ["/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/Library/Fonts/Arial Bold.ttf"],
        }
    return {
        WEIGHT_REGULAR: [
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/TTF/DejaVuSans.ttf",
        ],
        WEIGHT_BOLD: [
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
        ],
    }


def bundled_fonts_dir() -> Optional[Path]:
    """resources/fonts in a source checkout, or the sibling `fonts` directory
    Briefcase creates from that `sources` entry in a packaged app."""
    direct = find_resource("fonts", __file__, max_depth=4)
    if direct and direct.is_dir():
        return direct
    resources = find_resource("resources", __file__, max_depth=4)
    if resources and (resources / "fonts").is_dir():
        return resources / "fonts"
    return None


def _scan_bundled() -> Dict[str, Dict[str, str]]:
    families: Dict[str, Dict[str, str]] = {}
    directory = bundled_fonts_dir()
    if directory is None:
        return families
    for path in sorted(directory.iterdir()):
        if path.suffix.lower() not in FONT_SUFFIXES:
            continue
        try:
            family, style = ImageFont.truetype(str(path), 12).getname()
        except Exception:
            continue
        weight = WEIGHT_BOLD if "bold" in (style or "").lower() else WEIGHT_REGULAR
        families.setdefault(family, {}).setdefault(weight, str(path))
    return families


@lru_cache(maxsize=1)
def registry() -> Dict[str, Dict[str, str]]:
    """{family: {weight: path}} - Arial first, then the bundled families."""
    bundled = _scan_bundled()
    arial: Dict[str, str] = {}
    for weight, candidates in _system_arial_candidates().items():
        for candidate in candidates:
            if os.path.exists(candidate):
                arial[weight] = candidate
                break
    liberation = bundled.get("Liberation Sans", {})
    for weight in WEIGHTS:
        if weight not in arial and weight in liberation:
            arial[weight] = liberation[weight]
    families: Dict[str, Dict[str, str]] = {}
    if arial:
        families[DEFAULT_FAMILY] = arial
    for family in sorted(bundled):
        families.setdefault(family, bundled[family])
    return families


def list_families() -> List[str]:
    return list(registry().keys())


def fallback_font_path() -> str:
    """The regular Arial path (or best stand-in) - what the renderer has
    always loaded when no font attribute is present."""
    arial = registry().get(DEFAULT_FAMILY, {})
    return arial.get(WEIGHT_REGULAR) or arial.get(WEIGHT_BOLD) or "arial.ttf"


def font_path(family: Optional[str] = None, weight: Optional[str] = None) -> str:
    """Resolve a template's font_family/font_weight to a file path, degrading
    gracefully: unknown family -> Arial; missing weight -> regular."""
    families = registry()
    weight = (weight or WEIGHT_REGULAR).lower()
    if weight not in WEIGHTS:
        weight = WEIGHT_REGULAR
    entry = families.get(family or DEFAULT_FAMILY) or families.get(DEFAULT_FAMILY) or {}
    return entry.get(weight) or entry.get(WEIGHT_REGULAR) or entry.get(WEIGHT_BOLD) or fallback_font_path()
