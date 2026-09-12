
from __future__ import annotations

"""
OceanSight-V
4D A* Navigation Engine

Search dimensions
-----------------
    latitude
    longitude
    depth
    time

Temporal model
--------------
The navigation engine distinguishes:

    vessel/departure time
        from
    scientific HYCOM source time.

HYCOM model times are obtained only from NavigationTimeAdapter.

Therefore this module NEVER constructs environmental timestamps using:

    departure + arbitrary configured minutes

Instead:

    SearchState.time_index
        -> index into the REAL HYCOM source-time sequence
           used by this search.

Important:
    time_index=0 always means the first real HYCOM model timestamp
    selected for the current search.

Scientific rules
----------------
- No synthetic ocean data.
- No silent interpolation.
- No invented HYCOM timestamps.
- Environmental data is queried only at exact real HYCOM source times.
- Vessel physical travel time is tracked separately.
- Search policy is enforced before expensive environment queries.
- Existing navigation cost calculations are preserved.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from heapq import heappop, heappush
from math import atan2, cos, radians, sin, sqrt
from typing import Any

from .navigation_cost import (
    NavigationEdgeCost,
    calculate_edge_cost,
)
from .navigation_environment import (
    NavigationEnvironment,
    NavigationEnvironmentState,
)
from .navigation_models import (
    NavigationMetrics,
    NavigationRequest,
    NavigationResult,
    NavigationRoutePoint,
)
from .navigation_search_policy import (
    NavigationSearchPolicy,
    enforce_navigation_policy,
)
from .navigation_time import (
    NavigationTimeAdapter,
)


# =============================================================================
# CONSTANTS
# =============================================================================

EARTH_RADIUS_M = 6_371_000.0
EPSILON = 1.0e-12


# =============================================================================
# INTERNAL SEARCH MODELS
# =============================================================================


@dataclass(frozen=True, order=True)
class SearchState:
    """
    One node in the 4D navigation graph.

    time_index:
        Index into the REAL HYCOM source-time sequence selected for this
        navigation search.

    Important:
        time_index=0 is always the first model layer used by this search.
    """

    latitude: float
    longitude: float
    depth_m: float
    time_index: int


@dataclass(frozen=True)
class ParentRecord:
    """
    Parent information used for route reconstruction.
    """

    parent: SearchState | None
    edge_cost: NavigationEdgeCost | None
    environment: NavigationEnvironmentState


@dataclass(frozen=True)
class AStarResult:
    """
    Internal A* result.
    """

    found: bool
    goal_state: SearchState | None
    route: list[SearchState]
    expanded_nodes: int
    generated_nodes: int
    message: str

    # -------------------------------------------------------------------------
    # Temporal provenance.
    # -------------------------------------------------------------------------

    departure_vessel_time_utc: str | None = None
    starting_model_time_utc: str | None = None
    model_times_utc: list[str] | None = None


# =============================================================================
# COORDINATE HELPERS
# =============================================================================


def normalize_longitude(
    longitude: float,
) -> float:
    """
    Normalize longitude to [-180, 180].
    """

    value = float(
        longitude
    )

    while value > 180.0:
        value -= 360.0

    while value < -180.0:
        value += 360.0

    return value


def haversine_distance_m(
    latitude_1: float,
    longitude_1: float,
    latitude_2: float,
    longitude_2: float,
) -> float:
    """
    Great-circle horizontal distance between two geographic points.

    Depth is deliberately excluded because this calculates horizontal
    geographic separation.
    """

    lat1 = radians(
        float(latitude_1)
    )

    lat2 = radians(
        float(latitude_2)
    )

    dlat = lat2 - lat1

    dlon = radians(
        normalize_longitude(
            float(longitude_2)
            - float(longitude_1)
        )
    )

    a = (
        sin(dlat / 2.0) ** 2
        + cos(lat1)
        * cos(lat2)
        * sin(dlon / 2.0) ** 2
    )

    a = min(
        1.0,
        max(
            0.0,
            a,
        ),
    )

    c = (
        2.0
        * atan2(
            sqrt(a),
            sqrt(
                max(
                    0.0,
                    1.0 - a,
                )
            ),
        )
    )

    return EARTH_RADIUS_M * c


def route_bearing_math_deg(
    latitude_1: float,
    longitude_1: float,
    latitude_2: float,
    longitude_2: float,
) -> float:
    """
    Calculate mathematical bearing.

    Convention:
        0°   = east
        90°  = north
        180° = west
        270° = south
    """

    lat1 = radians(
        float(latitude_1)
    )

    lat2 = radians(
        float(latitude_2)
    )

    dlon = radians(
        normalize_longitude(
            float(longitude_2)
            - float(longitude_1)
        )
    )

    x = (
        cos(lat2)
        * sin(dlon)
    )

    y = (
        cos(lat1)
        * sin(lat2)
        - sin(lat1)
        * cos(lat2)
        * cos(dlon)
    )

    compass_deg = (
        atan2(
            x,
            y,
        )
        * 180.0
        / 3.141592653589793
    )

    math_deg = (
        90.0
        - compass_deg
    ) % 360.0

    return math_deg


# =============================================================================
# TIME HELPERS
# =============================================================================


def parse_utc(
    value: str,
) -> datetime:
    """
    Parse an ISO-8601 timestamp with an explicit timezone.
    """

    text = str(
        value
    ).strip()

    if text.endswith("Z"):
        text = (
            text[:-1]
            + "+00:00"
        )

    parsed = datetime.fromisoformat(
        text
    )

    if parsed.tzinfo is None:
        raise ValueError(
            "UTC time must include an explicit timezone."
        )

    return parsed.astimezone(
        timezone.utc
    )


def format_utc(
    value: datetime,
) -> str:
    """
    Format a datetime as UTC ISO-8601.
    """

    return (
        value.astimezone(
            timezone.utc
        )
        .isoformat()
        .replace(
            "+00:00",
            "Z",
        )
    )


# =============================================================================
# 4D NEIGHBOR GENERATOR
# =============================================================================


class NeighborGenerator:
    """
    Generate neighboring 4D search states.

    Spatial transitions:
        north
        south
        east
        west
        four diagonals

    Optional transition:
        wait in place

    Every transition advances exactly one REAL HYCOM MODEL-TIME layer.

    `time_step_minutes` remains in the public signature for compatibility
    with the existing codebase, but it no longer defines environmental
    timestamps.
    """

    def __init__(
        self,
        *,
        latitude_step_deg: float,
        longitude_step_deg: float,
        depth_step_m: float,
    ) -> None:

        if latitude_step_deg <= 0.0:
            raise ValueError(
                "latitude_step_deg must be greater than zero."
            )

        if longitude_step_deg <= 0.0:
            raise ValueError(
                "longitude_step_deg must be greater than zero."
            )

        if depth_step_m <= 0.0:
            raise ValueError(
                "depth_step_m must be greater than zero."
            )

        self.latitude_step_deg = float(
            latitude_step_deg
        )

        self.longitude_step_deg = float(
            longitude_step_deg
        )

        self.depth_step_m = float(
            depth_step_m
        )

    def neighbors(
        self,
        state: SearchState,
        *,
        target_depth_m: float,
        time_step_minutes: int,
        allow_waiting: bool = True,
    ) -> list[SearchState]:
        """
        Generate valid candidate next states.

        Every candidate advances one model-time layer.

        The actual elapsed duration of that layer comes from the discovered
        INCOIS HYCOM source-time sequence used by the A* engine.
        """

        if time_step_minutes <= 0:
            raise ValueError(
                "time_step_minutes must be greater than zero."
            )

        next_time = (
            state.time_index
            + 1
        )

        spatial_moves = [
            (
                self.latitude_step_deg,
                0.0,
            ),
            (
                -self.latitude_step_deg,
                0.0,
            ),
            (
                0.0,
                self.longitude_step_deg,
            ),
            (
                0.0,
                -self.longitude_step_deg,
            ),
            (
                self.latitude_step_deg,
                self.longitude_step_deg,
            ),
            (
                self.latitude_step_deg,
                -self.longitude_step_deg,
            ),
            (
                -self.latitude_step_deg,
                self.longitude_step_deg,
            ),
            (
                -self.latitude_step_deg,
                -self.longitude_step_deg,
            ),
        ]

        if allow_waiting:
            spatial_moves.insert(
                0,
                (
                    0.0,
                    0.0,
                ),
            )

        depth_candidates = [
            state.depth_m
        ]

        depth_difference = (
            float(target_depth_m)
            - float(state.depth_m)
        )

        if abs(
            depth_difference
        ) > EPSILON:

            direction = (
                1.0
                if depth_difference > 0.0
                else -1.0
            )

            candidate_depth = (
                state.depth_m
                + direction
                * self.depth_step_m
            )

            if (
                direction > 0.0
                and candidate_depth
                > target_depth_m
            ):

                candidate_depth = (
                    target_depth_m
                )

            if (
                direction < 0.0
                and candidate_depth
                < target_depth_m
            ):

                candidate_depth = (
                    target_depth_m
                )

            if candidate_depth >= 0.0:

                depth_candidates.append(
                    candidate_depth
                )

        results: list[
            SearchState
        ] = []

        for depth in depth_candidates:

            for (
                lat_delta,
                lon_delta,
            ) in spatial_moves:

                latitude = (
                    state.latitude
                    + lat_delta
                )

                longitude = normalize_longitude(
                    state.longitude
                    + lon_delta
                )

                if not (
                    -90.0
                    <= latitude
                    <= 90.0
                ):

                    continue

                if depth < 0.0:

                    continue

                results.append(
                    SearchState(
                        latitude=latitude,
                        longitude=longitude,
                        depth_m=depth,
                        time_index=next_time,
                    )
                )

        return results


# =============================================================================
# HEURISTIC
# =============================================================================


def heuristic_cost(
    *,
    state: SearchState,
    goal: SearchState,
    vessel_speed_m_s: float,
) -> float:
    """
    Lower-bound-oriented travel-time heuristic.

    Uses horizontal great-circle distance divided by configured vessel
    speed. It does not assume a favorable ocean current.
    """

    if vessel_speed_m_s <= 0.0:
        raise ValueError(
            "vessel_speed_m_s must be greater than zero."
        )

    horizontal_distance = (
        haversine_distance_m(
            state.latitude,
            state.longitude,
            goal.latitude,
            goal.longitude,
        )
    )

    return (
        horizontal_distance
        / float(vessel_speed_m_s)
    )


# =============================================================================
# 4D A* ENGINE
# =============================================================================


class OceanSightAStar:
    """
    Standalone OceanSight-V 4D A* engine.

    Temporal architecture
    ---------------------
    A search first resolves the vessel departure time against real HYCOM
    source times.

    Example:

        vessel departure:
            2026-09-10T07:00:00Z

        real HYCOM source times:
            2026-09-10T06:00:00Z
            2026-09-10T12:00:00Z
            2026-09-10T18:00:00Z

    Search timeline:

        time_index=0 -> 12:00Z
        time_index=1 -> 18:00Z
        time_index=2 -> next real source time

    The vessel departure remains 07:00Z in provenance.

    Physical travel time is tracked independently using navigation_cost.
    """

    def __init__(
        self,
        environment: NavigationEnvironment,
        *,
        latitude_step_deg: float = 0.05,
        longitude_step_deg: float = 0.05,
        depth_step_m: float = 50.0,
        search_policy: NavigationSearchPolicy | None = None,
    ) -> None:

        self.environment = environment

        self.latitude_step_deg = float(
            latitude_step_deg
        )

        self.longitude_step_deg = float(
            longitude_step_deg
        )

        self.depth_step_m = float(
            depth_step_m
        )

        if self.latitude_step_deg <= 0.0:
            raise ValueError(
                "latitude_step_deg must be greater than zero."
            )

        if self.longitude_step_deg <= 0.0:
            raise ValueError(
                "longitude_step_deg must be greater than zero."
            )

        if self.depth_step_m <= 0.0:
            raise ValueError(
                "depth_step_m must be greater than zero."
            )

        self.search_policy = (
            search_policy
            if search_policy is not None
            else NavigationSearchPolicy()
        )

        self.neighbor_generator = (
            NeighborGenerator(
                latitude_step_deg=(
                    self.latitude_step_deg
                ),
                longitude_step_deg=(
                    self.longitude_step_deg
                ),
                depth_step_m=(
                    self.depth_step_m
                ),
            )
        )

        # ---------------------------------------------------------------------
        # Ensure the environment has the real HYCOM time adapter.
        # ---------------------------------------------------------------------

        if self.environment.time_adapter is None:

            self.environment.time_adapter = (
                NavigationTimeAdapter.from_live_incois()
            )

    # =========================================================================
    # MODEL TIME SEQUENCE
    # =========================================================================

    def _source_times(
        self,
    ) -> list[str]:
        """
        Return the real INCOIS HYCOM source-time sequence.
        """

        adapter = self.environment.time_adapter

        if adapter is None:

            raise RuntimeError(
                "NavigationEnvironment has no NavigationTimeAdapter."
            )

        times = (
            adapter.available_model_times()
        )

        if not times:

            raise RuntimeError(
                "NavigationTimeAdapter returned no HYCOM source times."
            )

        return times

    def _source_time_for_index(
        self,
        time_index: int,
        source_times: list[str],
    ) -> str:

        if (
            time_index < 0
            or time_index >= len(
                source_times
            )
        ):

            raise IndexError(
                "HYCOM source-time index is outside the discovered "
                "source-time sequence."
            )

        return source_times[
            time_index
        ]

    # =========================================================================
    # ENVIRONMENT
    # =========================================================================

    def _environment_for_state(
        self,
        state: SearchState,
        *,
        source_times: list[str],
    ) -> NavigationEnvironmentState:
        """
        Retrieve the scientific environment for a 4D state.

        The environmental timestamp comes exclusively from the real
        HYCOM source-time sequence.
        """

        timestamp = (
            self._source_time_for_index(
                state.time_index,
                source_times,
            )
        )

        environment = (
            self.environment.sample(
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
                    timestamp
                ),
            )
        )

        self.environment.validate_scientific_integrity(
            environment
        )

        return environment

    # =========================================================================
    # SEARCH
    # =========================================================================

    def search(
        self,
        request: NavigationRequest,
    ) -> AStarResult:
        """
        Execute bounded 4D A* using real HYCOM model-time layers.
        """

        # ---------------------------------------------------------------------
        # SEARCH POLICY
        # ---------------------------------------------------------------------

        try:

            enforce_navigation_policy(
                request,
                policy=self.search_policy,
                latitude_step_deg=(
                    self.latitude_step_deg
                ),
                longitude_step_deg=(
                    self.longitude_step_deg
                ),
            )

        except ValueError as exc:

            return AStarResult(
                found=False,
                goal_state=None,
                route=[],
                expanded_nodes=0,
                generated_nodes=0,
                message=(
                    "Navigation search rejected by policy: "
                    f"{exc}"
                ),
            )

        # ---------------------------------------------------------------------
        # REQUEST DEPARTURE TIME
        # ---------------------------------------------------------------------

        try:

            departure_time = parse_utc(
                request.departure_time_utc
            )

        except ValueError as exc:

            return AStarResult(
                found=False,
                goal_state=None,
                route=[],
                expanded_nodes=0,
                generated_nodes=0,
                message=(
                    "Invalid departure time: "
                    f"{exc}"
                ),
            )

        time_step_minutes = int(
            request.time_step_minutes
        )

        max_search_nodes = int(
            request.max_search_nodes
        )

        if time_step_minutes <= 0:

            return AStarResult(
                found=False,
                goal_state=None,
                route=[],
                expanded_nodes=0,
                generated_nodes=0,
                message=(
                    "time_step_minutes must be greater than zero."
                ),
            )

        # ---------------------------------------------------------------------
        # DISCOVER REAL MODEL TIMES
        # ---------------------------------------------------------------------

        try:

            global_source_times = (
                self._source_times()
            )

        except Exception as exc:

            return AStarResult(
                found=False,
                goal_state=None,
                route=[],
                expanded_nodes=0,
                generated_nodes=0,
                message=(
                    "Unable to obtain real HYCOM source times: "
                    f"{exc}"
                ),
            )

        # ---------------------------------------------------------------------
        # RESOLVE VESSEL DEPARTURE TO FIRST REAL MODEL TIME.
        #
        # IMPORTANT:
        #
        # We preserve the requested vessel departure exactly.
        #
        # We only select an explicit real model timestamp for environmental
        # sampling.
        # ---------------------------------------------------------------------

        adapter = self.environment.time_adapter

        if adapter is None:

            return AStarResult(
                found=False,
                goal_state=None,
                route=[],
                expanded_nodes=0,
                generated_nodes=0,
                message=(
                    "NavigationTimeAdapter is required for "
                    "4D model-time routing."
                ),
            )

        try:

            resolved_start = (
                adapter.next_valid(
                    format_utc(
                        departure_time
                    )
                )
            )

        except Exception as exc:

            return AStarResult(
                found=False,
                goal_state=None,
                route=[],
                expanded_nodes=0,
                generated_nodes=0,
                message=(
                    "Unable to resolve vessel departure time "
                    "against HYCOM source times: "
                    f"{exc}"
                ),
            )

        if resolved_start is None:

            return AStarResult(
                found=False,
                goal_state=None,
                route=[],
                expanded_nodes=0,
                generated_nodes=0,
                message=(
                    "No real INCOIS HYCOM source time exists at "
                    "or after the requested vessel departure time."
                ),
                departure_vessel_time_utc=(
                    format_utc(
                        departure_time
                    )
                ),
                model_times_utc=[],
            )

        starting_model_time = (
            resolved_start.model_time_utc
        )

        # ---------------------------------------------------------------------
        # Build a SEARCH-LOCAL model-time sequence.
        #
        # Therefore the first layer is always index 0.
        # ---------------------------------------------------------------------

        try:

            starting_source_index = (
                global_source_times.index(
                    starting_model_time
                )
            )

        except ValueError:

            return AStarResult(
                found=False,
                goal_state=None,
                route=[],
                expanded_nodes=0,
                generated_nodes=0,
                message=(
                    "Resolved HYCOM model time was not found "
                    "in the discovered source-time sequence."
                ),
                departure_vessel_time_utc=(
                    format_utc(
                        departure_time
                    )
                ),
                starting_model_time_utc=(
                    starting_model_time
                ),
                model_times_utc=(
                    global_source_times
                ),
            )

        search_model_times = (
            global_source_times[
                starting_source_index:
            ]
        )

        if not search_model_times:

            return AStarResult(
                found=False,
                goal_state=None,
                route=[],
                expanded_nodes=0,
                generated_nodes=0,
                message=(
                    "No real HYCOM model-time layers are available "
                    "for the navigation search."
                ),
                departure_vessel_time_utc=(
                    format_utc(
                        departure_time
                    )
                ),
                starting_model_time_utc=(
                    starting_model_time
                ),
                model_times_utc=[],
            )

        # ---------------------------------------------------------------------
        # START / GOAL
        #
        # Both begin at local search time_index=0.
        # ---------------------------------------------------------------------

        start = SearchState(
            latitude=float(
                request.start.latitude
            ),
            longitude=normalize_longitude(
                request.start.longitude
            ),
            depth_m=float(
                request.start.depth_m
            ),
            time_index=0,
        )

        goal = SearchState(
            latitude=float(
                request.destination.latitude
            ),
            longitude=normalize_longitude(
                request.destination.longitude
            ),
            depth_m=float(
                request.destination.depth_m
            ),
            time_index=0,
        )

        constraints = request.constraints

        # ---------------------------------------------------------------------
        # GOAL TOLERANCE
        # ---------------------------------------------------------------------

        latitude_tolerance = 1.0e-6
        longitude_tolerance = 1.0e-6
        depth_tolerance = 1.0e-6

        def reached_goal(
            state: SearchState,
        ) -> bool:

            longitude_difference = (
                normalize_longitude(
                    state.longitude
                    - goal.longitude
                )
            )

            return (
                abs(
                    state.latitude
                    - goal.latitude
                )
                <= latitude_tolerance
                and abs(
                    longitude_difference
                )
                <= longitude_tolerance
                and abs(
                    state.depth_m
                    - goal.depth_m
                )
                <= depth_tolerance
            )

        # ---------------------------------------------------------------------
        # OPEN SET
        # ---------------------------------------------------------------------

        open_heap: list[
            tuple[
                float,
                int,
                SearchState,
            ]
        ] = []

        counter = 0

        initial_h = heuristic_cost(
            state=start,
            goal=goal,
            vessel_speed_m_s=(
                constraints.vessel_speed_m_s
            ),
        )

        heappush(
            open_heap,
            (
                initial_h,
                counter,
                start,
            ),
        )

        # ---------------------------------------------------------------------
        # COSTS / PARENTS / CACHE
        # ---------------------------------------------------------------------

        g_score: dict[
            SearchState,
            float,
        ] = {
            start: 0.0
        }

        parents: dict[
            SearchState,
            ParentRecord,
        ] = {}

        environment_cache: dict[
            SearchState,
            NavigationEnvironmentState,
        ] = {}

        # ---------------------------------------------------------------------
        # Physical vessel elapsed time.
        #
        # This is intentionally separate from HYCOM model time.
        # ---------------------------------------------------------------------

        vessel_elapsed_seconds: dict[
            SearchState,
            float,
        ] = {
            start: 0.0
        }

        expanded_nodes = 0
        generated_nodes = 1

        # ---------------------------------------------------------------------
        # ENVIRONMENT CACHE HELPER
        # ---------------------------------------------------------------------

        def get_environment(
            state: SearchState,
        ) -> NavigationEnvironmentState:

            cached = environment_cache.get(
                state
            )

            if cached is not None:

                return cached

            value = (
                self._environment_for_state(
                    state,
                    source_times=(
                        search_model_times
                    ),
                )
            )

            environment_cache[
                state
            ] = value

            return value

        # ---------------------------------------------------------------------
        # START ENVIRONMENT
        # ---------------------------------------------------------------------

        try:

            start_environment = (
                get_environment(
                    start
                )
            )

        except Exception as exc:

            return AStarResult(
                found=False,
                goal_state=None,
                route=[],
                expanded_nodes=0,
                generated_nodes=0,
                message=(
                    "Unable to sample starting "
                    f"environment: {exc}"
                ),
                departure_vessel_time_utc=(
                    format_utc(
                        departure_time
                    )
                ),
                starting_model_time_utc=(
                    starting_model_time
                ),
                model_times_utc=(
                    search_model_times
                ),
            )

        parents[
            start
        ] = ParentRecord(
            parent=None,
            edge_cost=None,
            environment=start_environment,
        )

        # ---------------------------------------------------------------------
        # MAIN A* LOOP
        # ---------------------------------------------------------------------

        while open_heap:

            (
                _priority,
                _counter,
                current,
            ) = heappop(
                open_heap
            )

            # -------------------------------------------------------------
            # GOAL
            # -------------------------------------------------------------

            if reached_goal(
                current
            ):

                route = (
                    self._reconstruct_route(
                        current,
                        parents,
                    )
                )

                return AStarResult(
                    found=True,
                    goal_state=current,
                    route=route,
                    expanded_nodes=(
                        expanded_nodes
                    ),
                    generated_nodes=(
                        generated_nodes
                    ),
                    message=(
                        "4D A* route found using real "
                        "INCOIS HYCOM source-time layers."
                    ),
                    departure_vessel_time_utc=(
                        format_utc(
                            departure_time
                        )
                    ),
                    starting_model_time_utc=(
                        starting_model_time
                    ),
                    model_times_utc=(
                        search_model_times
                    ),
                )

            # -------------------------------------------------------------
            # NODE LIMIT
            # -------------------------------------------------------------

            expanded_nodes += 1

            if (
                expanded_nodes
                > max_search_nodes
            ):

                return AStarResult(
                    found=False,
                    goal_state=None,
                    route=[],
                    expanded_nodes=(
                        expanded_nodes
                    ),
                    generated_nodes=(
                        generated_nodes
                    ),
                    message=(
                        "Maximum A* search-node "
                        "limit reached."
                    ),
                    departure_vessel_time_utc=(
                        format_utc(
                            departure_time
                        )
                    ),
                    starting_model_time_utc=(
                        starting_model_time
                    ),
                    model_times_utc=(
                        search_model_times
                    ),
                )

            current_g = g_score[
                current
            ]

            current_vessel_elapsed = (
                vessel_elapsed_seconds[
                    current
                ]
            )

            # -------------------------------------------------------------
            # CURRENT ENVIRONMENT
            # -------------------------------------------------------------

            try:

                current_environment = (
                    get_environment(
                        current
                    )
                )

            except Exception:

                continue

            # -------------------------------------------------------------
            # LAST MODEL LAYER
            # -------------------------------------------------------------

            if (
                current.time_index
                >= len(
                    search_model_times
                )
                - 1
            ):

                continue

            # -------------------------------------------------------------
            # ACTUAL REAL MODEL INTERVAL
            # -------------------------------------------------------------

            current_model_time = parse_utc(
                search_model_times[
                    current.time_index
                ]
            )

            next_model_time = parse_utc(
                search_model_times[
                    current.time_index
                    + 1
                ]
            )

            model_interval_seconds = (
                next_model_time
                - current_model_time
            ).total_seconds()

            if model_interval_seconds <= 0.0:

                continue

            # -------------------------------------------------------------
            # NEIGHBORS
            # -------------------------------------------------------------

            neighbors = (
                self.neighbor_generator.neighbors(
                    current,
                    target_depth_m=(
                        goal.depth_m
                    ),
                    time_step_minutes=(
                        time_step_minutes
                    ),
                    allow_waiting=(
                        request.allow_waiting
                    ),
                )
            )

            for neighbor in neighbors:

                # ---------------------------------------------------------
                # DEPTH CONSTRAINTS
                # ---------------------------------------------------------

                if (
                    constraints.min_depth_m
                    is not None
                    and neighbor.depth_m
                    < constraints.min_depth_m
                ):

                    continue

                if (
                    constraints.max_depth_m
                    is not None
                    and neighbor.depth_m
                    > constraints.max_depth_m
                ):

                    continue

                # ---------------------------------------------------------
                # ENVIRONMENT
                # ---------------------------------------------------------

                try:

                    neighbor_environment = (
                        get_environment(
                            neighbor
                        )
                    )

                except Exception:

                    continue

                # ---------------------------------------------------------
                # GEOMETRY
                # ---------------------------------------------------------

                distance_m = (
                    haversine_distance_m(
                        current.latitude,
                        current.longitude,
                        neighbor.latitude,
                        neighbor.longitude,
                    )
                )

                bearing_deg = (
                    route_bearing_math_deg(
                        current.latitude,
                        current.longitude,
                        neighbor.latitude,
                        neighbor.longitude,
                    )
                )

                # ---------------------------------------------------------
                # COST
                # ---------------------------------------------------------

                try:

                    edge_cost = (
                        calculate_edge_cost(
                            environment=(
                                current_environment
                            ),
                            distance_m=(
                                distance_m
                            ),
                            route_bearing_math_deg=(
                                bearing_deg
                            ),
                            constraints=(
                                constraints
                            ),
                            weights=(
                                request.weights
                            ),
                            hazard_penalty=0.0,
                        )
                    )

                except Exception:

                    continue

                if not edge_cost.traversable:

                    continue

                # ---------------------------------------------------------
                # PHYSICAL EDGE TRAVEL TIME
                # ---------------------------------------------------------

                edge_travel_seconds = float(
                    edge_cost.travel_time_seconds
                )

                if edge_travel_seconds < 0.0:

                    continue

                # ---------------------------------------------------------
                # PHYSICAL FEASIBILITY
                #
                # One graph edge represents movement during one actual
                # HYCOM source interval.
                #
                # The vessel cannot require more physical travel time
                # than the environmental interval represented by that edge.
                # ---------------------------------------------------------

                if (
                    edge_travel_seconds
                    > model_interval_seconds
                    + EPSILON
                ):

                    continue

                # ---------------------------------------------------------
                # VESSEL TRAVEL TIME
                # ---------------------------------------------------------

                tentative_vessel_elapsed = (
                    current_vessel_elapsed
                    + edge_travel_seconds
                )

                elapsed_hours = (
                    tentative_vessel_elapsed
                    / 3600.0
                )

                if (
                    constraints.max_route_duration_hours
                    is not None
                    and elapsed_hours
                    > constraints.max_route_duration_hours
                ):

                    continue

                # ---------------------------------------------------------
                # A* SCORE
                # ---------------------------------------------------------

                tentative_g = (
                    current_g
                    + edge_cost.total_cost
                )

                known_g = g_score.get(
                    neighbor,
                    float("inf"),
                )

                if (
                    tentative_g
                    >= known_g
                ):

                    continue

                # ---------------------------------------------------------
                # BEST PATH UPDATE
                # ---------------------------------------------------------

                g_score[
                    neighbor
                ] = tentative_g

                vessel_elapsed_seconds[
                    neighbor
                ] = tentative_vessel_elapsed

                parents[
                    neighbor
                ] = ParentRecord(
                    parent=current,
                    edge_cost=edge_cost,
                    environment=(
                        neighbor_environment
                    ),
                )

                heuristic = (
                    heuristic_cost(
                        state=neighbor,
                        goal=goal,
                        vessel_speed_m_s=(
                            constraints.vessel_speed_m_s
                        ),
                    )
                )

                priority = (
                    tentative_g
                    + heuristic
                )

                counter += 1

                heappush(
                    open_heap,
                    (
                        priority,
                        counter,
                        neighbor,
                    )
                )

                generated_nodes += 1

        return AStarResult(
            found=False,
            goal_state=None,
            route=[],
            expanded_nodes=(
                expanded_nodes
            ),
            generated_nodes=(
                generated_nodes
            ),
            message=(
                "No traversable 4D route was found."
            ),
            departure_vessel_time_utc=(
                format_utc(
                    departure_time
                )
            ),
            starting_model_time_utc=(
                starting_model_time
            ),
            model_times_utc=(
                search_model_times
            ),
        )

    # =========================================================================
    # ROUTE RECONSTRUCTION
    # =========================================================================

    @staticmethod
    def _reconstruct_route(
        goal_state: SearchState,
        parents: dict[
            SearchState,
            ParentRecord,
        ],
    ) -> list[SearchState]:

        route: list[
            SearchState
        ] = []

        current: SearchState | None = (
            goal_state
        )

        while current is not None:

            route.append(
                current
            )

            record = parents.get(
                current
            )

            if record is None:

                break

            current = record.parent

        route.reverse()

        return route


# =============================================================================
# HIGH-LEVEL NAVIGATION ROUTE ENGINE
# =============================================================================


class NavigationRouteEngine:
    """
    High-level adapter from NavigationRequest to NavigationResult.
    """

    def __init__(
        self,
        environment: NavigationEnvironment | None = None,
        *,
        latitude_step_deg: float = 0.05,
        longitude_step_deg: float = 0.05,
        depth_step_m: float = 50.0,
        search_policy: NavigationSearchPolicy | None = None,
    ) -> None:

        self.environment = (
            environment
            if environment is not None
            else NavigationEnvironment()
        )

        # ---------------------------------------------------------------------
        # Attach real HYCOM time adapter when necessary.
        # ---------------------------------------------------------------------

        if self.environment.time_adapter is None:

            self.environment.time_adapter = (
                NavigationTimeAdapter.from_live_incois()
            )

        self.astar = OceanSightAStar(
            self.environment,
            latitude_step_deg=(
                latitude_step_deg
            ),
            longitude_step_deg=(
                longitude_step_deg
            ),
            depth_step_m=(
                depth_step_m
            ),
            search_policy=(
                search_policy
            ),
        )

    # =========================================================================
    # ROUTE RESULT CONVERSION
    # =========================================================================

    def _convert_route(
        self,
        request: NavigationRequest,
        search: AStarResult,
    ) -> NavigationResult:

        if not search.found:

            return NavigationResult(
                status="no_route",
                mode=request.mode,
                available=False,
                message=search.message,
                route=[],
                metrics=NavigationMetrics(),
                synthetic_data=False,
                interpolation=False,
                provenance={
                    "expanded_nodes": (
                        search.expanded_nodes
                    ),
                    "generated_nodes": (
                        search.generated_nodes
                    ),
                    "routing_algorithm": (
                        "OceanSight 4D A*"
                    ),
                    "temporal_model": (
                        "REAL INCOIS HYCOM source-time layers"
                    ),
                    "departure_vessel_time_utc": (
                        search.departure_vessel_time_utc
                    ),
                    "starting_model_time_utc": (
                        search.starting_model_time_utc
                    ),
                    "model_times_utc": (
                        search.model_times_utc
                        or []
                    ),
                },
            )

        departure_time = parse_utc(
            request.departure_time_utc
        )

        route_points: list[
            NavigationRoutePoint
        ] = []

        total_distance_m = 0.0
        total_travel_seconds = 0.0

        current_speeds: list[
            float
        ] = []

        hazard_exposure = 0.0

        source_times: list[
            str
        ] = []

        sources: list[
            str
        ] = []

        datasets: list[
            str
        ] = []

        all_synthetic = False
        all_interpolation = False

        model_times = (
            search.model_times_utc
            or []
        )

        if not model_times:

            return NavigationResult(
                status="unavailable",
                mode=request.mode,
                available=False,
                message=(
                    "A* returned a route without HYCOM "
                    "model-time provenance."
                ),
                route=[],
                metrics=NavigationMetrics(),
                synthetic_data=False,
                interpolation=False,
                provenance={
                    "routing_algorithm": (
                        "OceanSight 4D A*"
                    ),
                },
            )

        # ---------------------------------------------------------------------
        # Vessel physical elapsed time is reconstructed from edge costs.
        # ---------------------------------------------------------------------

        vessel_elapsed_seconds = 0.0

        for index, state in enumerate(
            search.route
        ):

            if (
                state.time_index < 0
                or state.time_index >= len(
                    model_times
                )
            ):

                return NavigationResult(
                    status="unavailable",
                    mode=request.mode,
                    available=False,
                    message=(
                        "Route contained an invalid HYCOM "
                        "source-time index."
                    ),
                    route=[],
                    metrics=NavigationMetrics(),
                    synthetic_data=False,
                    interpolation=False,
                    provenance={
                        "routing_algorithm": (
                            "OceanSight 4D A*"
                        ),
                    },
                )

            # -----------------------------------------------------------------
            # REAL HYCOM MODEL TIME
            # -----------------------------------------------------------------

            model_timestamp = (
                model_times[
                    state.time_index
                ]
            )

            environment = (
                self.environment.sample(
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
                        model_timestamp
                    ),
                )
            )

            self.environment.validate_scientific_integrity(
                environment
            )

            segment_distance_m = 0.0
            segment_cost = 0.0
            segment_travel_seconds = 0.0

            vessel_speed = (
                request.constraints
                .vessel_speed_m_s
            )

            if index > 0:

                parent = search.route[
                    index - 1
                ]

                segment_distance_m = (
                    haversine_distance_m(
                        parent.latitude,
                        parent.longitude,
                        state.latitude,
                        state.longitude,
                    )
                )

                bearing_deg = (
                    route_bearing_math_deg(
                        parent.latitude,
                        parent.longitude,
                        state.latitude,
                        state.longitude,
                    )
                )

                parent_model_timestamp = (
                    model_times[
                        parent.time_index
                    ]
                )

                parent_environment = (
                    self.environment.sample(
                        latitude=(
                            parent.latitude
                        ),
                        longitude=(
                            parent.longitude
                        ),
                        depth_m=(
                            parent.depth_m
                        ),
                        time_utc=(
                            parent_model_timestamp
                        ),
                    )
                )

                edge = calculate_edge_cost(
                    environment=(
                        parent_environment
                    ),
                    distance_m=(
                        segment_distance_m
                    ),
                    route_bearing_math_deg=(
                        bearing_deg
                    ),
                    constraints=(
                        request.constraints
                    ),
                    weights=(
                        request.weights
                    ),
                    hazard_penalty=0.0,
                )

                if not edge.traversable:

                    return NavigationResult(
                        status="unavailable",
                        mode=request.mode,
                        available=False,
                        message=(
                            "A reconstructed route segment "
                            "was not physically traversable."
                        ),
                        route=[],
                        metrics=NavigationMetrics(),
                        synthetic_data=False,
                        interpolation=False,
                        provenance={
                            "routing_algorithm": (
                                "OceanSight 4D A*"
                            ),
                        },
                    )

                segment_cost = (
                    edge.total_cost
                )

                segment_travel_seconds = float(
                    edge.travel_time_seconds
                )

                total_distance_m += (
                    segment_distance_m
                )

                total_travel_seconds += (
                    segment_travel_seconds
                )

                vessel_elapsed_seconds += (
                    segment_travel_seconds
                )

            # -----------------------------------------------------------------
            # PHYSICAL VESSEL ARRIVAL TIME
            #
            # This is deliberately separate from model_timestamp above.
            # -----------------------------------------------------------------

            vessel_timestamp = (
                departure_time
                + timedelta(
                    seconds=(
                        vessel_elapsed_seconds
                    )
                )
            )

            vessel_timestamp_utc = (
                format_utc(
                    vessel_timestamp
                )
            )

            # -----------------------------------------------------------------
            # Current statistics.
            # -----------------------------------------------------------------

            current_speed = (
                environment.current_speed_m_s
            )

            if current_speed is not None:

                current_speeds.append(
                    current_speed
                )

            # -----------------------------------------------------------------
            # Provenance.
            # -----------------------------------------------------------------

            actual_source_time = (
                environment.actual_time_utc
            )

            if (
                actual_source_time is not None
                and actual_source_time
                not in source_times
            ):

                source_times.append(
                    actual_source_time
                )

            source = (
                environment.hycom_source
            )

            if (
                source is not None
                and source
                not in sources
            ):

                sources.append(
                    source
                )

            dataset = (
                environment.hycom_dataset
            )

            if (
                dataset is not None
                and dataset
                not in datasets
            ):

                datasets.append(
                    dataset
                )

            if environment.synthetic_data:

                all_synthetic = True

            if environment.interpolation:

                all_interpolation = True

            # -----------------------------------------------------------------
            # Existing route-point API is preserved.
            #
            # time_utc remains the physical vessel arrival time.
            # Exact HYCOM source times remain in source_times_utc and
            # provenance.
            # -----------------------------------------------------------------

            route_points.append(
                NavigationRoutePoint(
                    sequence=index,
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
                        vessel_timestamp_utc
                    ),
                    segment_distance_m=(
                        segment_distance_m
                    ),
                    cumulative_distance_m=(
                        total_distance_m
                    ),
                    vessel_speed_m_s=(
                        vessel_speed
                    ),
                    u_current_m_s=(
                        environment
                        .u_current_m_s
                    ),
                    v_current_m_s=(
                        environment
                        .v_current_m_s
                    ),
                    current_speed_m_s=(
                        environment
                        .current_speed_m_s
                    ),
                    current_direction_math_deg=(
                        environment
                        .current_direction_math_deg
                    ),
                    hazard_penalty=0.0,
                    segment_cost=(
                        segment_cost
                    ),
                )
            )

        average_current = None

        if current_speeds:

            average_current = (
                sum(
                    current_speeds
                )
                / len(
                    current_speeds
                )
            )

        maximum_current = None

        if current_speeds:

            maximum_current = max(
                current_speeds
            )

        # ---------------------------------------------------------------------
        # Explicit temporal provenance.
        # ---------------------------------------------------------------------

        provenance: dict[str, Any] = {
            "routing_algorithm": (
                "OceanSight 4D A*"
            ),

            "environment_adapter": (
                "NavigationEnvironment"
            ),

            "cost_engine": (
                "navigation_cost"
            ),

            "search_policy": (
                "NavigationSearchPolicy"
            ),

            "expanded_nodes": (
                search.expanded_nodes
            ),

            "generated_nodes": (
                search.generated_nodes
            ),

            "temporal_model": (
                "REAL INCOIS HYCOM source-time layers"
            ),

            "departure_vessel_time_utc": (
                format_utc(
                    departure_time
                )
            ),

            "starting_model_time_utc": (
                search.starting_model_time_utc
            ),

            "hycom_model_times_utc": (
                model_times
            ),

            "source_times_used_utc": (
                source_times
            ),

            "time_semantics": {
                "route_point_time_utc": (
                    "physical vessel arrival time"
                ),
                "environment_time_utc": (
                    "exact INCOIS HYCOM source time"
                ),
                "interpolation": False,
                "synthetic_data": False,
            },
        }

        return NavigationResult(
            status="success",
            mode=request.mode,
            available=True,
            message=(
                "4D A* route successfully calculated "
                "using real environmental states and "
                "real INCOIS HYCOM model-time layers."
            ),
            route=route_points,
            metrics=NavigationMetrics(
                total_distance_m=(
                    total_distance_m
                ),
                total_distance_km=(
                    total_distance_m
                    / 1000.0
                ),
                travel_time_seconds=(
                    total_travel_seconds
                ),
                travel_time_hours=(
                    total_travel_seconds
                    / 3600.0
                ),
                estimated_fuel_units=None,
                max_current_speed_m_s=(
                    maximum_current
                ),
                average_current_speed_m_s=(
                    average_current
                ),
                hazard_exposure=(
                    hazard_exposure
                ),
            ),
            source_times_utc=(
                source_times
            ),
            sources=(
                sources
            ),
            datasets=(
                datasets
            ),
            synthetic_data=(
                all_synthetic
            ),
            interpolation=(
                all_interpolation
            ),
            provenance=(
                provenance
            ),
        )

    # =========================================================================
    # PUBLIC ROUTE
    # =========================================================================

    def route(
        self,
        request: NavigationRequest,
    ) -> NavigationResult:
        """
        Calculate a navigation route.

        Invalid requests are converted into structured NavigationResult
        responses rather than leaking internal exceptions.
        """

        if (
            request.constraints.vessel_speed_m_s
            <= 0.0
        ):

            return NavigationResult(
                status="invalid_request",
                mode=request.mode,
                available=False,
                message=(
                    "Vessel speed must be greater than zero."
                ),
            )

        try:

            search = self.astar.search(
                request
            )

        except ValueError as exc:

            return NavigationResult(
                status="invalid_request",
                mode=request.mode,
                available=False,
                message=str(
                    exc
                ),
            )

        except Exception as exc:

            return NavigationResult(
                status="unavailable",
                mode=request.mode,
                available=False,
                message=(
                    "Navigation engine failed: "
                    f"{exc}"
                ),
            )

        return self._convert_route(
            request,
            search,
        )

