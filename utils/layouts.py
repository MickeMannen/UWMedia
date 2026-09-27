import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from utils.app_settings import load_settings
from utils.resource_paths import find_resource, user_data_dir

LAYOUT_SUFFIXES = (".zip", ".json")


def bundled_layouts_dir() -> Optional[Path]:
    """The read-only 'overlays' folder Briefcase copies into the app bundle."""
    return find_resource("overlays", __file__)


def user_layouts_dir() -> Path:
    """Writable folder for the user's own HUD packages - overridable in Advanced settings."""
    override = load_settings().get("layouts_dir")
    path = Path(override) if override else user_data_dir() / "layouts"
    path.mkdir(parents=True, exist_ok=True)
    return path


def list_layouts() -> List[Tuple[str, Path]]:
    """
    (display_name, path) pairs for every bundled or user-supplied HUD
    layout/package, sorted by name. A user file with the same stem as a
    bundled one takes precedence.
    """
    entries = {}

    bundled = bundled_layouts_dir()
    if bundled and bundled.exists():
        for path in sorted(bundled.iterdir()):
            if path.suffix.lower() in LAYOUT_SUFFIXES:
                entries[path.stem] = path

    user_dir = user_layouts_dir()
    if user_dir.exists():
        for path in sorted(user_dir.iterdir()):
            if path.suffix.lower() in LAYOUT_SUFFIXES:
                entries[path.stem] = path

    return sorted(entries.items())


def bundled_templates_dir() -> Optional[Path]:
    """The read-only 'overlays/templates' folder Briefcase copies into the app bundle."""
    overlays = bundled_layouts_dir()
    if overlays is None:
        return None
    templates = overlays / "templates"
    return templates if templates.exists() else None


def user_templates_dir() -> Path:
    """Writable folder for the user's own template packages - overridable in Advanced settings."""
    override = load_settings().get("templates_dir")
    path = Path(override) if override else user_data_dir() / "templates"
    path.mkdir(parents=True, exist_ok=True)
    return path


# Tank-setup variants of a page, in the order the pickers list them - the
# number of tanks, from none up. Anything else a template tree adds follows
# alphabetically.
VARIANT_ORDER = ("no_tank", "single_tank", "sidemount", "multi_tank")
VARIANT_LABELS = {"no_tank": "No tank", "single_tank": "Single tank", "sidemount": "Sidemount", "multi_tank": "Multi-tank"}


def sort_variants(names) -> List[str]:
    known = [v for v in VARIANT_ORDER if v in names]
    return known + sorted(v for v in names if v not in VARIANT_ORDER)


def variant_display_name(variant: str) -> str:
    return VARIANT_LABELS.get(variant, variant.replace("_", " ").title())


def _read_manifest(computer_dir: Path) -> Optional[Dict[str, Any]]:
    """Parsed manifest.json for one brand/computer directory, with "path" added
    to the manifest and to each of its pages, and "variants" (subdirectory
    names - empty if the page has no variant level) added to each page."""
    manifest_path = computer_dir / "manifest.json"
    if not manifest_path.exists():
        return None
    try:
        with open(manifest_path) as f:
            manifest = json.load(f)
    except Exception:
        return None

    manifest["path"] = computer_dir
    pages = []
    for page in manifest.get("pages", []):
        page_dir = computer_dir / page["id"]
        variants = sort_variants([p.name for p in page_dir.iterdir() if p.is_dir()]) if page_dir.exists() else []
        pages.append({**page, "path": page_dir, "variants": variants})
    manifest["pages"] = pages
    return manifest


def page_display_name(page: Dict[str, Any]) -> str:
    """Cascade label for a manifest page entry - user-owned pages are marked
    so the three template pickers (Overlay Designer, Overlay Generator,
    Color's Add Overlay) all show the same "yours" hint."""
    name = page.get("name") or page.get("id", "")
    return f"{name} · yours" if page.get("origin") == "user" else name


