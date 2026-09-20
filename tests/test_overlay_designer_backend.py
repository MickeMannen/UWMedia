"""
Exercises the Overlay Designer backend (uwmedia/backends/
overlay_designer_backend.py) - overlay_rework.md Phase 1. The 13 selector/
log-preview tests that came along from the old read-only page (formerly
tests/test_hud_selector.py) were migrated to the new API here (decision Q13:
no legacy attribute aliases): `document` (an OverlayDocument) replaces the
bare `designer_layout` dict and the `designer_*` attributes lost their
prefix (current_dive/current_waypoint/dive_manager/video_cap/bg_frame/
preview_from_log/log_file_choices). Selection plumbing is unchanged: the
backend's own @Slot methods take the display string directly.

OverlayDesignerBackend() is safe to construct - and render_current_frame()
safe to call - directly in tests without a QApplication: __init__ only reads
bundled template files (list_templates/resolve_template_state), never user
settings.json/QFileDialog, and QImage construction from a numpy buffer
needs no GUI application instance.
"""
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

from models.dive import Dive, Waypoint
from models.manager import DiveManager
from utils.dummy_telemetry import DUMMY_DURATION_S
from uwmedia.backends.overlay_designer_backend import (
    FRAME_H,
    FRAME_W,
    ZOOM_MAX,
    ZOOM_MIN,
    OverlayDesignerBackend,
)


def _select_garmin_x50i_main(app):
    app.onBrandSelected("Garmin")
    # Garmin has two computers (x50i, mk3i), so the default pick after
    # selecting the brand is not guaranteed to be x50i; select it explicitly.
    app.onComputerSelected(
        next(name for name, cid in app._computer_choices.items() if cid == "x50i")
    )
    app.onPageSelected(
        next(name for name, pid in app._page_choices.items() if pid == "main")
    )


def _fields(app):
    return {e.get("field") for e in app.document.elements}


# -- Variant resolution (migrated) ------------------------------------------

def test_no_dive_loaded_defaults_to_single_tank_variant():
    app = OverlayDesignerBackend()
    app.current_dive = None
    _select_garmin_x50i_main(app)
    # resolve_tank_variant(None) -> "single_tank", one of this page's real
    # variants, so that's what gets picked rather than variants[0]'s
    # alphabetical "sidemount".
    assert app.document.ref.variant == "single_tank"
    assert "secondary_tank_name" not in _fields(app)
    assert "primary_tank_name" in _fields(app)


def test_single_tank_dive_resolves_single_tank_variant():
    app = OverlayDesignerBackend()
    app.current_dive = MagicMock(waypoints=[MagicMock(tanks={"Micke01": object()})])
    _select_garmin_x50i_main(app)
    assert app.document.ref.variant == "single_tank"
    assert "secondary_tank_name" not in _fields(app)


def test_sidemount_dive_resolves_sidemount_variant():
    app = OverlayDesignerBackend()
    app.current_dive = MagicMock(
        waypoints=[MagicMock(tanks={"Micke01": object(), "Micke02": object()})]
    )
    _select_garmin_x50i_main(app)
    assert app.document.ref.variant == "sidemount"
    assert "secondary_tank_name" in _fields(app)


def test_variant_combo_lists_page_variants_and_overrides_auto_pick():
    app = OverlayDesignerBackend()
    _select_garmin_x50i_main(app)
    assert app.variantVisible is True
    assert app.variantList == ["Sidemount", "Single Tank"]
    assert app.variantIndex == 1  # auto-picked single_tank

    app.onVariantSelected("Sidemount")
    assert app.document.ref.variant == "sidemount"
    assert app.variantIndex == 0
    # the dummy dive follows the variant so the second tank renders
    assert all(len(w.tanks) == 2 for w in app.dummy_dive.waypoints)

    # a page without variants hides the combo
    app.onPageSelected(next(name for name, pid in app._page_choices.items() if pid == "gases"))
    assert app.variantVisible is False and app.document.ref.variant is None


# -- Standalone canvas (new in Phase 1) ---------------------------------------

def test_default_canvas_is_populated_without_any_media_or_log():
    app = OverlayDesignerBackend()
    assert app.document is not None
    assert app.bg_frame is None and app.current_dive is None
    assert app.viewMode == "design" and app.zoomIsFit is True
    assert app.telemetrySource == "dummy" and app.logTelemetryAvailable is False
    assert app.timeEnabled is True and app.timeMax == DUMMY_DURATION_S
    assert "Dummy telemetry" in app.dataText and "Depth 24.0 m" in app.dataText

    img = app.render_current_frame()
    assert (img.width(), img.height()) == (app.canvasDisplayWidth, app.canvasDisplayHeight)
    assert img.width() > 1 and img.height() > 1


def test_render_without_document_returns_placeholder():
    app = OverlayDesignerBackend()
    app.document = None
    img = app.render_current_frame()
    assert (img.width(), img.height()) == (1, 1)


def test_design_view_renders_skin_at_native_size_times_zoom():
    app = OverlayDesignerBackend()
    app.onBrandSelected("Shearwater")  # perdix_2 main single_tank: 917x753 native
    app.setZoomPercent(100)
    assert app.zoomIsFit is False
    img = app.render_current_frame()
    assert (img.width(), img.height()) == (917, 753)
    assert (app.canvasDisplayWidth, app.canvasDisplayHeight) == (917, 753)

    app.setZoomPercent(50)
    img = app.render_current_frame()
    assert (img.width(), img.height()) == (458, 376)  # rounded


def test_frame_preview_renders_full_frame_on_synthetic_background():
    app = OverlayDesignerBackend()
    app.setViewMode("frame")
    img = app.render_current_frame()
    assert (img.width(), img.height()) == (FRAME_W, FRAME_H)
    # display size follows zoom, not render size
    app.setZoomPercent(50)
    assert (app.canvasDisplayWidth, app.canvasDisplayHeight) == (960, 540)
    assert (app.render_current_frame().width(), app.render_current_frame().height()) == (FRAME_W, FRAME_H)


def test_zoom_fit_tracks_viewport_and_explicit_zoom_clamps():
    app = OverlayDesignerBackend()  # mk3i main: 692x922 native
    app.setViewportSize(400, 400)
    assert app.zoomIsFit is True
    assert app.zoomPercent == round(min(400 / 692, 400 / 922) * 100)

    app.setZoomPercent(200)
    assert app.zoomIsFit is False and app.canvasDisplayWidth == 1384
    app.setViewportSize(300, 300)  # ignored while not in fit mode
    assert app.zoomPercent == 200

    app.setZoomPercent(10 ** 6)
    assert app.zoom == ZOOM_MAX
    app.setZoomPercent(1)
    assert app.zoom == ZOOM_MIN
    app.zoomIn()
    assert app.zoomPercent == 50
    app.zoomOut()
    assert app.zoomPercent == 25

    app.zoomFit()
    assert app.zoomIsFit is True


def test_time_slider_scrubs_dummy_dive():
    app = OverlayDesignerBackend()
    revision = app._preview_revision
    app.onTimeChanged(0)
    assert "Depth 0.0 m" in app.dataText and app.timeText == "0:00:00"
    app.onTimeChanged(10 * 60)
    assert "Depth 24.0 m" in app.dataText
    assert app._preview_revision == revision + 2


