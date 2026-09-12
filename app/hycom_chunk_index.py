
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np


# =============================================================================
# OCEANSIGHT-V
# HYCOM CHUNK INDEX
#
# The index must never return a chunk whose source time does not match the
# requested time.
#
# Spatial coverage alone is NOT sufficient.
#
# No synthetic data.
# No interpolation.
# =============================================================================


PROJECT_ROOT = (
    Path(__file__).resolve().parent.parent
)

CHUNK_DIR = (
    PROJECT_ROOT
    / "processed"
    / "hycom_chunks"
)

PROVENANCE_DIR = (
    PROJECT_ROOT
    / "processed"
    / "hycom_chunk_provenance"
)

INDEX_PATH = (
    PROJECT_ROOT
    / "processed"
    / "hycom_chunk_index.json"
)


# =============================================================================
# DEFAULT SOURCE
# =============================================================================

DEFAULT_DATASET_FILE = (
    "RSMC_hycom_20260911.nc"
)

DEFAULT_DATASET_URL = (
    "https://incois.gov.in/thredds/dodsC/"
    "osf/currents2/"
    + DEFAULT_DATASET_FILE
)


# =============================================================================
# INDEX RECORD
# =============================================================================

@dataclass(frozen=True)
class HycomChunkRecord:

    chunk_file: str

    chunk_path: str

    dataset_file: str

    dataset_url: str

    source: str

    source_time_utc: str

    latitude_min: float
    latitude_max: float

    longitude_min: float
    longitude_max: float

    depth_min_m: float
    depth_max_m: float

    time_index: int

    depth_start: int
    depth_count: int

    lat_start: int
    lat_count: int

    lon_start: int
    lon_count: int

    provenance_path: str | None


# =============================================================================
# HELPERS
# =============================================================================

def _safe_float(
    value: Any,
) -> float | None:

    try:

        result = float(
            value
        )

        if not math.isfinite(
            result
        ):
            return None

        return result

    except (
        TypeError,
        ValueError,
    ):

        return None


def _safe_int(
    value: Any,
) -> int | None:

    try:
        return int(
            value
        )

    except (
        TypeError,
        ValueError,
    ):

        return None


def _read_json(
    path: Path,
) -> dict[str, Any]:

    try:

        with path.open(
            "r",
            encoding="utf-8",
        ) as handle:

            value = json.load(
                handle
            )

        if isinstance(
            value,
            dict,
        ):

            return value

    except Exception:

        pass

    return {}


def _source_time_from_npz(
    arrays: Any,
) -> str:

    if "time_iso" not in arrays.files:

        raise RuntimeError(
            "HYCOM chunk does not contain "
            "'time_iso'."
        )

    values = np.asarray(
        arrays["time_iso"]
    ).reshape(-1)

    if values.size == 0:

        raise RuntimeError(
            "HYCOM chunk contains an empty "
            "'time_iso' array."
        )

    value = values[0]

    if isinstance(
        value,
        bytes,
    ):

        return value.decode(
            "utf-8",
            errors="replace",
        )

    return str(
        value
    )


# =============================================================================
# CLASS
# =============================================================================