def list_templates() -> Dict[str, Dict[str, Dict[str, Any]]]:
    """
    {brand: {computer: manifest}} for every bundled or user-supplied template
    tree under overlays/templates (see rework_hud.md for the tree layout).
    `manifest` is manifest.json's parsed contents plus "path" (the computer's
    directory), "origin" ("bundled" or "user") and, per page, "variants"
    (subdirectory names - empty if the page has no variant level), "path" and
    "origin".

    Merging is *additive* (overlay_rework.md §5.1/§5.2): a user computer
    directory that matches a bundled brand/computer adds its own pages beside
    the bundled ones (its manifest may list only those pages); a user page
    whose id collides with a bundled page is skipped with a warning - bundled
    pages are never shadowed. Brands/computers that exist only in the user
    tree (e.g. the Custom brand) are added whole. The user computer directory,
    when present, is recorded as manifest["user_path"].
    """
    brands: Dict[str, Dict[str, Dict[str, Any]]] = {}

    for templates_dir, origin in ((bundled_templates_dir(), "bundled"), (user_templates_dir(), "user")):
        if not templates_dir or not templates_dir.exists():
            continue
        for brand_dir in sorted(templates_dir.iterdir()):
            if not brand_dir.is_dir():
                continue
            for computer_dir in sorted(brand_dir.iterdir()):
                if not computer_dir.is_dir():
                    continue
                manifest = _read_manifest(computer_dir)
                if manifest is None:
                    continue
                manifest["origin"] = origin
                for page in manifest["pages"]:
                    page["origin"] = origin
                if origin == "user":
                    manifest["user_path"] = computer_dir

                existing = brands.get(brand_dir.name, {}).get(computer_dir.name)
                if existing is None:
                    brands.setdefault(brand_dir.name, {})[computer_dir.name] = manifest
                    continue

                # Additive merge into the bundled computer.
                existing["user_path"] = computer_dir
                existing_ids = {p["id"] for p in existing["pages"]}
                for page in manifest["pages"]:
                    if page["id"] in existing_ids:
                        print(
                            f"Warning: user template page {brand_dir.name}/{computer_dir.name}/{page['id']} "
                            f"collides with a bundled page and is ignored (bundled pages cannot be overridden)."
                        )
                        continue
                    existing["pages"].append(page)
                    existing_ids.add(page["id"])

    return brands


def resolve_template_state(
    brand: str, computer: str, page: str, variant: Optional[str] = None, state: str = "normal"
) -> Optional[Path]:
    """Path to the state .json file for a given brand/computer/page[/variant]/
    state selection, or None if that combination doesn't exist. A page with
    variants has no state of its own (its page-level normal.json, when
    present, is the variants' shared base - see load_layout_file), so
    variant=None resolves to None there."""
    manifest = list_templates().get(brand, {}).get(computer)
    if manifest is None:
        return None
    for page_entry in manifest.get("pages", []):
        if page_entry["id"] != page:
            continue
        page_dir = page_entry["path"]
        if variant is None and page_entry.get("variants"):
            return None
        state_path = (page_dir / variant / f"{state}.json") if variant else (page_dir / f"{state}.json")
        return state_path if state_path.exists() else None
    return None


# ----------------------------------------------------------------------
# Variant overlays: a page's variants (single_tank / sidemount) share one
# base layout and add only what differs
# ----------------------------------------------------------------------
#
# A variant state file is either a complete layout (the original form, still
# valid) or an *overlay* on the page's shared base:
#
#   main/normal.json              the base: manufacturer, model, hud_skin
#                                 (skin image, scale, anchor) and every
#                                 element the variants share, each with an "id"
#   main/single_tank/normal.json  {"base": "../normal.json",
#                                  "linked_elements": [...tank block...],
#                                  "overrides": {"<id>": {"rel_x": ...}},   # optional
#                                  "remove": ["<id>"]}                     # optional
#
# load_layout_file() merges the two into the flat layout every consumer
# already understands: base elements first (overrides applied, removed ones
# dropped), then the variant's own elements; the skin path re-pointed at the
# base's image. The merged layout is tagged so the Overlay Designer can put
# an edit back where it came from (utils/template_store.save_template):
# LAYOUT_BASE_KEY on the layout (absolute base path) and ELEMENT_ORIGIN_KEY
# on each element ("base", "override" or "variant"). Both are transient -
# strip_variant_markers() removes them before anything is written or exported.

VARIANT_BASE_FIELD = "base"
VARIANT_ELEMENTS_FIELD = "linked_elements"
VARIANT_OVERRIDES_FIELD = "overrides"
VARIANT_REMOVE_FIELD = "remove"
LAYOUT_BASE_KEY = "_variant_of"
ELEMENT_ORIGIN_KEY = "_origin"
ORIGIN_BASE, ORIGIN_OVERRIDE, ORIGIN_VARIANT = "base", "override", "variant"


def is_variant_overlay(data: Dict[str, Any]) -> bool:
    return isinstance(data, dict) and isinstance(data.get(VARIANT_BASE_FIELD), str)


def variant_base_path(overlay_path: Path, data: Dict[str, Any]) -> Path:
    return (Path(overlay_path).parent / data[VARIANT_BASE_FIELD]).resolve()


