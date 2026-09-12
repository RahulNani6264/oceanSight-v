
from __future__ import annotations

import json
from datetime import datetime, timezone,timedelta
from pathlib import Path
from typing import Any

import httpx
import truststore

from .hycom_chunk_index import HycomChunkIndex
from .hycom_chunk_planner import HycomChunkPlanner
from .hycom_downloader import download_plan, existing_chunk_paths
from .hycom_thredds_discovery import find_dataset_for_time


PROJECT_ROOT = Path(__file__).resolve().parent.parent

PROCESSED_DIR = PROJECT_ROOT / "processed"

CATALOG_DIR = PROCESSED_DIR / "hycom_catalog"

HYCOM_CHUNK_DIR = PROCESSED_DIR / "hycom_chunks"

HYCOM_PROVENANCE_DIR = (
    PROCESSED_DIR / "hycom_chunk_provenance"
)

HYCOM_INDEX_PATH = (
    PROCESSED_DIR / "hycom_chunk_index.json"
)

CATALOG_DIR.mkdir(
    parents=True,
    exist_ok=True,
)

HYCOM_CHUNK_DIR.mkdir(
    parents=True,
    exist_ok=True,
)

HYCOM_PROVENANCE_DIR.mkdir(
    parents=True,
    exist_ok=True,
)


