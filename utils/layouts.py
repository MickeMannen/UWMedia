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
        variants = sorted(p.name for p in page_dir.iterdir() if p.is_dir()) if page_dir.exists() else []
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
    state selection, or None if that combination doesn't exist."""
    manifest = list_templates().get(brand, {}).get(computer)
    if manifest is None:
        return None
    for page_entry in manifest.get("pages", []):
        if page_entry["id"] != page:
            continue
        page_dir = page_entry["path"]
        state_path = (page_dir / variant / f"{state}.json") if variant else (page_dir / f"{state}.json")
        return state_path if state_path.exists() else None
    return None
