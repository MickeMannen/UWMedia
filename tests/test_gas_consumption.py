"""utils/gas_consumption.py - SAC and GTR the way the Perdix 2 manual (p.41)
defines them, for logs that record tank pressure only."""
from datetime import datetime, timedelta

from models.dive import TankData, Waypoint
from utils.gas_consumption import fill_sac_and_gtr


def _dive(depth_m, bar_per_min, seconds=600, tanks=1, start_bar=200.0):
    """A steady dive at `depth_m` burning `bar_per_min` (tank pressure, not
    surface-normalised) per tank."""
    t0 = datetime(2026, 1, 1)
    wps = []
    for t in range(0, seconds + 1, 10):
        pressure = start_bar - bar_per_min * t / 60.0
        wps.append(Waypoint(
            timestamp=t0 + timedelta(seconds=t), depth=depth_m, time_since_start=t,
            tanks={f"T{i + 1}": TankData(pressure_bar=pressure, o2_percent=21.0) for i in range(tanks)},
        ))
    return wps


def test_sac_is_the_two_minute_pressure_rate_at_the_surface_equivalent():
    wps = _dive(20.0, bar_per_min=3.0)  # 3 bar/min at 3 ata = 1.0 bar/min SAC
    fill_sac_and_gtr(wps)
    assert wps[3].pressure_sac is None       # first 30 s: nothing yet ("wait")
    assert wps[6].pressure_sac is None       # less than half the window collected
    late = wps[-1]
    assert abs(late.pressure_sac - 1.0) < 0.02


def test_gtr_counts_reserve_and_the_ascent_at_10m_per_min():
    wps = _dive(20.0, bar_per_min=3.0, seconds=300)
    fill_sac_and_gtr(wps, reserve_bar=50.0)
    wp = wps[-1]
    pressure = wp.tanks["T1"].pressure_bar  # 185 bar
    ascent_min = 2.0                        # 20 m at 10 m/min
    p_ascent = 1.0 * ascent_min * 2.0       # SAC x minutes x average ambient (2 ata)
    expected_min = (pressure - 50.0 - p_ascent) / (1.0 * 3.0)
    assert abs(wp.air_remaining / 60.0 - expected_min) < 0.5


def test_sidemount_pair_sums_both_tanks_and_keeps_a_reserve_in_each():
    wps = _dive(10.0, bar_per_min=1.0, seconds=300, tanks=2)  # 2 bar/min total at 2 ata = 1.0 SAC
    fill_sac_and_gtr(wps, reserve_bar=50.0)
    wp = wps[-1]
    assert abs(wp.pressure_sac - 1.0) < 0.02
    total = sum(t.pressure_bar for t in wp.tanks.values())
    expected_min = (total - 100.0 - 1.0 * 1.0 * 1.5) / (1.0 * 2.0)
    assert abs(wp.air_remaining / 60.0 - expected_min) < 0.5


def test_logged_values_are_left_alone():
    wps = _dive(20.0, bar_per_min=3.0, seconds=300)
    wps[-1].pressure_sac = 9.9
    wps[-1].air_remaining = 42
    fill_sac_and_gtr(wps)
    assert (wps[-1].pressure_sac, wps[-1].air_remaining) == (9.9, 42)
    assert wps[-2].pressure_sac is not None
