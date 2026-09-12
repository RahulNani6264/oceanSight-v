
from __future__ import annotations

"""
Controlled functional test for OceanSight-V 4D A*.

This uses a deterministic TEST ENVIRONMENT ONLY.

It does not represent scientific ocean observations.

It exists solely to verify:
    start -> neighbors -> costs -> A* -> goal -> route reconstruction

Temporal contract:
    - time_index starts at 0.
    - time_index never moves backward.
    - time_index may remain unchanged while physical vessel time is still
      inside the same HYCOM-model state interval.
    - A* must not require one model-time increment per spatial edge.
"""


from app.navigation_astar import (
    OceanSightAStar,
)
from app.navigation_environment import (
    NavigationEnvironment,
    NavigationEnvironmentState,
)
from app.navigation_models import (
    NavigationConstraints,
    NavigationRequest,
    NavigationWaypoint,
    NavigationWeights,
)


# =============================================================================
# CONTROLLED ENVIRONMENT
# =============================================================================


class ControlledNavigationEnvironment(
    NavigationEnvironment
):
    """
    Deterministic in-memory environment for algorithm testing.

    Every valid state gets the same non-zero current.

    No real scientific data is used here.
    """

    def sample(
        self,
        *,
        latitude: float,
        longitude: float,
        depth_m: float,
        time_utc: str,
    ) -> NavigationEnvironmentState:

        return NavigationEnvironmentState(
            requested_latitude=latitude,
            requested_longitude=longitude,
            requested_depth_m=depth_m,
            requested_time_utc=time_utc,

            actual_latitude=latitude,
            actual_longitude=longitude,
            actual_depth_m=depth_m,
            actual_time_utc=time_utc,

            temperature_c=25.0,
            salinity_psu=35.0,

            u_current_m_s=0.10,
            v_current_m_s=0.05,
            current_speed_m_s=0.1118033989,
            current_direction_math_deg=26.565051177,

            ssh_m=0.0,

            bathymetry_elevation_m=-4000.0,
            bathymetry_depth_m=4000.0,

            hycom_available=True,
            bathymetry_available=True,

            hycom_source="TEST_FIXTURE",
            hycom_dataset="CONTROLLED_TEST_ENVIRONMENT",
            hycom_source_url=None,

            bathymetry_source="TEST_FIXTURE",
            bathymetry_dataset="CONTROLLED_TEST_ENVIRONMENT",
            bathymetry_source_url=None,

            hycom_missing={
                "temperature": False,
                "salinity": False,
                "u_current": False,
                "v_current": False,
                "ssh": False,
            },

            synthetic_data=False,
            interpolation=False,

            provenance={
                "test_fixture": True,
                "scientific_data": False,
            },
        )


# =============================================================================
# MAIN TEST
# =============================================================================


