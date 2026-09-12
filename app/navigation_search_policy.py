from __future__ import annotations

"""
OceanSight-V
Navigation Search Policy

Purpose
-------
Protect the 4D navigation engine from uncontrolled searches.

This module does NOT:
    - fetch scientific data
    - calculate A*
    - generate ocean values
    - interpolate scientific data
    - modify HYCOM/Argo/GEBCO data

It validates the operational size of a navigation request before the
expensive environmental search begins.

IMPORTANT
---------
The spatial grid resolution is supplied by the caller.

This prevents the search policy from silently using a different grid
resolution from the actual A* engine.
"""

from dataclasses import dataclass
from math import ceil

from .navigation_models import NavigationRequest


# =============================================================================
# DEFAULT POLICY LIMITS
# =============================================================================

DEFAULT_MAX_LATITUDE_SPAN_DEG = 5.0
DEFAULT_MAX_LONGITUDE_SPAN_DEG = 5.0
DEFAULT_MAX_ROUTE_DURATION_HOURS = 168.0
DEFAULT_MAX_TIME_STEPS = 168
DEFAULT_MAX_DEPTH_M = 5000.0
DEFAULT_MAX_ALLOWED_NODE_BUDGET = 250_000

# Used only for conservative graph-size estimation.
DEFAULT_SPATIAL_BRANCHING_FACTOR = 8


# =============================================================================
# VALIDATION RESULT
# =============================================================================


@dataclass(frozen=True)
class SearchPolicyResult:
    """
    Result produced by search-policy validation.
    """

    allowed: bool
    message: str

    latitude_span_deg: float
    longitude_span_deg: float

    estimated_time_steps: int
    estimated_max_nodes: int

    latitude_step_deg: float
    longitude_step_deg: float


# =============================================================================
# POLICY
# =============================================================================


@dataclass(frozen=True)
class NavigationSearchPolicy:
    """
    Operational limits for a navigation request.

    These values are performance/safety limits.
    They are NOT scientific observations.
    """

    max_latitude_span_deg: float = (
        DEFAULT_MAX_LATITUDE_SPAN_DEG
    )

    max_longitude_span_deg: float = (
        DEFAULT_MAX_LONGITUDE_SPAN_DEG
    )

    max_route_duration_hours: float = (
        DEFAULT_MAX_ROUTE_DURATION_HOURS
    )

    max_time_steps: int = (
        DEFAULT_MAX_TIME_STEPS
    )

    max_depth_m: float = (
        DEFAULT_MAX_DEPTH_M
    )

    max_allowed_node_budget: int = (
        DEFAULT_MAX_ALLOWED_NODE_BUDGET
    )

    spatial_branching_factor: int = (
        DEFAULT_SPATIAL_BRANCHING_FACTOR
    )

    def __post_init__(self) -> None:

        if self.max_latitude_span_deg <= 0.0:
            raise ValueError(
                "max_latitude_span_deg must be greater than zero."
            )

        if self.max_longitude_span_deg <= 0.0:
            raise ValueError(
                "max_longitude_span_deg must be greater than zero."
            )

        if self.max_route_duration_hours <= 0.0:
            raise ValueError(
                "max_route_duration_hours must be greater than zero."
            )

        if self.max_time_steps <= 0:
            raise ValueError(
                "max_time_steps must be greater than zero."
            )

        if self.max_depth_m < 0.0:
            raise ValueError(
                "max_depth_m cannot be negative."
            )

        if self.max_allowed_node_budget <= 0:
            raise ValueError(
                "max_allowed_node_budget must be greater than zero."
            )

        if self.spatial_branching_factor <= 0:
            raise ValueError(
                "spatial_branching_factor must be greater than zero."
            )


# =============================================================================
# LONGITUDE HELPERS
# =============================================================================


def _longitude_span(
    longitude_1: float,
    longitude_2: float,
) -> float:
    """
    Return the smallest absolute longitude difference.

    Handles the ±180° wraparound correctly.
    """

    difference = abs(
        float(longitude_2)
        - float(longitude_1)
    )

    difference %= 360.0

    if difference > 180.0:
        difference = (
            360.0
            - difference
        )

    return difference


# =============================================================================
# REQUEST SPANS
# =============================================================================


def calculate_request_spans(
    request: NavigationRequest,
) -> tuple[float, float]:
    """
    Return the requested latitude and longitude spans.
    """

    latitude_span = abs(
        float(request.destination.latitude)
        - float(request.start.latitude)
    )

    longitude_span = _longitude_span(
        request.start.longitude,
        request.destination.longitude,
    )

    return (
        latitude_span,
        longitude_span,
    )


# =============================================================================
# TIME ESTIMATION
# =============================================================================


