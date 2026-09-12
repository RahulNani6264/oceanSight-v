
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from .hycom_chunk_index import (
    HycomChunkIndex,
    HycomChunkRecord,
)


# =============================================================================
# OCEANSIGHT-V
# HYCOM SCIENTIFIC DEPTH-SLICE ENGINE
#
# Purpose:
#
#   Assemble a real HYCOM field from locally stored real INCOIS chunks.
#
# Input:
#
#   latitude_min
#   latitude_max
#   longitude_min
#   longitude_max
#   depth_m
#   time_utc
#   variable
#
# Supported variables:
#
#   TEMP
#   SALN
#   UVEL
#   VVEL
#   SSH
#
# Scientific rules:
#
#   - Real INCOIS HYCOM values only.
#   - No interpolation.
#   - No synthetic values.
#   - Missing source values remain missing.
#   - Source time must exactly match requested time.
#   - Depth-dependent variables use nearest real HYCOM depth level.
#   - SSH is surface-only and ignores depth when reading the field.
#
# IMPORTANT IMPLEMENTATION DETAIL:
#
#   _load_chunk() returns a normal dict[str, np.ndarray].
#   Therefore use:
#
#       "TEMP" in arrays
#
#   rather than:
#
#       "TEMP" in arrays.files
#
# =============================================================================


# =============================================================================
# PROJECT
# =============================================================================

PROJECT_ROOT = (
    Path(__file__).resolve().parent.parent
)


# =============================================================================
# VARIABLE METADATA
# =============================================================================

@dataclass(frozen=True)
class VariableDefinition:
    name: str
    output_name: str
    units: str
    dimensions: str
    depth_dependent: bool


VARIABLES: dict[str, VariableDefinition] = {

    "TEMP": VariableDefinition(
        name="TEMP",
        output_name="temperature_c",
        units="degree_Celsius",
        dimensions="[time, depth, lat, lon]",
        depth_dependent=True,
    ),

    "SALN": VariableDefinition(
        name="SALN",
        output_name="salinity_psu",
        units="PSU",
        dimensions="[time, depth, lat, lon]",
        depth_dependent=True,
    ),

    "UVEL": VariableDefinition(
        name="UVEL",
        output_name="u_current_m_s",
        units="m s-1",
        dimensions="[time, depth, lat, lon]",
        depth_dependent=True,
    ),

    "VVEL": VariableDefinition(
        name="VVEL",
        output_name="v_current_m_s",
        units="m s-1",
        dimensions="[time, depth, lat, lon]",
        depth_dependent=True,
    ),

    "SSH": VariableDefinition(
        name="SSH",
        output_name="ssh_m",
        units="m",
        dimensions="[time, lat, lon]",
        depth_dependent=False,
    ),
}


# =============================================================================
# RESULT
# =============================================================================

@dataclass(frozen=True)
class OceanSlice:

    requested_latitude_min: float
    requested_latitude_max: float

    requested_longitude_min: float
    requested_longitude_max: float

    requested_depth_m: float

    requested_time_utc: str

    variable: str

    units: str

    actual_depth_m: float | None

    actual_time_utc: str

    latitudes: np.ndarray

    longitudes: np.ndarray

    values: np.ndarray

    missing_mask: np.ndarray

    source: str

    datasets: list[str]

    source_urls: list[str]

    chunk_files: list[str]

    provenance_paths: list[str]

    selection: str

    interpolation: bool

    synthetic_data: bool


# =============================================================================
# ENGINE
# =============================================================================