def test_state_selector_forces_resolved_state():
    app = OverlayDesignerBackend()
    assert app.stateIndex == 0 and app.stateList[0].startswith("Auto")
    app.onStateSelected("Deco")
    assert "State: deco" in app.dataText and app.stateIndex == 3
    app.onStateSelected("Safety stop")
    assert "State: safety_stop" in app.dataText
    app.onStateSelected("Auto (from data)")
    assert "State: normal" in app.dataText


def test_telemetry_source_cannot_switch_to_log_without_a_dive():
    app = OverlayDesignerBackend()
    app.setTelemetrySource("log")
    assert app.telemetrySource == "dummy"


def test_element_list_and_template_title_describe_document():
    app = OverlayDesignerBackend()
    assert app.hasDocument is True
    assert "Garmin" in app.templateTitle and "Main Screen" in app.templateTitle
    assert len(app.elementList) == len(app.document.elements) > 0
    assert "Image 692×922 px" in app.skinInfoText


# -- Media loading (migrated) -------------------------------------------------

def test_load_image_falls_back_to_pillow_for_cv2_unreadable_bmp():
    # Some real-world BMP exports decode fine in Pillow but return None from
    # cv2.imread - _load_image should fall back rather than give up.
    app = OverlayDesignerBackend()
    bmp_path = Path("test_data/dive_computers/garmin_x50i/x50i_page1_single_tank.bmp")
    assert bmp_path.exists()

    app._load_image(bmp_path)

    assert app.bg_frame is not None
    assert app.hasBackground is True
    assert app.timeText == "Photo Mode"

    app.setViewMode("frame")
    img = app.render_current_frame()
    assert img.width() == FRAME_W and img.height() == int(app.view_h)

    app.clearBackground()
    assert app.bg_frame is None and app.hasBackground is False
    assert app.timeMax == DUMMY_DURATION_S and app.timeEnabled is True
    assert (app.view_w, app.view_h) == (FRAME_W, FRAME_H)


# -- Preview a log file directly, no video (migrated) -------------------------

def _make_dive(log_filename, start_time, times, device="descent_mk3i", manufactor="Garmin"):
    waypoints = [
        Waypoint(timestamp=start_time + timedelta(seconds=t), time_since_start=t, depth=float(t), temp=20.0)
        for t in times
    ]
    return Dive(
        start_time=start_time,
        end_time=start_time + timedelta(seconds=times[-1]),
        waypoints=waypoints,
        log_filename=log_filename,
        device=device,
        manufactor=manufactor,
    )


def test_refresh_log_file_choices_labels_and_disambiguates():
    app = OverlayDesignerBackend()
    app.dive_manager = DiveManager()
    dive_a = _make_dive("005.fit", datetime(2026, 1, 1, 8, 0), [0, 60, 120])
    # Same log_filename/day as dive_a on purpose, to exercise disambiguation
    dive_b = _make_dive("005.fit", datetime(2026, 1, 1, 8, 0), [0, 60])
    app.dive_manager.add_dives([dive_a, dive_b])

    app._refresh_log_file_choices()

    assert app.logFileEnabled is True
    assert len(app.logFileList) == 2
    assert len(set(app.logFileList)) == 2  # labels are unique
    values = list(app.log_file_choices.values())
    assert dive_a in values and dive_b in values


def test_refresh_log_file_choices_empty_manager_disables_select():
    app = OverlayDesignerBackend()
    app.dive_manager = DiveManager()

    app._refresh_log_file_choices()

    assert app.logFileEnabled is False
    assert app.logFileList == []


def test_log_file_change_enters_preview_mode_without_video():
    dive = _make_dive("413.fit", datetime(2026, 1, 1, 8, 0), [0, 60, 300])
    app = OverlayDesignerBackend()
    app.log_file_choices = {"the label": dive}
    app.video_cap = MagicMock()

    app.onLogFileSelected("the label")

    assert app.preview_from_log is True
    assert app.current_dive is dive
    assert app.video_cap is None  # released and cleared
    assert app.bg_frame is None  # synthetic backdrop, no flat grey frame any more
    assert app.timeMax == 300
    assert app.current_waypoint.time_since_start == 0  # scrubbed to 0 on entry
    assert app.telemetrySource == "log" and app.logTelemetryAvailable is True
    assert "Log telemetry" in app.dataText and "Depth 0.0 m" in app.dataText

    # and the user can flip back to dummy telemetry while keeping the log
    app.setTelemetrySource("dummy")
    assert app.telemetrySource == "dummy" and "Dummy telemetry" in app.dataText


def test_log_file_change_ignores_unknown_selection():
    app = OverlayDesignerBackend()
    app.log_file_choices = {}  # nothing registered under this label

    app.onLogFileSelected("the label")

    assert app.preview_from_log is False
    assert app.current_dive is None


def test_sync_data_to_frame_by_dive_time_finds_nearest_waypoint():
    dive = _make_dive("413.fit", datetime(2026, 1, 1, 8, 0), [0, 60, 120, 300])
    app = OverlayDesignerBackend()
    app.current_dive = dive
    app.current_waypoint = None

    app._sync_data_to_frame_by_dive_time(90)
    assert app.current_waypoint.time_since_start == 120  # first wp >= 90

    app._sync_data_to_frame_by_dive_time(0)
    assert app.current_waypoint.time_since_start == 0

    # Past the last waypoint - falls back to the last one rather than "no match"
    app._sync_data_to_frame_by_dive_time(9999)
    assert app.current_waypoint.time_since_start == 300


def test_time_change_uses_dive_time_when_previewing_from_log():
    dive = _make_dive("413.fit", datetime(2026, 1, 1, 8, 0), [0, 60, 120])
    app = OverlayDesignerBackend()
    app.preview_from_log = True
    app.current_dive = dive
    app.current_waypoint = None
    app.video_cap = None

    revision_before = app._preview_revision
    app.onTimeChanged(60)

    assert app.current_waypoint.time_since_start == 60
    assert app._preview_revision == revision_before + 1


def test_out_of_range_log_waypoint_falls_back_to_dummy_for_rendering():
    app = OverlayDesignerBackend()
    app.current_dive = _make_dive("413.fit", datetime(2026, 1, 1, 8, 0), [0, 60])
    app.current_waypoint = None
    app._telemetry_source = "log"
    wp, waypoints = app._telemetry_for_render()
    assert wp is not None and wp.log_filename == "dummy_telemetry"
    assert waypoints is app.current_dive.waypoints
    app._update_data_text()
    assert "Out of dive range" in app.dataText


# -- Editing (Phase 2) ----------------------------------------------------------

def _perdix_at_100(app):
    app.onBrandSelected("Shearwater")  # perdix_2 main single_tank, 917x753 native
    app.setZoomPercent(100)
    return app


def test_elements_model_and_selection_slots():
    app = _perdix_at_100(OverlayDesignerBackend())
    rows = app.elements
    assert rows[0] == {"index": 0, "field": "depth", "kind": "text", "label": "depth", "hidden": False}
    assert any(r["kind"] == "badge" for r in rows) and any(r["kind"] == "tank_icon" for r in rows)
    assert app.hasSelection is False and app.selectedElement["index"] == -1
    assert app.selectedElement["color"] == "#FFFFFF"  # defaults, never undefined

    app.selectElement(3)
    assert app.selectedIndex == 3 and app.hasSelection and app.selectionBoxVisible
    assert app.selectionBoxLabel == "dive_time"
    app.selectSkin()
    assert app.skinSelected and app.selectedIndex == -1 and app.selectionBoxLabel == "Skin"
    assert (app.selectionBoxW, app.selectionBoxH) == (917.0, 753.0)
    app.clearSelection()
    assert not app.hasSelection and not app.selectionBoxVisible
    app.selectElement(999)
    assert not app.hasSelection


