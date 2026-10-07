"""gui/dive_profile_view.py: gas/sidemount line colours, chart axes and the
pixel <-> (time, depth) mapping, mm:ss formatting, nearest-sample lookup,
and render_profile_image off screen - placeholder text, grid, waypoint
handles, profile line per gas, legend, deco-stop shading, the cursor and
its NDL/deco readout. Drawing is checked by colour presence in regions of
the image, never exact pixels or text widths (fonts differ per OS)."""
import numpy as np
import pytest

from gui import dive_profile_view as view
from gui.dive_profile_view import (
    BG_COLOR,
    CURSOR_COLOR,
    DECO_STOP_RGB,
    DEPTH_LINE_COLOR,
    GAS_COLORS,
    MARGIN_BOTTOM,
    MARGIN_LEFT,
    MARGIN_RIGHT,
    MARGIN_TOP,
    WAYPOINT_COLOR,
    _format_mmss,
    chart_axes,
    gas_color,
    nearest_sample,
    next_free_gas_color,
    point_from_xy,
    render_profile_image,
    sample_color,
    time_from_x,
    xy_of,
)
from models.dive_plan import DiveProfilePlan, PlannedGas, PlannedWaypoint
from utils.dive_plan_engine import SimulatedSample

W, H = 600, 300


def _rgb(hex_color):
    return tuple(int(hex_color[i:i + 2], 16) for i in (1, 3, 5))


def _sample(t, depth, gas="Air", ceiling=0.0, ndl=None, tank_ref="T1", stop=0.0, stop_dur=0, tts=0):
    return SimulatedSample(time_sec=t, depth_m=depth, gas_id=gas, ceiling_m=ceiling, ndl_sec=ndl, tts_sec=tts,
                           stop_depth_m=stop, stop_duration_sec=stop_dur, cns_pct=0.0, po2=0.21, divemode="oc",
                           tank_pressure_bar=200.0, tank_ref=tank_ref)


def _air_plan(**kw):
    return DiveProfilePlan(gases=[PlannedGas(id="Air")], **kw)


def _square_profile(gas="Air", **kw):
    """0 -> 20 m at 2 min, held to 20 min, surfaced at 25 min, one sample a minute."""
    samples = []
    for minute in range(26):
        depth = min(20.0, minute * 10.0) if minute <= 20 else max(0.0, 20.0 - (minute - 20) * 4.0)
        samples.append(_sample(minute * 60, depth, gas=gas, **kw))
    return samples


def _pixels(img):
    return np.asarray(img.convert("RGB")).astype(int)


def _has_color(region, color, tol=0):
    diff = np.abs(region - np.array(_rgb(color) if isinstance(color, str) else color)).max(axis=-1)
    return bool((diff <= tol).any())


def _sidemount_plan():
    return DiveProfilePlan(dive_type="sidemount", gases=[
        PlannedGas(id="Left", side="left", tank_ref="T1"),
        PlannedGas(id="Right", side="right", tank_ref="T2", color="#EC4899"),
        PlannedGas(id="EAN50", gas_type="nitrox", o2_percent=50.0, tank_ref="T3"),
    ])


# --- colours ---------------------------------------------------------------

def test_gas_color_own_colour_palette_by_position_and_unknown():
    plan = DiveProfilePlan(gases=[PlannedGas(id="A"), PlannedGas(id="B", color="#123456"), PlannedGas(id="C")])
    assert gas_color(plan, "A") == GAS_COLORS[0]
    assert gas_color(plan, "B") == "#123456"
    assert gas_color(plan, "C") == GAS_COLORS[2]
    assert gas_color(plan, "nope") == DEPTH_LINE_COLOR
    many = DiveProfilePlan(gases=[PlannedGas(id=f"G{i}", tank_ref=f"T{i}") for i in range(len(GAS_COLORS) + 1)])
    assert gas_color(many, f"G{len(GAS_COLORS)}") == GAS_COLORS[0]  # wraps round


def test_sample_color_follows_sidemount_tank_in_use():
    plan = _sidemount_plan()
    assert sample_color(plan, _sample(0, 5, gas="Left", tank_ref="T1")) == GAS_COLORS[0]
    assert sample_color(plan, _sample(0, 5, gas="Left", tank_ref="T2")) == "#EC4899"
    # a stage tank, and a tank ref no gas owns, use the breathed gas's colour
    assert sample_color(plan, _sample(0, 5, gas="EAN50", tank_ref="T3")) == GAS_COLORS[2]
    assert sample_color(plan, _sample(0, 5, gas="Left", tank_ref="T9")) == GAS_COLORS[0]
    # not sidemount -> the gas colour, whatever the tank
    oc = _air_plan()
    assert sample_color(oc, _sample(0, 5, gas="Air", tank_ref="T2")) == GAS_COLORS[0]


