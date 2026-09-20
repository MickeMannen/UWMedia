"""
Color page multi-overlay data model (ui_rework.md Pass 2, ported to the QML
backend per qml_development.md's Toga-removal cutover): the "Add HUD" picker's
actual add logic (_resolve_new_color_overlay + confirmAddHud), plus
persist/restore round-tripping through utils/app_settings.py, plus Pass 2's
4-corner drag/resize gesture math.

Driven against ColorBackend.__new__(ColorBackend) + PySide6's own
QObject.__init__ (skips ColorBackend.__init__'s body, which reads real
settings.json/does real file IO on construction by design for production
use - see tests/test_color_preview.py's own docstring for why plain
QObject.__new__() alone isn't enough, and why no QApplication instance is
needed either).

Two tests from the pre-QML version of this file are gone, not just
renamed: test_resolve_custom_path_bypasses_template_lookup and
test_resolve_custom_path_missing_file_returns_none. Add HUD's custom-path
escape hatch was deliberately deferred when ColorBackend was first built
(qml_development.md Phase 1 - see that module's own docstring, "cascade-only,
matching every other first-pass page's deliberately-deferred convention")
- _resolve_new_color_overlay only takes (brand, computer, page,
location_label) now, no custom_path parameter at all, so there's nothing
left for those two tests to exercise.

No FakeTable/FakeCanvas/FakeTextInput/FakeSwitch widget doubles needed
anymore - QML has no table/canvas widget, so the backend exposes
overlayLabels as a plain Property (derived straight from
color_overlay_instances) and removeOverlayAtIndex(row) takes a row index
directly; build args come from plain string/bool instance attributes
(_source_text/_color_checked/etc), not .value-wrapped fake widgets.
"""
import json
from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import QObject

import utils.app_settings as app_settings
from gui.hud_renderer import overlay_pixel_bbox
from utils.layouts import list_templates
from uwmedia.backends.color_backend import (
    _OPPOSITE_CORNER,
    PREVIEW_DISPLAY_WIDTH,
    PREVIEW_WORKING_WIDTH,
    ColorBackend,
)

BASE_DIR = Path(__file__).parent.parent


def make_fake_backend():
    app = ColorBackend.__new__(ColorBackend)
    QObject.__init__(app)  # valid QObject, but skips ColorBackend.__init__'s real-settings reads
    app._hud_templates = list_templates()
    app._color_overlay_layout_cache = {}
    app.color_overlay_instances = []
    app._color_overlay_next_id = 0
    app.color_selected_overlay_id = None
    app.preview_view_w = float(PREVIEW_WORKING_WIDTH)
    app.preview_view_h = float(PREVIEW_WORKING_WIDTH) * 9.0 / 16.0
    app.preview_frame = None
    app.preview_current_waypoint = None
    app.preview_current_dive = None
    app._drag_state = None
    app._drag_box = {"visible": False, "x": 0.0, "y": 0.0, "w": 0.0, "h": 0.0, "label": ""}
    app._preview_revision = 0
    return app


# --- _resolve_new_color_overlay: template resolution + seed placement -----

def test_resolve_from_template_returns_resolved_layout_and_label():
    app = make_fake_backend()
    instance = app._resolve_new_color_overlay("shearwater", "perdix_2", "tec", "Bottom Left")
    assert instance is not None
    assert instance["layout_path"].exists()
    assert instance["label"] == "Shearwater Perdix 2 - Tec"
    assert instance["scale"] == 1.0
    assert instance["id"] == 0


def test_resolve_from_template_writes_a_temp_copy_not_the_bundled_file():
    """Regression: must never return the real bundled template path directly
    - cli_main.py's own relative-skin-path resolution (see
    resolve_layout_relative_skin) mutates a --overlays-file entry's JSON in
    place, which would otherwise permanently corrupt the shipped template on
    the very first real run that used it (caught during Pass 2 development -
    an early test run against the real bundled perdix_2 file rewrote it on
    disk before validation even failed)."""
    from utils.layouts import resolve_template_state

    app = make_fake_backend()
    bundled_path = resolve_template_state("shearwater", "perdix_2", "tec")
    assert bundled_path is not None

    instance = app._resolve_new_color_overlay("shearwater", "perdix_2", "tec", "Bottom Left")
    assert instance["layout_path"] != bundled_path
    assert instance["layout_path"].parent != bundled_path.parent
    # And the bundled file itself must be untouched by the resolve call.
    bundled_mtime_before = bundled_path.stat().st_mtime
    app._resolve_new_color_overlay("shearwater", "perdix_2", "tec", "Bottom Left")
    assert bundled_path.stat().st_mtime == bundled_mtime_before


