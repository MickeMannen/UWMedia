from datetime import datetime
from typing import List, Optional, Dict
from pydantic import BaseModel, Field
import bisect

class TankData(BaseModel):
    pressure_bar: float = Field(..., description="Tank pressure in bar")
    o2_percent: float = Field(21.0, description="Oxygen percentage")
    he_percent: float = Field(0.0, description="Helium percentage")
    name: Optional[str] = Field(None, description="Tank name/sensor ID")
    mode: Optional[str] = Field(None, description="Dive mode (OC/CC)")
    enabled: Optional[bool] = Field(None, description="Whether the tank is active")

class Waypoint(BaseModel):
    timestamp: datetime
    depth: Optional[float] = Field(None, description="Depth in meters")
    temp: Optional[float] = Field(None, description="Temperature in Celsius")
    max_depth: float = Field(0.0, description="Maximum depth reached until this waypoint")
    deco_stop_depth: Optional[float] = Field(None, description="Current deco stop depth in meters")
    tts: Optional[int] = Field(None, description="Time to surface in seconds")
    ndl: Optional[int] = Field(None, description="No deco limit in seconds")
    time_since_start: int = Field(..., description="Seconds since start of dive")
    dive_time: Optional[int] = Field(None, description="Elapsed dive time in seconds")
    tanks: Dict[str, TankData] = Field(default_factory=dict, description="Data for multiple tanks, keyed by tank ID")
    
    # Extended Garmin Fields
    next_stop_depth: Optional[float] = None
    next_stop_time: Optional[int] = None
    air_remaining: Optional[int] = None
    ascent_rate: Optional[float] = None
    n2_tissue_load: Optional[float] = Field(
        None,
        description=(
            "Garmin N2 tissue load, already a percentage (FIT field 'n2_load' is declared "
            "units=percent/scale=1/offset=0 in garmin_fit_sdk's own profile) - just not "
            "bounded to 0-100, since tissue supersaturation can legitimately exceed 100% at "
            "depth (confirmed 0-338 over one real dive)"
        ),
    )
    pressure_sac: Optional[float] = None
    volume_sac: Optional[float] = None
    rmv: Optional[float] = None
    heart_rate: Optional[int] = None
    cns: Optional[int] = None
    po2: Optional[float] = None
    divemode: Optional[str] = None
    gf: Optional[float] = None
    switchmix: Optional[float] = None
    battery: Optional[float] = None
    cleared_gas_mix: Optional[str] = Field(
        None, description="Backup/next gas shown during a gas-switch prompt (Shearwater); distinct from the currently-breathed gasmix"
    )
    po2_1: Optional[float] = Field(None, description="CCR cell 1 partial pressure of oxygen (bar) - distinct from the single OC po2 reading")
    po2_2: Optional[float] = Field(None, description="CCR cell 2 partial pressure of oxygen (bar)")
    po2_3: Optional[float] = Field(None, description="CCR cell 3 partial pressure of oxygen (bar)")
    dive_alerts: List[str] = Field(
        default_factory=list,
        description="Dive-alert event names (Garmin FIT event_mesgs 'dive_alert' field) at/before this waypoint's timestamp, since the previous waypoint - used by hud_rules_engine.resolve_state() as a state signal where available",
    )

    # Reference to parent dive info
    _dive: Optional['Dive'] = None

    @property
    def log_filename(self) -> Optional[str]:
        return self._dive.log_filename if self._dive else None

    @property
    def primary_tank_pressure(self) -> Optional[float]:
        """Returns the pressure of the first tank in the dictionary."""
        if not self.tanks:
            return None
        # Get the first tank's pressure
        first_tank = next(iter(self.tanks.values()))
        return first_tank.pressure_bar

    @property
    def primary_tank_name(self) -> Optional[str]:
        """Display name of the first tank - whatever the diver named it on their own
        device, falling back to its dict key. Lets a generic template (e.g. Garmin
        x50i's main page) show a tank's own name without hardcoding a specific diver's
        naming, unlike the tank_name:<key> field which needs a literal key."""
        if not self.tanks:
            return None
        key, first_tank = next(iter(self.tanks.items()))
        return first_tank.name or key

    @property
    def secondary_tank_pressure(self) -> Optional[float]:
        """Pressure of the second tank (sidemount's second cylinder), if any."""
        if len(self.tanks) < 2:
            return None
        return list(self.tanks.values())[1].pressure_bar

    @property
    def secondary_tank_name(self) -> Optional[str]:
        """Display name of the second tank - see primary_tank_name."""
        if len(self.tanks) < 2:
            return None
        key, second_tank = list(self.tanks.items())[1]
        return second_tank.name or key

    @property
    def gasmix(self) -> str:
        """Returns the gas mix string for the primary tank."""
        if not self.tanks:
            return "N/A"
        
        first_tank = next(iter(self.tanks.values()))
        o2 = round(first_tank.o2_percent)
        he = round(first_tank.he_percent)
        
        if he != 0:
            return f"{he:02d}/{o2:02d}"
        elif o2 >= 22:
            return f"Nx{o2:02d}"
        elif o2 == 21:
            return "AIR"
        else:
            return f"{o2:02d}%"

class Dive(BaseModel):
    start_time: datetime
    end_time: datetime
    waypoints: List[Waypoint]
    
    # Extended Meta Data
    device: Optional[str] = None
    manufactor: Optional[str] = None
    start_latitude: Optional[float] = None
    start_longitude: Optional[float] = None
    end_latitude: Optional[float] = None
    end_longitude: Optional[float] = None
    timezone: Optional[str] = None
    duration_seconds: Optional[int] = None
    
    # Source Info
    log_filename: Optional[str] = None
    log_path: Optional[str] = None

    def model_post_init(self, __context) -> None:
        """Set back-reference to parent dive on all waypoints."""
        for wp in self.waypoints:
            wp._dive = self

    @property
    def max_depth(self) -> float:
        if not self.waypoints:
            return 0.0
        return max((wp.depth or 0.0) for wp in self.waypoints)

    @property
    def duration(self) -> int:
        return int((self.end_time - self.start_time).total_seconds())

    def invalidate_timestamp_cache(self):
        """Call after mutating waypoints (slicing, tz adjustments, etc.)."""
        self._ts_cache = None

    def get_waypoint_at(self, target_time: datetime) -> Optional[Waypoint]:
        """Finds the waypoint closest to the given timestamp.
        Uses a cached timestamps list to avoid O(N) allocation per call."""
        if not self.waypoints:
            return None
        
        # Build / reuse cached timestamp list for binary search
        ts = getattr(self, '_ts_cache', None)
        if ts is None or len(ts) != len(self.waypoints):
            ts = [w.timestamp for w in self.waypoints]
            self._ts_cache = ts

        idx = bisect.bisect_left(ts, target_time)
        
        if idx == 0:
            return self.waypoints[0]
        if idx == len(self.waypoints):
            return self.waypoints[-1]
            
        # Check which one is closer: idx or idx-1
        before = self.waypoints[idx-1]
        after = self.waypoints[idx]
        
        if (target_time - before.timestamp) < (after.timestamp - target_time):
            return before
        return after
