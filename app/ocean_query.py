
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np

from .hycom_chunk_index import (
    HycomChunkIndex,
)


# =============================================================================
# OCEANSIGHT-V
# LOCAL OCEAN QUERY ENGINE
#
# This is the first application-level scientific query layer.
#
# Input:
#   latitude
#   longitude
#   time
#   depth
#
# Output:
#   nearest real source grid point
#
# Fields:
#   TEMP
#   SALN
#   UVEL
#   VVEL
#   SSH
#
# No interpolation is performed.
#
# The engine returns:
#   - requested coordinates
#   - actual source coordinates
#   - actual source time
#   - actual source depth
#   - scientific values
#   - current speed
#   - current direction
#   - source provenance
#
# =============================================================================


PROJECT_ROOT = (
    Path(__file__).resolve().parent.parent
)

CHUNK_DIR = (
    PROJECT_ROOT
    / "processed"
    / "hycom_chunks"
)


@dataclass(frozen=True)
class OceanObservation:
    requested_latitude: float
    requested_longitude: float
    requested_depth_m: float
    requested_time_utc: str | None

    actual_latitude: float
    actual_longitude: float
    actual_depth_m: float
    actual_time_utc: str

    temperature_c: float | None
    salinity: float | None

    u_current_m_s: float | None
    v_current_m_s: float | None

    current_speed_m_s: float | None
    current_direction_math_deg: float | None

    ssh_m: float | None

    source: str
    dataset: str
    source_url: str

    temp_missing: bool
    salinity_missing: bool
    u_current_missing: bool
    v_current_missing: bool
    ssh_missing: bool

    chunk_file: str


