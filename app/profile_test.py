from __future__ import annotations

import asyncio
from pathlib import Path
from urllib.parse import quote

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

    # One time step.
    # All 24 vertical levels.
    # One latitude.
    # One longitude.

    expression = (
        f"{variable}"
        "[(last)]"
        "[0:1:23]"
        "[30]"
        "[40]"
    )

    encoded = quote(
        expression,
        safe=",:+-"
    )

    return (
        f"{BASE_URL}"
        f"/griddap/"
        f"{DATASET}"
        f".csv?"
        f"{encoded}"
    )


async def fetch(
    variable: str,
) -> str:

    truststore.inject_into_ssl()

    url = build_url(
        variable
    )

    print()
    print("=" * 80)
    print("INCOIS VERTICAL PROFILE TEST")
    print("=" * 80)

    print()
    print("Variable:", variable)
    print("Dataset:", DATASET)

    print()
    print("Request URL:")
    print(url)

    headers = {
        "User-Agent":
            "OceanSight-v/0.1",
        "Accept":
            "text/csv",
    }

    async with httpx.AsyncClient(
        verify=True,
        timeout=60,
        follow_redirects=True,
        headers=headers,
    ) as client:

        response = await client.get(
            url
        )

    print()
    print(
        "HTTP status:",
        response.status_code,
    )

    if response.status_code != 200:
        print(
            response.text[:5000]
        )
        raise RuntimeError(
            "INCOIS profile request failed."
        )

    return response.text


def save(
    variable: str,
    text: str,
) -> Path:

    root = (
        Path(__file__).resolve().parent.parent
    )

    directory = (
        root / "raw"
    )

    directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    path = (
        directory
        / (
            f"{DATASET}_"
            f"{variable}_profile.csv"
        )
    )

    path.write_text(
        text,
        encoding="utf-8",
    )

    return path


async def main() -> None:

    for variable in (
        "TEMP",
        "SAL",
    ):

        try:

            text = await fetch(
                variable
            )

            path = save(
                variable,
                text,
            )

            print()
            print("RAW RESPONSE")
            print("-" * 80)

            for line in (
                text.splitlines()
                [:40]
            ):
                print(line)

            print()
            print(
                "Saved:",
                path,
            )

        except Exception as exc:

            print()
            print(
                f"{variable} FAILED:"
            )

            print(exc)

    print()
    print("=" * 80)
    print("PROFILE TEST COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(
        main()
    )