class HycomChunkIndex:

    def __init__(
        self,
        chunk_dir: Path = CHUNK_DIR,
    ) -> None:

        self.chunk_dir = Path(
            chunk_dir
        )

        self.provenance_dir = (
            self.chunk_dir.parent
            / "hycom_chunk_provenance"
        )

        self.index_path = (
            self.chunk_dir.parent
            / "hycom_chunk_index.json"
        )

        self.records = (
            self._build_records()
        )

    # =========================================================================
    # BUILD RECORDS
    # =========================================================================

    def _build_records(
        self,
    ) -> list[HycomChunkRecord]:

        if not self.chunk_dir.exists():

            return []

        records: list[
            HycomChunkRecord
        ] = []

        for chunk_path in sorted(
            self.chunk_dir.glob(
                "*.npz"
            )
        ):

            try:

                record = (
                    self._inspect_chunk(
                        chunk_path
                    )
                )

                records.append(
                    record
                )

            except Exception as exc:

                print(
                    f"WARNING: Could not inspect "
                    f"{chunk_path.name}: {exc}"
                )

        return records

    # =========================================================================
    # INSPECT ONE CHUNK
    # =========================================================================

    def _inspect_chunk(
        self,
        chunk_path: Path,
    ) -> HycomChunkRecord:

        provenance_path = (
            self.provenance_dir
            / (
                chunk_path.stem
                + ".json"
            )
        )

        metadata = {}

        if provenance_path.exists():

            metadata = _read_json(
                provenance_path
            )

        with np.load(
            chunk_path,
            allow_pickle=False,
        ) as arrays:

            required = (
                "lat",
                "lon",
                "depth",
                "time_iso",
            )

            missing = [
                name
                for name in required
                if name not in arrays.files
            ]

            if missing:

                raise RuntimeError(
                    "Missing required arrays: "
                    + ", ".join(
                        missing
                    )
                )

            lat = np.asarray(
                arrays["lat"],
                dtype=np.float64,
            )

            lon = np.asarray(
                arrays["lon"],
                dtype=np.float64,
            )

            depth = np.asarray(
                arrays["depth"],
                dtype=np.float64,
            )

            source_time = (
                _source_time_from_npz(
                    arrays
                )
            )

            if lat.size == 0:

                raise RuntimeError(
                    "Empty latitude array."
                )

            if lon.size == 0:

                raise RuntimeError(
                    "Empty longitude array."
                )

            if depth.size == 0:

                raise RuntimeError(
                    "Empty depth array."
                )

            # -----------------------------------------------------------------
            # Provenance
            # -----------------------------------------------------------------

            dataset_file = (
                metadata.get(
                    "dataset_file"
                )
                or DEFAULT_DATASET_FILE
            )

            dataset_url = (
                metadata.get(
                    "dataset_url"
                )
                or DEFAULT_DATASET_URL
            )

            source = (
                metadata.get(
                    "provider"
                )
                or metadata.get(
                    "source"
                )
                or "INCOIS"
            )

            request_metadata = metadata.get(
                "request",
                {},
            )

            if not isinstance(
                request_metadata,
                dict,
            ):

                request_metadata = {}

            # -----------------------------------------------------------------
            # IMPORTANT:
            #
            # The downloader saves ChunkPlan through "request".
            # Read time/space indexes from there.
            # -----------------------------------------------------------------

            time_index = (
                _safe_int(
                    request_metadata.get(
                        "time_index"
                    )
                )
            )

            if time_index is None:

                time_index = 0

            depth_start = (
                _safe_int(
                    request_metadata.get(
                        "depth_start"
                    )
                )
            )

            if depth_start is None:

                depth_start = 0

            depth_count = (
                _safe_int(
                    request_metadata.get(
                        "depth_count"
                    )
                )
            )

            if depth_count is None:

                depth_count = int(
                    depth.size
                )

            lat_start = (
                _safe_int(
                    request_metadata.get(
                        "lat_start"
                    )
                )
            )

            if lat_start is None:

                lat_start = 0

            lat_count = (
                _safe_int(
                    request_metadata.get(
                        "lat_count"
                    )
                )
            )

            if lat_count is None:

                lat_count = int(
                    lat.size
                )

            lon_start = (
                _safe_int(
                    request_metadata.get(
                        "lon_start"
                    )
                )
            )

            if lon_start is None:

                lon_start = 0

            lon_count = (
                _safe_int(
                    request_metadata.get(
                        "lon_count"
                    )
                )
            )

            if lon_count is None:

                lon_count = int(
                    lon.size
                )

            return HycomChunkRecord(

                chunk_file=(
                    chunk_path.name
                ),

                chunk_path=str(
                    chunk_path
                ),

                dataset_file=str(
                    dataset_file
                ),

                dataset_url=str(
                    dataset_url
                ),

                source=str(
                    source
                ),

                source_time_utc=(
                    source_time
                ),

                latitude_min=float(
                    np.nanmin(lat)
                ),

                latitude_max=float(
                    np.nanmax(lat)
                ),

                longitude_min=float(
                    np.nanmin(lon)
                ),

                longitude_max=float(
                    np.nanmax(lon)
                ),

                depth_min_m=float(
                    np.nanmin(depth)
                ),

                depth_max_m=float(
                    np.nanmax(depth)
                ),

                time_index=int(
                    time_index
                ),

                depth_start=int(
                    depth_start
                ),

                depth_count=int(
                    depth_count
                ),

                lat_start=int(
                    lat_start
                ),

                lat_count=int(
                    lat_count
                ),

                lon_start=int(
                    lon_start
                ),

                lon_count=int(
                    lon_count
                ),

                provenance_path=(
                    str(
                        provenance_path
                    )
                    if provenance_path.exists()
                    else None
                ),
            )

    # =========================================================================
    # TIME PARSING
    # =========================================================================

    @staticmethod
    def _parse_time(
        value: str | None,
    ) -> datetime | None:

        if not value:

            return None

        text = str(
            value
        ).strip()

        if text.endswith(
            "Z"
        ):

            text = (
                text[:-1]
                + "+00:00"
            )

        try:

            parsed = datetime.fromisoformat(
                text
            )

            if parsed.tzinfo is None:

                parsed = parsed.replace(
                    tzinfo=timezone.utc
                )

            return parsed.astimezone(
                timezone.utc
            )

        except ValueError:

            return None

    # =========================================================================
    # TIME EQUALITY
    # =========================================================================

    @classmethod
    def _same_time(
        cls,
        left: str | None,
        right: str | None,
    ) -> bool:

        left_dt = cls._parse_time(
            left
        )

        right_dt = cls._parse_time(
            right
        )

        if (
            left_dt is None
            or right_dt is None
        ):

            return False

        return (
            left_dt == right_dt
        )

    # =========================================================================
    # SPATIAL DISTANCE
    # =========================================================================

    @staticmethod
    def _chunk_distance(
        chunk: HycomChunkRecord,
        latitude: float,
        longitude: float,
    ) -> float:

        if (
            chunk.latitude_min
            <= latitude
            <= chunk.latitude_max
        ):

            lat_distance = 0.0

        elif latitude < chunk.latitude_min:

            lat_distance = (
                chunk.latitude_min
                - latitude
            )

        else:

            lat_distance = (
                latitude
                - chunk.latitude_max
            )

        if (
            chunk.longitude_min
            <= longitude
            <= chunk.longitude_max
        ):

            lon_distance = 0.0

        elif longitude < chunk.longitude_min:

            lon_distance = (
                chunk.longitude_min
                - longitude
            )

        else:

            lon_distance = (
                longitude
                - chunk.longitude_max
            )

        return math.hypot(
            lat_distance,
            lon_distance,
        )

    # =========================================================================
    # FIND CANDIDATES
    # =========================================================================

    def find_candidates(
        self,
        latitude: float,
        longitude: float,
        requested_time: str | None = None,
        depth: float | None = None,
    ) -> list[HycomChunkRecord]:

        latitude = float(
            latitude
        )

        longitude = float(
            longitude
        )

        # Normalize longitude.
        while longitude > 180.0:

            longitude -= 360.0

        while longitude < -180.0:

            longitude += 360.0

        requested_datetime = (
            self._parse_time(
                requested_time
            )
        )

        scored: list[
            tuple[
                tuple[float, float],
                HycomChunkRecord,
            ]
        ] = []

        for chunk in self.records:

            # -------------------------------------------------------------
            # LOCATION MUST BE INSIDE THE CHUNK
            # -------------------------------------------------------------

            spatial_distance = (
                self._chunk_distance(
                    chunk,
                    latitude,
                    longitude,
                )
            )

            if spatial_distance != 0.0:

                continue

            # -------------------------------------------------------------
            # TIME MUST MATCH EXACTLY
            #
            # This is the critical scientific correction.
            #
            # A chunk containing the requested location but belonging to
            # a different HYCOM model time must NEVER be returned.
            # -------------------------------------------------------------

            if requested_datetime is not None:

                if not self._same_time(
                    chunk.source_time_utc,
                    requested_time,
                ):

                    continue

            # -------------------------------------------------------------
            # DEPTH
            # -------------------------------------------------------------

            depth_distance = 0.0

            if depth is not None:

                requested_depth = float(
                    depth
                )

                if not (
                    chunk.depth_min_m
                    <= requested_depth
                    <= chunk.depth_max_m
                ):

                    continue

            scored.append(
                (
                    (
                        depth_distance,
                        spatial_distance,
                    ),
                    chunk,
                )
            )

        scored.sort(
            key=lambda item: item[0]
        )

        return [
            record
            for _, record in scored
        ]

    # =========================================================================
    # SAVE INDEX
    # =========================================================================

    def write_index(
        self,
    ) -> None:

        self.index_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        # Determine which datasets are represented.
        dataset_files = sorted(
            {
                record.dataset_file
                for record in self.records
            }
        )

        if len(dataset_files) == 1:

            index_dataset = (
                dataset_files[0]
            )

        elif dataset_files:

            index_dataset = (
                "RSMC HYCOM "
                "(multiple datasets)"
            )

        else:

            index_dataset = (
                "RSMC HYCOM"
            )

        dataset_urls = sorted(
            {
                record.dataset_url
                for record in self.records
            }
        )

        if len(dataset_urls) == 1:

            index_dataset_url = (
                dataset_urls[0]
            )

        else:

            index_dataset_url = None

        payload = {
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

            "source": "INCOIS",

            "dataset": index_dataset,

            "dataset_url": (
                index_dataset_url
            ),

            "dataset_files": dataset_files,

            "dataset_urls": dataset_urls,

            "chunk_count": len(
                self.records
            ),

            "chunks": [
                {
                    "chunk_file": (
                        record.chunk_file
                    ),

                    "chunk_path": (
                        record.chunk_path
                    ),

                    "dataset_file": (
                        record.dataset_file
                    ),

                    "dataset_url": (
                        record.dataset_url
                    ),

                    "source": (
                        record.source
                    ),

                    "source_time_utc": (
                        record.source_time_utc
                    ),

                    "latitude_min": (
                        record.latitude_min
                    ),

                    "latitude_max": (
                        record.latitude_max
                    ),

                    "longitude_min": (
                        record.longitude_min
                    ),

                    "longitude_max": (
                        record.longitude_max
                    ),

                    "depth_min_m": (
                        record.depth_min_m
                    ),

                    "depth_max_m": (
                        record.depth_max_m
                    ),

                    "time_index": (
                        record.time_index
                    ),

                    "depth_start": (
                        record.depth_start
                    ),

                    "depth_count": (
                        record.depth_count
                    ),

                    "lat_start": (
                        record.lat_start
                    ),

                    "lat_count": (
                        record.lat_count
                    ),

                    "lon_start": (
                        record.lon_start
                    ),

                    "lon_count": (
                        record.lon_count
                    ),

                    "provenance_path": (
                        record.provenance_path
                    ),

                    "synthetic_data": False,

                    "interpolation": False,
                }
                for record in self.records
            ],
        }

        self.index_path.write_text(
            json.dumps(
                payload,
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )


# =============================================================================
# COMMAND LINE
# =============================================================================

def main() -> None:

    print(
        "=" * 80
    )

    print(
        "OCEANSIGHT-V"
    )

    print(
        "HYCOM CHUNK INDEX"
    )

    print(
        "=" * 80
    )

    index = HycomChunkIndex()

    print()

    if not index.records:

        print(
            "No valid HYCOM chunks found."
        )

    else:

        for record in index.records:

            print()

            print(
                f"Chunk: {record.chunk_file}"
            )

            print(
                f"Source: {record.source}"
            )

            print(
                f"Dataset: {record.dataset_file}"
            )

            print(
                f"Time: {record.source_time_utc}"
            )

            print(
                f"Depth: "
                f"{record.depth_min_m} "
                f"to "
                f"{record.depth_max_m} m"
            )

            print(
                f"Latitude: "
                f"{record.latitude_min} "
                f"to "
                f"{record.latitude_max}"
            )

            print(
                f"Longitude: "
                f"{record.longitude_min} "
                f"to "
                f"{record.longitude_max}"
            )

            print(
                "Provenance:",
                (
                    "yes"
                    if record.provenance_path
                    else "no"
                ),
            )

    index.write_index()

    print()

    print(
        "-" * 80
    )

    print(
        f"Indexed chunks: "
        f"{len(index.records)}"
    )

    print()

    print(
        "Index saved:"
    )

    print(
        index.index_path
    )

    print()

    print(
        "=" * 80
    )

    print(
        "HYCOM CHUNK INDEX COMPLETE"
    )

    print(
        "=" * 80
    )


if __name__ == "__main__":
    main()