class OceanQueryEngine:
    """
    Query real locally stored HYCOM chunks.
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
    # LOAD CHUNK
    # =========================================================================

    @staticmethod
    def _load_chunk(
        chunk_path: str | Path,
    ) -> dict[str, np.ndarray]:

        path = Path(
            chunk_path
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
    # NEAREST INDEX
    # =========================================================================

    @staticmethod
    def _nearest_index(
        values: np.ndarray,
        requested: float,
    ) -> int:

        difference = np.abs(
            values.astype(
                np.float64
            )
            - float(requested)
        )

        return int(
            np.argmin(
                difference
            )
        )

    # =========================================================================
    # SAFE VALUE
    # =========================================================================

    @staticmethod
    def _safe_value(
        array: np.ndarray,
        index: tuple[int, ...],
    ) -> tuple[
        float | None,
        bool,
    ]:

        value = float(
            array[index]
        )

        if not np.isfinite(value):

            return (
                None,
                True,
            )

        return (
            value,
            False,
        )

    # =========================================================================
    # QUERY
    # =========================================================================

    def query(
        self,
        latitude: float,
        longitude: float,
        depth_m: float,
        time_utc: str | None = None,
    ) -> OceanObservation:

        candidates = (
            self.index.find_candidates(
                latitude=latitude,
                longitude=longitude,
                requested_time=time_utc,
                depth=depth_m,
            )
        )

        if not candidates:

            raise LookupError(
                "No locally stored HYCOM chunk covers "
                "the requested location/depth."
            )

        # The first candidate is the closest indexed chunk according to the
        # chunk index ranking.
        chunk = candidates[0]

        arrays = self._load_chunk(
            chunk.chunk_path
        )

        lat = arrays[
            "lat"
        ]

        lon = arrays[
            "lon"
        ]

        depth = arrays[
            "depth"
        ]

        # ---------------------------------------------------------------------
        # Nearest source grid point.
        # ---------------------------------------------------------------------

        lat_index = self._nearest_index(
            lat,
            latitude,
        )

        lon_index = self._nearest_index(
            lon,
            longitude,
        )

        depth_index = self._nearest_index(
            depth,
            depth_m,
        )

        actual_latitude = float(
            lat[lat_index]
        )

        actual_longitude = float(
            lon[lon_index]
        )

        actual_depth = float(
            depth[depth_index]
        )

        actual_time = str(
            arrays[
                "time_iso"
            ][0]
        )

        # ---------------------------------------------------------------------
        # 4D scientific fields
        #
        # Dimension order:
        #
        #   [time, depth, lat, lon]
        # ---------------------------------------------------------------------

        field_index = (
            0,
            depth_index,
            lat_index,
            lon_index,
        )

        temp, temp_missing = (
            self._safe_value(
                arrays["TEMP"],
                field_index,
            )
        )

        salinity, salinity_missing = (
            self._safe_value(
                arrays["SALN"],
                field_index,
            )
        )

        u_current, u_missing = (
            self._safe_value(
                arrays["UVEL"],
                field_index,
            )
        )

        v_current, v_missing = (
            self._safe_value(
                arrays["VVEL"],
                field_index,
            )
        )

        # ---------------------------------------------------------------------
        # SSH
        #
        # Dimension order:
        #
        #   [time, lat, lon]
        # ---------------------------------------------------------------------

        ssh, ssh_missing = (
            self._safe_value(
                arrays["SSH"],
                (
                    0,
                    lat_index,
                    lon_index,
                ),
            )
        )

        # ---------------------------------------------------------------------
        # Current magnitude / direction
        #
        # U = eastward
        # V = northward
        #
        # Angle is mathematical:
        #   0° east
        #   +90° north
        #   ±180° west
        #   -90° south
        #
        # We are NOT converting this to meteorological bearing yet.
        # ---------------------------------------------------------------------

        if (
            u_current is not None
            and v_current is not None
        ):

            speed = float(
                np.hypot(
                    u_current,
                    v_current,
                )
            )

            direction = float(
                np.degrees(
                    np.arctan2(
                        v_current,
                        u_current,
                    )
                )
            )

        else:

            speed = None
            direction = None

        return OceanObservation(

            requested_latitude=float(
                latitude
            ),

            requested_longitude=float(
                longitude
            ),

            requested_depth_m=float(
                depth_m
            ),

            requested_time_utc=time_utc,

            actual_latitude=(
                actual_latitude
            ),

            actual_longitude=(
                actual_longitude
            ),

            actual_depth_m=(
                actual_depth
            ),

            actual_time_utc=(
                actual_time
            ),

            temperature_c=temp,

            salinity=salinity,

            u_current_m_s=u_current,

            v_current_m_s=v_current,

            current_speed_m_s=speed,

            current_direction_math_deg=(
                direction
            ),

            ssh_m=ssh,

            source="INCOIS",

            dataset=(
                chunk.dataset_file
            ),

            source_url=(
                chunk.dataset_url
            ),

            temp_missing=temp_missing,

            salinity_missing=(
                salinity_missing
            ),

            u_current_missing=(
                u_missing
            ),

            v_current_missing=(
                v_missing
            ),

            ssh_missing=(
                ssh_missing
            ),

            chunk_file=(
                chunk.chunk_file
            ),
        )

    # =========================================================================
    # DICTIONARY OUTPUT
    # =========================================================================

    def query_dict(
        self,
        latitude: float,
        longitude: float,
        depth_m: float,
        time_utc: str | None = None,
    ) -> dict[str, Any]:

        observation = self.query(
            latitude=latitude,
            longitude=longitude,
            depth_m=depth_m,
            time_utc=time_utc,
        )

        return asdict(
            observation
        )


def main() -> None:

    print("=" * 80)
    print(
        "OCEANSIGHT-V"
    )
    print(
        "LOCAL OCEAN QUERY ENGINE"
    )
    print("=" * 80)

    engine = OceanQueryEngine()

    result = engine.query_dict(
        latitude=-8.20,
        longitude=68.20,
        depth_m=100.0,
        time_utc=(
            "2026-09-10T06:00:00Z"
        ),
    )

    print()
    print(
        "QUERY RESULT"
    )

    print(
        "-" * 80
    )

    for key, value in result.items():

        print(
            f"{key}: {value}"
        )

    print()
    print("=" * 80)
    print(
        "OCEAN QUERY COMPLETE"
    )
    print("=" * 80)


if __name__ == "__main__":
    main()

