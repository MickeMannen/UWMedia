"""Overlay Designer page backend - overlay_rework.md Phase 1 (renamed from
"HUD Designer" in Phase 0; originally built as qml_development.md Phase 7).
QObject exposed to uwmedia/qml/OverlayDesignerPage.qml as the
"overlayDesignerBackend" context property, plus a QQuickImageProvider for the
canvas - the same cache-busting-URL mechanism Color's own backend uses.

What changed in Phase 1 versus the read-only previewer:

- The selected template lives in an editable `OverlayDocument`
  (utils/overlay_document.py) instead of a bare layout dict - Phase 2's
  edit operations, undo/redo and Phase 3's save all go through it.
- The canvas is never blank: with nothing loaded it renders the template
  against a synthetic dive (utils/dummy_telemetry.py) scrubbed by the time
  slider, with a State selector that forces normal/safety-stop/deco/clear
  so badges and colour bands can be checked on demand. Loading a video/
  photo or a dive log stays strictly optional (decision Q2/Q12).
- Two canvas modes: "design" (the skin alone at native pixels x zoom, via
  draw_hud(render_log=True) on a checkerboard - the authoring space) and
  "frame" (the 1920x1080 composite with the template's anchor/offset, on a
  synthetic underwater backdrop or the loaded media). Design view is the
  default. The old "Overlay scale" preview slider is gone - zoom replaces
  it; the template's own hud_skin.scale becomes editable in Phase 2.
- An explicit Variant selector (single_tank/sidemount) beside the page
  cascade; auto-resolved from a loaded dive's tank count exactly as before,
  overridable by hand.

Media/log loading (EXIF-matched dive lookup, video/photo frame extraction,
preview-from-log, TZ offset, raw-waypoint window) is unchanged business
logic from the Phase 7 port, now living under a collapsed "Background &
dive logs" pane in the QML. No settings persistence, as before.

Phase 2 adds the editing layer on top: selection (element or skin),
on-canvas press/drag/release with a QML-drawn selection box (arithmetic +
PIL text measurement only - the canvas is re-rendered once on release, the
same lesson Color's own drag learned), arrow-key nudging, an inspector
(`selectedElement`/`setSelectedAttr`, `skinAttrs`/`setSkinAttr`), add/
remove/duplicate/reorder, undo/redo, and the dirty flag. Geometry lives in
utils/overlay_document.py + utils/hud_designer.py; the backend only maps
between native skin pixels and canvas display pixels.

Phase 3 adds persistence (utils/template_store.py, overlay_rework.md §5):
`save()` in place (dev repo, or a user-owned page), `saveAs()` into a new
user-owned page (same computer / another computer / a new Custom
computer), `revert()`, the write-target banner, the read-only hint on
bundled pages in release mode, a "· yours" marker on user pages in the
cascade, and `templatesChanged` (app.py wires it to Color's and Overlay
Generator's reloadTemplates()).

Phase 4 adds the Custom-brand workflow: `createCustomTemplate()` builds an
empty page from an uploaded background image (copied/converted to
normal.png, scaled to at most 40 % of the frame) or a rounded-rectangle
shape, under an existing computer (inheriting its colour/warning rules) or
a new Custom computer with a chosen `rules_profile`.

Phase 5 (polish): multi-selection (Cmd/Ctrl-click, marquee), group drag
with grid/edge snapping, align + distribute, copy/paste (also across pages),
per-element display names (`label`) and a designer-only visibility toggle,
a grid overlay, bring-to-front/send-to-back, and .zip export/import.

Headless-safe: constructible and renderable without a QApplication (the
tests rely on this), it only reads bundled template files in __init__.
"""
import copy
import json
import tempfile
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image as PILImage
from PySide6.QtCore import Property, QObject, Signal, Slot
from PySide6.QtGui import QImage
from PySide6.QtQuick import QQuickImageProvider

from gui.hud_renderer import (
    ALIGN_OPTIONS,
    SMALL_SUFFIX_DEFAULT_SCALE,
    SMALL_SUFFIX_STYLES,
    VALIGN_OPTIONS,
    badge_lines,
    draw_hud,
    resolve_element_text,
)
from metadata.exif import MetadataHandler
from models.manager import DiveManager
from parsers.garmin import GarminParser
from parsers.subsurface import SubsurfaceParser
from parsers.uddf import UDDFParser
from utils.dummy_telemetry import (
    DUMMY_DURATION_S,
    STATE_LABELS,
    STATE_OPTIONS,
    apply_state,
    build_dummy_dive,
    waypoint_at,
)
from utils.fonts import DEFAULT_FAMILY, list_families
from utils.hud_designer import (
    ANCHORS,
    MARKER_STYLES,
    available_telemetry_fields,
    element_display_name,
    element_kind,
    element_native_bounds,
    hit_test_bounds,
)
from utils.hud_rules_engine import load_rules_json, resolve_state, resolve_tank_variant
from utils.layouts import list_templates, page_display_name, resolve_template_state
from utils.overlay_document import OverlayDocument, TemplateRef
from utils.template_store import (
    CUSTOM_BRAND,
    CUSTOM_MANUFACTURER,
    SKIN_FILENAME,
    STATE_FILENAME,
    TARGET_REPO,
    TemplateStoreError,
    display_root,
    is_dev_mode,
    normalized_layout,
    save_template,
    save_template_as,
    slugify,
    template_write_root,
)

VIEW_DESIGN = "design"
VIEW_FRAME = "frame"
SOURCE_DUMMY = "dummy"
SOURCE_LOG = "log"

ZOOM_MIN = 0.25
ZOOM_MAX = 4.0
ZOOM_STEP = 0.25
MAX_RENDER_WIDTH = 4096
FRAME_W, FRAME_H = 1920, 1080
CHECKER_PX = 16
DEFAULT_VIEWPORT = (700, 440)
DUMMY_DEFAULT_SECONDS = 12 * 60  # mid-dive: on the bottom, everything populated
NUDGE_PX = 1
NUDGE_PX_FAST = 10
HIT_SLACK_DISPLAY_PX = 3.0
SNAP_TOLERANCE_PX = 4.0        # native skin px
GRID_SIZES = [4, 8, 16, 32]
DEFAULT_GRID_SIZE = 8
ZIP_META_FILENAME = "template.json"
# Qt.KeyboardModifier values (avoid importing QtCore.Qt just for these).
MOD_SHIFT = 0x02000000
MOD_CTRL = 0x04000000
MOD_META = 0x10000000

# Element attributes whose default value is expressed by *absence* in the
# JSON - the inspector deletes the key instead of writing the default, so a
# bundled template edited in the designer doesn't sprout `"align": "left"`.
_ELEMENT_ATTR_DEFAULTS = {
    "align": "left",
    "valign": "top",
    "outline": True,
    "font_weight": "regular",
    "font_family": DEFAULT_FAMILY,
}
_NUMERIC_ELEMENT_ATTRS = {"font_size", "value_font_size", "scale", "width", "height", "corner_radius", "marker_size", "small_suffix_scale", "outline_width", "outline_gap", "up_count", "down_count", "segments", "segment_gap", "full_bar"}
_INT_ELEMENT_ATTRS = {"font_size", "value_font_size", "width", "height", "corner_radius", "marker_size", "outline_width", "outline_gap", "up_count", "down_count", "segments", "segment_gap", "full_bar"}
_STYLE_DEFAULTS = {"tissue_bar": "segments", "tank_icon": "fill"}
_NUMERIC_SKIN_ATTRS = {"scale", "opacity", "ref_offset_x", "ref_offset_y", "width", "height", "corner_radius"}
_INT_SKIN_ATTRS = {"width", "height", "corner_radius"}


def _prettify(key: str) -> str:
    return key.replace("_", " ").title()


def _clamp_zoom(value: float) -> float:
    return max(ZOOM_MIN, min(ZOOM_MAX, float(value)))