def test_resolve_missing_choice_returns_none():
    app = make_fake_backend()
    assert app._resolve_new_color_overlay(None, None, None, "Bottom Left") is None
    assert app._resolve_new_color_overlay("shearwater", "perdix_2", "does_not_exist", "Bottom Left") is None


@pytest.mark.parametrize(
    "location_label,expect_x_near,expect_y_near",
    [
        ("Top Left", 0.0, 0.0),
        ("Top Right", 1.0, 0.0),
        ("Bottom Left", 0.0, 1.0),
        ("Bottom Right", 1.0, 1.0),
        ("Center", 0.5, 0.5),
    ],
)
def test_resolve_seeds_xy_from_location_preset(location_label, expect_x_near, expect_y_near):
    app = make_fake_backend()
    instance = app._resolve_new_color_overlay("shearwater", "perdix_2", "tec", location_label)
    assert instance is not None
    # The seeded corner should be within one overlay-width/height of the
    # named edge (exact value depends on the skin's own pixel size, which
    # this test isn't pinning down - just the general corner/edge/center).
    assert abs(instance["x"] - expect_x_near) <= 0.6
    assert abs(instance["y"] - expect_y_near) <= 0.6
    if expect_x_near == 0.0:
        assert instance["x"] == 0.0
    if expect_y_near == 0.0:
        assert instance["y"] == 0.0


def test_resolve_always_seeds_natural_scale():
    """No Size step any more (dropped in favor of drag-to-resize after
    placement) - every newly resolved overlay always seeds at scale=1.0."""
    app = make_fake_backend()
    instance = app._resolve_new_color_overlay("shearwater", "perdix_2", "tec", "Top Left")
    assert instance["scale"] == 1.0


# --- confirmAddHud: resolve + append + id/persist/redraw wiring -----------

def test_confirm_add_hud_appends_in_order_and_increments_id():
    app = make_fake_backend()
    calls = {"persist": 0, "redraw": 0}
    app._persist_overlay_instances = lambda: calls.__setitem__("persist", calls["persist"] + 1)
    app._redraw_preview = lambda: calls.__setitem__("redraw", calls["redraw"] + 1)

    app._selected_brand_key = "shearwater"
    app._selected_computer_key = "perdix_2"
    app._selected_page_id = "tec"
    assert app.confirmAddHud() is True

    app._selected_brand_key = "generic"
    app._selected_computer_key = "depth_temp"
    app._selected_page_id = "compact"
    assert app.confirmAddHud() is True

    assert [inst["id"] for inst in app.color_overlay_instances] == [0, 1]
    # List order = z-order (last added drawn last = on top) - confirmed by
    # construction, not re-derived here.
    assert app.color_overlay_instances[0]["label"] == "Shearwater Perdix 2 - Tec"
    assert calls == {"persist": 2, "redraw": 2}


def test_confirm_add_hud_returns_false_and_sets_error_when_unresolvable():
    app = make_fake_backend()
    app._persist_overlay_instances = lambda: None
    app._redraw_preview = lambda: None
    app._selected_brand_key = None
    app._selected_computer_key = None
    app._selected_page_id = None

    assert app.confirmAddHud() is False
    assert app.addHudError != ""
    assert app.color_overlay_instances == []


def test_overlay_labels_reflects_instances():
    app = make_fake_backend()
    app.color_overlay_instances = [
        {"id": 0, "layout_path": Path("a.json"), "label": "A", "x": 0.0, "y": 0.0, "scale": 1.0},
        {"id": 1, "layout_path": Path("b.json"), "label": "B", "x": 0.0, "y": 0.0, "scale": 1.0},
    ]
    assert app.overlayLabels == ["A", "B"]


