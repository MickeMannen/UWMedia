from datetime import datetime
from typing import List, Optional, Dict
from pydantic import BaseModel, Field

class TankData(BaseModel):
    pressure_bar: float = Field(..., description="Tank pressure in bar")
    o2_percent: float = Field(21.0, description="Oxygen percentage")
    he_percent: float = Field(0.0, description="Helium percentage")

class Waypoint(BaseModel):
    timestamp: datetime
    depth: float = Field(..., description="Depth in meters")
    temp: float = Field(..., description="Temperature in Celsius")
    deco_stop_depth: Optional[float] = Field(None, description="Current deco stop depth in meters")
    tts: Optional[int] = Field(None, description="Time to surface in minutes")
    ndl: Optional[int] = Field(None, description="No deco limit in minutes")
    time_since_start: int = Field(..., description="Seconds since start of dive")
    tanks: Dict[str, TankData] = Field(default_factory=dict, description="Data for multiple tanks, keyed by tank ID")

class Dive(BaseModel):
    start_time: datetime
    end_time: datetime
    waypoints: List[Waypoint]
    
    @property
    def duration(self) -> int:
        return int((self.end_time - self.start_time).total_seconds())
