from __future__ import annotations

import asyncio
from pathlib import Path
from urllib.parse import quote


# This module is a manual live-data diagnostic script.
# Prevent pytest from collecting its helper function as a test.
__test__ = False

import httpx
import truststore


BASE_URL = (
    "https://erddap.incois.gov.in/erddap"
)

DATASET = (
    "incois_argo_10d_VAM"
)


def build_url(
    variable: str,
) -> str:
    """
    Build a tiny real INCOIS ERDDAP griddap request.

    IMPORTANT:
    INCOIS is telling us that latitude/longitude
    constraints are array INDEXES, not coordinate
    values.

    Metadata:
        latitude  -> 60 values -> indexes 0..59
        longitude -> 90 values -> indexes 0..89

    We therefore use:
        latitude  index 20..40
        longitude index 39..49

    These correspond approximately to:
        latitude  -9.5 .. 10.5
        longitude 69.5 .. 79.5

    Time:
        latest available -> [(last)]

    Vertical:
        first ZAX level -> [0]
    """

    latitude_start = 20
    latitude_end = 40

    longitude_start = 39
    longitude_end = 49

    expression = (
        f"{variable}"
        "[(last)]"
        "[0]"
        f"[{latitude_start}:1:{latitude_end}]"
        f"[{longitude_start}:1:{longitude_end}]"
    )

    encoded_expression = quote(
        expression,
        safe=",:+-"
    )

    return (
        f"{BASE_URL}"
        f"/griddap/"
        f"{DATASET}"
        f".csv?"
        f"{encoded_expression}"
    )


async def download(
    variable: str,
) -> str:

    # Install Windows/native certificate
    # trust for this Python process.
    truststore.inject_into_ssl()

    url = build_url(
        variable
    )

    print()
    print("=" * 80)
    print("INCOIS SMALL DATA TEST")
    print("=" * 80)

    print()
    print("Dataset:")
    print(DATASET)

    print()
    print("Variable:")
    print(variable)

    print()
    print(
        "Time: latest available"
    )

    print(
        "ZAX index: 0"
    )

    print(
        "Latitude indexes: 20..40"
    )

    print(
        "Longitude indexes: 39..49"
    )

    print()
    print("Request URL:")
    print(url)

    headers = {
        "User-Agent": (
            "OceanSight-v/0.1 "
            "(INCOIS scientific-data test)"
        ),
        "Accept": "text/csv",
    }

    async with httpx.AsyncClient(
        timeout=60.0,
        follow_redirects=True,
        headers=headers,
    ) as client:

        response = await client.get(
            url
        )

    print()
    print(
        f"HTTP status: "
        f"{response.status_code}"
    )

    if response.status_code != 200:

        print()
        print(
            "INCOIS returned an error:"
        )

        print(
            response.text[:5000]
        )

        raise RuntimeError(
            "INCOIS small-data request failed."
        )

    print()
    print(
        "Request successful."
    )

    print()
    print(
        "Returned characters:",
        len(response.text),
    )

    return response.text


def save_raw(
    variable: str,
    text: str,
) -> Path:

    project_root = (
        Path(__file__)
        .resolve()
        .parent.parent
    )

    raw_dir = (
        project_root / "raw"
    )

    raw_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    path = (
        raw_dir
        / (
            f"{DATASET}_"
            f"{variable}_"
            "small.csv"
        )
    )

    path.write_text(
        text,
        encoding="utf-8",
    )

    return path


def preview(
    text: str,
    max_lines: int = 30,
) -> None:

    print()
    print("=" * 80)
    print(
        "RAW INCOIS RESPONSE PREVIEW"
    )
    print("=" * 80)

    lines = text.splitlines()

    for line in lines[:max_lines]:
        print(line)


async def test_variable(
    variable: str,
) -> bool:

    try:

        text = await download(
            variable
        )

        path = save_raw(
            variable,
            text,
        )

        preview(
            text
        )

        print()
        print(
            f"{variable} raw data saved to:"
        )

        print(path)

        return True

    except Exception as exc:

        print()
        print(
            f"{variable} test FAILED"
        )

        print(
            str(exc)
        )

        return False


async def main() -> None:

    print()
    print("=" * 80)
    print(
        "OCEANSIGHT-V"
    )
    print(
        "REAL INCOIS NUMERICAL DATA TEST"
    )
    print("=" * 80)

    print()
    print(
        "This test retrieves only a tiny "
        "subset of the real INCOIS dataset."
    )

    print(
        "No mock or synthetic values are used."
    )

    print()
    print(
        "Testing latest TEMP..."
    )

    temp_ok = await test_variable(
        "TEMP"
    )

    if not temp_ok:

        print()
        print(
            "TEMP failed."
        )

        print(
            "Stopping before requesting SAL."
        )

        return

    print()
    print(
        "Testing latest SAL..."
    )

    sal_ok = await test_variable(
        "SAL"
    )

    print()
    print("=" * 80)
    print("TEST SUMMARY")
    print("=" * 80)

    print()
    print(
        "TEMP:",
        "PASS"
        if temp_ok
        else "FAIL",
    )

    print(
        "SAL:",
        "PASS"
        if sal_ok
        else "FAIL",
    )

    print()

    if temp_ok and sal_ok:

        print(
            "SUCCESS!"
        )

        print(
            "Real INCOIS numerical data "
            "was retrieved."
        )

        print()
        print(
            "Next step:"
        )

        print(
            "inspect the returned coordinates, "
            "time and ZAX values."
        )


if __name__ == "__main__":
    asyncio.run(
        main()
    )