def test_press_hits_element_drag_moves_it_in_one_undo_step():
    app = _perdix_at_100(OverlayDesignerBackend())
    boxes = app.elementBoxes
    x, y, w, h = boxes[0]  # depth
    app.onCanvasPressed(x + w / 2, y + h / 2)
    assert app.selectedIndex == 0 and app.isDirty is False
    before = app.selectedElement["x_px"], app.selectedElement["y_px"]
    revision = app._preview_revision

    app.onCanvasDragged(x + w / 2 + 30, y + h / 2 + 12)
    app.onCanvasDragged(x + w / 2 + 40, y + h / 2 + 20)
    assert app._preview_revision == revision  # no re-render while dragging
    app.onCanvasReleased()
    assert app._preview_revision == revision + 1
    after = app.selectedElement["x_px"], app.selectedElement["y_px"]
    assert after == (pytest.approx(before[0] + 40, abs=0.2), pytest.approx(before[1] + 20, abs=0.2))
    assert app.isDirty and app.canUndo
    app.undo()
    assert (app.selectedElement["x_px"], app.selectedElement["y_px"]) == before
    assert not app.canUndo and app.canRedo
    app.redo()
    assert app.selectedElement["x_px"] == pytest.approx(after[0], abs=0.2)


def test_press_on_empty_skin_selects_skin_and_click_without_move_is_not_an_edit():
    app = _perdix_at_100(OverlayDesignerBackend())
    app.onCanvasPressed(5, 5)
    app.onCanvasReleased()
    assert app.skinSelected and not app.isDirty and not app.canUndo
    app.onCanvasPressed(-50, -50)  # outside the skin entirely
    assert not app.hasSelection


def test_nudge_and_inspector_position_edits():
    app = _perdix_at_100(OverlayDesignerBackend())
    app.selectElement(0)
    x, y = app.selectedElement["x_px"], app.selectedElement["y_px"]
    app.nudgeSelected(-10, 5)
    assert (app.selectedElement["x_px"], app.selectedElement["y_px"]) == (pytest.approx(x - 10, abs=0.1), pytest.approx(y + 5, abs=0.1))
    app.setSelectedAttr("x_px", "300")
    app.setSelectedAttr("y_px", "  150.5 ")
    assert (app.selectedElement["x_px"], app.selectedElement["y_px"]) == (300.0, 150.5)
    app.setSelectedAttr("x_px", "not a number")
    assert app.selectedElement["x_px"] == 300.0


def test_inspector_attribute_edits_store_non_defaults_only():
    app = _perdix_at_100(OverlayDesignerBackend())
    app.selectElement(0)
    elem = app.document.elements[0]
    app.setSelectedAttr("align", "right")
    app.setSelectedAttr("valign", "middle")
    app.setSelectedAttr("bold", True)
    app.setSelectedAttr("font_family", "Roboto")
    app.setSelectedAttr("outline", False)
    app.setSelectedAttr("font_size", "90.4")
    app.setSelectedAttr("scale", "1.25")
    app.setSelectedAttr("color", "#00ADED")
    assert elem["align"] == "right" and elem["valign"] == "middle"
    assert elem["font_weight"] == "bold" and elem["font_family"] == "Roboto" and elem["outline"] is False
    assert elem["font_size"] == 90 and elem["scale"] == 1.25 and elem["color"] == "#00ADED"
    sel = app.selectedElement
    assert sel["bold"] is True and sel["font_family"] == "Roboto" and sel["outline"] is False

    # back to defaults -> keys removed, not written as defaults
    app.setSelectedAttr("align", "left")
    app.setSelectedAttr("valign", "top")
    app.setSelectedAttr("bold", False)
    app.setSelectedAttr("font_family", "Arial")
    app.setSelectedAttr("outline", True)
    for key in ("align", "valign", "font_weight", "font_family", "outline"):
        assert key not in elem
    app.setSelectedAttr("align", "diagonal")  # rejected
    assert "align" not in elem
    app.setSelectedAttr("font_size", "0")
    assert elem["font_size"] == 1  # clamped


def test_custom_label_text_and_field_changes():
    app = _perdix_at_100(OverlayDesignerBackend())
    app.addCustomLabel("  BAR ")
    assert app.selectedElement["is_custom"] and app.selectedElement["custom_text"] == "BAR"
    app.setSelectedAttr("custom_text", "PSI")
    assert app.document.elements[app.selectedIndex]["field"] == "custom:PSI"
    app.addCustomLabel("   ")  # ignored
    assert app.document.elements[app.selectedIndex]["field"] == "custom:PSI"
    app.setSelectedAttr("field", "temp")
    assert app.selectedElement["field"] == "temp" and not app.selectedElement["is_custom"]
    assert "temp" in app.availableFields and "state_badge" in app.availableFields and "timestamp" not in app.availableFields


def test_add_remove_duplicate_reorder_through_backend():
    app = _perdix_at_100(OverlayDesignerBackend())
    n = len(app.elements)
    app.addElement("anything", "graph")
    assert app.selectedIndex == n and app.selectedElement["kind"] == "graph" and app.selectedElement["field"] == "depth_graph"
    app.addElement("ignored", "badge")
    assert app.selectedElement["kind"] == "badge"
    app.addElement("secondary_tank_pressure", "tank_icon")
    assert app.selectedElement["kind"] == "tank_icon" and app.selectedElement["field"] == "secondary_tank_pressure"
    assert len(app.elements) == n + 3

    app.duplicateSelected()
    assert len(app.elements) == n + 4 and app.selectedIndex == n + 3
    app.moveSelectedLayer(-1)
    assert app.selectedIndex == n + 2
    app.removeSelected()
    assert len(app.elements) == n + 3
    app.clearSelection()
    app.removeSelected()  # nothing selected -> no-op
    assert len(app.elements) == n + 3
    # six recorded steps: 3 adds, duplicate, reorder, remove
    for _ in range(6):
        app.undo()
    assert len(app.elements) == n and not app.isDirty
    assert not app.canUndo


def test_frame_preview_skin_drag_rewrites_offsets_and_nudge_moves_skin():
    app = OverlayDesignerBackend()
    app.onBrandSelected("Shearwater")
    app.setViewMode("frame")
    z = app.zoom
    sx, sy, _, _ = app.document.frame_box(FRAME_W, FRAME_H)
    press_x, press_y = (sx + 5) * z, (sy + 5) * z
    app.onCanvasPressed(press_x, press_y)
    assert app.skinSelected and app.selectedIndex == -1
    # drag +20 display px right, 10 up
    app.onCanvasDragged(press_x + 20, press_y - 10)
    app.onCanvasReleased()
    nx, ny, _, _ = app.document.frame_box(FRAME_W, FRAME_H)
    assert nx == pytest.approx(sx + 20 / z, abs=1.0) and ny == pytest.approx(sy - 10 / z, abs=1.0)
    assert app.skinAttrs["ref_offset_x"] != 16.0 and app.isDirty

    app.nudgeSelected(3, 0)
    assert app.document.frame_box(FRAME_W, FRAME_H)[0] == pytest.approx(nx + 3, abs=1.0)
    # element boxes are expressed in frame-display space in this mode
    ex, ey, ew, eh = app.elementBoxes[0]
    assert ex > nx * z and ey > ny * z and ew < 917 * z


