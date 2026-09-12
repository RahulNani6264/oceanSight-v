from __future__ import annotations

"""
OceanSight-V
Navigation Cost Engine

Purpose
-------
Calculate deterministic routing costs for the common OceanSight-V
navigation engine.

This module DOES NOT:
    - fetch ocean data
    - fabricate environmental values
    - perform A* search
    - interpolate missing scientific fields
    - modify HYCOM/Argo/GEBCO data

It consumes:
    - a real NavigationEnvironmentState
    - an explicit route segment distance
    - an explicit route bearing
    - vessel configuration
    - routing weights
    - optional hazard penalty supplied by a future hazard engine

The same cost engine can therefore be used by:
    Disaster
    Logistics
    Fisheries
    Naval
"""

from dataclasses import dataclass
from math import cos, radians, sin, sqrt

from .navigation_environment import NavigationEnvironmentState
from .navigation_models import NavigationConstraints, NavigationWeights


# =============================================================================
# CONSTANTS
# =============================================================================

EPSILON = 1.0e-12

# Cost scaling constants.
#
# These are numerical normalization factors only. They do not represent
# synthetic environmental observations.
CURRENT_REFERENCE_M_S = 1.0
TIME_REFERENCE_SECONDS = 3600.0
DISTANCE_REFERENCE_KM = 1.0


# =============================================================================
# RESULT MODEL
# =============================================================================


@dataclass(frozen=True)
class NavigationEdgeCost:
    """
    Deterministic cost calculation for one navigation edge.
    """

    distance_m: float
    distance_cost: float

    route_bearing_math_deg: float

    along_route_current_m_s: float
    opposing_current_m_s: float
    cross_route_current_m_s: float

    vessel_speed_m_s: float
    effective_ground_speed_m_s: float

    travel_time_seconds: float
    travel_time_hours: float
    time_cost: float

    current_penalty: float
    hazard_penalty: float

    total_cost: float

    traversable: bool
    blocked_reason: str | None


# =============================================================================
# BASIC VECTOR HELPERS
# =============================================================================


def route_unit_vector(
    bearing_math_deg: float,
) -> tuple[float, float]:
    """
    Convert mathematical bearing into an east/north unit vector.

    Mathematical angle convention:
        0°   = east
        90°  = north
        180° = west
        270° = south
    """

    angle = radians(
        float(bearing_math_deg)
    )

    east = cos(angle)
    north = sin(angle)

    return east, north


def project_current_onto_route(
    *,
    u_current_m_s: float,
    v_current_m_s: float,
    route_bearing_math_deg: float,
) -> tuple[float, float]:
    """
    Project the current vector into:

        along-route component
        cross-route component
    """

    east_unit, north_unit = route_unit_vector(
        route_bearing_math_deg
    )

    along = (
        u_current_m_s * east_unit
        + v_current_m_s * north_unit
    )

    cross = (
        -u_current_m_s * north_unit
        + v_current_m_s * east_unit
    )

    return along, cross


# =============================================================================
# DISTANCE COST
# =============================================================================


def calculate_distance_cost(
    *,
    distance_m: float,
    weights: NavigationWeights,
) -> float:
    """
    Normalize distance in kilometres and apply the route weight.
    """

    if distance_m < 0.0:
        raise ValueError(
            "distance_m cannot be negative."
        )

    distance_km = (
        float(distance_m) / 1000.0
    )

    normalized_distance = (
        distance_km / DISTANCE_REFERENCE_KM
    )

    return (
        float(weights.distance_weight)
        * normalized_distance
    )


# =============================================================================
# CURRENT COST
# =============================================================================


def calculate_current_penalty(
    *,
    environment: NavigationEnvironmentState,
    route_bearing_math_deg: float,
    constraints: NavigationConstraints,
    weights: NavigationWeights,
) -> tuple[
    float,
    float,
    float,
    float,
]:
    """
    Calculate current-related routing quantities.

    Returns:
        along_route_current_m_s
        opposing_current_m_s
        cross_route_current_m_s
        current_penalty

    Important:
        Current values must come from the real scientific environment.
        Missing U/V means the edge cannot receive a scientific current
        penalty and is therefore treated as non-traversable by this
        strict navigation stage.
    """

    u = environment.u_current_m_s
    v = environment.v_current_m_s

    if u is None or v is None:
        raise ValueError(
            "Real U/V current data is unavailable for this navigation state."
        )

    along, cross = project_current_onto_route(
        u_current_m_s=float(u),
        v_current_m_s=float(v),
        route_bearing_math_deg=float(
            route_bearing_math_deg
        ),
    )

    opposing = max(
        0.0,
        -along,
    )

    # Optional hard threshold.
    #
    # Example:
    #     avoid_currents_above_m_s = 1.0
    #
    # means an opposing current stronger than 1 m/s may be rejected
    # by the navigation service.
    threshold = (
        constraints.avoid_currents_above_m_s
    )

    if (
        threshold is not None
        and opposing > threshold
    ):
        raise ValueError(
            (
                "Opposing current exceeds the configured "
                "avoidance threshold: "
                f"{opposing:.6f} m/s > "
                f"{threshold:.6f} m/s."
            )
        )

    normalized_opposing = (
        opposing / CURRENT_REFERENCE_M_S
    )

    penalty = (
        float(weights.current_penalty_weight)
        * normalized_opposing
    )

    return (
        along,
        opposing,
        cross,
        penalty,
    )


