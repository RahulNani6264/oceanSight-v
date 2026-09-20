from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from .ocean_regions import OCEAN_DEFINITIONS


PROJECT_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_REGION_FILE = (
    PROJECT_ROOT
    / "data"
    / "ocean_regions"
    / "RECCAP2_region_masks_all_v20221025.nc"
)


@dataclass(frozen=True)
class OceanBoundary:
    """A real ocean boundary derived from the RECCAP2 source mask."""

    available: bool
    ocean_name: str | None
    source_region: str | None
    geometry: dict[str, Any] | None
    bounding_box: dict[str, float] | None
    polygon_count: int
    source_file: str
    source: str
    latitude_resolution_degrees: float | None
    longitude_resolution_degrees: float | None
    synthetic_data: bool = False
    interpolation: bool = False


class OceanGeometryEngine:
    """
    Build real ocean-basin geometry from the RECCAP2 regional mask.

    The source grid is a 1-degree mask. The returned geometry is therefore
    the exact boundary of the source-mask cells, not a guessed coastline and
    not a smoothed or interpolated polygon.

    Longitude coordinates are normalized to [-180, 180]. Basins that cross
    the antimeridian remain valid MultiPolygon geometry with the appropriate
    split at +/-180 degrees.
    """

    def __init__(
        self,
        region_file: str | Path | None = None,
    ) -> None:
        self.region_file = Path(
            region_file
            if region_file is not None
            else DEFAULT_REGION_FILE
        )

        if not self.region_file.exists():
            raise FileNotFoundError(
                "Real ocean-region dataset was not found: "
                f"{self.region_file}"
            )

        self._loaded = False
        self._latitudes: np.ndarray | None = None
        self._longitudes: np.ndarray | None = None
        self._masks: dict[str, np.ndarray] = {}
        self._boundaries: dict[str, OceanBoundary] = {}

    # =========================================================================
    # SOURCE LOADING
    # =========================================================================

    def _load_source(self) -> None:
        if self._loaded:
            return

        try:
            from netCDF4 import Dataset
        except ImportError as exc:
            raise RuntimeError(
                "netCDF4 is required for real ocean-boundary geometry. "
                "Install the dependencies from requirements.txt."
            ) from exc

        with Dataset(self.region_file, mode="r") as dataset:
            latitude_name = self._find_coordinate_name(
                dataset.variables,
                ("lat", "latitude", "LAT", "Latitude"),
            )
            longitude_name = self._find_coordinate_name(
                dataset.variables,
                ("lon", "longitude", "LON", "Longitude"),
            )

            latitudes = np.asarray(
                dataset.variables[latitude_name][:],
                dtype=np.float64,
            ).reshape(-1)
            longitudes = np.asarray(
                dataset.variables[longitude_name][:],
                dtype=np.float64,
            ).reshape(-1)

            if latitudes.size < 2 or longitudes.size < 2:
                raise RuntimeError(
                    "The ocean-region source must contain at least two "
                    "latitude and longitude coordinates."
                )

            for _, source_region in OCEAN_DEFINITIONS.items():
                if source_region not in dataset.variables:
                    raise RuntimeError(
                        "The ocean-region source is missing the real mask "
                        f"variable '{source_region}'."
                    )

                mask = np.asarray(
                    dataset.variables[source_region][:],
                    dtype=np.float64,
                )

                if mask.shape != (
                    latitudes.size,
                    longitudes.size,
                ):
                    raise RuntimeError(
                        "Ocean-region mask shape does not match the source "
                        f"grid for '{source_region}': {mask.shape} != "
                        f"({latitudes.size}, {longitudes.size})."
                    )

                self._masks[source_region] = (
                    np.isfinite(mask)
                    & (mask > 0)
                )

        self._latitudes = latitudes
        self._longitudes = longitudes
        self._loaded = True

    # =========================================================================
    # DATASET HELPERS
    # =========================================================================

    @staticmethod
    def _find_coordinate_name(
        variables: Any,
        candidates: Iterable[str],
    ) -> str:
        available = set(
            variables.keys()
        )

        for candidate in candidates:
            if candidate in available:
                return candidate

        raise RuntimeError(
            "Could not identify the source latitude/longitude variable. "
            f"Available variables: {sorted(available)}"
        )

    @staticmethod
    def _axis_resolution(
        values: np.ndarray,
    ) -> float:
        differences = np.diff(values)

        if differences.size == 0:
            raise ValueError(
                "Coordinate axis must contain at least two values."
            )

        representative = float(
            np.median(
                np.abs(differences)
            )
        )

        if not np.isfinite(representative) or representative <= 0:
            raise RuntimeError(
                "Coordinate axis has an invalid resolution."
            )

        return representative

    @staticmethod
    def _cell_bounds(
        values: np.ndarray,
    ) -> np.ndarray:
        resolution = OceanGeometryEngine._axis_resolution(
            values
        )

        bounds = np.empty(
            values.size + 1,
            dtype=np.float64,
        )

        bounds[1:-1] = (
            values[:-1]
            + values[1:]
        ) / 2.0

        bounds[0] = (
            values[0]
            - resolution / 2.0
        )

        bounds[-1] = (
            values[-1]
            + resolution / 2.0
        )

        return bounds

    @staticmethod
    def _normalize_longitudes(
        longitudes: np.ndarray,
    ) -> np.ndarray:
        return (
            (
                longitudes
                + 180.0
            )
            % 360.0
        ) - 180.0

    # =========================================================================
    # SHAPE BUILDING
    # =========================================================================

    @staticmethod
    def _horizontal_active_runs(
        row_mask: np.ndarray,
    ) -> list[tuple[int, int]]:
        """
        Compress a boolean source row into inclusive start / exclusive end
        column runs. This keeps the shapely union small without changing the
        source-mask geometry.
        """

        active = np.flatnonzero(
            row_mask
        )

        if active.size == 0:
            return []

        runs: list[tuple[int, int]] = []
        start = int(active[0])
        previous = start

        for index in active[1:]:
            current = int(index)

            if current != previous + 1:
                runs.append(
                    (
                        start,
                        previous + 1,
                    )
                )
                start = current

            previous = current

        runs.append(
            (
                start,
                previous + 1,
            )
        )

        return runs

    @classmethod
    def _build_geometry_from_arrays(
        cls,
        mask: np.ndarray,
        latitudes: np.ndarray,
        longitudes: np.ndarray,
    ) -> dict[str, Any]:
        """
        Convert active source-mask cells into an exact polygonal union.

        Shapely dissolves shared cell edges and preserves holes, producing a
        proper Polygon / MultiPolygon representation rather than a collection
        of disconnected grid squares.
        """

        try:
            from shapely.geometry import box, mapping  # type: ignore[reportMissingModuleSource]
            from shapely.ops import unary_union  # type: ignore[reportMissingModuleSource]
        except ImportError as exc:
            raise RuntimeError(
                "shapely is required for real ocean-boundary geometry. "
                "Install the dependencies from requirements.txt."
            ) from exc

        mask = np.asarray(
            mask,
            dtype=bool,
        )
        latitudes = np.asarray(
            latitudes,
            dtype=np.float64,
        ).reshape(-1)
        longitudes = np.asarray(
            longitudes,
            dtype=np.float64,
        ).reshape(-1)

        if mask.shape != (
            latitudes.size,
            longitudes.size,
        ):
            raise ValueError(
                "Mask shape must match latitude/longitude dimensions."
            )

        if not np.all(
            np.diff(latitudes) > 0
        ):
            order = np.argsort(latitudes)
            latitudes = latitudes[order]
            mask = mask[order, :]

        normalized_longitudes = cls._normalize_longitudes(
            longitudes
        )

        longitude_order = np.argsort(
            normalized_longitudes
        )

        normalized_longitudes = (
            normalized_longitudes[
                longitude_order
            ]
        )
        mask = mask[:, longitude_order]

        latitude_bounds = cls._cell_bounds(
            latitudes
        )

        longitude_bounds = cls._cell_bounds(
            normalized_longitudes
        )

        # The normalized longitude axis is intentionally split at the
        # antimeridian. This makes the result valid EPSG:4326 MultiPolygon
        # geometry while preserving the source mask exactly.
        source_cells = []

        for row_index in range(
            mask.shape[0]
        ):
            runs = cls._horizontal_active_runs(
                mask[row_index]
            )

            if not runs:
                continue

            min_latitude = float(
                latitude_bounds[row_index]
            )
            max_latitude = float(
                latitude_bounds[row_index + 1]
            )

            for start_column, end_column in runs:
                min_longitude = float(
                    longitude_bounds[
                        start_column
                    ]
                )
                max_longitude = float(
                    longitude_bounds[
                        end_column
                    ]
                )

                source_cells.append(
                    box(
                        min_longitude,
                        min_latitude,
                        max_longitude,
                        max_latitude,
                    )
                )

        if not source_cells:
            return {
                "type": "MultiPolygon",
                "coordinates": [],
                "polygon_count": 0,
                "ring_count": 0,
                "coordinate_reference_system": "EPSG:4326",
                "longitude_mode": "-180_to_180",
                "boundary_resolution_degrees": {
                    "latitude": cls._axis_resolution(
                        latitudes
                    ),
                    "longitude": cls._axis_resolution(
                        longitudes
                    ),
                },
            }

        dissolved = unary_union(
            source_cells
        )

        if dissolved.geom_type == "Polygon":
            polygons = [
                dissolved
            ]
        elif dissolved.geom_type == "MultiPolygon":
            polygons = list(
                dissolved.geoms
            )
        else:
            raise RuntimeError(
                "The source-mask union did not produce Polygon or "
                f"MultiPolygon geometry; got {dissolved.geom_type}."
            )

        geometry = mapping(
            dissolved
        )

        coordinates = geometry.get(
            "coordinates",
            [],
        )

        ring_count = sum(
            len(polygon.interiors) + 1
            for polygon in polygons
        )

        bounds = dissolved.bounds

        return {
            "type": geometry[
                "type"
            ],
            "coordinates": coordinates,
            "polygon_count": len(polygons),
            "ring_count": ring_count,
            "coordinate_reference_system": "EPSG:4326",
            "longitude_mode": "-180_to_180",
            "boundary_resolution_degrees": {
                "latitude": cls._axis_resolution(
                    latitudes
                ),
                "longitude": cls._axis_resolution(
                    longitudes
                ),
            },
            "bbox": [
                float(bounds[0]),
                float(bounds[1]),
                float(bounds[2]),
                float(bounds[3]),
            ],
        }

    # =========================================================================
    # PUBLIC HELPERS
    # =========================================================================

    @staticmethod
    def normalize_ocean_name(
        ocean: str,
    ) -> tuple[str, str]:
        normalized = (
            str(ocean)
            .strip()
            .lower()
        )

        for public_name, source_region in OCEAN_DEFINITIONS.items():
            aliases = {
                public_name.lower(),
                source_region.lower(),
                public_name.lower().replace(
                    " ocean",
                    "",
                ),
            }

            if normalized in aliases:
                return public_name, source_region

        raise ValueError(
            "Unsupported ocean. Supported oceans are: "
            + ", ".join(
                OCEAN_DEFINITIONS.keys()
            )
            + "."
        )

    # =========================================================================
    # PUBLIC BOUNDARY API
    # =========================================================================

    def boundary(
        self,
        ocean: str,
    ) -> OceanBoundary:
        public_name, source_region = (
            self.normalize_ocean_name(
                ocean
            )
        )

        if source_region in self._boundaries:
            return self._boundaries[
                source_region
            ]

        self._load_source()

        assert self._latitudes is not None
        assert self._longitudes is not None

        geometry = self._build_geometry_from_arrays(
            mask=self._masks[source_region],
            latitudes=self._latitudes,
            longitudes=self._longitudes,
        )

        raw_bbox = geometry.get(
            "bbox"
        )

        bounding_box = None
        if (
            isinstance(raw_bbox, list)
            and len(raw_bbox) == 4
        ):
            bounding_box = {
                "min_longitude": float(
                    raw_bbox[0]
                ),
                "min_latitude": float(
                    raw_bbox[1]
                ),
                "max_longitude": float(
                    raw_bbox[2]
                ),
                "max_latitude": float(
                    raw_bbox[3]
                ),
            }

        boundary_resolution = geometry.get(
            "boundary_resolution_degrees",
            {},
        )

        result = OceanBoundary(
            available=bool(
                geometry.get(
                    "polygon_count",
                    0,
                )
            ),
            ocean_name=public_name,
            source_region=source_region,
            geometry=geometry,
            bounding_box=bounding_box,
            polygon_count=int(
                geometry.get(
                    "polygon_count",
                    0,
                )
            ),
            source_file=str(
                self.region_file
            ),
            source=(
                "RECCAP2 Ocean regional masks; "
                "source-cell union boundary extraction"
            ),
            latitude_resolution_degrees=(
                float(
                    boundary_resolution.get(
                        "latitude"
                    )
                )
                if boundary_resolution.get(
                    "latitude"
                ) is not None
                else None
            ),
            longitude_resolution_degrees=(
                float(
                    boundary_resolution.get(
                        "longitude"
                    )
                )
                if boundary_resolution.get(
                    "longitude"
                ) is not None
                else None
            ),
        )

        self._boundaries[
            source_region
        ] = result

        return result

    def boundary_dict(
        self,
        ocean: str,
    ) -> dict[str, Any]:
        result = self.boundary(
            ocean
        )

        return {
            "available": result.available,
            "ocean": {
                "name": result.ocean_name,
                "source_region": result.source_region,
            },
            "geometry": result.geometry,
            "bounding_box": result.bounding_box,
            "grid": {
                "latitude_resolution_degrees": result.latitude_resolution_degrees,
                "longitude_resolution_degrees": result.longitude_resolution_degrees,
                "boundary_method": (
                    "source-mask cell union; "
                    "no interpolation; no smoothing"
                ),
            },
            "source": {
                "provider": "RECCAP2 Ocean",
                "dataset": "RECCAP2 regional ocean masks",
                "file": result.source_file,
                "description": result.source,
            },
            "scientific_rules": {
                "synthetic_data": result.synthetic_data,
                "interpolation": result.interpolation,
                "source_mask_geometry": True,
            },
        }
