
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .hycom_thredds_discovery import (
    build_client,
    discover_rsmc_files,
    inspect_dataset,
    parse_utc,
)


# =============================================================================
# OCEANSIGHT-V
# LIVE INCOIS HYCOM TIME-STEP DISCOVERY
#
# Purpose:
#
#   Discover real HYCOM model time steps from the INCOIS THREDDS catalog.
#
# This module is specifically intended for:
#
#   - frontend time slider
#   - animation
#   - time-step selection
#   - dataset selection
#
# Scientific rules:
#
#   - Times are read from the REAL INCOIS HYCOM TIME coordinate.
#   - No hard-coded model times.
#   - No synthetic times.
#   - No interpolation between timestamps.
#   - Dataset identity is preserved.
#
# IMPORTANT:
#
#   This module does NOT download full NetCDF scientific arrays.
#   It only reads:
#
#       THREDDS catalog
#       DDS
#       TIME vector
#
# =============================================================================


PROJECT_ROOT = (
    Path(__file__).resolve().parent.parent
)

PROCESSED_DIR = (
    PROJECT_ROOT
    / "processed"
)

CATALOG_DIR = (
    PROCESSED_DIR
    / "hycom_catalog"
)

CATALOG_DIR.mkdir(
    parents=True,
    exist_ok=True,
)


DEFAULT_MAX_DATASETS = 7


# =============================================================================
# TIME HELPERS
# =============================================================================

