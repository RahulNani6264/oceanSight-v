from __future__ import annotations

import time

from app.navigation_astar import OceanSightAStar
from app.navigation_environment import NavigationEnvironment
from app.navigation_models import (
    NavigationConstraints,
    NavigationRequest,
    NavigationWaypoint,
    NavigationWeights,
)
from app.navigation_search_policy import NavigationSearchPolicy


def main() -> None:
    print("=" * 80)
    print("OCEANSIGHT-V")
    print("REAL HYCOM-BACKED 4D A* TEST")
    print("=" * 80)

    environment = NavigationEnvironment()

    engine = OceanSightAStar(
        environment,
        latitude_step_deg=0.05,
        longitude_step_deg=0.05,
        depth_step_m=50.0,
        search_policy=NavigationSearchPolicy(
            max_latitude_span_deg=1.0,
            max_longitude_span_deg=1.0,
            max_route_duration_hours=6.0,
            max_time_steps=6,
            max_depth_m=500.0,
            max_allowed_node_budget=250,
        ),
    )

    request = NavigationRequest(
        mode="logistics",

        start=NavigationWaypoint(
            latitude=-8.20,
            longitude=68.20,
            depth_m=100.0,
            name="REAL-HYCOM-START",
        ),

        destination=NavigationWaypoint(
            latitude=-8.15,
            longitude=68.25,
            depth_m=100.0,
            name="REAL-HYCOM-GOAL",
        ),

        departure_time_utc="2026-09-10T06:00:00Z",

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
            current_penalty_weight=2.0,
            hazard_penalty_weight=1.0,
            time_penalty_weight=1.0,
            waiting_penalty_weight=0.25,
        ),

        requested_depth_m=100.0,

        allow_waiting=False,

        max_search_nodes=250,

        time_step_minutes=60,
    )

    started = time.perf_counter()

    result = engine.search(request)

    elapsed = (
        time.perf_counter()
        - started
    )

    print()
    print("Search result:")
    print("  found:", result.found)
    print("  message:", result.message)
    print("  expanded_nodes:", result.expanded_nodes)
    print("  generated_nodes:", result.generated_nodes)
    print("  route_length:", len(result.route))
    print(
        "  execution_seconds:",
        round(elapsed, 3),
    )

    if not result.found:
        raise AssertionError(
            "Real HYCOM-backed A* failed."
        )

    if len(result.route) < 2:
        raise AssertionError(
            "Real HYCOM route contains fewer than two states."
        )

    print()
    print("Real route:")

    for state in result.route:
        print(
            "  "
            f"lat={state.latitude:.6f}, "
            f"lon={state.longitude:.6f}, "
            f"depth={state.depth_m:.1f} m, "
            f"time_index={state.time_index}"
        )

    print()
    print("REAL HYCOM-BACKED 4D A* TEST: PASS")
    print("=" * 80)


if __name__ == "__main__":
    main()