def test_skin_attr_edits_anchor_by_display_name_and_scale_refits():
    app = _perdix_at_100(OverlayDesignerBackend())
    app.selectSkin()
    app.setSkinAttr("anchor", "Top Right")
    assert app.skinAttrs["anchor"] == "TOP_RIGHT" and app.skinAttrs["anchor_index"] == 2
    app.setSkinAttr("anchor", "Nowhere")
    assert app.skinAttrs["anchor"] == "TOP_RIGHT"
    app.setSkinAttr("opacity", "5")
    assert app.skinAttrs["opacity"] == 1.0
    app.setSkinAttr("ref_offset_x", "-40")
    assert app.skinAttrs["ref_offset_x"] == -40.0
    app.setSkinAttr("scale", "0.5")
    assert app.skinAttrs["scale"] == 0.5 and app.document.skin["scale"] == 0.5
    assert app.anchorList[0] == "Top Left" and "Roboto" in app.fontFamilies


def test_replace_skin_image_updates_native_size_and_canvas():
    app = _perdix_at_100(OverlayDesignerBackend())
    other = Path("overlays/templates/garmin/x50i/main/single_tank/normal.png").resolve()
    assert app._replace_skin_image_from_path(other) is True
    assert app.skinAttrs["native_width"] == 473 and (app.canvasDisplayWidth, app.canvasDisplayHeight) == (473, 301)
    assert app.isDirty
    assert app._replace_skin_image_from_path(Path("nope.png")) is False


def test_show_bounds_toggle_and_boxes_follow_zoom():
    app = _perdix_at_100(OverlayDesignerBackend())
    x100 = app.elementBoxes[0][0]
    app.setZoomPercent(50)
    assert app.elementBoxes[0][0] == pytest.approx(x100 / 2)
    assert app.showBounds is True
    app.setShowBounds(False)
    assert app.showBounds is False


# -- Persistence (Phase 3) --------------------------------------------------------

import json
from conftest import mark_as_checkout


def _signal_counter(signal):
    calls = []
    signal.connect(lambda: calls.append(1))
    return calls


def test_release_mode_bundled_page_is_read_only_and_save_as_creates_user_page(isolated_template_roots):
    roots = isolated_template_roots
    app = OverlayDesignerBackend()
    app.onBrandSelected("Shearwater")
    assert app.isDevMode is False and "saved to" in app.writeTargetText
    assert app.pageOrigin == "bundled" and app.canSave is False and app.readOnlyHint.startswith("Built-in")
    assert app.save() is False
    changed = _signal_counter(app.templatesChanged)

    app.selectElement(0)
    app.nudgeSelected(10, 0)
    assert app.isDirty
    assert app.saveAs(app.saveAsCurrentTargetIndex, "", "My Main") == ""
    assert changed == [1]
    assert app.document.ref == app.document.ref.__class__("shearwater", "perdix_2", "my_main", None)
    assert app.pageOrigin == "user" and app.canSave is True and app.readOnlyHint == "" and not app.isDirty
    assert "My Main · yours" in app.pageList and app.pageIndex == app.pageList.index("My Main · yours")
    assert app.selectedIndex == 0  # selection kept across the reload
    path = roots["user"] / "shearwater" / "perdix_2" / "my_main" / "normal.json"
    assert path.exists() and (path.parent / "normal.png").exists()
    assert list(roots["bundled"].rglob("my_main")) == []

    # in-place save of the user page
    app.nudgeSelected(0, 5)
    assert app.save() is True and changed == [1, 1] and not app.isDirty
    saved = json.loads(path.read_text())
    assert saved["hud_skin"]["linked_elements"][0]["rel_y"] == pytest.approx(app.document.elements[0]["rel_y"], abs=1e-5)

    # save-as onto an existing id is refused with a message
    err = app.saveAs(app.saveAsCurrentTargetIndex, "", "Main Screen")
    assert err == "" or "already" in err  # "main_screen" is a new id; "main" would collide
    assert "already" in app.saveAs(app.saveAsCurrentTargetIndex, "", "My Main")
    assert "Enter a page name" in app.saveAs(app.saveAsCurrentTargetIndex, "", "  ")


def test_save_as_new_custom_computer_appears_in_cascade(isolated_template_roots):
    app = OverlayDesignerBackend()
    app.onBrandSelected("Garmin")
    new_index = len(app.saveAsTargets) - 1
    assert app.saveAsTargets[new_index]["computer"] == ""
    assert "Enter a name for the new computer" in app.saveAs(new_index, "", "Main")
    assert app.saveAs(new_index, "GoPro HUD", "Main") == ""
    assert "Custom" in app.brandList and app.brandIndex == app.brandList.index("Custom")
    assert app.templateTitle.startswith("Custom GoPro HUD")
    assert app.document.manufacturer == "Custom" and app.pageOrigin == "user" and app.canSave
    assert any(t["brand"] == "custom" and t["computer"] == "gopro_hud" for t in app.saveAsTargets)


def test_revert_reloads_from_disk(isolated_template_roots):
    app = OverlayDesignerBackend()
    app.selectElement(0)
    before = app.selectedElement["x_px"]
    app.nudgeSelected(25, 0)
    assert app.isDirty and app.selectedElement["x_px"] != before
    app.revert()
    assert not app.isDirty and app.selectedElement["x_px"] == before and app.selectedIndex == 0


def test_dev_mode_saves_bundled_page_into_repo_tree(isolated_template_roots):
    roots = isolated_template_roots
    mark_as_checkout(roots)
    app = OverlayDesignerBackend()
    app.onBrandSelected("Shearwater")
    assert app.isDevMode is True and app.writeTargetText.startswith("Dev mode") and app.canSave and app.readOnlyHint == ""
    app.selectElement(0)
    app.setSelectedAttr("align", "right")
    assert app.save() is True and not app.isDirty
    saved = json.loads((roots["bundled"] / "shearwater" / "perdix_2" / "main" / "single_tank" / "normal.json").read_text())
    assert saved["hud_skin"]["linked_elements"][0]["align"] == "right"
    assert saved["hud_skin"]["path"] == "normal.png"
    assert list(roots["user"].iterdir()) == []


def test_overlay_generator_picks_up_new_templates_on_reload(isolated_template_roots):
    from uwmedia.backends.overlay_generator_backend import OverlayGeneratorBackend
    designer = OverlayDesignerBackend()
    generator = OverlayGeneratorBackend()
    assert "Custom" not in generator.brandList
    assert designer.saveAs(len(designer.saveAsTargets) - 1, "GoPro HUD", "Main") == ""
    generator.reloadTemplates()
    assert "Custom" in generator.brandList
    generator.onBrandSelected("Custom")
    assert generator.pageList == ["Main · yours"]


# -- Custom-brand workflow (Phase 4) ------------------------------------------------

from PIL import Image as _PILImage


def _target_index(app, brand, computer):
    return next(i for i, t in enumerate(app.saveAsTargets) if t["brand"] == brand and t["computer"] == computer)


