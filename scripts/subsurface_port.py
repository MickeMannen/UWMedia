"""A small Python port of Subsurface's Bühlmann ZHL-16C open-circuit planner,
used to cross-check our planner (utils/dive_plan_engine.py) on the same
profile with fresh tissues. scripts/deco_reference.py's `port` command and
tests/test_deco_reference.py run it.

Ported from Subsurface's core/deco.cpp (add_segment, tissue_tolerance_calc,
deco_allowed_depth) and core/planner.cpp (plan, trial_ascent, wait_until,
ascent_velocity), as of the source in October 2026. What it keeps from
Subsurface:
- tissues start at (surface - water vapour) x 78.1 % N2, air is 20.9 % O2;
- depth to pressure through the water's salinity (sea water by default);
- the profile is linear between waypoints, one tissue step per second;
- the GF slope runs in pressure from the deepest GF-low ceiling seen in the
  dive (at least 1 bar below the surface) to GF high at the surface;
- a stop is held while a trial ascent to the next 3 m level would break the
  ceiling on the way, and ends on a whole minute of runtime (wait_until);
- ascent rates per depth band (75 % / 50 % of average depth, stops, last 6 m).

What it leaves out: helium, gas switches, CCR, VPM-B, the safety stop and
previous dives. A single-gas nitrox or air plan only.
"""
import math
from typing import List, Optional, Sequence, Tuple

N2_A = [1.1696, 1.0, 0.8618, 0.7562, 0.62, 0.5043, 0.441, 0.4,
        0.375, 0.35, 0.3295, 0.3065, 0.2835, 0.261, 0.248, 0.2327]
N2_B = [0.5578, 0.6514, 0.7222, 0.7825, 0.8126, 0.8434, 0.8693, 0.8910,
        0.9092, 0.9222, 0.9319, 0.9403, 0.9477, 0.9544, 0.9602, 0.9653]
N2_HALFLIFE = [5.0, 8.0, 12.5, 18.5, 27.0, 38.3, 54.3, 77.0,
               109.0, 146.0, 187.0, 239.0, 305.0, 390.0, 498.0, 635.0]
WV_PRESSURE = 0.0627       # bar, Bühlmann's value
N2_IN_AIR = 0.781          # Subsurface's tissue start value
O2_IN_AIR = 0.209
SEAWATER_SALINITY = 10300  # g / 10 l
GF_LOW_POSITION_MIN = 1.0  # bar below the surface
STOP_STEP_MM = 3000
BASE_TIMESTEP = 2          # seconds per ascent step
DECO_TIMESTEP = 60         # stop times end on whole minutes


class _Tissues:
    def __init__(self, surface_bar: float):
        self.n2 = [(surface_bar - WV_PRESSURE) * N2_IN_AIR] * 16
        self.gf_low_pressure = surface_bar + GF_LOW_POSITION_MIN

    def copy(self) -> "_Tissues":
        c = _Tissues.__new__(_Tissues)
        c.n2 = list(self.n2)
        c.gf_low_pressure = self.gf_low_pressure
        return c


