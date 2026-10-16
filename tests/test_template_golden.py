"""Golden images of every bundled template in the states that matter
(simulator.md A4): the overlay is rendered on a black 1920x1080 frame, cropped
to its own pixels and halved, and compared with the PNG kept in
tests/fixtures/overlay_golden/. A difference means something changed the
rendered output - a font size slipping, a badge moving, a colour rule
breaking - and fails until the change is confirmed as intended and the
reference regenerated:

    pytest tests/test_template_golden.py -m golden --update-golden

The goldens are UWMedia's own output, looked at by eye once (not pictures of
the real devices - fidelity is hud_rules_sources.md's job). Marked `golden`:
run by the "Everything" suite only (tests/run_tests.sh 4), as the fonts
differ between machines."""
from pathlib import Path

import cv2
import numpy as np
import pytest

from gui.hud_renderer import draw_hud
from test_template_sweep import bundled_pages, load_page
from utils.dummy_telemetry import build_dummy_dive, forced_dive, waypoint_at

GOLDEN_DIR = Path(__file__).parent / "fixtures" / "overlay_golden"
STATES = ("normal", "ndl_low", "deco_at_stop", "deco_violation", "clear", "safety_stop", "safety_paused", "fast_ascent", "critical_gas")
MEAN_TOLERANCE = 2.0      # mean absolute difference over the crop (0-255)
CHANGED_FRACTION = 0.005  # share of pixels that may differ by more than 40

pytestmark = pytest.mark.golden


def golden_name(brand, computer, page, variant, state):
    return "__".join(p for p in (brand, computer, page, variant, state) if p) + ".png"


def render_half(layout, state):
    dive = build_dummy_dive("single_tank")
    wp, history = forced_dive(waypoint_at(dive, 12 * 60), state)
    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    draw_hud(frame, layout, wp, waypoints=history, render_log=False)
    mask = frame.max(axis=2) > 0
    ys, xs = np.where(mask)
    if len(xs) == 0:
        return frame[:2, :2]
    crop = frame[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    return cv2.resize(crop, (max(1, crop.shape[1] // 2), max(1, crop.shape[0] // 2)), interpolation=cv2.INTER_AREA)


@pytest.mark.parametrize("state", STATES)
@pytest.mark.parametrize("brand,computer,page,variant", bundled_pages(), ids=lambda v: str(v))
def test_golden_image(brand, computer, page, variant, state, request, tmp_path):
    layout, _ = load_page(brand, computer, page, variant)
    image = render_half(layout, state)
    path = GOLDEN_DIR / golden_name(brand, computer, page, variant, state)
    if request.config.getoption("--update-golden"):
        GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(path), image, [cv2.IMWRITE_PNG_COMPRESSION, 9])
        return
    assert path.exists(), f"no golden image {path.name}; create it with --update-golden after checking the render by eye"
    golden = cv2.imread(str(path), cv2.IMREAD_COLOR)
    assert golden.shape == image.shape, f"{path.name}: size changed {golden.shape[:2]} -> {image.shape[:2]} (the overlay moved or grew)"
    diff = np.abs(golden.astype(np.int16) - image.astype(np.int16))
    mean = float(diff.mean())
    changed = float((diff.max(axis=2) > 40).mean())
    if mean > MEAN_TOLERANCE or changed > CHANGED_FRACTION:
        out = tmp_path / path.name
        cv2.imwrite(str(out), np.hstack([golden, image, np.clip(diff * 3, 0, 255).astype(np.uint8)]))
        pytest.fail(f"{path.name} differs from its golden (mean {mean:.2f}, {changed:.2%} of pixels): golden | now | diff written to {out}")