class HycomLiveManager:
    """
    Live INCOIS HYCOM acquisition manager.

    Responsibilities:

        1. Discover the real HYCOM dataset for the requested UTC time.
        2. Ensure a coordinate catalog exists for that dataset.
        3. Plan chunks around the requested geographic point.
        4. Check whether those chunks already exist.
        5. Download missing chunks from INCOIS OPeNDAP.
        6. Rebuild the local HYCOM chunk index.

    No synthetic data.
    No interpolation.
    No full NetCDF download.
    """

    def __init__(
        self,
        catalog_dir: Path | str = CATALOG_DIR,
    ) -> None:

        self.catalog_dir = Path(
            catalog_dir
        )

        self.catalog_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

    # =========================================================================
    # DISCOVERY
    # =========================================================================

    def discover_dataset(
        self,
        time_utc: str,
    ) -> dict[str, Any]:

        return find_dataset_for_time(
            requested_time_utc=time_utc,
        )

    # =========================================================================
    # DATASET URL
    # =========================================================================

    @staticmethod
    def _dataset_url(
        filename: str,
    ) -> str:

        return (
            "https://incois.gov.in/thredds/"
            "dodsC/osf/currents2/"
            f"{filename}"
        )

    # =========================================================================
    # HTTP CLIENT
    # =========================================================================

    @staticmethod
    def _build_client() -> httpx.Client:

        truststore.inject_into_ssl()

        timeout = httpx.Timeout(
            connect=30.0,
            read=120.0,
            write=60.0,
            pool=30.0,
        )

        return httpx.Client(
            verify=True,
            timeout=timeout,
            follow_redirects=True,
            headers={
                "User-Agent": (
                    "OceanSight-V/1.0 "
                    "HYCOM live manager"
                )
            },
        )

    # =========================================================================
    # COMPLETE DATASET PREPARATION
    # =========================================================================

    def prepare_for_time(
        self,
        time_utc: str,
    ) -> dict[str, Any]:

        discovery = self.discover_dataset(
            time_utc
        )

        if not discovery.get(
            "available",
            False,
        ):

            return {
                "available": False,
                "discovery": discovery,
                "catalog": None,
            }

        selected = discovery.get(
            "selected"
        )

        if not isinstance(
            selected,
            dict,
        ):
            raise RuntimeError(
                "HYCOM discovery returned no selected dataset."
            )

        catalog = self.ensure_coordinate_catalog(
            discovery
        )

        return {
            "available": True,
            "discovery": discovery,
            "catalog": catalog,
        }

    # =========================================================================
    # CATALOG PATHS
    # =========================================================================

    def _catalog_paths(
        self,
        filename: str,
    ) -> tuple[Path, Path]:

        stem = Path(
            filename
        ).stem

        npz_path = (
            self.catalog_dir
            / f"{stem}_coordinates.npz"
        )

        json_path = (
            self.catalog_dir
            / f"{stem}_coordinates.json"
        )

        return (
            npz_path,
            json_path,
        )

    # =========================================================================
    # OPeNDAP COORDINATE DOWNLOAD
    # =========================================================================

    @staticmethod
    def _fetch_coordinate(
        client: httpx.Client,
        dataset_url: str,
        variable: str,
        count: int,
    ):
        from urllib.parse import quote

        import re
        import numpy as np

        constraint = (
            f"{variable}[0:1:{count - 1}]"
        )

        url = (
            f"{dataset_url}.ascii?"
            f"{quote(constraint, safe='')}"
        )

        response = client.get(
            url
        )

        if response.status_code != 200:
            raise RuntimeError(
                "INCOIS HYCOM coordinate request failed.\n"
                f"HTTP: {response.status_code}\n"
                f"URL: {url}\n"
                f"Response:\n"
                f"{response.text[:3000]}"
            )

        marker = f"{variable}["
        lines = response.text.splitlines()

        marker_index = None

        for index, line in enumerate(
            lines
        ):
            if line.strip().startswith(
                marker
            ):
                marker_index = index
                break

        if marker_index is None:
            raise RuntimeError(
                f"Could not find OPeNDAP marker "
                f"for {variable}."
            )

        pattern = re.compile(
            r"""
            [-+]?
            (?:
                \d+(?:\.\d*)?
                |
                \.\d+
            )
            (?:
                [eE][-+]?\d+
            )?
            """,
            re.VERBOSE,
        )

        values = []

        for line in lines[
            marker_index + 1:
        ]:

            stripped = line.strip()

            if not stripped:
                continue

            for item in stripped.split(","):

                item = item.strip()

                match = pattern.fullmatch(
                    item
                )

                if match is not None:

                    values.append(
                        float(
                            match.group()
                        )
                    )

                    if len(values) >= count:
                        break

            if len(values) >= count:
                break

        if len(values) != count:
            raise RuntimeError(
                f"{variable} coordinate count mismatch.\n"
                f"Expected: {count}\n"
                f"Received: {len(values)}"
            )

        return np.asarray(
            values,
            dtype=(
                np.float64
                if variable == "TIME"
                else np.float32
            ),
        )

    # =========================================================================
    # ENSURE COORDINATE CATALOG
    # =========================================================================

    def ensure_coordinate_catalog(
        self,
        discovery: dict[str, Any],
    ) -> dict[str, Any]:

        selected = discovery.get(
            "selected"
        )

        if not isinstance(
            selected,
            dict,
        ):
            raise RuntimeError(
                "No selected HYCOM dataset was returned."
            )

        filename = str(
            selected["filename"]
        )

        dataset_url = str(
            selected.get(
                "dataset_url"
            )
            or self._dataset_url(
                filename
            )
        )

        npz_path, json_path = (
            self._catalog_paths(
                filename
            )
        )

        if (
            npz_path.exists()
            and json_path.exists()
        ):

            return {
                "available": True,
                "dataset_file": filename,
                "dataset_url": dataset_url,
                "coordinate_file": str(
                    npz_path
                ),
                "metadata_file": str(
                    json_path
                ),
                "created": False,
            }

        expected_sizes = {
            "LAT": 1384,
            "LON": 1665,
            "DEPTH": 6,
            "TIME": int(
                selected.get(
                    "time_count",
                    28,
                )
            ),
        }

        with self._build_client() as client:

            lat = self._fetch_coordinate(
                client,
                dataset_url,
                "LAT",
                expected_sizes["LAT"],
            )

            lon = self._fetch_coordinate(
                client,
                dataset_url,
                "LON",
                expected_sizes["LON"],
            )

            depth = self._fetch_coordinate(
                client,
                dataset_url,
                "DEPTH",
                expected_sizes["DEPTH"],
            )

            time_numeric = self._fetch_coordinate(
                client,
                dataset_url,
                "TIME",
                expected_sizes["TIME"],
            )

        epoch = datetime(
            1900,
            12,
            31,
            tzinfo=timezone.utc,
        )

        time_iso = []

        for value in time_numeric:

            converted = (
                epoch
                + timedelta(
                    days=float(value)
                )
            )

            time_iso.append(
                converted
                .replace(
                    microsecond=0
                )
                .isoformat()
                .replace(
                    "+00:00",
                    "Z",
                )
            )

        import numpy as np

        np.savez_compressed(
            npz_path,
            LAT=lat,
            LON=lon,
            DEPTH=depth,
            TIME=time_numeric,
        )

        metadata = {
            "provider": "INCOIS",
            "service": "THREDDS OPeNDAP",
            "dataset_file": filename,
            "dataset_url": dataset_url,
            "created_at_utc": (
                datetime.now(
                    timezone.utc
                )
                .replace(
                    microsecond=0
                )
                .isoformat()
                .replace(
                    "+00:00",
                    "Z",
                )
            ),
            "dimensions": {
                "LAT": int(
                    len(lat)
                ),
                "LON": int(
                    len(lon)
                ),
                "DEPTH": int(
                    len(depth)
                ),
                "TIME": int(
                    len(time_numeric)
                ),
            },
            "coordinates": {
                "latitude": {
                    "units": "degrees_north",
                    "minimum": float(
                        np.min(lat)
                    ),
                    "maximum": float(
                        np.max(lat)
                    ),
                },
                "longitude": {
                    "units": "degrees_east",
                    "minimum": float(
                        np.min(lon)
                    ),
                    "maximum": float(
                        np.max(lon)
                    ),
                },
                "depth": {
                    "units": "m",
                    "positive": "down",
                    "values": [
                        float(value)
                        for value in depth
                    ],
                },
                "time": {
                    "units": (
                        "days since 1900-12-31"
                    ),
                    "calendar": "standard",
                    "minimum_numeric": float(
                        np.min(
                            time_numeric
                        )
                    ),
                    "maximum_numeric": float(
                        np.max(
                            time_numeric
                        )
                    ),
                    "iso_values": time_iso,
                },
            },
            "storage": {
                "coordinate_file": str(
                    npz_path
                ),
                "metadata_file": str(
                    json_path
                ),
                "full_netcdf_downloaded": False,
            },
            "synthetic_data": False,
            "interpolation": False,
        }

        json_path.write_text(
            json.dumps(
                metadata,
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        return {
            "available": True,
            "dataset_file": filename,
            "dataset_url": dataset_url,
            "coordinate_file": str(
                npz_path
            ),
            "metadata_file": str(
                json_path
            ),
            "created": True,
        }

    # =========================================================================
    # CHECK WHETHER REQUIRED CHUNKS EXIST
    # =========================================================================

    @staticmethod
    def _missing_plans(
        plans,
        force: bool = False,
    ):
        missing = []

        for plan in plans:

            chunk_path, provenance_path = (
                existing_chunk_paths(
                    plan
                )
            )

            if (
                force
                or not chunk_path.exists()
                or not provenance_path.exists()
            ):
                missing.append(
                    plan
                )

        return missing

    # =========================================================================
    # ENSURE HYCOM CHUNK
    # =========================================================================

    def ensure_hycom_chunk(
        self,
        latitude: float,
        longitude: float,
        time_utc: str,
        radius_degrees: float = 0.25,
        force: bool = False,
    ) -> dict[str, Any]:
        """
        Ensure real HYCOM chunk coverage for one requested point.
        """

        prepared = self.prepare_for_time(
            time_utc
        )

        if not prepared.get(
            "available",
            False,
        ):

            return {
                "available": False,
                "reason": (
                    "No INCOIS HYCOM dataset "
                    "covers the requested time."
                ),
                "prepared": prepared,
            }

        discovery = prepared[
            "discovery"
        ]

        catalog = prepared[
            "catalog"
        ]

        dataset_file = catalog[
            "dataset_file"
        ]

        dataset_url = catalog[
            "dataset_url"
        ]

        coordinate_file = Path(
            catalog[
                "coordinate_file"
            ]
        )

        planner = HycomChunkPlanner(
            coordinate_file=coordinate_file
        )

        plans = planner.plan_point(
            latitude=float(
                latitude
            ),
            longitude=float(
                longitude
            ),
            time_utc=time_utc,
            radius_degrees=float(
                radius_degrees
            ),
        )

        missing_plans = (
            self._missing_plans(
                plans,
                force=force,
            )
        )

        downloaded = []

        skipped = []

        timeout = httpx.Timeout(
            connect=30.0,
            read=180.0,
            write=60.0,
            pool=30.0,
        )

        truststore.inject_into_ssl()

        with httpx.Client(
            verify=True,
            timeout=timeout,
            follow_redirects=True,
            headers={
                "User-Agent":
                    "OceanSight-V/1.0"
            },
        ) as client:

            for plan in plans:

                chunk_path, provenance_path = (
                    existing_chunk_paths(
                        plan
                    )
                )

                if (
                    not force
                    and chunk_path.exists()
                    and provenance_path.exists()
                ):

                    skipped.append(
                        {
                            "chunk": str(
                                chunk_path
                            ),
                            "provenance": str(
                                provenance_path
                            ),
                        }
                    )

                    continue

                saved_chunk, saved_provenance = (
                    download_plan(
                        plan=plan,
                        client=client,
                        planner=planner,
                        dataset_file=dataset_file,
                        dataset_url=dataset_url,
                    )
                )

                downloaded.append(
                    {
                        "chunk": str(
                            saved_chunk
                        ),
                        "provenance": str(
                            saved_provenance
                        ),
                    }
                )

        # Rebuild the index after acquisition.
        index = HycomChunkIndex()

        index.write_index()

        return {
            "available": True,
            "requested": {
                "latitude": float(
                    latitude
                ),
                "longitude": float(
                    longitude
                ),
                "time_utc": time_utc,
                "radius_degrees": float(
                    radius_degrees
                ),
            },
            "dataset": {
                "file": dataset_file,
                "url": dataset_url,
            },
            "coordinate_catalog": catalog,
            "planned_chunks": len(
                plans
            ),
            "downloaded": downloaded,
            "skipped_existing": skipped,
            "index_path": str(
                HYCOM_INDEX_PATH
            ),
            "synthetic_data": False,
            "interpolation": False,
            "full_netcdf_downloaded": False,
            "discovery": discovery,
        }


# =============================================================================
# COMMAND LINE
# =============================================================================

def main() -> None:

    import argparse

    parser = argparse.ArgumentParser(
        description=(
            "Automatically discover and acquire "
            "real INCOIS HYCOM data for a point."
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
        "--time-utc",
        required=True,
    )

    parser.add_argument(
        "--radius-degrees",
        type=float,
        default=0.25,
    )

    parser.add_argument(
        "--force",
        action="store_true",
    )

    args = parser.parse_args()

    manager = HycomLiveManager()

    result = manager.ensure_hycom_chunk(
        latitude=args.latitude,
        longitude=args.longitude,
        time_utc=args.time_utc,
        radius_degrees=args.radius_degrees,
        force=args.force,
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

