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
    n2: Optional[float] = None
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
    def duration(self) -> int:
        return int((self.end_time - self.start_time).total_seconds())

    def get_waypoint_at(self, target_time: datetime) -> Optional[Waypoint]:
        """Finds the waypoint closest to the given timestamp."""
        if not self.waypoints:
            return None
        
        # Binary search for the insertion point
        # self.waypoints should be sorted by timestamp
        timestamps = [w.timestamp for w in self.waypoints]
        idx = bisect.bisect_left(timestamps, target_time)
        
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
