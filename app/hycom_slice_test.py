
from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

import httpx
import truststore


# =============================================================================
# OCEANSIGHT-V
# REAL INCOIS HYCOM SMALL-SLICE TEST
#
# This program uses the INCOIS THREDDS OPeNDAP server.
#
# IMPORTANT:
#   We NEVER download the complete 9+ GiB NetCDF file.
#
# We request only tiny indexed slices:
#
#   DEPTH
#   LAT
#   LON
#   TEMP
#   SALN
#   UVEL
#   VVEL
#   SSH
#
# The scientific data remains REAL INCOIS data.
# No synthetic/fake values are generated.
# =============================================================================


PROJECT_ROOT = (
    Path(__file__).resolve().parent.parent
)

RAW_DIR = (
    PROJECT_ROOT / "raw"
)

RAW_DIR.mkdir(
    parents=True,
    exist_ok=True,
)


FILE_NAME = (
    "RSMC_hycom_20260911.nc"
)

OPENDAP_DATASET = (
    "https://incois.gov.in/thredds/dodsC/"
    "osf/currents2/"
    + FILE_NAME
)


# =============================================================================
# SMALL TEST WINDOW
#
# We intentionally retrieve very few values.
#
# TIME:
#   first available time = index 0
#
# DEPTH:
#   all 6 model levels
#
# LAT:
#   4 latitude cells
#
# LON:
#   4 longitude cells
#
# Therefore:
#
# TEMP/SALN/UVEL/VVEL:
#   1 × 6 × 4 × 4 = 96 values
#
# SSH:
#   1 × 4 × 4 = 16 values
#
# =============================================================================


TIME_INDEX = 0

LAT_START = 700
LAT_STOP = 704

LON_START = 800
LON_STOP = 804


# =============================================================================
# URL BUILDING
# =============================================================================


def build_ascii_url(
    variable: str,
    expression: str,
) -> str:
    """
    Build an OPeNDAP .ascii URL.

    IMPORTANT:
        OPeNDAP index expressions contain characters such as:

            [
            ]
            :
            ,

        These must be URL-encoded.

    Example logical constraint:

        DEPTH[0:1:5]

    Encoded form:

        DEPTH%5B0%3A1%3A5%5D
    """

    constraint = (
        f"{variable}{expression}"
    )

    encoded_constraint = quote(
        constraint,
        safe="",
    )

    return (
        f"{OPENDAP_DATASET}.ascii?"
        f"{encoded_constraint}"
    )


# =============================================================================
# HTTP REQUEST
# =============================================================================


def fetch(
    client: httpx.Client,
    variable: str,
    expression: str,
) -> str:

    url = build_ascii_url(
        variable,
        expression,
    )

    print()
    print("=" * 80)
    print(
        f"REQUEST: {variable}"
    )
    print("=" * 80)

    print(
        "Logical constraint:"
    )

    print(
        f"{variable}{expression}"
    )

    print()
    print(
        "Encoded URL:"
    )

    print(
        url
    )

    response = client.get(
        url
    )

    print()
    print(
        "HTTP status:",
        response.status_code,
    )

    if response.status_code != 200:

        print()
        print(
            "SERVER RESPONSE"
        )

        print(
            "-" * 80
        )

        print(
            response.text[:5000]
        )

        raise RuntimeError(
            f"INCOIS OPeNDAP request failed "
            f"for {variable}"
        )

    print()
    print(
        "RAW RESPONSE"
    )

    print(
        "-" * 80
    )

    # Keep terminal output manageable.
    print(
        response.text[:10000]
    )

    return response.text


# =============================================================================
# SAVE
# =============================================================================


def save_response(
    filename: str,
    response: str,
) -> Path:

    path = (
        RAW_DIR / filename
    )

    path.write_text(
        response,
        encoding="utf-8",
    )

    return path


# =============================================================================
# MAIN
# =============================================================================


def main() -> None:

    truststore.inject_into_ssl()

    print("=" * 80)
    print(
        "OCEANSIGHT-V"
    )

    print(
        "REAL INCOIS HYCOM SMALL-SLICE TEST"
    )

    print("=" * 80)

    print()
    print(
        "Remote dataset:"
    )

    print(
        OPENDAP_DATASET
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

        # =====================================================================
        # DEPTH
        # =====================================================================

        depth_response = fetch(
            client,
            "DEPTH",
            "[0:1:5]",
        )

        depth_path = save_response(
            "RSMC_hycom_DEPTH_test.txt",
            depth_response,
        )

        # =====================================================================
        # LATITUDE
        # =====================================================================

        lat_response = fetch(
            client,
            "LAT",
            f"[{LAT_START}:1:{LAT_STOP - 1}]",
        )

        lat_path = save_response(
            "RSMC_hycom_LAT_test.txt",
            lat_response,
        )

        # =====================================================================
        # LONGITUDE
        # =====================================================================

        lon_response = fetch(
            client,
            "LON",
            f"[{LON_START}:1:{LON_STOP - 1}]",
        )

        lon_path = save_response(
            "RSMC_hycom_LON_test.txt",
            lon_response,
        )

        # =====================================================================
        # TEMPERATURE
        # =====================================================================

        temp_expression = (
            f"[{TIME_INDEX}]"
            f"[0:1:5]"
            f"[{LAT_START}:1:{LAT_STOP - 1}]"
            f"[{LON_START}:1:{LON_STOP - 1}]"
        )

        temp_response = fetch(
            client,
            "TEMP",
            temp_expression,
        )

        temp_path = save_response(
            "RSMC_hycom_TEMP_test.txt",
            temp_response,
        )

        # =====================================================================
        # SALINITY
        # =====================================================================

        saln_response = fetch(
            client,
            "SALN",
            temp_expression,
        )

        saln_path = save_response(
            "RSMC_hycom_SALN_test.txt",
            saln_response,
        )

        # =====================================================================
        # EASTWARD CURRENT
        # =====================================================================

        uvel_response = fetch(
            client,
            "UVEL",
            temp_expression,
        )

        uvel_path = save_response(
            "RSMC_hycom_UVEL_test.txt",
            uvel_response,
        )

        # =====================================================================
        # NORTHWARD CURRENT
        # =====================================================================

        vvel_response = fetch(
            client,
            "VVEL",
            temp_expression,
        )

        vvel_path = save_response(
            "RSMC_hycom_VVEL_test.txt",
            vvel_response,
        )

        # =====================================================================
        # SEA-SURFACE HEIGHT
        # =====================================================================

        ssh_expression = (
            f"[{TIME_INDEX}]"
            f"[{LAT_START}:1:{LAT_STOP - 1}]"
            f"[{LON_START}:1:{LON_STOP - 1}]"
        )

        ssh_response = fetch(
            client,
            "SSH",
            ssh_expression,
        )

        ssh_path = save_response(
            "RSMC_hycom_SSH_test.txt",
            ssh_response,
        )

    # =========================================================================
    # SUMMARY
    # =========================================================================

    print()
    print("=" * 80)
    print(
        "SLICE TEST COMPLETE"
    )
    print("=" * 80)

    print()
    print(
        "Saved files:"
    )

    for path in [
        depth_path,
        lat_path,
        lon_path,
        temp_path,
        saln_path,
        uvel_path,
        vvel_path,
        ssh_path,
    ]:

        print(
            " ",
            path,
        )

    print()
    print(
        "No complete HYCOM NetCDF was downloaded."
    )

    print()
    print(
        "Only tiny OPeNDAP slices were requested."
    )

    print()
    print("=" * 80)


if __name__ == "__main__":
    main()

