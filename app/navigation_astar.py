
from __future__ import annotations

"""
OceanSight-V
4D A* Navigation Engine

Temporal design
---------------

This engine maintains TWO separate clocks:

1. Vessel physical time
   ---------------------
   Calculated from actual route-segment travel time.

2. HYCOM model time
   -----------------
   Selected only from actual INCOIS HYCOM source TIME values.

Environmental state policy
--------------------------
For a vessel state at physical time T:

    use the latest real HYCOM source time <= T

No interpolation is performed.

Important transition rule
-------------------------
A moving spatial edge may not silently cross a HYCOM source-time boundary.

If the vessel needs to advance to the next model state, the engine may
perform an explicit MODEL-TIME SYNCHRONIZATION / WAIT transition:

    same position
    current model time
          ->
    next real HYCOM model time

This makes the temporal transition explicit instead of inventing
environmental timestamps.

Scientific rules
----------------
- No synthetic ocean data.
- No environmental interpolation.
- No invented HYCOM timestamps.
- HYCOM environmental states come only from real INCOIS source times.
- Vessel physical time is tracked independently.
- Spatial edges may not cross a model boundary silently.
- Explicit model-boundary waiting is allowed only when waiting is enabled.
"""

from bisect import bisect_right
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
        Index into the SEARCH-LOCAL REAL HYCOM source-time sequence.

    Important:
        time_index describes the environmental/model state currently
        associated with the physical vessel arrival state.

        It is NOT a count of arbitrary minutes.
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

    departure_vessel_time_utc: str | None = None
    starting_model_time_utc: str | None = None
    model_times_utc: list[str] | None = None

    # Physical vessel elapsed time for every route state.
    vessel_elapsed_seconds: list[float] | None = None


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

    Depth is deliberately excluded.
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
    Generate spatial and depth candidate moves.

    Temporal advancement is NOT performed here.

    A* determines temporal advancement after calculating physical vessel
    arrival time.
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
        allow_waiting: bool = True,
    ) -> list[SearchState]:
        """
        Generate spatial/depth neighbors.

        All generated candidates initially remain in the current
        environmental model layer.

        A* may subsequently convert a boundary-wait action into the
        next real model layer.
        """

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
                        time_index=(
                            state.time_index
                        ),
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

    This heuristic ignores favorable currents.
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
    ----------------------

    Vessel physical time is tracked continuously through edge travel time.

    Environmental/model time is discrete and comes only from the real
    INCOIS HYCOM source-time sequence.

    Moving edges cannot silently cross a model boundary.

    When waiting is enabled, a dedicated temporal synchronization action
    may advance:

        model index N
            ->
        model index N+1

    while keeping the vessel at the same location.

    This is deliberately explicit.
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

        if self.environment.time_adapter is None:

            self.environment.time_adapter = (
                NavigationTimeAdapter.from_live_incois()
            )

    # =========================================================================
    # SOURCE TIMES
    # =========================================================================

    def _source_times(
        self,
    ) -> list[str]:

        adapter = (
            self.environment.time_adapter
        )

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

    @staticmethod
    def _parsed_source_times(
        source_times: list[str],
    ) -> list[datetime]:

        return [
            parse_utc(
                value
            )
            for value in source_times
        ]

    @staticmethod
    def _latest_source_index_at_or_before(
        vessel_time: datetime,
        parsed_source_times: list[datetime],
    ) -> int | None:
        """
        Find the latest real HYCOM source time <= vessel time.

        No interpolation.
        """

        position = bisect_right(
            parsed_source_times,
            vessel_time,
        )

        if position <= 0:

            return None

        return position - 1

    # =========================================================================
    # ENVIRONMENT
    # =========================================================================

    def _environment_for_state(
        self,
        state: SearchState,
        *,
        source_times: list[str],
    ) -> NavigationEnvironmentState:

        if (
            state.time_index < 0
            or state.time_index >= len(
                source_times
            )
        ):

            raise IndexError(
                "HYCOM source-time index is outside "
                "the navigation timeline."
            )

        model_time = source_times[
            state.time_index
        ]

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
                    model_time
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
        # DEPARTURE TIME
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

        # ---------------------------------------------------------------------
        # OPTIONAL MINIMUM ARRIVAL TIME
        # ---------------------------------------------------------------------
        #
        # This is a physical vessel-time constraint. It is intentionally
        # separate from HYCOM model time. When supplied, the vessel may reach
        # the geographic destination earlier, but A* will not terminate until
        # the physical vessel clock has reached this earliest-arrival time.
        #
        # getattr() keeps this engine backward-compatible with older
        # NavigationRequest models until the field is added to the request
        # contract.
        # ---------------------------------------------------------------------

        minimum_arrival_time = None

        minimum_arrival_time_raw = getattr(
            request,
            "minimum_arrival_time_utc",
            None,
        )

        if minimum_arrival_time_raw is not None:

            try:

                minimum_arrival_time = parse_utc(
                    minimum_arrival_time_raw
                )

            except ValueError as exc:

                return AStarResult(
                    found=False,
                    goal_state=None,
                    route=[],
                    expanded_nodes=0,
                    generated_nodes=0,
                    message=(
                        "Invalid minimum arrival time: "
                        f"{exc}"
                    ),
                )

            if minimum_arrival_time < departure_time:

                return AStarResult(
                    found=False,
                    goal_state=None,
                    route=[],
                    expanded_nodes=0,
                    generated_nodes=0,
                    message=(
                        "minimum_arrival_time_utc cannot be earlier "
                        "than departure_time_utc."
                    ),
                )

        max_search_nodes = int(
            request.max_search_nodes
        )

        # ---------------------------------------------------------------------
        # REAL HYCOM SOURCE TIME AXIS
        # ---------------------------------------------------------------------

        try:

            global_source_times = (
                self._source_times()
            )

            global_parsed_times = (
                self._parsed_source_times(
                    global_source_times
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
                    "Unable to obtain real HYCOM source times: "
                    f"{exc}"
                ),
            )

        # ---------------------------------------------------------------------
        # STARTING MODEL STATE
        #
        # Use the latest real HYCOM source time at or before the vessel
        # departure.
        #
        # This avoids looking into a future model state.
        # ---------------------------------------------------------------------

        starting_global_index = (
            self._latest_source_index_at_or_before(
                departure_time,
                global_parsed_times,
            )
        )

        if starting_global_index is None:

            return AStarResult(
                found=False,
                goal_state=None,
                route=[],
                expanded_nodes=0,
                generated_nodes=0,
                message=(
                    "Requested vessel departure occurs before "
                    "the earliest available INCOIS HYCOM source time."
                ),
                departure_vessel_time_utc=(
                    format_utc(
                        departure_time
                    )
                ),
                model_times_utc=(
                    global_source_times
                ),
            )

        starting_model_time = (
            global_source_times[
                starting_global_index
            ]
        )

        # ---------------------------------------------------------------------
        # SEARCH-LOCAL MODEL TIME AXIS
        #
        # time_index 0 is always the first model layer used by this search.
        # ---------------------------------------------------------------------

        search_model_times = (
            global_source_times[
                starting_global_index:
            ]
        )

        search_model_datetimes = (
            global_parsed_times[
                starting_global_index:
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
                    "No real HYCOM model-time layers are available."
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
        # START
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

        # ---------------------------------------------------------------------
        # GOAL
        # ---------------------------------------------------------------------
        #
        # Goal location has no fixed model time. The vessel may reach the
        # destination in any valid environmental layer.
        # ---------------------------------------------------------------------

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
        # SCORES
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

        # Physical vessel elapsed time at each state.
        vessel_elapsed_seconds: dict[
            SearchState,
            float,
        ] = {
            start: 0.0
        }

        expanded_nodes = 0
        generated_nodes = 1

        # ---------------------------------------------------------------------
        # CACHE
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
                    "Unable to sample starting environment: "
                    f"{exc}"
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
        # MAIN LOOP
        # ---------------------------------------------------------------------

        while open_heap:

            (
                _priority,
                _counter,
                current,
            ) = heappop(
                open_heap
            )

            current_g = g_score.get(
                current,
                float("inf"),
            )

            current_vessel_elapsed = (
                vessel_elapsed_seconds.get(
                    current,
                    float("inf"),
                )
            )

            current_vessel_time = (
                departure_time
                + timedelta(
                    seconds=current_vessel_elapsed
                )
            )

            # -------------------------------------------------------------
            # GOAL / EARLIEST-ARRIVAL CONSTRAINT
            # -------------------------------------------------------------

            minimum_arrival_satisfied = (
                minimum_arrival_time is None
                or current_vessel_time >= minimum_arrival_time
            )

            if (
                reached_goal(current)
                and minimum_arrival_satisfied
            ):

                route = (
                    self._reconstruct_route(
                        current,
                        parents,
                    )
                )

                elapsed_values = [
                    vessel_elapsed_seconds.get(
                        state,
                        0.0,
                    )
                    for state in route
                ]

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
                        "INCOIS HYCOM source-time states "
                        "with physically tracked vessel time."
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
                    vessel_elapsed_seconds=(
                        elapsed_values
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
            # CURRENT PHYSICAL VESSEL TIME
            # -------------------------------------------------------------
            # Already calculated before the goal check so the same physical
            # clock is used consistently by the goal constraint, waiting
            # transition, and spatial-transition logic.

            # -------------------------------------------------------------
            # CURRENT / NEXT MODEL TIME
            # -------------------------------------------------------------

            current_model_time = (
                search_model_datetimes[
                    current.time_index
                ]
            )

            next_model_time = None

            if (
                current.time_index + 1
                < len(
                    search_model_datetimes
                )
            ):

                next_model_time = (
                    search_model_datetimes[
                        current.time_index + 1
                    ]
                )

            # =============================================================
            # EXPLICIT MODEL-TIME SYNCHRONIZATION
            # =============================================================
            #
            # This action is separate from normal spatial movement.
            #
            # It is available only when waiting is enabled.
            #
            # The vessel stays at the same coordinates and waits until the
            # next REAL HYCOM source time.
            # =============================================================

            if (
                request.allow_waiting
                and next_model_time is not None
            ):

                wait_seconds = (
                    next_model_time
                    - current_vessel_time
                ).total_seconds()

                # Only a future boundary can be waited for.
                if wait_seconds > EPSILON:

                    wait_hours = (
                        wait_seconds
                        / 3600.0
                    )

                    if (
                        constraints.max_route_duration_hours
                        is None
                        or (
                            (
                                current_vessel_elapsed
                                + wait_seconds
                            )
                            / 3600.0
                            <= constraints.max_route_duration_hours
                        )
                    ):

                        wait_state = SearchState(
                            latitude=(
                                current.latitude
                            ),
                            longitude=(
                                current.longitude
                            ),
                            depth_m=(
                                current.depth_m
                            ),
                            time_index=(
                                current.time_index
                                + 1
                            ),
                        )

                        # Waiting itself gets a small deterministic cost.
                        waiting_cost = (
                            wait_hours
                            * request.weights.waiting_penalty_weight
                        )

                        tentative_wait_g = (
                            current_g
                            + waiting_cost
                        )

                        known_wait_g = (
                            g_score.get(
                                wait_state,
                                float("inf"),
                            )
                        )

                        if (
                            tentative_wait_g
                            < known_wait_g
                        ):

                            try:
                                wait_environment = (
                                    get_environment(
                                        wait_state
                                    )
                                )

                                wait_edge = NavigationEdgeCost(
    distance_m=0.0,

    distance_cost=0.0,

    route_bearing_math_deg=0.0,

    along_route_current_m_s=0.0,
    opposing_current_m_s=0.0,
    cross_route_current_m_s=0.0,

    vessel_speed_m_s=(
        constraints.vessel_speed_m_s
    ),

    effective_ground_speed_m_s=(
        constraints.vessel_speed_m_s
    ),

    travel_time_seconds=(
        wait_seconds
    ),

    travel_time_hours=(
        wait_hours
    ),

    time_cost=(
        wait_hours
        * request.weights.time_penalty_weight
    ),

    current_penalty=0.0,
    hazard_penalty=0.0,

    total_cost=(
        waiting_cost
    ),

    traversable=True,

    blocked_reason=None,
)

                            except Exception as exc:
                                print(
                                    "WAIT TRANSITION REJECTED:"
                                    f" {exc}"
                                )

                                wait_environment = None
                                wait_edge = None
                            if (
                                wait_environment
                                is not None
                                and wait_edge
                                is not None
                            ):

                                g_score[
                                    wait_state
                                ] = tentative_wait_g

                                vessel_elapsed_seconds[
                                    wait_state
                                ] = (
                                    current_vessel_elapsed
                                    + wait_seconds
                                )

                                parents[
                                    wait_state
                                ] = ParentRecord(
                                    parent=current,
                                    edge_cost=wait_edge,
                                    environment=(
                                        wait_environment
                                    ),
                                )

                                wait_h = (
                                    heuristic_cost(
                                        state=wait_state,
                                        goal=goal,
                                        vessel_speed_m_s=(
                                            constraints
                                            .vessel_speed_m_s
                                        ),
                                    )
                                )

                                counter += 1

                                heappush(
                                    open_heap,
                                    (
                                        tentative_wait_g
                                        + wait_h,
                                        counter,
                                        wait_state,
                                    ),
                                )

                                generated_nodes += 1

            # =============================================================
            # NORMAL SPATIAL / DEPTH TRANSITIONS
            # =============================================================

            neighbors = (
                self.neighbor_generator.neighbors(
                    current,
                    target_depth_m=(
                        goal.depth_m
                    ),
                    allow_waiting=False,
                )
            )

            for candidate in neighbors:

                # ---------------------------------------------------------
                # DEPTH CONSTRAINTS
                # ---------------------------------------------------------

                if (
                    constraints.min_depth_m
                    is not None
                    and candidate.depth_m
                    < constraints.min_depth_m
                ):

                    continue

                if (
                    constraints.max_depth_m
                    is not None
                    and candidate.depth_m
                    > constraints.max_depth_m
                ):

                    continue

                # ---------------------------------------------------------
                # GEOMETRY
                # ---------------------------------------------------------

                distance_m = (
                    haversine_distance_m(
                        current.latitude,
                        current.longitude,
                        candidate.latitude,
                        candidate.longitude,
                    )
                )

                bearing_deg = (
                    route_bearing_math_deg(
                        current.latitude,
                        current.longitude,
                        candidate.latitude,
                        candidate.longitude,
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

                edge_travel_seconds = float(
                    edge_cost.travel_time_seconds
                )

                if edge_travel_seconds < 0.0:

                    continue

                # ---------------------------------------------------------
                # PHYSICAL VESSEL ARRIVAL
                # ---------------------------------------------------------

                tentative_vessel_elapsed = (
                    current_vessel_elapsed
                    + edge_travel_seconds
                )

                tentative_vessel_time = (
                    departure_time
                    + timedelta(
                        seconds=(
                            tentative_vessel_elapsed
                        )
                    )
                )

                # ---------------------------------------------------------
                # MODEL BOUNDARY RULE
                #
                # A moving edge may not silently cross a source-time
                # boundary.
                #
                # Example:
                #
                # current model state = 06:00
                # next model state    = 12:00
                #
                # if the moving edge ends at 12:03, it is rejected.
                #
                # The search can instead wait explicitly at the current
                # position until 12:00 and then move using the new state.
                #
                # This is intentionally conservative.
                # ---------------------------------------------------------

                if (
                    next_model_time is not None
                    and tentative_vessel_time
                    > next_model_time
                    + timedelta(
                        seconds=EPSILON
                    )
                ):

                    continue

                # ---------------------------------------------------------
                # DETERMINE MODEL STATE AT ARRIVAL
                # ---------------------------------------------------------

                candidate_model_index = (
                    self._latest_source_index_at_or_before(
                        tentative_vessel_time,
                        search_model_datetimes,
                    )
                )

                if candidate_model_index is None:

                    continue

                # ---------------------------------------------------------
                # Normal movement can remain in the current model state
                # or arrive exactly at the next boundary.
                # ---------------------------------------------------------

                if (
                    candidate_model_index
                    > current.time_index + 1
                ):

                    continue

                neighbor = SearchState(
                    latitude=(
                        candidate.latitude
                    ),
                    longitude=(
                        candidate.longitude
                    ),
                    depth_m=(
                        candidate.depth_m
                    ),
                    time_index=(
                        candidate_model_index
                    ),
                )

                # ---------------------------------------------------------
                # ROUTE DURATION
                # ---------------------------------------------------------

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
                # DESTINATION ENVIRONMENT
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
                # PATH UPDATE
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
                            constraints
                            .vessel_speed_m_s
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
    # RESULT CONVERSION
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
                        "Piecewise exact INCOIS HYCOM "
                        "source-time states with explicit "
                        "boundary synchronization"
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

        model_times = (
            search.model_times_utc
            or []
        )

        vessel_elapsed_values = (
            search.vessel_elapsed_seconds
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

        # ---------------------------------------------------------------------
        # CONVERT EACH SEARCH STATE
        # ---------------------------------------------------------------------

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
                        "Route contained an invalid "
                        "HYCOM source-time index."
                    ),
                    route=[],
                    metrics=NavigationMetrics(),
                    synthetic_data=False,
                    interpolation=False,
                )

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

                if edge.traversable:

                    segment_cost = (
                        edge.total_cost
                    )

                    segment_travel_seconds = (
                        float(
                            edge.travel_time_seconds
                        )
                    )

                    # ---------------------------------------------------------
                    # Spatial segment.
                    # ---------------------------------------------------------

                    if segment_distance_m > EPSILON:

                        total_distance_m += (
                            segment_distance_m
                        )

                        total_travel_seconds += (
                            segment_travel_seconds
                        )

                    # ---------------------------------------------------------
                    # Explicit model-boundary wait.
                    #
                    # Same spatial coordinates and a changed model index
                    # means this transition represents the explicit wait
                    # until the next real source timestamp.
                    # ---------------------------------------------------------

                    else:

                        total_travel_seconds += (
                            segment_travel_seconds
                        )

                else:

                    return NavigationResult(
                        status="unavailable",
                        mode=request.mode,
                        available=False,
                        message=(
                            "A reconstructed route segment "
                            "was not traversable."
                        ),
                        route=[],
                        metrics=NavigationMetrics(),
                        synthetic_data=False,
                        interpolation=False,
                    )

            # -----------------------------------------------------------------
            # PHYSICAL VESSEL TIME
            # -----------------------------------------------------------------

            if index < len(
                vessel_elapsed_values
            ):

                vessel_elapsed_seconds = (
                    vessel_elapsed_values[
                        index
                    ]
                )

            else:

                vessel_elapsed_seconds = (
                    total_travel_seconds
                )

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
            # Current statistics
            # -----------------------------------------------------------------

            current_speed = (
                environment.current_speed_m_s
            )

            if current_speed is not None:

                current_speeds.append(
                    current_speed
                )

            # -----------------------------------------------------------------
            # Provenance
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
            # ROUTE POINT
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

                    # Backward-compatible physical vessel time.
                    time_utc=(
                        vessel_timestamp_utc
                    ),

                    vessel_time_utc=(
                        vessel_timestamp_utc
                    ),

                    model_time_utc=(
                        model_timestamp
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
        # TEMPORAL PROVENANCE
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
                "Piecewise exact INCOIS HYCOM "
                "source-time states with explicit "
                "model-boundary synchronization"
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

                "vessel_time_utc": (
                    "physical vessel arrival time"
                ),

                "model_time_utc": (
                    "exact INCOIS HYCOM source time "
                    "associated with the environmental state"
                ),

                "model_state_policy": (
                    "latest exact source time at or before "
                    "physical vessel state; boundary changes "
                    "occur only through explicit synchronization"
                ),

                "moving_edge_boundary_crossing": (
                    "rejected"
                ),

                "model_boundary_waiting": (
                    "explicit when allow_waiting=true"
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
                "using real environmental states, "
                "real INCOIS HYCOM source-time states, "
                "and physically tracked vessel time."
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

