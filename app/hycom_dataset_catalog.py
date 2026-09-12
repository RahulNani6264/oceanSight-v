
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

import httpx
import numpy as np
import truststore


# =============================================================================
# OCEANSIGHT-V
# INCOIS HYCOM DATASET COORDINATE CATALOG
#
# Downloads ONLY the coordinate vectors:
#
#   LAT   -> 1384 values
#   LON   -> 1665 values
#   DEPTH -> 6 values
#   TIME  -> 28 values
#
# This is tiny compared with the ~10 GiB NetCDF file.
#
# The vectors are necessary so the planner can convert:
#
#   latitude / longitude / requested time
#
# into actual INCOIS array indices.
# =============================================================================


PROJECT_ROOT = (
    Path(__file__).resolve().parent.parent
)

PROCESSED_DIR = (
    PROJECT_ROOT / "processed"
)

CATALOG_DIR = (
    PROCESSED_DIR / "hycom_catalog"
)

CATALOG_DIR.mkdir(
    parents=True,
    exist_ok=True,
)


FILE_NAME = (
    "RSMC_hycom_20260911.nc"
)

DATASET_URL = (
    "https://incois.gov.in/thredds/dodsC/"
    "osf/currents2/"
    + FILE_NAME
)


EXPECTED_SIZES = {
    "LAT": 1384,
    "LON": 1665,
    "DEPTH": 6,
    "TIME": 28,
}


FLOAT_PATTERN = re.compile(
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


def utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def build_url(
    variable: str,
) -> str:

    constraint = (
        f"{variable}[0:1:"
        f"{EXPECTED_SIZES[variable] - 1}]"
    )

    encoded = quote(
        constraint,
        safe="",
    )

    return (
        f"{DATASET_URL}.ascii?"
        f"{encoded}"
    )


def extract_values(
    text: str,
    variable: str,
) -> np.ndarray:

    marker = (
        f"{variable}["
    )

    lines = text.splitlines()

    marker_index = None

    for index, line in enumerate(lines):

        if line.strip().startswith(
            marker
        ):
            marker_index = index
            break

    if marker_index is None:

        raise ValueError(
            f"Could not find {variable} data marker."
        )

    values: list[float] = []

    for line in lines[
        marker_index + 1:
    ]:

        stripped = line.strip()

        if not stripped:
            continue

        if (
            ".TIME[" in stripped
            or ".DEPTH[" in stripped
            or ".LAT[" in stripped
            or ".LON[" in stripped
        ):
            break

        parts = [
            item.strip()
            for item in stripped.split(",")
        ]

        for item in parts:

            match = (
                FLOAT_PATTERN.fullmatch(
                    item
                )
            )

            if match is None:
                continue

            values.append(
                float(
                    match.group()
                )
            )

            if (
                len(values)
                >= EXPECTED_SIZES[
                    variable
                ]
            ):
                break

        if (
            len(values)
            >= EXPECTED_SIZES[
                variable
            ]
        ):
            break

    expected = EXPECTED_SIZES[
        variable
    ]

    if len(values) != expected:

        raise ValueError(
            f"{variable}: expected "
            f"{expected} values, received "
            f"{len(values)}"
        )

    return np.asarray(
        values,
        dtype=(
            np.float64
            if variable == "TIME"
            else np.float32
        ),
    )


def time_to_iso(
    days: float,
) -> str:

    origin = datetime(
        1900,
        12,
        31,
        tzinfo=timezone.utc,
    )

    value = (
        origin
        + timedelta(
            days=float(days)
        )
    )

    return (
        value
        .replace(
            microsecond=0
        )
        .isoformat()
        .replace(
            "+00:00",
            "Z",
        )
    )


def fetch_vector(
    client: httpx.Client,
    variable: str,
) -> np.ndarray:

    url = build_url(
        variable
    )

    print()
    print(
        f"REQUEST: {variable}"
    )

    print(
        "URL:",
        url,
    )

    response = client.get(
        url
    )

    print(
        "HTTP:",
        response.status_code,
    )

    if response.status_code != 200:

        print(
            response.text[:4000]
        )

        raise RuntimeError(
            f"Failed to retrieve {variable}"
        )

    return extract_values(
        response.text,
        variable,
    )


def main() -> None:

    truststore.inject_into_ssl()

    print("=" * 80)
    print(
        "OCEANSIGHT-V"
    )
    print(
        "INCOIS HYCOM DATASET CATALOG"
    )
    print("=" * 80)

    print()
    print(
        "Dataset:",
        FILE_NAME,
    )

    print()
    print(
        "Full NetCDF download:"
    )

    print(
        "NOT USED"
    )

    timeout = httpx.Timeout(
        connect=30.0,
        read=120.0,
        write=60.0,
        pool=30.0,
    )

    with httpx.Client(
        verify=True,
        timeout=timeout,
        follow_redirects=True,
        headers={
            "User-Agent":
                "OceanSight-V/1.0"
        },
    ) as client:

        lat = fetch_vector(
            client,
            "LAT",
        )

        lon = fetch_vector(
            client,
            "LON",
        )

        depth = fetch_vector(
            client,
            "DEPTH",
        )

        time_numeric = fetch_vector(
            client,
            "TIME",
        )

    time_iso = [
        time_to_iso(
            value
        )
        for value in time_numeric
    ]

    output_npz = (
        CATALOG_DIR
        / "hycom_coordinates.npz"
    )

    np.savez_compressed(
        output_npz,
        LAT=lat,
        LON=lon,
        DEPTH=depth,
        TIME=time_numeric,
    )

    metadata = {
        "provider": "INCOIS",
        "service": "THREDDS OPeNDAP",
        "dataset_file": FILE_NAME,
        "dataset_url": DATASET_URL,
        "created_at_utc": utc_now(),

        "dimensions": {
            "LAT": int(len(lat)),
            "LON": int(len(lon)),
            "DEPTH": int(len(depth)),
            "TIME": int(len(time_numeric)),
        },

        "coordinates": {
            "latitude": {
                "units": "degrees_north",
                "minimum": float(lat.min()),
                "maximum": float(lat.max()),
            },

            "longitude": {
                "units": "degrees_east",
                "minimum": float(lon.min()),
                "maximum": float(lon.max()),
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
                    time_numeric.min()
                ),
                "maximum_numeric": float(
                    time_numeric.max()
                ),
                "iso_values": time_iso,
            },
        },

        "storage": {
            "coordinate_file": (
                str(output_npz)
            ),
            "full_netcdf_downloaded": False,
        },
    }

    metadata_path = (
        CATALOG_DIR
        / "hycom_coordinates.json"
    )

    metadata_path.write_text(
        json.dumps(
            metadata,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print()
    print("=" * 80)
    print(
        "CATALOG CREATED"
    )
    print("=" * 80)

    print()
    print(
        "LAT count:",
        len(lat),
    )

    print(
        "LON count:",
        len(lon),
    )

    print(
        "DEPTH:",
        depth.tolist(),
    )

    print(
        "TIME count:",
        len(time_numeric),
    )

    print()
    print(
        "First time:",
        time_iso[0],
    )

    print(
        "Last time:",
        time_iso[-1],
    )

    print()
    print(
        "Coordinate NPZ:",
        output_npz,
    )

    print(
        "Metadata JSON:",
        metadata_path,
    )

    print()
    print(
        "Full NetCDF downloaded:",
        False,
    )

    print()
    print("=" * 80)
    print(
        "HYCOM DATASET CATALOG COMPLETE"
    )
    print("=" * 80)


if __name__ == "__main__":
    main()