class OverlayDesignerBackend(QObject):
    cascadeChanged = Signal()
    documentChanged = Signal()
    selectionChanged = Signal()
    boxesChanged = Signal()
    templatesChanged = Signal()
    persistenceChanged = Signal()
    viewChanged = Signal()
    telemetryChanged = Signal()
    timeChanged = Signal()
    dataChanged = Signal()
    statusChanged = Signal()
    tzChanged = Signal()
    logFilesChanged = Signal()
    previewChanged = Signal()
    waypointViewerChanged = Signal()

    def __init__(self):
        super().__init__()

        # --- document / template cascade ---
        self.document: Optional[OverlayDocument] = None
        self._hud_templates = list_templates()
        self._brand_choices = {_prettify(k): k for k in sorted(self._hud_templates)}
        self._computer_choices: Dict[str, str] = {}
        self._page_choices: Dict[str, str] = {}
        self._variant_choices: Dict[str, str] = {}
        self._selected_brand_key: Optional[str] = None
        self._selected_computer_key: Optional[str] = None
        self._selected_page_id: Optional[str] = None
        self._selected_variant: Optional[str] = None
        self._page_origin = ""
        self._can_save = False

        # --- editing / selection ---
        self._selected_index = -1          # primary selection (inspector target)
        self._selected_set: set = set()    # every selected element index (incl. primary)
        self._skin_selected = False
        self._drag = None
        self._marquee = None               # {"x0","y0","x1","y1"} in native px while rubber-banding
        self._clipboard: List[Dict[str, object]] = []
        self._hidden: set = set()          # designer-only, never serialized
        self._show_bounds = True
        self._show_grid = False
        self._snap = False
        self._grid_size = DEFAULT_GRID_SIZE
        self._element_boxes: List[List[float]] = []
        self._selection_box = {"visible": False, "x": 0.0, "y": 0.0, "w": 0.0, "h": 0.0, "label": ""}

        # --- canvas view ---
        self._view_mode = VIEW_DESIGN
        self._zoom = 1.0
        self._zoom_fit = True
        self._viewport_w, self._viewport_h = DEFAULT_VIEWPORT
        self._preview_revision = 0
        self._checker_cache: Optional[Tuple[Tuple[int, int], np.ndarray]] = None
        self._synthetic_bg_cache: Optional[Tuple[Tuple[int, int], np.ndarray]] = None

        # --- telemetry ---
        self._telemetry_source = SOURCE_DUMMY
        self._state_override = "auto"
        self.dummy_dive = build_dummy_dive("single_tank")

        # --- media / logs (unchanged from the Phase 7 port, renamed) ---
        self.view_w = float(FRAME_W)
        self.view_h = float(FRAME_H)
        self.bg_frame = None
        self.video_cap = None
        self.video_fps = 30.0
        self.video_creation_date = None
        self.dive_manager = DiveManager()
        self.current_dive = None
        self.current_waypoint = None
        self.preview_from_log = False
        self.log_file_choices: Dict[str, object] = {}

        self._time_value = 0
        self._time_min = 0
        self._time_max = 0
        self._time_enabled = False
        self._time_text = "00:00:00"
        self._data_text = ""
        self._log_text = "Current Log: none (dummy telemetry)"
        self._status_text = ""
        self._tz_value = 0

        self._waypoint_visible = False
        self._waypoint_json = ""

        self._enter_dummy_time_range()
        if self._brand_choices:
            self._select_brand(next(iter(self._brand_choices.keys())))

    # ==================================================================
    # Brand / computer / page / variant cascade
    # ==================================================================

    @Property(list, notify=cascadeChanged)
    def brandList(self):
        return list(self._brand_choices.keys())

    @Property(int, notify=cascadeChanged)
    def brandIndex(self):
        return self._index_of(self._brand_choices, self._selected_brand_key)

    @Property(list, notify=cascadeChanged)
    def computerList(self):
        return list(self._computer_choices.keys())

    @Property(int, notify=cascadeChanged)
    def computerIndex(self):
        return self._index_of(self._computer_choices, self._selected_computer_key)

    @Property(bool, notify=cascadeChanged)
    def computerVisible(self):
        brand = self._selected_brand_key
        computers = self._hud_templates.get(brand, {}) if brand else {}
        return len(computers) > 1

    @Property(list, notify=cascadeChanged)
    def pageList(self):
        return list(self._page_choices.keys())

    @Property(int, notify=cascadeChanged)
    def pageIndex(self):
        return self._index_of(self._page_choices, self._selected_page_id)

    @Property(list, notify=cascadeChanged)
    def variantList(self):
        return list(self._variant_choices.keys())

    @Property(int, notify=cascadeChanged)
    def variantIndex(self):
        return self._index_of(self._variant_choices, self._selected_variant)

    @Property(bool, notify=cascadeChanged)
    def variantVisible(self):
        return bool(self._variant_choices)

    @staticmethod
    def _index_of(choices: Dict[str, str], key) -> int:
        for i, value in enumerate(choices.values()):
            if value == key:
                return i
        return 0

    def _select_brand(self, brand_display_name):
        self._selected_brand_key = self._brand_choices.get(brand_display_name)
        self._refresh_computer_choices()

    @Slot(str)
    def onBrandSelected(self, brand_display_name):
        self._select_brand(brand_display_name)

    def _refresh_computer_choices(self):
        brand = self._selected_brand_key
        computers = self._hud_templates.get(brand, {}) if brand else {}
        self._computer_choices = {_prettify(k): k for k in sorted(computers)}
        self._selected_computer_key = next(iter(self._computer_choices.values()), None)
        self._refresh_page_choices()

    @Slot(str)
    def onComputerSelected(self, computer_display_name):
        self._selected_computer_key = self._computer_choices.get(computer_display_name)
        self._refresh_page_choices()

    def _manifest(self):
        brand, computer = self._selected_brand_key, self._selected_computer_key
        return self._hud_templates.get(brand, {}).get(computer) if brand and computer else None

    def _page_entry(self):
        manifest = self._manifest()
        page = self._selected_page_id
        if not manifest or not page:
            return None
        return next((p for p in manifest.get("pages", []) if p["id"] == page), None)

    def _refresh_page_choices(self):
        manifest = self._manifest()
        pages = manifest["pages"] if manifest else []
        self._page_choices = {page_display_name(page): page["id"] for page in pages}
        self._selected_page_id = next(iter(self._page_choices.values()), None)
        self._refresh_variant_choices()

    @Slot(str)
    def onPageSelected(self, page_display_name):
        self._selected_page_id = self._page_choices.get(page_display_name)
        self._refresh_variant_choices()

    def _refresh_variant_choices(self):
        """Auto-picks the variant from the loaded dive's tank count (2+ tanks
        -> sidemount, else single_tank; no dive -> single_tank), exactly the
        rule the previewer applied - the user can then override it with the
        Variant combo until the page changes."""
        page_entry = self._page_entry()
        variants = (page_entry.get("variants") or []) if page_entry else []
        self._variant_choices = {_prettify(v): v for v in variants}
        if variants:
            resolved = resolve_tank_variant(self.current_dive)
            self._selected_variant = resolved if resolved in variants else variants[0]
        else:
            self._selected_variant = None
        self.cascadeChanged.emit()
        self._load_selected_template()

    @Slot(str)
    def onVariantSelected(self, variant_display_name):
        variant = self._variant_choices.get(variant_display_name)
        if variant is None or variant == self._selected_variant:
            return
        self._selected_variant = variant
        self.cascadeChanged.emit()
        self._load_selected_template()

    def _load_selected_template(self):
        brand, computer, page, variant = (
            self._selected_brand_key, self._selected_computer_key,
            self._selected_page_id, self._selected_variant,
        )
        if self._page_entry() is None:
            self.document = None
            self._after_document_changed()
            return
        state_path = resolve_template_state(brand, computer, page, variant=variant)
        if state_path is None:
            self.document = None
            self._set_status("Template state file not found.")
            self._after_document_changed()
            return

        ref = TemplateRef(brand, computer, page, variant)
        self.document = OverlayDocument.load(state_path, ref=ref)
        self.dummy_dive = build_dummy_dive(variant)
        page_entry = self._page_entry() or {}
        self._page_origin = page_entry.get("origin", "bundled")
        self._can_save = self._page_origin == "user" or is_dev_mode()
        self._set_status(f"Loaded {ref.label}")
        self._after_document_changed()

    def _select_ref(self, ref: TemplateRef, keep_selection: bool = False):
        """Re-list the template tree and select `ref` (falling back to the
        first available entry at each level), then load it. Used after save /
        save-as / revert so new pages and computers show up in the cascade."""
        selected_index = self._selected_index
        skin_selected = self._skin_selected
        self._hud_templates = list_templates()
        self._brand_choices = {_prettify(k): k for k in sorted(self._hud_templates)}
        brand = ref.brand if ref.brand in self._hud_templates else next(iter(self._hud_templates), None)
        self._selected_brand_key = brand
        computers = self._hud_templates.get(brand, {}) if brand else {}
        self._computer_choices = {_prettify(k): k for k in sorted(computers)}
        self._selected_computer_key = ref.computer if ref.computer in computers else next(iter(self._computer_choices.values()), None)
        manifest = self._manifest()
        pages = manifest["pages"] if manifest else []
        self._page_choices = {page_display_name(page): page["id"] for page in pages}
        page_ids = list(self._page_choices.values())
        self._selected_page_id = ref.page if ref.page in page_ids else (page_ids[0] if page_ids else None)
        page_entry = self._page_entry()
        variants = (page_entry.get("variants") or []) if page_entry else []
        self._variant_choices = {_prettify(v): v for v in variants}
        if variants:
            if ref.variant in variants:
                self._selected_variant = ref.variant
            else:
                resolved = resolve_tank_variant(self.current_dive)
                self._selected_variant = resolved if resolved in variants else variants[0]
        else:
            self._selected_variant = None
        self.cascadeChanged.emit()
        self._load_selected_template()
        if keep_selection and self.document is not None:
            self._set_primary(min(selected_index, len(self.document.elements) - 1))
            self._skin_selected = skin_selected and self._selected_index < 0
            self.selectionChanged.emit()
            self._update_boxes()

    # ==================================================================
    # Persistence (Phase 3) - see utils/template_store.py
    # ==================================================================

    @Property(bool, notify=persistenceChanged)
    def isDevMode(self):
        return is_dev_mode()

    @Property(str, notify=persistenceChanged)
    def writeTargetText(self):
        root, kind = template_write_root()
        if kind == TARGET_REPO:
            return f"Dev mode - saving into the repo: {display_root(root)}"
        return f"Your templates are saved to {display_root(root)}"

    @Property(str, notify=documentChanged)
    def pageOrigin(self):
        return self._page_origin if self.document is not None else ""

    @Property(bool, notify=documentChanged)
    def canSave(self):
        return self.document is not None and self._can_save

    @Property(str, notify=documentChanged)
    def readOnlyHint(self):
        if self.document is None or self._can_save:
            return ""
        return "Built-in template - read-only here. Use Save as… to make your own copy."

    @Property(list, notify=cascadeChanged)
    def saveAsTargets(self):
        """[{label, brand, computer}] - every existing computer plus the
        'new Custom computer' entry (computer == "")."""
        targets = []
        for brand in sorted(self._hud_templates):
            for computer, manifest in sorted(self._hud_templates[brand].items()):
                label = f"{manifest.get('manufacturer') or _prettify(brand)} · {manifest.get('model') or _prettify(computer)}".strip(" ·")
                targets.append({"label": label, "brand": brand, "computer": computer})
        targets.append({"label": "New Custom computer…", "brand": CUSTOM_BRAND, "computer": ""})
        return targets

    @Property(int, notify=cascadeChanged)
    def saveAsCurrentTargetIndex(self):
        for i, target in enumerate(self.saveAsTargets):
            if target["brand"] == self._selected_brand_key and target["computer"] == self._selected_computer_key:
                return i
        return 0

    @Slot(str, result=str)
    def slugFor(self, name):
        return slugify(name)

    @Slot(result=bool)
    def save(self):
        doc = self.document
        if doc is None or doc.ref is None:
            return False
        if not self._can_save:
            self._set_status(self.readOnlyHint)
            return False
        try:
            path = save_template(doc.ref, doc.render_layout())
        except TemplateStoreError as e:
            self._set_status(str(e))
            return False
        except OSError as e:
            self._set_status(f"Could not save: {e}")
            return False
        ref = doc.ref
        self._select_ref(ref, keep_selection=True)
        self._set_status(f"Saved {ref.label} → {display_root(path)}")
        self.templatesChanged.emit()
        return True

    @Slot(int, str, str, result=str)
    def saveAs(self, target_index, new_computer_name, page_name):
        """Returns "" on success, else a user-facing error message."""
        doc = self.document
        if doc is None:
            return "Nothing to save."
        targets = self.saveAsTargets
        if not 0 <= int(target_index) < len(targets):
            return "Pick where to save the page."
        target = targets[int(target_index)]
        page_name = (page_name or "").strip()
        page_id = slugify(page_name)
        if not page_id:
            return "Enter a page name."
        manufacturer = model = None
        if target["computer"]:
            brand, computer = target["brand"], target["computer"]
        else:
            new_computer_name = (new_computer_name or "").strip()
            computer = slugify(new_computer_name)
            if not computer:
                return "Enter a name for the new computer."
            brand = CUSTOM_BRAND
            manufacturer, model = CUSTOM_MANUFACTURER, new_computer_name
        dst = TemplateRef(brand, computer, page_id, None)
        try:
            path = save_template_as(
                doc.render_layout(), dst, page_name,
                manufacturer=manufacturer, model=model, overwrite_user=False,
            )
        except TemplateStoreError as e:
            return str(e)
        except OSError as e:
            return f"Could not save: {e}"
        self._select_ref(dst, keep_selection=True)
        self._set_status(f"Saved as {dst.label} → {display_root(path)}")
        self.templatesChanged.emit()
        return ""

    @Slot()
    def revert(self):
        doc = self.document
        if doc is None or doc.ref is None:
            return
        ref = doc.ref
        self._select_ref(ref, keep_selection=True)
        self._set_status(f"Reverted {ref.label} to the saved file")

    def _after_document_changed(self):
        if self.document is None:
            self._page_origin = ""
            self._can_save = False
        self._selected_index = -1
        self._selected_set = set()
        self._skin_selected = False
        self._drag = None
        self._marquee = None
        self._hidden = set()
        self._zoom_fit = True
        self._apply_fit_zoom()
        self.documentChanged.emit()
        self.selectionChanged.emit()
        self.viewChanged.emit()
        self._update_data_text()
        self._redraw()

    def _after_edit(self):
        """After any document mutation: refresh everything derived from it."""
        self.documentChanged.emit()
        self.selectionChanged.emit()
        self._update_boxes()
        self._redraw()

    def _after_geometry_edit(self):
        """After a mutation that changes the skin's native size (replace
        image, undo/redo across such a change): Fit zoom may need to move."""
        if self._zoom_fit:
            self._apply_fit_zoom()
        self.viewChanged.emit()
        self._after_edit()

    # ------------------------------------------------------------------
    # Document summary for the right-hand column (read-only in Phase 1)
    # ------------------------------------------------------------------

    @Property(bool, notify=documentChanged)
    def hasDocument(self):
        return self.document is not None

    @Property(str, notify=documentChanged)
    def templateTitle(self):
        doc = self.document
        if doc is None:
            return "No template selected"
        page_entry = self._page_entry() or {}
        parts = [f"{doc.manufacturer} {doc.model}".strip(), page_entry.get("name", doc.ref.page if doc.ref else "")]
        if doc.ref and doc.ref.variant:
            parts.append(_prettify(doc.ref.variant))
        return " · ".join(p for p in parts if p)

    @Property(str, notify=documentChanged)
    def skinInfoText(self):
        doc = self.document
        if doc is None:
            return ""
        skin = doc.skin
        nw, nh = doc.skin_native_size()
        if doc.skin_type == "shape":
            base = f"Shape {nw:.0f}×{nh:.0f} px · {skin.get('color', '#000000')} · opacity {skin.get('opacity', 1.0):.2f}"
        else:
            base = f"Image {nw:.0f}×{nh:.0f} px · scale {skin.get('scale', 1.0):.2f} · opacity {skin.get('opacity', 1.0):.2f}"
        anchor = _prettify(str(skin.get("anchor", "TOP_LEFT")))
        return f"{base}\nAnchor {anchor} · offset {skin.get('ref_offset_x', 0):.0f}, {skin.get('ref_offset_y', 0):.0f}"

    @staticmethod
    def _element_label(elem) -> str:
        name = (elem.get("label") or "").strip()
        if name:
            return name
        field = elem.get("field", "")
        if field.startswith("custom:"):
            # Multi-line custom labels (e.g. Garmin's vertical "N\nD\nL") stay one row.
            return "“" + field[len("custom:"):].replace("\n", "⏎") + "”"
        return field

    @Property(list, notify=documentChanged)
    def elementList(self):
        doc = self.document
        if doc is None:
            return []
        return [f"{self._element_label(e)}  ({element_kind(e)})" for e in doc.elements]

    @Property(list, notify=documentChanged)
    def elements(self):
        """Rows for the QML element list: [{index, field, kind, label}]."""
        doc = self.document
        if doc is None:
            return []
        return [
            {
                "index": i, "field": e.get("field", ""), "kind": element_kind(e),
                "label": self._element_label(e), "hidden": i in self._hidden,
            }
            for i, e in enumerate(doc.elements)
        ]

    # ==================================================================
    # Selection + inspector (Phase 2)
    # ==================================================================

    def _set_primary(self, index: int):
        """Single-select `index` (or clear with -1)."""
        self._selected_index = index
        self._selected_set = {index} if index >= 0 else set()

    def _selection(self) -> List[int]:
        doc = self.document
        n = len(doc.elements) if doc is not None else 0
        return sorted(i for i in self._selected_set if 0 <= i < n)

    def _sanitize_selection(self):
        doc = self.document
        n = len(doc.elements) if doc is not None else 0
        self._selected_set = {i for i in self._selected_set if 0 <= i < n}
        if self._selected_index >= n or self._selected_index not in self._selected_set:
            self._selected_index = max(self._selected_set) if self._selected_set else -1
        self._hidden = {i for i in self._hidden if 0 <= i < n}

    @Property(int, notify=selectionChanged)
    def selectedIndex(self):
        return self._selected_index

    @Property(list, notify=selectionChanged)
    def selectedIndices(self):
        return self._selection()

    @Property(int, notify=selectionChanged)
    def selectionCount(self):
        return len(self._selection())

    @Property(bool, notify=selectionChanged)
    def skinSelected(self):
        return self._skin_selected

    @Property(bool, notify=selectionChanged)
    def hasSelection(self):
        return self._skin_selected or self._selected_index >= 0

    @Slot(int)
    def selectElement(self, index):
        doc = self.document
        if doc is None or doc.element(index) is None:
            return
        self._set_primary(index)
        self._skin_selected = False
        self.selectionChanged.emit()
        self._update_boxes()

    @Slot(int)
    def toggleElement(self, index):
        """Cmd/Ctrl-click: add to / remove from the selection."""
        doc = self.document
        if doc is None or doc.element(index) is None:
            return
        self._skin_selected = False
        if index in self._selected_set:
            self._selected_set.discard(index)
            if self._selected_index == index:
                self._selected_index = max(self._selected_set) if self._selected_set else -1
        else:
            self._selected_set.add(index)
            self._selected_index = index
        self.selectionChanged.emit()
        self._update_boxes()

    @Slot()
    def selectAll(self):
        doc = self.document
        if doc is None or not doc.elements:
            return
        self._selected_set = set(range(len(doc.elements)))
        self._selected_index = len(doc.elements) - 1
        self._skin_selected = False
        self.selectionChanged.emit()
        self._update_boxes()

    @Slot()
    def selectSkin(self):
        if self.document is None:
            return
        self._set_primary(-1)
        self._skin_selected = True
        self.selectionChanged.emit()
        self._update_boxes()

    @Slot()
    def clearSelection(self):
        if self._selected_index < 0 and not self._selected_set and not self._skin_selected:
            return
        self._set_primary(-1)
        self._skin_selected = False
        self.selectionChanged.emit()
        self._update_boxes()

    # -- visibility (designer-only) -------------------------------------

    @Property(list, notify=documentChanged)
    def hiddenIndices(self):
        return sorted(self._hidden)

    @Slot(int)
    def toggleHidden(self, index):
        doc = self.document
        if doc is None or doc.element(index) is None:
            return
        if index in self._hidden:
            self._hidden.discard(index)
        else:
            self._hidden.add(index)
        self.documentChanged.emit()
        self._update_boxes()
        self._redraw()

    @Slot()
    def showAllElements(self):
        if not self._hidden:
            return
        self._hidden = set()
        self.documentChanged.emit()
        self._update_boxes()
        self._redraw()

    def _visible_layout(self, layout: Dict[str, object]) -> Dict[str, object]:
        if not self._hidden:
            return layout
        skin = layout.setdefault("hud_skin", {})
        skin["linked_elements"] = [e for i, e in enumerate(skin.get("linked_elements", [])) if i not in self._hidden]
        return layout

    @Property("QVariant", notify=selectionChanged)
    def selectedElement(self):
        """Everything the inspector shows for the selected element, with
        every key present (QML never sees undefined) and positions in native
        skin pixels."""
        doc = self.document
        elem = doc.element(self._selected_index) if doc is not None else None
        if elem is None:
            # Fully populated defaults so QML bindings never see undefined.
            return {
                "index": -1, "kind": "", "field": "", "is_custom": False, "custom_text": "",
                "x_px": 0, "y_px": 0, "font_size": 16, "value_font_size": 16, "scale": 1.0,
                "color": "#FFFFFF", "align": "left", "valign": "top", "font_family": DEFAULT_FAMILY,
                "bold": False, "outline": True, "width": 0, "height": 0, "corner_radius": 0,
                "marker_style": "dot", "marker_size": 6, "ceiling_color": "#808080", "label": "",
                "small_suffix": "", "small_suffix_scale": SMALL_SUFFIX_DEFAULT_SCALE,
                "draw_outline": False, "outline_color": "#FFFFFF", "outline_width": 2, "outline_gap": 4,
                "up_count": 4, "down_count": 1, "style": "segments",
                "segments": 5, "segment_gap": 2, "full_bar": 200,
            }
        x_px, y_px = doc.element_position_px(self._selected_index)
        field = elem.get("field", "")
        return {
            "index": self._selected_index,
            "kind": element_kind(elem),
            "field": field,
            "is_custom": field.startswith("custom:"),
            "custom_text": field[len("custom:"):] if field.startswith("custom:") else "",
            "x_px": round(x_px, 1),
            "y_px": round(y_px, 1),
            "font_size": elem.get("font_size", 16),
            "value_font_size": elem.get("value_font_size", elem.get("font_size", 16)),
            "scale": elem.get("scale", 1.0),
            "color": elem.get("color", "#FFFFFF"),
            "align": elem.get("align", "left"),
            "valign": elem.get("valign", "top"),
            "font_family": elem.get("font_family") or DEFAULT_FAMILY,
            "bold": (elem.get("font_weight") or "regular") == "bold",
            "outline": bool(elem.get("outline", True)),
            "width": elem.get("width", 0),
            "height": elem.get("height", 0),
            "corner_radius": elem.get("corner_radius", 0),
            "marker_style": elem.get("marker_style", "dot"),
            "marker_size": elem.get("marker_size", 6),
            "ceiling_color": elem.get("ceiling_color", "#808080"),
            "label": elem.get("label", ""),
            "small_suffix": elem.get("small_suffix") or "",
            "small_suffix_scale": elem.get("small_suffix_scale", SMALL_SUFFIX_DEFAULT_SCALE),
            "draw_outline": bool(elem.get("draw_outline", False)),
            "outline_color": elem.get("outline_color", "#FFFFFF"),
            "outline_width": elem.get("outline_width", 2),
            "outline_gap": elem.get("outline_gap", 4),
            "up_count": elem.get("up_count", 4),
            "down_count": elem.get("down_count", 1),
            "style": elem.get("style") or _STYLE_DEFAULTS.get(element_kind(elem), "segments"),
            "segments": elem.get("segments", 5),
            "segment_gap": elem.get("segment_gap", 2),
            "full_bar": elem.get("full_bar", 200),
        }

    @Slot(str, "QVariant")
    def setSelectedAttr(self, key, value):
        """Inspector edits. Numeric fields arrive as strings from TextFields
        and are parsed here; defaults are stored as key *absence*."""
        doc = self.document
        index = self._selected_index
        if doc is None or doc.element(index) is None:
            return
        if key in ("x_px", "y_px"):
            try:
                number = float(value)
            except (TypeError, ValueError):
                self.selectionChanged.emit()
                return
            x, y = doc.element_position_px(index)
            doc.set_element_position_px(index, number if key == "x_px" else x, number if key == "y_px" else y)
        elif key == "custom_text":
            doc.set_element_attr(index, "field", "custom:" + str(value))
        elif key == "bold":
            doc.set_element_attr(index, "font_weight", "bold" if bool(value) else None)
        elif key == "font_family":
            doc.set_element_attr(index, "font_family", None if value in (None, "", DEFAULT_FAMILY) else str(value))
        elif key in ("align", "valign", "outline"):
            if key == "outline":
                value = bool(value)
            elif key == "align" and value not in ALIGN_OPTIONS or key == "valign" and value not in VALIGN_OPTIONS:
                return
            doc.set_element_attr(index, key, None if value == _ELEMENT_ATTR_DEFAULTS[key] else value)
        elif key in _NUMERIC_ELEMENT_ATTRS:
            try:
                number = float(value)
            except (TypeError, ValueError):
                self.selectionChanged.emit()
                return
            if key in _INT_ELEMENT_ATTRS:
                number = int(round(number))
            if key in ("font_size", "value_font_size", "width", "height", "marker_size", "outline_width"):
                number = max(1, number)
            elif key in ("outline_gap", "up_count", "down_count", "segment_gap"):
                number = max(0, number)
            elif key in ("segments", "full_bar"):
                number = max(1, number)
            elif key == "scale":
                number = max(0.05, number)
            elif key == "small_suffix_scale":
                number = max(0.1, min(1.0, round(number, 3)))
            doc.set_element_attr(index, key, number)
        elif key in ("field", "color", "ceiling_color", "marker_style", "outline_color"):
            if key == "marker_style" and value not in MARKER_STYLES:
                return
            doc.set_element_attr(index, key, str(value))
        elif key == "draw_outline":
            doc.set_element_attr(index, "draw_outline", True if bool(value) else None)
        elif key == "style":
            if value not in ("segments", "fill"):
                return
            default = _STYLE_DEFAULTS.get(element_kind(doc.element(index)), "segments")
            doc.set_element_attr(index, "style", None if value == default else value)
        elif key == "label":
            text = str(value or "").strip()
            doc.set_element_attr(index, "label", text or None)
        elif key == "small_suffix":
            style = str(value or "")
            if style and style not in SMALL_SUFFIX_STYLES:
                return
            doc.set_element_attr(index, "small_suffix", style or None)
        else:
            return
        self._after_edit()

    @Property("QVariant", notify=documentChanged)
    def skinAttrs(self):
        doc = self.document
        if doc is None:
            return {"type": ""}
        skin = doc.skin
        nw, nh = doc.skin_native_size()
        return {
            "type": doc.skin_type,
            "native_width": nw,
            "native_height": nh,
            "path": str(doc.skin_abs_path or ""),
            "scale": skin.get("scale", 1.0),
            "opacity": skin.get("opacity", 1.0),
            "anchor": skin.get("anchor", "TOP_LEFT"),
            "anchor_index": ANCHORS.index(skin.get("anchor", "TOP_LEFT")) if skin.get("anchor", "TOP_LEFT") in ANCHORS else 0,
            "ref_offset_x": skin.get("ref_offset_x", 0.0),
            "ref_offset_y": skin.get("ref_offset_y", 0.0),
            "width": skin.get("width", 400),
            "height": skin.get("height", 200),
            "color": skin.get("color", "#000000"),
            "corner_radius": skin.get("corner_radius", 20),
        }

    @Slot(str, "QVariant")
    def setSkinAttr(self, key, value):
        doc = self.document
        if doc is None:
            return
        if key == "anchor":
            anchor = self._anchor_choices.get(str(value), value)
            if anchor not in ANCHORS:
                return
            doc.set_skin_attr("anchor", anchor)
        elif key in _NUMERIC_SKIN_ATTRS:
            try:
                number = float(value)
            except (TypeError, ValueError):
                self.documentChanged.emit()
                return
            if key in _INT_SKIN_ATTRS:
                number = int(round(number))
            if key == "scale":
                number = max(0.05, number)
            elif key == "opacity":
                number = max(0.0, min(1.0, number))
            elif key in ("width", "height"):
                number = max(1, number)
            doc.set_skin_attr(key, number)
        elif key == "color":
            doc.set_skin_attr("color", str(value))
        else:
            return
        if key in ("scale", "width", "height"):
            self._after_geometry_edit()
        else:
            self._after_edit()

    @Slot()
    def replaceSkinImage(self):
        from PySide6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getOpenFileName(None, "Select skin image", "", "Images (*.png *.jpg *.jpeg *.webp *.bmp)")
        if path:
            self._replace_skin_image_from_path(Path(path))

    def _replace_skin_image_from_path(self, path: Path) -> bool:
        doc = self.document
        if doc is None:
            return False
        old_w, old_h = doc.skin_native_size()
        if not doc.set_skin_image(path):
            self._set_status(f"Could not read image: {path}")
            return False
        new_w, new_h = doc.skin_native_size()
        message = f"Skin image replaced: {Path(path).name} (copied next to the template on Save)"
        if old_w and old_h and new_w and new_h and abs((old_w / old_h) - (new_w / new_h)) > 0.02:
            message += (
                f" - aspect ratio changed ({old_w:.0f}×{old_h:.0f} → {new_w:.0f}×{new_h:.0f}); "
                "element positions are proportional, so check their placement."
            )
        self._set_status(message)
        self._after_geometry_edit()
        return True

    # ==================================================================
    # Custom-brand workflow (Phase 4)
    # ==================================================================

    @Property(list, constant=True)
    def rulesProfiles(self):
        """Colour/warning rule sets a new Custom computer can borrow:
        "Default" plus every manufacturer block in hud_rules.json."""
        return ["Default"] + [key for key in load_rules_json() if key != "default"]

    @Slot(result=str)
    def browseImageFile(self):
        from PySide6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getOpenFileName(
            None, "Select background image", "", "Images (*.png *.jpg *.jpeg *.webp *.bmp)"
        )
        return path or ""

    @Slot(int, str, str, str, str, str, float, float, str, result=str)
    def createCustomTemplate(self, target_index, new_computer_name, page_name, background_kind,
                             image_path, rules_profile, shape_width, shape_height, shape_color):
        """Returns "" on success, else a user-facing error message. `target_index`
        indexes saveAsTargets (an existing computer, or the trailing "new
        Custom computer" entry)."""
        targets = self.saveAsTargets
        if not 0 <= int(target_index) < len(targets):
            return "Pick where to create the page."
        target = targets[int(target_index)]
        page_name = (page_name or "").strip()
        page_id = slugify(page_name)
        if not page_id:
            return "Enter a page name."

        manufacturer = model = profile = None
        if target["computer"]:
            brand, computer = target["brand"], target["computer"]
        else:
            new_computer_name = (new_computer_name or "").strip()
            computer = slugify(new_computer_name)
            if not computer:
                return "Enter a name for the new computer."
            brand = CUSTOM_BRAND
            manufacturer, model = CUSTOM_MANUFACTURER, new_computer_name
            if rules_profile and rules_profile.strip().lower() != "default":
                profile = rules_profile.strip()

        skin: Dict[str, object] = {
            "anchor": "BOTTOM_LEFT", "ref_offset_x": 16.0, "ref_offset_y": -16.0,
            "opacity": 1.0, "linked_elements": [],
        }
        skin_source = None
        if background_kind == "image":
            source = Path(image_path) if image_path else None
            if source is None or not source.exists():
                return "Pick a background image."
            try:
                with PILImage.open(source) as img:
                    width, height = img.size
            except Exception:
                return f"Could not read image: {source.name}"
            # Default size: the skin fills at most 40 % of the frame either way.
            scale = min(1.0, 0.4 * FRAME_H / height, 0.4 * FRAME_W / width)
            skin.update({"type": "image", "path": str(source.resolve()), "scale": round(scale, 3)})
            skin_source = source
        elif background_kind == "shape":
            try:
                width = max(1, int(round(float(shape_width))))
                height = max(1, int(round(float(shape_height))))
            except (TypeError, ValueError):
                return "Enter a width and height for the shape."
            color = shape_color if isinstance(shape_color, str) and len(shape_color) == 7 and shape_color.startswith("#") else "#000000"
            skin.update({"type": "shape", "width": width, "height": height, "color": color,
                         "corner_radius": 20, "opacity": 0.6})
        else:
            return "Pick a background type."

        layout = {
            "manufacturer": manufacturer or "",
            "model": model or "",
            "hud_skin": skin,
            "design_width": FRAME_W,
            "design_height": FRAME_H,
        }
        dst = TemplateRef(brand, computer, page_id, None)
        try:
            path = save_template_as(
                layout, dst, page_name, skin_source=skin_source,
                manufacturer=manufacturer, model=model, rules_profile=profile, overwrite_user=False,
            )
        except TemplateStoreError as e:
            return str(e)
        except OSError as e:
            return f"Could not create the template: {e}"
        self._select_ref(dst)
        self._set_status(f"Created {dst.label} → {display_root(path)} - add elements with + Add")
        self.templatesChanged.emit()
        return ""

    # -- option lists for the inspector ---------------------------------

    @Property(list, notify=telemetryChanged)
    def availableFields(self):
        dive = self.current_dive if (self._telemetry_source == SOURCE_LOG and self.current_dive is not None) else self.dummy_dive
        fields = [f for f in available_telemetry_fields(dive) if f not in ("timestamp", "dive_alerts")]
        for extra in ("ndl_before_clear", "depth_graph", "state_badge"):
            if extra not in fields:
                fields.append(extra)
        return fields

    @Property(list, constant=True)
    def fontFamilies(self):
        return list_families()

    @Property(list, constant=True)
    def anchorList(self):
        return list(self._anchor_choices.keys())

    @property
    def _anchor_choices(self) -> Dict[str, str]:
        return {_prettify(a): a for a in ANCHORS}

    @Property(list, constant=True)
    def markerStyles(self):
        return list(MARKER_STYLES)

    @Property(list, constant=True)
    def smallSuffixStyles(self):
        """["", "seconds", "decimals"] - index-aligned with smallSuffixLabels."""
        return [""] + list(SMALL_SUFFIX_STYLES)

    @Property(list, constant=True)
    def smallSuffixLabels(self):
        return ["None", "Seconds (MM:SS)", "Decimals (x.y)"]

    # -- structural edits ----------------------------------------------

    @Slot(str, str)
    def addElement(self, field, kind):
        doc = self.document
        if doc is None or not field:
            return
        if kind not in ("text", "badge", "tank_icon", "graph", "tissue_bar", "ascent_chevrons"):
            kind = "text"
        if kind == "graph":
            field = "depth_graph"
        elif kind == "badge":
            field = "state_badge"
        elif kind == "tissue_bar":
            field = "n2_tissue_load"
        elif kind == "ascent_chevrons":
            field = "ascent_rate"
        index = doc.add_element(field, kind)
        self._hidden = set()
        self._set_primary(index)
        self._skin_selected = False
        self._after_edit()

    @Slot(str)
    def addCustomLabel(self, text):
        text = (text or "").strip()
        if not text:
            return
        self.addElement("custom:" + text, "text")

    @Slot()
    def removeSelected(self):
        doc = self.document
        selection = self._selection()
        if doc is None or not selection:
            return
        doc.push_undo()
        for index in reversed(selection):
            del doc.elements[index]
        self._hidden = set()
        self._set_primary(min(selection[0], len(doc.elements) - 1))
        self._after_edit()

    @Slot()
    def duplicateSelected(self):
        doc = self.document
        selection = self._selection()
        if doc is None or not selection:
            return
        doc.push_undo()
        clones = []
        for index in selection:
            clone = copy.deepcopy(doc.elements[index])
            clone["rel_x"] = min(1.5, float(clone.get("rel_x", 0.0)) + 0.02)
            clone["rel_y"] = min(1.5, float(clone.get("rel_y", 0.0)) + 0.02)
            clones.append(clone)
        start = len(doc.elements)
        doc.elements.extend(clones)
        self._hidden = set()
        self._selected_set = set(range(start, start + len(clones)))
        self._selected_index = start + len(clones) - 1
        self._after_edit()

    @Slot(int)
    def moveSelectedLayer(self, delta):
        doc = self.document
        if doc is None or doc.element(self._selected_index) is None:
            return
        new_index = doc.reorder_element(self._selected_index, int(delta))
        self._hidden = set()
        self._set_primary(new_index)
        self._after_edit()

    @Slot()
    def bringToFront(self):
        doc = self.document
        if doc is not None:
            self.moveSelectedLayer(len(doc.elements))

    @Slot()
    def sendToBack(self):
        doc = self.document
        if doc is not None:
            self.moveSelectedLayer(-len(doc.elements))

    @Slot(int, int)
    def nudgeSelected(self, dx, dy):
        doc = self.document
        if doc is None:
            return
        selection = self._selection()
        if selection:
            doc.push_undo()
            native_w, native_h = doc.skin_native_size()
            if native_w <= 0 or native_h <= 0:
                return
            for index in selection:
                elem = doc.elements[index]
                doc.move_element(
                    index,
                    float(elem.get("rel_x", 0.0)) + dx / native_w,
                    float(elem.get("rel_y", 0.0)) + dy / native_h,
                    record_undo=False,
                )
        elif self._skin_selected and self._view_mode == VIEW_FRAME:
            x, y, _, _ = doc.frame_box(self.view_w, self.view_h)
            doc.set_frame_position(x + dx, y + dy, self.view_w, self.view_h)
        else:
            return
        self._after_edit()

    # -- align / distribute (Phase 5) -----------------------------------

    @Slot(str)
    def alignSelected(self, mode):
        """mode: left|hcenter|right|top|vcenter|bottom - aligns the selected
        elements' rendered bounds to the *primary* (last-clicked) element,
        which stays put - the usual "align to key object" convention. (Falls
        back to the selection's outer edge if there is no primary.)"""
        doc = self.document
        selection = self._selection()
        if doc is None or len(selection) < 2:
            return
        bounds = self._all_native_bounds()
        boxes = {i: bounds[i] for i in selection}
        native_w, native_h = doc.skin_native_size()
        if native_w <= 0 or native_h <= 0:
            return
        anchor = boxes.get(self._selected_index)

        def edge(lo, hi, pick):
            if anchor is not None:
                return anchor[lo] if pick == "lo" else anchor[hi] if pick == "hi" else (anchor[lo] + anchor[hi]) / 2.0
            values_lo = [b[lo] for b in boxes.values()]
            values_hi = [b[hi] for b in boxes.values()]
            return min(values_lo) if pick == "lo" else max(values_hi) if pick == "hi" else (min(values_lo) + max(values_hi)) / 2.0

        if mode == "left":
            target = edge(0, 2, "lo")
            deltas = {i: (target - b[0], 0.0) for i, b in boxes.items()}
        elif mode == "right":
            target = edge(0, 2, "hi")
            deltas = {i: (target - b[2], 0.0) for i, b in boxes.items()}
        elif mode == "hcenter":
            target = edge(0, 2, "mid")
            deltas = {i: (target - (b[0] + b[2]) / 2.0, 0.0) for i, b in boxes.items()}
        elif mode == "top":
            target = edge(1, 3, "lo")
            deltas = {i: (0.0, target - b[1]) for i, b in boxes.items()}
        elif mode == "bottom":
            target = edge(1, 3, "hi")
            deltas = {i: (0.0, target - b[3]) for i, b in boxes.items()}
        elif mode == "vcenter":
            target = edge(1, 3, "mid")
            deltas = {i: (0.0, target - (b[1] + b[3]) / 2.0) for i, b in boxes.items()}
        else:
            return
        self._apply_deltas(deltas)

    @Slot(int)
    def resizeSelected(self, steps):
        """Quick size change for every selected element: each step is ~5 %.
        Text/badge -> font sizes; tank icon / graph -> width and height."""
        doc = self.document
        selection = self._selection()
        if doc is None or not selection or not steps:
            return
        factor = 1.05 ** int(steps)
        doc.push_undo()
        for index in selection:
            elem = doc.elements[index]
            kind = element_kind(elem)
            if kind in ("tank_icon", "graph", "tissue_bar", "ascent_chevrons"):
                defaults = {"tank_icon": (20, 30), "graph": (300, 150), "tissue_bar": (12, 33), "ascent_chevrons": (16, 47)}[kind]
                for key, default in (("width", defaults[0]), ("height", defaults[1])):
                    current = float(elem.get(key, default))
                    grown = current * factor
                    # guarantee visible movement even for tiny icons
                    if abs(grown - current) < 1.0:
                        grown = current + (1.0 if steps > 0 else -1.0)
                    elem[key] = max(1, int(round(grown)))
            else:
                for key in ("font_size", "value_font_size"):
                    if key in elem or key == "font_size":
                        current = float(elem.get(key, 16))
                        grown = current * factor
                        if abs(grown - current) < 1.0:
                            grown = current + (1.0 if steps > 0 else -1.0)
                        elem[key] = max(1, int(round(grown)))
        self._after_edit()

    @Slot(str)
    def distributeSelected(self, axis):
        """axis: h|v - even gaps between the selected elements' bounds."""
        doc = self.document
        selection = self._selection()
        if doc is None or len(selection) < 3:
            return
        bounds = self._all_native_bounds()
        lo, hi = (0, 2) if axis == "h" else (1, 3)
        ordered = sorted(selection, key=lambda i: bounds[i][lo])
        first, last = bounds[ordered[0]], bounds[ordered[-1]]
        total_span = last[hi] - first[lo]
        total_size = sum(bounds[i][hi] - bounds[i][lo] for i in ordered)
        gap = (total_span - total_size) / (len(ordered) - 1)
        deltas = {}
        cursor = first[lo]
        for i in ordered:
            size = bounds[i][hi] - bounds[i][lo]
            delta = cursor - bounds[i][lo]
            deltas[i] = (delta, 0.0) if axis == "h" else (0.0, delta)
            cursor += size + gap
        self._apply_deltas(deltas)

    def _apply_deltas(self, deltas: Dict[int, Tuple[float, float]]):
        doc = self.document
        native_w, native_h = doc.skin_native_size()
        if not any(abs(dx) > 1e-6 or abs(dy) > 1e-6 for dx, dy in deltas.values()):
            return
        doc.push_undo()
        for index, (dx, dy) in deltas.items():
            elem = doc.elements[index]
            doc.move_element(
                index,
                float(elem.get("rel_x", 0.0)) + dx / native_w,
                float(elem.get("rel_y", 0.0)) + dy / native_h,
                record_undo=False,
            )
        self._after_edit()

    # -- clipboard (Phase 5) - lives on the backend, so it works across pages

    @Property(bool, notify=selectionChanged)
    def canPaste(self):
        return bool(self._clipboard)

    @Slot()
    def copySelected(self):
        doc = self.document
        selection = self._selection()
        if doc is None or not selection:
            return
        self._clipboard = [copy.deepcopy(doc.elements[i]) for i in selection]
        self.selectionChanged.emit()

    @Slot()
    def cutSelected(self):
        self.copySelected()
        self.removeSelected()

    @Slot()
    def paste(self):
        doc = self.document
        if doc is None or not self._clipboard:
            return
        doc.push_undo()
        start = len(doc.elements)
        for elem in self._clipboard:
            clone = copy.deepcopy(elem)
            clone["rel_x"] = min(1.5, float(clone.get("rel_x", 0.0)) + 0.02)
            clone["rel_y"] = min(1.5, float(clone.get("rel_y", 0.0)) + 0.02)
            doc.elements.append(clone)
        self._hidden = set()
        self._selected_set = set(range(start, len(doc.elements)))
        self._selected_index = len(doc.elements) - 1
        self._skin_selected = False
        self._after_edit()

    @Property(bool, notify=documentChanged)
    def canUndo(self):
        return self.document is not None and self.document.can_undo

    @Property(bool, notify=documentChanged)
    def canRedo(self):
        return self.document is not None and self.document.can_redo

    @Property(bool, notify=documentChanged)
    def isDirty(self):
        return self.document is not None and self.document.dirty

    @Slot()
    def undo(self):
        doc = self.document
        if doc is None or not doc.undo():
            return
        self._hidden = set()
        self._sanitize_selection()
        self._after_geometry_edit()

    @Slot()
    def redo(self):
        doc = self.document
        if doc is None or not doc.redo():
            return
        self._hidden = set()
        self._sanitize_selection()
        self._after_geometry_edit()

    # ==================================================================
    # Canvas geometry: native skin px <-> canvas display px
    # ==================================================================

    def _skin_display_transform(self) -> Tuple[float, float, float]:
        """(offset_x, offset_y, k): display = offset + native * k."""
        doc = self.document
        zoom = self._zoom
        if doc is None:
            return 0.0, 0.0, zoom
        if self._view_mode == VIEW_DESIGN:
            return 0.0, 0.0, zoom
        sx, sy, w_hud, _ = doc.frame_box(self.view_w, self.view_h)
        native_w, _ = doc.skin_native_size()
        k = (w_hud / native_w) if native_w else 1.0
        return sx * zoom, sy * zoom, k * zoom

    def _display_to_native(self, x: float, y: float) -> Tuple[float, float]:
        ox, oy, k = self._skin_display_transform()
        if k == 0:
            return 0.0, 0.0
        return (x - ox) / k, (y - oy) / k

    def _native_bounds_to_display(self, bounds) -> List[float]:
        ox, oy, k = self._skin_display_transform()
        x0, y0, x1, y1 = bounds
        return [ox + x0 * k, oy + y0 * k, max(1.0, (x1 - x0) * k), max(1.0, (y1 - y0) * k)]

    def _all_native_bounds(self) -> List[Tuple[float, float, float, float]]:
        doc = self.document
        if doc is None:
            return []
        wp, waypoints = self._telemetry_for_render()
        native_w, native_h = doc.skin_native_size()
        layout = doc.layout
        result = []
        for elem in doc.elements:
            kind = element_kind(elem)
            text = None
            lines = None
            try:
                if kind == "text":
                    text, _ = resolve_element_text(layout, elem.get("field", ""), wp, waypoints)
                    text = str(text) if text not in (None, "") else None
                elif kind == "badge":
                    lines = badge_lines(doc.rules_manufacturer, doc.model, elem, wp)
                result.append(element_native_bounds(elem, native_w, native_h, text=text, badge_lines=lines))
            except Exception as e:
                print(f"Overlay Designer bounds error ({elem.get('field')}): {e}")
                x = float(elem.get("rel_x", 0.0)) * native_w
                y = float(elem.get("rel_y", 0.0)) * native_h
                result.append((x, y, x + 10.0, y + 10.0))
        return result

    def _update_boxes(self):
        doc = self.document
        if doc is None:
            self._element_boxes = []
            self._selection_box = {"visible": False, "x": 0.0, "y": 0.0, "w": 0.0, "h": 0.0, "label": ""}
            self.boxesChanged.emit()
            return
        native_bounds = self._all_native_bounds()
        self._element_boxes = [self._native_bounds_to_display(b) for b in native_bounds]
        if 0 <= self._selected_index < len(self._element_boxes):
            x, y, w, h = self._element_boxes[self._selected_index]
            label = self._element_label(doc.elements[self._selected_index])
            count = len(self._selection())
            if count > 1:
                label = f"{label}  (+{count - 1})"
            self._selection_box = {"visible": True, "x": x, "y": y, "w": w, "h": h, "label": label}
        elif self._skin_selected:
            native_w, native_h = doc.skin_native_size()
            x, y, w, h = self._native_bounds_to_display((0.0, 0.0, native_w, native_h))
            self._selection_box = {"visible": True, "x": x, "y": y, "w": w, "h": h, "label": "Skin"}
        else:
            self._selection_box = {"visible": False, "x": 0.0, "y": 0.0, "w": 0.0, "h": 0.0, "label": ""}
        self.boxesChanged.emit()

    @Property(list, notify=boxesChanged)
    def elementBoxes(self):
        return [list(b) for b in self._element_boxes]

    @Property(list, notify=boxesChanged)
    def secondarySelectionBoxes(self):
        """Display boxes of the selected elements other than the primary."""
        return [list(self._element_boxes[i]) for i in self._selection()
                if i != self._selected_index and i < len(self._element_boxes)]

    @Property("QVariant", notify=boxesChanged)
    def marqueeBox(self):
        if not self._marquee:
            return {"visible": False, "x": 0, "y": 0, "w": 0, "h": 0}
        m = self._marquee
        x0, x1 = sorted((m["x0"], m["x1"]))
        y0, y1 = sorted((m["y0"], m["y1"]))
        x, y, w, h = self._native_bounds_to_display((x0, y0, x1, y1))
        return {"visible": True, "x": x, "y": y, "w": w, "h": h}

    @Property(bool, notify=boxesChanged)
    def selectionBoxVisible(self):
        return self._selection_box["visible"]

    @Property(float, notify=boxesChanged)
    def selectionBoxX(self):
        return self._selection_box["x"]

    @Property(float, notify=boxesChanged)
    def selectionBoxY(self):
        return self._selection_box["y"]

    @Property(float, notify=boxesChanged)
    def selectionBoxW(self):
        return self._selection_box["w"]

    @Property(float, notify=boxesChanged)
    def selectionBoxH(self):
        return self._selection_box["h"]

    @Property(str, notify=boxesChanged)
    def selectionBoxLabel(self):
        return self._selection_box["label"]

    @Property(bool, notify=boxesChanged)
    def showBounds(self):
        return self._show_bounds

    @Slot(bool)
    def setShowBounds(self, value):
        self._show_bounds = bool(value)
        self.boxesChanged.emit()

    # -- grid + snapping (Phase 5) ---------------------------------------

    @Property(bool, notify=viewChanged)
    def showGrid(self):
        return self._show_grid

    @Slot(bool)
    def setShowGrid(self, value):
        self._show_grid = bool(value)
        self.viewChanged.emit()
        self._redraw()

    @Property(bool, notify=viewChanged)
    def snapEnabled(self):
        return self._snap

    @Slot(bool)
    def setSnapEnabled(self, value):
        self._snap = bool(value)
        self.viewChanged.emit()

    @Property(list, constant=True)
    def gridSizes(self):
        return list(GRID_SIZES)

    @Property(int, notify=viewChanged)
    def gridSize(self):
        return self._grid_size

    @Slot(int)
    def setGridSize(self, value):
        value = int(value)
        if value < 1 or value == self._grid_size:
            return
        self._grid_size = value
        self.viewChanged.emit()
        if self._show_grid:
            self._redraw()

    def _snap_delta(self, index: int, dx: float, dy: float, bounds) -> Tuple[float, float]:
        """Adjust a proposed (dx, dy) move of element `index` so its anchor
        lands on the grid and/or its bounds edges line up with unselected
        elements' edges (within SNAP_TOLERANCE_PX native px)."""
        if not self._snap:
            return dx, dy
        doc = self.document
        native_w, native_h = doc.skin_native_size()
        elem = doc.elements[index]
        ax = float(elem.get("rel_x", 0.0)) * native_w + dx
        ay = float(elem.get("rel_y", 0.0)) * native_h + dy
        best_x = best_y = None
        g = float(self._grid_size)
        gx, gy = round(ax / g) * g, round(ay / g) * g
        if abs(gx - ax) <= SNAP_TOLERANCE_PX:
            best_x = gx - ax
        if abs(gy - ay) <= SNAP_TOLERANCE_PX:
            best_y = gy - ay
        # edge/centre snapping against unselected, visible elements
        x0, y0, x1, y1 = bounds[index]
        moved = (x0 + dx, y0 + dy, x1 + dx, y1 + dy)
        mine_x = (moved[0], (moved[0] + moved[2]) / 2.0, moved[2])
        mine_y = (moved[1], (moved[1] + moved[3]) / 2.0, moved[3])
        selected = self._selected_set
        for j, other in enumerate(bounds):
            if j in selected or j in self._hidden:
                continue
            for ox in (other[0], (other[0] + other[2]) / 2.0, other[2]):
                for mx in mine_x:
                    d = ox - mx
                    if abs(d) <= SNAP_TOLERANCE_PX and (best_x is None or abs(d) < abs(best_x)):
                        best_x = d
            for oy in (other[1], (other[1] + other[3]) / 2.0, other[3]):
                for my in mine_y:
                    d = oy - my
                    if abs(d) <= SNAP_TOLERANCE_PX and (best_y is None or abs(d) < abs(best_y)):
                        best_y = d
        return dx + (best_x or 0.0), dy + (best_y or 0.0)

    # ==================================================================
    # Canvas mouse interaction
    # ==================================================================

    @Slot(float, float)
    def onCanvasPressed(self, x, y):
        self.onCanvasPressedMod(x, y, 0)

    @Slot(float, float, int)
    def onCanvasPressedMod(self, x, y, modifiers):
        """Press with keyboard modifiers (Qt.KeyboardModifier bits):
        Cmd/Ctrl/Shift-click toggles an element in/out of the selection;
        a plain press on a selected element starts a group drag; a plain
        press on empty skin starts a marquee (Design view) or a skin drag
        (Frame preview)."""
        doc = self.document
        self._drag = None
        self._marquee = None
        if doc is None:
            return
        toggle = bool(int(modifiers) & (MOD_CTRL | MOD_META | MOD_SHIFT))
        nx, ny = self._display_to_native(x, y)
        _, _, k = self._skin_display_transform()
        slack = HIT_SLACK_DISPLAY_PX / k if k else 2.0
        bounds = self._all_native_bounds()
        hittable = [b if i not in self._hidden else (1e9, 1e9, 1e9, 1e9) for i, b in enumerate(bounds)]
        hit = hit_test_bounds(nx, ny, hittable, slack=slack)
        if hit is not None:
            self._skin_selected = False
            if toggle:
                self.toggleElement(hit)
                return
            if hit not in self._selected_set:
                self._set_primary(hit)
            else:
                self._selected_index = hit
            self._drag = {
                "mode": "element", "index": hit, "pushed": False,
                "start_nx": nx, "start_ny": ny,
                "orig": {i: (float(doc.elements[i].get("rel_x", 0.0)), float(doc.elements[i].get("rel_y", 0.0)))
                         for i in self._selection()},
                "bounds": bounds,
            }
        else:
            native_w, native_h = doc.skin_native_size()
            on_skin = 0 <= nx <= native_w and 0 <= ny <= native_h
            if toggle:
                return
            if on_skin and self._view_mode == VIEW_FRAME:
                self._set_primary(-1)
                self._skin_selected = True
                sx, sy, _, _ = doc.frame_box(self.view_w, self.view_h)
                self._drag = {
                    "mode": "skin", "pushed": False,
                    "start_x": x, "start_y": y, "orig_fx": sx, "orig_fy": sy,
                }
            else:
                # Design view (or off-skin): marquee; resolves on release.
                self._drag = {"mode": "marquee", "pushed": False, "start_nx": nx, "start_ny": ny,
                              "on_skin": on_skin, "bounds": bounds, "moved": False}
                self._set_primary(-1)
                self._skin_selected = False
        self.selectionChanged.emit()
        self._update_boxes()

    @Slot(float, float)
    def onCanvasDragged(self, x, y):
        drag = self._drag
        doc = self.document
        if not drag or doc is None:
            return
        if drag["mode"] == "marquee":
            nx, ny = self._display_to_native(x, y)
            drag["moved"] = True
            self._marquee = {"x0": drag["start_nx"], "y0": drag["start_ny"], "x1": nx, "y1": ny}
            self.boxesChanged.emit()
            return
        if not drag["pushed"]:
            doc.push_undo()
            drag["pushed"] = True
        if drag["mode"] == "element":
            nx, ny = self._display_to_native(x, y)
            native_w, native_h = doc.skin_native_size()
            if native_w <= 0 or native_h <= 0:
                return
            dx_px = nx - drag["start_nx"]
            dy_px = ny - drag["start_ny"]
            # Snap on the primary; the rest of the group follows by the same delta.
            primary = drag["index"]
            ox, oy = drag["orig"][primary]
            cur_dx = (ox * native_w + dx_px) - float(doc.elements[primary].get("rel_x", 0.0)) * native_w
            cur_dy = (oy * native_h + dy_px) - float(doc.elements[primary].get("rel_y", 0.0)) * native_h
            sdx, sdy = self._snap_delta(primary, cur_dx, cur_dy, drag["bounds"] if not self._snap else self._all_native_bounds())
            dx_px += sdx - cur_dx
            dy_px += sdy - cur_dy
            for index, (rx, ry) in drag["orig"].items():
                if doc.element(index) is None:
                    continue
                doc.move_element(index, rx + dx_px / native_w, ry + dy_px / native_h, record_undo=False)
        else:
            zoom = self._zoom or 1.0
            fx = drag["orig_fx"] + (x - drag["start_x"]) / zoom
            fy = drag["orig_fy"] + (y - drag["start_y"]) / zoom
            doc.set_frame_position(fx, fy, self.view_w, self.view_h, record_undo=False)
        self.selectionChanged.emit()
        self._update_boxes()

    @Slot()
    def onCanvasReleased(self):
        drag = self._drag
        self._drag = None
        if not drag:
            return
        if drag["mode"] == "marquee":
            m = self._marquee
            self._marquee = None
            if m is None or not drag["moved"]:
                # plain click: select the skin (or nothing off-skin)
                self._set_primary(-1)
                self._skin_selected = bool(drag["on_skin"])
            else:
                x0, x1 = sorted((m["x0"], m["x1"]))
                y0, y1 = sorted((m["y0"], m["y1"]))
                picked = [
                    i for i, (bx0, by0, bx1, by1) in enumerate(drag["bounds"])
                    if i not in self._hidden and bx1 >= x0 and bx0 <= x1 and by1 >= y0 and by0 <= y1
                ]
                self._selected_set = set(picked)
                self._selected_index = picked[-1] if picked else -1
                self._skin_selected = False
            self.selectionChanged.emit()
            self._update_boxes()
            return
        if drag["pushed"]:
            self._after_edit()

    # ==================================================================
    # Zip export / import (Phase 5)
    # ==================================================================

    @Slot()
    def exportZip(self):
        from PySide6.QtWidgets import QFileDialog

        doc = self.document
        if doc is None:
            return
        suggested = f"{doc.ref.computer}_{doc.ref.page}.zip" if doc.ref else "overlay_page.zip"
        path, _ = QFileDialog.getSaveFileName(None, "Export overlay page", suggested, "Zip archives (*.zip)")
        if path:
            self._export_zip_to(Path(path))

    def _export_zip_to(self, path: Path) -> bool:
        doc = self.document
        if doc is None:
            return False
        path = Path(path)
        if path.suffix.lower() != ".zip":
            path = path.with_suffix(".zip")
        layout = normalized_layout(doc.render_layout())
        page_entry = self._page_entry() or {}
        meta = {
            "brand": doc.ref.brand if doc.ref else "",
            "computer": doc.ref.computer if doc.ref else "",
            "page": doc.ref.page if doc.ref else "",
            "page_name": page_entry.get("name", doc.ref.page if doc.ref else ""),
            "manufacturer": doc.manufacturer,
            "model": doc.model,
            "rules_profile": doc.layout.get("rules_profile"),
        }
        try:
            with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr(STATE_FILENAME, json.dumps(layout, indent=2, ensure_ascii=False))
                zf.writestr(ZIP_META_FILENAME, json.dumps(meta, indent=2))
                if doc.skin_type == "image" and doc.skin_abs_path and doc.skin_abs_path.exists():
                    zf.write(doc.skin_abs_path, SKIN_FILENAME)
        except OSError as e:
            self._set_status(f"Could not export: {e}")
            return False
        self._set_status(f"Exported {display_root(path)}")
        return True

    @Slot(result=str)
    def importZip(self):
        """Pick a .zip; returns the suggested page name ("" when cancelled or
        unreadable) - the QML then opens the Save-as popup in import mode."""
        from PySide6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getOpenFileName(None, "Import overlay page", "", "Zip archives (*.zip)")
        if not path:
            return ""
        error = self._read_import_zip(Path(path))
        if error:
            self._set_status(error)
            return ""
        return self._import["meta"].get("page_name") or "Imported"

    def _read_import_zip(self, path: Path) -> str:
        """Stage a zip for import; returns "" or an error message."""
        self._import = None
        try:
            with zipfile.ZipFile(path) as zf:
                names = set(zf.namelist())
                if STATE_FILENAME not in names:
                    return f"{path.name} has no {STATE_FILENAME}."
                layout = json.loads(zf.read(STATE_FILENAME).decode("utf-8"))
                meta = json.loads(zf.read(ZIP_META_FILENAME).decode("utf-8")) if ZIP_META_FILENAME in names else {}
                skin_path = None
                if layout.get("hud_skin", {}).get("type", "image") == "image":
                    if SKIN_FILENAME not in names:
                        return f"{path.name} has no {SKIN_FILENAME} skin image."
                    tmp_dir = Path(tempfile.mkdtemp(prefix="uwmedia_import_"))
                    skin_path = tmp_dir / SKIN_FILENAME
                    skin_path.write_bytes(zf.read(SKIN_FILENAME))
                    layout["hud_skin"]["path"] = str(skin_path)
        except (OSError, zipfile.BadZipFile, ValueError) as e:
            return f"Could not read {path.name}: {e}"
        self._import = {"layout": layout, "meta": meta, "skin_path": skin_path}
        self.persistenceChanged.emit()
        return ""

    @Property(bool, notify=persistenceChanged)
    def importPending(self):
        return bool(getattr(self, "_import", None))

    @Slot()
    def cancelImport(self):
        self._import = None
        self.persistenceChanged.emit()

    @Slot(int, str, str, result=str)
    def finishImport(self, target_index, new_computer_name, page_name):
        """Save the staged import as a new page - same arguments as saveAs()."""
        staged = getattr(self, "_import", None)
        if not staged:
            return "Nothing to import."
        targets = self.saveAsTargets
        if not 0 <= int(target_index) < len(targets):
            return "Pick where to save the page."
        target = targets[int(target_index)]
        page_name = (page_name or "").strip()
        page_id = slugify(page_name)
        if not page_id:
            return "Enter a page name."
        manufacturer = model = None
        rules_profile = None
        if target["computer"]:
            brand, computer = target["brand"], target["computer"]
        else:
            new_computer_name = (new_computer_name or "").strip()
            computer = slugify(new_computer_name)
            if not computer:
                return "Enter a name for the new computer."
            brand = CUSTOM_BRAND
            manufacturer, model = CUSTOM_MANUFACTURER, new_computer_name
            rules_profile = staged["meta"].get("rules_profile")
        dst = TemplateRef(brand, computer, page_id, None)
        try:
            path = save_template_as(
                staged["layout"], dst, page_name, skin_source=staged["skin_path"],
                manufacturer=manufacturer, model=model, rules_profile=rules_profile, overwrite_user=False,
            )
        except TemplateStoreError as e:
            return str(e)
        except OSError as e:
            return f"Could not import: {e}"
        self._import = None
        self.persistenceChanged.emit()
        self._select_ref(dst)
        self._set_status(f"Imported as {dst.label} → {display_root(path)}")
        self.templatesChanged.emit()
        return ""

    # ==================================================================
    # Canvas view: mode + zoom
    # ==================================================================

    @Property(str, notify=viewChanged)
    def viewMode(self):
        return self._view_mode

    @Slot(str)
    def setViewMode(self, mode):
        if mode not in (VIEW_DESIGN, VIEW_FRAME) or mode == self._view_mode:
            return
        self._view_mode = mode
        self._zoom_fit = True
        self._apply_fit_zoom()
        self._drag = None
        self.viewChanged.emit()
        self._update_boxes()
        self._redraw()

    def _native_canvas_size(self) -> Tuple[float, float]:
        """Size of what the canvas shows, in its own pixels: the skin's
        native size in Design view, the frame size in Frame preview."""
        if self._view_mode == VIEW_DESIGN:
            if self.document is not None:
                w, h = self.document.skin_native_size()
                if w > 0 and h > 0:
                    return w, h
            return 400.0, 200.0
        return self.view_w, self.view_h

    def _fit_zoom(self) -> float:
        w, h = self._native_canvas_size()
        if w <= 0 or h <= 0:
            return 1.0
        return _clamp_zoom(min(self._viewport_w / w, self._viewport_h / h))

    def _apply_fit_zoom(self):
        if self._zoom_fit:
            self._zoom = self._fit_zoom()

    @Property(float, notify=viewChanged)
    def zoom(self):
        return self._zoom

    @Property(int, notify=viewChanged)
    def zoomPercent(self):
        return int(round(self._zoom * 100))

    @Property(bool, notify=viewChanged)
    def zoomIsFit(self):
        return self._zoom_fit

    @Slot(int)
    def setZoomPercent(self, percent):
        self._set_zoom(percent / 100.0)

    @Slot()
    def zoomIn(self):
        self._set_zoom((int(round(self._zoom / ZOOM_STEP)) + 1) * ZOOM_STEP)

    @Slot()
    def zoomOut(self):
        self._set_zoom((int(round(self._zoom / ZOOM_STEP)) - 1) * ZOOM_STEP)

    def _set_zoom(self, value: float):
        self._zoom_fit = False
        self._zoom = _clamp_zoom(value)
        self.viewChanged.emit()
        self._update_boxes()
        self._redraw()

    @Slot()
    def zoomFit(self):
        self._zoom_fit = True
        self._apply_fit_zoom()
        self.viewChanged.emit()
        self._update_boxes()
        self._redraw()

    @Slot(int, int)
    def setViewportSize(self, width, height):
        """Called by the QML canvas viewport on resize so Fit can track it."""
        width, height = max(1, int(width)), max(1, int(height))
        if (width, height) == (self._viewport_w, self._viewport_h):
            return
        self._viewport_w, self._viewport_h = width, height
        if not self._zoom_fit:
            return
        before = self._zoom
        self._apply_fit_zoom()
        if before != self._zoom:
            self.viewChanged.emit()
            self._update_boxes()
            if self._view_mode == VIEW_DESIGN:
                self._redraw()  # Design view renders at zoom; Frame view only stretches

    @Property(int, notify=viewChanged)
    def canvasDisplayWidth(self):
        w, _ = self._native_canvas_size()
        return max(1, int(round(w * self._zoom)))

    @Property(int, notify=viewChanged)
    def canvasDisplayHeight(self):
        _, h = self._native_canvas_size()
        return max(1, int(round(h * self._zoom)))

    # ==================================================================
    # Rendering - QQuickImageProvider
    # ==================================================================

    def _redraw(self):
        self._preview_revision += 1
        self.previewChanged.emit()

    @Property(str, notify=previewChanged)
    def previewImageSource(self):
        return f"image://overlaydesignerpreview/frame?r={self._preview_revision}"

    def _checkerboard(self, width: int, height: int) -> np.ndarray:
        if self._checker_cache and self._checker_cache[0] == (width, height):
            return self._checker_cache[1].copy()
        yy, xx = np.indices((height, width))
        mask = ((yy // CHECKER_PX + xx // CHECKER_PX) % 2).astype(bool)
        board = np.where(mask, 74, 54).astype(np.uint8)
        board = np.repeat(board[:, :, None], 3, axis=2)
        self._checker_cache = ((width, height), board)
        return board.copy()

    def _draw_grid(self, canvas: np.ndarray, zoom: float) -> None:
        """Faint grid lines every gridSize native px (skipped when they would
        be denser than 4 display px)."""
        step = self._grid_size * zoom
        if step < 4:
            return
        h, w = canvas.shape[:2]
        xs = np.arange(0, w, step).round().astype(int)
        ys = np.arange(0, h, step).round().astype(int)
        canvas[:, xs[xs < w]] = (105, 105, 105)
        canvas[ys[ys < h], :] = (105, 105, 105)

    def _synthetic_background(self) -> np.ndarray:
        """A neutral "underwater" gradient with a soft vignette, sized to the
        current frame - what Frame preview composites onto when no video/
        photo is loaded, so the template's anchor placement is visible."""
        width, height = int(self.view_w), int(self.view_h)
        if self._synthetic_bg_cache and self._synthetic_bg_cache[0] == (width, height):
            return self._synthetic_bg_cache[1].copy()
        y = np.linspace(0.0, 1.0, height, dtype=np.float32)[:, None, None]
        x = np.linspace(0.0, 1.0, width, dtype=np.float32)[None, :, None]
        top = np.array([150, 112, 34], dtype=np.float32)      # BGR: teal-ish
        bottom = np.array([72, 38, 12], dtype=np.float32)     # BGR: deep blue
        img = top * (1.0 - y) + bottom * y
        vignette = 1.0 - 0.35 * (((x - 0.5) ** 2) + ((y - 0.5) ** 2)) * 2.0
        img = np.clip(img * vignette, 0, 255).astype(np.uint8)
        img = np.ascontiguousarray(np.broadcast_to(img, (height, width, 3)))
        self._synthetic_bg_cache = ((width, height), img)
        return img.copy()

    def render_current_frame(self) -> QImage:
        if self.document is None:
            return QImage(1, 1, QImage.Format.Format_RGB888)

        wp, waypoints = self._telemetry_for_render()
        if self._view_mode == VIEW_DESIGN:
            native_w, native_h = self._native_canvas_size()
            zoom = self._zoom
            if native_w * zoom > MAX_RENDER_WIDTH:
                zoom = MAX_RENDER_WIDTH / native_w
            width = max(1, int(round(native_w * zoom)))
            height = max(1, int(round(native_h * zoom)))
            canvas = self._checkerboard(width, height)
            if self._show_grid:
                self._draw_grid(canvas, zoom)
            layout = self._visible_layout(self.document.design_view_layout(zoom))
            try:
                draw_hud(canvas, layout, wp, render_log=True, waypoints=waypoints)
            except Exception as e:
                print(f"Overlay Designer render error (design view): {e}")
        else:
            canvas = self.bg_frame.copy() if self.bg_frame is not None else self._synthetic_background()
            try:
                draw_hud(canvas, self._visible_layout(self.document.render_layout()), wp, waypoints=waypoints)
            except Exception as e:
                print(f"Overlay Designer render error (frame view): {e}")

        rgb = np.ascontiguousarray(cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB))
        h, w = rgb.shape[:2]
        qimage = QImage(rgb.data, w, h, rgb.strides[0], QImage.Format.Format_RGB888)
        return qimage.copy()

    # ==================================================================
    # Telemetry: dummy vs log, state override
    # ==================================================================

    @Property(str, notify=telemetryChanged)
    def telemetrySource(self):
        return self._telemetry_source

    @Property(bool, notify=telemetryChanged)
    def logTelemetryAvailable(self):
        return self.current_dive is not None

    @Slot(str)
    def setTelemetrySource(self, source):
        if source not in (SOURCE_DUMMY, SOURCE_LOG):
            return
        if source == SOURCE_LOG and self.current_dive is None:
            return
        if source == self._telemetry_source:
            return
        self._telemetry_source = source
        self.telemetryChanged.emit()
        self._update_data_text()
        self._redraw()

    @Property(list, constant=True)
    def stateList(self):
        return [STATE_LABELS[s] for s in STATE_OPTIONS]

    @Property(int, notify=telemetryChanged)
    def stateIndex(self):
        return STATE_OPTIONS.index(self._state_override)

    @Slot(str)
    def onStateSelected(self, label):
        state = next((s for s in STATE_OPTIONS if STATE_LABELS[s] == label), None)
        if state is None or state == self._state_override:
            return
        self._state_override = state
        self.telemetryChanged.emit()
        self._update_data_text()
        self._redraw()

    def _current_seconds(self) -> float:
        if self.video_cap is not None:
            return self._time_value / self.video_fps if self.video_fps else 0.0
        return float(self._time_value)

    def _telemetry_for_render(self):
        """(waypoint, waypoints) the canvas renders with. Log telemetry when
        selected and in range; otherwise the synthetic dive at the current
        slider time - so the canvas is always populated. The state override
        applies to both."""
        seconds = self._current_seconds()
        waypoints = None
        wp = None
        if self._telemetry_source == SOURCE_LOG and self.current_dive is not None:
            waypoints = self.current_dive.waypoints
            wp = self.current_waypoint
        if wp is None:
            wp = waypoint_at(self.dummy_dive, seconds)
            if waypoints is None:
                waypoints = self.dummy_dive.waypoints
        if wp is not None:
            wp = apply_state(wp, self._state_override)
        return wp, waypoints

    def _update_data_text(self):
        wp, _ = self._telemetry_for_render()
        using_log = (
            self._telemetry_source == SOURCE_LOG
            and self.current_dive is not None
            and self.current_waypoint is not None
        )
        if wp is None:
            self._data_text = "No telemetry."
        else:
            source = "Log telemetry" if using_log else "Dummy telemetry"
            if self._telemetry_source == SOURCE_LOG and not using_log and self.current_dive is not None:
                source = "Out of dive range - showing dummy telemetry"
            manufacturer = self.document.rules_manufacturer if self.document else None
            model = self.document.model if self.document else None
            state = resolve_state(manufacturer, model, wp)
            depth = f"{wp.depth:.1f} m" if wp.depth is not None else "--"
            temp = f"{wp.temp:.1f} °C" if wp.temp is not None else "--"
            self._data_text = f"{source} · Depth {depth} · Temp {temp} · State: {state}"
        self.dataChanged.emit()
        self._update_boxes()  # rendered strings (and so hit boxes) follow the telemetry

    # ==================================================================
    # Time slider (video frames / log seconds / dummy seconds)
    # ==================================================================

    @Property(int, notify=timeChanged)
    def timeValue(self):
        return self._time_value

    @Property(int, notify=timeChanged)
    def timeMin(self):
        return self._time_min

    @Property(int, notify=timeChanged)
    def timeMax(self):
        return self._time_max

    @Property(bool, notify=timeChanged)
    def timeEnabled(self):
        return self._time_enabled

    @Property(str, notify=timeChanged)
    def timeText(self):
        return self._time_text

    def _set_time(self, minimum, maximum, value, enabled, text):
        self._time_min = minimum
        self._time_max = maximum
        self._time_value = value
        self._time_enabled = enabled
        self._time_text = text
        self.timeChanged.emit()

    def _enter_dummy_time_range(self):
        self._set_time(
            0, DUMMY_DURATION_S, DUMMY_DEFAULT_SECONDS, True,
            str(timedelta(seconds=DUMMY_DEFAULT_SECONDS)),
        )

    @Slot(int)
    def onTimeChanged(self, value):
        if self.video_cap is not None:
            frame_idx = int(value)
            self.video_cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            ret, frame = self.video_cap.read()
            if not ret:
                return
            frame = cv2.resize(
                frame, (int(self.view_w), int(self.view_h)), interpolation=cv2.INTER_AREA
            )
            self.bg_frame = frame
            seconds = frame_idx / self.video_fps
            self._time_value = value
            self._time_text = str(timedelta(seconds=int(seconds)))
            self.timeChanged.emit()
            self._sync_data_to_frame(seconds)
            self._redraw()
            return

        seconds = int(value)
        self._time_value = value
        self._time_text = str(timedelta(seconds=seconds))
        self.timeChanged.emit()
        if self.preview_from_log:
            self._sync_data_to_frame_by_dive_time(seconds)
        else:
            self._update_data_text()
        self._redraw()

    # ==================================================================
    # Background / logs - unchanged business logic from the Phase 7 port
    # ==================================================================

    @Property(str, notify=dataChanged)
    def dataText(self):
        return self._data_text

    @Property(str, notify=dataChanged)
    def logText(self):
        return self._log_text

    @Property(str, notify=statusChanged)
    def statusText(self):
        return self._status_text

    def _set_status(self, text):
        self._status_text = text
        self.statusChanged.emit()

    @Property(bool, notify=previewChanged)
    def hasBackground(self):
        return self.bg_frame is not None

    @Slot()
    def loadBackground(self):
        from PySide6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getOpenFileName(None, "Select background")
        if not path:
            return
        self._load_background_from_path(Path(path))

    @Slot()
    def clearBackground(self):
        """Back to the synthetic backdrop + dummy time range (video released)."""
        if self.video_cap:
            self.video_cap.release()
            self.video_cap = None
        self.bg_frame = None
        self.video_creation_date = None
        self.preview_from_log = False
        self.view_w, self.view_h = float(FRAME_W), float(FRAME_H)
        self._enter_dummy_time_range()
        self._after_background_changed()

    def _after_background_changed(self):
        self._zoom_fit = True
        self._apply_fit_zoom()
        self.viewChanged.emit()
        self._update_data_text()  # also refreshes the boxes (frame size may have changed)
        self._redraw()

    def _load_background_from_path(self, path: Path):
        self.preview_from_log = False
        handler = MetadataHandler()
        try:
            self.video_creation_date = handler.get_local_creation_date(path)
        except Exception:
            self.video_creation_date = datetime.now()

        if path.suffix.lower() in (".mp4", ".mov"):
            self._load_video(path)
        else:
            self._load_image(path)
        self._match_dive_to_media()

    def _load_video(self, path):
        if self.video_cap:
            self.video_cap.release()
        cap = cv2.VideoCapture(str(path))
        ret, frame = cap.read()
        if not ret:
            self._set_status(f"Could not read video: {path}")
            return
        self.video_cap = cap
        self.video_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        total_frames = max(1, int(cap.get(cv2.CAP_PROP_FRAME_COUNT)))
        h, w = frame.shape[:2]
        target_w = FRAME_W
        target_h = int(target_w * h / w)
        self.view_w, self.view_h = float(target_w), float(target_h)
        self.bg_frame = cv2.resize(frame, (target_w, target_h), interpolation=cv2.INTER_AREA)
        self._set_time(0, max(1, total_frames - 1), 0, True, "00:00:00")
        self._after_background_changed()

    def _load_image(self, path):
        if self.video_cap:
            self.video_cap.release()
            self.video_cap = None
        img = cv2.imread(str(path))
        if img is None:
            try:
                img = cv2.cvtColor(np.array(PILImage.open(path).convert("RGB")), cv2.COLOR_RGB2BGR)
            except Exception:
                img = None
        if img is None:
            self._set_status(f"Could not read image: {path}")
            return
        h, w = img.shape[:2]
        target_w = FRAME_W
        target_h = int(target_w * h / w)
        self.view_w, self.view_h = float(target_w), float(target_h)
        self.bg_frame = cv2.resize(img, (target_w, target_h), interpolation=cv2.INTER_AREA)
        self._set_time(0, 0, 0, False, "Photo Mode")
        self._sync_data_to_frame(0)
        self._after_background_changed()

    @Slot()
    def loadLogs(self):
        from PySide6.QtWidgets import QFileDialog

        path = QFileDialog.getExistingDirectory(None, "Select dive log directory")
        if not path:
            return
        self._load_logs_from_path(Path(path))

    def _load_logs_from_path(self, dir_path: Path):
        self.dive_manager = DiveManager()
        uddf, garmin, subsurface = UDDFParser(), GarminParser(), SubsurfaceParser()
        count = 0
        if not dir_path.exists():
            return
        for path in dir_path.iterdir():
            try:
                if path.suffix == ".uddf":
                    self.dive_manager.add_dives(uddf.parse(path))
                    count += 1
                elif path.suffix == ".fit":
                    self.dive_manager.add_dives(garmin.parse(path))
                    count += 1
                elif path.suffix in (".ssrf", ".xml"):
                    self.dive_manager.add_dives(subsurface.parse(path))
                    count += 1
            except Exception as e:
                print(f"Error parsing {path.name}: {e}")
        self._set_status(f"Loaded {count} log files from {dir_path.name}")
        self._refresh_log_file_choices()
        self._match_dive_to_media()

    def _refresh_log_file_choices(self):
        self.log_file_choices = {}
        seen_counts: Dict[str, int] = {}
        for dive in self.dive_manager.dives.values():
            name = dive.log_filename or "Unknown log"
            when = dive.start_time.strftime("%Y-%m-%d %H:%M") if dive.start_time else "?"
            device = dive.device or dive.manufactor or ""
            base_label = f"{name} — {when}" + (f" ({device})" if device else "")
            seen_counts[base_label] = seen_counts.get(base_label, 0) + 1
            n = seen_counts[base_label]
            label = base_label if n == 1 else f"{base_label} #{n}"
            self.log_file_choices[label] = dive
        self.logFilesChanged.emit()

    @Property(list, notify=logFilesChanged)
    def logFileList(self):
        return list(self.log_file_choices.keys())

    @Property(bool, notify=logFilesChanged)
    def logFileEnabled(self):
        return bool(self.log_file_choices)

    @Slot(str)
    def onLogFileSelected(self, label):
        dive = self.log_file_choices.get(label)
        if dive is None or not dive.waypoints:
            return

        if self.video_cap:
            self.video_cap.release()
            self.video_cap = None
        self.bg_frame = None  # synthetic backdrop stands in for the old flat grey
        self.view_w, self.view_h = float(FRAME_W), float(FRAME_H)
        self.preview_from_log = True
        self.current_dive = dive
        self._telemetry_source = SOURCE_LOG

        duration = max(w.time_since_start for w in dive.waypoints)
        self._set_time(0, max(1, duration), 0, True, "00:00:00")

        self._sync_data_to_frame_by_dive_time(0)
        self.telemetryChanged.emit()
        # Re-resolve the variant from this dive's tank count and reload.
        self._refresh_variant_choices()

    def _sync_data_to_frame_by_dive_time(self, offset_seconds):
        if not self.current_dive:
            return
        wp = None
        for w in self.current_dive.waypoints:
            if w.time_since_start >= offset_seconds:
                wp = w
                break
        self.current_waypoint = wp or (
            self.current_dive.waypoints[-1] if self.current_dive.waypoints else None
        )
        wp = self.current_waypoint
        self._log_text = f"Current Log: {wp.log_filename or 'Unknown'}" if wp else "Current Log: None (No Match)"
        self._update_data_text()

    @Property(int, notify=tzChanged)
    def tzValue(self):
        return self._tz_value

    @Property(str, notify=tzChanged)
    def tzText(self):
        return f"{int(self._tz_value)}h"

    @Slot(int)
    def onTzChanged(self, value):
        self._tz_value = value
        self.tzChanged.emit()
        self._match_dive_to_media()

    def _match_dive_to_media(self):
        if not self.video_creation_date:
            return
        adjusted = self.video_creation_date + timedelta(hours=self._tz_value)
        self.current_dive = self.dive_manager.find_dive_for_timestamp(adjusted)
        if self.current_dive:
            self._telemetry_source = SOURCE_LOG
            seconds = self._time_value / self.video_fps if self.video_cap else 0
            self._sync_data_to_frame(seconds)
            self.telemetryChanged.emit()
            self._refresh_variant_choices()
        else:
            self._log_text = "Current Log: None (No Match)"
            self._data_text = "No matching dive found for this date/offset - showing dummy telemetry."
            self.telemetryChanged.emit()
            self.dataChanged.emit()

    def _sync_data_to_frame(self, offset_seconds):
        if not self.current_dive or not self.video_creation_date:
            return
        target_ts = self.video_creation_date + timedelta(hours=self._tz_value, seconds=offset_seconds)
        wp = None
        for w in self.current_dive.waypoints:
            if w.timestamp >= target_ts:
                wp = w
                break
        self.current_waypoint = wp
        self._log_text = f"Current Log: {wp.log_filename or 'Unknown'}" if wp else "Current Log: None (No Match)"
        self._update_data_text()

    # ------------------------------------------------------------------
    # Raw waypoint viewer - a QML Window bound to backend state
    # ------------------------------------------------------------------

    @Slot()
    def showWaypoint(self):
        wp, _ = self._telemetry_for_render()
        if wp is None:
            self._set_status("No waypoint data for current frame.")
            return
        self._waypoint_json = wp.model_dump_json(indent=4)
        self._waypoint_visible = True
        self.waypointViewerChanged.emit()

    @Slot()
    def closeWaypointViewer(self):
        self._waypoint_visible = False
        self.waypointViewerChanged.emit()

    @Property(bool, notify=waypointViewerChanged)
    def waypointVisible(self):
        return self._waypoint_visible

    @Property(str, notify=waypointViewerChanged)
    def waypointJson(self):
        return self._waypoint_json


class OverlayDesignerPreviewImageProvider(QQuickImageProvider):
    def __init__(self, backend: OverlayDesignerBackend):
        super().__init__(QQuickImageProvider.ImageType.Image)
        self._backend = backend

    def requestImage(self, id, size, requestedSize):
        return self._backend.render_current_frame()
