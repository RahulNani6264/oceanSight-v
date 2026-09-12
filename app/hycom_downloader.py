
from __future__ import annotations

"""Download planner-generated HYCOM chunks from the INCOIS OPeNDAP service."""

import argparse
import json
import re
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

import httpx
import numpy as np
import truststore

from app.hycom_chunk_planner import (
    ChunkPlan,
    HycomChunkPlanner,
)


# =============================================================================
# PATHS
# =============================================================================

PROJECT_ROOT = (
    Path(__file__).resolve().parent.parent
)

PROCESSED_DIR = (
    PROJECT_ROOT / "processed"
)

CHUNK_DIR = (
    PROCESSED_DIR / "hycom_chunks"
)

PROVENANCE_DIR = (
    PROCESSED_DIR / "hycom_chunk_provenance"
)

CHUNK_DIR.mkdir(
    parents=True,
    exist_ok=True,
)

PROVENANCE_DIR.mkdir(
    parents=True,
    exist_ok=True,
)


# =============================================================================
# DEFAULT INCOIS DATASET
#
# Existing CLI behaviour remains unchanged when no dataset is supplied.
# The live manager can override these values.
# =============================================================================

FILE_NAME = (
    "RSMC_hycom_20260911.nc"
)

DATASET_URL = (
    "https://incois.gov.in/thredds/dodsC/"
    "osf/currents2/"
    + FILE_NAME
)


# =============================================================================
# VERIFIED SOURCE FILL VALUES
# =============================================================================

FILL_VALUES = {
    "TEMP": -1.0e34,
    "SALN": -1.0e34,
    "UVEL": 1.2676506e30,
    "VVEL": 1.2676506e30,
    "SSH": 1.2676506e30,
}


# =============================================================================
# NUMBER PARSER
# =============================================================================

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


# =============================================================================
# TIME
# =============================================================================

def utc_now() -> str:
    return (
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
    )


