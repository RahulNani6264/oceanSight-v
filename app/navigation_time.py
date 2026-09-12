from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from .hycom_times import (
    datetime_to_iso,
    discover_hycom_times,
    find_time,
    parse_utc,
)


# =============================================================================
# OCEANSIGHT-V
# NAVIGATION TIME ADAPTER
#
# Purpose:
#
#   Keep navigation/vessel time separate from HYCOM model source time.
#
# Scientific rules:
#
#   - HYCOM model timestamps come only from the real INCOIS TIME coordinate.
#   - No synthetic model timestamps.
#   - No interpolation.
#   - A vessel may travel between model timestamps.
#   - Environmental states are evaluated only at valid real HYCOM timestamps.
#   - Requested/vessel time is never silently rewritten as model time.
#
# =============================================================================


UTC = timezone.utc


# =============================================================================
# DATA MODEL
# =============================================================================

@dataclass(frozen=True)
class NavigationTimePoint:
    """
    Represents one navigation-time observation point.

    vessel_time_utc:
        Physical time used by the navigation search.

    model_time_utc:
        Actual INCOIS HYCOM source TIME used for environmental data.

    source_dataset:
        HYCOM dataset containing the source timestamp.

    source_time_index:
        Index of the source TIME coordinate within that dataset.

    exact_model_time:
        True when vessel time exactly equals the model source time.

    model_time_offset_seconds:
        Difference:

            model_time - vessel_time

        Positive means the model timestamp is later than vessel time.
    """

    vessel_time_utc: str
    model_time_utc: str
    source_dataset: str
    source_dataset_url: str
    source_time_index: int
    exact_model_time: bool
    model_time_offset_seconds: float


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def _normalize_utc(value: datetime) -> datetime:
    """
    Normalize datetime to timezone-aware UTC.
    """

    if value.tzinfo is None:

        raise ValueError(
            "Navigation datetime must be timezone-aware."
        )

    return value.astimezone(UTC)


def _parse_vessel_time(value: str) -> datetime:
    """
    Parse a navigation/vessel timestamp.

    Requires explicit timezone information.
    """

    parsed = parse_utc(value)

    if parsed.tzinfo is None:

        raise ValueError(
            "Navigation timestamp must be timezone-aware UTC."
        )

    return _normalize_utc(parsed)


def _time_difference_seconds(
    vessel_time: datetime,
    model_time: datetime,
) -> float:
    """
    Return model_time - vessel_time in seconds.
    """

    return (
        model_time - vessel_time
    ).total_seconds()


# =============================================================================
# NAVIGATION TIME ADAPTER
# =============================================================================