def test_next_free_gas_color_skips_used_and_wraps_when_all_taken():
    assert next_free_gas_color(DiveProfilePlan()) == GAS_COLORS[0]
    plan = DiveProfilePlan(gases=[PlannedGas(id="A", color=GAS_COLORS[1]), PlannedGas(id="B", tank_ref="T2")])
    # A has palette[1], B by position also palette[1] -> palette[0] is free
    assert next_free_gas_color(plan) == GAS_COLORS[0]
    full = DiveProfilePlan(gases=[PlannedGas(id=f"G{i}", tank_ref=f"T{i}") for i in range(len(GAS_COLORS) + 2)])
    assert next_free_gas_color(full) == GAS_COLORS[(len(GAS_COLORS) + 2) % len(GAS_COLORS)]


# --- axes and mapping ------------------------------------------------------

def test_chart_axes_none_without_anything_to_scale_from():
    assert chart_axes(DiveProfilePlan(), []) is None
    assert chart_axes(DiveProfilePlan(max_depth_m=30), []) is None
    assert chart_axes(DiveProfilePlan(planned_runtime_sec=600), []) is None


def test_chart_axes_from_plan_limits_samples_and_waypoints():
    assert chart_axes(DiveProfilePlan(max_depth_m=30, planned_runtime_sec=3000), []) == pytest.approx((3000.0, 33.0))
    # samples beyond the planned limits grow the axes
    plan = DiveProfilePlan(max_depth_m=10, planned_runtime_sec=600,
                           waypoints=[PlannedWaypoint(runtime_sec=900, depth_m=12, gas_id="Air")])
    assert chart_axes(plan, [_sample(0, 0), _sample(700, 25)]) == pytest.approx((900.0, 25 * 1.1))
    # shallow dives still get at least a 5 m axis; time never 0
    assert chart_axes(DiveProfilePlan(), [_sample(0, 1.0)]) == pytest.approx((1.0, 5.5))


def test_xy_of_and_point_from_xy_are_inverse_and_clamped():
    axes = (1200.0, 40.0)
    x, y = xy_of(600, 20, W, H, axes)
    assert x == pytest.approx(MARGIN_LEFT + (W - MARGIN_LEFT - MARGIN_RIGHT) / 2)
    assert y == pytest.approx(MARGIN_TOP + (H - MARGIN_TOP - MARGIN_BOTTOM) / 2)
    assert xy_of(0, 0, W, H, axes) == (MARGIN_LEFT, MARGIN_TOP)
    assert xy_of(1200, 40, W, H, axes) == (W - MARGIN_RIGHT, H - MARGIN_BOTTOM)
    assert point_from_xy(x, y, W, H, axes) == pytest.approx((600, 20))
    assert point_from_xy(-50, -50, W, H, axes) == (0.0, 0.0)
    assert point_from_xy(W + 50, H + 50, W, H, axes) == (1200.0, 40.0)
    # degenerate canvas never divides by zero
    assert point_from_xy(10, 10, 1, 1, axes) == (0.0, 0.0)


def test_time_from_x_matches_drawn_x_and_clamps():
    max_t = 1800.0
    x = xy_of(450, 0, W, H, (max_t, 10.0))[0]
    assert time_from_x(x, W, max_t) == pytest.approx(450)
    assert time_from_x(0, W, max_t) == 0.0
    assert time_from_x(W * 2, W, max_t) == max_t


@pytest.mark.parametrize("seconds, text", [(0, "0:00"), (59.9, "0:59"), (61, "1:01"), (3600, "60:00"), (-5, "0:00")])
def test_format_mmss(seconds, text):
    assert _format_mmss(seconds) == text


def test_nearest_sample():
    samples = [_sample(0, 0), _sample(60, 10), _sample(120, 20)]
    assert nearest_sample([], 5) is None
    assert nearest_sample(samples, 80).time_sec == 60
    assert nearest_sample(samples, 1000).time_sec == 120


# --- rendering -------------------------------------------------------------

def test_render_without_axes_draws_only_the_hint():
    img = render_profile_image(DiveProfilePlan(), [], W, H)
    assert img.size == (W, H)
    px = _pixels(img)
    bg = np.array(_rgb(BG_COLOR))
    changed = np.abs(px - bg).max(axis=-1) > 0
    assert changed.any()
    ys, _ = np.nonzero(changed)
    assert ys.min() >= MARGIN_TOP - 2 and ys.max() < MARGIN_TOP + 30  # just the one hint line
    # zero sizes are clamped to a 1x1 image
    assert render_profile_image(DiveProfilePlan(), [], 0, -3).size == (1, 1)


