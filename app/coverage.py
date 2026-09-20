from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone

@dataclass(frozen=True)
class Coverage:
    west: float; east: float; south: float; north: float
    start_utc: str|None=None; end_utc: str|None=None
    def contains(self,lat:float,lon:float,time_utc:str|None=None)->bool:
        lon=((lon+180)%360)-180
        spatial=self.south<=lat<=self.north and self.west<=lon<=self.east
        if not spatial:return False
        if time_utc and (self.start_utc and time_utc<self.start_utc or self.end_utc and time_utc>self.end_utc):return False
        return True

def validate_request(c:Coverage,lat:float,lon:float,time_utc:str|None=None):
    if not c.contains(lat,lon,time_utc):
        raise ValueError("Requested location or time is outside the installed dataset coverage.")
