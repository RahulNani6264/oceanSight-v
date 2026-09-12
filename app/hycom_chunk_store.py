
from __future__ import annotations

import json
import math
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

import httpx
import numpy as np
import truststore


# =============================================================================
# OCEANSIGHT-V
# REAL INCOIS HYCOM CHUNK STORE
#
# This program requests only small OPeNDAP subsets.
# It NEVER downloads the complete ~10 GB NetCDF file.
#
# Stored fields:
#   TIME
#   DEPTH
#   LAT
#   LON
#   TEMP
#   SALN
#   UVEL
#   VVEL
#   SSH
#
# 4D fields:
#   [time, depth, lat, lon]
#
# SSH:
#   [time, lat, lon]
#
# Missing source values:
#   NaN + explicit boolean mask
#
# No synthetic data is generated.
# =============================================================================


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
# REAL INCOIS DATASET
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
# CHUNK CONFIGURATION
# =============================================================================

TIME_INDEX = 0

LAT_START = 700
LAT_COUNT = 8

LON_START = 800
LON_COUNT = 8

DEPTH_START = 0
DEPTH_COUNT = 6


# =============================================================================
# VERIFIED INCOIS FILL VALUES
# =============================================================================

HYCOM_FILL_VALUES = {
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
# HELPERS
# =============================================================================

def utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def build_ascii_url(
    variable: str,
    expression: str,
) -> str:
    """
    Convert an OPeNDAP indexed expression into a fully URL-encoded request.
    """

    constraint = (
        f"{variable}{expression}"
    )

    encoded = quote(
        constraint,
        safe="",
    )

    return (
        f"{DATASET_URL}.ascii?"
        f"{encoded}"
    )


def is_fill_value(
    value: float,
    variable: str,
) -> bool:
    """
    Detect an INCOIS source fill value.
    """

    fill = HYCOM_FILL_VALUES.get(
        variable
    )

    if fill is None:
        return False

    if value == fill:
        return True

    scale = max(
        1.0,
        abs(fill),
        abs(value),
    )

    return (
        abs(value - fill)
        <= 1.0e-6 * scale
    )


# =============================================================================
# OPeNDAP RESPONSE PARSER
# =============================================================================

def extract_data_values(
    response_text: str,
    marker_prefix: str,
    expected_count: int,
) -> np.ndarray:
    """
    Parse INCOIS OPeNDAP ASCII output.

    Supports:

        DEPTH[6]
        0.0, 10.0, 50.0, ...

    and:

        TEMP.TEMP[1][6][8][8]
        [0][0][0], 27.5, 27.6, ...

    Returns exactly expected_count float32 values.
    """

    lines = response_text.splitlines()

    marker_index: int | None = None

    for index, line in enumerate(lines):

        if line.strip().startswith(
            marker_prefix
        ):
            marker_index = index
            break

    if marker_index is None:

        raise ValueError(
            "Could not find OPeNDAP data marker:\n"
            f"{marker_prefix}"
        )

    values: list[float] = []

    for line in lines[
        marker_index + 1:
    ]:

        stripped = line.strip()

        if not stripped:
            continue

        # Stop when coordinate maps begin.
        if (
            ".TIME[" in stripped
            or ".DEPTH[" in stripped
            or ".LAT[" in stripped
            or ".LON[" in stripped
        ):
            break

        # ---------------------------------------------------------------------
        # MULTIDIMENSIONAL ARRAY LINE
        #
        # Example:
        #
        # [0][0][0], 27.1, 27.2, 27.3
        # ---------------------------------------------------------------------

        if stripped.startswith("["):

            parts = [
                item.strip()
                for item in stripped.split(",")
            ]

            for item in parts[1:]:

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

        # ---------------------------------------------------------------------
        # ONE-DIMENSIONAL ARRAY LINE
        #
        # Example:
        #
        # 0.0, 10.0, 50.0, 100.0
        # ---------------------------------------------------------------------

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
            "OPeNDAP data count mismatch.\n"
            f"Expected: {expected_count}\n"
            f"Received: {len(values)}\n"
            f"Marker: {marker_prefix}\n"
        )

    return np.asarray(
        values,
        dtype=np.float32,
    )


# =============================================================================
# REMOTE REQUEST
# =============================================================================

def fetch_ascii(
    client: httpx.Client,
    variable: str,
    expression: str,
) -> str:

    url = build_ascii_url(
        variable,
        expression,
    )

    print()
    print(
        f"REQUEST: {variable}"
    )

    print(
        f"Constraint: {variable}{expression}"
    )

    print(
        f"URL: {url}"
    )

    response = client.get(
        url
    )

    print(
        f"HTTP: {response.status_code}"
    )

    if response.status_code != 200:

        print()
        print(
            response.text[:5000]
        )

        raise RuntimeError(
            f"INCOIS OPeNDAP request failed "
            f"for {variable}"
        )

    return response.text


