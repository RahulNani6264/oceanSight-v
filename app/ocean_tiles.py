from __future__ import annotations

import json
import math
import struct
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import numpy as np

from .hycom_chunk_index import HycomChunkIndex
from .ocean_slice import OceanSliceEngine


@dataclass(frozen=True)
class OceanTileRequest:
    level: int
    x: int
    y: int
    variable: str
    time_utc: str
    depth_m: float


class OceanTileEngine:
    """
    Converts one geographic source slice into a compact binary tile.

    OceanSliceEngine remains the scientific source of truth.

    This class:
      - calculates one geographic tile bounding box
      - intersects the tile with available HYCOM coverage
      - queries only the intersecting geographic area
      - selects existing source-grid cells
      - converts values to Float32
      - returns compact binary data

    Scientific rules:
      - no synthetic values
      - no interpolation
      - source-grid values only
      - regular source-grid index downsampling only
    """

    TILE_SIZE = 256
    MAX_LEVEL = 6

    def __init__(
        self,
        slice_engine: OceanSliceEngine | None = None,
        chunk_index: HycomChunkIndex | None = None,
    ) -> None:
        self.slice_engine = (
            slice_engine
            or OceanSliceEngine()
        )

        self.chunk_index = (
            chunk_index
            or HycomChunkIndex()
        )

        self._coverage = self._calculate_coverage()

    # =========================================================================
    # COVERAGE
    # =========================================================================

    def _calculate_coverage(
        self,
    ) -> tuple[float, float, float, float]:
        """
        Calculate the actual geographic coverage from the indexed chunks.

        Returns:
            latitude_min,
            latitude_max,
            longitude_min,
            longitude_max
        """

        records = self.chunk_index.records

        if not records:
            raise RuntimeError(
                "No valid HYCOM chunk records are available."
            )

        latitude_min = min(
            record.latitude_min
            for record in records
        )

        latitude_max = max(
            record.latitude_max
            for record in records
        )

        longitude_min = min(
            record.longitude_min
            for record in records
        )

        longitude_max = max(
            record.longitude_max
            for record in records
        )

        return (
            float(latitude_min),
            float(latitude_max),
            float(longitude_min),
            float(longitude_max),
        )

    @property
    def coverage(
        self,
    ) -> dict[str, float]:
        latitude_min, latitude_max, longitude_min, longitude_max = (
            self._coverage
        )

        return {
            "latitude_min": latitude_min,
            "latitude_max": latitude_max,
            "longitude_min": longitude_min,
            "longitude_max": longitude_max,
        }

    @classmethod
    def _intersect_bbox(
        cls,
        tile_bbox: tuple[float, float, float, float],
        coverage: tuple[float, float, float, float],
    ) -> tuple[float, float, float, float] | None:
        """
        Intersect a tile bbox with the available source-data coverage.

        Returns None when the tile does not overlap the source dataset.
        """

        (
            tile_latitude_min,
            tile_latitude_max,
            tile_longitude_min,
            tile_longitude_max,
        ) = tile_bbox

        (
            coverage_latitude_min,
            coverage_latitude_max,
            coverage_longitude_min,
            coverage_longitude_max,
        ) = coverage

        latitude_min = max(
            tile_latitude_min,
            coverage_latitude_min,
        )

        latitude_max = min(
            tile_latitude_max,
            coverage_latitude_max,
        )

        longitude_min = max(
            tile_longitude_min,
            coverage_longitude_min,
        )

        longitude_max = min(
            tile_longitude_max,
            coverage_longitude_max,
        )

        if latitude_min >= latitude_max:
            return None

        if longitude_min >= longitude_max:
            return None

        return (
            latitude_min,
            latitude_max,
            longitude_min,
            longitude_max,
        )

    # =========================================================================
    # TILE GEOMETRY
    # =========================================================================

    @classmethod
    def tile_count_x(
        cls,
        level: int,
    ) -> int:
        return 2**level

    @classmethod
    def tile_count_y(
        cls,
        level: int,
    ) -> int:
        return max(
            1,
            2 ** max(level - 1, 0),
        )

    @classmethod
    def validate_tile_request(
        cls,
        level: int,
        x: int,
        y: int,
    ) -> tuple[int, int, int]:
        level = int(level)
        x = int(x)
        y = int(y)

        if level < 0 or level > cls.MAX_LEVEL:
            raise ValueError(
                f"level must be between 0 and {cls.MAX_LEVEL}."
            )

        max_x = cls.tile_count_x(level)
        max_y = cls.tile_count_y(level)

        if x < 0 or x >= max_x:
            raise ValueError(
                f"x must be between 0 and {max_x - 1} "
                f"for level {level}."
            )

        if y < 0 or y >= max_y:
            raise ValueError(
                f"y must be between 0 and {max_y - 1} "
                f"for level {level}."
            )

        return level, x, y

    @classmethod
    def tile_bbox(
        cls,
        level: int,
        x: int,
        y: int,
    ) -> tuple[float, float, float, float]:
        """
        Equirectangular global tiling.

        Returns:
            latitude_min,
            latitude_max,
            longitude_min,
            longitude_max
        """

        tile_x_count = cls.tile_count_x(level)
        tile_y_count = cls.tile_count_y(level)

        longitude_width = (
            360.0 / tile_x_count
        )

        latitude_height = (
            180.0 / tile_y_count
        )

        longitude_min = (
            -180.0
            + x * longitude_width
        )

        longitude_max = (
            longitude_min
            + longitude_width
        )

        latitude_min = (
            -90.0
            + y * latitude_height
        )

        latitude_max = (
            latitude_min
            + latitude_height
        )

        return (
            latitude_min,
            latitude_max,
            longitude_min,
            longitude_max,
        )

    # =========================================================================
    # GRID COMPACTION
    # =========================================================================

    @staticmethod
    def _select_indices(
        count: int,
        target_count: int,
    ) -> list[int]:
        if count <= 0:
            return []

        if count <= target_count:
            return list(
                range(count)
            )

        indices = np.linspace(
            0,
            count - 1,
            num=target_count,
            dtype=np.int64,
        )

        return sorted(
            set(
                int(index)
                for index in indices
            )
        )

    @classmethod
    def _compact_grid(
        cls,
        values: Any,
        missing_mask: Any,
    ) -> tuple[np.ndarray, np.ndarray]:
        source_values = np.asarray(
            values,
            dtype=np.float32,
        )

        source_missing = np.asarray(
            missing_mask,
            dtype=bool,
        )

        if source_values.ndim != 2:
            raise RuntimeError(
                "Source values must be a two-dimensional grid."
            )

        if source_missing.shape != source_values.shape:
            raise RuntimeError(
                "Source missing mask does not match source values."
            )

        row_indices = cls._select_indices(
            source_values.shape[0],
            cls.TILE_SIZE,
        )

        column_indices = cls._select_indices(
            source_values.shape[1],
            cls.TILE_SIZE,
        )

        if not row_indices or not column_indices:
            raise LookupError(
                "The requested tile contains no source-grid cells."
            )

        compact_values = source_values[
            np.ix_(
                row_indices,
                column_indices,
            )
        ].copy()

        compact_missing = source_missing[
            np.ix_(
                row_indices,
                column_indices,
            )
        ].copy()

        invalid_values = (
            ~np.isfinite(compact_values)
        )

        compact_missing = (
            compact_missing
            | invalid_values
        )

        compact_values[
            compact_missing
        ] = np.nan

        return (
            compact_values,
            compact_missing,
        )

    # =========================================================================
    # BUILD TILE
    # =========================================================================

    def build_tile(
        self,
        *,
        variable: str,
        time_utc: str,
        depth_m: float,
        level: int,
        x: int,
        y: int,
    ) -> tuple[dict[str, Any], bytes]:
        level, x, y = self.validate_tile_request(
            level,
            x,
            y,
        )

        tile_bbox = self.tile_bbox(
            level,
            x,
            y,
        )

        (
            tile_latitude_min,
            tile_latitude_max,
            tile_longitude_min,
            tile_longitude_max,
        ) = tile_bbox

        intersected_bbox = self._intersect_bbox(
            tile_bbox,
            self._coverage,
        )

        if intersected_bbox is None:
            raise LookupError(
                "The requested tile does not overlap "
                "the available HYCOM coverage."
            )

        (
            query_latitude_min,
            query_latitude_max,
            query_longitude_min,
            query_longitude_max,
        ) = intersected_bbox

        normalized_variable = (
            str(variable)
            .strip()
            .upper()
        )

        result = self.slice_engine.query_dict(
            latitude_min=query_latitude_min,
            latitude_max=query_latitude_max,
            longitude_min=query_longitude_min,
            longitude_max=query_longitude_max,
            depth_m=float(depth_m),
            time_utc=time_utc,
            variable=normalized_variable,
        )

        grid = result.get(
            "grid",
            {},
        )

        source_values = grid.get(
            "values",
            [],
        )

        source_missing = grid.get(
            "missing_mask",
            [],
        )

        compact_values, compact_missing = (
            self._compact_grid(
                source_values,
                source_missing,
            )
        )

        finite_values = compact_values[
            np.isfinite(compact_values)
        ]

        if finite_values.size == 0:
            raise LookupError(
                "The requested tile contains no valid source values."
            )

        actual = result.get(
            "actual",
            {},
        )

        variable_info = result.get(
            "variable",
            {},
        )

        source = result.get(
            "source",
            {},
        )

        metadata: dict[str, Any] = {
            "available": True,
            "format": "oceansight-f32-v1",
            "encoding": "little-endian-float32",
            "level": level,
            "x": x,
            "y": y,
            "tile_size": {
                "width": int(
                    compact_values.shape[1]
                ),
                "height": int(
                    compact_values.shape[0]
                ),
            },
            "bbox": {
                "latitude_min": tile_latitude_min,
                "latitude_max": tile_latitude_max,
                "longitude_min": tile_longitude_min,
                "longitude_max": tile_longitude_max,
            },
            "source_bbox": {
                "latitude_min": query_latitude_min,
                "latitude_max": query_latitude_max,
                "longitude_min": query_longitude_min,
                "longitude_max": query_longitude_max,
            },
            "available_coverage": self.coverage,
            "variable": {
                "name": variable_info.get(
                    "name",
                    normalized_variable,
                ),
                "output_name": variable_info.get(
                    "output_name"
                ),
                "units": variable_info.get(
                    "units"
                ),
            },
            "depth_m": {
                "requested": float(
                    depth_m
                ),
                "actual": actual.get(
                    "depth_m"
                ),
            },
            "time_utc": {
                "requested": time_utc,
                "actual": actual.get(
                    "time_utc"
                ),
            },
            "value_range": {
                "min": float(
                    np.min(finite_values)
                ),
                "max": float(
                    np.max(finite_values)
                ),
            },
            "valid_value_count": int(
                finite_values.size
            ),
            "missing_value_count": int(
                np.count_nonzero(
                    compact_missing
                )
            ),
            "source": source,
            "scientific_rules": {
                "synthetic_data": False,
                "interpolation": False,
                "source_grid_values_only": True,
                "tile_downsampling": (
                    "regular existing source-grid indices only"
                ),
            },
        }

        values_bytes = np.asarray(
            compact_values,
            dtype="<f4",
            order="C",
        ).tobytes()

        missing_bytes = np.asarray(
            compact_missing,
            dtype=np.uint8,
            order="C",
        ).tobytes()

        metadata["binary_sections"] = {
            "values": {
                "offset": 0,
                "bytes": len(
                    values_bytes
                ),
                "dtype": "float32",
            },
            "missing_mask": {
                "offset": len(
                    values_bytes
                ),
                "bytes": len(
                    missing_bytes
                ),
                "dtype": "uint8",
            },
        }

        metadata_bytes = json.dumps(
            metadata,
            separators=(
                ",",
                ":",
            ),
            ensure_ascii=False,
        ).encode(
            "utf-8"
        )

        # First 8 bytes:
        # little-endian unsigned metadata length.
        payload = (
            struct.pack(
                "<Q",
                len(metadata_bytes),
            )
            + metadata_bytes
            + values_bytes
            + missing_bytes
        )

        return metadata, payload