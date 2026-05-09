from datetime import datetime
from typing import List, Optional, Dict
from pydantic import BaseModel, Field

class TankData(BaseModel):
    pressure_bar: float = Field(..., description="Tank pressure in bar")
    o2_percent: float = Field(21.0, description="Oxygen percentage")
    he_percent: float = Field(0.0, description="Helium percentage")
    name: Optional[str] = Field(None, description="Tank name/sensor ID")
    mode: Optional[str] = Field(None, description="Dive mode (OC/CC)")
    enabled: Optional[bool] = Field(None, description="Whether the tank is active")

class Waypoint(BaseModel):
    timestamp: datetime
    depth: float = Field(..., description="Depth in meters")
    temp: float = Field(..., description="Temperature in Celsius")
    deco_stop_depth: Optional[float] = Field(None, description="Current deco stop depth in meters")
    tts: Optional[int] = Field(None, description="Time to surface in seconds")
    ndl: Optional[int] = Field(None, description="No deco limit in seconds")
    time_since_start: int = Field(..., description="Seconds since start of dive")
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

    @property
    def duration(self) -> int:
        return int((self.end_time - self.start_time).total_seconds())
