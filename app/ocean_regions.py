from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr


# =============================================================================
# OCEANSIGHT-V
# REAL OCEAN BASIN REGION RESOLVER
#
# Source:
#   RECCAP2 Ocean regional mask dataset
#
# The source defines open-ocean masks for:
#   atlantic
#   pacific
#   indian
#   arctic
#   southern
#
# Scientific rule:
#   We only report a basin when the real source mask identifies the point.
#
# No:
#   - synthetic polygons
#   - guessed basin names
#   - coordinate heuristics
#   - interpolation
# =============================================================================


PROJECT_ROOT = (
    Path(__file__).resolve().parent.parent
)

DEFAULT_REGION_FILE = (
    PROJECT_ROOT
    / "data"
    / "ocean_regions"
    / "RECCAP2_region_masks_all_v20221025.nc"
)


# =============================================================================
# PUBLIC OCEAN DEFINITIONS
# =============================================================================

OCEAN_DEFINITIONS = {
    "Pacific Ocean": "pacific",
    "Atlantic Ocean": "atlantic",
    "Indian Ocean": "indian",
    "Southern Ocean": "southern",
    "Arctic Ocean": "arctic",
}


# =============================================================================
# RESULT
# =============================================================================

@dataclass(frozen=True)
class OceanRegionResult:
    available: bool
    ocean_name: str | None
    source_region: str | None
    latitude: float
    longitude: float
    source_latitude: float | None
    source_longitude: float | None
    source_file: str
    source: str
    selection: str
    interpolation: bool
    synthetic_data: bool


# =============================================================================
# ENGINE
# =============================================================================

