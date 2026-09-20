"""utils/overlay_document.py - the Overlay Designer's editable template
model (overlay_rework.md Phase 1)."""
import copy
import glob
import json
from pathlib import Path

import pytest

from utils.overlay_document import OverlayDocument, TemplateRef

BUNDLED = sorted(glob.glob("overlays/templates/**/normal.json", recursive=True))


@pytest.mark.parametrize("path", BUNDLED)
def test_every_bundled_template_round_trips_key_for_key(path):
    doc = OverlayDocument.load(Path(path))
    with open(path) as f:
        original = json.load(f)
    assert doc.to_layout() == original
    assert doc.dirty is False
    saved = doc.to_layout(for_save=True)
    # for_save only normalises the skin path to a bare file name (already
    # the case in every bundled file) and rounds rel_x/rel_y to 5 decimals
    # (the generic depth_temp pages carry raw floats) - nothing else moves.
    assert saved["hud_skin"].get("path") == original["hud_skin"].get("path")
    for saved_elem, orig_elem in zip(saved["hud_skin"]["linked_elements"], original["hud_skin"]["linked_elements"]):
        for key in ("rel_x", "rel_y"):
            assert saved_elem[key] == round(orig_elem[key], 5)
        assert {k: v for k, v in saved_elem.items() if k not in ("rel_x", "rel_y")} == \
            {k: v for k, v in orig_elem.items() if k not in ("rel_x", "rel_y")}
    stripped = lambda layout: {k: v for k, v in layout.items() if k != "hud_skin"}
    assert stripped(saved) == stripped(original)


def test_image_skin_native_size_and_absolute_path():
    path = Path("overlays/templates/shearwater/perdix_2/main/single_tank/normal.json")
    doc = OverlayDocument.load(path, ref=TemplateRef("shearwater", "perdix_2", "main", "single_tank"))
    assert (doc.native_width, doc.native_height) == (917, 753)
    assert doc.skin_abs_path == (path.parent / "normal.png").resolve()
    assert doc.skin_native_size() == (917.0, 753.0)
    w, h = doc.skin_scaled_size()
    assert (round(w), round(h)) == (688, 565)  # x 0.75
    assert doc.ref.label == "shearwater/perdix_2/main/single_tank"
    # the layout itself never learns the absolute path or native size
    assert doc.layout["hud_skin"]["path"] == "normal.png"
    assert "native_width" not in doc.layout["hud_skin"]
    assert doc.render_layout()["hud_skin"]["path"] == str(doc.skin_abs_path)


def test_shape_skin_sizes():
    doc = OverlayDocument.load(Path("overlays/templates/generic/dive_profile/main/normal.json"))
    assert doc.skin_type == "shape"
    assert doc.skin_native_size() == (900.0, 220.0)
    assert doc.skin_scaled_size() == (900.0, 220.0)
    assert doc.skin_abs_path is None


def test_missing_skin_file_does_not_crash():
    doc = OverlayDocument({"hud_skin": {"type": "image", "path": "nope.png", "linked_elements": []}})
    assert (doc.native_width, doc.native_height) == (0, 0)
    assert doc.skin_native_size() == (0.0, 0.0)


def test_design_view_layout_image_uses_zoom_as_scale():
    doc = OverlayDocument.load(Path("overlays/templates/shearwater/perdix_2/main/single_tank/normal.json"))
    layout = doc.design_view_layout(2.0)
    assert layout["hud_skin"]["scale"] == 2.0
    assert Path(layout["hud_skin"]["path"]).is_absolute()
    assert doc.layout["hud_skin"]["scale"] == 0.75  # template untouched


def test_design_view_layout_shape_multiplies_dimensions_and_scale():
    doc = OverlayDocument({"hud_skin": {"type": "shape", "width": 400, "height": 200, "linked_elements": []}})
    layout = doc.design_view_layout(1.5)
    assert layout["hud_skin"]["width"] == 600 and layout["hud_skin"]["height"] == 300
    assert layout["hud_skin"]["scale"] == 1.5
    assert doc.layout["hud_skin"]["width"] == 400 and "scale" not in doc.layout["hud_skin"]


