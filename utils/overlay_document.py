"""Editable in-memory model of one overlay template page - overlay_rework.md
Phase 1 (document model) + Phase 2 (element/skin editing, undo/redo,
frame-space geometry); persistence arrives in Phase 3. No Qt imports: the Overlay Designer backend owns one of these and
every edit goes through it, which is what makes dirty tracking, undo/redo and
serialization trivial.

The document wraps the layout dict exactly as it sits in `normal.json` (see
overlay_rework.md §1.3 for the schema) and never drops keys it does not know
about, so a load -> to_layout() round trip of every bundled template is
key-for-key identical. Transient facts the renderer needs (the absolute skin
path, the skin image's native pixel size) are kept *beside* the layout, not
injected into it, so they can't leak into a saved file.
"""
import copy
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2

from utils.hud_designer import ANCHORS, element_defaults, element_kind

UNDO_LIMIT = 100
REL_DECIMALS = 5
REL_MIN, REL_MAX = -0.5, 1.5  # an element may hang off the skin, but not vanish


def _clamp_rel(value: float) -> float:
    return max(REL_MIN, min(REL_MAX, float(value)))


@dataclass(frozen=True)
class TemplateRef:
    """Which template tree slot a document came from (or is destined for)."""
    brand: str
    computer: str
    page: str
    variant: Optional[str] = None

    @property
    def label(self) -> str:
        parts = [self.brand, self.computer, self.page]
        if self.variant:
            parts.append(self.variant)
        return "/".join(parts)