def datetime_to_iso(
    value: datetime,
) -> str:
    """
    Normalize a timezone-aware datetime into UTC ISO-8601 text.
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
# DATASET TIME DISCOVERY
# =============================================================================

def discover_hycom_times(
    max_datasets: int = DEFAULT_MAX_DATASETS,
) -> dict[str, Any]:
    """
    Discover real HYCOM timestamps from the newest INCOIS RSMC datasets.

    Returns:

        available
        source
        datasets
        times
        dataset_time_map
        earliest_time_utc
        latest_time_utc
        dataset_count
        time_count

    No scientific model values are downloaded here.
    """

    if max_datasets <= 0:

        raise ValueError(
            "max_datasets must be greater than zero."
        )

    with build_client() as client:

        filenames = discover_rsmc_files(
            client
        )

        candidate_files = filenames[
            :max_datasets
        ]

        discovered_datasets: list[
            dict[str, Any]
        ] = []

        time_records: list[
            dict[str, Any]
        ] = []

        for filename in candidate_files:

            info = inspect_dataset(
                client,
                filename,
            )

            time_values = [
                str(value)
                for value in info.get(
                    "time_iso",
                    [],
                )
            ]

            discovered_datasets.append(
                {
                    "filename": (
                        info[
                            "filename"
                        ]
                    ),
                    "dataset_url": (
                        info[
                            "dataset_url"
                        ]
                    ),
                    "time_count": (
                        info[
                            "time_count"
                        ]
                    ),
                    "time_start_utc": (
                        info[
                            "time_start_utc"
                        ]
                    ),
                    "time_end_utc": (
                        info[
                            "time_end_utc"
                        ]
                    ),
                }
            )

            for index, time_text in enumerate(
                time_values
            ):

                time_records.append(
                    {
                        "time_utc": time_text,
                        "dataset": (
                            info[
                                "filename"
                            ]
                        ),
                        "dataset_url": (
                            info[
                                "dataset_url"
                            ]
                        ),
                        "time_index": index,
                    }
                )

    # -------------------------------------------------------------------------
    # Remove duplicate timestamps while retaining dataset identity.
    #
    # The same physical model time can occasionally be present in overlapping
    # daily datasets.
    # -------------------------------------------------------------------------

    unique_time_map: dict[
        str,
        list[dict[str, Any]],
    ] = {}

    for record in time_records:

        time_text = record[
            "time_utc"
        ]

        unique_time_map.setdefault(
            time_text,
            [],
        ).append(
            record
        )

    # -------------------------------------------------------------------------
    # Sort by actual UTC time.
    # -------------------------------------------------------------------------

    def sort_time(
        record: dict[str, Any],
    ) -> datetime:

        return parse_utc(
            record[
                "time_utc"
            ]
        )

    unique_times = sorted(
        unique_time_map.keys(),
        key=lambda value:
        parse_utc(value),
    )

    # -------------------------------------------------------------------------
    # Build frontend-friendly time records.
    # -------------------------------------------------------------------------

    times: list[
        dict[str, Any]
    ] = []

    for time_text in unique_times:

        matching_datasets = (
            unique_time_map[
                time_text
            ]
        )

        datasets = sorted(
            {
                record[
                    "dataset"
                ]
                for record
                in matching_datasets
            }
        )

        dataset_urls = sorted(
            {
                record[
                    "dataset_url"
                ]
                for record
                in matching_datasets
            }
        )

        primary = matching_datasets[0]

        times.append(
            {
                "time_utc": time_text,

                "dataset": (
                    primary[
                        "dataset"
                    ]
                ),

                "dataset_url": (
                    primary[
                        "dataset_url"
                    ]
                ),

                "time_index": (
                    primary[
                        "time_index"
                    ]
                ),

                "datasets": datasets,

                "dataset_urls": dataset_urls,
            }
        )

    # -------------------------------------------------------------------------
    # Overall coverage.
    # -------------------------------------------------------------------------

    if times:

        earliest = times[0][
            "time_utc"
        ]

        latest = times[-1][
            "time_utc"
        ]

    else:

        earliest = None
        latest = None

    return {
        "available": bool(
            times
        ),

        "source": "INCOIS",

        "service": (
            "THREDDS OPeNDAP"
        ),

        "model": "RSMC HYCOM",

        "dataset_count": len(
            discovered_datasets
        ),

        "time_count": len(
            times
        ),

        "earliest_time_utc": earliest,

        "latest_time_utc": latest,

        "datasets": discovered_datasets,

        "times": times,

        "scientific_rules": {
            "real_source_times": True,
            "synthetic_times": False,
            "interpolation": False,
            "source_time_coordinate": (
                "INCOIS HYCOM TIME"
            ),
        },
    }


# =============================================================================
# FIND NEAREST / EXACT TIME
# =============================================================================

def find_time(
    requested_time_utc: str,
    discovery: dict[str, Any],
) -> dict[str, Any]:
    """
    Find an exact HYCOM source timestamp.

    No interpolation is performed.

    Returns a clear result when the requested timestamp does not exist.
    """

    requested = parse_utc(
        requested_time_utc
    )

    requested_iso = datetime_to_iso(
        requested
    )

    times = discovery.get(
        "times",
        [],
    )

    for record in times:

        candidate = parse_utc(
            record[
                "time_utc"
            ]
        )

        if candidate == requested:

            return {
                "available": True,

                "requested_time_utc": (
                    requested_iso
                ),

                "actual_time_utc": (
                    record[
                        "time_utc"
                    ]
                ),

                "dataset": (
                    record[
                        "dataset"
                    ]
                ),

                "dataset_url": (
                    record[
                        "dataset_url"
                    ]
                ),

                "time_index": (
                    record[
                        "time_index"
                    ]
                ),

                "interpolation": False,

                "synthetic_data": False,
            }

    return {
        "available": False,

        "requested_time_utc": (
            requested_iso
        ),

        "actual_time_utc": None,

        "dataset": None,

        "dataset_url": None,

        "time_index": None,

        "interpolation": False,

        "synthetic_data": False,

        "reason": (
            "The requested timestamp does not exactly match "
            "an INCOIS HYCOM source TIME value."
        ),
    }


# =============================================================================
# SAVE
# =============================================================================

def save_time_catalog(
    discovery: dict[str, Any],
    filename: str = "hycom_times.json",
) -> Path:
    """
    Save the discovered real HYCOM time catalog.
    """

    path = (
        CATALOG_DIR
        / filename
    )

    path.write_text(
        json.dumps(
            discovery,
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
            "Discover real INCOIS HYCOM time steps."
        )
    )

    parser.add_argument(
        "--max-datasets",
        type=int,
        default=DEFAULT_MAX_DATASETS,
        help=(
            "Maximum number of newest RSMC datasets "
            "to inspect. Default: 7."
        ),
    )

    parser.add_argument(
        "--find-time",
        type=str,
        default=None,
        help=(
            "Optional exact UTC timestamp to locate "
            "in the discovered HYCOM time vector."
        ),
    )

    parser.add_argument(
        "--output",
        type=str,
        default="hycom_times.json",
        help=(
            "Output JSON filename."
        ),
    )

    return parser


# =============================================================================
# MAIN
# =============================================================================

def main() -> None:

    parser = build_parser()

    args = parser.parse_args()

    if args.max_datasets <= 0:

        raise ValueError(
            "max-datasets must be greater than zero."
        )

    print(
        "=" * 80
    )

    print(
        "OCEANSIGHT-V"
    )

    print(
        "LIVE INCOIS HYCOM TIME-STEP DISCOVERY"
    )

    print(
        "=" * 80
    )

    print()

    print(
        "Datasets to inspect:",
        args.max_datasets,
    )

    print()

    print(
        "Reading the live INCOIS THREDDS catalog..."
    )

    discovery = discover_hycom_times(
        max_datasets=args.max_datasets,
    )

    print()

    print(
        "DISCOVERY RESULT"
    )

    print(
        "-" * 80
    )

    print(
        "Available:",
        discovery[
            "available"
        ],
    )

    print(
        "Datasets:",
        discovery[
            "dataset_count"
        ],
    )

    print(
        "Unique source times:",
        discovery[
            "time_count"
        ],
    )

    print(
        "Earliest:",
        discovery[
            "earliest_time_utc"
        ],
    )

    print(
        "Latest:",
        discovery[
            "latest_time_utc"
        ],
    )

    print()

    print(
        "DATASETS"
    )

    print(
        "-" * 80
    )

    for dataset in discovery[
        "datasets"
    ]:

        print()

        print(
            "Dataset:",
            dataset[
                "filename"
            ],
        )

        print(
            "TIME count:",
            dataset[
                "time_count"
            ],
        )

        print(
            "TIME start:",
            dataset[
                "time_start_utc"
            ],
        )

        print(
            "TIME end:",
            dataset[
                "time_end_utc"
            ],
        )

    print()

    print(
        "FIRST SOURCE TIMES"
    )

    print(
        "-" * 80
    )

    for record in discovery[
        "times"
    ][:20]:

        print(
            record[
                "time_utc"
            ],
            "->",
            record[
                "dataset"
            ],
            "index",
            record[
                "time_index"
            ],
        )

    # -------------------------------------------------------------------------
    # Optional exact time search.
    # -------------------------------------------------------------------------

    if args.find_time is not None:

        print()

        print(
            "EXACT TIME SEARCH"
        )

        print(
            "-" * 80
        )

        match = find_time(
            requested_time_utc=args.find_time,
            discovery=discovery,
        )

        print(
            json.dumps(
                match,
                indent=2,
                ensure_ascii=False,
            )
        )

    output_path = (
        save_time_catalog(
            discovery=discovery,
            filename=args.output,
        )
    )

    print()

    print(
        "TIME CATALOG SAVED"
    )

    print(
        output_path
    )

    print()

    print(
        "Synthetic times:",
        discovery[
            "scientific_rules"
        ][
            "synthetic_times"
        ],
    )

    print(
        "Interpolation:",
        discovery[
            "scientific_rules"
        ][
            "interpolation"
        ],
    )

    print()

    print(
        "=" * 80
    )

    print(
        "HYCOM TIME-STEP DISCOVERY COMPLETE"
    )

    print(
        "=" * 80
    )


if __name__ == "__main__":
    main()

