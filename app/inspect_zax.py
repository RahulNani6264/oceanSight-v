from __future__ import annotations

import json
from pathlib import Path


METADATA_FILE = (
    Path(__file__).resolve().parent.parent
    / "metadata"
    / "incois_argo_10d_VAM_metadata.json"
)


def main() -> None:
    print("=" * 80)
    print("OCEANSIGHT-V")
    print("INCOIS ZAX / VERTICAL-LEVEL INSPECTOR")
    print("=" * 80)

    if not METADATA_FILE.exists():
        raise FileNotFoundError(
            f"Metadata file not found:\n{METADATA_FILE}"
        )

    data = json.loads(
        METADATA_FILE.read_text(
            encoding="utf-8"
        )
    )

    rows = (
        data.get("table", {})
        .get("rows", [])
    )

    print()
    print("ZAX METADATA")
    print("-" * 80)

    for row in rows:
        if (
            isinstance(row, list)
            and len(row) >= 4
            and str(row[1]).strip() == "ZAX"
        ):
            print(
                " | ".join(
                    str(value)
                    for value in row
                )
            )

    print()
    print("TIME METADATA")
    print("-" * 80)

    for row in rows:
        if (
            isinstance(row, list)
            and len(row) >= 4
            and str(row[1]).strip() == "time"
        ):
            print(
                " | ".join(
                    str(value)
                    for value in row
                )
            )

    print()
    print("TEMP ATTRIBUTES")
    print("-" * 80)

    for row in rows:
        if (
            isinstance(row, list)
            and len(row) >= 4
            and str(row[0]).strip() == "attribute"
            and str(row[1]).strip() == "TEMP"
        ):
            print(
                " | ".join(
                    str(value)
                    for value in row
                )
            )

    print()
    print("SAL ATTRIBUTES")
    print("-" * 80)

    for row in rows:
        if (
            isinstance(row, list)
            and len(row) >= 4
            and str(row[0]).strip() == "attribute"
            and str(row[1]).strip() == "SAL"
        ):
            print(
                " | ".join(
                    str(value)
                    for value in row
                )
            )

    print()
    print("=" * 80)
    print("INSPECTION COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    main()