import math
from datetime import datetime
from typing import Iterable, List, Literal, Optional, Tuple
from pydantic import BaseModel, Field, model_validator

from utils.deco_engine import mod_meters
from utils.dive_computers import DEFAULT_DIVE_COMPUTER

GasType = Literal["air", "nitrox", "trimix"]
# "oc" open circuit, "sidemount" open circuit breathed from a left and a
# right tank of the same gas (PlannedGas.side), "ccr" closed circuit
# rebreather - the diluent gas is the loop, every other gas is an
# open-circuit bailout.
DiveType = Literal["oc", "sidemount", "ccr"]
# Sidemount dives only: which side a tank is worn on. None = a stage tank.
SidemountSide = Literal["left", "right"]
# Which part of the dive a gas's depth range applies to: "descent" covers the
# descent and bottom phase, "ascent" everything after the deepest waypoint
# (deco/travel gases on the way up), "any" both. See
# utils.dive_plan_engine.auto_gas_for_waypoint.
GasPhase = Literal["any", "descent", "ascent"]


# Tank reference of a CCR dive's O2 cylinder (not a PlannedGas - it's never
# breathed directly, the loop draws on it to hold the setpoint).
CCR_O2_TANK_REF = "O2"


class TankSpec(BaseModel):
    """One physical tank of the dive, as the log writers record it."""

    ref: str
    size_l: float
    start_pressure_bar: float
    o2_percent: float
    he_percent: float
    role: Literal["oc", "diluent", "oxygen"] = "oc"  # oc = breathed open circuit (incl. bailout)
    gas_id: Optional[str] = None  # the PlannedGas filled in it; None for the CCR O2 cylinder


class PlannedGas(BaseModel):
    """One gas available to a hand-built dive profile. On a CCR dive the
    diluent gas is the loop: its breathed fraction is computed per-depth to
    hold the plan's setpoint (DiveProfilePlan.setpoint_at, see
    utils.deco_engine.ccr_effective_fractions)."""

    id: str = Field(..., description="Unique label, e.g. 'Bottom', 'Deco 50%'")
    gas_type: GasType = "air"
    o2_percent: float = Field(21.0, ge=1.0, le=100.0)
    he_percent: float = Field(0.0, ge=0.0, le=99.0)
    diluent: bool = Field(False, description="CCR dives only: this gas is the loop's diluent; the others are open-circuit bailout")
    side: Optional[SidemountSide] = Field(None, description="Sidemount dives only: the side this tank is worn on. The left and the right tank (same gas) are breathed alternately, switching every DiveProfilePlan.sidemount_switch_bar; the right one is never picked on its own. None = a stage tank")
    tank_ref: str = Field("T1", description="UDDF tank reference this gas is breathed from")
    # Defaults: an AL80 (11.1 L water volume, 207 bar / 3000 psi service pressure).
    tank_size_l: float = Field(11.1, gt=0)
    start_pressure_bar: float = Field(207.0, ge=0)
    sac_lpm: Optional[float] = Field(None, ge=0, description="Per-gas SAC override in L/min; None uses the plan's own sac_lpm")
    use_min_depth_m: Optional[float] = Field(None, ge=0, description="Shallow end of the depth range this gas is auto-assigned in; None = from the surface")
    use_max_depth_m: Optional[float] = Field(None, ge=0, description="Deep end of the depth range this gas is auto-assigned in; None = no limit")
    use_phase: GasPhase = "any"
    color: Optional[str] = Field(None, description="#RRGGBB the profile line is drawn in while this gas is breathed; None = palette colour by position (gui.dive_profile_view.gas_color)")

    @property
    def has_depth_range(self) -> bool:
        return self.use_min_depth_m is not None or self.use_max_depth_m is not None

    def covers_depth(self, depth_m: float) -> bool:
        low = self.use_min_depth_m if self.use_min_depth_m is not None else 0.0
        high = self.use_max_depth_m if self.use_max_depth_m is not None else float("inf")
        return low <= depth_m <= high

    @property
    def f_o2(self) -> float:
        return self.o2_percent / 100.0

    @property
    def f_he(self) -> float:
        return self.he_percent / 100.0

    @property
    def mod_m(self) -> float:
        return mod_meters(self.f_o2, max_po2=1.4)


