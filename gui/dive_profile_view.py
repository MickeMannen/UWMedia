from typing import List, Optional, Sequence, Tuple

from PIL import Image, ImageDraw

from gui.hud_renderer import get_font
from models.dive_plan import DiveProfilePlan
from utils.dive_plan_engine import SimulatedSample

# Matches this app's existing dark-card canvas palette (see
# uwmedia/app.py's THEME/_draw_progress_bar) rather than inventing a new
# light-chart look.
BG_COLOR = "#1F2937"
GRID_COLOR = "#374151"
AXIS_TEXT_COLOR = "#9CA3AF"
DEPTH_LINE_COLOR = "#0EA5A4"
WAYPOINT_COLOR = "#FBBF24"
NDL_COLOR = "#22C55E"
DECO_COLOR = "#EF4444"
CURSOR_COLOR = "#FFFFFF"
# Planned deco stops (deco_schedule_timeline): each stop's 3 m level shaded
# in translucent grey, more opaque the longer the stop.
DECO_STOP_RGB = (156, 163, 175)
DECO_STOP_ALPHA_MIN = 35
DECO_STOP_ALPHA_MAX = 190
DECO_STOP_LEVEL_M = 3.0

# Selectable per-gas line colours - picked to stay distinct from the grey deco
# stop shading, the yellow waypoint handles and the white cursor.
GAS_COLORS = (
    "#0EA5A4",  # teal
    "#3B82F6",  # blue
    "#22C55E",  # green
    "#A855F7",  # purple
    "#F97316",  # orange
    "#EC4899",  # pink
    "#84CC16",  # lime
    "#06B6D4",  # cyan
    "#EF4444",  # red
)


def gas_color(plan: DiveProfilePlan, gas_id: str) -> str:
    """The gas's own colour, or a palette colour by its position in the
    plan's gas list (so older plans without colours still differ)."""
    for i, gas in enumerate(plan.gases):
        if gas.id == gas_id:
            return gas.color or GAS_COLORS[i % len(GAS_COLORS)]
    return DEPTH_LINE_COLOR


def next_free_gas_color(plan: DiveProfilePlan) -> str:
    used = {gas_color(plan, g.id) for g in plan.gases}
    return next((c for c in GAS_COLORS if c not in used), GAS_COLORS[len(plan.gases) % len(GAS_COLORS)])

# Shared with the app's drag-scrub handler (uwmedia/app.py) via time_from_x
# below, so the pixel-to-time mapping used for scrubbing always matches what
# was actually drawn.
MARGIN_LEFT = 50
MARGIN_RIGHT = 16
MARGIN_TOP = 26
MARGIN_BOTTOM = 28
DEPTH_HEADROOM = 1.1  # so the line doesn't hug the bottom axis


def chart_axes(plan: DiveProfilePlan, samples: List[SimulatedSample]) -> Optional[Tuple[float, float]]:
    """(max_time_sec, max_depth_m) the chart is drawn with - shared by
    render_profile_image and the click/drag mapping (point_from_xy/xy_of)
    so a click always lands where it was drawn. Uses the plan's own
    max_depth_m/planned_runtime_sec when set (the axes are then fixed
    before any waypoint exists) and only grows past them when the
    simulated profile does. None when there is nothing to scale from."""
    times = [s.time_sec for s in samples] + [wp.runtime_sec for wp in plan.waypoints]
    depths = [s.depth_m for s in samples] + [wp.depth_m for wp in plan.waypoints]
    if plan.planned_runtime_sec:
        times.append(plan.planned_runtime_sec)
    if plan.max_depth_m:
        depths.append(plan.max_depth_m)
    if not samples and not (plan.planned_runtime_sec and plan.max_depth_m):
        return None
    max_time = max(times, default=0) or 1
    max_depth = max(max(depths, default=1.0), 5.0) * DEPTH_HEADROOM
    return float(max_time), max_depth


def xy_of(time_sec: float, depth_m: float, width: int, height: int, axes: Tuple[float, float]) -> Tuple[float, float]:
    max_time, max_depth = axes
    plot_w = max(1, width - MARGIN_LEFT - MARGIN_RIGHT)
    plot_h = max(1, height - MARGIN_TOP - MARGIN_BOTTOM)
    return MARGIN_LEFT + (time_sec / max_time) * plot_w, MARGIN_TOP + (depth_m / max_depth) * plot_h


def point_from_xy(x: float, y: float, width: int, height: int, axes: Tuple[float, float]) -> Tuple[float, float]:
    """Inverse of xy_of - canvas pixel to (time_sec, depth_m), clamped to
    the plotted range."""
    max_time, max_depth = axes
    plot_w = max(1, width - MARGIN_LEFT - MARGIN_RIGHT)
    plot_h = max(1, height - MARGIN_TOP - MARGIN_BOTTOM)
    fx = min(1.0, max(0.0, (x - MARGIN_LEFT) / plot_w))
    fy = min(1.0, max(0.0, (y - MARGIN_TOP) / plot_h))
    return fx * max_time, fy * max_depth