class NavigationTimeAdapter:
    """
    Adapter between vessel/navigation time and real HYCOM source time.

    The adapter deliberately does NOT invent model timestamps.

    Example:

        vessel time = 2026-09-10T07:00:00Z

        HYCOM source times =
            2026-09-10T06:00:00Z
            2026-09-10T12:00:00Z

    Result:

        vessel time remains:
            07:00Z

        next valid model time:
            12:00Z

    Therefore the caller can distinguish:

        vessel_time_utc = 07:00Z
        model_time_utc  = 12:00Z

    instead of pretending HYCOM contains a 07:00Z record.
    """

    def __init__(
        self,
        discovery: dict[str, Any],
    ) -> None:

        self.discovery = discovery

        if not discovery.get(
            "available",
            False,
        ):

            raise ValueError(
                "HYCOM time discovery returned no available source times."
            )

        self.times: list[
            dict[str, Any]
        ] = list(
            discovery.get(
                "times",
                [],
            )
        )

        if not self.times:

            raise ValueError(
                "HYCOM discovery contains no source TIME records."
            )

        self._parsed_times: list[
            tuple[datetime, dict[str, Any]]
        ] = []

        for record in self.times:

            time_text = record.get(
                "time_utc"
            )

            if not time_text:

                continue

            parsed = parse_utc(
                time_text
            )

            self._parsed_times.append(
                (
                    _normalize_utc(parsed),
                    record,
                )
            )

        self._parsed_times.sort(
            key=lambda item: item[0]
        )

        if not self._parsed_times:

            raise ValueError(
                "HYCOM discovery contains no valid source timestamps."
            )

    # -------------------------------------------------------------------------
    # Discovery constructors
    # -------------------------------------------------------------------------

    @classmethod
    def from_live_incois(
        cls,
        max_datasets: int = 7,
    ) -> "NavigationTimeAdapter":
        """
        Discover real HYCOM source timestamps directly from INCOIS.
        """

        discovery = discover_hycom_times(
            max_datasets=max_datasets
        )

        return cls(
            discovery=discovery
        )

    # -------------------------------------------------------------------------
    # Coverage
    # -------------------------------------------------------------------------

    @property
    def earliest_model_time_utc(self) -> str:
        """
        Earliest real HYCOM source timestamp.
        """

        return datetime_to_iso(
            self._parsed_times[0][0]
        )

    @property
    def latest_model_time_utc(self) -> str:
        """
        Latest real HYCOM source timestamp.
        """

        return datetime_to_iso(
            self._parsed_times[-1][0]
        )

    # -------------------------------------------------------------------------
    # Exact model time
    # -------------------------------------------------------------------------

    def exact(
        self,
        vessel_time_utc: str,
    ) -> NavigationTimePoint | None:
        """
        Return a model observation only when vessel time exactly matches
        a real HYCOM source timestamp.

        No interpolation.
        No time shifting.
        """

        vessel_time = _parse_vessel_time(
            vessel_time_utc
        )

        requested_iso = datetime_to_iso(
            vessel_time
        )

        result = find_time(
            requested_time_utc=requested_iso,
            discovery=self.discovery,
        )

        if not result.get(
            "available",
            False,
        ):

            return None

        model_time = parse_utc(
            result[
                "actual_time_utc"
            ]
        )

        model_time = _normalize_utc(
            model_time
        )

        return NavigationTimePoint(
            vessel_time_utc=requested_iso,
            model_time_utc=datetime_to_iso(
                model_time
            ),
            source_dataset=result[
                "dataset"
            ],
            source_dataset_url=result[
                "dataset_url"
            ],
            source_time_index=int(
                result[
                    "time_index"
                ]
            ),
            exact_model_time=True,
            model_time_offset_seconds=0.0,
        )

    # -------------------------------------------------------------------------
    # Next valid model time
    # -------------------------------------------------------------------------

    def next_valid(
        self,
        vessel_time_utc: str,
    ) -> NavigationTimePoint | None:
        """
        Return the first real HYCOM model timestamp at or after vessel time.

        Important:

            vessel time is NOT modified.

        Example:

            vessel = 07:00Z
            source  = 06:00Z, 12:00Z

            result:
                vessel = 07:00Z
                model  = 12:00Z

        No interpolation is performed.
        """

        vessel_time = _parse_vessel_time(
            vessel_time_utc
        )

        vessel_iso = datetime_to_iso(
            vessel_time
        )

        for model_time, record in self._parsed_times:

            if model_time < vessel_time:

                continue

            return NavigationTimePoint(
                vessel_time_utc=vessel_iso,
                model_time_utc=datetime_to_iso(
                    model_time
                ),
                source_dataset=record[
                    "dataset"
                ],
                source_dataset_url=record[
                    "dataset_url"
                ],
                source_time_index=int(
                    record[
                        "time_index"
                    ]
                ),
                exact_model_time=(
                    model_time == vessel_time
                ),
                model_time_offset_seconds=(
                    _time_difference_seconds(
                        vessel_time,
                        model_time,
                    )
                ),
            )

        return None

    # -------------------------------------------------------------------------
    # Previous valid model time
    # -------------------------------------------------------------------------

    def previous_valid(
        self,
        vessel_time_utc: str,
    ) -> NavigationTimePoint | None:
        """
        Return the latest real HYCOM model timestamp at or before vessel time.

        No interpolation is performed.
        """

        vessel_time = _parse_vessel_time(
            vessel_time_utc
        )

        vessel_iso = datetime_to_iso(
            vessel_time
        )

        selected: (
            tuple[
                datetime,
                dict[str, Any]
            ]
            | None
        ) = None

        for model_time, record in self._parsed_times:

            if model_time > vessel_time:

                break

            selected = (
                model_time,
                record,
            )

        if selected is None:

            return None

        model_time, record = selected

        return NavigationTimePoint(
            vessel_time_utc=vessel_iso,
            model_time_utc=datetime_to_iso(
                model_time
            ),
            source_dataset=record[
                "dataset"
            ],
            source_dataset_url=record[
                "dataset_url"
            ],
            source_time_index=int(
                record[
                    "time_index"
                ]
            ),
            exact_model_time=(
                model_time == vessel_time
            ),
            model_time_offset_seconds=(
                _time_difference_seconds(
                    vessel_time,
                    model_time,
                )
            ),
        )

    # -------------------------------------------------------------------------
    # Next model timestamp after current source time
    # -------------------------------------------------------------------------

    def next_model_time(
        self,
        model_time_utc: str,
    ) -> NavigationTimePoint | None:
        """
        Return the next real HYCOM source timestamp strictly after
        the supplied model timestamp.
        """

        current = _parse_vessel_time(
            model_time_utc
        )

        for model_time, record in self._parsed_times:

            if model_time <= current:

                continue

            iso = datetime_to_iso(
                current
            )

            return NavigationTimePoint(
                vessel_time_utc=iso,
                model_time_utc=datetime_to_iso(
                    model_time
                ),
                source_dataset=record[
                    "dataset"
                ],
                source_dataset_url=record[
                    "dataset_url"
                ],
                source_time_index=int(
                    record[
                        "time_index"
                    ]
                ),
                exact_model_time=False,
                model_time_offset_seconds=(
                    _time_difference_seconds(
                        current,
                        model_time,
                    )
                ),
            )

        return None

    # -------------------------------------------------------------------------
    # Model interval
    # -------------------------------------------------------------------------

    def model_interval_seconds(
        self,
        model_time_utc: str,
    ) -> float | None:
        """
        Return the real interval from a model timestamp to the next
        available HYCOM timestamp.

        This is useful for physically bounding vessel travel during
        one environmental-model interval.
        """

        current = _parse_vessel_time(
            model_time_utc
        )

        for index, (
            model_time,
            _record,
        ) in enumerate(
            self._parsed_times
        ):

            if model_time != current:

                continue

            if index + 1 >= len(
                self._parsed_times
            ):

                return None

            next_time = self._parsed_times[
                index + 1
            ][0]

            return (
                next_time - model_time
            ).total_seconds()

        return None

    # -------------------------------------------------------------------------
    # Available model timestamps
    # -------------------------------------------------------------------------

    def available_model_times(
        self,
    ) -> list[str]:
        """
        Return all real HYCOM source timestamps.
        """

        return [
            datetime_to_iso(
                model_time
            )
            for model_time, _record
            in self._parsed_times
        ]

    # -------------------------------------------------------------------------
    # Navigation window validation
    # -------------------------------------------------------------------------

    def validate_vessel_time(
        self,
        vessel_time_utc: str,
    ) -> dict[str, Any]:
        """
        Validate a vessel/navigation timestamp against HYCOM coverage.

        This does not rewrite the requested time.
        """

        vessel_time = _parse_vessel_time(
            vessel_time_utc
        )

        vessel_iso = datetime_to_iso(
            vessel_time
        )

        earliest = self._parsed_times[
            0
        ][0]

        latest = self._parsed_times[
            -1
        ][0]

        exact_match = (
            vessel_time in {
                parsed
                for parsed, _record
                in self._parsed_times
            }
        )

        return {
            "available": (
                earliest
                <= vessel_time
                <= latest
            ),
            "vessel_time_utc": vessel_iso,
            "exact_model_time": exact_match,
            "earliest_model_time_utc": (
                datetime_to_iso(
                    earliest
                )
            ),
            "latest_model_time_utc": (
                datetime_to_iso(
                    latest
                )
            ),
            "synthetic_data": False,
            "interpolation": False,
        }


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def discover_navigation_time(
    max_datasets: int = 7,
) -> NavigationTimeAdapter:
    """
    Create a navigation time adapter from the live INCOIS catalog.
    """

    return NavigationTimeAdapter.from_live_incois(
        max_datasets=max_datasets
    )