class PlannedWaypoint(BaseModel):
    """A single hand-placed point on the profile. The transition arriving
    here happens immediately after the previous waypoint's runtime_sec, at
    rate_m_per_min (or the plan's default for that direction); whatever time
    remains before this waypoint's own runtime_sec is spent holding at
    depth_m. See utils.dive_plan_engine.expand_plan for the exact rule."""

    runtime_sec: int = Field(..., ge=0, description="Absolute elapsed dive time, in seconds")
    depth_m: float = Field(..., ge=0)
    gas_id: str
    rate_m_per_min: Optional[float] = Field(None, gt=0, description="Override for the transition arriving here; None uses the plan default for that direction")
    phase: Optional[Literal["descent", "ascent"]] = Field(None, description="Forces this waypoint's phase for auto gas choice / PO2 limits; None = derived (utils.dive_plan_engine.waypoint_phases). Set on End dive's waypoints, which can sit at the dive's max depth yet belong to the ascent")
    gas_auto: bool = Field(False, description="True: gas_id is re-derived from the gases' depth ranges whenever the plan changes (utils.dive_plan_engine.apply_auto_gases)")


class DiveProfilePlan(BaseModel):
    name: str = "Custom Dive"
    gf_low: float = Field(30.0, ge=0, le=100)
    gf_high: float = Field(70.0, ge=0, le=100)
    default_descent_rate: float = Field(20.0, gt=0, description="m/min")
    default_ascent_rate: float = Field(9.0, gt=0, description="m/min")
    water_temp_c: float = Field(20.0)
    sac_lpm: float = Field(20.0, ge=0, description="Surface air consumption in L/min for every gas without its own override - drives the simulated tank-pressure curves")
    max_po2_bottom: float = Field(1.4, ge=0.5, le=2.0, description="Highest acceptable PO2 on the descent/bottom - limits each gas's MOD there")
    max_po2_deco: float = Field(1.6, ge=0.5, le=2.0, description="Highest acceptable PO2 on the ascent/deco - limits each gas's MOD there")
    max_depth_m: Optional[float] = Field(None, gt=0, description="Planned max depth - fixes the chart's depth axis so waypoints can be placed by clicking")
    planned_runtime_sec: Optional[int] = Field(None, gt=0, description="Planned runtime - fixes the chart's time axis the same way")
    dive_type: DiveType = "oc"
    ccr_low_setpoint: float = Field(0.7, ge=0.4, le=1.6, description="Loop PO2 shallower than ccr_setpoint_switch_depth_m")
    ccr_high_setpoint: float = Field(1.3, ge=0.4, le=1.6, description="Loop PO2 at and below ccr_setpoint_switch_depth_m")
    ccr_setpoint_switch_depth_m: float = Field(6.0, ge=0, description="Auto setpoint switch depth, used both ways")
    ccr_o2_tank_size_l: float = Field(3.0, gt=0)
    ccr_o2_start_pressure_bar: float = Field(200.0, ge=0)
    sidemount_switch_bar: float = Field(30.0, gt=0, description="Sidemount: switch to the other tank of a pair once the one breathed is this far below it")
    # Log metadata, written into the saved files.
    start_time: Optional[datetime] = Field(None, description="Local dive start; None = the time of saving")
    computer: str = Field(DEFAULT_DIVE_COMPUTER, description="utils.dive_computers.DIVE_COMPUTERS label the log poses as")
    computer_serial: str = Field("12345678", description="Digits only - FIT stores the serial as a number")
    gases: List[PlannedGas] = Field(default_factory=list)
    waypoints: List[PlannedWaypoint] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _split_sidemount_pairs(cls, data):
        """Plans saved before tanks had a side (embedded in the logs older
        versions wrote) marked one gas as a sidemount pair, breathed from
        <tank_ref>L and <tank_ref>R. That gas becomes the left tank, plus
        a right tank of the same gas (split_sidemount_pair)."""
        if not isinstance(data, dict) or not isinstance(data.get("gases"), list):
            return data
        gases = []
        for gas in data["gases"]:
            if isinstance(gas, dict) and gas.get("sidemount_pair"):
                taken = [g.get("tank_ref", "T1") if isinstance(g, dict) else g.tank_ref for g in data["gases"]]
                taken += [g["tank_ref"] for g in gases]
                has_side = any((g.get("side") if isinstance(g, dict) else g.side) for g in gases)
                gases += split_sidemount_pair(gas, taken, first=not has_side)
            else:
                gases.append(gas)
        return {**data, "gases": gases}

    def sorted_waypoints(self) -> List[PlannedWaypoint]:
        return sorted(self.waypoints, key=lambda wp: wp.runtime_sec)

    def gas_by_id(self, gas_id: str) -> Optional[PlannedGas]:
        return next((g for g in self.gases if g.id == gas_id), None)

    @property
    def is_ccr(self) -> bool:
        return self.dive_type == "ccr"

    def diluent_gas(self) -> Optional[PlannedGas]:
        """The loop gas of a CCR dive; None on OC/sidemount dives."""
        if not self.is_ccr:
            return None
        return next((g for g in self.gases if g.diluent), None)

    def on_loop(self, gas: PlannedGas) -> bool:
        """Breathing this gas means breathing the rebreather loop."""
        return self.is_ccr and gas.diluent

    def setpoint_at(self, depth_m: float) -> float:
        return self.ccr_high_setpoint if depth_m >= self.ccr_setpoint_switch_depth_m else self.ccr_low_setpoint

    def sidemount_tanks(self) -> Optional[Tuple[PlannedGas, PlannedGas]]:
        """(left, right) of a sidemount dive; None on other dive types or
        while either side is missing."""
        if self.dive_type != "sidemount":
            return None
        left = next((g for g in self.gases if g.side == "left"), None)
        right = next((g for g in self.gases if g.side == "right"), None)
        return (left, right) if left is not None and right is not None else None

    def sidemount_error(self) -> Optional[str]:
        """Why this sidemount dive can't be built yet; None when it can (or
        isn't a sidemount dive)."""
        if self.dive_type == "sidemount" and self.sidemount_tanks() is None:
            return "Sidemount needs two tanks of the same gas: set one tank's side to Left and another's to Right"
        return None

    def breathed_gas(self, gas: PlannedGas) -> PlannedGas:
        """The gas a tank stands for: a sidemount dive's right tank is its
        left tank's gas (the pair is one gas, breathed from either side)."""
        pair = self.sidemount_tanks()
        return pair[0] if pair is not None and gas is pair[1] else gas

    def breathed_gas_id(self, gas_id: str) -> str:
        gas = self.gas_by_id(gas_id)
        return self.breathed_gas(gas).id if gas is not None else gas_id

    def breathed_gases(self) -> List[PlannedGas]:
        """The gases the diver can switch between - every gas but a
        sidemount dive's right tank, which is breathed as part of the
        left tank's gas."""
        pair = self.sidemount_tanks()
        return [g for g in self.gases if pair is None or g is not pair[1]]

    def tank_refs_for(self, gas: PlannedGas) -> List[str]:
        """The tank(s) a gas is breathed from - both sidemount tanks, left
        first, for either of them."""
        pair = self.sidemount_tanks()
        if pair is not None and gas in pair:
            return [pair[0].tank_ref, pair[1].tank_ref]
        return [gas.tank_ref]

    def gas_for_tank(self, ref: str) -> Optional[PlannedGas]:
        """The gas row whose own tank this is (a sidemount right tank's
        row, not the gas it's breathed as)."""
        return next((g for g in self.gases if g.tank_ref == ref), None)

    def tank_specs(self) -> List[TankSpec]:
        """Every tank of the dive: a CCR dive's O2 cylinder first, then the
        gases' tanks in gas order. A sidemount right tank holds its left
        tank's gas. Gases sharing a tank_ref share the first one's tank."""
        specs: List[TankSpec] = []
        if self.is_ccr:
            specs.append(TankSpec(
                ref=CCR_O2_TANK_REF, size_l=self.ccr_o2_tank_size_l,
                start_pressure_bar=self.ccr_o2_start_pressure_bar,
                o2_percent=100.0, he_percent=0.0, role="oxygen",
            ))
        seen = {s.ref for s in specs}
        for gas in self.gases:
            if gas.tank_ref in seen:
                continue
            seen.add(gas.tank_ref)
            specs.append(TankSpec(
                ref=gas.tank_ref, size_l=gas.tank_size_l, start_pressure_bar=gas.start_pressure_bar,
                o2_percent=gas.o2_percent, he_percent=gas.he_percent,
                role="diluent" if self.on_loop(gas) else "oc", gas_id=self.breathed_gas(gas).id,
            ))
        return specs

    def sac_for(self, gas: PlannedGas) -> float:
        return self.sac_lpm if gas.sac_lpm is None else gas.sac_lpm

    def max_po2_for(self, phase: str) -> float:
        return self.max_po2_deco if phase == "ascent" else self.max_po2_bottom

    def gas_mod_m(self, gas: PlannedGas, phase: str) -> Optional[float]:
        """MOD at the user's PO2 limit for this phase ("descent"/"ascent"),
        floored to 0.1m so a waypoint placed at it never exceeds the limit.
        None for a CCR diluent - the loop holds its setpoint, so the limit
        doesn't apply the same way."""
        if self.on_loop(gas):
            return None
        return math.floor(mod_meters(gas.f_o2, max_po2=self.max_po2_for(phase)) * 10) / 10

    def gas_display_mod_m(self, gas: PlannedGas) -> float:
        """MOD shown in the gas table: at the deco PO2 for ascent/deco gases,
        the bottom PO2 otherwise (a CCR diluent shows PlannedGas.mod_m)."""
        mod = self.gas_mod_m(gas, "ascent" if gas.use_phase == "ascent" else "descent")
        return gas.mod_m if mod is None else mod

    def gas_usable_at(self, gas: PlannedGas, depth_m: float, phase: str) -> bool:
        """Inside the gas's own depth range and phase, and within its MOD."""
        if gas.use_phase not in ("any", phase) or not gas.covers_depth(depth_m):
            return False
        mod = self.gas_mod_m(gas, phase)
        return mod is None or depth_m <= mod

    def gas_deepest_use_m(self, gas: PlannedGas, phase: str) -> float:
        """Deep end of where the gas may be auto-picked: its range, capped at
        its MOD for this phase."""
        high = gas.use_max_depth_m if gas.use_max_depth_m is not None else float("inf")
        mod = self.gas_mod_m(gas, phase)
        return high if mod is None else min(high, mod)


def split_sidemount_pair(gas: dict, taken_refs: Iterable[str], first: bool = True,
                         right_ref: Optional[str] = None) -> List[dict]:
    """A gas from an older plan or a log that was one sidemount pair (tanks
    <tank_ref>L/<tank_ref>R) as two tanks: the gas itself on the left, in
    its own tank_ref, and "<name> R" on the right in `right_ref` or else
    the next free T<n>.
    Only the dive's first pair gets sides (one left/right set per dive);
    a later one becomes a stage tank."""
    left = {k: v for k, v in gas.items() if k != "sidemount_pair"}
    if not first:
        return [left]
    left["side"] = "left"
    if right_ref is None:
        taken = set(taken_refs) | {left.get("tank_ref", "T1")}
        n = 1
        while f"T{n}" in taken:
            n += 1
        right_ref = f"T{n}"
    right = {**left, "id": f"{left['id']} R", "side": "right", "tank_ref": right_ref, "color": None}
    return [left, right]