class OceanSliceEngine:
    """
    Assemble real HYCOM geographic slices from locally stored chunks.
    """

    def __init__(
        self,
        chunk_index: HycomChunkIndex | None = None,
    ) -> None:

        self.index = (
            chunk_index
            if chunk_index is not None
            else HycomChunkIndex()
        )

    # =========================================================================
    # VALIDATE BBOX
    # =========================================================================

    @staticmethod
    def _validate_bbox(
        latitude_min: float,
        latitude_max: float,
        longitude_min: float,
        longitude_max: float,
    ) -> tuple[
        float,
        float,
        float,
        float,
    ]:

        latitude_min = float(
            latitude_min
        )

        latitude_max = float(
            latitude_max
        )

        longitude_min = float(
            longitude_min
        )

        longitude_max = float(
            longitude_max
        )

        if not (
            -90.0
            <= latitude_min
            <= 90.0
        ):
            raise ValueError(
                "latitude_min must be between -90 and 90."
            )

        if not (
            -90.0
            <= latitude_max
            <= 90.0
        ):
            raise ValueError(
                "latitude_max must be between -90 and 90."
            )

        if latitude_min > latitude_max:
            raise ValueError(
                "latitude_min cannot be greater than latitude_max."
            )

        if not (
            -180.0
            <= longitude_min
            <= 180.0
        ):
            raise ValueError(
                "longitude_min must be between -180 and 180."
            )

        if not (
            -180.0
            <= longitude_max
            <= 180.0
        ):
            raise ValueError(
                "longitude_max must be between -180 and 180."
            )

        # First implementation intentionally does not cross the dateline.
        if longitude_min > longitude_max:

            raise ValueError(
                "This slice implementation currently requires "
                "longitude_min <= longitude_max and does not "
                "support a dateline-crossing region."
            )

        return (
            latitude_min,
            latitude_max,
            longitude_min,
            longitude_max,
        )

    # =========================================================================
    # VARIABLE DEFINITION
    # =========================================================================

    @staticmethod
    def _variable_definition(
        variable: str,
    ) -> VariableDefinition:

        normalized = (
            str(variable)
            .strip()
            .upper()
        )

        if normalized not in VARIABLES:

            supported = ", ".join(
                sorted(
                    VARIABLES.keys()
                )
            )

            raise ValueError(
                f"Unsupported HYCOM variable '{variable}'. "
                f"Supported variables: {supported}"
            )

        return VARIABLES[
            normalized
        ]

    # =========================================================================
    # TIME
    # =========================================================================

    @staticmethod
    def _parse_time(
        value: str,
    ) -> datetime:

        text = str(
            value
        ).strip()

        if text.endswith("Z"):

            text = (
                text[:-1]
                + "+00:00"
            )

        try:

            parsed = datetime.fromisoformat(
                text
            )

        except ValueError as exc:

            raise ValueError(
                "time_utc must be a valid ISO-8601 timestamp."
            ) from exc

        if parsed.tzinfo is None:

            parsed = parsed.replace(
                tzinfo=timezone.utc
            )

        return parsed.astimezone(
            timezone.utc
        )

    @classmethod
    def _canonical_time(
        cls,
        value: str,
    ) -> str:

        parsed = cls._parse_time(
            value
        )

        return (
            parsed
            .replace(
                microsecond=0
            )
            .isoformat()
            .replace(
                "+00:00",
                "Z",
            )
        )

    # =========================================================================
    # LOAD CHUNK
    # =========================================================================

    @staticmethod
    def _load_chunk(
        chunk: HycomChunkRecord,
    ) -> dict[str, np.ndarray]:

        path = Path(
            chunk.chunk_path
        )

        if not path.exists():

            raise FileNotFoundError(
                f"HYCOM chunk does not exist: {path}"
            )

        with np.load(
            path,
            allow_pickle=False,
        ) as data:

            return {
                name: data[name]
                for name in data.files
            }

    # =========================================================================
    # CHUNK INTERSECTION
    # =========================================================================

    @staticmethod
    def _intersects(
        chunk: HycomChunkRecord,
        latitude_min: float,
        latitude_max: float,
        longitude_min: float,
        longitude_max: float,
    ) -> bool:

        lat_overlap = not (
            chunk.latitude_max
            < latitude_min
            or chunk.latitude_min
            > latitude_max
        )

        lon_overlap = not (
            chunk.longitude_max
            < longitude_min
            or chunk.longitude_min
            > longitude_max
        )

        return (
            lat_overlap
            and lon_overlap
        )

    # =========================================================================
    # FIND REGION CANDIDATES
    # =========================================================================

    def _find_region_candidates(
        self,
        latitude_min: float,
        latitude_max: float,
        longitude_min: float,
        longitude_max: float,
        time_utc: str,
        depth_m: float,
    ) -> list[HycomChunkRecord]:

        canonical_time = (
            self._canonical_time(
                time_utc
            )
        )

        records: list[
            HycomChunkRecord
        ] = []

        for chunk in self.index.records:

            # -----------------------------------------------------------------
            # Exact source time is mandatory.
            # -----------------------------------------------------------------

            chunk_time = (
                self._canonical_time(
                    chunk.source_time_utc
                )
            )

            if chunk_time != canonical_time:
                continue

            # -----------------------------------------------------------------
            # Requested depth must be within chunk depth range.
            # -----------------------------------------------------------------

            if not (
                chunk.depth_min_m
                <= depth_m
                <= chunk.depth_max_m
            ):
                continue

            # -----------------------------------------------------------------
            # Geographic overlap.
            # -----------------------------------------------------------------

            if not self._intersects(
                chunk=chunk,
                latitude_min=latitude_min,
                latitude_max=latitude_max,
                longitude_min=longitude_min,
                longitude_max=longitude_max,
            ):
                continue

            records.append(
                chunk
            )

        records.sort(
            key=lambda item: (
                item.latitude_min,
                item.longitude_min,
                item.chunk_file,
            )
        )

        return records

    # =========================================================================
    # NEAREST INDEX
    # =========================================================================

    @staticmethod
    def _nearest_index(
        values: np.ndarray,
        requested: float,
    ) -> int:

        values = np.asarray(
            values,
            dtype=np.float64,
        ).reshape(-1)

        if values.size == 0:

            raise RuntimeError(
                "Cannot select a nearest value from an empty coordinate axis."
            )

        difference = np.abs(
            values
            - float(requested)
        )

        return int(
            np.argmin(
                difference
            )
        )

    # =========================================================================
    # SELECT AXIS INDICES
    # =========================================================================

    @staticmethod
    def _selected_indices(
        values: np.ndarray,
        minimum: float,
        maximum: float,
    ) -> np.ndarray:

        values = np.asarray(
            values,
            dtype=np.float64,
        ).reshape(-1)

        mask = (
            (values >= minimum)
            & (values <= maximum)
        )

        return np.flatnonzero(
            mask
        )

    # =========================================================================
    # UNIQUE SORTED AXIS
    # =========================================================================

    @staticmethod
    def _unique_sorted(
        values: list[float],
        tolerance: float = 1e-8,
    ) -> np.ndarray:

        if not values:

            return np.array(
                [],
                dtype=np.float64,
            )

        values_array = np.asarray(
            values,
            dtype=np.float64,
        )

        values_array = np.sort(
            values_array
        )

        unique: list[float] = [
            float(
                values_array[0]
            )
        ]

        for value in values_array[1:]:

            numeric_value = float(
                value
            )

            if (
                abs(
                    numeric_value
                    - unique[-1]
                )
                > tolerance
            ):

                unique.append(
                    numeric_value
                )

        return np.asarray(
            unique,
            dtype=np.float64,
        )

    # =========================================================================
    # AXIS POSITION
    # =========================================================================

    @staticmethod
    def _axis_position(
        axis: np.ndarray,
        value: float,
        tolerance: float = 1e-8,
    ) -> int:

        if axis.size == 0:

            raise RuntimeError(
                "Cannot locate a value on an empty axis."
            )

        index = int(
            np.argmin(
                np.abs(
                    axis
                    - float(value)
                )
            )
        )

        difference = abs(
            float(
                axis[index]
            )
            - float(value)
        )

        if difference > tolerance:

            raise RuntimeError(
                "Coordinate could not be mapped to the assembled "
                "HYCOM slice grid."
            )

        return index

    # =========================================================================
    # ACTUAL DEPTH
    # =========================================================================

    def _actual_depth(
        self,
        records: list[HycomChunkRecord],
        requested_depth_m: float,
    ) -> float:

        candidate_depths: list[
            float
        ] = []

        for record in records:

            arrays = self._load_chunk(
                record
            )

            # _load_chunk() returns dict[str, np.ndarray].
            if "depth" not in arrays:

                continue

            depth_values = np.asarray(
                arrays["depth"],
                dtype=np.float64,
            ).reshape(-1)

            if depth_values.size == 0:

                continue

            index = self._nearest_index(
                depth_values,
                requested_depth_m,
            )

            candidate_depths.append(
                float(
                    depth_values[
                        index
                    ]
                )
            )

        if not candidate_depths:

            raise LookupError(
                "No HYCOM depth coordinate was available "
                "for the requested slice."
            )

        return min(
            candidate_depths,
            key=lambda value:
            abs(
                value
                - requested_depth_m
            ),
        )

    # =========================================================================
    # SOURCE VALUE CHECK
    # =========================================================================

    @staticmethod
    def _is_valid_source_value(
        value: Any,
    ) -> bool:

        try:

            return bool(
                np.isfinite(
                    float(
                        value
                    )
                )
            )

        except (
            TypeError,
            ValueError,
        ):

            return False

    # =========================================================================
    # ASSIGN CELL
    # =========================================================================

    @classmethod
    def _assign_cell(
        cls,
        values: np.ndarray,
        missing_mask: np.ndarray,
        row_index: int,
        column_index: int,
        value: Any,
    ) -> None:

        if not cls._is_valid_source_value(
            value
        ):
            return

        # Preserve first valid source cell.
        if missing_mask[
            row_index,
            column_index,
        ]:

            values[
                row_index,
                column_index,
            ] = float(
                value
            )

            missing_mask[
                row_index,
                column_index,
            ] = False

    # =========================================================================
    # QUERY
    # =========================================================================

    def query(
        self,
        latitude_min: float,
        latitude_max: float,
        longitude_min: float,
        longitude_max: float,
        depth_m: float,
        time_utc: str,
        variable: str = "TEMP",
    ) -> OceanSlice:

        (
            latitude_min,
            latitude_max,
            longitude_min,
            longitude_max,
        ) = self._validate_bbox(
            latitude_min=latitude_min,
            latitude_max=latitude_max,
            longitude_min=longitude_min,
            longitude_max=longitude_max,
        )

        depth_m = float(
            depth_m
        )

        if depth_m < 0.0:

            raise ValueError(
                "depth_m cannot be negative."
            )

        canonical_time = (
            self._canonical_time(
                time_utc
            )
        )

        variable_definition = (
            self._variable_definition(
                variable
            )
        )

        # ---------------------------------------------------------------------
        # Find existing real chunks.
        # ---------------------------------------------------------------------

        records = (
            self._find_region_candidates(
                latitude_min=latitude_min,
                latitude_max=latitude_max,
                longitude_min=longitude_min,
                longitude_max=longitude_max,
                time_utc=canonical_time,
                depth_m=depth_m,
            )
        )

        if not records:

            raise LookupError(
                "No locally stored HYCOM chunks cover "
                "the requested slice at the exact source time."
            )

        # ---------------------------------------------------------------------
        # Select actual source depth for depth-dependent fields.
        # ---------------------------------------------------------------------

        if variable_definition.depth_dependent:

            actual_depth = (
                self._actual_depth(
                    records=records,
                    requested_depth_m=depth_m,
                )
            )

        else:

            actual_depth = None

        # ---------------------------------------------------------------------
        # Load candidate chunks and gather source coordinates.
        # ---------------------------------------------------------------------

        loaded_chunks: list[
            tuple[
                HycomChunkRecord,
                dict[str, np.ndarray],
            ]
        ] = []

        all_latitudes: list[
            float
        ] = []

        all_longitudes: list[
            float
        ] = []

        for record in records:

            arrays = self._load_chunk(
                record
            )

            required_coordinates = [
                "lat",
                "lon",
                "time_iso",
            ]

            missing_coordinates = [
                name
                for name in required_coordinates
                if name not in arrays
            ]

            if missing_coordinates:

                raise RuntimeError(
                    f"Chunk {record.chunk_file} is missing "
                    "required coordinate arrays: "
                    + ", ".join(
                        missing_coordinates
                    )
                )

            chunk_latitudes = np.asarray(
                arrays["lat"],
                dtype=np.float64,
            ).reshape(-1)

            chunk_longitudes = np.asarray(
                arrays["lon"],
                dtype=np.float64,
            ).reshape(-1)

            selected_latitudes = (
                self._selected_indices(
                    chunk_latitudes,
                    latitude_min,
                    latitude_max,
                )
            )

            selected_longitudes = (
                self._selected_indices(
                    chunk_longitudes,
                    longitude_min,
                    longitude_max,
                )
            )

            if (
                selected_latitudes.size == 0
                or selected_longitudes.size == 0
            ):

                continue

            all_latitudes.extend(
                float(
                    chunk_latitudes[
                        index
                    ]
                )
                for index in selected_latitudes
            )

            all_longitudes.extend(
                float(
                    chunk_longitudes[
                        index
                    ]
                )
                for index in selected_longitudes
            )

            loaded_chunks.append(
                (
                    record,
                    arrays,
                )
            )

        if not loaded_chunks:

            raise LookupError(
                "The indexed HYCOM chunks do not contain "
                "grid cells inside the requested geographic bounds."
            )

        # ---------------------------------------------------------------------
        # Build final coordinate axes.
        # ---------------------------------------------------------------------

        latitudes = self._unique_sorted(
            all_latitudes
        )

        longitudes = self._unique_sorted(
            all_longitudes
        )

        if latitudes.size == 0:

            raise LookupError(
                "No latitude grid points were found."
            )

        if longitudes.size == 0:

            raise LookupError(
                "No longitude grid points were found."
            )

        # ---------------------------------------------------------------------
        # Initialize every cell as missing.
        #
        # NaN is used internally because JSON has no standard NaN value.
        # query_dict() converts these to null.
        # ---------------------------------------------------------------------

        values = np.full(
            (
                latitudes.size,
                longitudes.size,
            ),
            np.nan,
            dtype=np.float64,
        )

        missing_mask = np.ones(
            (
                latitudes.size,
                longitudes.size,
            ),
            dtype=bool,
        )

        # ---------------------------------------------------------------------
        # Populate final slice.
        # ---------------------------------------------------------------------

        for record, arrays in loaded_chunks:

            chunk_latitudes = np.asarray(
                arrays["lat"],
                dtype=np.float64,
            ).reshape(-1)

            chunk_longitudes = np.asarray(
                arrays["lon"],
                dtype=np.float64,
            ).reshape(-1)

            lat_indices = (
                self._selected_indices(
                    chunk_latitudes,
                    latitude_min,
                    latitude_max,
                )
            )

            lon_indices = (
                self._selected_indices(
                    chunk_longitudes,
                    longitude_min,
                    longitude_max,
                )
            )

            # -----------------------------------------------------------------
            # Verify exact source time again.
            # -----------------------------------------------------------------

            chunk_time_values = np.asarray(
                arrays[
                    "time_iso"
                ]
            ).reshape(-1)

            if chunk_time_values.size == 0:

                raise RuntimeError(
                    f"Chunk {record.chunk_file} has empty time_iso."
                )

            source_time = str(
                chunk_time_values[0]
            )

            if (
                self._canonical_time(
                    source_time
                )
                != canonical_time
            ):

                raise RuntimeError(
                    "Scientific time mismatch detected while assembling "
                    f"chunk {record.chunk_file}: "
                    f"{source_time} != {canonical_time}"
                )

            # -----------------------------------------------------------------
            # Verify requested variable exists.
            # -----------------------------------------------------------------

            variable_name = (
                variable_definition.name
            )

            if variable_name not in arrays:

                raise RuntimeError(
                    f"Chunk {record.chunk_file} does not contain "
                    f"HYCOM variable {variable_name}."
                )

            field = arrays[
                variable_name
            ]

            # -----------------------------------------------------------------
            # Select depth level.
            # -----------------------------------------------------------------

            depth_index: int | None = None

            if variable_definition.depth_dependent:

                if "depth" not in arrays:

                    raise RuntimeError(
                        f"Chunk {record.chunk_file} does not contain "
                        "a depth coordinate."
                    )

                chunk_depth = np.asarray(
                    arrays["depth"],
                    dtype=np.float64,
                ).reshape(-1)

                depth_index = (
                    self._nearest_index(
                        chunk_depth,
                        actual_depth
                        if actual_depth is not None
                        else depth_m,
                    )
                )

            # -----------------------------------------------------------------
            # Populate every geographic cell.
            # -----------------------------------------------------------------

            for source_lat_index in lat_indices:

                source_latitude = float(
                    chunk_latitudes[
                        source_lat_index
                    ]
                )

                output_lat_index = (
                    self._axis_position(
                        latitudes,
                        source_latitude,
                    )
                )

                for source_lon_index in lon_indices:

                    source_longitude = float(
                        chunk_longitudes[
                            source_lon_index
                        ]
                    )

                    output_lon_index = (
                        self._axis_position(
                            longitudes,
                            source_longitude,
                        )
                    )

                    # ---------------------------------------------------------
                    # Depth-dependent:
                    #
                    #     [time, depth, lat, lon]
                    #
                    # SSH:
                    #
                    #     [time, lat, lon]
                    # ---------------------------------------------------------

                    if variable_definition.depth_dependent:

                        if depth_index is None:

                            raise RuntimeError(
                                "Depth index was not selected for "
                                "a depth-dependent variable."
                            )

                        value = field[
                            0,
                            depth_index,
                            source_lat_index,
                            source_lon_index,
                        ]

                    else:

                        value = field[
                            0,
                            source_lat_index,
                            source_lon_index,
                        ]

                    self._assign_cell(
                        values=values,
                        missing_mask=missing_mask,
                        row_index=output_lat_index,
                        column_index=output_lon_index,
                        value=value,
                    )

        # ---------------------------------------------------------------------
        # Source metadata.
        # ---------------------------------------------------------------------

        datasets = sorted(
            {
                record.dataset_file
                for record in records
            }
        )

        source_urls = sorted(
            {
                record.dataset_url
                for record in records
            }
        )

        chunk_files = sorted(
            {
                record.chunk_file
                for record in records
            }
        )

        provenance_paths = sorted(
            {
                record.provenance_path
                for record in records
                if record.provenance_path
            }
        )

        # ---------------------------------------------------------------------
        # Require at least one valid real source cell.
        # ---------------------------------------------------------------------

        valid_count = int(
            np.count_nonzero(
                ~missing_mask
            )
        )

        if valid_count == 0:

            raise LookupError(
                "The requested HYCOM slice contains only "
                "missing source values."
            )

        return OceanSlice(

            requested_latitude_min=(
                latitude_min
            ),

            requested_latitude_max=(
                latitude_max
            ),

            requested_longitude_min=(
                longitude_min
            ),

            requested_longitude_max=(
                longitude_max
            ),

            requested_depth_m=(
                depth_m
            ),

            requested_time_utc=(
                canonical_time
            ),

            variable=(
                variable_definition.name
            ),

            units=(
                variable_definition.units
            ),

            actual_depth_m=(
                actual_depth
            ),

            actual_time_utc=(
                canonical_time
            ),

            latitudes=(
                latitudes
            ),

            longitudes=(
                longitudes
            ),

            values=(
                values
            ),

            missing_mask=(
                missing_mask
            ),

            source="INCOIS",

            datasets=(
                datasets
            ),

            source_urls=(
                source_urls
            ),

            chunk_files=(
                chunk_files
            ),

            provenance_paths=(
                provenance_paths
            ),

            selection=(
                "nearest-neighbour depth selection; "
                "real source grid cells assembled without interpolation"
            ),

            interpolation=False,

            synthetic_data=False,
        )

    # =========================================================================
    # DICTIONARY OUTPUT
    # =========================================================================

    def query_dict(
        self,
        latitude_min: float,
        latitude_max: float,
        longitude_min: float,
        longitude_max: float,
        depth_m: float,
        time_utc: str,
        variable: str = "TEMP",
    ) -> dict[str, Any]:

        result = self.query(
            latitude_min=latitude_min,
            latitude_max=latitude_max,
            longitude_min=longitude_min,
            longitude_max=longitude_max,
            depth_m=depth_m,
            time_utc=time_utc,
            variable=variable,
        )

        values = np.asarray(
            result.values,
            dtype=np.float64,
        )

        json_values: list[
            list[float | None]
        ] = []

        for row in values:

            json_row: list[
                float | None
            ] = []

            for value in row:

                if np.isfinite(
                    value
                ):

                    json_row.append(
                        float(
                            value
                        )
                    )

                else:

                    json_row.append(
                        None
                    )

            json_values.append(
                json_row
            )

        missing_mask = [
            [
                bool(
                    value
                )
                for value in row
            ]
            for row in result.missing_mask
        ]

        valid_values = (
            values[
                np.isfinite(values)
            ]
        )

        return {
            "available": True,

            "requested": {
                "latitude_min": (
                    result.requested_latitude_min
                ),
                "latitude_max": (
                    result.requested_latitude_max
                ),
                "longitude_min": (
                    result.requested_longitude_min
                ),
                "longitude_max": (
                    result.requested_longitude_max
                ),
                "depth_m": (
                    result.requested_depth_m
                ),
                "time_utc": (
                    result.requested_time_utc
                ),
                "variable": (
                    result.variable
                ),
            },

            "actual": {
                "depth_m": (
                    result.actual_depth_m
                ),
                "time_utc": (
                    result.actual_time_utc
                ),
            },

            "variable": {
                "name": (
                    result.variable
                ),
                "units": (
                    result.units
                ),
                "dimensions": (
                    VARIABLES[
                        result.variable
                    ].dimensions
                ),
            },

            "grid": {
                "latitudes": [
                    float(
                        value
                    )
                    for value in result.latitudes
                ],
                "longitudes": [
                    float(
                        value
                    )
                    for value in result.longitudes
                ],
                "values": (
                    json_values
                ),
                "missing_mask": (
                    missing_mask
                ),
            },

            "statistics": {
                "grid_rows": int(
                    result.latitudes.size
                ),
                "grid_columns": int(
                    result.longitudes.size
                ),
                "total_cells": int(
                    result.values.size
                ),
                "valid_cells": int(
                    valid_values.size
                ),
                "missing_cells": int(
                    result.values.size
                    - valid_values.size
                ),
                "minimum": (
                    float(
                        valid_values.min()
                    )
                    if valid_values.size
                    else None
                ),
                "maximum": (
                    float(
                        valid_values.max()
                    )
                    if valid_values.size
                    else None
                ),
            },

            "source": {
                "provider": (
                    result.source
                ),
                "datasets": (
                    result.datasets
                ),
                "source_urls": (
                    result.source_urls
                ),
                "chunk_files": (
                    result.chunk_files
                ),
                "provenance_paths": (
                    result.provenance_paths
                ),
            },

            "selection": (
                result.selection
            ),

            "interpolation": (
                result.interpolation
            ),

            "synthetic_data": (
                result.synthetic_data
            ),
        }