def time_from_x(x: float, width: int, max_time_sec: float) -> float:
    """Inverse of render_profile_image's own x_of() - converts a canvas x
    pixel back to dive time, clamped to the plotted range."""
    plot_w = max(1, width - MARGIN_LEFT - MARGIN_RIGHT)
    frac = (x - MARGIN_LEFT) / plot_w
    frac = min(1.0, max(0.0, frac))
    return frac * max_time_sec


def _format_mmss(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


def nearest_sample(samples: List[SimulatedSample], time_sec: float) -> Optional[SimulatedSample]:
    if not samples:
        return None
    return min(samples, key=lambda s: abs(s.time_sec - time_sec))


def _draw_gas_legend(draw, plan, samples, right, bottom, font, areas=()) -> None:
    """Swatch + name per gas actually breathed, stacked up from the
    bottom-right corner of the plot (usually empty - dives end shallow),
    then a filled swatch per shaded area in `areas` ((label, rgb))."""
    used = {s.gas_id for s in samples}
    rows = [(g.id, gas_color(plan, g.id), False) for g in plan.gases if g.id in used]
    rows += [(label, rgb, True) for label, rgb in areas]
    if not rows:
        return
    row_h = 16
    names_w = max(draw.textlength(label, font=font) for label, _, _ in rows)
    left = right - names_w - 28
    top = bottom - row_h * len(rows) - 4
    draw.rectangle([left - 6, top - 4, right + 4, bottom + 2], fill=BG_COLOR, outline=GRID_COLOR)
    for i, (label, color, filled) in enumerate(rows):
        y = top + i * row_h + row_h / 2
        if filled:
            draw.rectangle([left, y - 5, left + 18, y + 5], fill=color)
        else:
            draw.line([(left, y), (left + 18, y)], fill=color, width=3)
        draw.text((left + 24, y - 7), label, fill=AXIS_TEXT_COLOR, font=font)


def _draw_deco_schedules(img, schedules, interval_sec, x_of, y_of) -> None:
    """Every planned stop over time: for each schedule column, the 3 m level
    above each stop depth, alpha by stop length (relative to the longest
    stop anywhere in the dive)."""
    longest = max((dur for _, stops in schedules for _, dur, _ in stops), default=0)
    if longest <= 0:
        return
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    for i, (t, stops) in enumerate(schedules):
        x0, x1 = x_of(t), x_of(t + interval_sec)
        per_depth = {}
        for depth, dur, _ in stops:
            per_depth[depth] = per_depth.get(depth, 0) + dur
        for depth, dur in per_depth.items():
            alpha = DECO_STOP_ALPHA_MIN + (DECO_STOP_ALPHA_MAX - DECO_STOP_ALPHA_MIN) * min(1.0, dur / longest)
            draw.rectangle(
                [x0, y_of(max(0.0, depth - DECO_STOP_LEVEL_M)), max(x0 + 1, x1 - 1), y_of(depth)],
                fill=DECO_STOP_RGB + (int(alpha),),
            )
    img.paste(Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB"))


def render_profile_image(
    plan: DiveProfilePlan,
    samples: List[SimulatedSample],
    width: int,
    height: int,
    cursor_time: Optional[float] = None,
    waypoints_only: bool = False,
    show_readout: bool = True,
    deco_schedules: Sequence[Tuple[int, List[Tuple[float, int, str]]]] = (),
    deco_schedule_interval_sec: int = 60,
) -> Image.Image:
    """Renders the depth-vs-time chart for the dive profile builder as a PIL
    image. Matches this app's existing canvas convention of rendering
    everything to a raster image and calling `canvas.draw_image()` - no
    canvas in this app draws vector paths directly (see
    uwmedia/app.py's `_redraw_designer_canvas`/`_draw_progress_bar`).

    waypoints_only draws straight lines between the waypoints instead of the
    simulated profile - a cheap preview while a waypoint is being dragged,
    where re-running the deco simulation per mouse move is too slow.
    `samples` still feed the axes so they don't jump mid-drag.

    The profile line takes each gas's colour (gas_color). show_readout=False leaves
    out the one-line NDL/deco text at the top - for callers that show the
    cursor details themselves (the QML page's hover box).

    deco_schedules (utils.dive_plan_engine.deco_schedule_timeline) adds the
    planned deco stops as translucent grey shading: at each moment,
    every stop an ascent started then would make, darker for longer stops -
    so you can watch stops get added, deepen and clear as the dive goes on."""
    img = Image.new("RGB", (max(1, width), max(1, height)), BG_COLOR)
    draw = ImageDraw.Draw(img)
    font_small = get_font(12)
    font_label = get_font(14)

    margin_left, margin_right, margin_top, margin_bottom = MARGIN_LEFT, MARGIN_RIGHT, MARGIN_TOP, MARGIN_BOTTOM

    axes = chart_axes(plan, samples)
    if axes is None:
        draw.text(
            (margin_left, margin_top),
            "Click in the chart to place the first waypoint",
            fill=AXIS_TEXT_COLOR,
            font=font_label,
        )
        return img
    max_time, max_depth = axes

    def x_of(t: float) -> float:
        return xy_of(t, 0.0, width, height, axes)[0]

    def y_of(depth: float) -> float:
        return xy_of(0.0, depth, width, height, axes)[1]

    grid_step = 5.0 if max_depth <= 30 else 10.0
    d = 0.0
    while d <= max_depth:
        y = y_of(d)
        draw.line([(margin_left, y), (width - margin_right, y)], fill=GRID_COLOR, width=1)
        draw.text((4, y - 6), f"{int(d)}m", fill=AXIS_TEXT_COLOR, font=font_small)
        d += grid_step

    time_step = 300 if max_time <= 1800 else 600
    t = 0
    while t <= max_time:
        x = x_of(t)
        draw.line([(x, margin_top), (x, height - margin_bottom)], fill=GRID_COLOR, width=1)
        draw.text((x - 12, height - margin_bottom + 6), _format_mmss(t), fill=AXIS_TEXT_COLOR, font=font_small)
        t += time_step

    if plan.max_depth_m:
        y = y_of(plan.max_depth_m)
        for x0 in range(margin_left, width - margin_right, 12):
            draw.line([(x0, y), (min(x0 + 6, width - margin_right), y)], fill=AXIS_TEXT_COLOR, width=1)

    if not samples and not plan.waypoints:
        draw.text(
            (margin_left + 8, margin_top + 8),
            "Click to place a waypoint · drag a point to move it · right-click to delete",
            fill=AXIS_TEXT_COLOR,
            font=font_label,
        )

    if waypoints_only:
        wps = plan.sorted_waypoints()
        points = [(x_of(0), y_of(0))] + [(x_of(wp.runtime_sec), y_of(wp.depth_m)) for wp in wps]
        draw.line(points, fill=DEPTH_LINE_COLOR, width=1)
        cursor_time = None
    else:
        if deco_schedules:
            _draw_deco_schedules(img, deco_schedules, deco_schedule_interval_sec, x_of, y_of)
            draw = ImageDraw.Draw(img)
        points = [(x_of(s.time_sec), y_of(s.depth_m)) for s in samples]
        for i in range(len(points) - 1):
            draw.line([points[i], points[i + 1]], fill=gas_color(plan, samples[i + 1].gas_id), width=3)
        areas = []
        if deco_schedules:
            areas.append(("Deco stops", DECO_STOP_RGB))
        _draw_gas_legend(draw, plan, samples, width - margin_right - 8, height - margin_bottom - 8, font_small, areas)

    for wp in plan.sorted_waypoints():
        x, y = x_of(wp.runtime_sec), y_of(wp.depth_m)
        draw.ellipse([x - 4, y - 4, x + 4, y + 4], fill=WAYPOINT_COLOR, outline=BG_COLOR)

    if cursor_time is not None:
        nearest = nearest_sample(samples, cursor_time)
        if nearest is not None:
            x = x_of(nearest.time_sec)
            draw.line([(x, margin_top), (x, height - margin_bottom)], fill=CURSOR_COLOR, width=1)
            cx, cy = x, y_of(nearest.depth_m)
            draw.ellipse([cx - 5, cy - 5, cx + 5, cy + 5], outline=CURSOR_COLOR, width=2)

            if nearest.ceiling_m > 0:
                readout = (
                    f"{_format_mmss(nearest.time_sec)}  {nearest.depth_m:.0f}m  "
                    f"DECO → {nearest.stop_depth_m:.0f}m ({_format_mmss(nearest.stop_duration_sec)})  "
                    f"TTS {_format_mmss(nearest.tts_sec)}"
                )
                readout_color = DECO_COLOR
            elif nearest.ndl_sec is not None:
                readout = f"{_format_mmss(nearest.time_sec)}  {nearest.depth_m:.0f}m  NDL {nearest.ndl_sec // 60}min"
                readout_color = NDL_COLOR
            else:
                readout = f"{_format_mmss(nearest.time_sec)}  {nearest.depth_m:.0f}m  NDL 99+min"
                readout_color = NDL_COLOR

            gas = plan.gas_by_id(nearest.gas_id)
            if gas is not None:
                readout += f"  ·  {gas.id}"

            if show_readout:
                draw.text((margin_left, 4), readout, fill=readout_color, font=font_label)

    return img