def estimate_time_steps(
    request: NavigationRequest,
) -> int:
    """
    Estimate the number of temporal graph states required.

    The calculation uses the request's actual configured time step.
    """

    if (
        request.constraints.max_route_duration_hours
        is not None
    ):
        duration_hours = float(
            request.constraints.max_route_duration_hours
        )
    else:
        duration_hours = (
            DEFAULT_MAX_ROUTE_DURATION_HOURS
        )

    step_hours = (
        float(request.time_step_minutes)
        / 60.0
    )

    if step_hours <= 0.0:
        raise ValueError(
            "time_step_minutes must be greater than zero."
        )

    return max(
        1,
        int(
            ceil(
                duration_hours
                / step_hours
            )
        ),
    )


# =============================================================================
# NODE ESTIMATION
# =============================================================================


def estimate_search_nodes(
    *,
    request: NavigationRequest,
    policy: NavigationSearchPolicy,
    latitude_step_deg: float,
    longitude_step_deg: float,
) -> int:
    """
    Estimate the maximum spatial-temporal graph size.

    IMPORTANT:
        latitude_step_deg and longitude_step_deg MUST be the same
        values used by the actual A* engine.

    This function only estimates graph size.
    It does not create scientific data.
    """

    if latitude_step_deg <= 0.0:
        raise ValueError(
            "latitude_step_deg must be greater than zero."
        )

    if longitude_step_deg <= 0.0:
        raise ValueError(
            "longitude_step_deg must be greater than zero."
        )

    latitude_span, longitude_span = (
        calculate_request_spans(
            request
        )
    )

    latitude_cells = max(
        1,
        int(
            ceil(
                latitude_span
                / float(latitude_step_deg)
            )
        )
        + 1,
    )

    longitude_cells = max(
        1,
        int(
            ceil(
                longitude_span
                / float(longitude_step_deg)
            )
        )
        + 1,
    )

    time_steps = estimate_time_steps(
        request
    )

    spatial_nodes = (
        latitude_cells
        * longitude_cells
    )

    # The graph contains multiple candidate transitions per state.
    # For a node-budget guard, the number of unique spatial-temporal
    # states is the primary estimate.
    #
    # The branching factor is retained as policy metadata but is not
    # multiplied into the node count because doing so would estimate
    # generated edges rather than graph nodes.
    estimated_nodes = (
        spatial_nodes
        * time_steps
    )

    return int(
        estimated_nodes
    )


# =============================================================================
# REQUEST VALIDATION
# =============================================================================