def merge_variant_layout(base: Dict[str, Any], overlay: Dict[str, Any], base_dir: Path, overlay_dir: Path) -> Dict[str, Any]:
    """The flat layout for a variant overlay on `base` (deep-copied), tagged
    with LAYOUT_BASE_KEY / ELEMENT_ORIGIN_KEY. Relative skin paths are
    re-expressed relative to `overlay_dir`, where consumers resolve them."""
    import copy
    import os

    layout = copy.deepcopy(base)
    skin = layout.setdefault("hud_skin", {})
    raw = skin.get("path")
    if raw and not Path(raw).is_absolute():
        skin["path"] = os.path.relpath((Path(base_dir) / raw).resolve(), Path(overlay_dir).resolve())
    overrides = overlay.get(VARIANT_OVERRIDES_FIELD) or {}
    removed = set(overlay.get(VARIANT_REMOVE_FIELD) or [])
    merged: List[Dict[str, Any]] = []
    for elem in skin.get("linked_elements", []):
        elem_id = elem.get("id")
        if elem_id in removed:
            continue
        elem = dict(elem)
        if elem_id in overrides:
            elem.update(overrides[elem_id])
            elem[ELEMENT_ORIGIN_KEY] = ORIGIN_OVERRIDE
        else:
            elem[ELEMENT_ORIGIN_KEY] = ORIGIN_BASE
        merged.append(elem)
    for elem in overlay.get(VARIANT_ELEMENTS_FIELD) or []:
        elem = dict(elem)
        elem[ELEMENT_ORIGIN_KEY] = ORIGIN_VARIANT
        merged.append(elem)
    skin["linked_elements"] = merged
    for key, value in overlay.items():
        if key not in (VARIANT_BASE_FIELD, VARIANT_ELEMENTS_FIELD, VARIANT_OVERRIDES_FIELD, VARIANT_REMOVE_FIELD):
            layout[key] = value
    return layout


def load_layout_file(path) -> Dict[str, Any]:
    """The flat layout in a template state file - the file itself, or, for a
    variant overlay, its base merged with it (merge_variant_layout). The
    result of an overlay carries the transient LAYOUT_BASE_KEY /
    ELEMENT_ORIGIN_KEY markers; strip_variant_markers() removes them."""
    path = Path(path)
    with open(path) as f:
        data = json.load(f)
    if not is_variant_overlay(data):
        return data
    base_path = variant_base_path(path, data)
    with open(base_path) as f:
        base = json.load(f)
    layout = merge_variant_layout(base, data, base_path.parent, path.parent)
    layout[LAYOUT_BASE_KEY] = str(base_path)
    return layout


def strip_variant_markers(layout: Dict[str, Any]) -> Dict[str, Any]:
    """Deep copy without the transient overlay markers - what gets written,
    exported or compared."""
    import copy

    data = copy.deepcopy(layout)
    data.pop(LAYOUT_BASE_KEY, None)
    for elem in data.get("hud_skin", {}).get("linked_elements", []):
        elem.pop(ELEMENT_ORIGIN_KEY, None)
    return data


def split_variant_layout(layout: Dict[str, Any], base: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """The inverse of merge_variant_layout for saving an edited merged
    layout: (new base layout, overlay data). Shared elements (origin base /
    override) go back to the base in the edited order; an overridden
    element keeps the base's own values in the base and its differing keys
    in the overlay's overrides; elements the variant added, and any element
    without an origin (added while editing this variant), go to the
    overlay; base elements no longer present are listed under remove. The
    skin and every non-element key follow the base."""
    import copy

    base_elems = {e.get("id"): e for e in base.get("hud_skin", {}).get("linked_elements", []) if e.get("id")}
    new_base = strip_variant_markers(layout)
    shared: List[Dict[str, Any]] = []
    variant_elems: List[Dict[str, Any]] = []
    overrides: Dict[str, Dict[str, Any]] = {}
    seen_ids = set()
    for elem in layout.get("hud_skin", {}).get("linked_elements", []):
        origin = elem.get(ELEMENT_ORIGIN_KEY)
        clean = {k: v for k, v in elem.items() if k != ELEMENT_ORIGIN_KEY}
        elem_id = clean.get("id")
        if origin in (ORIGIN_BASE, ORIGIN_OVERRIDE) and elem_id in base_elems:
            seen_ids.add(elem_id)
            original = base_elems[elem_id]
            if origin == ORIGIN_OVERRIDE:
                diff = {k: v for k, v in clean.items() if original.get(k, object()) != v}
                diff.pop("id", None)
                if diff:
                    overrides[elem_id] = diff
                shared.append(copy.deepcopy(original))
            else:
                shared.append(clean)
        elif origin == ORIGIN_BASE:
            shared.append(clean)  # a base element without an id - written back as it is
        else:
            variant_elems.append(clean)
    new_base["hud_skin"]["linked_elements"] = shared
    removed = [eid for eid in base_elems if eid not in seen_ids]
    overlay: Dict[str, Any] = {VARIANT_ELEMENTS_FIELD: variant_elems}
    if overrides:
        overlay[VARIANT_OVERRIDES_FIELD] = overrides
    if removed:
        overlay[VARIANT_REMOVE_FIELD] = removed
    return new_base, overlay