def test_remove_overlay_at_index_deletes_row():
    app = make_fake_backend()
    app.color_overlay_instances = [
        {"id": 0, "layout_path": Path("a.json"), "label": "A", "x": 0.0, "y": 0.0, "scale": 1.0},
        {"id": 1, "layout_path": Path("b.json"), "label": "B", "x": 0.0, "y": 0.0, "scale": 1.0},
    ]
    app._persist_overlay_instances = lambda: None

    app.removeOverlayAtIndex(0)

    assert len(app.color_overlay_instances) == 1
    assert app.color_overlay_instances[0]["label"] == "B"


# --- persist / restore round trip through utils/app_settings.py -----------

def test_persist_and_restore_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(app_settings, "settings_path", lambda: tmp_path / "settings.json")

    app = make_fake_backend()
    instance = app._resolve_new_color_overlay("shearwater", "perdix_2", "tec", "Top Left")
    app.color_overlay_instances = [instance]

    app._persist_overlay_instances()

    restored_app = make_fake_backend()
    restored_app._restore_overlay_instances()

    assert len(restored_app.color_overlay_instances) == 1
    restored = restored_app.color_overlay_instances[0]
    assert restored["layout_path"] == instance["layout_path"]
    assert restored["label"] == instance["label"]
    assert restored["x"] == instance["x"]
    assert restored["y"] == instance["y"]
    assert restored["scale"] == instance["scale"]
    assert restored["id"] == 0  # regenerated in-session, not persisted


def test_restore_skips_instance_with_missing_layout_file(tmp_path, monkeypatch):
    monkeypatch.setattr(app_settings, "settings_path", lambda: tmp_path / "settings.json")
    app_settings.set_field("color_overlay_instances", [
        {"layout_path": "/does/not/exist.json", "label": "Ghost", "x": 0.1, "y": 0.1, "scale": 1.0},
    ])

    app = make_fake_backend()
    app._restore_overlay_instances()

    assert app.color_overlay_instances == []


# --- Phase 3: selection + 4-corner drag/resize gesture math ----------------

def _make_shape_layout_file(tmp_path, name="layout.json", width=200, height=100):
    path = tmp_path / name
    path.write_text(json.dumps({
        "design_width": 1920,
        "hud_skin": {"type": "shape", "width": width, "height": height, "color": "#ff0000", "opacity": 1.0},
    }))
    return path


def _make_drag_test_app(tmp_path):
    app = make_fake_backend()
    # 1920x1080 working frame -> canvas display is PREVIEW_DISPLAY_WIDTH
    # wide, proportionally scaled tall.
    app.preview_view_w = 1920.0
    app.preview_view_h = 1080.0
    app._persist_overlay_instances = lambda: None
    app._redraw_preview = lambda: None
    layout_path = _make_shape_layout_file(tmp_path)
    instance = {"id": 0, "layout_path": layout_path, "label": "Test", "x": 0.1, "y": 0.1, "scale": 1.0}
    app.color_overlay_instances = [instance]
    return app, instance


# Overlay's frame-pixel bbox: x0=192,y0=108 (0.1*1920, 0.1*1080), w=200,
# h=100 (design_width==frame_w so res_scale==1) -> x1=392,y1=208.
_DISPLAY_SCALE = PREVIEW_DISPLAY_WIDTH / 1920.0


def test_hit_test_body_hit_when_nothing_selected(tmp_path):
    app, instance = _make_drag_test_app(tmp_path)
    body_hit = app._hit_test_overlay(300 * _DISPLAY_SCALE, 150 * _DISPLAY_SCALE)
    assert body_hit == (instance, "move", None)

    miss = app._hit_test_overlay(10 * _DISPLAY_SCALE, 10 * _DISPLAY_SCALE)
    assert miss is None