# =============================================================================
# EFFECTIVE SPEED
# =============================================================================


def calculate_effective_ground_speed(
    *,
    vessel_speed_m_s: float,
    along_route_current_m_s: float,
) -> float:
    """
    Calculate speed along the intended route.

    ground speed along route =
        vessel through-water speed
        + current component along route

    A strong opposing current can reduce this to zero or below, in which
    case the segment is not traversable under the current operating speed.
    """

    if vessel_speed_m_s <= 0.0:
        raise ValueError(
            "vessel_speed_m_s must be greater than zero."
        )

    return (
        float(vessel_speed_m_s)
        + float(along_route_current_m_s)
    )


# =============================================================================
# TIME COST
# =============================================================================


def calculate_time_cost(
    *,
    distance_m: float,
    effective_ground_speed_m_s: float,
    weights: NavigationWeights,
) -> tuple[
    float,
    float,
    float,
]:
    """
    Return:

        travel time in seconds
        travel time in hours
        weighted time cost
    """

    if distance_m < 0.0:
        raise ValueError(
            "distance_m cannot be negative."
        )

    if effective_ground_speed_m_s <= EPSILON:
        raise ValueError(
            "Effective ground speed is not positive."
        )

    travel_time_seconds = (
        float(distance_m)
        / float(effective_ground_speed_m_s)
    )

    travel_time_hours = (
        travel_time_seconds
        / TIME_REFERENCE_SECONDS
    )

    time_cost = (
        float(weights.time_penalty_weight)
        * travel_time_hours
    )

    return (
        travel_time_seconds,
        travel_time_hours,
        time_cost,
    )


# =============================================================================
# HAZARD COST
# =============================================================================


def validate_hazard_penalty(
    hazard_penalty: float | None,
) -> float:
    """
    Validate an externally supplied hazard penalty.

    The hazard engine will later provide this value.

    Until then, callers should explicitly provide 0.0 when no hazard
    layer is part of the route calculation.
    """

    if hazard_penalty is None:
        return 0.0

    value = float(
        hazard_penalty
    )

    if value < 0.0:
        raise ValueError(
            "hazard_penalty cannot be negative."
        )

    return value


def calculate_hazard_cost(
    *,
    hazard_penalty: float | None,
    weights: NavigationWeights,
) -> float:
    """
    Apply the configured hazard weight to an externally supplied
    hazard penalty.
    """

    penalty = validate_hazard_penalty(
        hazard_penalty
    )

    return (
        float(weights.hazard_penalty_weight)
        * penalty
    )


# =============================================================================
# TOTAL COST
# =============================================================================


def calculate_total_cost(
    *,
    distance_cost: float,
    current_penalty: float,
    time_cost: float,
    hazard_cost: float,
) -> float:
    """
    Sum independent routing cost components.
    """

    values = (
        distance_cost,
        current_penalty,
        time_cost,
        hazard_cost,
    )

    if any(
        float(value) < 0.0
        for value in values
    ):
        raise ValueError(
            "Navigation cost components cannot be negative."
        )

    return sum(
        float(value)
        for value in values
    )


# =============================================================================
# MAIN EDGE COST CALCULATOR
# =============================================================================


