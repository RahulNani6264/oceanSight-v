
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .gebco_chunk_index import main as rebuild_gebco_index
from .gebco_chunk_store import download_bbox
from .gebco_query import GEBCOQuery


PROJECT_ROOT = Path(__file__).resolve().parent.parent

PROCESSED_DIR = (
    PROJECT_ROOT / "processed"
)

GEBCO_INDEX = (
    PROCESSED_DIR / "gebco_chunk_index.json"
)


class GEBCOLiveManager:
    """
    Live GEBCO acquisition manager.

    Responsibilities:

        1. Check whether local GEBCO data covers a point.
        2. Download a real GEBCO chunk when coverage is missing.
        3. Rebuild the GEBCO chunk index.
        4. Return a fresh GEBCOQuery result.

    No synthetic data.
    No interpolation.
    """

    def __init__(self) -> None:
        pass

    @staticmethod
    def _bounding_box(
        latitude: float,
        longitude: float,
        radius_degrees: float,
    ) -> tuple[float, float, float, float]:

        if radius_degrees <= 0:
            raise ValueError(
                "radius_degrees must be greater than zero."
            )

        lat_min = max(
            -90.0,
            latitude - radius_degrees,
        )

        lat_max = min(
            90.0,
            latitude + radius_degrees,
        )

        lon_min = max(
            -180.0,
            longitude - radius_degrees,
        )

        lon_max = min(
            180.0,
            longitude + radius_degrees,
        )

        return (
            lat_min,
            lat_max,
            lon_min,
            lon_max,
        )

    def query_or_acquire(
        self,
        latitude: float,
        longitude: float,
        radius_degrees: float = 0.25,
    ) -> dict[str, Any]:

        latitude = float(
            latitude
        )

        longitude = float(
            longitude
        )

        # -------------------------------------------------------------
        # First check the existing GEBCO cache.
        # -------------------------------------------------------------

        try:

            current_query = GEBCOQuery(
                index_path=GEBCO_INDEX
            )

            existing = current_query.query(
                latitude,
                longitude,
            )

            if existing.get(
                "available",
                False,
            ):

                existing[
                    "acquisition"
                ] = {
                    "automatic": False,
                    "downloaded": [],
                    "synthetic_data": False,
                    "interpolation": False,
                }

                return existing

        except (
            FileNotFoundError,
            RuntimeError,
        ):

            # No usable local index yet.
            pass

        # -------------------------------------------------------------
        # No local coverage.
        # Download real GEBCO data around the point.
        # -------------------------------------------------------------

        (
            lat_min,
            lat_max,
            lon_min,
            lon_max,
        ) = self._bounding_box(
            latitude=latitude,
            longitude=longitude,
            radius_degrees=radius_degrees,
        )

        saved_chunks = download_bbox(
            lat_min=lat_min,
            lat_max=lat_max,
            lon_min=lon_min,
            lon_max=lon_max,
        )

        # -------------------------------------------------------------
        # Rebuild the GEBCO index.
        #
        # The existing indexer is intentionally reused so the format
        # remains identical to manually indexed GEBCO chunks.
        # -------------------------------------------------------------

        rebuild_gebco_index()

        # -------------------------------------------------------------
        # Fresh query object.
        #
        # GEBCOQuery loads the index during __init__.
        # -------------------------------------------------------------

        refreshed_query = GEBCOQuery(
            index_path=GEBCO_INDEX
        )

        result = refreshed_query.query(
            latitude,
            longitude,
        )

        result[
            "acquisition"
        ] = {
            "automatic": True,
            "requested": {
                "latitude": latitude,
                "longitude": longitude,
                "radius_degrees": radius_degrees,
            },
            "bounding_box": {
                "latitude_min": lat_min,
                "latitude_max": lat_max,
                "longitude_min": lon_min,
                "longitude_max": lon_max,
            },
            "downloaded": [
                str(path)
                for path in saved_chunks
            ],
            "synthetic_data": False,
            "interpolation": False,
        }

        return result


def main() -> None:

    import argparse

    parser = argparse.ArgumentParser(
        description=(
            "Automatically acquire real GEBCO 2026 "
            "coverage for a requested point."
        )
    )

    parser.add_argument(
        "--latitude",
        type=float,
        required=True,
    )

    parser.add_argument(
        "--longitude",
        type=float,
        required=True,
    )

    parser.add_argument(
        "--radius-degrees",
        type=float,
        default=0.25,
    )

    args = parser.parse_args()

    manager = GEBCOLiveManager()

    result = manager.query_or_acquire(
        latitude=args.latitude,
        longitude=args.longitude,
        radius_degrees=args.radius_degrees,
    )

    print(
        json.dumps(
            result,
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()