def test_render_empty_planned_chart_has_grid_max_depth_line_and_hint():
    plan = DiveProfilePlan(max_depth_m=30, planned_runtime_sec=2400)
    px = _pixels(render_profile_image(plan, [], W, H))
    grid = _rgb(view.GRID_COLOR)
    assert _has_color(px[MARGIN_TOP:H - MARGIN_BOTTOM, MARGIN_LEFT:W - MARGIN_RIGHT], grid)
    # depth labels left of the plot, time labels under it
    assert _has_color(px[:, :MARGIN_LEFT], view.AXIS_TEXT_COLOR, tol=60)
    assert _has_color(px[H - MARGIN_BOTTOM:, :], view.AXIS_TEXT_COLOR, tol=60)
    # dashed planned-max-depth line at y_of(30)
    axes = chart_axes(plan, [])
    y = int(round(xy_of(0, 30, W, H, axes)[1]))
    row = px[y - 1:y + 2, MARGIN_LEFT:W - MARGIN_RIGHT]
    assert _has_color(row, view.AXIS_TEXT_COLOR)
    # no profile, no waypoints
    assert not _has_color(px, DEPTH_LINE_COLOR)
    assert not _has_color(px, WAYPOINT_COLOR)


def test_render_profile_line_in_gas_colour_with_waypoints_and_legend():
    plan = _air_plan(waypoints=[PlannedWaypoint(runtime_sec=120, depth_m=20, gas_id="Air"), PlannedWaypoint(runtime_sec=1200, depth_m=20, gas_id="Air")])
    samples = _square_profile()
    img = render_profile_image(plan, samples, W, H)
    px = _pixels(img)
    axes = chart_axes(plan, samples)
    # the bottom segment at 20 m is drawn in Air's colour
    bx, by = xy_of(600, 20, W, H, axes)
    assert _has_color(px[int(by) - 2:int(by) + 3, int(bx) - 2:int(bx) + 3], GAS_COLORS[0])
    # waypoint handles sit on their waypoints
    for wp in plan.waypoints:
        x, y = (int(round(v)) for v in xy_of(wp.runtime_sec, wp.depth_m, W, H, axes))
        assert _has_color(px[y - 3:y + 4, x - 3:x + 4], WAYPOINT_COLOR)
    # legend swatch in the bottom-right corner of the plot
    corner = px[H - MARGIN_BOTTOM - 40:H - MARGIN_BOTTOM, W - 150:W - MARGIN_RIGHT]
    assert _has_color(corner, GAS_COLORS[0])
    # no cursor
    assert not _has_color(px[:MARGIN_TOP - 4, :], view.NDL_COLOR, tol=40)


def test_render_line_switches_colour_with_gas():
    plan = DiveProfilePlan(gases=[PlannedGas(id="Air"), PlannedGas(id="EAN50", tank_ref="T2", color="#A855F7")])
    samples = [_sample(t * 60, 20.0 if t < 10 else 6.0, gas="Air" if t < 10 else "EAN50") for t in range(20)]
    px = _pixels(render_profile_image(plan, samples, W, H))
    axes = chart_axes(plan, samples)
    x_deep, y_deep = xy_of(300, 20, W, H, axes)
    x_shallow, y_shallow = xy_of(900, 6, W, H, axes)
    assert _has_color(px[int(y_deep) - 2:int(y_deep) + 3, int(x_deep) - 2:int(x_deep) + 3], GAS_COLORS[0])
    assert _has_color(px[int(y_shallow) - 2:int(y_shallow) + 3, int(x_shallow) - 2:int(x_shallow) + 3], "#A855F7")