def resolve_next_model_time(
    vessel_time_utc: str,
    max_datasets: int = 7,
) -> NavigationTimePoint | None:
    """
    Discover live HYCOM times and resolve the next valid model time.
    """

    adapter = discover_navigation_time(
        max_datasets=max_datasets
    )

    return adapter.next_valid(
        vessel_time_utc
    )


# =============================================================================
# COMMAND LINE TEST
# =============================================================================

def main() -> None:
    import argparse
    import json

    parser = argparse.ArgumentParser(
        description=(
            "Inspect real INCOIS HYCOM source time handling "
            "for OceanSight-V navigation."
        )
    )

    parser.add_argument(
        "--max-datasets",
        type=int,
        default=7,
    )

    parser.add_argument(
        "--time",
        type=str,
        required=True,
        help=(
            "Vessel/navigation UTC time, "
            "for example 2026-09-10T07:00:00Z."
        ),
    )

    args = parser.parse_args()

    adapter = discover_navigation_time(
        max_datasets=args.max_datasets
    )

    print()
    print("=" * 80)
    print(
        "OCEANSIGHT-V NAVIGATION TIME ADAPTER"
    )
    print("=" * 80)
    print()

    print(
        "HYCOM coverage:"
    )

    print(
        "  Earliest:",
        adapter.earliest_model_time_utc,
    )

    print(
        "  Latest:",
        adapter.latest_model_time_utc,
    )

    print()

    validation = adapter.validate_vessel_time(
        args.time
    )

    print(
        "VESSEL TIME VALIDATION"
    )

    print(
        json.dumps(
            validation,
            indent=2,
        )
    )

    print()

    exact = adapter.exact(
        args.time
    )

    print(
        "EXACT MODEL MATCH"
    )

    if exact is None:

        print(
            "  None"
        )

    else:

        print(
            json.dumps(
                exact.__dict__,
                indent=2,
            )
        )

    print()

    next_valid = adapter.next_valid(
        args.time
    )

    print(
        "NEXT VALID MODEL TIME"
    )

    if next_valid is None:

        print(
            "  None"
        )

    else:

        print(
            json.dumps(
                next_valid.__dict__,
                indent=2,
            )
        )

    print()

    print(
        "AVAILABLE SOURCE TIMES"
    )

    for value in adapter.available_model_times():

        print(
            " ",
            value,
        )

    print()

    print("=" * 80)
    print(
        "NAVIGATION TIME ADAPTER TEST COMPLETE"
    )
    print("=" * 80)


if __name__ == "__main__":
    main()