def calculate_edge_cost(
    *,
    environment: NavigationEnvironmentState,
    distance_m: float,
    route_bearing_math_deg: float,
    constraints: NavigationConstraints,
    weights: NavigationWeights,
    hazard_penalty: float | None = 0.0,
) -> NavigationEdgeCost:
    """
    Calculate the complete cost of traversing one route edge.

    Scientific behavior:
        - Requires real U/V.
        - Never invents missing currents.
        - Never interpolates.
        - Preserves the environment source information.
        - Does not modify environmental data.
    """

    distance_m = float(
        distance_m
    )

    route_bearing_math_deg = (
        float(route_bearing_math_deg)
        % 360.0
    )

    if distance_m < 0.0:
        raise ValueError(
            "distance_m cannot be negative."
        )

    vessel_speed = float(
        constraints.vessel_speed_m_s
    )

    if vessel_speed <= 0.0:
        raise ValueError(
            "vessel_speed_m_s must be greater than zero."
        )

    # -------------------------------------------------------------------------
    # Scientific integrity guard.
    # -------------------------------------------------------------------------

    if environment.synthetic_data:
        raise ValueError(
            "Synthetic environmental data cannot be used for navigation."
        )

    if environment.interpolation:
        raise ValueError(
            "Interpolated environmental data cannot be used at this stage."
        )

    if (
        environment.u_current_m_s is None
        or environment.v_current_m_s is None
    ):
        raise ValueError(
            "Navigation requires real U/V current values."
        )

    # -------------------------------------------------------------------------
    # Distance
    # -------------------------------------------------------------------------

    distance_cost = calculate_distance_cost(
        distance_m=distance_m,
        weights=weights,
    )

    # -------------------------------------------------------------------------
    # Current
    # -------------------------------------------------------------------------

    (
        along_current,
        opposing_current,
        cross_current,
        current_penalty,
    ) = calculate_current_penalty(
        environment=environment,
        route_bearing_math_deg=route_bearing_math_deg,
        constraints=constraints,
        weights=weights,
    )

    # -------------------------------------------------------------------------
    # Effective speed
    # -------------------------------------------------------------------------

    effective_ground_speed = (
        calculate_effective_ground_speed(
            vessel_speed_m_s=vessel_speed,
            along_route_current_m_s=along_current,
        )
    )

    # -------------------------------------------------------------------------
    # Traversability
    # -------------------------------------------------------------------------

    if effective_ground_speed <= EPSILON:

        return NavigationEdgeCost(
            distance_m=distance_m,
            distance_cost=distance_cost,

            route_bearing_math_deg=(
                route_bearing_math_deg
            ),

            along_route_current_m_s=(
                along_current
            ),

            opposing_current_m_s=(
                opposing_current
            ),

            cross_route_current_m_s=(
                cross_current
            ),

            vessel_speed_m_s=vessel_speed,

            effective_ground_speed_m_s=(
                effective_ground_speed
            ),

            travel_time_seconds=(
                float("inf")
            ),

            travel_time_hours=(
                float("inf")
            ),

            time_cost=float("inf"),

            current_penalty=current_penalty,

            hazard_penalty=validate_hazard_penalty(
                hazard_penalty
            ),

            total_cost=float("inf"),

            traversable=False,

            blocked_reason=(
                "Opposing current prevents positive "
                "forward ground speed at the configured "
                "vessel speed."
            ),
        )

    # -------------------------------------------------------------------------
    # Time
    # -------------------------------------------------------------------------

    (
        travel_time_seconds,
        travel_time_hours,
        time_cost,
    ) = calculate_time_cost(
        distance_m=distance_m,
        effective_ground_speed_m_s=(
            effective_ground_speed
        ),
        weights=weights,
    )

    # -------------------------------------------------------------------------
    # Hazard
    # -------------------------------------------------------------------------

    hazard_cost = calculate_hazard_cost(
        hazard_penalty=hazard_penalty,
        weights=weights,
    )

    # -------------------------------------------------------------------------
    # Total
    # -------------------------------------------------------------------------

    total_cost = calculate_total_cost(
        distance_cost=distance_cost,
        current_penalty=current_penalty,
        time_cost=time_cost,
        hazard_cost=hazard_cost,
    )

    return NavigationEdgeCost(
        distance_m=distance_m,

        distance_cost=distance_cost,

        route_bearing_math_deg=(
            route_bearing_math_deg
        ),

        along_route_current_m_s=(
            along_current
        ),

        opposing_current_m_s=(
            opposing_current
        ),

        cross_route_current_m_s=(
            cross_current
        ),

        vessel_speed_m_s=vessel_speed,

        effective_ground_speed_m_s=(
            effective_ground_speed
        ),

        travel_time_seconds=(
            travel_time_seconds
        ),

        travel_time_hours=(
            travel_time_hours
        ),

        time_cost=time_cost,

        current_penalty=current_penalty,

        hazard_penalty=hazard_cost,

        total_cost=total_cost,

        traversable=True,

        blocked_reason=None,
    )


# =============================================================================
# PROFILE FACTORIES
# =============================================================================


def disaster_weights() -> NavigationWeights:
    """
    Default routing profile for disaster operations.

    This is an operational profile, not environmental data.
    """

    return NavigationWeights(
        distance_weight=1.0,
        current_penalty_weight=1.5,
        hazard_penalty_weight=5.0,
        time_penalty_weight=2.0,
        waiting_penalty_weight=0.5,
    )


def logistics_weights() -> NavigationWeights:
    """
    Default routing profile for commercial logistics.

    Emphasizes current and travel-time efficiency.
    """

    return NavigationWeights(
        distance_weight=1.0,
        current_penalty_weight=2.5,
        hazard_penalty_weight=2.0,
        time_penalty_weight=2.5,
        waiting_penalty_weight=0.25,
    )


def fisheries_weights() -> NavigationWeights:
    """
    Default routing profile for fisheries operations.

    The specialized fisheries engine can later add additional ecological
    constraints without changing this core cost implementation.
    """

    return NavigationWeights(
        distance_weight=1.0,
        current_penalty_weight=1.5,
        hazard_penalty_weight=2.0,
        time_penalty_weight=1.0,
        waiting_penalty_weight=0.25,
    )


def naval_weights() -> NavigationWeights:
    """
    Default routing profile for naval operations.

    Specialized acoustic/subsurface constraints will be incorporated by
    the future naval engine.
    """

    return NavigationWeights(
        distance_weight=1.0,
        current_penalty_weight=2.0,
        hazard_penalty_weight=4.0,
        time_penalty_weight=1.5,
        waiting_penalty_weight=0.5,
    )