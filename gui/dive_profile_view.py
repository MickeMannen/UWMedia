from typing import List, Optional

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

# Shared with the app's drag-scrub handler (uwmedia/app.py) via time_from_x
# below, so the pixel-to-time mapping used for scrubbing always matches what
# was actually drawn.
MARGIN_LEFT = 50
MARGIN_RIGHT = 16


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


def render_profile_image(
    plan: DiveProfilePlan,
    samples: List[SimulatedSample],
    width: int,
    height: int,
    cursor_time: Optional[float] = None,
) -> Image.Image:
    """Renders the depth-vs-time chart for the dive profile builder as a PIL
    image. Matches this app's existing canvas convention of rendering
    everything to a raster image and calling `canvas.draw_image()` - no
    canvas in this app draws vector paths directly (see
    uwmedia/app.py's `_redraw_designer_canvas`/`_draw_progress_bar`)."""
    img = Image.new("RGB", (max(1, width), max(1, height)), BG_COLOR)
    draw = ImageDraw.Draw(img)
    font_small = get_font(12)
    font_label = get_font(14)

    margin_left, margin_right, margin_top, margin_bottom = MARGIN_LEFT, MARGIN_RIGHT, 26, 28
    plot_w = max(1, width - margin_left - margin_right)
    plot_h = max(1, height - margin_top - margin_bottom)

    if not samples:
        draw.text(
            (margin_left, margin_top),
            "Add waypoints to preview the profile",
            fill=AXIS_TEXT_COLOR,
            font=font_label,
        )
        return img

    max_time = max(s.time_sec for s in samples) or 1
    max_depth = max((s.depth_m for s in samples), default=1.0)
    max_depth = max(max_depth, 5.0) * 1.1  # headroom so the line doesn't hug the bottom axis

    def x_of(t: float) -> float:
        return margin_left + (t / max_time) * plot_w

    def y_of(depth: float) -> float:
        return margin_top + (depth / max_depth) * plot_h

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

    points = [(x_of(s.time_sec), y_of(s.depth_m)) for s in samples]
    for i in range(len(points) - 1):
        color = DECO_COLOR if samples[i].ceiling_m > 0 else DEPTH_LINE_COLOR
        draw.line([points[i], points[i + 1]], fill=color, width=2)

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

            draw.text((margin_left, 4), readout, fill=readout_color, font=font_label)

    return img
