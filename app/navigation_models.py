from __future__ import annotations

"""
OceanSight-V
Navigation models and contracts.

This module defines the backend contract for the common navigation engine.

Design goals:
    - Shared by Disaster, Logistics, Fisheries, and Naval modes.
    - Time-aware and ready for 4D A* routing.
    - Explicit scientific units.
    - No synthetic scientific data.
    - No hidden interpolation.
    - No pressure/depth ambiguity.

Scientific conventions:
    latitude/longitude -> degrees
    depth -> meters, positive downward
    time -> ISO-8601 UTC
    current U/V -> meters per second
    vessel speed -> meters per second

Important:
    These models describe the navigation contract only.
    They do not fabricate environmental values.
"""

from typing import Literal

from pydantic import BaseModel, Field, field_validator


# =============================================================================
# COMMON ENUMS
# =============================================================================

NavigationMode = Literal[
    "disaster",
    "logistics",
    "fisheries",
    "naval",
]

RoutingStatus = Literal[
    "success",
    "unavailable",
    "no_route",
    "invalid_request",
]


# =============================================================================
# WAYPOINT
# =============================================================================

class NavigationWaypoint(BaseModel):
    """
    A geographic waypoint.

    Latitude and longitude are expressed in degrees.
    Depth is optional because some routes are surface routes while
    others may be constrained to a subsurface operating depth.
    """

    latitude: float = Field(
        ...,
        ge=-90.0,
        le=90.0,
    )

    longitude: float = Field(
        ...,
        ge=-180.0,
        le=180.0,
    )

    depth_m: float = Field(
        default=0.0,
        ge=0.0,
    )

    name: str | None = None


# =============================================================================
# NAVIGATION CONSTRAINTS
# =============================================================================

class NavigationConstraints(BaseModel):
    """
    Operational constraints used by the routing engine.

    These are configuration values, not environmental observations.
    """

    vessel_speed_m_s: float = Field(
        ...,
        gt=0.0,
        description="Through-water vessel speed in m/s.",
    )

    max_route_duration_hours: float | None = Field(
        default=None,
        gt=0.0,
    )

    max_depth_m: float | None = Field(
        default=None,
        ge=0.0,
    )

    min_depth_m: float | None = Field(
        default=None,
        ge=0.0,
    )

    avoid_currents_above_m_s: float | None = Field(
        default=None,
        ge=0.0,
        description=(
            "Optional current-speed threshold for avoidance."
        ),
    )

    avoid_hazards: bool = True


# =============================================================================
# ROUTING WEIGHTS
# =============================================================================

class NavigationWeights(BaseModel):
    """
    Relative cost weights for the 4D routing engine.

    These values are intentionally configurable so each operational mode
    can use a different cost profile while sharing the same A* engine.
    """

    distance_weight: float = Field(
        default=1.0,
        ge=0.0,
    )

    current_penalty_weight: float = Field(
        default=1.0,
        ge=0.0,
    )

    hazard_penalty_weight: float = Field(
        default=1.0,
        ge=0.0,
    )

    time_penalty_weight: float = Field(
        default=1.0,
        ge=0.0,
    )

    waiting_penalty_weight: float = Field(
        default=0.25,
        ge=0.0,
    )


# =============================================================================
# ROUTING REQUEST
# =============================================================================

class NavigationRequest(BaseModel):
    """
    Common navigation request.

    This is the request contract that every operational interface can use.
    """

    mode: NavigationMode

    start: NavigationWaypoint

    destination: NavigationWaypoint

    departure_time_utc: str

    constraints: NavigationConstraints

    weights: NavigationWeights = Field(
        default_factory=NavigationWeights
    )

    requested_depth_m: float = Field(
        default=0.0,
        ge=0.0,
        description=(
            "Environmental current-field depth used for routing."
        ),
    )

    allow_waiting: bool = True

    max_search_nodes: int = Field(
        default=250_000,
        ge=1,
        le=2_000_000,
    )

    time_step_minutes: int = Field(
        default=60,
        ge=1,
        le=1_440,
    )

    @field_validator("departure_time_utc")
    @classmethod
    def validate_departure_time(
        cls,
        value: str,
    ) -> str:
        """
        Require an explicit timezone.

        Full ISO-8601 normalization is performed by the API layer so that
        this model remains reusable.
        """

        value = str(value).strip()

        if not value:
            raise ValueError(
                "departure_time_utc cannot be empty."
            )

        if not (
            value.endswith("Z")
            or "+" in value
            or value.count("-") >= 3
        ):
            raise ValueError(
                "departure_time_utc must include an explicit timezone."
            )

        return value


# =============================================================================
# ROUTE POINT
# =============================================================================

class NavigationRoutePoint(BaseModel):
    """
    One point in the resulting route.

    Environmental values are optional because a valid route should still
    be representable when a particular field is unavailable.
    """

    sequence: int = Field(
        ...,
        ge=0,
    )

    latitude: float = Field(
        ...,
        ge=-90.0,
        le=90.0,
    )

    longitude: float = Field(
        ...,
        ge=-180.0,
        le=180.0,
    )

    depth_m: float = Field(
        ...,
        ge=0.0,
    )

    time_utc: str

    segment_distance_m: float = Field(
        default=0.0,
        ge=0.0,
    )

    cumulative_distance_m: float = Field(
        default=0.0,
        ge=0.0,
    )

    vessel_speed_m_s: float | None = None

    u_current_m_s: float | None = None

    v_current_m_s: float | None = None

    current_speed_m_s: float | None = None

    current_direction_math_deg: float | None = None

    hazard_penalty: float | None = None

    segment_cost: float | None = None


# =============================================================================
# ROUTE METRICS
# =============================================================================

class NavigationMetrics(BaseModel):
    """
    Derived route metrics.

    These values are calculated from the selected scientific inputs and
    routing configuration.
    """

    total_distance_m: float = Field(
        default=0.0,
        ge=0.0,
    )

    total_distance_km: float = Field(
        default=0.0,
        ge=0.0,
    )

    travel_time_seconds: float = Field(
        default=0.0,
        ge=0.0,
    )

    travel_time_hours: float = Field(
        default=0.0,
        ge=0.0,
    )

    estimated_fuel_units: float | None = Field(
        default=None,
        ge=0.0,
    )

    max_current_speed_m_s: float | None = Field(
        default=None,
        ge=0.0,
    )

    average_current_speed_m_s: float | None = Field(
        default=None,
        ge=0.0,
    )

    hazard_exposure: float | None = Field(
        default=None,
        ge=0.0,
    )


# =============================================================================
# ROUTE RESULT
# =============================================================================

class NavigationResult(BaseModel):
    """
    Canonical response from the navigation engine.
    """

    status: RoutingStatus

    mode: NavigationMode

    available: bool

    message: str

    route: list[NavigationRoutePoint] = Field(
        default_factory=list
    )

    metrics: NavigationMetrics = Field(
        default_factory=NavigationMetrics
    )

    source_times_utc: list[str] = Field(
        default_factory=list
    )

    sources: list[str] = Field(
        default_factory=list
    )

    datasets: list[str] = Field(
        default_factory=list
    )

    scientific_units: dict[str, str] = Field(
        default_factory=lambda: {
            "latitude": "degrees",
            "longitude": "degrees",
            "depth": "m",
            "current": "m/s",
            "distance": "m",
            "time": "UTC",
        }
    )

    synthetic_data: bool = False

    interpolation: bool = False

    provenance: dict[str, object] = Field(
        default_factory=dict
    )