# =============================================================================
# COMMAND LINE TEST
# =============================================================================

def main() -> None:

    print(
        "=" * 80
    )

    print(
        "OCEANSIGHT-V"
    )

    print(
        "HYCOM DEPTH SLICE ENGINE"
    )

    print(
        "=" * 80
    )

    engine = OceanSliceEngine()

    result = engine.query_dict(
        latitude_min=-8.25,
        latitude_max=-8.15,
        longitude_min=68.15,
        longitude_max=68.25,
        depth_m=100.0,
        time_utc="2026-09-10T06:00:00Z",
        variable="TEMP",
    )

    print()

    print(
        "SLICE RESULT"
    )

    print(
        "-" * 80
    )

    print(
        "Variable:",
        result[
            "variable"
        ][
            "name"
        ],
    )

    print(
        "Units:",
        result[
            "variable"
        ][
            "units"
        ],
    )

    print(
        "Requested depth:",
        result[
            "requested"
        ][
            "depth_m"
        ],
        "m",
    )

    print(
        "Actual depth:",
        result[
            "actual"
        ][
            "depth_m"
        ],
        "m",
    )

    print(
        "Requested time:",
        result[
            "requested"
        ][
            "time_utc"
        ],
    )

    print(
        "Actual time:",
        result[
            "actual"
        ][
            "time_utc"
        ],
    )

    print(
        "Latitude points:",
        len(
            result[
                "grid"
            ][
                "latitudes"
            ]
        ),
    )

    print(
        "Longitude points:",
        len(
            result[
                "grid"
            ][
                "longitudes"
            ]
        ),
    )

    print(
        "Datasets:",
        result[
            "source"
        ][
            "datasets"
        ],
    )

    print(
        "Chunks:",
        result[
            "source"
        ][
            "chunk_files"
        ],
    )

    print(
        "Valid source cells:",
        result[
            "statistics"
        ][
            "valid_cells"
        ],
    )

    print(
        "Missing source cells:",
        result[
            "statistics"
        ][
            "missing_cells"
        ],
    )

    print(
        "Minimum value:",
        result[
            "statistics"
        ][
            "minimum"
        ],
    )

    print(
        "Maximum value:",
        result[
            "statistics"
        ][
            "maximum"
        ],
    )

    print(
        "Interpolation:",
        result[
            "interpolation"
        ],
    )

    print(
        "Synthetic data:",
        result[
            "synthetic_data"
        ],
    )

    print()

    print(
        "=" * 80
    )

    print(
        "HYCOM SLICE TEST COMPLETE"
    )

    print(
        "=" * 80
    )


if __name__ == "__main__":
    main()

