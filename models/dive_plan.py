import math
from datetime import datetime
from typing import List, Literal, Optional
from pydantic import BaseModel, Field

from utils.deco_engine import mod_meters
from utils.dive_computers import DEFAULT_DIVE_COMPUTER

GasType = Literal["air", "nitrox", "trimix"]
# "oc" open circuit, "sidemount" open circuit with paired left/right tanks
# (PlannedGas.sidemount_pair), "ccr" closed circuit rebreather - the
# diluent gas is the loop, every other gas is an open-circuit bailout.
DiveType = Literal["oc", "sidemount", "ccr"]
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
    sidemount_pair: bool = Field(False, description="Sidemount dives only: breathed from two identical tanks, <tank_ref>L and <tank_ref>R, alternated every DiveProfilePlan.sidemount_switch_bar")
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

    def tank_refs_for(self, gas: PlannedGas) -> List[str]:
        """The tank(s) a gas is breathed from - a left/right pair for a
        sidemount-paired gas, left first."""
        if self.dive_type == "sidemount" and gas.sidemount_pair:
            return [f"{gas.tank_ref}L", f"{gas.tank_ref}R"]
        return [gas.tank_ref]

    def tank_specs(self) -> List[TankSpec]:
        """Every tank of the dive: a CCR dive's O2 cylinder first, then the
        gases' tanks in gas order (a sidemount pair left then right). Gases
        sharing a tank_ref share the first one's tank."""
        specs: List[TankSpec] = []
        if self.is_ccr:
            specs.append(TankSpec(
                ref=CCR_O2_TANK_REF, size_l=self.ccr_o2_tank_size_l,
                start_pressure_bar=self.ccr_o2_start_pressure_bar,
                o2_percent=100.0, he_percent=0.0, role="oxygen",
            ))
        seen = {s.ref for s in specs}
        for gas in self.gases:
            for ref in self.tank_refs_for(gas):
                if ref in seen:
                    continue
                seen.add(ref)
                specs.append(TankSpec(
                    ref=ref, size_l=gas.tank_size_l, start_pressure_bar=gas.start_pressure_bar,
                    o2_percent=gas.o2_percent, he_percent=gas.he_percent,
                    role="diluent" if self.on_loop(gas) else "oc", gas_id=gas.id,
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
