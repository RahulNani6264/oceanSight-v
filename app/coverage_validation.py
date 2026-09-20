from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime

@dataclass(frozen=True)
class DatasetCoverage:
 west: float; east: float; south: float; north: float
 start_utc: datetime | None = None; end_utc: datetime | None = None
 def contains(self, lat: float, lon: float, when: datetime | None = None) -> bool:
  if not (-90 <= lat <= 90): return False
  lon = ((lon + 180) % 360) - 180
  spatial = self.west <= lon <= self.east if self.west <= self.east else lon >= self.west or lon <= self.east
  temporal = (self.start_utc is None or when is None or when >= self.start_utc) and (self.end_utc is None or when is None or when <= self.end_utc)
  return spatial and self.south <= lat <= self.north and temporal

def validate_point(coverage: DatasetCoverage, lat: float, lon: float, when: datetime | None = None):
 if not coverage.contains(lat, lon, when):
  raise ValueError('Requested location or time is outside the installed dataset coverage.')
