from typing import List, Literal, Optional
from pydantic import BaseModel, Field

from utils.deco_engine import mod_meters

GasType = Literal["air", "nitrox", "trimix", "ccr"]


class PlannedGas(BaseModel):
    """One gas available to a hand-built dive profile. For gas_type == 'ccr',
    o2_percent/he_percent describe the diluent - the loop's actual breathed
    fraction is computed per-depth to hold ccr_setpoint constant (see
    utils.deco_engine.ccr_effective_fractions)."""

    id: str = Field(..., description="Unique label, e.g. 'Bottom', 'Deco 50%'")
    gas_type: GasType = "air"
    o2_percent: float = Field(21.0, ge=1.0, le=100.0)
    he_percent: float = Field(0.0, ge=0.0, le=99.0)
    ccr_setpoint: Optional[float] = Field(None, description="Target loop PO2 in bar, only used when gas_type == 'ccr'")
    tank_ref: str = Field("T1", description="UDDF tank reference this gas is breathed from")
    tank_size_l: float = Field(15.0, gt=0)
    start_pressure_bar: float = Field(200.0, ge=0)
    sac_lpm: float = Field(20.0, ge=0, description="Surface air consumption, drives the simulated tank-pressure curve")

    @property
    def f_o2(self) -> float:
        return self.o2_percent / 100.0

    @property
    def f_he(self) -> float:
        return self.he_percent / 100.0

    @property
    def is_ccr(self) -> bool:
        return self.gas_type == "ccr"

    @property
    def mod_m(self) -> float:
        max_po2 = self.ccr_setpoint if self.is_ccr and self.ccr_setpoint else 1.4
        return mod_meters(self.f_o2, max_po2=max_po2)


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


class DiveProfilePlan(BaseModel):
    name: str = "Custom Dive"
    gf_low: float = Field(30.0, ge=0, le=100)
    gf_high: float = Field(70.0, ge=0, le=100)
    default_descent_rate: float = Field(20.0, gt=0, description="m/min")
    default_ascent_rate: float = Field(9.0, gt=0, description="m/min")
    water_temp_c: float = Field(20.0)
    gases: List[PlannedGas] = Field(default_factory=list)
    waypoints: List[PlannedWaypoint] = Field(default_factory=list)

    def sorted_waypoints(self) -> List[PlannedWaypoint]:
        return sorted(self.waypoints, key=lambda wp: wp.runtime_sec)

    def gas_by_id(self, gas_id: str) -> Optional[PlannedGas]:
        return next((g for g in self.gases if g.id == gas_id), None)
