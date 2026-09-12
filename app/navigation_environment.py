from __future__ import annotations

"""
OceanSight-V
Navigation Environment Adapter

Purpose:
    Provide the navigation engine with real ocean-environment state.

This module is intentionally an adapter around the existing OceanSight-V
scientific query layer.

It does NOT:
    - generate synthetic ocean values
    - interpolate missing values
    - convert Argo pressure to depth
    - invent missing timestamps
    - implement A*
    - implement route optimization
    - silently replace vessel time with a different model time

Primary scientific source:
    INCOIS HYCOM

Supporting terrain source:
    GEBCO

Scientific conventions:
    depth   -> meters, positive downward
    U       -> eastward current, m/s
    V       -> northward current, m/s
    speed   -> m/s
    time    -> UTC

Temporal rule:
    HYCOM environmental sampling in this adapter must use an ACTUAL
    INCOIS HYCOM source TIME.

    A vessel/navigation timestamp may be different from the model
    timestamp, but that distinction must be handled explicitly by
    the navigation time layer.

    This module therefore never silently performs:

        vessel_time -> nearest model time

    and never interpolates between source times.
"""

from dataclasses import dataclass
from typing import Any

from .navigation_time import NavigationTimeAdapter

from .ocean_3d_query import Ocean3DQueryEngine


# =============================================================================
# NAVIGATION ENVIRONMENT STATE
# =============================================================================


@dataclass(frozen=True)
class NavigationEnvironmentState:
    """
    Real environmental state sampled at one navigation state.

    requested_* fields:
        Values requested by the navigation engine.

    actual_* fields:
        Actual source grid/time selected by the scientific query layer.

    Temporal distinction:

        requested_time_utc
            = navigation/requested time

        actual_time_utc
            = actual HYCOM source TIME used for the environmental query

    They are intentionally allowed to be different because vessel time
    and model source time are different concepts.

    This adapter itself never invents or interpolates a model timestamp.
    """

    requested_latitude: float
    requested_longitude: float
    requested_depth_m: float
    requested_time_utc: str

    actual_latitude: float | None
    actual_longitude: float | None
    actual_depth_m: float | None
    actual_time_utc: str | None

    temperature_c: float | None
    salinity_psu: float | None

    u_current_m_s: float | None
    v_current_m_s: float | None
    current_speed_m_s: float | None
    current_direction_math_deg: float | None

    ssh_m: float | None

    bathymetry_elevation_m: float | None
    bathymetry_depth_m: float | None

    hycom_available: bool
    bathymetry_available: bool

    hycom_source: str | None
    hycom_dataset: str | None
    hycom_source_url: str | None

    bathymetry_source: str | None
    bathymetry_dataset: str | None
    bathymetry_source_url: str | None

    hycom_missing: dict[str, bool]
    synthetic_data: bool
    interpolation: bool

    provenance: dict[str, Any]


# =============================================================================
# ENVIRONMENT ADAPTER
# =============================================================================