# =============================================================================
# FETCH 1D COORDINATE
# =============================================================================

def fetch_1d(
    client: httpx.Client,
    variable: str,
    start: int,
    count: int,
) -> np.ndarray:

    expression = (
        f"[{start}:1:{start + count - 1}]"
    )

    response = fetch_ascii(
        client,
        variable,
        expression,
    )

    marker = (
        f"{variable}[{count}]"
    )

    values = extract_data_values(
        response,
        marker,
        count,
    )

    return values


# =============================================================================
# FETCH 4D GRID
# =============================================================================

def fetch_grid_4d(
    client: httpx.Client,
    variable: str,
) -> np.ndarray:

    expression = (
        f"[{TIME_INDEX}]"
        f"[{DEPTH_START}:1:"
        f"{DEPTH_START + DEPTH_COUNT - 1}]"
        f"[{LAT_START}:1:"
        f"{LAT_START + LAT_COUNT - 1}]"
        f"[{LON_START}:1:"
        f"{LON_START + LON_COUNT - 1}]"
    )

    expected_count = (
        DEPTH_COUNT
        * LAT_COUNT
        * LON_COUNT
    )

    response = fetch_ascii(
        client,
        variable,
        expression,
    )

    marker = (
        f"{variable}.{variable}"
        f"[1]"
        f"[{DEPTH_COUNT}]"
        f"[{LAT_COUNT}]"
        f"[{LON_COUNT}]"
    )

    values = extract_data_values(
        response,
        marker,
        expected_count,
    )

    return values.reshape(
        (
            1,
            DEPTH_COUNT,
            LAT_COUNT,
            LON_COUNT,
        )
    )


# =============================================================================
# FETCH 3D GRID
# =============================================================================

def fetch_grid_3d(
    client: httpx.Client,
    variable: str,
) -> np.ndarray:

    expression = (
        f"[{TIME_INDEX}]"
        f"[{LAT_START}:1:"
        f"{LAT_START + LAT_COUNT - 1}]"
        f"[{LON_START}:1:"
        f"{LON_START + LON_COUNT - 1}]"
    )

    expected_count = (
        LAT_COUNT
        * LON_COUNT
    )

    response = fetch_ascii(
        client,
        variable,
        expression,
    )

    marker = (
        f"{variable}.{variable}"
        f"[1]"
        f"[{LAT_COUNT}]"
        f"[{LON_COUNT}]"
    )

    values = extract_data_values(
        response,
        marker,
        expected_count,
    )

    return values.reshape(
        (
            1,
            LAT_COUNT,
            LON_COUNT,
        )
    )


# =============================================================================
# HYCOM TIME
# =============================================================================

