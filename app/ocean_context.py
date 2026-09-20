from __future__ import annotations

import math
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, TypeAlias

from .ocean_geometry import OceanGeometryEngine
from .ocean_regions import OceanRegionEngine
from .ocean_sensors import OceanSensorEngine

from .ocean_variables import get_variable_definition


EARTH_RADIUS_KM = 6371.0088
DEFAULT_RADIUS_KM = 50.0
MAX_RADIUS_KM = 2000.0


class OceanContextEngine:
    """
    Build one lightweight scientific context shared by Ocean Dashboard and
    Block Dashboard.

    This engine intentionally returns orchestration metadata and geometry,
    while leaving large numerical payloads to the dedicated volume,
    bathymetry, and sensor endpoints. It never creates synthetic scientific
    observations or interpolated time points.
    """

    def __init__(
        self,
        *,
        region_engine: OceanRegionEngine,
        geometry_engine: OceanGeometryEngine,
        time_engine: Any,
        sensor_engine: OceanSensorEngine,
    ) -> None:
        self.region_engine = region_engine
        self.geometry_engine = geometry_engine
        self.time_engine = time_engine
        self.sensor_engine = sensor_engine

    @staticmethod
    def _normalize_latitude(latitude: float) -> float:
        value = float(latitude)
        if not math.isfinite(value) or value < -90.0 or value > 90.0:
            raise ValueError("latitude must be between -90 and 90 degrees.")
        return value

    @staticmethod
    def _normalize_longitude(longitude: float) -> float:
        value = float(longitude)
        if not math.isfinite(value):
            raise ValueError("longitude must be a finite number.")
        normalized = ((value + 180.0) % 360.0) - 180.0
        if math.isclose(normalized, -180.0, abs_tol=1e-12):
            return 180.0
        return normalized

    @staticmethod
    def _parse_reference_time(value: str | None) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            raise ValueError("reference_time_utc must include an explicit timezone.")
        return (
            parsed.astimezone(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )

    @staticmethod
    def _bbox_from_radius(
        latitude: float,
        longitude: float,
        radius_km: float,
    ) -> dict[str, float]:
        if not math.isfinite(radius_km) or radius_km <= 0.0:
            raise ValueError("radius_km must be greater than zero.")
        if radius_km > MAX_RADIUS_KM:
            raise ValueError(f"radius_km cannot exceed {MAX_RADIUS_KM} km.")

        delta_lat = radius_km / 111.1950802335
        cos_lat = max(0.01, math.cos(math.radians(latitude)))
        delta_lon = min(180.0, radius_km / (111.1950802335 * cos_lat))

        return {
            "latitude_min": max(-90.0, latitude - delta_lat),
            "latitude_max": min(90.0, latitude + delta_lat),
            "longitude_min": longitude - delta_lon,
            "longitude_max": longitude + delta_lon,
        }

    @staticmethod
    def _geometry_bbox(
        geometry_bbox: dict[str, float] | None,
    ) -> dict[str, float] | None:
        if geometry_bbox is None:
            return None
        return {
            "latitude_min": float(geometry_bbox["min_latitude"]),
            "latitude_max": float(geometry_bbox["max_latitude"]),
            "longitude_min": float(geometry_bbox["min_longitude"]),
            "longitude_max": float(geometry_bbox["max_longitude"]),
        }

    def _resolve_selection(
        self,
        *,
        ocean: str | None,
        latitude: float | None,
        longitude: float | None,
    ) -> tuple[str, str, dict[str, Any] | None]:
        selected_ocean: str | None = ocean
        identification: dict[str, Any] | None = None

        if latitude is not None or longitude is not None:
            if latitude is None or longitude is None:
                raise ValueError(
                    "latitude and longitude must be supplied together."
                )

            identification = self.region_engine.identify_dict(
                latitude=latitude,
                longitude=longitude,
            )

            if not identification.get("available"):
                raise ValueError(
                    "The selected coordinate is not identified as an ocean by "
                    "the real RECCAP2 regional mask."
                )

            detected = identification.get("ocean") or {}
            detected_name = detected.get("name")
            detected_region = detected.get("source_region")
            if not detected_name or not detected_region:
                raise ValueError(
                    "The selected coordinate did not return a valid ocean region."
                )

            if selected_ocean is not None:
                requested_name, requested_region = (
                    self.geometry_engine.normalize_ocean_name(selected_ocean)
                )
                if requested_region != detected_region:
                    raise ValueError(
                        "The supplied ocean does not contain the selected "
                        "coordinate according to the real RECCAP2 mask."
                    )
                selected_ocean = requested_name
                return requested_name, requested_region, identification

            selected_ocean = detected_name
            return detected_name, detected_region, identification

        if selected_ocean is None:
            raise ValueError(
                "Provide either ocean or a latitude/longitude coordinate."
            )

        selected_name, selected_region = self.geometry_engine.normalize_ocean_name(
            selected_ocean
        )
        return selected_name, selected_region, identification

    def build_context(
        self,
        *,
        mode: str,
        ocean: str | None = None,
        latitude: float | None = None,
        longitude: float | None = None,
        radius_km: float = DEFAULT_RADIUS_KM,
        variable: str = "TEMP",
        reference_time_utc: str | None = None,
        past_hours: float = 24.0,
        future_hours: float = 24.0,
        include_sensors: bool = True,
        sensor_limit: int = 100,
    ) -> dict[str, Any]:
        normalized_mode = str(mode).strip().lower()
        if normalized_mode not in {"ocean", "block"}:
            raise ValueError("mode must be 'ocean' or 'block'.")

        normalized_latitude = (
            self._normalize_latitude(latitude) if latitude is not None else None
        )
        normalized_longitude = (
            self._normalize_longitude(longitude) if longitude is not None else None
        )

        if normalized_mode == "block" and (
            normalized_latitude is None or normalized_longitude is None
        ):
            raise ValueError(
                "Block context requires latitude and longitude."
            )

        normalized_radius = float(radius_km)
        if not math.isfinite(normalized_radius) or normalized_radius <= 0.0:
            raise ValueError("radius_km must be greater than zero.")
        if normalized_radius > MAX_RADIUS_KM:
            raise ValueError(f"radius_km cannot exceed {MAX_RADIUS_KM} km.")

        normalized_variable = str(variable).strip()
        if not normalized_variable:
            raise ValueError("variable cannot be empty.")
        variable_definition = get_variable_definition(normalized_variable)

        normalized_reference_time = self._parse_reference_time(reference_time_utc)

        selected_name, selected_region, identification = self._resolve_selection(
            ocean=ocean,
            latitude=normalized_latitude,
            longitude=normalized_longitude,
        )

        boundary = self.geometry_engine.boundary(selected_name)
        if not boundary.available or boundary.geometry is None:
            raise LookupError(
                f"No real boundary is available for {selected_name}."
            )

        if normalized_mode == "block":
            bbox = self._bbox_from_radius(
                normalized_latitude,
                normalized_longitude,
                normalized_radius,
            )
        else:
            bbox = self._geometry_bbox(boundary.bounding_box)

        time_window = self.time_engine.window(
            reference_time_utc=normalized_reference_time,
            past_hours=float(past_hours),
            future_hours=float(future_hours),
        )

        sensors: list[dict[str, Any]] = []
        sensor_acquisition: dict[str, Any]
        if include_sensors and normalized_latitude is not None and normalized_longitude is not None:
            sensors = self.sensor_engine.discover_local(
                latitude=normalized_latitude,
                longitude=normalized_longitude,
                radius_km=normalized_radius,
                time_utc=normalized_reference_time,
                limit=int(sensor_limit),
            )
            sensor_acquisition = {
                "mode": "local",
                "available": bool(sensors),
                "source": "INCOIS ERDDAP",
                "dataset": "Indian_ARGO_Floats",
                "note": "Unified context includes locally indexed verified sensors; the dedicated sensor endpoint may perform live acquisition.",
            }
        else:
            sensor_acquisition = {
                "mode": "not_requested",
                "available": False,
                "source": None,
                "dataset": None,
            }

        if normalized_mode == "ocean":
            spatial_selection = {
                "type": "ocean_basin",
                "ocean_boundary": deepcopy(boundary.geometry),
                "bounding_box": bbox,
            }
        else:
            spatial_selection = {
                "type": "radius_block",
                "center": {
                    "latitude": normalized_latitude,
                    "longitude": normalized_longitude,
                    "coordinate_reference_system": "EPSG:4326",
                },
                "radius_km": normalized_radius,
                "bounding_box": bbox,
                "ocean_boundary": deepcopy(boundary.geometry),
            }

        return {
            "available": True,
            "context_version": "1.0",
            "mode": normalized_mode,
            "selection": {
                "ocean": {
                    "name": selected_name,
                    "source_region": selected_region,
                },
                "coordinate": (
                    {
                        "latitude": normalized_latitude,
                        "longitude": normalized_longitude,
                        "coordinate_reference_system": "EPSG:4326",
                    }
                    if normalized_latitude is not None and normalized_longitude is not None
                    else None
                ),
                "region_identification": identification,
            },
            "spatial": spatial_selection,
            "variable": variable_definition,
            "time": time_window,
            "sensors": {
                "count": len(sensors),
                "items": sensors,
                "acquisition": sensor_acquisition,
            },
            "downstream": {
                "volume_endpoint": "/api/v1/ocean/volume",
                "bathymetry_endpoint": "/api/v1/ocean/bathymetry",
                "sensors_endpoint": "/api/v1/ocean/sensors",
                "sensor_detail_endpoint": "/api/v1/ocean/sensor",
                "boundary_endpoint": "/api/v1/ocean/boundary",
                "time_window_endpoint": "/api/v1/ocean/time-window",
                "time_range_endpoint": "/api/v1/ocean/time-range",
            },
            "scientific_rules": {
                "synthetic_data": False,
                "interpolation": False,
                "source_mask_ocean_identification": True,
                "source_mask_boundary_geometry": True,
                "source_time_catalog_only": True,
                "sensor_position_source_data_only": True,
            },
        }


__all__ = ["OceanContextEngine", "DEFAULT_RADIUS_KM", "MAX_RADIUS_KM"]