@pytest.mark.parametrize(
    "corner,point",
    [("top_left", (192, 108)), ("top_right", (392, 108)), ("bottom_left", (192, 208)), ("bottom_right", (392, 208))],
)
def test_hit_test_corner_handles_active_only_once_selected(tmp_path, corner, point):
    app, instance = _make_drag_test_app(tmp_path)
    px, py = point[0] * _DISPLAY_SCALE, point[1] * _DISPLAY_SCALE

    # Not selected yet - a press at a corner point still just hits the body
    # (it's on the bbox boundary), no resize handles are active.
    assert app._hit_test_overlay(px, py) == (instance, "move", None)

    app.color_selected_overlay_id = instance["id"]
    assert app._hit_test_overlay(px, py) == (instance, "resize", corner)


def test_press_on_unselected_overlay_selects_it_immediately(tmp_path):
    app, instance = _make_drag_test_app(tmp_path)
    redraws = {"count": 0}
    app._redraw_preview = lambda: redraws.__setitem__("count", redraws["count"] + 1)

    app.onPreviewPressed(300 * _DISPLAY_SCALE, 150 * _DISPLAY_SCALE)

    assert app.color_selected_overlay_id == instance["id"]
    assert redraws["count"] == 1  # selection shown before any drag


def test_press_on_empty_canvas_deselects(tmp_path):
    app, instance = _make_drag_test_app(tmp_path)
    app.color_selected_overlay_id = instance["id"]
    redraws = {"count": 0}
    app._redraw_preview = lambda: redraws.__setitem__("count", redraws["count"] + 1)

    app.onPreviewPressed(1.0, 1.0)

    assert app.color_selected_overlay_id is None
    assert redraws["count"] == 1


def test_press_then_drag_moves_overlay(tmp_path):
    app, instance = _make_drag_test_app(tmp_path)
    press_x, press_y = 300 * _DISPLAY_SCALE, 150 * _DISPLAY_SCALE

    app.onPreviewPressed(press_x, press_y)
    assert app._drag_state is not None
    assert app._drag_state["mode"] == "move"

    # Drag 100 display px right - should shift x by 100/PREVIEW_DISPLAY_WIDTH.
    app.onPreviewDragged(press_x + 100, press_y)
    assert instance["x"] == pytest.approx(0.1 + 100 / PREVIEW_DISPLAY_WIDTH)
    assert instance["y"] == pytest.approx(0.1)  # unchanged - drag was x-only


@pytest.mark.parametrize("corner", ["top_left", "top_right", "bottom_left", "bottom_right"])
def test_resize_from_each_corner_keeps_opposite_corner_fixed(tmp_path, corner):
    app, instance = _make_drag_test_app(tmp_path)
    raw_layout = app._load_overlay_layout(instance["layout_path"])
    bbox_before = overlay_pixel_bbox(raw_layout, instance["x"], instance["y"], instance["scale"], 1920, 1080)
    corners_before = app._corner_points(bbox_before)
    opposite = _OPPOSITE_CORNER[corner]
    anchor_before = corners_before[opposite]
    press_point = corners_before[corner]

    # Select the overlay first (plain click, no drag) - matches the real
    # "select, then drag a handle" UX; handles are only active once selected.
    cx = (bbox_before[0] + bbox_before[2]) / 2 * _DISPLAY_SCALE
    cy = (bbox_before[1] + bbox_before[3]) / 2 * _DISPLAY_SCALE
    app.onPreviewPressed(cx, cy)
    app.onPreviewReleased()
    assert app.color_selected_overlay_id == instance["id"]

    press_x, press_y = press_point[0] * _DISPLAY_SCALE, press_point[1] * _DISPLAY_SCALE
    app.onPreviewPressed(press_x, press_y)
    assert app._drag_state["mode"] == "resize"
    assert app._drag_state["corner"] == corner

    # Drag straight away from the anchor to roughly double the box size.
    drag_x = press_x + (press_point[0] - anchor_before[0]) * _DISPLAY_SCALE
    drag_y = press_y + (press_point[1] - anchor_before[1]) * _DISPLAY_SCALE
    app.onPreviewDragged(drag_x, drag_y)

    bbox_after = overlay_pixel_bbox(raw_layout, instance["x"], instance["y"], instance["scale"], 1920, 1080)
    corners_after = app._corner_points(bbox_after)
    # abs=1.5, not a tighter pixel-exact bound: the frame-px -> display-px
    # -> frame-px round trip goes through a couple of int() truncations
    # (see overlay_pixel_bbox/_hit_test_overlay), so a sub-2px drift at any
    # given PREVIEW_DISPLAY_WIDTH is expected rounding noise, not a real
    # anchor-drift bug.
    assert corners_after[opposite] == pytest.approx(anchor_before, abs=1.5)
    assert instance["scale"] > 1.0  # grew, since we dragged away from the anchor