def test_legend_lists_only_breathed_gases_and_both_sidemount_tanks(monkeypatch):
    calls = []
    original = view._draw_gas_legend

    def spy(draw, plan, samples, right, bottom, font, areas=()):
        labels = []

        class Recorder:
            def __getattr__(self, name):
                return getattr(draw, name)

            def text(self, xy, text, **kw):
                labels.append(text)
                return draw.text(xy, text, **kw)

        original(Recorder(), plan, samples, right, bottom, font, areas)
        calls.append(labels)

    monkeypatch.setattr(view, "_draw_gas_legend", spy)

    oc = DiveProfilePlan(gases=[PlannedGas(id="Air"), PlannedGas(id="Unused", tank_ref="T2")])
    render_profile_image(oc, _square_profile(), W, H)
    sm = _sidemount_plan()
    render_profile_image(sm, [_sample(0, 0, gas="Left"), _sample(60, 10, gas="Left", tank_ref="T2")], W, H)
    render_profile_image(sm, [_sample(0, 0, gas="EAN50", tank_ref="T3"), _sample(60, 3, gas="EAN50", tank_ref="T3")], W, H)
    render_profile_image(oc, [_sample(0, 0, gas="nobody"), _sample(60, 5, gas="nobody")], W, H)
    assert calls[0] == ["Air"]
    assert calls[1] == ["Left (T1 L)", "Right (T2 R)"]
    assert calls[2] == ["EAN50"]
    assert calls[3] == []


def test_render_waypoints_only_draws_straight_preview_without_cursor():
    plan = _air_plan(waypoints=[PlannedWaypoint(runtime_sec=600, depth_m=20, gas_id="Air")])
    samples = _square_profile(ndl=1200)
    full = render_profile_image(plan, samples, W, H, cursor_time=600)
    preview = render_profile_image(plan, samples, W, H, cursor_time=600, waypoints_only=True)
    pf, pp = _pixels(full), _pixels(preview)
    axes = chart_axes(plan, samples)
    # the preview goes straight from the surface at 0:00 to the waypoint
    mx, my = xy_of(300, 10, W, H, axes)
    assert _has_color(pp[int(my) - 2:int(my) + 3, int(mx) - 2:int(mx) + 3], DEPTH_LINE_COLOR)
    # cursor and readout only on the full render
    assert _has_color(pf[:MARGIN_TOP - 4, :], view.NDL_COLOR, tol=40)
    assert not _has_color(pp[:MARGIN_TOP - 4, :], view.NDL_COLOR, tol=40)
    cx = int(round(xy_of(600, 0, W, H, axes)[0]))
    assert _has_color(pf[MARGIN_TOP + 5:MARGIN_TOP + 20, cx - 1:cx + 2], CURSOR_COLOR)
    assert not _has_color(pp[MARGIN_TOP + 5:MARGIN_TOP + 20, cx - 1:cx + 2], CURSOR_COLOR)


@pytest.mark.parametrize("kwargs, color", [
    ({"ceiling": 3.0, "stop": 3.0, "stop_dur": 120, "tts": 300}, view.DECO_COLOR),
    ({"ndl": 900}, view.NDL_COLOR),
    ({}, view.NDL_COLOR),  # no NDL known -> "99+"
])
def test_cursor_readout_colour_by_deco_state(kwargs, color):
    plan = _air_plan()
    samples = _square_profile(**kwargs)
    px = _pixels(render_profile_image(plan, samples, W, H, cursor_time=610))
    other = view.NDL_COLOR if color == view.DECO_COLOR else view.DECO_COLOR
    top = px[:MARGIN_TOP - 4, :]
    assert _has_color(top, color, tol=40)
    assert not _has_color(top, other, tol=40)
    hidden = _pixels(render_profile_image(plan, samples, W, H, cursor_time=610, show_readout=False))
    assert not _has_color(hidden[:MARGIN_TOP - 4, :], color, tol=40)


def test_cursor_readout_text_names_state_and_gas(monkeypatch):
    texts = []
    real_draw = view.ImageDraw.Draw

    def recording_draw(img):
        d = real_draw(img)
        original_text = d.text

        def text(xy, t, *a, **kw):
            texts.append(t)
            return original_text(xy, t, *a, **kw)

        d.text = text
        return d

    monkeypatch.setattr(view.ImageDraw, "Draw", recording_draw)
    plan = _air_plan()
    render_profile_image(plan, _square_profile(ceiling=6.0, stop=6.0, stop_dur=90, tts=420), W, H, cursor_time=600)
    render_profile_image(plan, _square_profile(ndl=1500), W, H, cursor_time=600)
    render_profile_image(plan, _square_profile(), W, H, cursor_time=600)
    render_profile_image(plan, _square_profile(gas="ghost"), W, H, cursor_time=600)
    readouts = [t for t in texts if t.startswith("10:00 ")]
    assert readouts == [
        "10:00  20m  DECO → 6m (1:30)  TTS 7:00  ·  Air",
        "10:00  20m  NDL 25min  ·  Air",
        "10:00  20m  NDL 99+min  ·  Air",
        "10:00  20m  NDL 99+min",
    ]
    # axis labels: 5 m grid on a <=30 m axis, 5-minute ticks on a short dive
    assert "0m" in texts and "5m" in texts and "20m" in texts
    assert "0:00" in texts and "5:00" in texts and "25:00" in texts