def test_to_layout_for_save_normalises_path_and_rounds():
    doc = OverlayDocument({
        "hud_skin": {
            "type": "image", "path": "/abs/dir/skin.png",
            "linked_elements": [{"field": "depth", "rel_x": 0.123456789, "rel_y": 0.5}],
        }
    })
    saved = doc.to_layout(for_save=True)
    assert saved["hud_skin"]["path"] == "skin.png"
    assert saved["hud_skin"]["linked_elements"][0]["rel_x"] == 0.12346
    assert doc.layout["hud_skin"]["path"] == "/abs/dir/skin.png"  # copy, not in place


def test_dirty_undo_redo():
    doc = OverlayDocument.load(Path("overlays/templates/generic/depth_temp/standard/normal.json"))
    original = copy.deepcopy(doc.layout)
    assert not doc.dirty and not doc.can_undo and not doc.can_redo

    doc.push_undo()
    doc.elements[0]["rel_x"] = 0.9
    assert doc.dirty and doc.can_undo

    assert doc.undo() is True
    assert doc.layout == original and not doc.dirty and doc.can_redo

    assert doc.redo() is True
    assert doc.elements[0]["rel_x"] == 0.9 and doc.dirty

    doc.mark_saved()
    assert not doc.dirty
    assert doc.undo() is True and doc.dirty  # undoing past the save point is dirty again
    assert doc.undo() is False  # stack exhausted


def test_undo_stack_is_capped():
    from utils.overlay_document import UNDO_LIMIT
    doc = OverlayDocument({"hud_skin": {"type": "shape", "linked_elements": []}})
    for i in range(UNDO_LIMIT + 10):
        doc.push_undo()
        doc.layout["counter"] = i
    assert len(doc._undo) == UNDO_LIMIT


# --- overlay_rework.md Phase 2: editing operations ---------------------------

def _perdix():
    return OverlayDocument.load(Path("overlays/templates/shearwater/perdix_2/main/single_tank/normal.json"),
                                ref=TemplateRef("shearwater", "perdix_2", "main", "single_tank"))


def test_add_remove_duplicate_elements_record_undo_steps():
    doc = _perdix()
    n = len(doc.elements)
    index = doc.add_element("temp")
    assert index == n and doc.elements[index]["field"] == "temp"
    assert doc.elements[index]["rel_x"] == 0.5 and doc.elements[index]["font_size"] == 30
    assert doc.dirty and doc.can_undo

    clone_index = doc.duplicate_element(index)
    assert clone_index == index + 1
    assert doc.elements[clone_index]["field"] == "temp"
    assert doc.elements[clone_index]["rel_x"] == pytest.approx(0.52)

    assert doc.remove_element(clone_index) is True
    assert doc.remove_element(999) is False
    assert len(doc.elements) == n + 1

    # three undo steps: remove, duplicate, add
    assert doc.undo() and doc.undo() and doc.undo()
    assert len(doc.elements) == n and not doc.dirty
    assert doc.undo() is False


def test_add_element_kinds_normalise_field_and_type():
    doc = _perdix()
    g = doc.add_element("depth_graph", "graph")
    b = doc.add_element("state_badge", "badge")
    t = doc.add_element("primary_tank_pressure", "tank_icon")
    assert doc.elements[g]["type"] == "graph" and doc.elements[g]["width"] == 300
    assert doc.elements[b]["type"] == "badge" and doc.elements[b]["value_font_size"] == 32
    assert doc.elements[t]["type"] == "tank_icon" and doc.elements[t]["corner_radius"] == 4


def test_move_nudge_and_position_px_round_trip_with_clamping():
    doc = _perdix()
    doc.move_element(0, 0.25, 0.75)
    assert (doc.elements[0]["rel_x"], doc.elements[0]["rel_y"]) == (0.25, 0.75)
    x, y = doc.element_position_px(0)
    assert (x, y) == (pytest.approx(917 * 0.25), pytest.approx(753 * 0.75))

    doc.nudge_element(0, 10, -5)
    nx, ny = doc.element_position_px(0)
    assert (nx, ny) == (pytest.approx(x + 10), pytest.approx(y - 5))

    doc.set_element_position_px(0, 917 * 5, -917 * 5)
    assert doc.elements[0]["rel_x"] == 1.5 and doc.elements[0]["rel_y"] == -0.5  # clamped

    doc.move_element(0, 0.1, 0.1, record_undo=False)
    undo_depth = len(doc._undo)
    doc.move_element(0, 0.2, 0.2, record_undo=False)
    assert len(doc._undo) == undo_depth  # streaming drag: no extra steps


