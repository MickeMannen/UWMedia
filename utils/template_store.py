"""Where overlay templates are written, and how - overlay_rework.md Phase 3
(decisions Q3-Q6 and Q9).

Ownership model (§5.1):

- Bundled pages are read-only in release mode. `save_template()` refuses
  them; the only way to change one is `save_template_as()`, which copies the
  page (JSON + skin PNG) into a page the user owns under a *new* page id -
  under the same computer, another one, or a new Custom computer.
- User pages are purely additive. They live under the user templates dir
  (utils.layouts.user_templates_dir) in a tree that mirrors the bundled one
  exactly: templates/<brand>/<computer>/<page>/[<variant>/]normal.json +
  normal.png + manifest.json. A user manifest under a bundled computer lists
  only the user's pages (manufacturer/model copied from the bundled
  manifest so hud_rules.json lookups match). A user page can never claim a
  bundled page id.
- Dev mode (a source checkout): everything - bundled and Custom alike -
  saves straight into the repo's overlays/templates/.

Dev-mode detection (§5.3): not frozen, and `.git` + `pyproject.toml` sit two
levels above the bundled overlays/templates directory (a Briefcase bundle
has neither). The UWMEDIA_TEMPLATES_TARGET environment variable ("repo" or
"user") overrides the heuristic. There is deliberately no settings switch.
"""
import copy
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from PIL import Image

from utils.layouts import bundled_templates_dir, list_templates, resolve_template_state, user_templates_dir
from utils.overlay_document import REL_DECIMALS, TemplateRef

ENV_TARGET = "UWMEDIA_TEMPLATES_TARGET"
TARGET_REPO = "repo"
TARGET_USER = "user"
SKIN_FILENAME = "normal.png"
STATE_FILENAME = "normal.json"
MANIFEST_FILENAME = "manifest.json"
CUSTOM_BRAND = "custom"
CUSTOM_MANUFACTURER = "Custom"


class TemplateStoreError(Exception):
    """Base class for template-store failures (message is user-facing)."""


class ReadOnlyTemplateError(TemplateStoreError):
    """Save attempted on a page that isn't writable in this mode."""


class TemplateExistsError(TemplateStoreError):
    """Save-as/create targeted a page id that already exists."""


# ----------------------------------------------------------------------
# Mode
# ----------------------------------------------------------------------

def is_dev_checkout() -> bool:
    """True when running from a git checkout of this project (not a frozen
    or Briefcase-packaged app)."""
    if getattr(sys, "frozen", False):
        return False
    root = bundled_templates_dir()
    if root is None:
        return False
    repo = root.parent.parent
    return (repo / ".git").exists() and (repo / "pyproject.toml").exists()


def template_write_root() -> Tuple[Path, str]:
    """(root directory, TARGET_REPO | TARGET_USER) that saves go to."""
    override = os.environ.get(ENV_TARGET, "").strip().lower()
    bundled = bundled_templates_dir()
    if override == TARGET_REPO and bundled is not None:
        return bundled, TARGET_REPO
    if override == TARGET_USER:
        return user_templates_dir(), TARGET_USER
    if is_dev_checkout() and bundled is not None:
        return bundled, TARGET_REPO
    return user_templates_dir(), TARGET_USER


def is_dev_mode() -> bool:
    return template_write_root()[1] == TARGET_REPO


# ----------------------------------------------------------------------
# Queries
# ----------------------------------------------------------------------

def slugify(name: str) -> str:
    """Directory-safe id from a display name: "GoPro HUD" -> "gopro_hud"."""
    slug = re.sub(r"[^a-z0-9]+", "_", (name or "").strip().lower()).strip("_")
    return re.sub(r"_+", "_", slug)


def _page_entry(brand: str, computer: str, page: str, templates: Optional[Dict] = None) -> Optional[Dict[str, Any]]:
    templates = templates if templates is not None else list_templates()
    manifest = templates.get(brand, {}).get(computer)
    if not manifest:
        return None
    return next((p for p in manifest.get("pages", []) if p["id"] == page), None)


