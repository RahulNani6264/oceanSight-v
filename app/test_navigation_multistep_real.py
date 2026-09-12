
from __future__ import annotations

"""
OceanSight-V
REAL HYCOM 4D A* Boundary-Synchronization Test

Purpose
-------
This test verifies the temporal architecture of the navigation engine
using REAL INCOIS HYCOM source states.

Required behavior:

1. Vessel time is continuous and physically accumulated.
2. HYCOM model times come only from real INCOIS source timestamps.
3. No synthetic timestamps are created.
4. No interpolation is used.
5. Model time never moves backward.
6. A real HYCOM boundary can be crossed through an explicit
   same-position synchronization/wait transition.
7. Real bathymetry and current traversability remain enabled.

Test design
-----------
The route is deliberately long and the vessel deliberately slow enough
that reaching the destination before the first 6-hour HYCOM boundary is
physically unlikely.

The test stays within the real GEBCO coverage around the starting point.
"""

from datetime import datetime, timezone

from .navigation_astar import OceanSightAStar
from .navigation_environment import NavigationEnvironment
from .navigation_models import (
    NavigationConstraints,
    NavigationRequest,
    NavigationWeights,
)
from .navigation_time import NavigationTimeAdapter


# =============================================================================
# TEST CONFIGURATION
# =============================================================================

START_LATITUDE = -8.20
START_LONGITUDE = 68.20

# Keep the route inside the GEBCO region around the test point.
#
# The existing downloaded GEBCO coverage includes approximately:
#
#     latitude  -8.3979 -> -7.9021
#     longitude  67.7521 -> 68.4979
#
# Therefore this destination remains inside that region.
DESTINATION_LATITUDE = -7.925
DESTINATION_LONGITUDE = 68.20

START_DEPTH_M = 100.0
DESTINATION_DEPTH_M = 100.0

DEPARTURE_TIME_UTC = "2026-09-10T06:00:00Z"

# Deliberately slow, but not so slow that normal current effects make
# essentially every edge impossible.
VESSEL_SPEED_M_S = 1.2

# This is intentionally NOT interpreted as the HYCOM cadence.
CONFIGURED_TIME_STEP_MINUTES = 60

# Spatial resolution.
LATITUDE_STEP_DEG = 0.025
LONGITUDE_STEP_DEG = 0.05
DEPTH_STEP_M = 50.0

MAX_ROUTE_DURATION_HOURS = 48.0
MAX_SEARCH_NODES = 250_000


# =============================================================================
# HELPERS
# =============================================================================

def assert_true(
    condition: bool,
    message: str,
) -> None:

    if not condition:
        raise AssertionError(message)


def parse_test_utc(
    value: str,
) -> datetime:

    text = str(value).strip()

    if text.endswith("Z"):
        text = text[:-1] + "+00:00"

    parsed = datetime.fromisoformat(text)

    if parsed.tzinfo is None:
        raise ValueError(
            "Timestamp must include an explicit timezone."
        )

    return parsed.astimezone(timezone.utc)


# =============================================================================
# MAIN TEST
# =============================================================================