def test_create_custom_template_from_image_under_new_custom_computer(isolated_template_roots, tmp_path):
    roots = isolated_template_roots
    image = tmp_path / "hud graphic.jpg"
    _PILImage.new("RGB", (800, 600), (30, 30, 30)).save(image)
    app = OverlayDesignerBackend()
    assert app.rulesProfiles == ["Default", "Shearwater", "Garmin"]
    new_index = len(app.saveAsTargets) - 1
    changed = _signal_counter(app.templatesChanged)

    assert app.createCustomTemplate(new_index, "GoPro HUD", "Main", "image", str(image), "Garmin", 0, 0, "") == ""
    assert changed == [1]
    page_dir = roots["user"] / "custom" / "gopro_hud" / "main"
    saved = json.loads((page_dir / "normal.json").read_text())
    assert (saved["manufacturer"], saved["model"], saved["rules_profile"]) == ("Custom", "GoPro HUD", "Garmin")
    assert saved["hud_skin"]["type"] == "image" and saved["hud_skin"]["path"] == "normal.png"
    assert saved["hud_skin"]["scale"] == round(min(1.0, 0.4 * 1080 / 600, 0.4 * 1920 / 800), 3)
    assert saved["hud_skin"]["anchor"] == "BOTTOM_LEFT" and saved["hud_skin"]["linked_elements"] == []
    with _PILImage.open(page_dir / "normal.png") as img:
        assert img.size == (800, 600) and img.mode == "RGBA"
    manifest = json.loads((roots["user"] / "custom" / "gopro_hud" / "manifest.json").read_text())
    assert manifest["rules_profile"] == "Garmin" and manifest["pages"] == [{"id": "main", "name": "Main"}]

    # selected, empty, ours, and renders through the standard pipeline
    assert app.templateTitle.startswith("Custom GoPro HUD") and app.pageOrigin == "user" and app.canSave
    assert app.elements == [] and app.document.rules_manufacturer == "Garmin"
    assert (app.skinAttrs["native_width"], app.skinAttrs["native_height"]) == (800, 600)
    img = app.render_current_frame()
    assert img.width() > 1

    # then a field can be added and saved in place
    app.addElement("depth", "text")
    assert app.save() is True
    assert len(json.loads((page_dir / "normal.json").read_text())["hud_skin"]["linked_elements"]) == 1

    # same id again is refused
    assert "already" in app.createCustomTemplate(new_index, "GoPro HUD", "Main", "image", str(image), "Default", 0, 0, "")


def test_create_custom_template_under_existing_computer_inherits_rules(isolated_template_roots, tmp_path):
    roots = isolated_template_roots
    image = tmp_path / "shot.png"
    _PILImage.new("RGBA", (300, 300), (0, 0, 0, 0)).save(image)
    app = OverlayDesignerBackend()
    index = _target_index(app, "shearwater", "perdix_2")
    assert app.createCustomTemplate(index, "", "My Page", "image", str(image), "Garmin", 0, 0, "") == ""
    saved = json.loads((roots["user"] / "shearwater" / "perdix_2" / "my_page" / "normal.json").read_text())
    assert saved["manufacturer"] == "Shearwater" and "rules_profile" not in saved  # inherits, no override
    assert "My Page · yours" in app.pageList and app.document.rules_manufacturer == "Shearwater"


def test_create_custom_template_shape_and_validation(isolated_template_roots):
    roots = isolated_template_roots
    app = OverlayDesignerBackend()
    new_index = len(app.saveAsTargets) - 1
    assert "Enter a page name" in app.createCustomTemplate(new_index, "Cam", "  ", "shape", "", "Default", 400, 200, "#000000")
    assert "Enter a name" in app.createCustomTemplate(new_index, "", "Main", "shape", "", "Default", 400, 200, "#000000")
    assert "Pick a background image" in app.createCustomTemplate(new_index, "Cam", "Main", "image", "", "Default", 0, 0, "")
    assert "Pick a background image" in app.createCustomTemplate(new_index, "Cam", "Main", "image", "/nope/none.png", "Default", 0, 0, "")
    assert "background type" in app.createCustomTemplate(new_index, "Cam", "Main", "video", "", "Default", 0, 0, "")
    assert list(roots["user"].iterdir()) == []

    assert app.createCustomTemplate(new_index, "Cam", "Main", "shape", "", "Default", 640, 240, "#102030") == ""
    saved = json.loads((roots["user"] / "custom" / "cam" / "main" / "normal.json").read_text())
    assert saved["hud_skin"]["type"] == "shape" and (saved["hud_skin"]["width"], saved["hud_skin"]["height"]) == (640, 240)
    assert saved["hud_skin"]["color"] == "#102030" and "path" not in saved["hud_skin"]
    assert "rules_profile" not in saved and not (roots["user"] / "custom" / "cam" / "main" / "normal.png").exists()
    assert app.skinAttrs["type"] == "shape"


def test_custom_template_renders_through_cli_layout_path(isolated_template_roots, tmp_path):
    """The acceptance check: a saved custom page renders via the same
    relative-skin resolution + draw_hud() the CLI's --layout path uses."""
    from cli_main import resolve_layout_relative_skin
    from gui.hud_renderer import draw_hud
    from utils.dummy_telemetry import build_dummy_dive, waypoint_at

    roots = isolated_template_roots
    image = tmp_path / "bg.png"
    _PILImage.new("RGBA", (400, 200), (255, 255, 255, 255)).save(image)
    app = OverlayDesignerBackend()
    assert app.createCustomTemplate(len(app.saveAsTargets) - 1, "Cam", "Main", "image", str(image), "Default", 0, 0, "") == ""
    app.addElement("depth", "text")
    app.setSelectedAttr("color", "#FF0000")
    assert app.save()

    layout_path = roots["user"] / "custom" / "cam" / "main" / "normal.json"
    resolve_layout_relative_skin(layout_path)  # what cli_main does for --layout
    layout = json.loads(layout_path.read_text())
    assert Path(layout["hud_skin"]["path"]).is_absolute()
    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    draw_hud(frame, layout, waypoint_at(build_dummy_dive(), 600))
    assert frame.sum() > 0  # white skin bottom-left + red depth text landed on the frame
    assert frame[1079, 16].sum() > 0 or frame[1000, 100].sum() > 0


def test_replace_skin_image_warns_on_aspect_change(isolated_template_roots, tmp_path):
    app = OverlayDesignerBackend()
    app.onBrandSelected("Shearwater")  # 917x753
    same_ratio = tmp_path / "same.png"
    _PILImage.new("RGBA", (917 * 2, 753 * 2), (0, 0, 0, 255)).save(same_ratio)
    assert app._replace_skin_image_from_path(same_ratio)
    assert "Skin image replaced" in app.statusText and "aspect ratio changed" not in app.statusText
    square = tmp_path / "square.png"
    _PILImage.new("RGBA", (500, 500), (0, 0, 0, 255)).save(square)
    assert app._replace_skin_image_from_path(square)
    assert "aspect ratio changed" in app.statusText


# -- Polish (Phase 5) ---------------------------------------------------------------

from uwmedia.backends.overlay_designer_backend import MOD_META, MOD_SHIFT


def _center(box):
    return box[0] + box[2] / 2, box[1] + box[3] / 2


