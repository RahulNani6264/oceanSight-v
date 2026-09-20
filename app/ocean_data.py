from __future__ import annotations

import math
from copy import deepcopy
from typing import Any, Sequence

from .ocean_bathymetry import OceanBathymetryEngine
from .ocean_geometry import OceanGeometryEngine
from .ocean_volume import OceanVolumeEngine
from .ocean_variables import (
    get_variable_definition,
    normalize_variable_name,
)
from .ocean_external import OceanExternalDataEngine


DEFAULT_RADIUS_KM = 50.0
MAX_RADIUS_KM = 2000.0


class OceanDataEngine:
    """Route frontend scientific-data requests to real data engines."""

    DIRECT_HYCOM = {
        "temperature": "TEMP",
        "salinity": "SALN",
        "current_u": "UVEL",
        "current_v": "VVEL",
        "sea_surface_height": "SSH",
    }

    DERIVED = {
        "current_speed",
        "current_direction",
    }

    EXTERNAL_SURFACE_VARIABLES = {
        "wind",
        "air_pressure",
        "chlorophyll",
    }

    def __init__(
        self,
        *,
        volume_engine: OceanVolumeEngine,
        bathymetry_engine: OceanBathymetryEngine,
        geometry_engine: OceanGeometryEngine,
        external_engine: OceanExternalDataEngine | None = None,
    ) -> None:
        self.volume_engine = volume_engine
        self.bathymetry_engine = bathymetry_engine
        self.geometry_engine = geometry_engine
        self.external_engine = external_engine or OceanExternalDataEngine(
            geometry_engine=geometry_engine
        )

    @staticmethod
    def _lat(value: float) -> float:
        value = float(value)

        if not math.isfinite(value) or not -90.0 <= value <= 90.0:
            raise ValueError(
                "latitude must be between -90 and 90 degrees."
            )

        return value

    @staticmethod
    def _lon(value: float) -> float:
        value = float(value)

        if not math.isfinite(value):
            raise ValueError("longitude must be finite.")

        return ((value + 180.0) % 360.0) - 180.0

    @staticmethod
    def _radius_bbox(
        latitude: float,
        longitude: float,
        radius_km: float,
    ) -> dict[str, float]:
        if (
            not math.isfinite(radius_km)
            or radius_km <= 0
            or radius_km > MAX_RADIUS_KM
        ):
            raise ValueError(
                "radius_km must be greater than zero and no more than "
                f"{MAX_RADIUS_KM} km."
            )

        km_per_degree = 111.1950802335
        delta_lat = radius_km / km_per_degree

        cos_lat = max(
            0.01,
            math.cos(math.radians(latitude)),
        )

        delta_lon = min(
            180.0,
            radius_km / (km_per_degree * cos_lat),
        )

        return {
            "latitude_min": max(-90.0, latitude - delta_lat),
            "latitude_max": min(90.0, latitude + delta_lat),
            "longitude_min": longitude - delta_lon,
            "longitude_max": longitude + delta_lon,
        }

    @staticmethod
    def _validate_bbox(
        bbox: dict[str, float],
    ) -> dict[str, float]:
        required_keys = (
            "latitude_min",
            "latitude_max",
            "longitude_min",
            "longitude_max",
        )

        missing = [
            key
            for key in required_keys
            if key not in bbox
        ]

        if missing:
            raise ValueError(
                "Bounding box is missing required values: "
                + ", ".join(missing)
            )

        normalized = {
            key: float(bbox[key])
            for key in required_keys
        }

        if not all(
            math.isfinite(value)
            for value in normalized.values()
        ):
            raise ValueError(
                "Bounding-box values must be finite."
            )

        if not (
            -90.0
            <= normalized["latitude_min"]
            <= 90.0
        ):
            raise ValueError(
                "latitude_min must be between -90 and 90."
            )

        if not (
            -90.0
            <= normalized["latitude_max"]
            <= 90.0
        ):
            raise ValueError(
                "latitude_max must be between -90 and 90."
            )

        if not (
            -180.0
            <= normalized["longitude_min"]
            <= 180.0
        ):
            raise ValueError(
                "longitude_min must be between -180 and 180."
            )

        if not (
            -180.0
            <= normalized["longitude_max"]
            <= 180.0
        ):
            raise ValueError(
                "longitude_max must be between -180 and 180."
            )

        if (
            normalized["latitude_min"]
            > normalized["latitude_max"]
        ):
            raise ValueError(
                "latitude_min cannot exceed latitude_max."
            )

        if (
            normalized["longitude_min"]
            > normalized["longitude_max"]
        ):
            raise ValueError(
                "longitude_min cannot exceed longitude_max."
            )

        return normalized

    def _geometry_bbox(
        self,
        boundary: Any,
    ) -> dict[str, float]:
        if boundary.bounding_box is None:
            raise LookupError(
                "Selected ocean has no real boundary bounding box."
            )

        bounding_box = boundary.bounding_box

        return self._validate_bbox(
            {
                "latitude_min": bounding_box["min_latitude"],
                "latitude_max": bounding_box["max_latitude"],
                "longitude_min": bounding_box["min_longitude"],
                "longitude_max": bounding_box["max_longitude"],
            }
        )

    @staticmethod
    def _depths(
        depths_m: Sequence[float] | None,
    ) -> list[float] | None:
        if depths_m is None:
            return None

        values = sorted(
            {
                round(float(depth), 6)
                for depth in depths_m
            }
        )

        if not values:
            raise ValueError(
                "depths_m must contain at least one depth."
            )

        if values[0] < 0:
            raise ValueError(
                "depths_m must contain positive or zero numeric depths."
            )

        return values

    def _select(
        self,
        *,
        mode: str,
        ocean: str | None,
        latitude: float | None,
        longitude: float | None,
        radius_km: float,
        bbox: dict[str, float] | None = None,
    ) -> tuple[
        str,
        dict[str, Any],
        dict[str, float],
    ]:
        mode = str(mode).strip().lower()

        if mode not in {"ocean", "block"}:
            raise ValueError(
                "mode must be 'ocean' or 'block'."
            )

        lat = (
            None
            if latitude is None
            else self._lat(latitude)
        )

        lon = (
            None
            if longitude is None
            else self._lon(longitude)
        )

        normalized_bbox = (
            None
            if bbox is None
            else self._validate_bbox(bbox)
        )

        identification = None
        selected: str | None = None

        if lat is not None or lon is not None:
            if lat is None or lon is None:
                raise ValueError(
                    "latitude and longitude must be supplied together."
                )

            from .ocean_regions import OceanRegionEngine

            identification = OceanRegionEngine().identify_dict(
                latitude=lat,
                longitude=lon,
            )

            if not identification.get("available"):
                raise LookupError(
                    "The coordinate is not identified as an ocean "
                    "by the real RECCAP2 mask."
                )

            detected = identification.get("ocean") or {}
            selected = detected.get("name")

            if not selected:
                raise LookupError(
                    "The coordinate did not resolve to a supported ocean."
                )

        elif ocean:
            selected, _ = self.geometry_engine.normalize_ocean_name(
                ocean
            )

        elif normalized_bbox is not None:
            center_lat = (
                normalized_bbox["latitude_min"]
                + normalized_bbox["latitude_max"]
            ) / 2.0

            center_lon = (
                normalized_bbox["longitude_min"]
                + normalized_bbox["longitude_max"]
            ) / 2.0

            from .ocean_regions import OceanRegionEngine

            identification = OceanRegionEngine().identify_dict(
                latitude=center_lat,
                longitude=center_lon,
            )

            if not identification.get("available"):
                raise LookupError(
                    "The requested bounding box is not identified "
                    "as a supported ocean by the real RECCAP2 mask."
                )

            selected = (
                identification.get("ocean") or {}
            ).get("name")

            if not selected:
                raise LookupError(
                    "The requested bounding box did not resolve "
                    "to a supported ocean."
                )

        else:
            raise ValueError(
                "Provide ocean, latitude and longitude, or bbox."
            )

        boundary = self.geometry_engine.boundary(selected)

        if (
            not boundary.available
            or boundary.geometry is None
        ):
            raise LookupError(
                f"No real ocean boundary is available for {selected}."
            )

        if normalized_bbox is None:
            if mode == "block":
                if lat is None or lon is None:
                    raise ValueError(
                        "Block mode requires latitude and longitude."
                    )

                normalized_bbox = self._radius_bbox(
                    latitude=lat,
                    longitude=lon,
                    radius_km=radius_km,
                )
            else:
                normalized_bbox = self._geometry_bbox(boundary)

        selection = {
            "mode": mode,
            "ocean": selected,
            "coordinate": (
                None
                if lat is None or lon is None
                else {
                    "latitude": lat,
                    "longitude": lon,
                    "coordinate_reference_system": "EPSG:4326",
                }
            ),
            "radius_km": (
                float(radius_km)
                if mode == "block"
                else None
            ),
            "identification": identification,
            "boundary": deepcopy(boundary.geometry),
            "bounding_box": normalized_bbox,
        }

        return selected, selection, normalized_bbox

    @staticmethod
    def _derive_levels(
        u: dict[str, Any],
        v: dict[str, Any],
        direction: bool,
    ) -> list[dict[str, Any]]:
        u_levels = u.get("levels", [])
        v_levels = v.get("levels", [])

        if len(u_levels) != len(v_levels):
            raise RuntimeError(
                "UVEL and VVEL returned different depth counts."
            )

        result: list[dict[str, Any]] = []

        for u_level, v_level in zip(u_levels, v_levels):
            if (
                u_level.get("latitudes")
                != v_level.get("latitudes")
                or u_level.get("longitudes")
                != v_level.get("longitudes")
            ):
                raise RuntimeError(
                    "UVEL and VVEL returned different source grids."
                )

            values: list[list[float | None]] = []
            missing_mask: list[list[bool]] = []
            valid_count = 0

            for (
                u_row,
                v_row,
                water_row,
                u_missing_row,
                v_missing_row,
            ) in zip(
                u_level["values"],
                v_level["values"],
                u_level["water_mask"],
                u_level["missing_mask"],
                v_level["missing_mask"],
            ):
                output_row: list[float | None] = []
                missing_row: list[bool] = []

                for (
                    u_value,
                    v_value,
                    water,
                    u_missing,
                    v_missing,
                ) in zip(
                    u_row,
                    v_row,
                    water_row,
                    u_missing_row,
                    v_missing_row,
                ):
                    valid = (
                        bool(water)
                        and not u_missing
                        and not v_missing
                        and u_value is not None
                        and v_value is not None
                    )

                    if not valid:
                        output_row.append(None)
                        missing_row.append(True)
                        continue

                    u_numeric = float(u_value)
                    v_numeric = float(v_value)

                    if direction:
                        value = math.degrees(
                            math.atan2(
                                v_numeric,
                                u_numeric,
                            )
                        )

                        if value < 0:
                            value += 360.0
                    else:
                        value = math.hypot(
                            u_numeric,
                            v_numeric,
                        )

                    output_row.append(float(value))
                    missing_row.append(False)
                    valid_count += 1

                values.append(output_row)
                missing_mask.append(missing_row)

            result.append(
                {
                    "requested_depth_m": u_level.get(
                        "requested_depth_m"
                    ),
                    "actual_depth_m": u_level.get(
                        "actual_depth_m"
                    ),
                    "units": (
                        "degree"
                        if direction
                        else "m/s"
                    ),
                    "latitudes": deepcopy(
                        u_level.get("latitudes", [])
                    ),
                    "longitudes": deepcopy(
                        u_level.get("longitudes", [])
                    ),
                    "values": values,
                    "missing_mask": missing_mask,
                    "water_mask": deepcopy(
                        u_level.get("water_mask", [])
                    ),
                    "valid_value_count": valid_count,
                    "actual_time_utc": u_level.get(
                        "actual_time_utc"
                    ),
                    "source": {
                        "provider": "INCOIS",
                        "dataset": "RSMC HYCOM",
                        "fields": [
                            "UVEL",
                            "VVEL",
                        ],
                    },
                }
            )

        return result

    async def build_data(
        self,
        *,
        mode: str,
        ocean: str | None,
        latitude: float | None,
        longitude: float | None,
        radius_km: float,
        time_utc: str,
        variable: str,
        depths_m: Sequence[float] | None,
        bbox: dict[str, float] | None = None,
    ) -> dict[str, Any]:
        canonical = normalize_variable_name(variable)
        definition = get_variable_definition(canonical)

        selected, selection, normalized_bbox = self._select(
            mode=mode,
            ocean=ocean,
            latitude=latitude,
            longitude=longitude,
            radius_km=radius_km,
            bbox=bbox,
        )

        depth_values = self._depths(depths_m)

        # Bathymetry is routed before checking the catalog's connected flag.
        # This allows the dedicated bathymetry engine to report its own
        # provider status instead of being blocked prematurely.
        if canonical == "bathymetry":
            payload = self.bathymetry_engine.build_surface(
                ocean=selected,
                latitude_min=normalized_bbox["latitude_min"],
                latitude_max=normalized_bbox["latitude_max"],
                longitude_min=normalized_bbox["longitude_min"],
                longitude_max=normalized_bbox["longitude_max"],
            )

            return {
                "available": True,
                "selection": selection,
                "variable": definition,
                "data_kind": "bathymetry_surface",
                "data": payload,
                "scientific_rules": {
                    "synthetic_data": False,
                    "interpolation": False,
                },
            }

        # External variables are routed before the connected flag check.
        # The external engine remains responsible for confirming whether
        # the requested real provider is operational.
        if canonical in self.EXTERNAL_SURFACE_VARIABLES:
            payload = await self.external_engine.build_data(
                variable_id=canonical,
                latitude_min=normalized_bbox["latitude_min"],
                latitude_max=normalized_bbox["latitude_max"],
                longitude_min=normalized_bbox["longitude_min"],
                longitude_max=normalized_bbox["longitude_max"],
                time_utc=time_utc,
            )

            return {
                "available": True,
                "selection": selection,
                "variable": definition,
                "data_kind": "external_surface_grid",
                "data": payload,
                "scientific_rules": {
                    "synthetic_data": False,
                    "interpolation": False,
                    "real_external_provider": True,
                },
            }

        # Only variables that require a verified HYCOM or derived adapter
        # are blocked by the catalog connection flag.
        if not definition.get("connected"):
            raise NotImplementedError(
                f"Variable '{canonical}' is cataloged but has no "
                "connected real-data provider yet."
            )

        if canonical in self.DIRECT_HYCOM:
            payload = self.volume_engine.build_volume(
                ocean=selected,
                latitude_min=normalized_bbox["latitude_min"],
                latitude_max=normalized_bbox["latitude_max"],
                longitude_min=normalized_bbox["longitude_min"],
                longitude_max=normalized_bbox["longitude_max"],
                time_utc=time_utc,
                variable=self.DIRECT_HYCOM[canonical],
                depths_m=depth_values,
            )

            return {
                "available": True,
                "selection": selection,
                "variable": definition,
                "data_kind": "multi_depth_volume",
                "data": payload,
                "scientific_rules": {
                    "synthetic_data": False,
                    "interpolation": False,
                },
            }

        if canonical in self.DERIVED:
            u = self.volume_engine.build_volume(
                ocean=selected,
                latitude_min=normalized_bbox["latitude_min"],
                latitude_max=normalized_bbox["latitude_max"],
                longitude_min=normalized_bbox["longitude_min"],
                longitude_max=normalized_bbox["longitude_max"],
                time_utc=time_utc,
                variable="UVEL",
                depths_m=depth_values,
            )

            v = self.volume_engine.build_volume(
                ocean=selected,
                latitude_min=normalized_bbox["latitude_min"],
                latitude_max=normalized_bbox["latitude_max"],
                longitude_min=normalized_bbox["longitude_min"],
                longitude_max=normalized_bbox["longitude_max"],
                time_utc=time_utc,
                variable="VVEL",
                depths_m=depth_values,
            )

            direction = canonical == "current_direction"

            payload = deepcopy(u)

            payload["variable"] = {
                "name": definition["name"],
                "output_name": definition["short_name"],
                "units": definition["unit"],
                "dimensions": "depth,latitude,longitude",
                "depth_dependent": True,
            }

            payload["request"]["variable"] = canonical
            payload["levels"] = self._derive_levels(
                u,
                v,
                direction,
            )

            payload["source"] = {
                "provider": "INCOIS",
                "dataset": "RSMC HYCOM",
                "fields": [
                    "UVEL",
                    "VVEL",
                ],
                "derivation": definition["source"].get(
                    "formula"
                ),
            }

            return {
                "available": True,
                "selection": selection,
                "variable": definition,
                "data_kind": "derived_multi_depth_volume",
                "data": payload,
                "scientific_rules": {
                    "synthetic_data": False,
                    "interpolation": False,
                    "derived_from_real_source_fields": True,
                },
            }

        raise NotImplementedError(
            f"Variable '{canonical}' does not have a connected "
            "real-data router yet."
        )


__all__ = [
    "OceanDataEngine",
    "DEFAULT_RADIUS_KM",
    "MAX_RADIUS_KM",
]