def test_set_element_attr_semantics():
    doc = _perdix()
    doc.set_element_attr(0, "align", "right")
    assert doc.elements[0]["align"] == "right"
    steps = len(doc._undo)
    doc.set_element_attr(0, "align", "right")  # no-op: no undo step
    assert len(doc._undo) == steps
    doc.set_element_attr(0, "align", None)  # delete
    assert "align" not in doc.elements[0]
    doc.set_element_attr(0, "rel_x", 9.0)
    assert doc.elements[0]["rel_x"] == 1.5
    doc.set_element_attr(0, "type", "graph")  # type is derived, not settable
    assert "type" not in doc.elements[0]

    # field changes normalise the element type
    doc.set_element_attr(0, "field", "depth_graph")
    assert doc.elements[0]["type"] == "graph"
    doc.set_element_attr(0, "field", "state_badge")
    assert doc.elements[0]["type"] == "badge"
    doc.set_element_attr(0, "field", "temp")
    assert "type" not in doc.elements[0]
    doc.set_element_attr(999, "field", "temp")  # unknown index ignored


def test_reorder_element_moves_within_bounds():
    doc = _perdix()
    first = doc.elements[0]["field"]
    assert doc.reorder_element(0, 1) == 1 and doc.elements[1]["field"] == first
    assert doc.reorder_element(1, -5) == 0 and doc.elements[0]["field"] == first
    assert doc.reorder_element(0, 0) == 0
    assert doc.reorder_element(999, 1) == 999


def test_set_skin_attr_validates_anchor_and_protects_structure():
    doc = _perdix()
    doc.set_skin_attr("anchor", "TOP_RIGHT")
    assert doc.skin["anchor"] == "TOP_RIGHT"
    doc.set_skin_attr("anchor", "NOWHERE")
    assert doc.skin["anchor"] == "TOP_RIGHT"
    doc.set_skin_attr("opacity", 0.5)
    assert doc.skin["opacity"] == 0.5
    before = dict(doc.skin)
    doc.set_skin_attr("linked_elements", [])
    doc.set_skin_attr("type", "shape")
    doc.set_skin_attr("path", "x.png")
    assert doc.skin == before


def test_set_skin_image_replaces_path_and_native_size():
    doc = _perdix()
    other = Path("overlays/templates/garmin/x50i/main/single_tank/normal.png").resolve()
    assert doc.set_skin_image(other) is True
    assert doc.skin["path"] == str(other)
    assert (doc.native_width, doc.native_height) == (473, 301)
    assert doc.to_layout(for_save=True)["hud_skin"]["path"] == "normal.png"
    assert doc.set_skin_image(Path("nope.png")) is False
    assert doc.undo() and (doc.native_width, doc.native_height) == (917, 753)


def test_frame_box_matches_draw_hud_anchor_math():
    doc = _perdix()  # BOTTOM_LEFT, offset (16, -16), 917x753 @ 0.75
    assert doc.frame_box(1920, 1080) == (16.0, 500.0, 687.0, 564.0)
    # a 4K frame scales offsets and skin by res_scale = 2
    x, y, w, h = doc.frame_box(3840, 2160)
    assert (w, h) == (1375.0, 1129.0) and x == 32.0 and y == 2160 - 32 - 1129


def test_set_frame_position_is_the_inverse_of_frame_box():
    doc = _perdix()
    doc.set_frame_position(100, 200, 1920, 1080)
    assert doc.frame_box(1920, 1080)[:2] == (100.0, 200.0)
    doc.set_skin_attr("anchor", "CENTER")
    doc.set_frame_position(600, 300, 1920, 1080)
    assert doc.frame_box(1920, 1080)[:2] == (600.0, 300.0)
    assert doc.dirty
