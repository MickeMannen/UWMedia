"""The post-pass every profile parser runs once its samples are read: the
Buhlmann recompute (utils.deco_engine.DiveDecompressor) for ceiling/TTS/
GF/CNS where the log doesn't carry them, then SAC/GTR
(utils.gas_consumption). Same rules as the block in parsers/uddf.py and
parsers/subsurface.py: a value the log itself recorded always wins over
the recompute."""
import math
from typing import List, Optional, Sequence, Tuple

from models.dive import Waypoint
from utils.deco_engine import DiveDecompressor, GasDefinition
from utils.gas_consumption import fill_sac_and_gtr


def deco_gas(name: str, o2_percent: float, he_percent: float) -> GasDefinition:
    """A GasDefinition with its MOD at PPO2 1.4."""
    f_o2 = o2_percent / 100.0
    mod = ((1.4 / f_o2) - 1.0) * 10.0 if f_o2 > 0 else 0.0
    return GasDefinition(name=name, f_o2=f_o2, f_he=he_percent / 100.0, mod_meters=max(0, mod))


def apply_deco_and_gas(
    waypoints: List[Waypoint],
    gases: Sequence[GasDefinition],
    file_gf: Optional[Tuple[float, float]] = None,
) -> None:
    """Fills ceiling, and TTS/deco stop/GF/PO2 where still None, plus CNS
    and next stop depth, then SAC/GTR on waypoints that have none."""
    if not waypoints:
        return
    try:
        gases = list(gases) or [GasDefinition("AIR", 0.21, 0.0, 56.0)]
        decompressor = (
            DiveDecompressor(gf_low=file_gf[0], gf_high=file_gf[1], simulation_interval=10)
            if file_gf else DiveDecompressor(simulation_interval=10)
        )
        wp_dicts = [wp.model_dump() for wp in waypoints]
        for d in wp_dicts:
            d['divetime'] = d['time_since_start']
            d['datetime'] = d['timestamp']
        deco_results = decompressor.process_waypoints(wp_dicts, gases)

        for wp in waypoints:
            res = deco_results.get(wp.time_since_start)
            if not res:
                continue
            if wp.tts is None:
                wp.tts = res.tts_seconds
            wp.ceiling = res.ceiling_meters
            if wp.deco_stop_depth is None:
                wp.deco_stop_depth = res.ceiling_meters
            if wp.gf is None:
                wp.gf = res.gf_current
            if wp.po2 is None:
                wp.po2 = round(res.po2, 2)
            wp.cns = int(res.cns)
            ceiling = wp.deco_stop_depth or 0.0
            wp.next_stop_depth = math.ceil(ceiling / 3.0) * 3.0 if ceiling > 0 else 0.0
            if wp.next_stop_time is None:
                wp.next_stop_time = 0
    except Exception as e:
        print(f"Warning: Decompression calculation failed for dive: {e}")

    fill_sac_and_gtr(waypoints)


def parse_gf(low, high) -> Optional[Tuple[float, float]]:
    """(low, high) as 0-1 fractions from percent values, or None when
    missing or not 0 < low <= high <= 100."""
    try:
        gf = (float(low) / 100.0, float(high) / 100.0)
    except (TypeError, ValueError):
        return None
    return gf if 0 < gf[0] <= gf[1] <= 1.0 else None