def numeric_time_to_iso(
    numeric_time: float,
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
            days=float(
                numeric_time
            )
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


# =============================================================================
# URL
# =============================================================================

def build_url(
    variable: str,
    expression: str,
    dataset_url: str | None = None,
) -> str:
    """
    Build an INCOIS OPeNDAP ASCII URL.

    When dataset_url is provided, that selected HYCOM dataset
    is used. Otherwise the existing default dataset is used.
    """

    base_url = (
        dataset_url
        if dataset_url is not None
        else DATASET_URL
    )

    constraint = (
        f"{variable}{expression}"
    )

    encoded = quote(
        constraint,
        safe="",
    )

    return (
        f"{base_url}.ascii?"
        f"{encoded}"
    )


# =============================================================================
# OPeNDAP RESPONSE PARSER
# =============================================================================

def extract_values(
    text: str,
    marker: str,
    expected_count: int,
) -> np.ndarray:
    """Parse INCOIS OPeNDAP .ascii responses."""

    lines = text.splitlines()

    marker_index: int | None = None

    for index, line in enumerate(lines):

        if line.strip().startswith(
            marker
        ):
            marker_index = index
            break

    if marker_index is None:
        raise ValueError(
            "OPeNDAP marker not found:\n"
            f"{marker}"
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

        if stripped.startswith("["):
            parts = [
                item.strip()
                for item in stripped.split(",")
            ]

            # Remove multidimensional index prefix.
            parts = parts[1:]

        else:
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

            if len(values) >= expected_count:
                break

        if len(values) >= expected_count:
            break

    if len(values) != expected_count:
        raise ValueError(
            "OPeNDAP value count mismatch.\n"
            f"Marker: {marker}\n"
            f"Expected: {expected_count}\n"
            f"Received: {len(values)}"
        )

    return np.asarray(
        values,
        dtype=np.float32,
    )


# =============================================================================
# REQUEST
# =============================================================================

def fetch(
    client: httpx.Client,
    variable: str,
    expression: str,
    marker: str,
    expected_count: int,
    dataset_url: str | None = None,
) -> np.ndarray:
    """
    Request one real HYCOM field from the selected dataset.
    """

    url = build_url(
        variable=variable,
        expression=expression,
        dataset_url=dataset_url,
    )

    active_dataset_url = (
        dataset_url
        if dataset_url is not None
        else DATASET_URL
    )

    print()
    print(
        f"REQUEST: {variable}"
    )

    print(
        "Constraint:",
        f"{variable}{expression}",
    )

    print(
        "Dataset:",
        active_dataset_url,
    )

    response = client.get(
        url
    )

    print(
        "HTTP:",
        response.status_code,
    )

    if response.status_code != 200:

        print()
        print(
            "INCOIS RESPONSE"
        )

        print(
            "-" * 80
        )

        print(
            response.text[:5000]
        )

        raise RuntimeError(
            "INCOIS OPeNDAP request failed "
            f"for {variable}"
        )

    return extract_values(
        response.text,
        marker,
        expected_count,
    )


# =============================================================================
# MISSING VALUES
# =============================================================================

def clean_field(
    values: np.ndarray,
    variable: str,
) -> tuple[
    np.ndarray,
    np.ndarray,
]:
    """
    Convert source fill values to:

        NaN
        boolean missing mask

    Missing data is never replaced by zero.
    """

    array = np.asarray(
        values,
        dtype=np.float32,
    ).copy()

    missing = (
        ~np.isfinite(
            array
        )
    )

    fill = FILL_VALUES.get(
        variable
    )

    if fill is not None:

        missing |= (
            array == fill
        )

    array[missing] = np.nan

    return (
        array,
        missing,
    )


# =============================================================================
# CHUNK NAME
# =============================================================================

def chunk_name(
    plan: ChunkPlan,
) -> str:

    return (
        f"hycom_t{plan.time_index:04d}_"
        f"y{plan.lat_start:04d}-"
        f"{plan.lat_start + plan.lat_count - 1:04d}_"
        f"x{plan.lon_start:04d}-"
        f"{plan.lon_start + plan.lon_count - 1:04d}.npz"
    )


# =============================================================================
# EXISTING CHUNK CHECK
# =============================================================================

def existing_chunk_paths(
    plan: ChunkPlan,
) -> tuple[Path, Path]:

    name = chunk_name(
        plan
    )

    chunk_path = (
        CHUNK_DIR / name
    )

    provenance_path = (
        PROVENANCE_DIR
        / f"{Path(name).stem}.json"
    )

    return (
        chunk_path,
        provenance_path,
    )


# =============================================================================
# SAVE
# =============================================================================

def save_chunk(
    plan: ChunkPlan,
    time_numeric: float,
    time_iso: str,
    depth: np.ndarray,
    lat: np.ndarray,
    lon: np.ndarray,
    temp: np.ndarray,
    saln: np.ndarray,
    uvel: np.ndarray,
    vvel: np.ndarray,
    ssh: np.ndarray,
    temp_missing: np.ndarray,
    saln_missing: np.ndarray,
    uvel_missing: np.ndarray,
    vvel_missing: np.ndarray,
    ssh_missing: np.ndarray,
    dataset_file: str | None = None,
    dataset_url: str | None = None,
) -> tuple[
    Path,
    Path,
]:

    actual_dataset_file = (
        dataset_file
        if dataset_file is not None
        else FILE_NAME
    )

    actual_dataset_url = (
        dataset_url
        if dataset_url is not None
        else DATASET_URL
    )

    chunk_name_value = (
        chunk_name(plan)
    )

    chunk_path = (
        CHUNK_DIR
        / chunk_name_value
    )

    np.savez_compressed(
        chunk_path,
        time_numeric=np.asarray(
            [time_numeric],
            dtype=np.float64,
        ),
        time_iso=np.asarray(
            [time_iso],
        ),
        depth=np.asarray(
            depth,
            dtype=np.float32,
        ),
        lat=np.asarray(
            lat,
            dtype=np.float32,
        ),
        lon=np.asarray(
            lon,
            dtype=np.float32,
        ),
        TEMP=temp,
        SALN=saln,
        UVEL=uvel,
        VVEL=vvel,
        SSH=ssh,
        TEMP_missing=temp_missing,
        SALN_missing=saln_missing,
        UVEL_missing=uvel_missing,
        VVEL_missing=vvel_missing,
        SSH_missing=ssh_missing,
    )

    provenance = {
        "project": "OceanSight-V",
        "provider": "INCOIS",
        "service": "THREDDS OPeNDAP",

        "dataset_file": actual_dataset_file,
        "dataset_url": actual_dataset_url,

        "created_at_utc": utc_now(),

        "request": asdict(
            plan
        ),

        "actual_coordinates": {
            "depth_m": [
                float(value)
                for value in depth
            ],
            "latitude": [
                float(value)
                for value in lat
            ],
            "longitude": [
                float(value)
                for value in lon
            ],
            "time_numeric": time_numeric,
            "time_iso": time_iso,
        },

        "dimensions": {
            "TEMP": [
                "time",
                "depth",
                "lat",
                "lon",
            ],
            "SALN": [
                "time",
                "depth",
                "lat",
                "lon",
            ],
            "UVEL": [
                "time",
                "depth",
                "lat",
                "lon",
            ],
            "VVEL": [
                "time",
                "depth",
                "lat",
                "lon",
            ],
            "SSH": [
                "time",
                "lat",
                "lon",
            ],
        },

        "variables": {
            "TEMP": {
                "units": "degree_Celsius",
                "fill_value": -1.0e34,
            },

            "SALN": {
                "fill_value": -1.0e34,
            },

            "UVEL": {
                "units": "m/s",
                "meaning": "eastward current",
                "fill_value": 1.2676506e30,
            },

            "VVEL": {
                "units": "m/s",
                "meaning": "northward current",
                "fill_value": 1.2676506e30,
            },

            "SSH": {
                "units": "m",
                "fill_value": 1.2676506e30,
            },
        },

        "missing_value_policy": (
            "INCOIS fill values are represented "
            "as NaN in scientific arrays and "
            "True in corresponding missing masks. "
            "Missing values are never converted to zero."
        ),

        "interpolation": False,
        "synthetic_data": False,
        "full_netcdf_downloaded": False,
    }

    provenance_path = (
        PROVENANCE_DIR
        / f"{Path(chunk_path.name).stem}.json"
    )

    provenance_path.write_text(
        json.dumps(
            provenance,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    return (
        chunk_path,
        provenance_path,
    )


# =============================================================================
# DOWNLOAD ONE CHUNK
# =============================================================================

def download_plan(
    plan: ChunkPlan,
    client: httpx.Client,
    planner: HycomChunkPlanner,
    dataset_file: str | None = None,
    dataset_url: str | None = None,
) -> tuple[
    Path,
    Path,
]:

    depth = planner.depth[
        plan.depth_start:
        plan.depth_start
        + plan.depth_count
    ]

    lat = planner.lat[
        plan.lat_start:
        plan.lat_start
        + plan.lat_count
    ]

    lon = planner.lon[
        plan.lon_start:
        plan.lon_start
        + plan.lon_count
    ]

    time_numeric = float(
        planner.time[
            plan.time_index
        ]
    )

    time_iso = (
        numeric_time_to_iso(
            time_numeric
        )
    )

    # -------------------------------------------------------------------------
    # 4D fields
    # -------------------------------------------------------------------------

    expression_4d = (
        f"[{plan.time_index}]"
        f"[{plan.depth_start}:1:"
        f"{plan.depth_start + plan.depth_count - 1}]"
        f"[{plan.lat_start}:1:"
        f"{plan.lat_start + plan.lat_count - 1}]"
        f"[{plan.lon_start}:1:"
        f"{plan.lon_start + plan.lon_count - 1}]"
    )

    expected_4d = (
        plan.depth_count
        * plan.lat_count
        * plan.lon_count
    )

    temp_raw = fetch(
        client=client,
        variable="TEMP",
        expression=expression_4d,
        marker=(
            f"TEMP.TEMP[1]"
            f"[{plan.depth_count}]"
            f"[{plan.lat_count}]"
            f"[{plan.lon_count}]"
        ),
        expected_count=expected_4d,
        dataset_url=dataset_url,
    )

    saln_raw = fetch(
        client=client,
        variable="SALN",
        expression=expression_4d,
        marker=(
            f"SALN.SALN[1]"
            f"[{plan.depth_count}]"
            f"[{plan.lat_count}]"
            f"[{plan.lon_count}]"
        ),
        expected_count=expected_4d,
        dataset_url=dataset_url,
    )

    uvel_raw = fetch(
        client=client,
        variable="UVEL",
        expression=expression_4d,
        marker=(
            f"UVEL.UVEL[1]"
            f"[{plan.depth_count}]"
            f"[{plan.lat_count}]"
            f"[{plan.lon_count}]"
        ),
        expected_count=expected_4d,
        dataset_url=dataset_url,
    )

    vvel_raw = fetch(
        client=client,
        variable="VVEL",
        expression=expression_4d,
        marker=(
            f"VVEL.VVEL[1]"
            f"[{plan.depth_count}]"
            f"[{plan.lat_count}]"
            f"[{plan.lon_count}]"
        ),
        expected_count=expected_4d,
        dataset_url=dataset_url,
    )

    # -------------------------------------------------------------------------
    # SSH
    # -------------------------------------------------------------------------

    expression_ssh = (
        f"[{plan.time_index}]"
        f"[{plan.lat_start}:1:"
        f"{plan.lat_start + plan.lat_count - 1}]"
        f"[{plan.lon_start}:1:"
        f"{plan.lon_start + plan.lon_count - 1}]"
    )

    expected_ssh = (
        plan.lat_count
        * plan.lon_count
    )

    ssh_raw = fetch(
        client=client,
        variable="SSH",
        expression=expression_ssh,
        marker=(
            f"SSH.SSH[1]"
            f"[{plan.lat_count}]"
            f"[{plan.lon_count}]"
        ),
        expected_count=expected_ssh,
        dataset_url=dataset_url,
    )

    # -------------------------------------------------------------------------
    # Reshape + clean
    # -------------------------------------------------------------------------

    temp, temp_missing = clean_field(
        temp_raw.reshape(
            (
                1,
                plan.depth_count,
                plan.lat_count,
                plan.lon_count,
            )
        ),
        "TEMP",
    )

    saln, saln_missing = clean_field(
        saln_raw.reshape(
            (
                1,
                plan.depth_count,
                plan.lat_count,
                plan.lon_count,
            )
        ),
        "SALN",
    )

    uvel, uvel_missing = clean_field(
        uvel_raw.reshape(
            (
                1,
                plan.depth_count,
                plan.lat_count,
                plan.lon_count,
            )
        ),
        "UVEL",
    )

    vvel, vvel_missing = clean_field(
        vvel_raw.reshape(
            (
                1,
                plan.depth_count,
                plan.lat_count,
                plan.lon_count,
            )
        ),
        "VVEL",
    )

    ssh, ssh_missing = clean_field(
        ssh_raw.reshape(
            (
                1,
                plan.lat_count,
                plan.lon_count,
            )
        ),
        "SSH",
    )

    return save_chunk(
        plan=plan,
        time_numeric=time_numeric,
        time_iso=time_iso,
        depth=depth,
        lat=lat,
        lon=lon,
        temp=temp,
        saln=saln,
        uvel=uvel,
        vvel=vvel,
        ssh=ssh,
        temp_missing=temp_missing,
        saln_missing=saln_missing,
        uvel_missing=uvel_missing,
        vvel_missing=vvel_missing,
        ssh_missing=ssh_missing,
        dataset_file=dataset_file,
        dataset_url=dataset_url,
    )


# =============================================================================
# ARGUMENT PARSER
# =============================================================================

def build_parser() -> argparse.ArgumentParser:

    parser = argparse.ArgumentParser(
        description=(
            "Download real INCOIS HYCOM chunks "
            "for a requested point or region."
        )
    )

    parser.add_argument(
        "--latitude",
        type=float,
        help="Requested point latitude.",
    )

    parser.add_argument(
        "--longitude",
        type=float,
        help="Requested point longitude.",
    )

    parser.add_argument(
        "--radius-degrees",
        type=float,
        default=0.25,
        help=(
            "Point request radius in degrees. "
            "Default: 0.25"
        ),
    )

    parser.add_argument(
        "--lat-min",
        type=float,
        help="Region minimum latitude.",
    )

    parser.add_argument(
        "--lat-max",
        type=float,
        help="Region maximum latitude.",
    )

    parser.add_argument(
        "--lon-min",
        type=float,
        help="Region minimum longitude.",
    )

    parser.add_argument(
        "--lon-max",
        type=float,
        help="Region maximum longitude.",
    )

    parser.add_argument(
        "--time-utc",
        default="2026-09-10T06:00:00Z",
        help=(
            "Requested UTC time. "
            "Default: 2026-09-10T06:00:00Z"
        ),
    )

    parser.add_argument(
        "--dataset-file",
        default=None,
        help=(
            "Specific INCOIS HYCOM dataset filename. "
            "When omitted, the existing default dataset is used."
        ),
    )

    parser.add_argument(
        "--dataset-url",
        default=None,
        help=(
            "Specific INCOIS HYCOM OPeNDAP dataset URL. "
            "When omitted, the existing default dataset is used."
        ),
    )

    parser.add_argument(
        "--coordinate-file",
        default=None,
        help=(
            "Dataset-specific HYCOM coordinate NPZ. "
            "When omitted, the existing default coordinate "
            "catalog is used."
        ),
    )

    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Download again even if the exact chunk "
            "and provenance already exist."
        ),
    )

    return parser


# =============================================================================
# PLAN REQUEST
# =============================================================================

def build_plans(
    planner: HycomChunkPlanner,
    args: argparse.Namespace,
) -> list[ChunkPlan]:

    region_values = (
        args.lat_min,
        args.lat_max,
        args.lon_min,
        args.lon_max,
    )

    any_region_argument = any(
        value is not None
        for value in region_values
    )

    all_region_arguments = all(
        value is not None
        for value in region_values
    )

    # -------------------------------------------------------------------------
    # REGION
    # -------------------------------------------------------------------------

    if any_region_argument:

        if not all_region_arguments:

            raise ValueError(
                "Region mode requires all four arguments:\n"
                "--lat-min --lat-max --lon-min --lon-max"
            )

        return planner.plan_region(
            lat_min=args.lat_min,
            lat_max=args.lat_max,
            lon_min=args.lon_min,
            lon_max=args.lon_max,
            time_utc=args.time_utc,
        )

    # -------------------------------------------------------------------------
    # POINT
    # -------------------------------------------------------------------------

    if (
        args.latitude is not None
        or args.longitude is not None
    ):

        if (
            args.latitude is None
            or args.longitude is None
        ):

            raise ValueError(
                "Point mode requires both:\n"
                "--latitude --longitude"
            )

        return planner.plan_point(
            latitude=args.latitude,
            longitude=args.longitude,
            time_utc=args.time_utc,
            radius_degrees=args.radius_degrees,
        )

    # -------------------------------------------------------------------------
    # ORIGINAL DEMO
    # -------------------------------------------------------------------------

    return planner.plan_region(
        lat_min=-8.4,
        lat_max=-7.9,
        lon_min=68.0,
        lon_max=68.5,
        time_utc="2026-09-10T06:00:00Z",
    )


# =============================================================================
# MAIN
# =============================================================================

def main() -> None:

    truststore.inject_into_ssl()

    parser = build_parser()

    args = parser.parse_args()

    print("=" * 80)
    print(
        "OCEANSIGHT-V"
    )
    print(
        "REAL INCOIS HYCOM CHUNK DOWNLOADER"
    )
    print("=" * 80)

    # -------------------------------------------------------------------------
    # Planner selection.
    #
    # A dataset-specific coordinate file can now be supplied.
    # -------------------------------------------------------------------------

    if args.coordinate_file is not None:

        coordinate_file = Path(
            args.coordinate_file
        )

        planner = HycomChunkPlanner(
            coordinate_file=coordinate_file
        )

    else:

        planner = HycomChunkPlanner()

    plans = build_plans(
        planner,
        args,
    )

    active_dataset_file = (
        args.dataset_file
        if args.dataset_file is not None
        else FILE_NAME
    )

    active_dataset_url = (
        args.dataset_url
        if args.dataset_url is not None
        else DATASET_URL
    )

    print()
    print(
        "Chunks planned:",
        len(plans),
    )

    print()
    print(
        "Dataset:",
        active_dataset_file,
    )

    print(
        "Source:",
        active_dataset_url,
    )

    timeout = httpx.Timeout(
        connect=30.0,
        read=180.0,
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

        downloaded_count = 0

        skipped_count = 0

        for index, plan in enumerate(
            plans,
            start=1,
        ):

            print()
            print(
                "=" * 80
            )

            print(
                f"CHUNK {index}/{len(plans)}"
            )

            print(
                "=" * 80
            )

            print()
            print(
                "Time index:",
                plan.time_index,
            )

            print(
                "Requested time:",
                plan.requested_time_utc,
            )

            print(
                "Latitude indexes:",
                plan.lat_start,
                "to",
                plan.lat_start
                + plan.lat_count
                - 1,
            )

            print(
                "Longitude indexes:",
                plan.lon_start,
                "to",
                plan.lon_start
                + plan.lon_count
                - 1,
            )

            print(
                "Latitude coverage:",
                plan.lat_min,
                "to",
                plan.lat_max,
            )

            print(
                "Longitude coverage:",
                plan.lon_min,
                "to",
                plan.lon_max,
            )

            chunk_path, provenance_path = (
                existing_chunk_paths(
                    plan
                )
            )

            if (
                not args.force
                and chunk_path.exists()
                and provenance_path.exists()
            ):

                print()
                print(
                    "SKIP: Exact chunk already exists."
                )

                print(
                    "Chunk:",
                    chunk_path,
                )

                print(
                    "Provenance:",
                    provenance_path,
                )

                skipped_count += 1

                continue

            print()
            print(
                "DOWNLOADING REAL INCOIS DATA..."
            )

            saved_chunk, saved_provenance = (
                download_plan(
                    plan=plan,
                    client=client,
                    planner=planner,
                    dataset_file=active_dataset_file,
                    dataset_url=active_dataset_url,
                )
            )

            print()
            print(
                "Chunk saved:",
                saved_chunk,
            )

            print(
                "Provenance saved:",
                saved_provenance,
            )

            downloaded_count += 1

    print()
    print(
        "=" * 80
    )

    print(
        "HYCOM CHUNK DOWNLOAD COMPLETE"
    )

    print(
        "=" * 80
    )

    print()
    print(
        "Planned chunks:",
        len(plans),
    )

    print(
        "Downloaded:",
        downloaded_count,
    )

    print(
        "Skipped existing:",
        skipped_count,
    )

    print(
        "Full NetCDF downloaded:",
        False,
    )

    print(
        "Synthetic data:",
        False,
    )

    print(
        "Interpolation:",
        False,
    )

    print(
        "=" * 80
    )


if __name__ == "__main__":
    main()