class OceanRegionEngine:
    """
    Resolve a latitude/longitude to a real open-ocean basin using
    the RECCAP2 regional mask dataset.
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

        self._dataset: xr.Dataset | None = None

    # =========================================================================
    # DATASET
    # =========================================================================

    def _open_dataset(self) -> xr.Dataset:
        if self._dataset is None:
            self._dataset = xr.open_dataset(
                self.region_file
            )

        return self._dataset

    # =========================================================================
    # VALIDATION
    # =========================================================================

    @staticmethod
    def _validate_coordinates(
        latitude: float,
        longitude: float,
    ) -> tuple[float, float]:

        latitude = float(latitude)
        longitude = float(longitude)

        if not (
            -90.0
            <= latitude
            <= 90.0
        ):
            raise ValueError(
                "latitude must be between -90 and 90."
            )

        if not (
            -180.0
            <= longitude
            <= 180.0
        ):
            raise ValueError(
                "longitude must be between -180 and 180."
            )

        return latitude, longitude

    # =========================================================================
    # FIND COORDINATE AXES
    # =========================================================================

    @staticmethod
    def _find_coordinate_name(
        dataset: xr.Dataset,
        candidates: tuple[str, ...],
    ) -> str:

        available = set(
            dataset.coords
        ) | set(
            dataset.variables
        )

        for candidate in candidates:
            if candidate in available:
                return candidate

        raise RuntimeError(
            "Could not identify the latitude/longitude coordinate "
            f"from candidates: {candidates}. "
            f"Available variables: {sorted(available)}"
        )

    def _coordinates(
        self,
        dataset: xr.Dataset,
    ) -> tuple[str, str]:

        latitude_name = (
            self._find_coordinate_name(
                dataset,
                (
                    "lat",
                    "latitude",
                    "LAT",
                    "Latitude",
                ),
            )
        )

        longitude_name = (
            self._find_coordinate_name(
                dataset,
                (
                    "lon",
                    "longitude",
                    "LON",
                    "Longitude",
                ),
            )
        )

        return (
            latitude_name,
            longitude_name,
        )

    # =========================================================================
    # FIND REGION VARIABLE
    # =========================================================================

    @staticmethod
    def _find_region_variable(
        dataset: xr.Dataset,
        basin_name: str,
    ) -> str | None:

        normalized = (
            str(basin_name)
            .strip()
            .lower()
        )

        candidates = (
            normalized,
            f"{normalized}_mask",
        )

        variables = set(
            dataset.data_vars
        ) | set(
            dataset.variables
        )

        for candidate in candidates:
            if candidate in variables:
                return candidate

        return None

    # =========================================================================
    # NUMERIC AXIS
    # =========================================================================

    @staticmethod
    def _axis_values(
        dataset: xr.Dataset,
        name: str,
    ) -> np.ndarray:

        values = np.asarray(
            dataset[name].values,
            dtype=np.float64,
        ).reshape(-1)

        if values.size == 0:
            raise RuntimeError(
                f"Ocean-region coordinate axis '{name}' is empty."
            )

        return values

    # =========================================================================
    # NEAREST SOURCE INDEX
    # =========================================================================

    @staticmethod
    def _nearest_index(
        values: np.ndarray,
        requested: float,
    ) -> int:

        differences = np.abs(
            values
            - float(requested)
        )

        return int(
            np.argmin(
                differences
            )
        )

    # =========================================================================
    # MASK VALUE
    # =========================================================================

    @staticmethod
    def _mask_value(
        dataset: xr.Dataset,
        variable_name: str,
        latitude_name: str,
        longitude_name: str,
        latitude_index: int,
        longitude_index: int,
    ) -> Any:

        variable = dataset[
            variable_name
        ]

        # Standard 2D region masks.
        if set(
            variable.dims
        ) == {
            latitude_name,
            longitude_name,
        }:

            return variable.isel(
                {
                    latitude_name:
                        latitude_index,
                    longitude_name:
                        longitude_index,
                }
            ).values.item()

        # Allow dimension ordering to differ while preserving
        # source-grid semantics.
        if (
            latitude_name in variable.dims
            and longitude_name in variable.dims
        ):

            selection = {
                latitude_name:
                    latitude_index,
                longitude_name:
                    longitude_index,
            }

            return variable.isel(
                selection
            ).values.item()

        raise RuntimeError(
            f"Ocean-region variable '{variable_name}' does not "
            "contain the expected latitude/longitude dimensions."
        )

    # =========================================================================
    # VALID MASK VALUE
    # =========================================================================

    @staticmethod
    def _is_ocean_mask_active(
        value: Any,
    ) -> bool:

        try:
            numeric = float(value)
        except (
            TypeError,
            ValueError,
        ):
            return False

        if not np.isfinite(numeric):
            return False

        return numeric > 0

    # =========================================================================
    # RESOLVE
    # =========================================================================

    def identify(
        self,
        latitude: float,
        longitude: float,
    ) -> OceanRegionResult:

        latitude, longitude = (
            self._validate_coordinates(
                latitude,
                longitude,
            )
        )

        dataset = self._open_dataset()

        (
            latitude_name,
            longitude_name,
        ) = self._coordinates(
            dataset
        )

        latitudes = (
            self._axis_values(
                dataset,
                latitude_name,
            )
        )

        longitudes = (
            self._axis_values(
                dataset,
                longitude_name,
            )
        )

        latitude_index = (
            self._nearest_index(
                latitudes,
                latitude,
            )
        )

        longitude_index = (
            self._nearest_index(
                longitudes,
                longitude,
            )
        )

        actual_latitude = float(
            latitudes[
                latitude_index
            ]
        )

        actual_longitude = float(
            longitudes[
                longitude_index
            ]
        )

        # ---------------------------------------------------------------------
        # Check only the five supported open-ocean basin masks.
        # ---------------------------------------------------------------------

        matches: list[
            tuple[str, str]
        ] = []

        for (
            public_name,
            source_region,
        ) in OCEAN_DEFINITIONS.items():

            variable_name = (
                self._find_region_variable(
                    dataset,
                    source_region,
                )
            )

            if variable_name is None:
                continue

            value = (
                self._mask_value(
                    dataset=dataset,
                    variable_name=variable_name,
                    latitude_name=latitude_name,
                    longitude_name=longitude_name,
                    latitude_index=latitude_index,
                    longitude_index=longitude_index,
                )
            )

            if self._is_ocean_mask_active(
                value
            ):
                matches.append(
                    (
                        public_name,
                        source_region,
                    )
                )

        # ---------------------------------------------------------------------
        # No real basin match.
        #
        # This can occur for:
        #   - land
        #   - coast mask
        #   - source-grid missing area
        # ---------------------------------------------------------------------

        if not matches:

            return OceanRegionResult(
                available=False,
                ocean_name=None,
                source_region=None,
                latitude=latitude,
                longitude=longitude,
                source_latitude=actual_latitude,
                source_longitude=actual_longitude,
                source_file=str(
                    self.region_file
                ),
                source="RECCAP2 Ocean regional masks",
                selection=(
                    "nearest source-grid cell; "
                    "no interpolation"
                ),
                interpolation=False,
                synthetic_data=False,
            )

        # ---------------------------------------------------------------------
        # A valid point should normally belong to one basin.
        #
        # If multiple source masks overlap at the selected source cell,
        # refuse to silently choose one.
        # ---------------------------------------------------------------------

        if len(matches) > 1:

            names = ", ".join(
                item[0]
                for item in matches
            )

            raise RuntimeError(
                "Ocean-region masks overlap at the selected source "
                f"grid cell: {names}"
            )

        ocean_name, source_region = (
            matches[0]
        )

        return OceanRegionResult(
            available=True,
            ocean_name=ocean_name,
            source_region=source_region,
            latitude=latitude,
            longitude=longitude,
            source_latitude=actual_latitude,
            source_longitude=actual_longitude,
            source_file=str(
                self.region_file
            ),
            source="RECCAP2 Ocean regional masks",
            selection=(
                "nearest source-grid cell; "
                "real regional mask; no interpolation"
            ),
            interpolation=False,
            synthetic_data=False,
        )

    # =========================================================================
    # LIST OCEANS
    # =========================================================================

    def list_oceans(
        self,
    ) -> list[dict[str, str]]:

        return [
            {
                "name": public_name,
                "source_region": source_region,
            }
            for public_name, source_region
            in OCEAN_DEFINITIONS.items()
        ]

    # =========================================================================
    # DICTIONARY OUTPUT
    # =========================================================================

    def identify_dict(
        self,
        latitude: float,
        longitude: float,
    ) -> dict[str, Any]:

        result = self.identify(
            latitude=latitude,
            longitude=longitude,
        )

        return {
            "available": result.available,

            "ocean": (
                {
                    "name": result.ocean_name,
                    "source_region": result.source_region,
                }
                if result.available
                else None
            ),

            "requested": {
                "latitude": result.latitude,
                "longitude": result.longitude,
            },

            "source_grid": {
                "latitude": result.source_latitude,
                "longitude": result.source_longitude,
            },

            "source": {
                "provider": result.source,
                "file": result.source_file,
            },

            "selection": result.selection,

            "interpolation": result.interpolation,

            "synthetic_data": result.synthetic_data,
        }

    # =========================================================================
    # CLEANUP
    # =========================================================================

    def close(self) -> None:

        if self._dataset is not None:
            self._dataset.close()

            self._dataset = None