def test_modifier_click_toggles_multi_selection_and_marquee_selects_by_bounds():
    app = _perdix_at_100(OverlayDesignerBackend())
    boxes = app.elementBoxes
    app.onCanvasPressed(*_center(boxes[0])); app.onCanvasReleased()
    app.onCanvasPressedMod(*_center(boxes[3]), MOD_META); app.onCanvasReleased()
    app.onCanvasPressedMod(*_center(boxes[5]), MOD_SHIFT); app.onCanvasReleased()
    assert app.selectedIndices == [0, 3, 5] and app.selectionCount == 3 and app.selectedIndex == 5
    assert app.selectionBoxLabel.endswith("(+2)") and len(app.secondarySelectionBoxes) == 2
    app.onCanvasPressedMod(*_center(boxes[3]), MOD_META)  # toggle off
    assert app.selectedIndices == [0, 5] and app.selectedIndex == 5
    app.toggleElement(5)
    assert app.selectedIndex == 0

    # marquee over the top-left quarter picks every element intersecting it
    app.clearSelection()
    app.onCanvasPressed(1, 1)
    assert app.marqueeBox["visible"] is False
    app.onCanvasDragged(917 / 2, 753 / 2)
    assert app.marqueeBox["visible"] is True and app.marqueeBox["w"] > 100
    app.onCanvasReleased()
    assert app.marqueeBox["visible"] is False
    expected = [i for i, (x, y, w, h) in enumerate(boxes) if x <= 917 / 2 and y <= 753 / 2]
    assert app.selectedIndices == expected and len(expected) >= 3
    assert not app.isDirty  # selecting is never an edit

    app.selectAll()
    assert app.selectionCount == len(app.elements)
    app.onCanvasPressed(1, 1); app.onCanvasReleased()  # plain click on empty skin -> skin
    assert app.skinSelected and app.selectionCount == 0


def test_group_drag_moves_every_selected_element_in_one_undo_step():
    app = _perdix_at_100(OverlayDesignerBackend())
    boxes = app.elementBoxes
    app.selectElement(0); app.toggleElement(3)
    before = {i: (app.document.elements[i]["rel_x"], app.document.elements[i]["rel_y"]) for i in (0, 3)}
    cx, cy = _center(boxes[3])
    app.onCanvasPressed(cx, cy)
    assert app.selectedIndices == [0, 3]  # pressing a selected member keeps the group
    app.onCanvasDragged(cx + 40, cy + 20)
    app.onCanvasReleased()
    for i in (0, 3):
        assert app.document.elements[i]["rel_x"] == pytest.approx(before[i][0] + 40 / 917, abs=1e-6)
        assert app.document.elements[i]["rel_y"] == pytest.approx(before[i][1] + 20 / 753, abs=1e-6)
    assert len(app.document._undo) == 1
    app.nudgeSelected(-40, -20)
    for i in (0, 3):
        assert app.document.elements[i]["rel_x"] == pytest.approx(before[i][0], abs=1e-6)
    assert len(app.document._undo) == 2


def test_align_and_distribute():
    app = _perdix_at_100(OverlayDesignerBackend())
    app.selectElement(0); app.toggleElement(3); app.toggleElement(6)  # depth, dive_time, ndl
    for mode, lo, hi in (("left", 0, 0), ("right", 2, 2), ("top", 1, 1), ("bottom", 3, 3)):
        app.alignSelected(mode)
        b = app._all_native_bounds()
        values = [b[i][lo] for i in (0, 3, 6)]
        assert max(values) - min(values) < 0.6, mode
    app.alignSelected("hcenter")
    b = app._all_native_bounds()
    centers = [(b[i][0] + b[i][2]) / 2 for i in (0, 3, 6)]
    assert max(centers) - min(centers) < 0.6
    app.alignSelected("vcenter")
    b = app._all_native_bounds()
    centers = [(b[i][1] + b[i][3]) / 2 for i in (0, 3, 6)]
    assert max(centers) - min(centers) < 0.6

    # spread them out, then distribute horizontally -> equal gaps
    app.document.move_element(0, 0.05, 0.5); app.document.move_element(3, 0.30, 0.5); app.document.move_element(6, 0.80, 0.5)
    app._update_boxes()
    app.distributeSelected("h")
    b = app._all_native_bounds()
    ordered = sorted((0, 3, 6), key=lambda i: b[i][0])
    gaps = [b[ordered[k + 1]][0] - b[ordered[k]][2] for k in range(2)]
    assert gaps[0] == pytest.approx(gaps[1], abs=0.6)
    app.alignSelected("nonsense")  # ignored
    app.selectElement(0)
    steps = len(app.document._undo)
    app.alignSelected("left")  # single selection -> no-op
    assert len(app.document._undo) == steps


def test_copy_paste_across_pages_and_cut():
    app = _perdix_at_100(OverlayDesignerBackend())
    assert app.canPaste is False
    app.selectElement(0); app.toggleElement(1)
    app.copySelected()
    assert app.canPaste is True
    fields = [app.document.elements[i]["field"] for i in (0, 1)]
    app.onBrandSelected("Garmin")  # clipboard survives the page switch
    n = len(app.elements)
    app.paste()
    assert len(app.elements) == n + 2 and app.selectedIndices == [n, n + 1]
    assert [app.document.elements[i]["field"] for i in (n, n + 1)] == fields
    assert app.isDirty
    app.cutSelected()
    assert len(app.elements) == n and app.canPaste
    app.undo(); app.undo()
    assert len(app.elements) == n and not app.isDirty


def test_labels_and_designer_only_visibility():
    app = _perdix_at_100(OverlayDesignerBackend())
    app.selectElement(0)
    app.setSelectedAttr("label", "  Depth big  ")
    assert app.document.elements[0]["label"] == "Depth big"
    assert app.elements[0]["label"] == "Depth big" and app.selectedElement["label"] == "Depth big"
    assert app.selectionBoxLabel == "Depth big"
    app.setSelectedAttr("label", "")
    assert "label" not in app.document.elements[0] and app.elements[0]["label"] == "depth"

    count = len(app.document.elements)
    plain = app.render_current_frame()
    app.toggleHidden(0)
    assert app.hiddenIndices == [0] and app.elements[0]["hidden"] is True
    hidden = app.render_current_frame()
    assert hidden != plain
    assert "linked_elements" in app.document.layout["hud_skin"] and len(app.document.elements) == count  # never serialized
    assert not app.isDirty
    # hidden elements can't be hit; a structural edit clears the hidden set
    x, y, w, h = app.elementBoxes[0]
    app.onCanvasPressed(x + w / 2, y + h / 2); app.onCanvasReleased()
    assert app.selectedIndex != 0
    app.addElement("temp", "text")
    assert app.hiddenIndices == []
    app.toggleHidden(1); app.showAllElements()
    assert app.hiddenIndices == []