class NavigationEnvironment:
    """
    Adapter between the navigation system and the existing scientific
    OceanSight-V query engine.

    A single NavigationEnvironment instance owns one scientific engine so
    repeated route-state queries reuse initialized backend components.

    Optional NavigationTimeAdapter support allows this class to validate
    that a supplied environmental model timestamp really exists in the
    INCOIS HYCOM TIME coordinate.

    IMPORTANT:

        Validation does NOT automatically replace a requested vessel
        timestamp with another model timestamp.

    The navigation engine must explicitly choose which model timestamp
    it wants to evaluate.
    """

    def __init__(
        self,
        engine: Ocean3DQueryEngine | None = None,
        time_adapter: NavigationTimeAdapter | None = None,
    ) -> None:

        self.engine = (
            engine
            if engine is not None
            else Ocean3DQueryEngine()
        )

        self.time_adapter = time_adapter

    # =========================================================================
    # SAFE FLOAT
    # =========================================================================

    @staticmethod
    def _safe_float(
        value: Any,
    ) -> float | None:

        if value is None:
            return None

        try:
            return float(value)

        except (
            TypeError,
            ValueError,
        ):
            return None

    # =========================================================================
    # TIME NORMALIZATION
    # =========================================================================

    @staticmethod
    def _normalize_time_text(
        time_utc: str,
    ) -> str:
        """
        Normalize a UTC timestamp using the existing HYCOM time utilities.

        This function does not alter the represented instant.
        """

        from .hycom_times import (
            datetime_to_iso,
            parse_utc,
        )

        parsed = parse_utc(
            str(time_utc)
        )

        return datetime_to_iso(
            parsed
        )

    # =========================================================================
    # MODEL TIME VALIDATION
    # =========================================================================

    def validate_model_time(
        self,
        time_utc: str,
    ) -> dict[str, Any]:
        """
        Validate whether time_utc is an actual INCOIS HYCOM source time.

        If no NavigationTimeAdapter has been configured, this method
        returns an explicit 'not_checked' result rather than pretending
        validation occurred.

        No interpolation and no time substitution are performed.
        """

        normalized_time = (
            self._normalize_time_text(
                time_utc
            )
        )

        if self.time_adapter is None:

            return {
                "status": "not_checked",

                "requested_time_utc": (
                    normalized_time
                ),

                "actual_model_time_utc": None,

                "exact_model_time": None,

                "synthetic_data": False,

                "interpolation": False,

                "reason": (
                    "No NavigationTimeAdapter is attached "
                    "to this environment instance."
                ),
            }

        exact = self.time_adapter.exact(
            normalized_time
        )

        if exact is None:

            return {
                "status": "invalid_model_time",

                "requested_time_utc": (
                    normalized_time
                ),

                "actual_model_time_utc": None,

                "exact_model_time": False,

                "synthetic_data": False,

                "interpolation": False,

                "reason": (
                    "The supplied environmental time does not "
                    "exactly match an INCOIS HYCOM source TIME value."
                ),
            }

        return {
            "status": "valid_model_time",

            "requested_time_utc": (
                normalized_time
            ),

            "actual_model_time_utc": (
                exact.model_time_utc
            ),

            "source_dataset": (
                exact.source_dataset
            ),

            "source_dataset_url": (
                exact.source_dataset_url
            ),

            "source_time_index": (
                exact.source_time_index
            ),

            "exact_model_time": True,

            "synthetic_data": False,

            "interpolation": False,
        }

    # =========================================================================
    # HYCOM + GEBCO
    # =========================================================================

    def sample(
        self,
        *,
        latitude: float,
        longitude: float,
        depth_m: float,
        time_utc: str,
    ) -> NavigationEnvironmentState:
        """
        Retrieve the scientific environment at one navigation state.

        The time supplied here is treated as the ENVIRONMENTAL MODEL TIME.

        When a NavigationTimeAdapter is configured, this time must exactly
        match a real INCOIS HYCOM source TIME.

        The adapter deliberately does NOT do:

            07:00 -> 12:00

        and does NOT do nearest-time selection or interpolation.

        The navigation engine is responsible for explicitly choosing
        the correct model timestamp for each temporal search state.
        """

        normalized_time = (
            self._normalize_time_text(
                time_utc
            )
        )

        # ---------------------------------------------------------------------
        # Explicit source-time validation when the adapter is available.
        # ---------------------------------------------------------------------

        time_validation = (
            self.validate_model_time(
                normalized_time
            )
        )

        if (
            self.time_adapter is not None
            and time_validation[
                "status"
            ]
            != "valid_model_time"
        ):

            raise ValueError(
                "NavigationEnvironment.sample() requires an exact "
                "INCOIS HYCOM source TIME when a NavigationTimeAdapter "
                "is configured. "
                f"Requested time: {normalized_time}. "
                "No interpolation or automatic time substitution is "
                "performed."
            )

        # ---------------------------------------------------------------------
        # Scientific query.
        # ---------------------------------------------------------------------

        result = self.engine.query(
            latitude=float(
                latitude
            ),
            longitude=float(
                longitude
            ),
            depth_m=float(
                depth_m
            ),
            time_utc=normalized_time,
        )

        water_column = result.get(
            "water_column",
            {},
        )

        hycom_data = (
            water_column.get(
                "data"
            )
            or {}
        )

        hycom_missing = (
            water_column.get(
                "missing",
                {}
            )
            or {}
        )

        hycom_available = bool(
            water_column.get(
                "available",
                False,
            )
        )

        bathymetry = (
            result.get(
                "bathymetry",
                {}
            )
            or {}
        )

        bathymetry_available = bool(
            bathymetry.get(
                "available",
                False,
            )
        )

        bathymetry_data = bathymetry

        elevation_m = self._safe_float(
            bathymetry_data.get(
                "elevation_m"
            )
        )

        depth_below_sea_level = (
            self._safe_float(
                bathymetry_data.get(
                    "depth_below_sea_level_m"
                )
            )
        )

        # ---------------------------------------------------------------------
        # Scientific integrity comes from the existing unified engine.
        # ---------------------------------------------------------------------

        scientific_provenance = (
            result.get(
                "provenance",
                {}
            )
            or {}
        )

        # ---------------------------------------------------------------------
        # Actual source time.
        # ---------------------------------------------------------------------

        actual_time = (
            hycom_data.get(
                "actual_time_utc"
            )
        )

        actual_time_text = (
            str(
                actual_time
            )
            if actual_time is not None
            else None
        )

        # ---------------------------------------------------------------------
        # Build provenance.
        # ---------------------------------------------------------------------

        provenance = {
            **scientific_provenance,

            "requested": {
                "latitude": float(
                    latitude
                ),
                "longitude": float(
                    longitude
                ),
                "depth_m": float(
                    depth_m
                ),
                "time_utc": normalized_time,
            },

            "actual_source": {
                "latitude": self._safe_float(
                    hycom_data.get(
                        "actual_latitude"
                    )
                ),
                "longitude": self._safe_float(
                    hycom_data.get(
                        "actual_longitude"
                    )
                ),
                "depth_m": self._safe_float(
                    hycom_data.get(
                        "actual_depth_m"
                    )
                ),
                "time_utc": actual_time_text,
            },

            "environment_adapter": (
                "NavigationEnvironment"
            ),

            "temporal_policy": {
                "exact_source_time_required": (
                    self.time_adapter is not None
                ),
                "interpolation": False,
                "automatic_time_substitution": False,
                "model_time_source": (
                    "INCOIS HYCOM TIME"
                ),
            },

            "navigation_time_validation": (
                time_validation
            ),
        }

        return NavigationEnvironmentState(

            requested_latitude=float(
                latitude
            ),

            requested_longitude=float(
                longitude
            ),

            requested_depth_m=float(
                depth_m
            ),

            requested_time_utc=normalized_time,

            actual_latitude=self._safe_float(
                hycom_data.get(
                    "actual_latitude"
                )
            ),

            actual_longitude=self._safe_float(
                hycom_data.get(
                    "actual_longitude"
                )
            ),

            actual_depth_m=self._safe_float(
                hycom_data.get(
                    "actual_depth_m"
                )
            ),

            actual_time_utc=actual_time_text,

            temperature_c=self._safe_float(
                hycom_data.get(
                    "temperature_c"
                )
            ),

            salinity_psu=self._safe_float(
                hycom_data.get(
                    "salinity_psu"
                )
            ),

            u_current_m_s=self._safe_float(
                hycom_data.get(
                    "u_current_m_s"
                )
            ),

            v_current_m_s=self._safe_float(
                hycom_data.get(
                    "v_current_m_s"
                )
            ),

            current_speed_m_s=self._safe_float(
                hycom_data.get(
                    "current_speed_m_s"
                )
            ),

            current_direction_math_deg=(
                self._safe_float(
                    hycom_data.get(
                        "current_direction_math_deg"
                    )
                )
            ),

            ssh_m=self._safe_float(
                hycom_data.get(
                    "ssh_m"
                )
            ),

            bathymetry_elevation_m=(
                elevation_m
            ),

            bathymetry_depth_m=(
                depth_below_sea_level
            ),

            hycom_available=(
                hycom_available
            ),

            bathymetry_available=(
                bathymetry_available
            ),

            hycom_source=(
                str(
                    water_column.get(
                        "source"
                    )
                )
                if water_column.get(
                    "source"
                ) is not None
                else None
            ),

            hycom_dataset=(
                str(
                    water_column.get(
                        "dataset"
                    )
                )
                if water_column.get(
                    "dataset"
                ) is not None
                else None
            ),

            hycom_source_url=(
                str(
                    water_column.get(
                        "source_url"
                    )
                )
                if water_column.get(
                    "source_url"
                ) is not None
                else None
            ),

            bathymetry_source=(
                str(
                    bathymetry.get(
                        "source"
                    )
                )
                if bathymetry.get(
                    "source"
                ) is not None
                else None
            ),

            bathymetry_dataset=(
                str(
                    bathymetry.get(
                        "dataset"
                    )
                )
                if bathymetry.get(
                    "dataset"
                ) is not None
                else None
            ),

            bathymetry_source_url=(
                str(
                    bathymetry.get(
                        "source_url"
                    )
                )
                if bathymetry.get(
                    "source_url"
                ) is not None
                else None
            ),

            hycom_missing={
                str(
                    key
                ): bool(
                    value
                )
                for key, value in (
                    hycom_missing.items()
                )
            },

            synthetic_data=bool(
                result.get(
                    "synthetic_data",
                    False,
                )
            ),

            interpolation=bool(
                result.get(
                    "interpolation",
                    False,
                )
            ),

            provenance=provenance,
        )

    # =========================================================================
    # EXPLICIT NAVIGATION-TIME SAMPLING SUPPORT
    # =========================================================================

    def model_time_for_vessel_time(
        self,
        vessel_time_utc: str,
    ) -> dict[str, Any]:
        """
        Explicitly resolve a vessel timestamp to the next REAL HYCOM
        source timestamp.

        This function does NOT sample the ocean.

        It exists so the navigation engine can make the distinction:

            vessel_time_utc
                vs
            model_time_utc

        completely explicit.

        Example:

            vessel time = 07:00Z
            next model time = 12:00Z

        The returned data preserves both values.

        No interpolation is performed.
        """

        if self.time_adapter is None:

            raise RuntimeError(
                "A NavigationTimeAdapter is required for explicit "
                "vessel-time to model-time resolution."
            )

        resolved = self.time_adapter.next_valid(
            vessel_time_utc
        )

        if resolved is None:

            return {
                "available": False,

                "vessel_time_utc": (
                    self._normalize_time_text(
                        vessel_time_utc
                    )
                ),

                "model_time_utc": None,

                "exact_model_time": False,

                "interpolation": False,

                "synthetic_data": False,

                "reason": (
                    "No real INCOIS HYCOM source time exists "
                    "at or after the supplied vessel time."
                ),
            }

        return {
            "available": True,

            "vessel_time_utc": (
                resolved.vessel_time_utc
            ),

            "model_time_utc": (
                resolved.model_time_utc
            ),

            "source_dataset": (
                resolved.source_dataset
            ),

            "source_dataset_url": (
                resolved.source_dataset_url
            ),

            "source_time_index": (
                resolved.source_time_index
            ),

            "exact_model_time": (
                resolved.exact_model_time
            ),

            "model_time_offset_seconds": (
                resolved.model_time_offset_seconds
            ),

            "interpolation": False,

            "synthetic_data": False,
        }

    # =========================================================================
    # NEXT MODEL TIME
    # =========================================================================

    def next_model_time(
        self,
        model_time_utc: str,
    ) -> dict[str, Any] | None:
        """
        Return the next REAL HYCOM source time.

        This is useful to the navigation engine when moving from one
        environmental model state to the next.
        """

        if self.time_adapter is None:

            raise RuntimeError(
                "A NavigationTimeAdapter is required to determine "
                "the next HYCOM model time."
            )

        resolved = self.time_adapter.next_model_time(
            model_time_utc
        )

        if resolved is None:

            return None

        return {
            "current_model_time_utc": (
                self._normalize_time_text(
                    model_time_utc
                )
            ),

            "next_model_time_utc": (
                resolved.model_time_utc
            ),

            "source_dataset": (
                resolved.source_dataset
            ),

            "source_dataset_url": (
                resolved.source_dataset_url
            ),

            "source_time_index": (
                resolved.source_time_index
            ),

            "interval_seconds": (
                resolved.model_time_offset_seconds
            ),

            "interpolation": False,

            "synthetic_data": False,
        }

    # =========================================================================
    # CURRENT VALIDITY
    # =========================================================================

    @staticmethod
    def has_navigable_current(
        state: NavigationEnvironmentState,
    ) -> bool:
        """
        Return True only when both U and V are real finite values.
        """

        return (
            state.u_current_m_s is not None
            and state.v_current_m_s is not None
        )

    # =========================================================================
    # BATHYMETRY VALIDITY
    # =========================================================================

    @staticmethod
    def has_bathymetry(
        state: NavigationEnvironmentState,
    ) -> bool:
        """
        Return True only when real bathymetry is available.
        """

        return (
            state.bathymetry_available
            and state.bathymetry_elevation_m
            is not None
        )

    # =========================================================================
    # SCIENTIFIC INTEGRITY CHECK
    # =========================================================================

    @staticmethod
    def validate_scientific_integrity(
        state: NavigationEnvironmentState,
    ) -> None:
        """
        Fail fast if an environment result violates OceanSight-V
        scientific integrity rules.
        """

        if state.synthetic_data:

            raise RuntimeError(
                "Navigation environment returned synthetic data. "
                "Navigation requires real scientific observations/models."
            )

        if state.interpolation:

            raise RuntimeError(
                "Navigation environment returned interpolated data. "
                "This navigation stage requires exact source selections."
            )

        # ---------------------------------------------------------------------
        # When a time adapter is attached, the state must correspond to a
        # real source timestamp.
        # ---------------------------------------------------------------------

        if (
            state.actual_time_utc is None
        ):

            raise RuntimeError(
                "Navigation environment returned no actual HYCOM "
                "source timestamp."
            )

    # =========================================================================
    # SERIALIZATION
    # =========================================================================

    @staticmethod
    def to_dict(
        state: NavigationEnvironmentState,
    ) -> dict[str, Any]:
        """
        Convert the environment state into an API-friendly dictionary.
        """

        return {

            "requested": {
                "latitude": (
                    state.requested_latitude
                ),
                "longitude": (
                    state.requested_longitude
                ),
                "depth_m": (
                    state.requested_depth_m
                ),
                "time_utc": (
                    state.requested_time_utc
                ),
            },

            "actual_source": {
                "latitude": (
                    state.actual_latitude
                ),
                "longitude": (
                    state.actual_longitude
                ),
                "depth_m": (
                    state.actual_depth_m
                ),
                "time_utc": (
                    state.actual_time_utc
                ),
            },

            "current": {
                "u_m_s": (
                    state.u_current_m_s
                ),
                "v_m_s": (
                    state.v_current_m_s
                ),
                "speed_m_s": (
                    state.current_speed_m_s
                ),
                "direction_math_deg": (
                    state.current_direction_math_deg
                ),
            },

            "water": {
                "temperature_c": (
                    state.temperature_c
                ),
                "salinity_psu": (
                    state.salinity_psu
                ),
                "ssh_m": (
                    state.ssh_m
                ),
            },

            "bathymetry": {
                "elevation_m": (
                    state.bathymetry_elevation_m
                ),
                "depth_below_sea_level_m": (
                    state.bathymetry_depth_m
                ),
            },

            "availability": {
                "hycom": (
                    state.hycom_available
                ),
                "bathymetry": (
                    state.bathymetry_available
                ),
            },

            "missing": (
                state.hycom_missing
            ),

            "provenance": {
                "hycom": {
                    "source": (
                        state.hycom_source
                    ),
                    "dataset": (
                        state.hycom_dataset
                    ),
                    "source_url": (
                        state.hycom_source_url
                    ),
                },

                "bathymetry": {
                    "source": (
                        state.bathymetry_source
                    ),
                    "dataset": (
                        state.bathymetry_dataset
                    ),
                    "source_url": (
                        state.bathymetry_source_url
                    ),
                },

                "synthetic_data": (
                    state.synthetic_data
                ),

                "interpolation": (
                    state.interpolation
                ),

                "environment_adapter": (
                    "NavigationEnvironment"
                ),
            },
        }