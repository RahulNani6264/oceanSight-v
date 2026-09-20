from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent
ARGO_DB = PROJECT_ROOT / "processed" / "argo_store.sqlite"

EARTH_RADIUS_KM = 6371.0088
DEFAULT_RADIUS_KM = 100.0
DEFAULT_LIMIT = 100
MAX_RADIUS_KM = 2000.0


@dataclass(frozen=True)
class SensorType:
    id: str
    name: str
    connected: bool
    source: str | None
    dataset: str | None
    description: str


SENSOR_TYPES: tuple[SensorType, ...] = (
    SensorType(
        id="argo_float",
        name="Argo Float",
        connected=True,
        source="INCOIS ERDDAP",
        dataset="Indian_ARGO_Floats",
        description=(
            "Autonomous Argo profiling float represented by real INCOIS "
            "observations available in the OceanSight store or live source."
        ),
    ),
    SensorType(
        id="surface_buoy",
        name="Surface Buoy",
        connected=False,
        source=None,
        dataset=None,
        description="No verified buoy data source is currently connected to OceanSight.",
    ),
    SensorType(
        id="drifter",
        name="Surface Drifter",
        connected=False,
        source=None,
        dataset=None,
        description="No verified drifter data source is currently connected to OceanSight.",
    ),
    SensorType(
        id="fixed_station",
        name="Fixed Station",
        connected=False,
        source=None,
        dataset=None,
        description="No verified fixed-station data source is currently connected to OceanSight.",
    ),
)