def template_origin(brand: str, computer: str, page: str) -> str:
    """"bundled" | "user" | "missing"."""
    entry = _page_entry(brand, computer, page)
    return entry.get("origin", "bundled") if entry else "missing"


def can_save_in_place(brand: str, computer: str, page: str) -> bool:
    """Save (as opposed to Save as) is allowed when the page exists and is
    either owned by the user or we are writing into the dev repo."""
    origin = template_origin(brand, computer, page)
    if origin == "missing":
        return False
    return origin == "user" or is_dev_mode()


# ----------------------------------------------------------------------
# Writing
# ----------------------------------------------------------------------

def _write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name, suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _copy_skin(source: Path, dest: Path) -> None:
    """Copy (or convert to RGBA PNG) a skin image into a page directory."""
    source, dest = Path(source), Path(dest)
    if not source.exists():
        raise TemplateStoreError(f"Skin image not found: {source}")
    if source.resolve() == dest.resolve():
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    if source.suffix.lower() == ".png":
        shutil.copyfile(source, dest)
        return
    with Image.open(source) as img:
        img.convert("RGBA").save(dest, format="PNG")


def normalized_layout(layout: Dict[str, Any]) -> Dict[str, Any]:
    """The on-disk form: skin path reduced to normal.png for image skins,
    rel_x/rel_y rounded like the hand-authored files."""
    data = copy.deepcopy(layout)
    skin = data.setdefault("hud_skin", {})
    if skin.get("type", "image") == "image":
        skin["path"] = SKIN_FILENAME
    else:
        skin.pop("path", None)
    for elem in skin.get("linked_elements", []):
        for key in ("rel_x", "rel_y"):
            if isinstance(elem.get(key), float):
                elem[key] = round(elem[key], REL_DECIMALS)
    return data


def _skin_source_from_layout(layout: Dict[str, Any]) -> Optional[Path]:
    skin = layout.get("hud_skin", {})
    if skin.get("type", "image") != "image":
        return None
    raw = skin.get("path")
    return Path(raw) if raw and Path(raw).is_absolute() else None


def save_template(ref: TemplateRef, layout: Dict[str, Any], skin_source: Optional[Path] = None) -> Path:
    """Overwrite an existing page's state file in place. `layout` may carry an
    absolute skin path (the document's resolved one, or a freshly replaced
    image) - it is copied in as normal.png when it isn't already that file.
    Raises ReadOnlyTemplateError for bundled pages in release mode."""
    if not can_save_in_place(ref.brand, ref.computer, ref.page):
        raise ReadOnlyTemplateError(
            f"{ref.label} is a built-in template and is read-only here - use Save as… to make your own copy."
        )
    state_path = resolve_template_state(ref.brand, ref.computer, ref.page, variant=ref.variant)
    if state_path is None:
        raise TemplateStoreError(f"No state file found for {ref.label}.")
    page_dir = state_path.parent
    source = Path(skin_source) if skin_source else _skin_source_from_layout(layout)
    if source is not None and layout.get("hud_skin", {}).get("type", "image") == "image":
        _copy_skin(source, page_dir / SKIN_FILENAME)
    _write_json(state_path, normalized_layout(layout))
    return state_path


def _ensure_manifest(
    root: Path, brand: str, computer: str, page_id: str, page_name: str,
    manufacturer: Optional[str], model: Optional[str], rules_profile: Optional[str] = None,
) -> Path:
    path = root / brand / computer / MANIFEST_FILENAME
    if path.exists():
        with open(path) as f:
            data = json.load(f)
    else:
        data = {
            "manufacturer": manufacturer or CUSTOM_MANUFACTURER,
            "model": model if model is not None else computer.replace("_", " ").title(),
            "pages": [],
        }
        if rules_profile:
            data["rules_profile"] = rules_profile
    pages = data.setdefault("pages", [])
    entry = next((p for p in pages if p.get("id") == page_id), None)
    if entry is None:
        pages.append({"id": page_id, "name": page_name})
    else:
        entry["name"] = page_name
    _write_json(path, data)
    return path