def test_snap_to_grid_and_to_element_edges(isolated_template_roots):
    # A fresh 400x200 shape page with one element: no neighbours, so grid
    # snapping can be observed on its own.
    app = OverlayDesignerBackend()
    assert app.createCustomTemplate(len(app.saveAsTargets) - 1, "Snap Cam", "Main", "shape", "", "Default", 400, 200, "#000000") == ""
    app.setZoomPercent(100)
    app.setSnapEnabled(True); app.setGridSize(16)
    assert app.snapEnabled and app.gridSize == 16 and app.gridSizes == [4, 8, 16, 32]
    app.addElement("depth", "text")
    app.setSelectedAttr("x_px", "96"); app.setSelectedAttr("y_px", "96")  # on the 16 px grid

    def drag_primary(dx, dy):
        x, y, w, h = app.elementBoxes[app.selectedIndex]
        app.onCanvasPressed(x + w / 2, y + h / 2)
        app.onCanvasDragged(x + w / 2 + dx, y + h / 2 + dy)
        app.onCanvasReleased()

    drag_primary(3, 2)  # within the 4 px tolerance -> pulled back onto 96/96
    assert (app.selectedElement["x_px"], app.selectedElement["y_px"]) == (96.0, 96.0)
    drag_primary(13, 0)  # 109 -> nearest node 112
    assert (app.selectedElement["x_px"], app.selectedElement["y_px"]) == (112.0, 96.0)
    drag_primary(7, 0)  # 119: 7 px from 112 and 9 from 128 -> no snap
    assert app.selectedElement["x_px"] == pytest.approx(119.0, abs=0.2)
    app.setSnapEnabled(False)
    drag_primary(3, 0)
    assert app.selectedElement["x_px"] == pytest.approx(122.0, abs=0.2)

    # Edge snapping: a second identical element 2.5 px right of the first is
    # pulled onto its left edge (the nearest snap target - the 32 px grid
    # node at 128 is further away) when nudged by a fraction of a pixel.
    app.setSnapEnabled(True); app.setGridSize(32)
    app.addElement("depth", "text")
    app.setSelectedAttr("x_px", "124.5"); app.setSelectedAttr("y_px", "150")
    drag_primary(0.2, 0)
    bounds = app._all_native_bounds()
    assert bounds[1][0] == pytest.approx(bounds[0][0], abs=0.01)
    assert app.selectedElement["x_px"] == pytest.approx(122.0, abs=0.2)


def test_grid_overlay_and_zoom_independent_of_snap():
    app = _perdix_at_100(OverlayDesignerBackend())
    plain = app.render_current_frame()
    app.setShowGrid(True)
    assert app.showGrid
    gridded = app.render_current_frame()
    assert gridded != plain and gridded.width() == plain.width()
    app.setGridSize(32)
    assert app.render_current_frame() != gridded


def test_bring_to_front_and_send_to_back():
    app = _perdix_at_100(OverlayDesignerBackend())
    first = app.document.elements[0]["field"]
    app.selectElement(0)
    app.bringToFront()
    assert app.selectedIndex == len(app.elements) - 1 and app.document.elements[-1]["field"] == first
    app.sendToBack()
    assert app.selectedIndex == 0 and app.document.elements[0]["field"] == first


def test_zip_export_and_import_round_trip(isolated_template_roots, tmp_path):
    roots = isolated_template_roots
    app = _perdix_at_100(OverlayDesignerBackend())
    app.selectElement(0); app.setSelectedAttr("align", "right")
    zip_path = tmp_path / "perdix_main"
    assert app._export_zip_to(zip_path) is True
    zip_path = zip_path.with_suffix(".zip")
    import zipfile
    with zipfile.ZipFile(zip_path) as zf:
        names = set(zf.namelist())
        assert names == {"normal.json", "normal.png", "template.json"}
        layout = json.loads(zf.read("normal.json"))
        meta = json.loads(zf.read("template.json"))
    assert layout["hud_skin"]["path"] == "normal.png" and layout["hud_skin"]["linked_elements"][0]["align"] == "right"
    assert meta["manufacturer"] == "Shearwater" and meta["page"] == "main"

    assert app._read_import_zip(zip_path) == "" and app.importPending
    assert "Enter a page name" in app.finishImport(len(app.saveAsTargets) - 1, "Cam", "")
    assert app.finishImport(len(app.saveAsTargets) - 1, "Imported Cam", "From zip") == ""
    assert not app.importPending
    page = roots["user"] / "custom" / "imported_cam" / "from_zip"
    assert (page / "normal.json").exists() and (page / "normal.png").exists()
    saved = json.loads((page / "normal.json").read_text())
    assert saved["manufacturer"] == "Custom" and saved["hud_skin"]["linked_elements"][0]["align"] == "right"
    assert app.templateTitle.startswith("Custom Imported Cam") and app.pageOrigin == "user"

    bad = tmp_path / "bad.zip"
    bad.write_bytes(b"not a zip")
    assert "Could not read" in app._read_import_zip(bad) and not app.importPending
    app._read_import_zip(zip_path); app.cancelImport()
    assert not app.importPending


def test_align_moves_others_onto_the_primary_element():
    app = _perdix_at_100(OverlayDesignerBackend())
    app.selectElement(3)          # dive_time ...
    app.toggleElement(6)          # ... then ndl: ndl is the primary and must not move
    before = app._all_native_bounds()
    app.alignSelected("left")
    after = app._all_native_bounds()
    assert after[6] == before[6]
    assert after[3][0] == pytest.approx(before[6][0], abs=0.01)
    app.alignSelected("top")
    after = app._all_native_bounds()
    assert after[6] == before[6] and after[3][1] == pytest.approx(before[6][1], abs=0.01)


def test_resize_selected_scales_fonts_and_icon_geometry():
    app = _perdix_at_100(OverlayDesignerBackend())
    app.selectElement(0)  # depth, font 112
    app.resizeSelected(1)
    assert app.document.elements[0]["font_size"] == 118
    app.resizeSelected(-1)
    assert app.document.elements[0]["font_size"] == 112
    icon = next(i for i, e in enumerate(app.document.elements) if e.get("type") == "tank_icon")
    app.selectElement(icon)
    w, h = app.document.elements[icon]["width"], app.document.elements[icon]["height"]  # 19 x 34
    app.resizeSelected(1)
    assert (app.document.elements[icon]["width"], app.document.elements[icon]["height"]) == (w + 1, round(h * 1.05))
    app.resizeSelected(-1); app.resizeSelected(-1)
    assert app.document.elements[icon]["width"] < w
    steps = len(app.document._undo)
    app.resizeSelected(0)
    assert len(app.document._undo) == steps
    app.selectElement(0); app.toggleElement(icon)
    app.resizeSelected(2)
    assert app.document.elements[0]["font_size"] == round(112 * 1.05 ** 2)


def test_small_suffix_inspector_attribute_round_trip():
    app = OverlayDesignerBackend()  # mk3i main single_tank
    dive_time = next(i for i, e in enumerate(app.document.elements) if e.get("field") == "dive_time")
    app.selectElement(dive_time)
    assert app.selectedElement["small_suffix"] == "seconds" and app.selectedElement["small_suffix_scale"] == 0.33
    assert app.smallSuffixStyles == ["", "seconds", "decimals"] and len(app.smallSuffixLabels) == 3
    app.setSelectedAttr("small_suffix", "")
    assert "small_suffix" not in app.document.elements[dive_time] and app.selectedElement["small_suffix"] == ""
    app.setSelectedAttr("small_suffix", "bogus")
    assert "small_suffix" not in app.document.elements[dive_time]
    app.setSelectedAttr("small_suffix", "decimals")
    app.setSelectedAttr("small_suffix_scale", "5")
    assert app.document.elements[dive_time]["small_suffix"] == "decimals"
    assert app.document.elements[dive_time]["small_suffix_scale"] == 1.0  # clamped


