
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

import httpx
import truststore


# =============================================================================
# OCEANSIGHT-V
# LIVE INCOIS THREDDS HYCOM DATASET DISCOVERY
#
# Responsibilities:
#
#   1. Read the live INCOIS THREDDS currents2 catalog.
#   2. Discover available RSMC_hycom_YYYYMMDD.nc files.
#   3. Inspect the real TIME coordinate of candidate files.
#   4. Select the dataset whose TIME range contains the requested UTC time.
#
# IMPORTANT:
#   - No full NetCDF file is downloaded.
#   - Only catalog metadata and the tiny TIME vector are requested.
#   - Scientific data arrays are NOT downloaded here.
# =============================================================================


PROJECT_ROOT = Path(__file__).resolve().parent.parent

PROCESSED_DIR = PROJECT_ROOT / "processed"

CATALOG_DIR = PROCESSED_DIR / "hycom_catalog"

CATALOG_DIR.mkdir(
    parents=True,
    exist_ok=True,
)


THREDDS_ROOT = (
    "https://incois.gov.in/thredds"
)

CATALOG_URL = (
    f"{THREDDS_ROOT}/catalog/osf/currents2/catalog.html"
)

OPENDAP_BASE = (
    f"{THREDDS_ROOT}/dodsC/osf/currents2"
)


RSMC_PATTERN = re.compile(
    r"RSMC_hycom_(\d{8})\.nc",
    re.IGNORECASE,
)


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
# TIME HELPERS
# =============================================================================

def parse_utc(
    value: str,
) -> datetime:
    """
    Parse an ISO-8601 UTC timestamp.
    """

    text = value.strip()

    if text.endswith("Z"):
        text = text[:-1] + "+00:00"

    dt = datetime.fromisoformat(text)

    if dt.tzinfo is None:
        dt = dt.replace(
            tzinfo=timezone.utc
        )
    else:
        dt = dt.astimezone(
            timezone.utc
        )

    return dt


def numeric_time_to_datetime(
    numeric_time: float,
) -> datetime:
    """
    Convert INCOIS HYCOM TIME values using:

        days since 1900-12-31
    """

    epoch = datetime(
        1900,
        12,
        31,
        tzinfo=timezone.utc,
    )

    return (
        epoch
        + timedelta(
            days=float(
                numeric_time
            )
        )
    )


