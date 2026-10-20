"""The camera's clock against the dive computer's: how the Color page shows
the offset and reads a dive time typed from the computer's display.

A clip is matched to its dive by the time the camera wrote into the file.
That time is off by the camera's timezone setting (whole hours, usually)
and by however far its clock has drifted (seconds, sometimes minutes). The
Color page lets the user set both while watching the preview; the total
goes to the CLI as `--media-shift <seconds>`. Only the matching uses it -
the file's own time is written to the output unchanged.
"""
import re
from typing import Optional


def format_offset(seconds: float) -> str:
    """"+2 h 14 s", "-37 s", "+1 h", "0 s" - an offset the way the page shows it."""
    total = int(round(seconds))
    if total == 0:
        return "0 s"
    sign = "+" if total > 0 else "-"
    total = abs(total)
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    parts = []
    if hours:
        parts.append(f"{hours} h")
    if minutes:
        parts.append(f"{minutes} min")
    if secs or not parts:
        parts.append(f"{secs} s")
    return sign + " ".join(parts)


def parse_dive_time(text: str) -> Optional[float]:
    """Seconds from what a dive computer shows as its dive time: "12:34",
    "1:02:03", "12.34" (minutes.seconds the way some people type it),
    "754" (plain seconds), "12m34s". None when it is not a time."""
    s = str(text or "").strip().lower().replace(" ", "")
    if not s:
        return None
    if "m" in s or "s" in s or "h" in s:
        m = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?", s)
        if not m or not any(m.groups()):
            return None
        h, mi, se = (int(g) if g else 0 for g in m.groups())
        return float(h * 3600 + mi * 60 + se)
    if ":" in s:
        sep = ":"
    elif s.count(".") == 1 and all(p.isdigit() for p in s.split(".")) and len(s.split(".")[1]) == 2:
        sep = "."
    else:
        try:
            return float(s)
        except ValueError:
            return None
    parts = s.split(sep)
    if not all(p.isdigit() for p in parts) or len(parts) > 3:
        return None
    nums = [int(p) for p in parts]
    while len(nums) < 3:
        nums.insert(0, 0)
    h, mi, se = nums
    if se >= 60 or (len(parts) == 3 and mi >= 60):
        return None
    return float(h * 3600 + mi * 60 + se)
