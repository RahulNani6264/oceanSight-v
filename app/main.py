from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from app.dataset_discovery import DatasetDiscovery
from app.storage import save_metadata


IMPORTANT_DATASETS = [
    "incois_argo_10d_VAM",
    "incois_argo_10day_McCreary",
    "incois_argo_mnt_VAM",
    "Indian_ARGO_Floats",
    "ascat_daily_datasets",
    "incois_oceansat2_datasets",
    "incois_valueadded_products_datasets",
    "IRS_chlorophyll_datasets",
    "incois_argo_sst_weekly",
    "incois_quickscat_daily_datasets",
    "incois_tmi_3day_datasets",
]


def print_metadata_summary(
    dataset_id: str,
    metadata: Any,
) -> None:

    print()
    print("=" * 90)
    print(f"DATASET: {dataset_id}")
    print("=" * 90)

    table = {}

    if (
        isinstance(metadata, dict)
        and isinstance(
            metadata.get("table"),
            dict,
        )
    ):
        table = metadata["table"]

    rows = table.get(
        "rows",
        [],
    )

    if not rows:
        print(
            "No metadata rows returned."
        )
        return

    dimensions = []
    variables = []
    global_attributes = []

    for row in rows:

        if not isinstance(
            row,
            list,
        ):
            continue

        if len(row) < 2:
            continue

        row_type = str(
            row[0]
        ).strip()

        name = str(
            row[1]
        ).strip()

        if row_type == "dimension":
            dimensions.append(row)

        elif row_type == "variable":
            variables.append(row)

        elif row_type == "attribute":
            global_attributes.append(row)

    print()
    print("DIMENSIONS")
    print("-" * 90)

    for row in dimensions:

        print(
            " | ".join(
                str(value)
                for value in row
            )
        )

    print()
    print("VARIABLES")
    print("-" * 90)

    for row in variables:

        print(
            " | ".join(
                str(value)
                for value in row
            )
        )

    print()
    print("IMPORTANT GLOBAL ATTRIBUTES")
    print("-" * 90)

    wanted = {
        "title",
        "summary",
        "institution",
        "time_coverage_start",
        "time_coverage_end",
        "geospatial_lat_min",
        "geospatial_lat_max",
        "geospatial_lon_min",
        "geospatial_lon_max",
        "geospatial_lat_resolution",
        "geospatial_lon_resolution",
        "Conventions",
        "history",
    }

    for row in global_attributes:

        if len(row) < 4:
            continue

        attribute_name = str(
            row[2]
        ).strip()

        if attribute_name in wanted:

            print(
                " | ".join(
                    str(value)
                    for value in row
                )
            )


async def inspect_dataset(
    discovery: DatasetDiscovery,
    dataset_id: str,
) -> dict[str, Any]:

    print()
    print(
        f"Reading metadata: {dataset_id}"
    )

    metadata = await (
        discovery.dataset_metadata(
            dataset_id
        )
    )

    print_metadata_summary(
        dataset_id,
        metadata,
    )

    filename = (
        f"{dataset_id}_metadata.json"
    )

    path = save_metadata(
        filename,
        metadata,
    )

    print()
    print(
        f"Saved metadata: {path}"
    )

    return {
        "dataset_id":
            dataset_id,
        "metadata":
            metadata,
    }


async def main() -> None:

    print()
    print("=" * 90)
    print(
        "OCEANSIGHT-V — INCOIS SCIENTIFIC "
        "DATASET INSPECTOR"
    )
    print("=" * 90)

    discovery = DatasetDiscovery()

    print()
    print(
        "Connecting to INCOIS ERDDAP..."
    )

    await discovery.catalog()

    print(
        "✓ INCOIS ERDDAP connection successful"
    )

    print()
    print(
        "Inspecting important datasets..."
    )

    results = {}

    for dataset_id in IMPORTANT_DATASETS:

        try:

            result = await inspect_dataset(
                discovery,
                dataset_id,
            )

            results[
                dataset_id
            ] = result

        except Exception as exc:

            print()
            print(
                f"✗ Failed: {dataset_id}"
            )

            print(
                f"  Reason: {exc}"
            )

            results[
                dataset_id
            ] = {
                "dataset_id":
                    dataset_id,
                "error":
                    str(exc),
            }

    combined_path = save_metadata(
        "important_dataset_metadata.json",
        results,
    )

    print()
    print("=" * 90)
    print(
        "METADATA INSPECTION COMPLETE"
    )
    print("=" * 90)

    print()
    print(
        f"Combined metadata: {combined_path}"
    )

    print()
    print(
        "No large scientific data was downloaded."
    )

    print(
        "Only dataset metadata was retrieved."
    )


if __name__ == "__main__":
    asyncio.run(main())