def save_template_as(
    layout: Dict[str, Any],
    dst: TemplateRef,
    page_name: str,
    skin_source: Optional[Path] = None,
    manufacturer: Optional[str] = None,
    model: Optional[str] = None,
    rules_profile: Optional[str] = None,
    overwrite_user: bool = True,
) -> Path:
    """Write `layout` as page `dst` under the current write root, creating the
    computer directory/manifest as needed and copying the skin PNG so the
    result is self-contained. Refuses a page id that already exists as a
    bundled page (the ownership model's one hard rule); an existing *user*
    page is overwritten when overwrite_user is True."""
    for part in (dst.brand, dst.computer, dst.page):
        if not part or slugify(part) != part:
            raise TemplateStoreError(f"Invalid template id '{part}' - use lowercase letters, digits and underscores.")
    if dst.variant and slugify(dst.variant) != dst.variant:
        raise TemplateStoreError(f"Invalid variant id '{dst.variant}'.")

    root, kind = template_write_root()
    templates = list_templates()
    existing_computer = templates.get(dst.brand, {}).get(dst.computer)
    existing_page = _page_entry(dst.brand, dst.computer, dst.page, templates)
    if existing_page is not None:
        if existing_page.get("origin") == "bundled" or kind == TARGET_REPO:
            raise TemplateExistsError(
                f"A page with id '{dst.page}' already exists under {dst.brand}/{dst.computer} - choose another name."
            )
        if not overwrite_user:
            raise TemplateExistsError(f"You already have a page '{dst.page}' under {dst.brand}/{dst.computer}.")

    if existing_computer is not None:
        manufacturer = manufacturer or existing_computer.get("manufacturer")
        model = model if model is not None else existing_computer.get("model", "")
        rules_profile = rules_profile or existing_computer.get("rules_profile")

    page_dir = root / dst.brand / dst.computer / dst.page
    if dst.variant:
        page_dir = page_dir / dst.variant
    page_dir.mkdir(parents=True, exist_ok=True)

    _ensure_manifest(root, dst.brand, dst.computer, dst.page, page_name, manufacturer, model, rules_profile)

    data = normalized_layout(layout)
    if manufacturer:
        data["manufacturer"] = manufacturer
    if model is not None:
        data["model"] = model
    if rules_profile:
        data["rules_profile"] = rules_profile

    if layout.get("hud_skin", {}).get("type", "image") == "image":
        source = Path(skin_source) if skin_source else _skin_source_from_layout(layout)
        if source is None:
            raise TemplateStoreError("The skin image path is not absolute - cannot locate the image to copy.")
        _copy_skin(source, page_dir / SKIN_FILENAME)

    state_path = page_dir / STATE_FILENAME
    _write_json(state_path, data)
    return state_path


def create_computer(brand: str, computer: str, manufacturer: str, model: str, rules_profile: Optional[str] = None) -> Path:
    """Create an (empty-page-list) computer manifest under the write root -
    used by the Custom-brand wizard before its first page is saved."""
    for part in (brand, computer):
        if not part or slugify(part) != part:
            raise TemplateStoreError(f"Invalid template id '{part}'.")
    root, _ = template_write_root()
    if list_templates().get(brand, {}).get(computer) is not None:
        raise TemplateExistsError(f"{brand}/{computer} already exists.")
    path = root / brand / computer / MANIFEST_FILENAME
    data: Dict[str, Any] = {"manufacturer": manufacturer, "model": model, "pages": []}
    if rules_profile:
        data["rules_profile"] = rules_profile
    _write_json(path, data)
    return path


def display_root(root: Path) -> str:
    """Home-contracted path for status lines."""
    try:
        home = Path.home()
        return "~/" + str(root.relative_to(home)) if root.is_relative_to(home) else str(root)
    except Exception:
        return str(root)