def test_release_clears_state_and_persists(tmp_path):
    app, instance = _make_drag_test_app(tmp_path)
    persisted = {"count": 0}
    app._persist_overlay_instances = lambda: persisted.__setitem__("count", persisted["count"] + 1)

    app.onPreviewPressed(300 * _DISPLAY_SCALE, 150 * _DISPLAY_SCALE)
    app.onPreviewReleased()

    assert app._drag_state is None
    assert persisted["count"] == 1


def test_press_outside_any_overlay_leaves_no_drag_state(tmp_path):
    app, instance = _make_drag_test_app(tmp_path)
    app.onPreviewPressed(1.0, 1.0)
    assert app._drag_state is None


def test_render_current_frame_with_selection_draws_without_crashing(tmp_path):
    """Smoke test for the real render_current_frame path (every other test
    overrides _redraw_preview with a no-op) - a selected overlay must render
    its blue frame + corner handles without raising."""
    app, instance = _make_drag_test_app(tmp_path)
    app.preview_frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    app.color_selected_overlay_id = instance["id"]

    qimage = app.render_current_frame()

    assert qimage.width() == 1920
    assert qimage.height() == 1080


def test_remove_overlay_clears_selection_if_removed(tmp_path):
    app, instance = _make_drag_test_app(tmp_path)
    app.color_selected_overlay_id = instance["id"]

    app.removeOverlayAtIndex(0)

    assert app.color_selected_overlay_id is None


# --- _build_args(): --overlays-file wiring (Pass 2's Start-button plumbing) -

def _make_build_args_backend(overlay_instances):
    app = make_fake_backend()
    app._source_text = "/tmp/source.mp4"
    app._output_text = "/tmp/out"
    app._logs_text = ""
    app._color_checked = False
    app._color_profile = "default"
    app._filename_format_by_label = {"": ""}
    app._filename_format = ""
    app._hw_accel = True
    app.color_overlay_instances = overlay_instances
    return app


def test_build_args_omits_overlays_file_when_no_overlays():
    app = _make_build_args_backend([])
    args = app._build_args()
    assert "--overlays-file" not in args


def test_build_args_includes_overlays_file_with_correct_content(tmp_path):
    layout_path = _make_shape_layout_file(tmp_path)
    instances = [{"id": 0, "layout_path": layout_path, "label": "X", "x": 0.2, "y": 0.3, "scale": 1.1}]
    app = _make_build_args_backend(instances)

    args = app._build_args()

    assert "--overlays-file" in args
    overlays_path = Path(args[args.index("--overlays-file") + 1])
    assert overlays_path.exists()
    written = json.loads(overlays_path.read_text())
    assert written == [{"layout_path": str(layout_path), "x": 0.2, "y": 0.3, "scale": 1.1}]


# --overlays-file wasn't the only long-deferred flag never actually wired
# up: --hw-accel was too (color_page.py's own docstring flagged it as
# deferred pending the Advanced page's existence - the Advanced page has
# existed for a while, but nothing ever went back and read its hwAccel
# toggle when building the Start button's real subprocess args, so every
# Color-page batch silently ran in pure software encoding regardless of
# that toggle - found while the user was wondering why a real batch was
# slow). Now a Property on ColorBackend itself (moved off the Advanced
# page per the user's follow-up request) - _build_args reads the plain
# instance attribute, no get_fields() monkeypatching needed any more.

def test_build_args_includes_hw_accel_when_enabled():
    app = _make_build_args_backend([])
    app._hw_accel = True

    assert "--hw-accel" in app._build_args()


def test_build_args_omits_hw_accel_when_disabled():
    app = _make_build_args_backend([])
    app._hw_accel = False

    assert "--hw-accel" not in app._build_args()