def main() -> None:

    print("=" * 80)
    print("OCEANSIGHT-V")
    print("REAL HYCOM 4D A* BOUNDARY-SYNCHRONIZATION TEST")
    print("=" * 80)

    print()
    print("Start:", START_LATITUDE, START_LONGITUDE)
    print(
        "Destination:",
        DESTINATION_LATITUDE,
        DESTINATION_LONGITUDE,
    )
    print("Depth:", START_DEPTH_M, "m")
    print("Departure:", DEPARTURE_TIME_UTC)
    print("Vessel speed:", VESSEL_SPEED_M_S, "m/s")
    print(
        "Configured time_step_minutes:",
        CONFIGURED_TIME_STEP_MINUTES,
    )

    # =========================================================================
    # REAL HYCOM SOURCE-TIME CATALOG
    # =========================================================================

    print()
    print("Discovering REAL INCOIS HYCOM source times...")

    time_adapter = (
        NavigationTimeAdapter.from_live_incois()
    )

    source_times = (
        time_adapter.available_model_times()
    )

    assert_true(
        len(source_times) >= 3,
        (
            "Expected at least three real INCOIS HYCOM "
            f"source timestamps; found {len(source_times)}."
        ),
    )

    print(
        "Discovered source times:",
        len(source_times),
    )

    # =========================================================================
    # RESOLVE DEPARTURE
    # =========================================================================

    resolved_start = (
        time_adapter.next_valid(
            DEPARTURE_TIME_UTC
        )
    )

    assert_true(
        resolved_start is not None,
        (
            "Could not resolve vessel departure "
            "against the real HYCOM source-time catalog."
        ),
    )

    assert resolved_start is not None

    starting_model_time = (
        resolved_start.model_time_utc
    )

    print()
    print(
        "Vessel departure:",
        DEPARTURE_TIME_UTC,
    )

    print(
        "Starting HYCOM model time:",
        starting_model_time,
    )

    # =========================================================================
    # NEXT REAL HYCOM BOUNDARY
    # =========================================================================

    next_model = (
        time_adapter.next_model_time(
            starting_model_time
        )
    )

    assert_true(
        next_model is not None,
        (
            "Could not find the next real HYCOM "
            "source-time boundary."
        ),
    )

    assert next_model is not None

    next_boundary_time = (
        next_model.model_time_utc
    )

    starting_dt = parse_test_utc(
        starting_model_time
    )

    next_boundary_dt = parse_test_utc(
        next_boundary_time
    )

    boundary_interval_seconds = (
        next_boundary_dt - starting_dt
    ).total_seconds()
    
    assert_true(
        boundary_interval_seconds > 0.0,
        (
            "HYCOM boundary interval must "
            "be positive."
        ),
    )

    print(
        "Next HYCOM boundary:",
        next_boundary_time,
    )

    print(
        "Boundary interval:",
        boundary_interval_seconds,
        "seconds",
    )

    # =========================================================================
    # REAL ENVIRONMENT
    # =========================================================================

    environment = NavigationEnvironment(
        time_adapter=time_adapter,
    )

    # =========================================================================
    # ASTAR
    # =========================================================================

    astar = OceanSightAStar(
        environment,
        latitude_step_deg=LATITUDE_STEP_DEG,
        longitude_step_deg=LONGITUDE_STEP_DEG,
        depth_step_m=DEPTH_STEP_M,
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

        departure_time_utc=DEPARTURE_TIME_UTC,

        minimum_arrival_time_utc=next_boundary_time,

        mode="logistics",

        constraints=NavigationConstraints(
            vessel_speed_m_s=VESSEL_SPEED_M_S,
            min_depth_m=0.0,
            max_depth_m=5000.0,
            max_route_duration_hours=(
                MAX_ROUTE_DURATION_HOURS
            ),
        ),

        weights=NavigationWeights(),

        # Deliberately not equal to HYCOM source cadence.
        time_step_minutes=(
            CONFIGURED_TIME_STEP_MINUTES
        ),

        # Explicit synchronization is permitted.
        allow_waiting=True,

        max_search_nodes=MAX_SEARCH_NODES,
    )

    # =========================================================================
    # RUN A*
    # =========================================================================

    print()
    print(
        "Running REAL HYCOM boundary-aware A*..."
    )

    search = astar.search(
        request
    )

    print()
    print("SEARCH RESULT")
    print("-" * 80)

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
        len(search.route),
    )

    assert_true(
        search.found,
        (
            "Boundary-aware real HYCOM A* failed "
            "to find a route."
        ),
    )

    assert_true(
        len(search.route) >= 3,
        (
            "Expected multiple route states."
        ),
    )

    # =========================================================================
    # MODEL-TIME PROVENANCE
    # =========================================================================

    model_times = (
        search.model_times_utc
        or []
    )

    assert_true(
        len(model_times) >= 3,
        (
            "A* did not return enough real "
            "HYCOM model timestamps."
        ),
    )

    assert_true(
        search.starting_model_time_utc
        == starting_model_time,
        (
            "A* starting model time does not "
            "match the real HYCOM source time."
        ),
    )

    # =========================================================================
    # MODEL TIME ORDER
    # =========================================================================

    print()
    print("ROUTE TEMPORAL CHECK")
    print("-" * 80)

    previous_time_index = None
    used_model_indices: list[int] = []

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
                "negative model-time index."
            ),
        )

        assert_true(
            current_index < len(model_times),
            (
                f"Route state {index} references "
                "an invalid model-time index."
            ),
        )

        if previous_time_index is not None:

            assert_true(
                current_index >= previous_time_index,
                (
                    "Model-time index moved backward."
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

        used_model_indices.append(
            current_index
        )

        previous_time_index = (
            current_index
        )

    unique_model_indices = list(
        dict.fromkeys(
            used_model_indices
        )
    )

    assert_true(
        len(unique_model_indices) >= 2,
        (
            "The route did not cross a real "
            "HYCOM model-time boundary."
        ),
    )

    # =========================================================================
    # EXPLICIT SYNCHRONIZATION
    # =========================================================================

    print()
    print("MODEL-TIME SYNCHRONIZATION CHECK")
    print("-" * 80)

    synchronization_found = False

    for previous, current in zip(
        search.route,
        search.route[1:],
    ):

        if (
            current.time_index
            <= previous.time_index
        ):
            continue

        same_position = (
            abs(
                current.latitude
                - previous.latitude
            ) <= 1.0e-12
            and
            abs(
                current.longitude
                - previous.longitude
            ) <= 1.0e-12
            and
            abs(
                current.depth_m
                - previous.depth_m
            ) <= 1.0e-12
        )

        if same_position:

            synchronization_found = True

            previous_model_time = (
                model_times[
                    previous.time_index
                ]
            )

            current_model_time = (
                model_times[
                    current.time_index
                ]
            )

            print(
                "EXPLICIT MODEL-TIME SYNCHRONIZATION FOUND"
            )

            print(
                "  Location:",
                current.latitude,
                current.longitude,
            )

            print(
                "  Previous model time:",
                previous_model_time,
            )

            print(
                "  Next model time:",
                current_model_time,
            )

            break

    assert_true(
        synchronization_found,
        (
            "Model-time changed without an explicit "
            "same-position synchronization transition."
        ),
    )

    # =========================================================================
    # PHYSICAL VESSEL TIME
    # =========================================================================

    print()
    print("VESSEL TIME CHECK")
    print("-" * 80)

    vessel_elapsed = (
        search.vessel_elapsed_seconds
        or []
    )

    assert_true(
        len(vessel_elapsed)
        == len(search.route),
        (
            "A* must provide one physical vessel "
            "elapsed-time value per route state."
        ),
    )

    previous_elapsed = None

    for index, elapsed_seconds in enumerate(
        vessel_elapsed
    ):

        assert_true(
            elapsed_seconds >= 0.0,
            (
                f"Route state {index} contains "
                "negative vessel elapsed time."
            ),
        )

        if previous_elapsed is not None:

            assert_true(
                elapsed_seconds >= previous_elapsed,
                (
                    "Physical vessel time moved backward."
                ),
            )

        print(
            f"  route[{index}]"
            f" -> vessel_elapsed="
            f"{elapsed_seconds:.3f}s"
        )

        previous_elapsed = (
            elapsed_seconds
        )

    final_vessel_elapsed = (
        vessel_elapsed[-1]
    )

    print()
    print(
        "Final vessel elapsed time:",
        final_vessel_elapsed,
        "seconds",
    )

    print(
        "Final vessel elapsed time:",
        final_vessel_elapsed / 3600.0,
        "hours",
    )

    assert_true(
        final_vessel_elapsed
        > boundary_interval_seconds,
        (
            "Final physical vessel time did not "
            "cross the first real HYCOM boundary."
        ),
    )

    # =========================================================================
    # REAL HYCOM SOURCE-TIME CHECK
    # =========================================================================

    print()
    print("SOURCE-TIME INTEGRITY CHECK")
    print("-" * 80)

    for state in search.route:

        source_time = (
            model_times[
                state.time_index
            ]
        )

        assert_true(
            source_time in source_times,
            (
                "Route references a model time "
                "that is not present in the real "
                "INCOIS HYCOM source catalog."
            ),
        )

        print(
            "  PASS:",
            source_time,
        )

    # =========================================================================
    # SCIENTIFIC INTEGRITY
    # =========================================================================

    print()
    print("SCIENTIFIC INTEGRITY CHECK")
    print("-" * 80)

    for state in search.route:

        model_time = (
            model_times[
                state.time_index
            ]
        )

        sampled = environment.sample(
            latitude=state.latitude,
            longitude=state.longitude,
            depth_m=state.depth_m,
            time_utc=model_time,
        )

        environment.validate_scientific_integrity(
            sampled
        )

        assert_true(
            sampled.synthetic_data is False,
            "Synthetic data detected.",
        )

        assert_true(
            sampled.interpolation is False,
            "Interpolation detected.",
        )

        assert_true(
            sampled.actual_time_utc
            == model_time,
            (
                "Environmental source time does not "
                "match the exact HYCOM model time."
            ),
        )

        print(
            "  PASS:",
            model_time,
            "dataset=",
            sampled.hycom_dataset,
        )

    # =========================================================================
    # FINAL ROUTE
    # =========================================================================

    print()
    print("FINAL ROUTE")
    print("-" * 80)

    for index, state in enumerate(
        search.route
    ):

        model_time = (
            model_times[
                state.time_index
            ]
        )

        elapsed = (
            vessel_elapsed[
                index
            ]
        )

        print(
            f"  {index}"
            f" lat={state.latitude:.6f}"
            f" lon={state.longitude:.6f}"
            f" depth={state.depth_m:.1f}m"
            f" time_index={state.time_index}"
            f" model_time={model_time}"
            f" vessel_elapsed={elapsed:.1f}s"
        )

    print()
    print(
        "REAL HYCOM 4D A* "
        "BOUNDARY-SYNCHRONIZATION TEST: PASS"
    )

    print("=" * 80)


if __name__ == "__main__":
    main()