def test_axis_steps_widen_for_deep_long_dives(monkeypatch):
    texts = []
    real_draw = view.ImageDraw.Draw

    def recording_draw(img):
        d = real_draw(img)
        original_text = d.text
        d.text = lambda xy, t, *a, **kw: (texts.append(t), original_text(xy, t, *a, **kw))[1]
        return d

    monkeypatch.setattr(view.ImageDraw, "Draw", recording_draw)
    render_profile_image(DiveProfilePlan(max_depth_m=45, planned_runtime_sec=3600), [], W, H)
    assert "10m" in texts and "40m" in texts and "5m" not in texts
    assert "10:00" in texts and "60:00" in texts and "5:00" not in texts
    assert any(t.startswith("Click to place a waypoint") for t in texts)


def test_cursor_without_samples_draws_nothing_extra():
    plan = DiveProfilePlan(max_depth_m=30, planned_runtime_sec=1800)
    assert np.array_equal(_pixels(render_profile_image(plan, [], W, H, cursor_time=100)),
                          _pixels(render_profile_image(plan, [], W, H)))


def test_deco_schedules_shade_stop_levels_by_duration():
    plan = _air_plan()
    samples = _square_profile()
    # at 10:00 a 6 m stop (long) and a 3 m stop split in two (adds up);
    # at 15:00 a short 3 m stop
    schedules = [(600, [(6.0, 300, "Air"), (3.0, 100, "Air"), (3.0, 100, "Air")]), (900, [(3.0, 30, "Air")])]
    px = _pixels(render_profile_image(plan, samples, W, H, deco_schedules=schedules, deco_schedule_interval_sec=120))
    plain = _pixels(render_profile_image(plan, samples, W, H))
    axes = chart_axes(plan, samples)

    def shade_at(t, depth):
        x, y = xy_of(t + 60, depth, W, H, axes)
        return px[int(y), int(x)]

    bg = np.array(_rgb(BG_COLOR))
    long_stop, mid_stop, short_stop = shade_at(600, 4.5), shade_at(600, 1.5), shade_at(900, 1.5)
    # shaded cells are lighter than the background, darker for longer stops
    assert long_stop.sum() > mid_stop.sum() > short_stop.sum() > bg.sum()
    # unshaded time keeps the background
    x, y = xy_of(300, 1.5, W, H, axes)
    assert tuple(px[int(y), int(x)]) == tuple(plain[int(y), int(x)])
    # the legend gets a filled "Deco stops" swatch (18x10 px) in the shading
    # colour - the same grey as the axis text, so count pixels, not presence
    def swatch_pixels(a):
        corner = a[H - MARGIN_BOTTOM - 60:H - MARGIN_BOTTOM, W - 150:W - MARGIN_RIGHT]
        return int((np.abs(corner - np.array(DECO_STOP_RGB)).max(axis=-1) == 0).sum())

    assert swatch_pixels(px) >= swatch_pixels(plain) + 150


def test_deco_schedules_with_no_stop_time_leave_the_chart_unshaded():
    plan = _air_plan()
    samples = _square_profile()
    shaded = _pixels(render_profile_image(plan, samples, W, H, deco_schedules=[(600, [(3.0, 0, "Air")])]))
    axes = chart_axes(plan, samples)
    x, y = xy_of(630, 1.5, W, H, axes)
    assert tuple(shaded[int(y), int(x)]) == _rgb(BG_COLOR)


def test_render_real_simulation_end_to_end():
    from utils.dive_plan_engine import deco_schedule_timeline, simulate

    plan = DiveProfilePlan(gf_low=30, gf_high=70, gases=[PlannedGas(id="Air")],
                           waypoints=[PlannedWaypoint(runtime_sec=180, depth_m=40, gas_id="Air"),
                                      PlannedWaypoint(runtime_sec=1500, depth_m=40, gas_id="Air")])
    samples, _ = simulate(plan, resolution_sec=30)
    schedules = deco_schedule_timeline(plan)
    img = render_profile_image(plan, samples, 800, 400, cursor_time=1500, deco_schedules=schedules)
    px = _pixels(img)
    assert img.size == (800, 400)
    assert _has_color(px, GAS_COLORS[0]) and _has_color(px, WAYPOINT_COLOR)
    assert _has_color(px[:MARGIN_TOP - 4, :], view.DECO_COLOR, tol=40)  # 25 min at 40 m on air needs deco