def datetime_to_iso(
    value: datetime,
) -> str:
    """
    Convert timezone-aware datetime to normalized UTC ISO text.
    """

    value = value.astimezone(
        timezone.utc
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
# HTTP
# =============================================================================

def build_client() -> httpx.Client:
    """
    Build a trusted HTTP client for INCOIS.
    """

    truststore.inject_into_ssl()

    timeout = httpx.Timeout(
        connect=30.0,
        read=60.0,
        write=30.0,
        pool=30.0,
    )

    return httpx.Client(
        verify=True,
        timeout=timeout,
        follow_redirects=True,
        headers={
            "User-Agent": (
                "OceanSight-V/1.0 "
                "HYCOM dataset discovery"
            )
        },
    )


def fetch_text(
    client: httpx.Client,
    url: str,
) -> str:
    """
    Fetch a text response from INCOIS.
    """

    response = client.get(
        url
    )

    if response.status_code != 200:
        raise RuntimeError(
            "INCOIS THREDDS request failed.\n"
            f"HTTP: {response.status_code}\n"
            f"URL: {url}\n"
            f"Response:\n"
            f"{response.text[:3000]}"
        )

    return response.text


# =============================================================================
# CATALOG DISCOVERY
# =============================================================================

def discover_rsmc_files(
    client: httpx.Client,
) -> list[str]:
    """
    Discover RSMC HYCOM filenames from the live THREDDS catalog.

    Returns unique filenames sorted newest-first.
    """

    html = fetch_text(
        client,
        CATALOG_URL,
    )

    found_dates: dict[
        str,
        str,
    ] = {}

    for match in RSMC_PATTERN.finditer(
        html
    ):
        filename = match.group(0)

        date_text = match.group(1)

        found_dates[
            date_text
        ] = filename

    if not found_dates:
        raise RuntimeError(
            "No RSMC_hycom_YYYYMMDD.nc files "
            "were discovered from the INCOIS THREDDS catalog."
        )

    filenames = [
        found_dates[key]
        for key in sorted(
            found_dates.keys(),
            reverse=True,
        )
    ]

    return filenames


# =============================================================================
# DDS
# =============================================================================

def dataset_url(
    filename: str,
) -> str:
    """
    Build the real OPeNDAP URL for an RSMC dataset.
    """

    return (
        f"{OPENDAP_BASE}/"
        f"{filename}"
    )


def fetch_dds(
    client: httpx.Client,
    filename: str,
) -> str:
    """
    Retrieve DDS metadata only.
    """

    url = (
        f"{dataset_url(filename)}"
        ".dds"
    )

    return fetch_text(
        client,
        url,
    )


def extract_time_size(
    dds_text: str,
) -> int:
    """
    Extract TIME dimension size from DDS.

    Expected example:

        Float64 TIME[TIME = 28];
    """

    patterns = (
        re.compile(
            r"\bTIME\s*\[\s*TIME\s*=\s*(\d+)\s*\]",
            re.IGNORECASE,
        ),
        re.compile(
            r"\bTIME\s*\[\s*(\d+)\s*\]",
            re.IGNORECASE,
        ),
    )

    for pattern in patterns:

        match = pattern.search(
            dds_text
        )

        if match:
            return int(
                match.group(1)
            )

    raise RuntimeError(
        "Could not determine TIME dimension "
        "from HYCOM DDS."
    )


# =============================================================================
# TIME VECTOR
# =============================================================================

def build_time_ascii_url(
    filename: str,
    time_count: int,
) -> str:
    """
    Build an OPeNDAP .ascii request for the complete TIME vector.
    """

    constraint = (
        f"TIME[0:1:{time_count - 1}]"
    )

    encoded = quote(
        constraint,
        safe="",
    )

    return (
        f"{dataset_url(filename)}"
        f".ascii?{encoded}"
    )


def extract_numeric_values(
    text: str,
    variable: str,
    expected_count: int,
) -> list[float]:
    """
    Extract numeric values from an OPeNDAP ASCII response.
    """

    marker = (
        f"{variable}["
    )

    lines = text.splitlines()

    marker_index: int | None = None

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
            f"Could not find OPeNDAP "
            f"marker for {variable}."
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

        for item in stripped.split(","):

            item = item.strip()

            match = FLOAT_PATTERN.fullmatch(
                item
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
                >= expected_count
            ):
                return values

    if len(values) != expected_count:
        raise RuntimeError(
            "HYCOM TIME vector length mismatch.\n"
            f"Expected: {expected_count}\n"
            f"Received: {len(values)}"
        )

    return values


def fetch_time_values(
    client: httpx.Client,
    filename: str,
    time_count: int,
) -> list[float]:
    """
    Retrieve only the HYCOM TIME coordinate.
    """

    url = build_time_ascii_url(
        filename=filename,
        time_count=time_count,
    )

    text = fetch_text(
        client,
        url,
    )

    return extract_numeric_values(
        text=text,
        variable="TIME",
        expected_count=time_count,
    )


# =============================================================================
# DATASET INSPECTION
# =============================================================================

def inspect_dataset(
    client: httpx.Client,
    filename: str,
) -> dict:
    """
    Inspect one HYCOM dataset without downloading
    scientific data arrays.
    """

    dds_text = fetch_dds(
        client,
        filename,
    )

    time_count = extract_time_size(
        dds_text
    )

    time_numeric = fetch_time_values(
        client=client,
        filename=filename,
        time_count=time_count,
    )

    time_datetimes = [
        numeric_time_to_datetime(
            value
        )
        for value in time_numeric
    ]

    return {
        "filename": filename,
        "dataset_url": dataset_url(
            filename
        ),
        "time_count": time_count,
        "time_numeric": time_numeric,
        "time_iso": [
            datetime_to_iso(
                value
            )
            for value in time_datetimes
        ],
        "time_start_utc": datetime_to_iso(
            min(time_datetimes)
        ),
        "time_end_utc": datetime_to_iso(
            max(time_datetimes)
        ),
    }


# =============================================================================
# TIME-AWARE DATASET SELECTION
# =============================================================================

def find_dataset_for_time(
    requested_time_utc: str,
    max_candidates: int = 7,
) -> dict:
    """
    Find the INCOIS HYCOM dataset whose real TIME coordinate
    contains the requested UTC timestamp.

    Only a small number of newest RSMC files are inspected.
    """

    requested = parse_utc(
        requested_time_utc
    )

    with build_client() as client:

        filenames = discover_rsmc_files(
            client
        )

        candidates = filenames[
            :max_candidates
        ]

        inspected: list[dict] = []

        for filename in candidates:

            info = inspect_dataset(
                client,
                filename,
            )

            inspected.append(
                info
            )

            start = parse_utc(
                info["time_start_utc"]
            )

            end = parse_utc(
                info["time_end_utc"]
            )

            if start <= requested <= end:

                return {
                    "available": True,
                    "requested_time_utc": datetime_to_iso(
                        requested
                    ),
                    "selected": info,
                    "inspected_candidates": inspected,
                }

    return {
        "available": False,
        "requested_time_utc": datetime_to_iso(
            requested
        ),
        "selected": None,
        "inspected_candidates": inspected,
        "reason": (
            "No inspected INCOIS RSMC HYCOM dataset "
            "contains the requested UTC time."
        ),
    }


# =============================================================================
# SAVE DISCOVERY RESULT
# =============================================================================

def save_discovery_result(
    result: dict,
    filename: str = "latest_hycom_discovery.json",
) -> Path:
    """
    Save dataset discovery metadata locally.
    """

    path = (
        CATALOG_DIR
        / filename
    )

    import json

    path.write_text(
        json.dumps(
            result,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    return path


# =============================================================================
# COMMAND LINE
# =============================================================================

def build_parser():
    import argparse

    parser = argparse.ArgumentParser(
        description=(
            "Discover the real INCOIS HYCOM dataset "
            "covering a requested UTC time."
        )
    )

    parser.add_argument(
        "--time-utc",
        required=True,
        help=(
            "Requested UTC time, for example "
            "2026-09-10T06:00:00Z"
        ),
    )

    parser.add_argument(
        "--max-candidates",
        type=int,
        default=7,
        help=(
            "Maximum number of newest RSMC datasets "
            "to inspect. Default: 7"
        ),
    )

    parser.add_argument(
        "--output",
        default="latest_hycom_discovery.json",
        help="Output JSON filename.",
    )

    return parser


def main() -> None:
    parser = build_parser()

    args = parser.parse_args()

    if args.max_candidates <= 0:
        raise ValueError(
            "max-candidates must be greater than zero."
        )

    print("=" * 80)
    print("OCEANSIGHT-V")
    print("LIVE INCOIS HYCOM DATASET DISCOVERY")
    print("=" * 80)

    print()
    print(
        "Requested UTC time:",
        args.time_utc,
    )

    result = find_dataset_for_time(
        requested_time_utc=args.time_utc,
        max_candidates=args.max_candidates,
    )

    print()
    print(
        "DATASET CATALOG DISCOVERY"
    )
    print("-" * 80)

    inspected = result.get(
        "inspected_candidates",
        [],
    )

    print(
        "Candidates inspected:",
        len(inspected),
    )

    for item in inspected:

        print()
        print(
            "Dataset:",
            item["filename"],
        )

        print(
            "TIME start:",
            item["time_start_utc"],
        )

        print(
            "TIME end:",
            item["time_end_utc"],
        )

    print()
    print(
        "SELECTION"
    )
    print("-" * 80)

    selected = result.get(
        "selected"
    )

    if selected:

        print(
            "Selected dataset:",
            selected["filename"],
        )

        print(
            "Dataset URL:",
            selected["dataset_url"],
        )

        print(
            "TIME coverage:",
            selected["time_start_utc"],
            "to",
            selected["time_end_utc"],
        )

    else:

        print(
            "No dataset contains the requested time."
        )

        print(
            "Reason:",
            result.get(
                "reason",
                "unknown",
            ),
        )

    output_path = save_discovery_result(
        result,
        filename=args.output,
    )

    print()
    print(
        "Discovery result saved:"
    )

    print(
        output_path
    )

    print()
    print("=" * 80)
    print(
        "HYCOM DATASET DISCOVERY COMPLETE"
    )
    print("=" * 80)


if __name__ == "__main__":
    main()

