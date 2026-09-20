"""
Pass 2 (Color page) engine capability: compositing N independently-placed
HUD overlays onto one color-correction run via --overlays-file, instead of
today's single --layout. See ui_rework.md's "Page: Color" section and
gui/hud_renderer.py's resolve_overlay_instance_layout/overlay_pixel_bbox.
"""
import json
import shutil
import subprocess
from pathlib import Path

import cv2
import numpy as np
import pytest

from gui.hud_renderer import overlay_pixel_bbox, resolve_overlay_instance_layout

BASE_DIR = Path(__file__).parent.parent
TEST_DATA_DIR = BASE_DIR / "test_data" / "release_test"
RESULTS_DIR = BASE_DIR / "test_data" / "test_results"
LOGS_DIR = BASE_DIR / "test_data" / "logs" / "uddf"

# Two small, self-contained "shape" skins (no external skin PNG, no
# validate_layout complications from a real template's extra virtual
# fields like state_badge) - isolates this test to the compositing feature
# itself, distinct colors so each layer's region is trivially checkable.
LAYOUT_A_DATA = {
    "design_width": 1920,
    "hud_skin": {
        "type": "shape", "width": 300, "height": 120,
        "color": "#ff0000", "opacity": 1.0,
        "linked_elements": [{"field": "depth", "rel_x": 0.1, "rel_y": 0.3, "font_size": 24, "color": "#ffffff"}],
    },
}
LAYOUT_B_DATA = {
    "design_width": 1920,
    "hud_skin": {
        "type": "shape", "width": 300, "height": 120,
        "color": "#00ff00", "opacity": 1.0,
        "linked_elements": [{"field": "temp", "rel_x": 0.1, "rel_y": 0.3, "font_size": 24, "color": "#ffffff"}],
    },
}


@pytest.fixture(scope="module", autouse=True)
def setup_results_dir():
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    for file in RESULTS_DIR.glob("test_color_multi_overlay_*"):
        try:
            file.unlink()
        except Exception:
            pass
    yield


# --- Pure math: resolve_overlay_instance_layout / overlay_pixel_bbox -------

def test_resolve_overlay_instance_layout_places_skin_exactly():
    """A TOP_LEFT-anchored shape skin's rendered top-left/size should land
    exactly at (x*frame_w, y*frame_h) / (design_size*scale*res_scale)."""
    layout = {
        "design_width": 1920,
        "hud_skin": {"type": "shape", "width": 200, "height": 100, "color": "#ff0000", "opacity": 1.0},
    }
    frame_w, frame_h = 1280, 720
    x, y, scale = 0.25, 0.5, 1.5

    resolved = resolve_overlay_instance_layout(layout, x, y, scale, frame_w, frame_h)
    frame = np.zeros((frame_h, frame_w, 3), dtype=np.uint8)

    from gui.hud_renderer import draw_hud
    from models.dive import Waypoint
    from datetime import datetime

    draw_hud(frame, resolved, Waypoint(timestamp=datetime.now(), depth=10.5, temp=22.0, time_since_start=0))

    red_mask = (frame[:, :, 2] > 200) & (frame[:, :, 1] < 50) & (frame[:, :, 0] < 50)
    ys, xs = np.where(red_mask)
    assert xs.min() == int(x * frame_w)
    assert ys.min() == int(y * frame_h)

    res_scale = frame_w / 1920
    expected_w = round(200 * scale * res_scale)
    expected_h = round(100 * scale * res_scale)
    assert abs((xs.max() + 1 - xs.min()) - expected_w) <= 1
    assert abs((ys.max() + 1 - ys.min()) - expected_h) <= 1


def test_overlay_pixel_bbox_matches_render():
    layout = {
        "design_width": 1920,
        "hud_skin": {"type": "shape", "width": 200, "height": 100, "color": "#ff0000", "opacity": 1.0},
    }
    frame_w, frame_h = 1280, 720
    x, y, scale = 0.25, 0.5, 1.5

    x0, y0, x1, y1 = overlay_pixel_bbox(layout, x, y, scale, frame_w, frame_h)
    assert x0 == int(x * frame_w)
    assert y0 == int(y * frame_h)

    res_scale = frame_w / 1920
    assert x1 - x0 == int(200 * scale * res_scale)
    assert y1 - y0 == int(100 * scale * res_scale)


# --- End-to-end CLI: --overlays-file composites N layers in one run --------

def test_overlays_file_composites_two_layers():
    video_source = TEST_DATA_DIR / "20251019_M0284.MP4"
    assert video_source.exists()

    layout_a_path = RESULTS_DIR / "test_color_multi_overlay_layout_a.json"
    layout_b_path = RESULTS_DIR / "test_color_multi_overlay_layout_b.json"
    layout_a_path.write_text(json.dumps(LAYOUT_A_DATA))
    layout_b_path.write_text(json.dumps(LAYOUT_B_DATA))

    overlays_json = RESULTS_DIR / "test_color_multi_overlay_instances.json"
    instance_a = {"layout_path": str(layout_a_path), "x": 0.0, "y": 0.0, "scale": 1.0}
    instance_b = {"layout_path": str(layout_b_path), "x": 0.55, "y": 0.6, "scale": 1.0}
    overlays_json.write_text(json.dumps([instance_a, instance_b]))

    cmd = [
        "python3", "cli_main.py",
        str(video_source),
        str(RESULTS_DIR),
        "--logs", str(LOGS_DIR),
        "--overlays-file", str(overlays_json),
        "--filename-format", "test_color_multi_overlay_result",
        "--tz-adjust", "0",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=BASE_DIR)
    assert result.returncode == 0, f"CLI command failed: {result.stderr}"

    output_path = RESULTS_DIR / f"test_color_multi_overlay_result{video_source.suffix.lower()}"
    assert output_path.exists(), f"Output video does not exist: {output_path}"

    # Sanity-check both overlay regions actually changed relative to the
    # unmodified source frame (cheap "something was drawn there" check, no
    # pixel-diffing infrastructure per this project's existing convention).
    cap_in = cv2.VideoCapture(str(video_source))
    cap_out = cv2.VideoCapture(str(output_path))
    frame_w = int(cap_in.get(cv2.CAP_PROP_FRAME_WIDTH))
    frame_h = int(cap_in.get(cv2.CAP_PROP_FRAME_HEIGHT))

    FRAME_IDX = 5
    cap_in.set(cv2.CAP_PROP_POS_FRAMES, FRAME_IDX)
    ok_in, frame_in = cap_in.read()
    cap_out.set(cv2.CAP_PROP_POS_FRAMES, FRAME_IDX)
    ok_out, frame_out = cap_out.read()
    cap_in.release()
    cap_out.release()
    assert ok_in and ok_out

    for raw, inst in ((LAYOUT_A_DATA, instance_a), (LAYOUT_B_DATA, instance_b)):
        x0, y0, x1, y1 = overlay_pixel_bbox(raw, inst["x"], inst["y"], inst["scale"], frame_w, frame_h)
        x0, y0 = max(0, x0), max(0, y0)
        x1, y1 = min(frame_w, x1), min(frame_h, y1)
        region_in = frame_in[y0:y1, x0:x1].astype(np.int16)
        region_out = frame_out[y0:y1, x0:x1].astype(np.int16)
        assert region_in.size > 0
        mean_abs_diff = np.mean(np.abs(region_in - region_out))
        assert mean_abs_diff > 2.0, f"Overlay region for {inst['layout_path']} doesn't appear to differ from source"