def hycom_time_to_iso(
    days_since_origin: float,
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
                days_since_origin
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
# CLEAN FIELD
# =============================================================================

def clean_field(
    values: np.ndarray,
    variable: str,
) -> tuple[
    np.ndarray,
    np.ndarray,
]:
    """
    Clean one scientific array.

    Important implementation detail:
        The missing mask has exactly the same shape as the original array.

    Source fill values become:
        NaN in the scientific array
        True in the corresponding missing mask

    Missing values are never converted to zero.
    """

    array = np.asarray(
        values,
        dtype=np.float32,
    ).copy()

    missing = (
        ~np.isfinite(array)
    )

    # Work on flattened views so boolean indexing has exactly the same
    # one-dimensional shape on both sides.
    flat = array.reshape(-1)
    flat_missing = missing.reshape(-1)

    # Identify source fill values.
    for index in range(
        flat.size
    ):

        value = float(
            flat[index]
        )

        if is_fill_value(
            value,
            variable,
        ):
            flat_missing[index] = True

    # -------------------------------------------------------------------------
    # FIX:
    #
    # Do NOT do:
    #
    #     array[flat_missing] = np.nan
    #
    # because array is 4D while flat_missing is 1D.
    #
    # Instead operate on the flattened array.
    # -------------------------------------------------------------------------

    flat[flat_missing] = np.nan

    cleaned = flat.reshape(
        array.shape
    )

    cleaned_missing = (
        flat_missing.reshape(
            array.shape
        )
    )

    # Safety assertions.
    if cleaned.shape != values.shape:
        raise RuntimeError(
            f"{variable}: cleaned shape changed "
            f"from {values.shape} to {cleaned.shape}"
        )

    if cleaned_missing.shape != values.shape:
        raise RuntimeError(
            f"{variable}: missing mask shape "
            f"{cleaned_missing.shape} does not match "
            f"value shape {values.shape}"
        )

    return (
        cleaned,
        cleaned_missing,
    )


# =============================================================================
# BUILD CHUNK
# =============================================================================

def build_chunk() -> None:

    truststore.inject_into_ssl()

    print("=" * 80)
    print(
        "OCEANSIGHT-V"
    )
    print(
        "BUILD REAL INCOIS HYCOM CHUNK"
    )
    print("=" * 80)

    print()
    print(
        "Remote dataset:"
    )

    print(
        DATASET_URL
    )

    print()
    print(
        "Chunk dimensions:"
    )

    print(
        "  time  = 1"
    )

    print(
        f"  depth = {DEPTH_COUNT}"
    )

    print(
        f"  lat   = {LAT_COUNT}"
    )

    print(
        f"  lon   = {LON_COUNT}"
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

        # ---------------------------------------------------------------------
        # COORDINATES
        # ---------------------------------------------------------------------

        depth = fetch_1d(
            client,
            "DEPTH",
            DEPTH_START,
            DEPTH_COUNT,
        )

        lat = fetch_1d(
            client,
            "LAT",
            LAT_START,
            LAT_COUNT,
        )

        lon = fetch_1d(
            client,
            "LON",
            LON_START,
            LON_COUNT,
        )

        time_values = fetch_1d(
            client,
            "TIME",
            TIME_INDEX,
            1,
        )

        # ---------------------------------------------------------------------
        # 4D FIELDS
        # ---------------------------------------------------------------------

        temp_raw = fetch_grid_4d(
            client,
            "TEMP",
        )

        saln_raw = fetch_grid_4d(
            client,
            "SALN",
        )

        uvel_raw = fetch_grid_4d(
            client,
            "UVEL",
        )

        vvel_raw = fetch_grid_4d(
            client,
            "VVEL",
        )

        # ---------------------------------------------------------------------
        # 3D SSH
        # ---------------------------------------------------------------------

        ssh_raw = fetch_grid_3d(
            client,
            "SSH",
        )

    # -------------------------------------------------------------------------
    # CLEAN VALUES
    # -------------------------------------------------------------------------

    temp, temp_missing = clean_field(
        temp_raw,
        "TEMP",
    )

    saln, saln_missing = clean_field(
        saln_raw,
        "SALN",
    )

    uvel, uvel_missing = clean_field(
        uvel_raw,
        "UVEL",
    )

    vvel, vvel_missing = clean_field(
        vvel_raw,
        "VVEL",
    )

    ssh, ssh_missing = clean_field(
        ssh_raw,
        "SSH",
    )

    # -------------------------------------------------------------------------
    # TIME
    # -------------------------------------------------------------------------

    time_numeric = float(
        time_values[0]
    )

    time_iso = (
        hycom_time_to_iso(
            time_numeric
        )
    )

    # -------------------------------------------------------------------------
    # CHUNK FILE NAME
    # -------------------------------------------------------------------------

    chunk_name = (
        f"hycom_t{TIME_INDEX:04d}_"
        f"y{LAT_START:04d}-"
        f"{LAT_START + LAT_COUNT - 1:04d}_"
        f"x{LON_START:04d}-"
        f"{LON_START + LON_COUNT - 1:04d}.npz"
    )

    chunk_path = (
        CHUNK_DIR / chunk_name
    )

    # -------------------------------------------------------------------------
    # SAVE COMPRESSED LOCAL CHUNK
    # -------------------------------------------------------------------------

    np.savez_compressed(

        chunk_path,

        time_numeric=np.asarray(
            [time_numeric],
            dtype=np.float64,
        ),

        time_iso=np.asarray(
            [time_iso]
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

    # -------------------------------------------------------------------------
    # PROVENANCE
    # -------------------------------------------------------------------------

    provenance = {

        "project": (
            "OceanSight-V"
        ),

        "provider": (
            "INCOIS"
        ),

        "service": (
            "THREDDS OPeNDAP"
        ),

        "dataset_file": (
            FILE_NAME
        ),

        "dataset_url": (
            DATASET_URL
        ),

        "created_at_utc": (
            utc_now()
        ),

        "source_time": {

            "numeric_value": (
                time_numeric
            ),

            "units": (
                "days since 1900-12-31"
            ),

            "calendar": (
                "standard"
            ),

            "iso_utc": (
                time_iso
            ),

            "time_index": (
                TIME_INDEX
            ),
        },

        "chunk": {

            "time_index": (
                TIME_INDEX
            ),

            "depth_start": (
                DEPTH_START
            ),

            "depth_count": (
                DEPTH_COUNT
            ),

            "lat_start": (
                LAT_START
            ),

            "lat_count": (
                LAT_COUNT
            ),

            "lon_start": (
                LON_START
            ),

            "lon_count": (
                LON_COUNT
            ),
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

        "coordinates": {

            "depth": {

                "units": "m",

                "positive": "down",

                "values": [
                    float(value)
                    for value in depth
                ],
            },

            "latitude": {

                "units": (
                    "degrees_north"
                ),

                "values": [
                    float(value)
                    for value in lat
                ],
            },

            "longitude": {

                "units": (
                    "degrees_east"
                ),

                "values": [
                    float(value)
                    for value in lon
                ],
            },
        },

        "variables": {

            "TEMP": {

                "meaning": (
                    "INCOIS HYCOM temperature"
                ),

                "units": (
                    "degree_Celsius"
                ),

                "fill_value": (
                    -1.0e34
                ),
            },

            "SALN": {

                "meaning": (
                    "INCOIS HYCOM salinity"
                ),

                "fill_value": (
                    -1.0e34
                ),
            },

            "UVEL": {

                "meaning": (
                    "eastward current"
                ),

                "units": (
                    "m/s"
                ),

                "fill_value": (
                    1.2676506e30
                ),
            },

            "VVEL": {

                "meaning": (
                    "northward current"
                ),

                "units": (
                    "m/s"
                ),

                "fill_value": (
                    1.2676506e30
                ),
            },

            "SSH": {

                "meaning": (
                    "sea surface height"
                ),

                "units": (
                    "m"
                ),

                "fill_value": (
                    1.2676506e30
                ),
            },
        },

        "missing_value_policy": (
            "INCOIS source fill values are converted "
            "to NaN in the scientific arrays and "
            "represented by explicit boolean missing "
            "masks. Missing values are never converted "
            "to zero."
        ),

        "shape": {

            "time": 1,

            "depth": (
                DEPTH_COUNT
            ),

            "lat": (
                LAT_COUNT
            ),

            "lon": (
                LON_COUNT
            ),
        },

        "source_request_rules": {

            "subset_method": (
                "OPeNDAP indexed constraint"
            ),

            "complete_netcdf_download": (
                False
            ),
        },
    }

    provenance_path = (
        PROVENANCE_DIR
        / (
            chunk_path.stem
            + ".json"
        )
    )

    provenance_path.write_text(
        json.dumps(
            provenance,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    # -------------------------------------------------------------------------
    # SUMMARY
    # -------------------------------------------------------------------------

    print()
    print("=" * 80)
    print(
        "LOCAL CHUNK CREATED"
    )
    print("=" * 80)

    print()
    print(
        "Chunk:"
    )

    print(
        chunk_path
    )

    print()
    print(
        "Provenance:"
    )

    print(
        provenance_path
    )

    print()
    print(
        "Time:"
    )

    print(
        time_iso
    )

    print()
    print(
        "Depth:"
    )

    print(
        depth.tolist()
    )

    print()
    print(
        "Latitude:"
    )

    print(
        lat.tolist()
    )

    print()
    print(
        "Longitude:"
    )

    print(
        lon.tolist()
    )

    print()
    print(
        "Shapes:"
    )

    print(
        "  TEMP:",
        temp.shape,
    )

    print(
        "  SALN:",
        saln.shape,
    )

    print(
        "  UVEL:",
        uvel.shape,
    )

    print(
        "  VVEL:",
        vvel.shape,
    )

    print(
        "  SSH:",
        ssh.shape,
    )

    print()
    print(
        "Valid values:"
    )

    print(
        "  TEMP:",
        int(
            np.count_nonzero(
                ~np.isnan(temp)
            )
        ),
    )

    print(
        "  SALN:",
        int(
            np.count_nonzero(
                ~np.isnan(saln)
            )
        ),
    )

    print(
        "  UVEL:",
        int(
            np.count_nonzero(
                ~np.isnan(uvel)
            )
        ),
    )

    print(
        "  VVEL:",
        int(
            np.count_nonzero(
                ~np.isnan(vvel)
            )
        ),
    )

    print(
        "  SSH:",
        int(
            np.count_nonzero(
                ~np.isnan(ssh)
            )
        ),
    )

    print()
    print(
        "Complete NetCDF downloaded:",
        False,
    )

    print()
    print("=" * 80)
    print(
        "HYCOM CHUNK BUILD COMPLETE"
    )
    print("=" * 80)


if __name__ == "__main__":
    build_chunk()

