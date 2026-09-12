
from __future__ import annotations

"""
OceanSight-V
Multi-Step REAL HYCOM 4D A* Integration Test

Purpose
-------
Verify that the navigation engine can move through multiple REAL INCOIS
HYCOM model-time layers.

This test specifically checks that:

    time_index=0
        -> first real HYCOM model time selected for the search

    time_index=1
        -> next real HYCOM model time

    time_index=2
        -> next real HYCOM model time

and so on.

Scientific requirements
-----------------------
- Real INCOIS HYCOM data only.
- No synthetic data.
- No interpolation.
- No invented model timestamps.
- Every route state must correspond to an actual source timestamp.
- Multiple temporal layers must be traversed.
- Physical travel time must remain within each model interval.
"""

from datetime import datetime, timezone

from .navigation_astar import (
    OceanSightAStar,
)
from .navigation_environment import (
    NavigationEnvironment,
)
from .navigation_models import (
    NavigationConstraints,
    NavigationRequest,
    NavigationWeights,
)
from .navigation_time import (
    NavigationTimeAdapter,
)


# =============================================================================
# TEST CONSTANTS
# =============================================================================

START_LATITUDE = -8.20
START_LONGITUDE = 68.20

DESTINATION_LATITUDE = -8.10
DESTINATION_LONGITUDE = 68.30

START_DEPTH_M = 100.0
DESTINATION_DEPTH_M = 100.0

DEPARTURE_TIME_UTC = (
    "2026-09-10T06:00:00Z"
)

VESSEL_SPEED_M_S = 10.0

# Deliberately keep this value different from the HYCOM source cadence.
#
# This proves that A* is no longer constructing model times from
# request.time_step_minutes.
CONFIGURED_TIME_STEP_MINUTES = 60

LATITUDE_STEP_DEG = 0.05
LONGITUDE_STEP_DEG = 0.05
DEPTH_STEP_M = 50.0

MAX_ROUTE_DURATION_HOURS = 48.0


# =============================================================================
# ASSERTION HELPERS
# =============================================================================


def assert_true(
    condition: bool,
    message: str,
) -> None:

    if not condition:
        raise AssertionError(
            message
        )


# =============================================================================
# MAIN TEST
# =============================================================================