class OverlayDocument:
    def __init__(
        self,
        layout: Dict[str, Any],
        source_path: Optional[Path] = None,
        ref: Optional[TemplateRef] = None,
    ):
        self.layout: Dict[str, Any] = layout
        self.source_path: Optional[Path] = Path(source_path) if source_path else None
        self.ref: Optional[TemplateRef] = ref
        self.skin_abs_path: Optional[Path] = None
        self.native_width: int = 0
        self.native_height: int = 0
        self._undo: List[Dict[str, Any]] = []
        self._redo: List[Dict[str, Any]] = []
        self._saved_snapshot: Dict[str, Any] = copy.deepcopy(layout)
        self._resolve_skin()

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    @classmethod
    def load(cls, path: Path, ref: Optional[TemplateRef] = None) -> "OverlayDocument":
        path = Path(path)
        with open(path) as f:
            layout = json.load(f)
        return cls(layout, source_path=path, ref=ref)

    def _resolve_skin(self) -> None:
        """Absolute skin path (relative paths resolve against the JSON's own
        directory, exactly like every existing consumer does) and the image's
        native pixel size - the authoring coordinate space for Design view."""
        skin = self.skin
        self.skin_abs_path = None
        self.native_width = self.native_height = 0
        if skin.get("type", "image") != "image":
            return
        raw = skin.get("path")
        if not raw:
            return
        candidate = Path(raw)
        if not candidate.is_absolute() and self.source_path is not None:
            candidate = (self.source_path.parent / candidate).resolve()
        self.skin_abs_path = candidate
        if candidate.exists():
            img = cv2.imread(str(candidate), cv2.IMREAD_UNCHANGED)
            if img is not None:
                self.native_height, self.native_width = img.shape[:2]

    # ------------------------------------------------------------------
    # Read access
    # ------------------------------------------------------------------

    @property
    def skin(self) -> Dict[str, Any]:
        return self.layout.setdefault("hud_skin", {})

    @property
    def elements(self) -> List[Dict[str, Any]]:
        return self.skin.setdefault("linked_elements", [])

    @property
    def skin_type(self) -> str:
        return self.skin.get("type", "image")

    @property
    def manufacturer(self) -> str:
        return self.layout.get("manufacturer", "")

    @property
    def model(self) -> str:
        return self.layout.get("model", "")

    @property
    def rules_manufacturer(self) -> str:
        """Manufacturer key used for hud_rules.json lookups (rules_profile
        when set, else manufacturer) - mirrors gui.hud_renderer.rules_manufacturer."""
        return self.layout.get("rules_profile") or self.manufacturer

    @property
    def design_size(self) -> Tuple[int, int]:
        return int(self.layout.get("design_width", 1920)), int(self.layout.get("design_height", 1080))

    def skin_native_size(self) -> Tuple[float, float]:
        """Skin size in its own authoring pixels, before the template's `scale`
        - image: the PNG's pixel size; shape: its width/height."""
        if self.skin_type == "shape":
            return float(self.skin.get("width", 400)), float(self.skin.get("height", 200))
        return float(self.native_width), float(self.native_height)

    def skin_scaled_size(self) -> Tuple[float, float]:
        """Skin size in design pixels as the template renders it at
        design_width (native size x `scale` for images; shapes ignore scale)."""
        w, h = self.skin_native_size()
        if self.skin_type == "shape":
            return w, h
        scale = float(self.skin.get("scale", 1.0))
        return w * scale, h * scale

    # ------------------------------------------------------------------
    # Layouts for the renderer
    # ------------------------------------------------------------------

    def render_layout(self) -> Dict[str, Any]:
        """Deep copy with the skin path made absolute - what draw_hud() wants
        for a full-frame composite (Frame preview / CLI parity)."""
        layout = copy.deepcopy(self.layout)
        if self.skin_abs_path is not None:
            layout.setdefault("hud_skin", {})["path"] = str(self.skin_abs_path)
        return layout

    def design_view_layout(self, zoom: float) -> Dict[str, Any]:
        """Layout for draw_hud(..., render_log=True): the skin alone at its
        native size x `zoom`, template `scale` ignored (Design view is the
        authoring space - X/Y and font sizes are in native skin pixels).
        With render_log=True draw_hud puts the skin at (0, 0) with res_scale
        1.0 and sizes everything by hud_skin.scale, so zoom is expressed as
        that scale; shapes get width/height multiplied too, the same way
        resolve_overlay_instance_layout() already bakes a multiplier in."""
        layout = self.render_layout()
        skin = layout.setdefault("hud_skin", {})
        if skin.get("type", "image") == "shape":
            skin["width"] = float(skin.get("width", 400)) * zoom
            skin["height"] = float(skin.get("height", 200)) * zoom
        skin["scale"] = zoom
        return layout

    def frame_box(self, frame_w: float, frame_h: float) -> Tuple[float, float, float, float]:
        """(x, y, w, h) of the skin on a frame_w x frame_h composite - the
        same anchor/pivot/offset arithmetic (and int truncation) draw_hud()
        uses in its steps 1-4, so Frame-preview hit-testing lands exactly on
        the rendered pixels."""
        skin = self.skin
        design_w = float(self.design_size[0])
        res_scale = frame_w / design_w if design_w else 1.0
        native_w, native_h = self.skin_native_size()
        if self.skin_type == "shape":
            w_hud = int(native_w * res_scale)
            h_hud = int(native_h * res_scale)
        else:
            scale = float(skin.get("scale", 1.0))
            w_hud = int(native_w * scale * res_scale)
            h_hud = int(native_h * scale * res_scale)

        anchor = skin.get("anchor", "TOP_LEFT")
        base_x = frame_w / 2.0 if "CENTER" in anchor else float(frame_w) if "RIGHT" in anchor else 0.0
        base_y = frame_h / 2.0 if "MIDDLE" in anchor else float(frame_h) if "BOTTOM" in anchor else 0.0
        pivot_x = w_hud / 2.0 if "CENTER" in anchor else float(w_hud) if "RIGHT" in anchor else 0.0
        pivot_y = h_hud / 2.0 if "MIDDLE" in anchor else float(h_hud) if "BOTTOM" in anchor else 0.0
        skin_x = int(base_x + float(skin.get("ref_offset_x", 0.0)) * res_scale - pivot_x)
        skin_y = int(base_y + float(skin.get("ref_offset_y", 0.0)) * res_scale - pivot_y)
        return float(skin_x), float(skin_y), float(w_hud), float(h_hud)

    def set_frame_position(self, frame_x: float, frame_y: float, frame_w: float, frame_h: float, record_undo: bool = True) -> None:
        """Move the skin so its top-left lands at (frame_x, frame_y) on a
        frame_w x frame_h composite, keeping the current anchor - the inverse
        of frame_box(): ref offsets are stored in design pixels."""
        skin = self.skin
        design_w = float(self.design_size[0])
        res_scale = frame_w / design_w if design_w else 1.0
        _, _, w_hud, h_hud = self.frame_box(frame_w, frame_h)
        anchor = skin.get("anchor", "TOP_LEFT")
        base_x = frame_w / 2.0 if "CENTER" in anchor else float(frame_w) if "RIGHT" in anchor else 0.0
        base_y = frame_h / 2.0 if "MIDDLE" in anchor else float(frame_h) if "BOTTOM" in anchor else 0.0
        pivot_x = w_hud / 2.0 if "CENTER" in anchor else float(w_hud) if "RIGHT" in anchor else 0.0
        pivot_y = h_hud / 2.0 if "MIDDLE" in anchor else float(h_hud) if "BOTTOM" in anchor else 0.0
        if record_undo:
            self.push_undo()
        skin["ref_offset_x"] = round((frame_x - base_x + pivot_x) / res_scale, 2)
        skin["ref_offset_y"] = round((frame_y - base_y + pivot_y) / res_scale, 2)

    # ------------------------------------------------------------------
    # Element editing (Phase 2) - every public mutation records one undo
    # step unless told otherwise (drags push once on press, then stream).
    # ------------------------------------------------------------------

    def element(self, index: int) -> Optional[Dict[str, Any]]:
        elements = self.elements
        if 0 <= index < len(elements):
            return elements[index]
        return None

    def add_element(self, field: str, kind: str = "text", rel_x: float = 0.5, rel_y: float = 0.5, **attrs: Any) -> int:
        """Append a new element and return its index."""
        elem = element_defaults(kind, field)
        elem["rel_x"] = _clamp_rel(rel_x)
        elem["rel_y"] = _clamp_rel(rel_y)
        elem.update(attrs)
        self.push_undo()
        self.elements.append(elem)
        return len(self.elements) - 1

    def remove_element(self, index: int) -> bool:
        if self.element(index) is None:
            return False
        self.push_undo()
        del self.elements[index]
        return True

    def duplicate_element(self, index: int) -> Optional[int]:
        source = self.element(index)
        if source is None:
            return None
        self.push_undo()
        clone = copy.deepcopy(source)
        clone["rel_x"] = _clamp_rel(clone.get("rel_x", 0.0) + 0.02)
        clone["rel_y"] = _clamp_rel(clone.get("rel_y", 0.0) + 0.02)
        self.elements.insert(index + 1, clone)
        return index + 1

    def move_element(self, index: int, rel_x: float, rel_y: float, record_undo: bool = True) -> None:
        elem = self.element(index)
        if elem is None:
            return
        if record_undo:
            self.push_undo()
        elem["rel_x"] = _clamp_rel(rel_x)
        elem["rel_y"] = _clamp_rel(rel_y)

    def set_element_position_px(self, index: int, x_px: float, y_px: float, record_undo: bool = True) -> None:
        """Position in native skin pixels (what the inspector shows)."""
        native_w, native_h = self.skin_native_size()
        if native_w <= 0 or native_h <= 0:
            return
        self.move_element(index, x_px / native_w, y_px / native_h, record_undo=record_undo)

    def element_position_px(self, index: int) -> Tuple[float, float]:
        elem = self.element(index) or {}
        native_w, native_h = self.skin_native_size()
        return float(elem.get("rel_x", 0.0)) * native_w, float(elem.get("rel_y", 0.0)) * native_h

    def nudge_element(self, index: int, dx_px: float, dy_px: float) -> None:
        x, y = self.element_position_px(index)
        self.set_element_position_px(index, x + dx_px, y + dy_px)

    def set_element_attr(self, index: int, key: str, value: Any) -> None:
        """Set (or, with value None, delete) one attribute. rel_x/rel_y are
        clamped; a field change also normalises the element's type."""
        elem = self.element(index)
        if elem is None or key in ("type",):
            return
        if value is None:
            if key in elem and key not in ("field", "rel_x", "rel_y"):
                self.push_undo()
                del elem[key]
            return
        if key in ("rel_x", "rel_y"):
            value = _clamp_rel(value)
        if elem.get(key) == value:
            return
        self.push_undo()
        elem[key] = value
        if key == "field":
            if value == "depth_graph":
                elem["type"] = "graph"
            elif value == "state_badge":
                elem["type"] = "badge"
            elif element_kind(elem) in ("graph", "badge") and value not in ("depth_graph", "state_badge"):
                elem.pop("type", None)

    def reorder_element(self, index: int, delta: int) -> int:
        """Move an element up/down the z-order (list order); returns the new index."""
        elements = self.elements
        if self.element(index) is None:
            return index
        new_index = max(0, min(len(elements) - 1, index + delta))
        if new_index == index:
            return index
        self.push_undo()
        elem = elements.pop(index)
        elements.insert(new_index, elem)
        return new_index

    # ------------------------------------------------------------------
    # Skin editing (Phase 2)
    # ------------------------------------------------------------------

    def set_skin_attr(self, key: str, value: Any) -> None:
        skin = self.skin
        if key == "anchor" and value not in ANCHORS:
            return
        if key in ("type", "path", "linked_elements"):
            return
        if skin.get(key) == value:
            return
        self.push_undo()
        skin[key] = value

    def set_skin_image(self, path: Path) -> bool:
        """Point an image skin at a new file (absolute path until Phase 3's
        save copies it next to the JSON); rel_x/rel_y are left alone so the
        fields stay proportionally placed. Returns False if unreadable."""
        path = Path(path)
        img = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
        if img is None:
            return False
        self.push_undo()
        skin = self.skin
        skin["type"] = "image"
        skin["path"] = str(path)
        skin.setdefault("scale", 1.0)
        for key in ("width", "height", "color", "corner_radius"):
            skin.pop(key, None)
        self._resolve_skin()
        return True

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_layout(self, for_save: bool = False) -> Dict[str, Any]:
        """Deep copy of the layout. With for_save=True the skin path is
        reduced to its bare file name (templates are self-contained page
        directories) and rel_x/rel_y are rounded the way the hand-authored
        files are."""
        layout = copy.deepcopy(self.layout)
        if not for_save:
            return layout
        skin = layout.setdefault("hud_skin", {})
        if skin.get("path"):
            skin["path"] = Path(skin["path"]).name
        for elem in skin.get("linked_elements", []):
            for key in ("rel_x", "rel_y"):
                if isinstance(elem.get(key), float):
                    elem[key] = round(elem[key], REL_DECIMALS)
        return layout

    # ------------------------------------------------------------------
    # Dirty tracking + undo/redo (Phase 2's edit operations call these)
    # ------------------------------------------------------------------

    @property
    def dirty(self) -> bool:
        return self.layout != self._saved_snapshot

    def mark_saved(self) -> None:
        self._saved_snapshot = copy.deepcopy(self.layout)

    def push_undo(self) -> None:
        """Call *before* mutating self.layout - snapshots the current state."""
        self._undo.append(copy.deepcopy(self.layout))
        if len(self._undo) > UNDO_LIMIT:
            del self._undo[0]
        self._redo.clear()

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    def undo(self) -> bool:
        if not self._undo:
            return False
        self._redo.append(copy.deepcopy(self.layout))
        self.layout = self._undo.pop()
        self._resolve_skin()
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        self._undo.append(copy.deepcopy(self.layout))
        self.layout = self._redo.pop()
        self._resolve_skin()
        return True
