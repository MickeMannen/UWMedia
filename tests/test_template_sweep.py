"""Layout sweep over every bundled template (simulator.md A4): each page and
variant is laid out in every forced state of the Overlay Designer (and at a
few moments of the dummy dive), and every text, badge and notice element must
stay inside the skin and clear of the others. The geometry comes from
utils.hud_designer.element_native_bounds, the same mirror of the renderer
the designer's hit boxes use, so no pixels are rendered.

Issues that are known and accepted (or waiting for a display pass, A5) are
listed in tests/template_sweep_known.json; a new one fails the test, and the
failure message is the line to add once it has been looked at by eye."""
import json
from pathlib import Path

import pytest
from PIL import Image

from gui.hud_renderer import badge_lines, notice_for, resolve_element_text, rules_manufacturer
from utils.dummy_telemetry import STATE_OPTIONS, build_dummy_dive, forced_dive, waypoint_at
from utils.hud_designer import element_kind, element_native_bounds
from utils.hud_rules_engine import resolve_state
from utils.layouts import list_templates, load_layout_file, resolve_template_state, strip_variant_markers

KNOWN = Path(__file__).parent / "template_sweep_known.json"
SLACK = 2.0  # px of overlap or overhang that counts as touching, not colliding
DUMMY_MOMENTS = (400, 930, 1160, 1300, 1600)  # bottom, HIGH PPO2, fast ascent, missed stop, reserve


def bundled_pages():
    """(brand, computer, page, variant) for every bundled page / variant."""
    out = []
    for brand, computers in list_templates().items():
        for computer, manifest in computers.items():
            if manifest.get("origin") != "bundled":
                continue
            for page in manifest.get("pages", []):
                variants = page.get("variants") or [None]
                for variant in variants:
                    if resolve_template_state(brand, computer, page["id"], variant) is not None:
                        out.append((brand, computer, page["id"], variant))
    return out


def load_page(brand, computer, page, variant):
    path = resolve_template_state(brand, computer, page, variant)
    layout = strip_variant_markers(load_layout_file(path))
    skin = layout["hud_skin"]
    if skin.get("type") == "shape":
        size = (float(skin.get("width", 400)), float(skin.get("height", 200)))
    else:
        skin["path"] = str((path.parent / skin["path"]).resolve())
        size = tuple(float(v) for v in Image.open(skin["path"]).size)
    return layout, size


def situations():
    dive = build_dummy_dive("single_tank")
    base = waypoint_at(dive, 12 * 60)
    for state in STATE_OPTIONS:
        if state == "auto":
            continue
        wp, history = forced_dive(base, state)
        yield state, wp, history
    for t in DUMMY_MOMENTS:
        yield f"dive@{t}", waypoint_at(dive, t), dive.waypoints


def _overlap(a, b):
    """Overlap (width, height) of two boxes beyond the slack, or None."""
    w = min(a[2], b[2]) - max(a[0], b[0]) - SLACK
    h = min(a[3], b[3]) - max(a[1], b[1]) - SLACK
    return (w, h) if w > 0 and h > 0 else None


def sweep_page(layout, size, situation, wp, waypoints):
    """Issue strings for one page in one situation."""
    manufacturer, model = rules_manufacturer(layout), layout.get("model", "Perdix2")
    elements = layout["hud_skin"]["linked_elements"]
    state = resolve_state(manufacturer, model, wp, waypoints)
    notice = notice_for(layout, wp, waypoints)
    boxes = []  # (name, kind, bounds)
    for elem in elements:
        kind = element_kind(elem)
        if state in (elem.get("hide_in_states") or ()):
            continue
        if notice is not None and elem.get("hide_when_notice"):
            continue
        name = elem.get("id") or elem.get("label") or elem.get("field", kind)
        text, lines = None, None
        if kind == "text":
            text, _ = resolve_element_text(layout, elem.get("field", ""), wp, waypoints)
            if text in (None, ""):
                continue
            text = str(text)
        elif kind == "badge":
            lines = badge_lines(manufacturer, model, elem, wp, waypoints)
            if not lines:
                continue
        elif kind == "notice":
            if notice is None:
                continue
        elif kind == "graph":
            continue
        boxes.append((name, kind, element_native_bounds(elem, size[0], size[1], text=text, badge_lines=lines)))
    issues = []  # (key, detail): the key names the pair / element, the detail the numbers
    w, h = size
    for name, kind, (x0, y0, x1, y1) in boxes:
        if x0 < -SLACK or y0 < -SLACK or x1 > w + SLACK or y1 > h + SLACK:
            issues.append((f"{name} leaves the skin", f"{situation}: ({x0:.0f},{y0:.0f})-({x1:.0f},{y1:.0f}) of {w:.0f}x{h:.0f}"))
    textual = [(n, k, b) for n, k, b in boxes if k in ("text", "badge", "notice")]
    graphics = [(n, k, b) for n, k, b in boxes if k not in ("text", "badge", "notice")]
    for i, (na, ka, ba) in enumerate(textual):
        for nb, kb, bb in textual[i + 1:] + graphics:  # text against text, and text against an icon / bar / chevrons
            over = _overlap(ba, bb)
            if over:
                issues.append((f"{na} overlaps {nb}", f"{situation}: by {over[0]:.0f}x{over[1]:.0f} px"))
    return issues


def sweep_report(layout, size):
    """{issue key: [details...]} over every situation."""
    report = {}
    for situation, wp, waypoints in situations():
        for key, detail in sweep_page(layout, size, situation, wp, waypoints):
            report.setdefault(key, []).append(detail)
    return report


def _page_key(brand, computer, page, variant):
    return "/".join(p for p in (brand, computer, page, variant) if p)


def _known():
    return json.loads(KNOWN.read_text()) if KNOWN.exists() else {}


@pytest.mark.parametrize("brand,computer,page,variant", bundled_pages(), ids=lambda v: str(v))
def test_bundled_page_lays_out_in_every_state(brand, computer, page, variant):
    layout, size = load_page(brand, computer, page, variant)
    report = sweep_report(layout, size)
    key = _page_key(brand, computer, page, variant)
    known = _known().get(key, {})
    new = {k: v for k, v in report.items() if k not in known}
    lines = [f"{k}  ({len(v)} situation(s), e.g. {v[0]})" for k, v in new.items()]
    assert not new, (
        f"{key}: {len(new)} new layout issue(s) - check them by eye in the Overlay Designer "
        f"(State list) and either fix the template or add the key to {KNOWN.name} with a note:\n  " + "\n  ".join(lines)
    )


def test_known_issue_list_only_names_bundled_pages():
    keys = {_page_key(*p) for p in bundled_pages()}
    stale = [k for k in _known() if not k.startswith("_") and k not in keys]
    assert not stale, f"{KNOWN.name} lists pages that no longer exist: {stale}"