def validate_navigation_request(
    request: NavigationRequest,
    *,
    policy: NavigationSearchPolicy | None = None,
    latitude_step_deg: float = 0.05,
    longitude_step_deg: float = 0.05,
) -> SearchPolicyResult:
    """
    Validate the request against navigation search limits.

    The caller should pass the exact spatial resolution configured for
    the A* engine.

    Defaults match the current OceanSight A* configuration, but the
    values can be explicitly supplied so the two systems cannot silently
    drift apart.
    """

    active_policy = (
        policy
        if policy is not None
        else NavigationSearchPolicy()
    )

    latitude_step_deg = float(
        latitude_step_deg
    )

    longitude_step_deg = float(
        longitude_step_deg
    )

    if latitude_step_deg <= 0.0:
        raise ValueError(
            "latitude_step_deg must be greater than zero."
        )

    if longitude_step_deg <= 0.0:
        raise ValueError(
            "longitude_step_deg must be greater than zero."
        )

    latitude_span, longitude_span = (
        calculate_request_spans(
            request
        )
    )

    time_steps = estimate_time_steps(
        request
    )

    estimated_nodes = estimate_search_nodes(
        request=request,
        policy=active_policy,
        latitude_step_deg=(
            latitude_step_deg
        ),
        longitude_step_deg=(
            longitude_step_deg
        ),
    )

    # -------------------------------------------------------------------------
    # Geographic latitude span
    # -------------------------------------------------------------------------

    if (
        latitude_span
        > active_policy.max_latitude_span_deg
    ):
        return SearchPolicyResult(
            allowed=False,
            message=(
                "Navigation request exceeds the maximum "
                f"latitude span of "
                f"{active_policy.max_latitude_span_deg}°. "
                f"Requested: {latitude_span:.6f}°."
            ),
            latitude_span_deg=latitude_span,
            longitude_span_deg=longitude_span,
            estimated_time_steps=time_steps,
            estimated_max_nodes=estimated_nodes,
            latitude_step_deg=latitude_step_deg,
            longitude_step_deg=longitude_step_deg,
        )

    # -------------------------------------------------------------------------
    # Geographic longitude span
    # -------------------------------------------------------------------------

    if (
        longitude_span
        > active_policy.max_longitude_span_deg
    ):
        return SearchPolicyResult(
            allowed=False,
            message=(
                "Navigation request exceeds the maximum "
                f"longitude span of "
                f"{active_policy.max_longitude_span_deg}°. "
                f"Requested: {longitude_span:.6f}°."
            ),
            latitude_span_deg=latitude_span,
            longitude_span_deg=longitude_span,
            estimated_time_steps=time_steps,
            estimated_max_nodes=estimated_nodes,
            latitude_step_deg=latitude_step_deg,
            longitude_step_deg=longitude_step_deg,
        )

    # -------------------------------------------------------------------------
    # Depth
    # -------------------------------------------------------------------------

    maximum_requested_depth = max(
        float(request.start.depth_m),
        float(request.destination.depth_m),
        float(request.requested_depth_m),
    )

    if (
        request.constraints.max_depth_m
        is not None
    ):
        maximum_requested_depth = max(
            maximum_requested_depth,
            float(
                request.constraints.max_depth_m
            ),
        )

    if (
        maximum_requested_depth
        > active_policy.max_depth_m
    ):
        return SearchPolicyResult(
            allowed=False,
            message=(
                "Navigation request exceeds the maximum "
                f"supported depth of "
                f"{active_policy.max_depth_m:.1f} m."
            ),
            latitude_span_deg=latitude_span,
            longitude_span_deg=longitude_span,
            estimated_time_steps=time_steps,
            estimated_max_nodes=estimated_nodes,
            latitude_step_deg=latitude_step_deg,
            longitude_step_deg=longitude_step_deg,
        )

    # -------------------------------------------------------------------------
    # Route duration
    # -------------------------------------------------------------------------

    requested_duration = (
        request.constraints.max_route_duration_hours
    )

    if (
        requested_duration is not None
        and requested_duration
        > active_policy.max_route_duration_hours
    ):
        return SearchPolicyResult(
            allowed=False,
            message=(
                "Navigation request exceeds the maximum "
                f"route-duration policy of "
                f"{active_policy.max_route_duration_hours:.1f} hours."
            ),
            latitude_span_deg=latitude_span,
            longitude_span_deg=longitude_span,
            estimated_time_steps=time_steps,
            estimated_max_nodes=estimated_nodes,
            latitude_step_deg=latitude_step_deg,
            longitude_step_deg=longitude_step_deg,
        )

    # -------------------------------------------------------------------------
    # Time-step count
    # -------------------------------------------------------------------------

    if (
        time_steps
        > active_policy.max_time_steps
    ):
        return SearchPolicyResult(
            allowed=False,
            message=(
                "Navigation request requires too many "
                f"time steps: {time_steps}."
            ),
            latitude_span_deg=latitude_span,
            longitude_span_deg=longitude_span,
            estimated_time_steps=time_steps,
            estimated_max_nodes=estimated_nodes,
            latitude_step_deg=latitude_step_deg,
            longitude_step_deg=longitude_step_deg,
        )

    # -------------------------------------------------------------------------
    # Estimated node budget
    # -------------------------------------------------------------------------

    if (
        estimated_nodes
        > active_policy.max_allowed_node_budget
    ):
        return SearchPolicyResult(
            allowed=False,
            message=(
                "Estimated navigation graph exceeds the "
                f"allowed node budget of "
                f"{active_policy.max_allowed_node_budget:,}. "
                f"Estimated: {estimated_nodes:,}."
            ),
            latitude_span_deg=latitude_span,
            longitude_span_deg=longitude_span,
            estimated_time_steps=time_steps,
            estimated_max_nodes=estimated_nodes,
            latitude_step_deg=latitude_step_deg,
            longitude_step_deg=longitude_step_deg,
        )

    # -------------------------------------------------------------------------
    # Allowed
    # -------------------------------------------------------------------------

    return SearchPolicyResult(
        allowed=True,
        message=(
            "Navigation request satisfies search policy."
        ),
        latitude_span_deg=latitude_span,
        longitude_span_deg=longitude_span,
        estimated_time_steps=time_steps,
        estimated_max_nodes=estimated_nodes,
        latitude_step_deg=latitude_step_deg,
        longitude_step_deg=longitude_step_deg,
    )


# =============================================================================
# STRICT ENFORCEMENT
# =============================================================================


def enforce_navigation_policy(
    request: NavigationRequest,
    *,
    policy: NavigationSearchPolicy | None = None,
    latitude_step_deg: float = 0.05,
    longitude_step_deg: float = 0.05,
) -> SearchPolicyResult:
    """
    Validate the navigation request and raise ValueError when rejected.
    """

    result = validate_navigation_request(
        request,
        policy=policy,
        latitude_step_deg=latitude_step_deg,
        longitude_step_deg=longitude_step_deg,
    )

    if not result.allowed:
        raise ValueError(
            result.message
        )

    return result