def main() -> None:

    environment = (
        ControlledNavigationEnvironment()
    )

    engine = OceanSightAStar(
        environment,
        latitude_step_deg=0.05,
        longitude_step_deg=0.05,
        depth_step_m=50.0,
    )

    request = NavigationRequest(

        mode="logistics",

        start=NavigationWaypoint(
            latitude=-8.20,
            longitude=68.20,
            depth_m=100.0,
            name="START",
        ),

        destination=NavigationWaypoint(
            latitude=-8.15,
            longitude=68.25,
            depth_m=100.0,
            name="GOAL",
        ),

        departure_time_utc=(
            "2026-09-10T06:00:00Z"
        ),

        constraints=NavigationConstraints(
            vessel_speed_m_s=10.0,
            max_route_duration_hours=6.0,
            max_depth_m=500.0,
            min_depth_m=0.0,
            avoid_currents_above_m_s=None,
            avoid_hazards=True,
        ),

        weights=NavigationWeights(
            distance_weight=1.0,
            current_penalty_weight=1.0,
            hazard_penalty_weight=1.0,
            time_penalty_weight=1.0,
            waiting_penalty_weight=0.25,
        ),

        requested_depth_m=100.0,

        allow_waiting=False,

        max_search_nodes=100,

        # Kept intentionally for API compatibility.
        #
        # The corrected A* temporal model does NOT use this value to
        # invent environmental timestamps.
        time_step_minutes=60,
    )

    result = engine.search(
        request
    )

    print(
        "=" * 72
    )

    print(
        "OCEANSIGHT-V CONTROLLED 4D A* TEST"
    )

    print(
        "=" * 72
    )

    print(
        "Found:",
        result.found,
    )

    print(
        "Message:",
        result.message,
    )

    print(
        "Expanded nodes:",
        result.expanded_nodes,
    )

    print(
        "Generated nodes:",
        result.generated_nodes,
    )

    print(
        "Route length:",
        len(
            result.route
        ),
    )

    if not result.found:

        raise AssertionError(
            "Controlled A* failed to find the expected route."
        )

    if len(
        result.route
    ) < 2:

        raise AssertionError(
            "A* returned a route with insufficient states."
        )

    # =========================================================================
    # START VALIDATION
    # =========================================================================

    start = result.route[
        0
    ]

    if (
        abs(
            start.latitude
            + 8.20
        )
        > 1e-9
        or abs(
            start.longitude
            - 68.20
        )
        > 1e-9
    ):

        raise AssertionError(
            "Route does not begin at the requested start."
        )

    if (
        abs(
            start.depth_m
            - 100.0
        )
        > 1e-9
    ):

        raise AssertionError(
            "Route does not begin at the requested depth."
        )

    # =========================================================================
    # GOAL VALIDATION
    # =========================================================================

    goal = result.route[
        -1
    ]

    if (
        abs(
            goal.latitude
            + 8.15
        )
        > 1e-9
        or abs(
            goal.longitude
            - 68.25
        )
        > 1e-9
    ):

        raise AssertionError(
            "Route does not reach the requested destination."
        )

    if (
        abs(
            goal.depth_m
            - 100.0
        )
        > 1e-9
    ):

        raise AssertionError(
            "Route does not reach the requested destination depth."
        )

    # =========================================================================
    # TIME-INDEX VALIDATION
    # =========================================================================

    time_indices = [
        state.time_index
        for state in result.route
    ]

    if time_indices[
        0
    ] != 0:

        raise AssertionError(
            "Route must begin at time_index 0."
        )

    # -------------------------------------------------------------------------
    # Corrected temporal contract:
    #
    # time_index may remain unchanged when several physical vessel moves
    # occur within the same environmental/model-time state.
    #
    # It must NEVER move backward.
    # -------------------------------------------------------------------------

    for previous, current in zip(
        time_indices,
        time_indices[
            1:
        ],
    ):

        if current < previous:

            raise AssertionError(
                "4D route time indices must never move backward."
            )

    # =========================================================================
    # VERIFY THE NEW TEMPORAL SEMANTICS EXPLICITLY
    # =========================================================================

    if len(
        set(
            time_indices
        )
    ) == 1:

        print()
        print(
            "Temporal note:"
        )

        print(
            "  All controlled route points remain in "
            "the same model-time layer."
        )

        print(
            "  This is valid because physical vessel travel "
            "is shorter than a model-state interval."
        )

    else:

        print()
        print(
            "Temporal note:"
        )

        print(
            "  Route crosses multiple model-time layers."
        )

    # =========================================================================
    # VERIFY ROUTE IS ACTUALLY SPATIAL
    # =========================================================================

    first = result.route[
        0
    ]

    last = result.route[
        -1
    ]

    spatially_moved = (
        abs(
            last.latitude
            - first.latitude
        )
        > 1e-9
        or abs(
            last.longitude
            - first.longitude
        )
        > 1e-9
    )

    if not spatially_moved:

        raise AssertionError(
            "Controlled route did not move spatially."
        )

    # =========================================================================
    # PRINT ROUTE
    # =========================================================================

    print()
    print(
        "Route:"
    )

    for state in result.route:

        print(
            "  "
            f"lat={state.latitude:.5f}, "
            f"lon={state.longitude:.5f}, "
            f"depth={state.depth_m:.1f} m, "
            f"time_index={state.time_index}"
        )

    # =========================================================================
    # FINAL PASS
    # =========================================================================

    print()
    print(
        "CONTROLLED 4D A* TEST: PASS"
    )

    print(
        "=" * 72
    )


if __name__ == "__main__":

    main()

