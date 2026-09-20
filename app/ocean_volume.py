from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Sequence

import numpy as np

from .ocean_geometry import OceanGeometryEngine
from .ocean_slice import OceanSliceEngine, VARIABLES
from .ocean_variables import normalize_variable_name


class OceanVolumeEngine:
    """
    Assemble a real multi-depth ocean volume from existing scientific source
    slices without interpolating source values.

    Scientific rules:

        * Real INCOIS/HYCOM source values only.
        * No synthetic values.
        * No interpolation.
        * Exact source-time enforcement is inherited from OceanSliceEngine.
        * Depth-dependent variables use the nearest available real HYCOM depth.
        * Surface-only variables such as SSH are supported.
        * Water/land masking uses the selected real ocean geometry.
        * Large grids are reduced using existing source-grid indices only.
        * Current speed and current direction are calculated only from real
          UVEL and VVEL source values.
    """

    DEFAULT_DEPTHS_M: tuple[float, ...] = (
        0.0,
        10.0,
        50.0,
        100.0,
        250.0,
        500.0,
    )

    MAX_DEPTH_LEVELS = 24
    MAX_GRID_POINTS = 1_000_000

    def __init__(
        self,
        slice_engine: OceanSliceEngine | None = None,
        geometry_engine: OceanGeometryEngine | None = None,
    ) -> None:
        self.slice_engine = slice_engine or OceanSliceEngine()
        self.geometry_engine = geometry_engine or OceanGeometryEngine()

    # =========================================================================
    # NORMALIZE DEPTHS
    # =========================================================================

    @staticmethod
    def _normalize_depths(
        depths_m: Sequence[float] | None,
    ) -> list[float]:
        if depths_m is None:
            return list(OceanVolumeEngine.DEFAULT_DEPTHS_M)

        normalized = sorted(
            {
                round(float(depth), 6)
                for depth in depths_m
            }
        )

        if not normalized:
            raise ValueError(
                "depths_m must contain at least one depth."
            )

        if len(normalized) > OceanVolumeEngine.MAX_DEPTH_LEVELS:
            raise ValueError(
                f"At most {OceanVolumeEngine.MAX_DEPTH_LEVELS} "
                "depth levels may be requested."
            )

        if normalized[0] < 0.0:
            raise ValueError(
                "depths_m cannot contain negative values."
            )

        return normalized

    # =========================================================================
    # NORMALIZE BBOX
    # =========================================================================

    @staticmethod
    def _normalize_bbox(
        latitude_min: float,
        latitude_max: float,
        longitude_min: float,
        longitude_max: float,
    ) -> tuple[float, float, float, float]:
        latitude_min = float(latitude_min)
        latitude_max = float(latitude_max)
        longitude_min = float(longitude_min)
        longitude_max = float(longitude_max)

        if not -90.0 <= latitude_min <= 90.0:
            raise ValueError(
                "latitude_min must be between -90 and 90."
            )

        if not -90.0 <= latitude_max <= 90.0:
            raise ValueError(
                "latitude_max must be between -90 and 90."
            )

        if latitude_min > latitude_max:
            raise ValueError(
                "latitude_min cannot be greater than latitude_max."
            )

        if not -180.0 <= longitude_min <= 180.0:
            raise ValueError(
                "longitude_min must be between -180 and 180."
            )

        if not -180.0 <= longitude_max <= 180.0:
            raise ValueError(
                "longitude_max must be between -180 and 180."
            )

        if longitude_min > longitude_max:
            raise ValueError(
                "longitude_min cannot be greater than longitude_max. "
                "Use an antimeridian-safe bbox split at the API layer."
            )

        return (
            latitude_min,
            latitude_max,
            longitude_min,
            longitude_max,
        )

    # =========================================================================
    # JSON CONVERSION HELPERS
    # =========================================================================

    @staticmethod
    def _finite_grid(
        values: Any,
    ) -> list[list[float | None]]:
        array = np.asarray(
            values,
            dtype=np.float64,
        )

        if array.ndim != 2:
            raise RuntimeError(
                "Expected a two-dimensional grid for JSON conversion."
            )

        result: list[list[float | None]] = []

        for row in array:
            result.append(
                [
                    float(value)
                    if np.isfinite(value)
                    else None
                    for value in row
                ]
            )

        return result

    @staticmethod
    def _boolean_grid(
        values: Any,
    ) -> list[list[bool]]:
        array = np.asarray(
            values,
            dtype=bool,
        )

        if array.ndim != 2:
            raise RuntimeError(
                "Expected a two-dimensional boolean grid."
            )

        return [
            [
                bool(value)
                for value in row
            ]
            for row in array
        ]

    # =========================================================================
    # WATER MASK
    # =========================================================================

    @staticmethod
    def _water_mask(
        latitudes: Sequence[float],
        longitudes: Sequence[float],
        geometry: dict[str, Any],
    ) -> np.ndarray:
        """
        Mark source-grid cell centers inside the selected real ocean geometry.

        This classifies existing source-grid cells only. It does not interpolate
        or create scientific values.
        """
        try:
            from shapely.geometry import Point, shape
        except ImportError as exc:
            raise RuntimeError(
                "shapely is required for the ocean water mask."
            ) from exc

        source_geometry = shape(geometry)

        mask = np.zeros(
            (
                len(latitudes),
                len(longitudes),
            ),
            dtype=bool,
        )

        for row_index, latitude in enumerate(latitudes):
            for column_index, longitude in enumerate(longitudes):
                mask[row_index, column_index] = bool(
                    source_geometry.covers(
                        Point(
                            float(longitude),
                            float(latitude),
                        )
                    )
                )

        return mask

    # =========================================================================
    # SOURCE GRID REDUCTION
    # =========================================================================

    @staticmethod
    def _reduction_indices(
        latitude_count: int,
        longitude_count: int,
        max_points: int,
    ) -> tuple[list[int], list[int]]:
        """
        Select existing source-grid indices only.

        No interpolation is performed.
        """
        if latitude_count <= 0 or longitude_count <= 0:
            raise ValueError(
                "Source-grid dimensions must be positive."
            )

        if max_points <= 0:
            raise ValueError(
                "max_points must be greater than zero."
            )

        point_count = latitude_count * longitude_count

        if point_count <= max_points:
            return (
                list(range(latitude_count)),
                list(range(longitude_count)),
            )

        latitude_step = 1
        longitude_step = 1

        while True:
            current_lat_count = int(
                np.ceil(latitude_count / latitude_step)
            )
            current_lon_count = int(
                np.ceil(longitude_count / longitude_step)
            )

            if current_lat_count * current_lon_count <= max_points:
                break

            next_lat_count = int(
                np.ceil(latitude_count / (latitude_step + 1))
            )
            next_lon_count = int(
                np.ceil(longitude_count / (longitude_step + 1))
            )

            latitude_reduction = (
                current_lat_count - next_lat_count
            )
            longitude_reduction = (
                current_lon_count - next_lon_count
            )

            latitude_ratio = (
                latitude_reduction
                / max(current_lat_count, 1)
            )

            longitude_ratio = (
                longitude_reduction
                / max(current_lon_count, 1)
            )

            if latitude_ratio >= longitude_ratio:
                latitude_step += 1
            else:
                longitude_step += 1

        latitude_indices = list(
            range(
                0,
                latitude_count,
                latitude_step,
            )
        )

        longitude_indices = list(
            range(
                0,
                longitude_count,
                longitude_step,
            )
        )

        if not latitude_indices:
            latitude_indices = [0]

        if not longitude_indices:
            longitude_indices = [0]

        if latitude_indices[-1] != latitude_count - 1:
            latitude_indices.append(latitude_count - 1)

        if longitude_indices[-1] != longitude_count - 1:
            longitude_indices.append(longitude_count - 1)

        while (
            len(latitude_indices)
            * len(longitude_indices)
            > max_points
        ):
            if len(latitude_indices) >= len(longitude_indices):
                if len(latitude_indices) > 2:
                    latitude_indices = latitude_indices[::2]
                else:
                    longitude_indices = longitude_indices[::2]
            else:
                if len(longitude_indices) > 2:
                    longitude_indices = longitude_indices[::2]
                else:
                    latitude_indices = latitude_indices[::2]

        return latitude_indices, longitude_indices

    # =========================================================================
    # SOURCE GRID VALIDATION
    # =========================================================================

    @staticmethod
    def _validate_grid_arrays(
        values: np.ndarray,
        missing: np.ndarray,
        latitude_count: int,
        longitude_count: int,
        depth: float,
        variable_name: str,
    ) -> None:
        expected_shape = (
            latitude_count,
            longitude_count,
        )

        if values.shape != expected_shape:
            raise RuntimeError(
                f"Invalid source grid shape for variable "
                f"'{variable_name}' at depth {depth} m. "
                f"Expected {expected_shape}, received {values.shape}."
            )

        if missing.shape != expected_shape:
            raise RuntimeError(
                f"Invalid missing-mask shape for variable "
                f"'{variable_name}' at depth {depth} m. "
                f"Expected {expected_shape}, received {missing.shape}."
            )

    # =========================================================================
    # BUILD VOLUME
    # =========================================================================

    def build_volume(
        self,
        *,
        ocean: str,
        latitude_min: float,
        latitude_max: float,
        longitude_min: float,
        longitude_max: float,
        time_utc: str,
        variable: str = "TEMP",
        depths_m: Sequence[float] | None = None,
    ) -> dict[str, Any]:
        """
        Build a selected-ocean multi-depth volume from real HYCOM slices.

        The variable is normalized through OceanSliceEngine so all supported
        aliases work:

            TEMP
            temperature
            SST
            SALN
            salinity
            UVEL
            VVEL
            SSH
            current_speed
            current_direction
        """
        (
            latitude_min,
            latitude_max,
            longitude_min,
            longitude_max,
        ) = self._normalize_bbox(
            latitude_min=latitude_min,
            latitude_max=latitude_max,
            longitude_min=longitude_min,
            longitude_max=longitude_max,
        )

        normalized_depths = self._normalize_depths(depths_m)

        # Keep normalization independent of the concrete slice-engine
        # implementation, including compatible injected engines.
        variable_code = normalize_variable_name(variable)

        if variable_code not in VARIABLES:
            raise ValueError(
                "Unsupported ocean variable. Supported variables are: "
                + ", ".join(sorted(VARIABLES.keys()))
            )

        variable_definition = VARIABLES[variable_code]

        boundary = self.geometry_engine.boundary(ocean)

        if not boundary.available or boundary.geometry is None:
            raise LookupError(
                f"No real ocean boundary geometry is available for "
                f"{boundary.ocean_name}."
            )

        levels: list[dict[str, Any]] = []

        common_latitudes: list[float] | None = None
        common_longitudes: list[float] | None = None

        total_points: int | None = None
        original_point_count: int | None = None
        source_grid_reduced = False

        # The water mask depends only on the geographic grid and selected
        # ocean geometry, not on depth. Reuse it for every depth level.
        cached_water_mask: np.ndarray | None = None

        for requested_depth in normalized_depths:
            slice_result = self.slice_engine.query_dict(
                latitude_min=latitude_min,
                latitude_max=latitude_max,
                longitude_min=longitude_min,
                longitude_max=longitude_max,
                depth_m=requested_depth,
                time_utc=time_utc,
                variable=variable_code,
            )

            grid = slice_result.get(
                "grid",
                {},
            )

            source_latitudes = [
                float(value)
                for value in grid.get(
                    "latitudes",
                    [],
                )
            ]

            source_longitudes = [
                float(value)
                for value in grid.get(
                    "longitudes",
                    [],
                )
            ]

            if not source_latitudes or not source_longitudes:
                raise LookupError(
                    f"No source grid was returned for depth "
                    f"{requested_depth} m."
                )

            lat_indices = [
                index
                for index, value in enumerate(source_latitudes)
                if latitude_min <= value <= latitude_max
            ]

            lon_indices = [
                index
                for index, value in enumerate(source_longitudes)
                if longitude_min <= value <= longitude_max
            ]

            if not lat_indices or not lon_indices:
                raise LookupError(
                    "No source-grid cells fall inside the requested "
                    "bounding box."
                )

            latitudes = [
                source_latitudes[index]
                for index in lat_indices
            ]

            longitudes = [
                source_longitudes[index]
                for index in lon_indices
            ]

            values = np.asarray(
                grid.get(
                    "values",
                    [],
                ),
                dtype=np.float64,
            )

            missing = np.asarray(
                grid.get(
                    "missing_mask",
                    [],
                ),
                dtype=bool,
            )

            if values.ndim != 2:
                raise RuntimeError(
                    f"Source values for depth {requested_depth} m "
                    "must be a two-dimensional latitude/longitude grid."
                )

            if missing.ndim != 2:
                raise RuntimeError(
                    f"Missing mask for depth {requested_depth} m "
                    "must be a two-dimensional latitude/longitude grid."
                )

            values = values[
                np.ix_(
                    lat_indices,
                    lon_indices,
                )
            ]

            missing = missing[
                np.ix_(
                    lat_indices,
                    lon_indices,
                )
            ]

            point_count_before_reduction = (
                len(latitudes)
                * len(longitudes)
            )

            if original_point_count is None:
                original_point_count = (
                    point_count_before_reduction
                )

            if point_count_before_reduction > self.MAX_GRID_POINTS:
                (
                    reduced_lat_indices,
                    reduced_lon_indices,
                ) = self._reduction_indices(
                    latitude_count=len(latitudes),
                    longitude_count=len(longitudes),
                    max_points=self.MAX_GRID_POINTS,
                )

                latitudes = [
                    latitudes[index]
                    for index in reduced_lat_indices
                ]

                longitudes = [
                    longitudes[index]
                    for index in reduced_lon_indices
                ]

                values = values[
                    np.ix_(
                        reduced_lat_indices,
                        reduced_lon_indices,
                    )
                ]

                missing = missing[
                    np.ix_(
                        reduced_lat_indices,
                        reduced_lon_indices,
                    )
                ]

                source_grid_reduced = True

            point_count = (
                len(latitudes)
                * len(longitudes)
            )

            if point_count > self.MAX_GRID_POINTS:
                raise RuntimeError(
                    "Source-grid reduction failed to satisfy the "
                    f"maximum limit of {self.MAX_GRID_POINTS} cells."
                )

            self._validate_grid_arrays(
                values=values,
                missing=missing,
                latitude_count=len(latitudes),
                longitude_count=len(longitudes),
                depth=requested_depth,
                variable_name=variable_code,
            )

            if (
                common_latitudes is None
                or common_longitudes is None
            ):
                common_latitudes = list(latitudes)
                common_longitudes = list(longitudes)

                cached_water_mask = self._water_mask(
                    latitudes=common_latitudes,
                    longitudes=common_longitudes,
                    geometry=boundary.geometry,
                )
            else:
                if (
                    common_latitudes != latitudes
                    or common_longitudes != longitudes
                ):
                    raise RuntimeError(
                        "HYCOM depth slices returned different source grids. "
                        "Phase 2 requires a common geographic grid for the "
                        "3D volume. No regridding was performed."
                    )

            if cached_water_mask is None:
                raise RuntimeError(
                    "Water mask was not initialized."
                )

            water_mask = cached_water_mask

            if values.shape != water_mask.shape:
                raise RuntimeError(
                    "HYCOM source-grid shape does not match the "
                    "generated ocean water mask."
                )

            values_for_output = values.copy()
            values_for_output[~water_mask] = np.nan

            missing_for_output = missing.copy()
            missing_for_output[~water_mask] = True

            valid_value_count = int(
                np.count_nonzero(
                    water_mask
                    & ~missing_for_output
                    & np.isfinite(values_for_output)
                )
            )

            if valid_value_count == 0:
                raise LookupError(
                    f"No valid real {variable_code} source values were "
                    f"returned inside the selected "
                    f"{boundary.ocean_name} boundary at depth "
                    f"{requested_depth} m."
                )

            total_points = (
                point_count
                if total_points is None
                else max(
                    total_points,
                    point_count,
                )
            )

            actual_metadata = slice_result.get(
                "actual",
                {},
            )

            variable_metadata = slice_result.get(
                "variable",
                {},
            )

            source_metadata = slice_result.get(
                "source",
                {},
            )

            levels.append(
                {
                    "requested_depth_m": float(
                        requested_depth
                    ),
                    "actual_depth_m": actual_metadata.get(
                        "depth_m"
                    ),
                    "units": variable_metadata.get(
                        "units",
                        variable_definition.units,
                    ),
                    "latitudes": list(latitudes),
                    "longitudes": list(longitudes),
                    "values": self._finite_grid(
                        values_for_output
                    ),
                    "missing_mask": self._boolean_grid(
                        missing_for_output
                    ),
                    "water_mask": self._boolean_grid(
                        water_mask
                    ),
                    "valid_value_count": valid_value_count,
                    "source": source_metadata.get(
                        "provider",
                        "INCOIS",
                    ),
                    "datasets": list(
                        source_metadata.get(
                            "datasets",
                            [],
                        )
                    ),
                    "source_urls": list(
                        source_metadata.get(
                            "source_urls",
                            [],
                        )
                    ),
                    "chunk_files": list(
                        source_metadata.get(
                            "chunk_files",
                            [],
                        )
                    ),
                    "provenance_paths": list(
                        source_metadata.get(
                            "provenance_paths",
                            [],
                        )
                    ),
                    "provenance": slice_result.get(
                        "provenance",
                        {},
                    ),
                    "actual_time_utc": actual_metadata.get(
                        "time_utc",
                        time_utc,
                    ),
                }
            )

        if common_latitudes is None or common_longitudes is None:
            raise LookupError(
                "No common source grid was assembled."
            )

        all_datasets = sorted(
            {
                dataset
                for level in levels
                for dataset in level.get(
                    "datasets",
                    [],
                )
            }
        )

        all_source_urls = sorted(
            {
                source_url
                for level in levels
                for source_url in level.get(
                    "source_urls",
                    [],
                )
            }
        )

        all_chunk_files = sorted(
            {
                chunk_file
                for level in levels
                for chunk_file in level.get(
                    "chunk_files",
                    [],
                )
            }
        )

        all_provenance_paths = sorted(
            {
                provenance_path
                for level in levels
                for provenance_path in level.get(
                    "provenance_paths",
                    [],
                )
                if provenance_path
            }
        )

        generated_at_utc = (
            datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace(
                "+00:00",
                "Z",
            )
        )

        return {
            "available": True,
            "ocean": {
                "name": boundary.ocean_name,
                "source_region": boundary.source_region,
                "boundary": boundary.geometry,
                "bounding_box": boundary.bounding_box,
            },
            "request": {
                "latitude_min": latitude_min,
                "latitude_max": latitude_max,
                "longitude_min": longitude_min,
                "longitude_max": longitude_max,
                "time_utc": time_utc,
                "variable": variable_code,
                "depths_m": normalized_depths,
            },
            "variable": {
                # Preserve the caller's source/canonical spelling in the
                # payload while the normalized identifier remains available
                # under request.variable.
                "name": str(variable),
                "output_name": variable_definition.output_name,
                "units": variable_definition.units,
                "dimensions": variable_definition.dimensions,
                "depth_dependent": variable_definition.depth_dependent,
                "source_fields": list(
                    variable_definition.source_fields
                ),
                "derived_kind": variable_definition.derived_kind,
            },
            "grid": {
                "latitude_count": len(
                    common_latitudes
                ),
                "longitude_count": len(
                    common_longitudes
                ),
                "point_count": total_points or 0,
                "original_point_count": (
                    original_point_count or 0
                ),
                "source_grid_reduced": source_grid_reduced,
                "latitudes": common_latitudes,
                "longitudes": common_longitudes,
            },
            "levels": levels,
            "scientific_rules": {
                "synthetic_data": False,
                "interpolation": False,
                "source_grid_values_only": True,
                "source_grid_reduction": (
                    "regular existing source-grid indices only"
                    if source_grid_reduced
                    else "none"
                ),
                "water_mask_from_real_ocean_geometry": True,
                "depth_selection": (
                    "nearest available real HYCOM depth level"
                    if variable_definition.depth_dependent
                    else "surface-only variable"
                ),
                "current_direction_convention": (
                    "mathematical direction toward which the current "
                    "vector points, measured clockwise from east, "
                    "normalized to 0-360 degrees"
                    if variable_definition.derived_kind == "direction"
                    else None
                ),
            },
            "source": {
                "provider": "INCOIS",
                "dataset": "RSMC HYCOM",
                "datasets": all_datasets,
                "source_urls": all_source_urls,
                "chunk_files": all_chunk_files,
                "provenance_paths": all_provenance_paths,
                "description": (
                    "Real HYCOM source-grid depth slices assembled "
                    "into a multi-depth volume."
                ),
            },
            "generated_at_utc": generated_at_utc,
        }
