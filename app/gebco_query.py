from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any


import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]

INDEX_PATH = (
    PROJECT_ROOT
    / "processed"
    / "gebco_chunk_index.json"
)


class GEBCOQuery:
    """
    Query locally cached GEBCO 2026 numerical bathymetry.

    The query is nearest-neighbour only.
    No interpolation is performed.
    """

    def __init__(
        self,
        index_path: Path = INDEX_PATH,
    ) -> None:

        self.index_path = Path(index_path)

        if not self.index_path.exists():
            raise FileNotFoundError(
                f"GEBCO index not found:\n"
                f"{self.index_path}\n\n"
                "Run:\n"
                "python -m app.gebco_chunk_index"
            )

        with self.index_path.open(
            "r",
            encoding="utf-8",
        ) as f:
            self.index: dict[str, Any] = json.load(f)

        self.chunks = self.index.get(
            "chunks",
            [],
        )

        if not self.chunks:
            raise RuntimeError(
                "GEBCO index contains no chunks."
            )

    @staticmethod
    def _distance_sq(
        lat1: float,
        lon1: float,
        lat2: float,
        lon2: float,
    ) -> float:
        """
        Simple latitude/longitude distance metric for choosing
        the nearest grid point.

        This is sufficient for nearest-cell selection.
        """

        dlat = lat1 - lat2

        # Wrap longitude difference so that
        # 179.9 and -179.9 are close together.
        dlon = abs(lon1 - lon2)

        if dlon > 180.0:
            dlon = 360.0 - dlon

        return dlat * dlat + dlon * dlon

    @staticmethod
    def _contains(
        chunk: dict[str, Any],
        lat: float,
        lon: float,
    ) -> bool:

        lat_min = float(
            chunk["latitude_min"]
        )
        lat_max = float(
            chunk["latitude_max"]
        )

        lon_min = float(
            chunk["longitude_min"]
        )
        lon_max = float(
            chunk["longitude_max"]
        )

        return (
            lat_min <= lat <= lat_max
            and lon_min <= lon <= lon_max
        )

    def _candidate_chunks(
        self,
        lat: float,
        lon: float,
    ) -> list[dict[str, Any]]:

        candidates = [
            chunk
            for chunk in self.chunks
            if self._contains(
                chunk,
                lat,
                lon,
            )
        ]

        return candidates

    @staticmethod
    def _nearest_index(
        values: np.ndarray,
        target: float,
    ) -> int:

        values = np.asarray(
            values,
            dtype=np.float64,
        )

        if values.size == 0:
            raise ValueError(
                "Coordinate array is empty."
            )

        return int(
            np.argmin(
                np.abs(values - target)
            )
        )

    def query(
        self,
        lat: float,
        lon: float,
    ) -> dict[str, Any]:

        lat = float(lat)
        lon = float(lon)

        if not math.isfinite(lat):
            raise ValueError(
                "Latitude must be finite."
            )

        if not math.isfinite(lon):
            raise ValueError(
                "Longitude must be finite."
            )

        if not -90.0 <= lat <= 90.0:
            raise ValueError(
                "Latitude must be between -90 and 90."
            )

        # Normalize longitude.
        while lon > 180.0:
            lon -= 360.0

        while lon < -180.0:
            lon += 360.0

        candidates = self._candidate_chunks(
            lat,
            lon,
        )

        # If the exact point is outside every cached chunk,
        # do not pretend we have data.
        if not candidates:
            return {
                "available": False,
                "reason": (
                    "No cached GEBCO chunk covers "
                    "the requested coordinate."
                ),
                "latitude": lat,
                "longitude": lon,
                "source": "GEBCO",
                "dataset": "GEBCO_2026",
            }

        best_result: dict[str, Any] | None = None

        for chunk in candidates:

            npz_path = Path(
                chunk["npz_path"]
            )

            if not npz_path.exists():
                continue

            data = np.load(
                npz_path,
                allow_pickle=False,
            )

            try:
                latitudes = np.asarray(
                    data["latitude"],
                    dtype=np.float64,
                )

                longitudes = np.asarray(
                    data["longitude"],
                    dtype=np.float64,
                )

                elevation = np.asarray(
                    data["elevation_m"],
                    dtype=np.float32,
                )

                missing_mask = np.asarray(
                    data["missing_mask"],
                    dtype=bool,
                )

                lat_index = self._nearest_index(
                    latitudes,
                    lat,
                )

                lon_index = self._nearest_index(
                    longitudes,
                    lon,
                )

                source_lat = float(
                    latitudes[lat_index]
                )

                source_lon = float(
                    longitudes[lon_index]
                )

                source_elevation = float(
                    elevation[
                        lat_index,
                        lon_index,
                    ]
                )

                missing = bool(
                    missing_mask[
                        lat_index,
                        lon_index,
                    ]
                )

                distance = self._distance_sq(
                    lat,
                    lon,
                    source_lat,
                    source_lon,
                )

                result = {
                    "available": not missing,

                    "requested": {
                        "latitude": lat,
                        "longitude": lon,
                    },

                    "source_grid": {
                        "latitude": source_lat,
                        "longitude": source_lon,
                    },

                    "elevation_m": (
                        None
                        if missing
                        or not math.isfinite(
                            source_elevation
                        )
                        else source_elevation
                    ),

                    "missing": missing,

                    "selection": (
                        "nearest-neighbour"
                    ),

                    "chunk_id": chunk[
                        "chunk_id"
                    ],

                    "source": "GEBCO",

                    "dataset": "GEBCO_2026",

                    "source_url": self.index[
                        "source_url"
                    ],

                    "provenance_path": chunk[
                        "provenance_path"
                    ],

                    "_distance": distance,
                }

                if (
                    best_result is None
                    or distance
                    < best_result["_distance"]
                ):
                    best_result = result

            finally:
                data.close()

        if best_result is None:
            return {
                "available": False,
                "reason": (
                    "No readable GEBCO chunk "
                    "was available."
                ),
                "latitude": lat,
                "longitude": lon,
                "source": "GEBCO",
                "dataset": "GEBCO_2026",
            }

        best_result.pop(
            "_distance",
            None,
        )

        return best_result


def main() -> None:

    print("=" * 70)
    print("OceanSight - GEBCO Local Query Test")
    print("=" * 70)

    query_engine = GEBCOQuery()

    # Same area used by the HYCOM test.
    latitude = -8.2
    longitude = 68.2

    print()
    print("Requested:")
    print("  latitude :", latitude)
    print("  longitude:", longitude)

    result = query_engine.query(
        latitude,
        longitude,
    )

    print()
    print("Result:")
    print(
        json.dumps(
            result,
            indent=2,
        )
    )

    print()
    print("=" * 70)

    if result.get("available"):
        print(
            "SUCCESS: Actual GEBCO bathymetry "
            "was retrieved."
        )

        print()
        print(
            "Seafloor elevation:"
        )
        print(
            f"  {result['elevation_m']} meters"
        )

        print()
        print(
            "Because bathymetry is represented as "
            "elevation, a negative value means "
            "below sea level."
        )

    else:
        print(
            "NO BATHYMETRY AVAILABLE "
            "FOR THIS LOCAL CACHE."
        )

    print("=" * 70)


if __name__ == "__main__":
    main()