def main() -> None:

    print(
        "=" * 80
    )

    print(
        "OCEANSIGHT-V"
    )

    print(
        "MULTI-STEP REAL HYCOM 4D A* TEST"
    )

    print(
        "=" * 80
    )

    print()

    print(
        "Start:",
        START_LATITUDE,
        START_LONGITUDE,
    )

    print(
        "Destination:",
        DESTINATION_LATITUDE,
        DESTINATION_LONGITUDE,
    )

    print(
        "Departure:",
        DEPARTURE_TIME_UTC,
    )

    print(
        "Vessel speed:",
        VESSEL_SPEED_M_S,
        "m/s",
    )

    print(
        "Configured time_step_minutes:",
        CONFIGURED_TIME_STEP_MINUTES,
    )

    print()

    # =========================================================================
    # DISCOVER REAL HYCOM TIME AXIS
    # =========================================================================

    print(
        "Discovering REAL INCOIS HYCOM source times..."
    )

    time_adapter = (
        NavigationTimeAdapter.from_live_incois()
    )

    source_times = (
        time_adapter.available_model_times()
    )

    assert_true(
        len(source_times) >= 3,
        (
            "Test requires at least three real HYCOM "
            "source timestamps."
        ),
    )

    print(
        "Discovered source times:",
        len(source_times),
    )

    print()

    # =========================================================================
    # RESOLVE START MODEL TIME
    # =========================================================================

    resolved = (
        time_adapter.next_valid(
            DEPARTURE_TIME_UTC
        )
    )

    assert_true(
        resolved is not None,
        (
            "Unable to resolve vessel departure "
            "against real HYCOM source times."
        ),
    )

    assert resolved is not None

    starting_model_time = (
        resolved.model_time_utc
    )

    print(
        "Vessel departure time:",
        DEPARTURE_TIME_UTC,
    )

    print(
        "Starting HYCOM model time:",
        starting_model_time,
    )

    print(
        "Exact departure/model match:",
        resolved.exact_model_time,
    )

    print()

    # =========================================================================
    # BUILD REAL ENVIRONMENT
    # =========================================================================

    environment = NavigationEnvironment(
        time_adapter=time_adapter,
    )

    # =========================================================================
    # BUILD ASTAR
    # =========================================================================

    astar = OceanSightAStar(
        environment,
        latitude_step_deg=(
            LATITUDE_STEP_DEG
        ),
        longitude_step_deg=(
            LONGITUDE_STEP_DEG
        ),
        depth_step_m=(
            DEPTH_STEP_M
        ),
    )

    # =========================================================================
    # REQUEST
    # =========================================================================

    request = NavigationRequest(
        start={
            "latitude": START_LATITUDE,
            "longitude": START_LONGITUDE,
            "depth_m": START_DEPTH_M,
        },
        destination={
            "latitude": DESTINATION_LATITUDE,
            "longitude": DESTINATION_LONGITUDE,
            "depth_m": DESTINATION_DEPTH_M,
        },
        departure_time_utc=(
            DEPARTURE_TIME_UTC
        ),
        mode="logistics",
        constraints=NavigationConstraints(
            vessel_speed_m_s=(
                VESSEL_SPEED_M_S
            ),
            min_depth_m=0.0,
            max_depth_m=5000.0,
            max_route_duration_hours=(
                MAX_ROUTE_DURATION_HOURS
            ),
        ),
        weights=NavigationWeights(),
        time_step_minutes=(
            CONFIGURED_TIME_STEP_MINUTES
        ),
        allow_waiting=False,
        max_search_nodes=(
            250_000
        ),
    )

    # =========================================================================
    # SEARCH
    # =========================================================================

    print(
        "Running REAL HYCOM multi-step A*..."
    )

    search = astar.search(
        request
    )

    print()

    print(
        "SEARCH RESULT"
    )

    print(
        "-" * 80
    )

    print(
        "Found:",
        search.found,
    )

    print(
        "Message:",
        search.message,
    )

    print(
        "Expanded nodes:",
        search.expanded_nodes,
    )

    print(
        "Generated nodes:",
        search.generated_nodes,
    )

    print(
        "Route length:",
        len(
            search.route
        ),
    )

    print()

    assert_true(
        search.found,
        (
            "Multi-step real HYCOM-backed A* "
            "failed to find a route."
        ),
    )

    # =========================================================================
    # BASIC ROUTE REQUIREMENTS
    # =========================================================================

    assert_true(
        len(
            search.route
        ) >= 3,
        (
            "Multi-step test requires at least "
            "3 route states."
        ),
    )

    assert_true(
        search.route[0].time_index == 0,
        (
            "Route must begin at local "
            "time_index 0."
        ),
    )

    # =========================================================================
    # MODEL TIME PROVENANCE
    # =========================================================================

    model_times = (
        search.model_times_utc
        or []
    )

    assert_true(
        len(model_times) >= 3,
        (
            "A* result must contain at least "
            "three model-time layers."
        ),
    )

    assert_true(
        search.starting_model_time_utc
        == starting_model_time,
        (
            "A* starting model time does not match "
            "the resolved real HYCOM model time."
        ),
    )

    # =========================================================================
    # CHECK TEMPORAL PROGRESSION
    # =========================================================================

    print(
        "ROUTE TEMPORAL CHECK"
    )

    print(
        "-" * 80
    )

    previous_time_index = None

    used_time_indices: list[
        int
    ] = []

    for index, state in enumerate(
        search.route
    ):

        current_index = (
            state.time_index
        )

        assert_true(
            current_index >= 0,
            (
                f"Route state {index} has "
                "negative time_index."
            ),
        )

        assert_true(
            current_index
            < len(model_times),
            (
                f"Route state {index} references "
                "an invalid HYCOM model-time index."
            ),
        )

        if previous_time_index is not None:

            assert_true(
                current_index
                == previous_time_index + 1,
                (
                    "Model-time layers must advance "
                    "one real HYCOM source timestamp "
                    "at a time."
                ),
            )

        model_time = (
            model_times[
                current_index
            ]
        )

        print(
            f"  route[{index}]"
            f" -> time_index={current_index}"
            f" -> model_time={model_time}"
        )

        used_time_indices.append(
            current_index
        )

        previous_time_index = (
            current_index
        )

    # =========================================================================
    # REQUIRE MULTIPLE MODEL TIMES
    # =========================================================================

    unique_used_indices = list(
        dict.fromkeys(
            used_time_indices
        )
    )

    assert_true(
        len(
            unique_used_indices
        ) >= 2,
        (
            "Route must traverse multiple "
            "HYCOM model-time layers."
        ),
    )

    # =========================================================================
    # VERIFY ACTUAL MODEL TIME VALUES
    # =========================================================================

    print()

    print(
        "SOURCE-TIME INTEGRITY CHECK"
    )

    print(
        "-" * 80
    )

    for state in search.route:

        source_time = model_times[
            state.time_index
        ]

        # The timestamp must exactly match one of the REAL discovered
        # INCOIS source timestamps.

        assert_true(
            source_time in source_times,
            (
                "A* produced a model timestamp that "
                "is not present in the real HYCOM "
                "source-time catalog."
            ),
        )

        print(
            "  PASS:",
            source_time,
        )

    # =========================================================================
    # VERIFY REQUEST TIME IS NOT USED AS FAKE MODEL TIME
    # =========================================================================

    if (
        DEPARTURE_TIME_UTC
        != starting_model_time
    ):

        assert_true(
            DEPARTURE_TIME_UTC
            not in [
                model_times[
                    state.time_index
                ]
                for state in search.route
            ],
            (
                "The vessel departure time was incorrectly "
                "introduced as a HYCOM model timestamp."
            ),
        )

    # =========================================================================
    # VERIFY NO SYNTHETIC / INTERPOLATED DATA
    # =========================================================================

    print()

    print(
        "SCIENTIFIC INTEGRITY CHECK"
    )

    print(
        "-" * 80
    )

    for state in search.route:

        model_time = model_times[
            state.time_index
        ]

        sampled = (
            environment.sample(
                latitude=(
                    state.latitude
                ),
                longitude=(
                    state.longitude
                ),
                depth_m=(
                    state.depth_m
                ),
                time_utc=(
                    model_time
                ),
            )
        )

        environment.validate_scientific_integrity(
            sampled
        )

        assert_true(
            sampled.synthetic_data is False,
            (
                "Synthetic data detected in "
                "real HYCOM route."
            ),
        )

        assert_true(
            sampled.interpolation is False,
            (
                "Interpolation detected in "
                "real HYCOM route."
            ),
        )

        assert_true(
            sampled.actual_time_utc
            == model_time,
            (
                "Environment actual source time "
                "does not equal the requested real "
                "HYCOM model time."
            ),
        )

        print(
            "  PASS:",
            model_time,
            "dataset=",
            sampled.hycom_dataset,
        )

    # =========================================================================
    # VERIFY MODEL INTERVALS
    # =========================================================================

    print()

    print(
        "MODEL INTERVAL CHECK"
    )

    print(
        "-" * 80
    )

    for index in range(
        len(
            unique_used_indices
        )
        - 1
    ):

        current_index = (
            unique_used_indices[
                index
            ]
        )

        next_index = (
            unique_used_indices[
                index + 1
            ]
        )

        current_dt = datetime.fromisoformat(
            model_times[
                current_index
            ].replace(
                "Z",
                "+00:00",
            )
        ).astimezone(
            timezone.utc
        )

        next_dt = datetime.fromisoformat(
            model_times[
                next_index
            ].replace(
                "Z",
                "+00:00",
            )
        ).astimezone(
            timezone.utc
        )

        interval_seconds = (
            next_dt
            - current_dt
        ).total_seconds()

        assert_true(
            interval_seconds > 0.0,
            (
                "HYCOM source-time sequence "
                "must be strictly increasing."
            ),
        )

        print(
            "  ",
            model_times[
                current_index
            ],
            "->",
            model_times[
                next_index
            ],
            "=",
            interval_seconds,
            "seconds",
        )

    # =========================================================================
    # FINAL REPORT
    # =========================================================================

    print()

    print(
        "ROUTE"
    )

    print(
        "-" * 80
    )

    for index, state in enumerate(
        search.route
    ):

        model_time = model_times[
            state.time_index
        ]

        print(
            "  ",
            index,
            "lat=",
            f"{state.latitude:.6f}",
            "lon=",
            f"{state.longitude:.6f}",
            "depth=",
            f"{state.depth_m:.1f}m",
            "time_index=",
            state.time_index,
            "model_time=",
            model_time,
        )

    print()

    print(
        "REAL HYCOM MULTI-STEP 4D A* TEST: PASS"
    )

    print(
        "=" * 80
    )


if __name__ == "__main__":
    main()