class OceanSensorEngine:
    """
    Unified observation-platform service for OceanSight.

    Phase 5 deliberately exposes only platforms backed by a verified source.
    The current verified platform is the INCOIS Indian Argo dataset.

    Geographic discovery uses a true great-circle distance filter for local
    observations. No synthetic sensor locations are generated.
    """

    def __init__(self, db_path: str | Path = ARGO_DB) -> None:
        self.db_path = Path(db_path)
        if not self.db_path.exists():
            raise FileNotFoundError(
                "INCOIS Argo database does not exist: "
                f"{self.db_path}"
            )

    @staticmethod
    def _normalize_longitude(longitude: float) -> float:
        value = float(longitude)
        if not math.isfinite(value):
            raise ValueError("longitude must be finite")
        while value > 180.0:
            value -= 360.0
        while value < -180.0:
            value += 360.0
        return value

    @staticmethod
    def _validate_latitude(latitude: float) -> float:
        value = float(latitude)
        if not math.isfinite(value):
            raise ValueError("latitude must be finite")
        if not -90.0 <= value <= 90.0:
            raise ValueError("latitude must be between -90 and 90")
        return value

    @staticmethod
    def _haversine_km(
        latitude_1: float,
        longitude_1: float,
        latitude_2: float,
        longitude_2: float,
    ) -> float:
        phi1 = math.radians(latitude_1)
        phi2 = math.radians(latitude_2)
        dphi = math.radians(latitude_2 - latitude_1)
        dlambda = math.radians(longitude_2 - longitude_1)

        a = (
            math.sin(dphi / 2.0) ** 2
            + math.cos(phi1)
            * math.cos(phi2)
            * math.sin(dlambda / 2.0) ** 2
        )
        return EARTH_RADIUS_KM * 2.0 * math.atan2(
            math.sqrt(a),
            math.sqrt(max(0.0, 1.0 - a)),
        )

    @staticmethod
    def _parse_time(value: str | None) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            raise ValueError("time_utc cannot be empty when supplied")
        normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError as exc:
            raise ValueError(
                "time_utc must be a valid ISO-8601 timestamp"
            ) from exc
        if parsed.tzinfo is None:
            raise ValueError("time_utc must include an explicit timezone")
        return (
            parsed.astimezone(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def sensor_types() -> list[dict[str, Any]]:
        return [
            {
                "id": item.id,
                "name": item.name,
                "connected": item.connected,
                "source": item.source,
                "dataset": item.dataset,
                "description": item.description,
            }
            for item in SENSOR_TYPES
        ]

    def discover_local(
        self,
        latitude: float,
        longitude: float,
        radius_km: float = DEFAULT_RADIUS_KM,
        time_utc: str | None = None,
        limit: int = DEFAULT_LIMIT,
    ) -> list[dict[str, Any]]:
        latitude = self._validate_latitude(latitude)
        longitude = self._normalize_longitude(longitude)
        radius_km = float(radius_km)
        limit = int(limit)
        normalized_time = self._parse_time(time_utc)

        if not math.isfinite(radius_km) or radius_km <= 0.0:
            raise ValueError("radius_km must be greater than zero")
        if radius_km > MAX_RADIUS_KM:
            raise ValueError(f"radius_km cannot exceed {MAX_RADIUS_KM}")
        if not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")

        # First use a conservative latitude/longitude candidate window to
        # keep SQLite work bounded; final inclusion is a great-circle test.
        delta_lat = radius_km / 111.1950802335
        cos_lat = max(0.01, math.cos(math.radians(latitude)))
        delta_lon = min(180.0, radius_km / (111.1950802335 * cos_lat))

        connection = self._connect()
        try:
            rows = connection.execute(
                """
                SELECT
                    platform_number,
                    cycle_number,
                    direction,
                    profile_time_utc,
                    juld_location_utc,
                    latitude,
                    longitude,
                    source,
                    source_dataset,
                    source_url,
                    ingested_at_utc
                FROM argo_observations
                WHERE latitude BETWEEN ? AND ?
                  AND longitude BETWEEN ? AND ?
                GROUP BY
                    platform_number,
                    cycle_number,
                    direction,
                    profile_time_utc,
                    juld_location_utc,
                    latitude,
                    longitude,
                    source,
                    source_dataset,
                    source_url,
                    ingested_at_utc
                ORDER BY profile_time_utc DESC
                LIMIT 5000
                """,
                (
                    latitude - delta_lat,
                    latitude + delta_lat,
                    longitude - delta_lon,
                    longitude + delta_lon,
                ),
            ).fetchall()
        finally:
            connection.close()

        sensors: list[dict[str, Any]] = []
        for row in rows:
            row_latitude = row["latitude"]
            row_longitude = row["longitude"]
            if row_latitude is None or row_longitude is None:
                continue

            distance_km = self._haversine_km(
                latitude,
                longitude,
                float(row_latitude),
                float(row_longitude),
            )
            if distance_km > radius_km:
                continue

            row_time = row["profile_time_utc"]
            if normalized_time is not None and row_time != normalized_time:
                continue

            sensors.append(
                {
                    "sensor_id": f"argo:{row['platform_number']}:{row['cycle_number']}",
                    "sensor_type": "argo_float",
                    "platform_number": str(row["platform_number"]),
                    "cycle_number": int(row["cycle_number"]),
                    "direction": row["direction"],
                    "latitude": float(row_latitude),
                    "longitude": float(row_longitude),
                    "profile_time_utc": row_time,
                    "distance_from_query_km": round(distance_km, 3),
                    "position": {
                        "latitude": float(row_latitude),
                        "longitude": float(row_longitude),
                        "coordinate_reference_system": "EPSG:4326",
                    },
                    "vertical_information": {
                        "platform_position_is_surface_location": True,
                        "profile_pressure_unit": "dbar",
                        "pressure_is_depth": False,
                        "pressure_to_depth_conversion_performed": False,
                    },
                    "source": row["source"] or "INCOIS ERDDAP",
                    "dataset": row["source_dataset"] or "Indian_ARGO_Floats",
                    "source_url": row["source_url"],
                    "ingested_at_utc": row["ingested_at_utc"],
                    "synthetic_data": False,
                    "interpolation": False,
                }
            )

            if len(sensors) >= limit:
                break

        return sensors

    @staticmethod
    def filter_sensor_type(
        sensors: list[dict[str, Any]],
        sensor_type: str | None,
    ) -> list[dict[str, Any]]:
        if sensor_type is None:
            return sensors
        normalized = str(sensor_type).strip().lower()
        if not normalized:
            return sensors
        return [item for item in sensors if item.get("sensor_type") == normalized]