def test_tank_outline_inspector_attributes_and_mk3i_template():
    app = OverlayDesignerBackend()  # mk3i main single_tank
    icon = next(i for i, e in enumerate(app.document.elements) if e.get("type") == "tank_icon")
    app.selectElement(icon)
    sel = app.selectedElement
    assert sel["draw_outline"] is True and sel["outline_color"] == "#FFFFFF" and (sel["outline_width"], sel["outline_gap"]) == (2, 4)
    before = app.elementBoxes[icon]
    app.setSelectedAttr("draw_outline", False)
    assert "draw_outline" not in app.document.elements[icon]
    after = app.elementBoxes[icon]
    assert after[2] < before[2] and after[3] < before[3]  # bounds shrink to the fill
    app.setSelectedAttr("draw_outline", True)
    app.setSelectedAttr("outline_gap", "-3")
    app.setSelectedAttr("outline_width", "0")
    app.setSelectedAttr("outline_color", "#00ADED")
    e = app.document.elements[icon]
    assert e["draw_outline"] is True and e["outline_gap"] == 0 and e["outline_width"] == 1 and e["outline_color"] == "#00ADED"
    # the mk3i skin no longer carries a baked outline where the icon sits
    import numpy as np, cv2
    skin = cv2.imread(str(app.document.skin_abs_path), cv2.IMREAD_UNCHANGED)
    x0, y0, x1, y1 = [int(v) for v in app._all_native_bounds()[icon]]
    region = skin[max(0, y0 - 4):y1 + 4, max(0, x0 - 4):x1 + 4, :3]
    assert region.max() < 60


def test_x50i_pages_carry_a_dynamic_tissue_bar_and_drawn_tank_outlines():
    app = OverlayDesignerBackend()
    app.onBrandSelected("Garmin")
    app.onComputerSelected(next(n for n, c in app._computer_choices.items() if c == "x50i"))
    for page in ("main", "gases"):
        app.onPageSelected(next(n for n, p in app._page_choices.items() if p == page))
        kinds = [e["kind"] for e in app.elements]
        assert kinds.count("tissue_bar") == 1
        bar = app.document.elements[kinds.index("tissue_bar")]
        assert bar["field"] == "n2_tissue_load"
        for e in app.document.elements:
            if e.get("type") == "tank_icon":
                assert e["draw_outline"] is True
        # the skin is black where the bar and the tank outlines used to be
        import cv2
        skin = cv2.imread(str(app.document.skin_abs_path), cv2.IMREAD_UNCHANGED)
        for i, e in enumerate(app.document.elements):
            if e.get("type") in ("tissue_bar", "tank_icon"):
                x0, y0, x1, y1 = [int(v) for v in app._all_native_bounds()[i]]
                assert skin[y0:y1, x0:x1, :3].max() < 60, (page, e["field"])
    # adding a tissue bar through the designer
    app.addElement("whatever", "tissue_bar")
    assert app.selectedElement["kind"] == "tissue_bar" and app.selectedElement["field"] == "n2_tissue_load"
    w = app.selectedElement["width"]
    app.resizeSelected(1)
    assert app.selectedElement["width"] == w + 1


def test_x50i_pages_carry_dynamic_ascent_chevrons():
    app = OverlayDesignerBackend()
    app.onBrandSelected("Garmin")
    app.onComputerSelected(next(n for n, c in app._computer_choices.items() if c == "x50i"))
    for page in ("main", "gases"):
        app.onPageSelected(next(n for n, p in app._page_choices.items() if p == page))
        kinds = [e["kind"] for e in app.elements]
        assert kinds.count("ascent_chevrons") == 1
        i = kinds.index("ascent_chevrons")
        import cv2
        skin = cv2.imread(str(app.document.skin_abs_path), cv2.IMREAD_UNCHANGED)
        x0, y0, x1, y1 = [int(v) for v in app._all_native_bounds()[i]]
        assert skin[y0:y1, x0:x1, :3].max() < 60, page
    app.addElement("x", "ascent_chevrons")
    sel = app.selectedElement
    assert sel["kind"] == "ascent_chevrons" and sel["field"] == "ascent_rate" and sel["up_count"] == 4
    app.setSelectedAttr("up_count", "6"); app.setSelectedAttr("down_count", "-1")
    assert app.document.elements[app.selectedIndex]["up_count"] == 6 and app.document.elements[app.selectedIndex]["down_count"] == 0


def test_perdix_2_main_pages_have_a_dynamic_n2_bar_and_clean_skin():
    app = OverlayDesignerBackend()
    app.onBrandSelected("Shearwater")
    for variant in ("Single Tank", "Sidemount"):
        app.onVariantSelected(variant)
        kinds = [e["kind"] for e in app.elements]
        assert kinds.count("tissue_bar") == 1
        i = kinds.index("tissue_bar")
        bar = app.document.elements[i]
        assert bar["field"] == "gf" and bar["style"] == "fill"
        import cv2, numpy as np
        skin = cv2.imread(str(app.document.skin_abs_path), cv2.IMREAD_UNCHANGED)
        x0, y0, x1, y1 = [int(v) for v in app._all_native_bounds()[i]]
        region = skin[y0:y1, x0:x1, :3]
        # no blue frame / green fill pixels left under the element
        blue = (region[:, :, 0] > 150) & (region[:, :, 2] < 120)
        green = (region[:, :, 1] > 140) & (region[:, :, 0] < 130) & (region[:, :, 2] < 130)
        assert blue.sum() == 0 and green.sum() == 0, variant
    app.selectElement([e["kind"] for e in app.elements].index("tissue_bar"))
    assert app.selectedElement["style"] == "fill"
    app.setSelectedAttr("style", "segments")
    assert "style" not in app.document.elements[app.selectedIndex]
    app.setSelectedAttr("style", "fill")
    assert app.document.elements[app.selectedIndex]["style"] == "fill"
    app.setSelectedAttr("style", "bogus")
    assert app.document.elements[app.selectedIndex]["style"] == "fill"


def test_perdix_2_tank_icons_are_segmented_gauges_on_clean_skins():
    app = OverlayDesignerBackend()
    app.onBrandSelected("Shearwater")
    expected = {"Single Tank": 1, "Sidemount": 2}
    for variant, n in expected.items():
        app.onVariantSelected(variant)
        icons = [i for i, e in enumerate(app.document.elements) if e.get("type") == "tank_icon"]
        assert len(icons) == n, variant
        import cv2
        skin = cv2.imread(str(app.document.skin_abs_path), cv2.IMREAD_UNCHANGED)
        for i in icons:
            e = app.document.elements[i]
            assert e["style"] == "segments" and e["segments"] == 5 and "draw_outline" not in e
            x0, y0, x1, y1 = [int(v) for v in app._all_native_bounds()[i]]
            region = skin[y0:y1, x0:x1, :3]
            # the white segment blocks (hundreds of px each) are gone; the bezel
            # lettering copied in under the right sidemount icon is grey, so at
            # most a few stray bright pixels may remain
            assert int((region.min(axis=2) > 230).sum()) < 20, (variant, e["field"])
    app.onPageSelected(next(n for n, p in app._page_choices.items() if p == "tec"))
    tec_icons = [e for e in app.document.elements if e.get("type") == "tank_icon"]
    assert len(tec_icons) == 1 and tec_icons[0]["style"] == "segments"
    # inspector round trip: style default per kind
    app.selectElement(next(i for i, e in enumerate(app.document.elements) if e.get("type") == "tank_icon"))
    assert app.selectedElement["style"] == "segments" and app.selectedElement["segments"] == 5
    app.setSelectedAttr("style", "fill")
    assert "style" not in app.document.elements[app.selectedIndex]
    assert app.selectedElement["style"] == "fill"
    app.setSelectedAttr("style", "segments"); app.setSelectedAttr("segments", "0"); app.setSelectedAttr("full_bar", "232")
    e = app.document.elements[app.selectedIndex]
    assert e["style"] == "segments" and e["segments"] == 1 and e["full_bar"] == 232
    app.resizeSelected(1)
    assert e["width"] > 16 or e["height"] > 32