class SubsurfacePlanner:
    def __init__(
        self,
        gf_low: float,
        gf_high: float,
        o2_percent: float,
        surface_mbar: float = 1013.0,
        salinity: int = SEAWATER_SALINITY,
        ascent_rates: Sequence[float] = (9, 9, 9, 9),
    ):
        """GF in percent. ascent_rates in m/min: below 75 % of the average
        depth, below 50 %, from there to 6 m, the last 6 m (Subsurface's
        defaults are all 9)."""
        self.gf_low, self.gf_high = gf_low / 100.0, gf_high / 100.0
        self.f_n2 = 1.0 - o2_percent / 100.0
        self.surface = surface_mbar / 1000.0
        self.mbar_per_mm = salinity * 0.981 / 100000.0
        self.rates = [int(r * 1000 / 60) for r in ascent_rates]  # mm/s, truncated as in Subsurface

    def _bar(self, depth_mm: int) -> float:
        return round(self.surface * 1000 + depth_mm * self.mbar_per_mm) / 1000.0

    def _add(self, t: _Tissues, depth_mm: int, seconds: int) -> None:
        inspired = (self._bar(depth_mm) - WV_PRESSURE) * self.f_n2
        for i in range(16):
            t.n2[i] += (inspired - t.n2[i]) * (1.0 - math.exp(-seconds * math.log(2) / 60.0 / N2_HALFLIFE[i]))

    def _tolerated(self, t: _Tissues) -> float:
        """Ambient pressure the tissues tolerate (tissue_tolerance_calc);
        also moves the GF-low anchor deeper when the GF-low ceiling is."""
        gl, gh, surf = self.gf_low, self.gf_high, self.surface
        for a, b, p in zip(N2_A, N2_B, t.n2):
            t.gf_low_pressure = max(t.gf_low_pressure, (b * p - gl * a * b) / ((1 - b) * gl + b))
        g = t.gf_low_pressure
        ret = 0.0
        for a, b, p in zip(N2_A, N2_B, t.n2):
            if (surf / b + a - surf) * gh + surf < (g / b + a - g) * gl + g:
                tol = ((-a * b * (gh * g - gl * surf) - (1 - b) * (gh - gl) * g * surf + b * (g - surf) * p)
                       / (-a * b * (gh - gl) + (1 - b) * (gl * g - gh * surf) + b * (g - surf)))
            else:
                tol = ret
            ret = max(ret, tol)
        return ret

    def _ceiling_mm(self, t: _Tissues) -> int:
        delta = max(0.0, self._tolerated(t) - self.surface)
        return int(round(delta * 1000) / self.mbar_per_mm)

    def _velocity(self, depth_mm: int, avg_mm: float) -> int:
        if depth_mm * 4 > avg_mm * 3:
            return self.rates[0]
        if depth_mm * 2 > avg_mm:
            return self.rates[1]
        return self.rates[2] if depth_mm > 6000 else self.rates[3]

    def _trial_ascent(self, t: _Tissues, wait: int, depth: int, stop: int, avg: float) -> bool:
        t = t.copy()
        if wait:
            self._add(t, depth, wait)
        while depth > stop:
            step = min(self._velocity(depth, avg) * BASE_TIMESTEP, depth)
            self._add(t, depth, BASE_TIMESTEP)
            if self._ceiling_mm(t) > depth - step:
                return False
            depth -= step
        return True

    def _wait_until(self, t: _Tissues, clock: int, low: int, leap: int, depth: int, target: int, avg: float) -> int:
        while True:
            if low >= 48 * 3600:
                return 50 * 3600
            upper = low + leap + DECO_TIMESTEP - 1 - (low + leap - 1) % DECO_TIMESTEP
            if not self._trial_ascent(t, upper - clock, depth, target, avg):
                low = upper
                continue
            if upper - low <= DECO_TIMESTEP:
                return upper
            leap //= 2

    def plan(self, waypoints: Sequence[Tuple[int, float]]) -> Tuple[List[Tuple[float, float]], float]:
        """waypoints: (runtime_sec, depth_m) after an implicit surface start
        at 0 s, linear in between. Returns ([(stop_depth_m, minutes)],
        runtime_min) for the ascent from the last waypoint."""
        points = [(0, 0)] + [(int(s), int(round(d * 1000))) for s, d in waypoints if s > 0]
        t = _Tissues(self.surface)
        for (t0, d0), (t1, d1) in zip(points, points[1:]):
            for j in range(t0, t1):
                self._add(t, int(d0 + (d1 - d0) * (j - t0) / (t1 - t0)), 1)
        avg = sum((d0 + d1) * (t1 - t0) / 2 for (t0, d0), (t1, d1) in zip(points, points[1:])) / points[-1][0]
        clock, depth = points[-1]
        levels = [k * STOP_STEP_MM for k in range(depth // STOP_STEP_MM + 2)]
        idx = max(k for k, level in enumerate(levels) if level <= depth)
        self._tolerated(t)
        stops: List[Tuple[float, float]] = []
        last_stop = DECO_TIMESTEP
        while True:
            while True:  # ascend to the next stop level
                step = self._velocity(depth, avg) * BASE_TIMESTEP
                step = min(step, depth - levels[idx])
                self._add(t, depth, BASE_TIMESTEP)
                clock += BASE_TIMESTEP
                depth -= step
                if not (depth > 0 and depth > levels[idx]):
                    break
            if depth <= 0:
                break
            idx -= 1
            if not self._trial_ascent(t, 0, depth, levels[idx], avg):
                new_clock = self._wait_until(t, clock, clock, last_stop * 2 + 1, depth, levels[idx], avg)
                last_stop = new_clock - clock
                self._add(t, depth, last_stop)
                stops.append((depth / 1000.0, last_stop / 60.0))
                clock = new_clock
        return stops, clock / 60.0


def plan_reference(ref: dict, waypoints: Sequence[Tuple[int, float]]) -> Optional[Tuple[List[Tuple[float, float]], float]]:
    """The port on a reference dive (tests/deco_reference/*.json) along
    `waypoints`; None for a dive it can't plan (more than one gas, helium)."""
    if len(ref["gases"]) != 1 or ref["gases"][0]["he_percent"] > 0:
        return None
    gas = ref["gases"][0]
    o2 = O2_IN_AIR * 100 if gas["name"].strip().lower() == "air" else gas["o2_percent"]
    s = ref["settings"]
    planner = SubsurfacePlanner(s["gf_low"], s["gf_high"], o2, surface_mbar=s.get("surface_pressure_mbar") or 1013.0)
    return planner.plan(waypoints)
