from __future__ import annotations

import json
import math
import sqlite3
from pathlib import Path
from typing import Any


# =============================================================================
# OCEANSIGHT-V
# INCOIS ARGO QUERY ENGINE
#
# Real data source:
#
#     INCOIS ERDDAP
#     Indian_ARGO_Floats
#
# Scientific rules:
#
#     PRES is pressure in dbar.
#     PRES is NEVER silently converted to depth.
#     No interpolation.
#     No synthetic observations.
#
# Supported operations:
#
#     get_profile()
#     get_profile_series()
#     find_nearest_profile()
#     discover_profiles()
#     query_nearest_observation()
# =============================================================================


PROJECT_ROOT = (
    Path(__file__).resolve().parent.parent
)

ARGO_DB = (
    PROJECT_ROOT
    / "processed"
    / "argo_store.sqlite"
)

DEFAULT_RADIUS_DEGREES = 2.0

DEFAULT_LIMIT = 100

ARGO_SOURCE = "INCOIS ERDDAP"

ARGO_DATASET = "Indian_ARGO_Floats"

ARGO_SOURCE_URL = (
    "https://erddap.incois.gov.in/"
    "erddap/tabledap/"
    "Indian_ARGO_Floats.csv"
)


class ArgoQueryEngine:
    """
    Query the locally stored real INCOIS Argo observations.
    """

    def __init__(
        self,
        db_path: Path = ARGO_DB,
    ) -> None:

        self.db_path = Path(
            db_path
        )

        if not self.db_path.exists():

            raise FileNotFoundError(
                "INCOIS Argo database does not exist:\n"
                f"{self.db_path}\n\n"
                "Run:\n"
                "python -m app.argo_store"
            )

    # =========================================================================
    # CONNECTION
    # =========================================================================

    def _connect(
        self,
    ) -> sqlite3.Connection:

        connection = sqlite3.connect(
            self.db_path
        )

        connection.row_factory = (
            sqlite3.Row
        )

        return connection

    # =========================================================================
    # SAFE NUMBER
    # =========================================================================

    @staticmethod
    def _safe_float(
        value: Any,
    ) -> float | None:

        if value is None:
            return None

        try:

            result = float(
                value
            )

            if not math.isfinite(
                result
            ):

                return None

            return result

        except (
            TypeError,
            ValueError,
        ):

            return None

    # =========================================================================
    # SAFE TEXT
    # =========================================================================

    @staticmethod
    def _safe_text(
        value: Any,
    ) -> str | None:

        if value is None:

            return None

        text = str(
            value
        ).strip()

        if not text:

            return None

        return text

    # =========================================================================
    # PROFILE QUERY
    # =========================================================================

    def get_profile(
        self,
        platform_number: str,
        cycle_number: int,
    ) -> dict[str, Any]:

        platform_number = str(
            platform_number
        ).strip()

        cycle_number = int(
            cycle_number
        )

        with self._connect() as connection:

            rows = connection.execute(
                """
                SELECT
                    platform_number,
                    cycle_number,
                    direction,

                    profile_time_utc,
                    juld_location_utc,

                    latitude,
                    longitude,

                    pres_dbar,
                    pres_qc,

                    pres_adjusted_dbar,
                    pres_adjusted_qc,

                    temp_c,
                    temp_qc,

                    temp_adjusted_c,
                    temp_adjusted_qc,

                    psal_psu,
                    psal_qc,

                    psal_adjusted_psu,
                    psal_adjusted_qc,

                    source,
                    source_dataset,
                    source_url,
                    ingested_at_utc

                FROM argo_observations

                WHERE platform_number = ?
                  AND cycle_number = ?

                ORDER BY pres_dbar ASC
                """,
                (
                    platform_number,
                    cycle_number,
                ),
            ).fetchall()

        if not rows:

            return {
                "available": False,

                "reason": (
                    "No Argo profile was found "
                    "for the requested platform/cycle."
                ),

                "platform_number": (
                    platform_number
                ),

                "cycle_number": (
                    cycle_number
                ),

                "source": ARGO_SOURCE,

                "dataset": ARGO_DATASET,

                "synthetic_data": False,

                "interpolation": False,
            }

        observations: list[
            dict[str, Any]
        ] = []

        for row in rows:

            observations.append(
                dict(row)
            )

        first = observations[0]

        valid_pressures = [
            self._safe_float(
                row.get(
                    "pres_dbar"
                )
            )
            for row in observations
        ]

        valid_pressures = [
            value
            for value in valid_pressures
            if value is not None
        ]

        minimum_pressure = (
            min(valid_pressures)
            if valid_pressures
            else None
        )

        maximum_pressure = (
            max(valid_pressures)
            if valid_pressures
            else None
        )

        return {
            "available": True,

            "platform_number": platform_number,

            "cycle_number": cycle_number,

            "direction": first.get(
                "direction"
            ),

            "profile_time_utc": first.get(
                "profile_time_utc"
            ),

            "juld_location_utc": first.get(
                "juld_location_utc"
            ),

            "latitude": self._safe_float(
                first.get(
                    "latitude"
                )
            ),

            "longitude": self._safe_float(
                first.get(
                    "longitude"
                )
            ),

            "measurement_count": len(
                observations
            ),

            "observations": observations,

            "pressure": {
                "unit": "dbar",

                "preserved_as_source_pressure": True,

                "converted_to_depth": False,

                "minimum_dbar": (
                    minimum_pressure
                ),

                "maximum_dbar": (
                    maximum_pressure
                ),
            },

            "provenance": {
                "source": (
                    first.get(
                        "source"
                    )
                    or ARGO_SOURCE
                ),

                "dataset": (
                    first.get(
                        "source_dataset"
                    )
                    or ARGO_DATASET
                ),

                "source_url": (
                    first.get(
                        "source_url"
                    )
                    or ARGO_SOURCE_URL
                ),

                "synthetic_data": False,

                "interpolation": False,
            },

            "scientific_rules": {
                "pressure_unit": "dbar",

                "pressure_is_depth": False,

                "pressure_converted_to_depth": False,

                "synthetic_data": False,

                "interpolation": False,
            },
        }

    # =========================================================================
    # FRONTEND PROFILE SERIES
    # =========================================================================

    def get_profile_series(
        self,
        platform_number: str,
        cycle_number: int,
    ) -> dict[str, Any]:
        """
        Return one complete real Argo profile in a frontend-friendly format.

        PRES remains pressure in dbar.

        No pressure-to-depth conversion.
        No interpolation.
        No synthetic data.
        """

        profile = self.get_profile(
            platform_number=platform_number,
            cycle_number=cycle_number,
        )

        if not profile.get(
            "available"
        ):

            return {
                "available": False,

                "platform_number": (
                    str(
                        platform_number
                    ).strip()
                ),

                "cycle_number": int(
                    cycle_number
                ),

                "direction": None,

                "profile_time_utc": None,

                "juld_location_utc": None,

                "latitude": None,

                "longitude": None,

                "points": [],

                "point_count": 0,

                "pressure_unit": "dbar",

                "pressure_is_depth": False,

                "synthetic_data": False,

                "interpolation": False,

                "provenance": {
                    "source": ARGO_SOURCE,
                    "dataset": ARGO_DATASET,
                    "source_url": ARGO_SOURCE_URL,
                    "synthetic_data": False,
                    "interpolation": False,
                },
            }

        points: list[
            dict[str, Any]
        ] = []

        for row in profile.get(
            "observations",
            [],
        ):

            points.append(
                {
                    "pressure_dbar": (
                        self._safe_float(
                            row.get(
                                "pres_dbar"
                            )
                        )
                    ),

                    "pressure_qc": (
                        self._safe_text(
                            row.get(
                                "pres_qc"
                            )
                        )
                    ),

                    "pressure_adjusted_dbar": (
                        self._safe_float(
                            row.get(
                                "pres_adjusted_dbar"
                            )
                        )
                    ),

                    "pressure_adjusted_qc": (
                        self._safe_text(
                            row.get(
                                "pres_adjusted_qc"
                            )
                        )
                    ),

                    "temperature_c": (
                        self._safe_float(
                            row.get(
                                "temp_c"
                            )
                        )
                    ),

                    "temperature_qc": (
                        self._safe_text(
                            row.get(
                                "temp_qc"
                            )
                        )
                    ),

                    "temperature_adjusted_c": (
                        self._safe_float(
                            row.get(
                                "temp_adjusted_c"
                            )
                        )
                    ),

                    "temperature_adjusted_qc": (
                        self._safe_text(
                            row.get(
                                "temp_adjusted_qc"
                            )
                        )
                    ),

                    "salinity_psu": (
                        self._safe_float(
                            row.get(
                                "psal_psu"
                            )
                        )
                    ),

                    "salinity_qc": (
                        self._safe_text(
                            row.get(
                                "psal_qc"
                            )
                        )
                    ),

                    "salinity_adjusted_psu": (
                        self._safe_float(
                            row.get(
                                "psal_adjusted_psu"
                            )
                        )
                    ),

                    "salinity_adjusted_qc": (
                        self._safe_text(
                            row.get(
                                "psal_adjusted_qc"
                            )
                        )
                    ),
                }
            )

        return {
            "available": True,

            "platform_number": (
                profile.get(
                    "platform_number"
                )
            ),

            "cycle_number": (
                profile.get(
                    "cycle_number"
                )
            ),

            "direction": (
                profile.get(
                    "direction"
                )
            ),

            "profile_time_utc": (
                profile.get(
                    "profile_time_utc"
                )
            ),

            "juld_location_utc": (
                profile.get(
                    "juld_location_utc"
                )
            ),

            "latitude": (
                profile.get(
                    "latitude"
                )
            ),

            "longitude": (
                profile.get(
                    "longitude"
                )
            ),

            "points": points,

            "point_count": len(
                points
            ),

            "pressure_unit": "dbar",

            "pressure_is_depth": False,

            "synthetic_data": False,

            "interpolation": False,

            "scientific_rules": {
                "pressure_unit": "dbar",

                "pressure_is_depth": False,

                "pressure_converted_to_depth": False,

                "synthetic_data": False,

                "interpolation": False,
            },

            "provenance": (
                profile.get(
                    "provenance",
                    {},
                )
            ),
        }

    # =========================================================================
    # NEAREST PROFILE
    # =========================================================================

    def find_nearest_profile(
        self,
        latitude: float,
        longitude: float,
        radius_degrees: float = DEFAULT_RADIUS_DEGREES,
    ) -> dict[str, Any]:

        latitude = float(
            latitude
        )

        longitude = float(
            longitude
        )

        radius_degrees = float(
            radius_degrees
        )

        if not (
            math.isfinite(
                latitude
            )
            and math.isfinite(
                longitude
            )
            and math.isfinite(
                radius_degrees
            )
        ):

            raise ValueError(
                "Latitude, longitude and "
                "radius must be finite."
            )

        if not (
            -90.0 <= latitude <= 90.0
        ):

            raise ValueError(
                "Latitude must be between "
                "-90 and 90."
            )

        if radius_degrees <= 0.0:

            raise ValueError(
                "Radius must be greater than zero."
            )

        while longitude > 180.0:

            longitude -= 360.0

        while longitude < -180.0:

            longitude += 360.0

        with self._connect() as connection:

            row = connection.execute(
                """
                SELECT
                    platform_number,
                    cycle_number,
                    profile_time_utc,
                    latitude,
                    longitude,

                    COUNT(*) AS measurement_count,

                    MIN(pres_dbar)
                        AS minimum_pressure_dbar,

                    MAX(pres_dbar)
                        AS maximum_pressure_dbar

                FROM argo_observations

                WHERE latitude BETWEEN ? AND ?

                  AND longitude BETWEEN ? AND ?

                GROUP BY
                    platform_number,
                    cycle_number,
                    profile_time_utc,
                    latitude,
                    longitude

                ORDER BY
                    (
                        (latitude - ?) *
                        (latitude - ?)
                    )
                    +
                    (
                        (longitude - ?) *
                        (longitude - ?)
                    )

                LIMIT 1
                """,
                (
                    latitude - radius_degrees,
                    latitude + radius_degrees,

                    longitude - radius_degrees,
                    longitude + radius_degrees,

                    latitude,
                    latitude,

                    longitude,
                    longitude,
                ),
            ).fetchone()

        if row is None:

            return {
                "available": False,

                "reason": (
                    "No locally stored INCOIS Argo "
                    "profile is inside the requested "
                    "search radius."
                ),

                "requested": {
                    "latitude": latitude,
                    "longitude": longitude,
                    "radius_degrees": radius_degrees,
                },

                "source": ARGO_SOURCE,

                "dataset": ARGO_DATASET,

                "synthetic_data": False,

                "interpolation": False,
            }

        result = dict(
            row
        )

        result["latitude"] = (
            self._safe_float(
                result.get(
                    "latitude"
                )
            )
        )

        result["longitude"] = (
            self._safe_float(
                result.get(
                    "longitude"
                )
            )
        )

        result[
            "minimum_pressure_dbar"
        ] = self._safe_float(
            result.get(
                "minimum_pressure_dbar"
            )
        )

        result[
            "maximum_pressure_dbar"
        ] = self._safe_float(
            result.get(
                "maximum_pressure_dbar"
            )
        )

        actual_latitude = result.get(
            "latitude"
        )

        actual_longitude = result.get(
            "longitude"
        )

        if (
            actual_latitude is not None
            and actual_longitude is not None
        ):

            result[
                "spatial_distance_degrees"
            ] = math.sqrt(
                (
                    latitude
                    - actual_latitude
                ) ** 2
                +
                (
                    longitude
                    - actual_longitude
                ) ** 2
            )

        else:

            result[
                "spatial_distance_degrees"
            ] = None

        return {
            "available": True,

            "requested": {
                "latitude": latitude,
                "longitude": longitude,
                "radius_degrees": radius_degrees,
            },

            "nearest_profile": result,

            "provenance": {
                "source": ARGO_SOURCE,

                "dataset": ARGO_DATASET,

                "source_url": ARGO_SOURCE_URL,

                "synthetic_data": False,

                "interpolation": False,
            },

            "scientific_rules": {
                "synthetic_data": False,

                "interpolation": False,

                "pressure_unit": "dbar",

                "pressure_is_depth": False,
            },
        }

    # =========================================================================
    # DISCOVER MULTIPLE PROFILES
    # =========================================================================

    def discover_profiles(
        self,
        latitude: float,
        longitude: float,
        radius_degrees: float = 5.0,
        time_utc: str | None = None,
        platform_number: str | None = None,
        cycle_number: int | None = None,
        limit: int = DEFAULT_LIMIT,
    ) -> dict[str, Any]:
        """
        Discover real Argo profiles around a geographic location.

        This method is intended for frontend map marker discovery.

        time_utc, when supplied, is an EXACT profile timestamp filter.

        There is no nearest-time substitution.
        """

        latitude = float(
            latitude
        )

        longitude = float(
            longitude
        )

        radius_degrees = float(
            radius_degrees
        )

        limit = int(
            limit
        )

        if not (
            math.isfinite(
                latitude
            )
            and math.isfinite(
                longitude
            )
            and math.isfinite(
                radius_degrees
            )
        ):

            raise ValueError(
                "Latitude, longitude and "
                "radius must be finite."
            )

        if not (
            -90.0 <= latitude <= 90.0
        ):

            raise ValueError(
                "Latitude must be between "
                "-90 and 90."
            )

        if radius_degrees <= 0.0:

            raise ValueError(
                "Radius must be greater than zero."
            )

        if limit < 1:

            raise ValueError(
                "Limit must be at least 1."
            )

        if limit > 1000:

            raise ValueError(
                "Limit cannot exceed 1000."
            )

        while longitude > 180.0:

            longitude -= 360.0

        while longitude < -180.0:

            longitude += 360.0

        normalized_time = (
            None
            if time_utc is None
            else str(
                time_utc
            ).strip()
        )

        normalized_platform = (
            None
            if platform_number is None
            else str(
                platform_number
            ).strip()
        )

        normalized_cycle = (
            None
            if cycle_number is None
            else int(
                cycle_number
            )
        )

        where_clauses = [
            "latitude BETWEEN ? AND ?",
            "longitude BETWEEN ? AND ?",
        ]

        parameters: list[Any] = [
            latitude - radius_degrees,
            latitude + radius_degrees,

            longitude - radius_degrees,
            longitude + radius_degrees,
        ]

        if normalized_time:

            where_clauses.append(
                "profile_time_utc = ?"
            )

            parameters.append(
                normalized_time
            )

        if normalized_platform:

            where_clauses.append(
                "platform_number = ?"
            )

            parameters.append(
                normalized_platform
            )

        if normalized_cycle is not None:

            where_clauses.append(
                "cycle_number = ?"
            )

            parameters.append(
                normalized_cycle
            )

        where_sql = (
            "\n                  AND ".join(
                where_clauses
            )
        )

        query = f"""
            SELECT
                platform_number,
                cycle_number,
                direction,
                profile_time_utc,
                latitude,
                longitude,

                COUNT(*) AS measurement_count,

                MIN(pres_dbar)
                    AS minimum_pressure_dbar,

                MAX(pres_dbar)
                    AS maximum_pressure_dbar

            FROM argo_observations

            WHERE {where_sql}

            GROUP BY
                platform_number,
                cycle_number,
                direction,
                profile_time_utc,
                latitude,
                longitude

            ORDER BY
                (
                    (latitude - ?) *
                    (latitude - ?)
                )
                +
                (
                    (longitude - ?) *
                    (longitude - ?)
                )

            LIMIT ?
        """

        parameters.extend(
            [
                latitude,
                latitude,

                longitude,
                longitude,

                limit,
            ]
        )

        with self._connect() as connection:

            rows = connection.execute(
                query,
                tuple(
                    parameters
                ),
            ).fetchall()

        profiles: list[
            dict[str, Any]
        ] = []

        for row in rows:

            profile = dict(
                row
            )

            profile[
                "latitude"
            ] = self._safe_float(
                profile.get(
                    "latitude"
                )
            )

            profile[
                "longitude"
            ] = self._safe_float(
                profile.get(
                    "longitude"
                )
            )

            profile[
                "minimum_pressure_dbar"
            ] = self._safe_float(
                profile.get(
                    "minimum_pressure_dbar"
                )
            )

            profile[
                "maximum_pressure_dbar"
            ] = self._safe_float(
                profile.get(
                    "maximum_pressure_dbar"
                )
            )

            actual_latitude = profile.get(
                "latitude"
            )

            actual_longitude = profile.get(
                "longitude"
            )

            if (
                actual_latitude is not None
                and actual_longitude is not None
            ):

                profile[
                    "spatial_distance_degrees"
                ] = math.sqrt(
                    (
                        latitude
                        - actual_latitude
                    ) ** 2
                    +
                    (
                        longitude
                        - actual_longitude
                    ) ** 2
                )

            else:

                profile[
                    "spatial_distance_degrees"
                ] = None

            profiles.append(
                profile
            )

        return {
            "available": bool(
                profiles
            ),

            "requested": {
                "latitude": latitude,
                "longitude": longitude,
                "radius_degrees": radius_degrees,
                "time_utc": normalized_time,
                "platform_number": normalized_platform,
                "cycle_number": normalized_cycle,
                "limit": limit,
            },

            "profile_count": len(
                profiles
            ),

            "profiles": profiles,

            "source": ARGO_SOURCE,

            "dataset": ARGO_DATASET,

            "source_url": ARGO_SOURCE_URL,

            "synthetic_data": False,

            "interpolation": False,

            "scientific_rules": {
                "pressure_unit": "dbar",

                "pressure_is_depth": False,

                "pressure_converted_to_depth": False,

                "synthetic_data": False,

                "interpolation": False,

                "exact_time_filter": (
                    normalized_time is not None
                ),
            },
        }

    # =========================================================================
    # POINT + PRESSURE QUERY
    # =========================================================================

    def query_nearest_observation(
        self,
        latitude: float,
        longitude: float,
        pressure_dbar: float,
        radius_degrees: float = DEFAULT_RADIUS_DEGREES,
    ) -> dict[str, Any]:

        latitude = float(
            latitude
        )

        longitude = float(
            longitude
        )

        pressure_dbar = float(
            pressure_dbar
        )

        radius_degrees = float(
            radius_degrees
        )

        if not math.isfinite(
            pressure_dbar
        ):

            raise ValueError(
                "Pressure must be finite."
            )

        nearest = (
            self.find_nearest_profile(
                latitude=latitude,
                longitude=longitude,
                radius_degrees=radius_degrees,
            )
        )

        if not nearest.get(
            "available"
        ):

            return nearest

        profile = nearest[
            "nearest_profile"
        ]

        platform_number = (
            profile[
                "platform_number"
            ]
        )

        cycle_number = int(
            profile[
                "cycle_number"
            ]
        )

        observations = self.get_profile(
            platform_number=platform_number,
            cycle_number=cycle_number,
        )

        if not observations.get(
            "available"
        ):

            return observations

        rows = observations[
            "observations"
        ]

        valid_rows = [
            row
            for row in rows
            if row.get(
                "pres_dbar"
            ) is not None
        ]

        if not valid_rows:

            return {
                "available": False,

                "reason": (
                    "Nearest Argo profile contains "
                    "no valid PRES values."
                ),

                "source": ARGO_SOURCE,

                "dataset": ARGO_DATASET,

                "synthetic_data": False,

                "interpolation": False,
            }

        selected = min(
            valid_rows,
            key=lambda row: abs(
                float(
                    row["pres_dbar"]
                )
                - pressure_dbar
            ),
        )

        selected_pressure = self._safe_float(
            selected.get(
                "pres_dbar"
            )
        )

        spatial_distance = (
            self._safe_float(
                profile.get(
                    "spatial_distance_degrees"
                )
            )
        )

        pressure_difference = (
            None
            if selected_pressure is None
            else abs(
                selected_pressure
                - pressure_dbar
            )
        )

        return {
            "available": True,

            "requested": {
                "latitude": latitude,
                "longitude": longitude,
                "pressure_dbar": pressure_dbar,
                "radius_degrees": radius_degrees,
            },

            "source_observation": selected,

            "selection": (
                "nearest Argo profile + "
                "nearest observed PRES"
            ),

            "pressure": {
                "requested_dbar": pressure_dbar,

                "actual_dbar": selected_pressure,

                "unit": "dbar",

                "converted_to_depth": False,
            },

            "matching": {
                "spatial_distance_degrees": (
                    spatial_distance
                ),

                "pressure_difference_dbar": (
                    pressure_difference
                ),

                "actual_profile_time_utc": (
                    selected.get(
                        "profile_time_utc"
                    )
                ),
            },

            "provenance": {
                "source": (
                    selected.get(
                        "source"
                    )
                    or ARGO_SOURCE
                ),

                "dataset": (
                    selected.get(
                        "source_dataset"
                    )
                    or ARGO_DATASET
                ),

                "source_url": (
                    selected.get(
                        "source_url"
                    )
                    or ARGO_SOURCE_URL
                ),

                "synthetic_data": False,

                "interpolation": False,
            },

            "scientific_rules": {
                "pressure_unit": "dbar",

                "pressure_is_depth": False,

                "pressure_converted_to_depth": False,

                "synthetic_data": False,

                "interpolation": False,
            },
        }


# =============================================================================
# CLI TEST
# =============================================================================

def main() -> None:

    print("=" * 80)
    print(
        "OCEANSIGHT-V"
    )
    print(
        "INCOIS ARGO QUERY ENGINE"
    )
    print("=" * 80)

    engine = ArgoQueryEngine()

    platform = "7902250"
    cycle = 12

    # =========================================================================
    # PROFILE TEST
    # =========================================================================

    print()
    print(
        "PROFILE TEST"
    )
    print(
        "-" * 80
    )

    profile = engine.get_profile(
        platform_number=platform,
        cycle_number=cycle,
    )

    print(
        json.dumps(
            profile,
            indent=2,
        )
    )

    if not profile.get(
        "available"
    ):

        print()
        print(
            "Profile not found."
        )

        return

    observations = profile[
        "observations"
    ]

    first = observations[0]

    print()
    print(
        "FIRST OBSERVATION"
    )
    print(
        "-" * 80
    )

    print(
        "Platform:",
        first.get(
            "platform_number"
        ),
    )

    print(
        "Cycle:",
        first.get(
            "cycle_number"
        ),
    )

    print(
        "Profile time:",
        first.get(
            "profile_time_utc"
        ),
    )

    print(
        "Latitude:",
        first.get(
            "latitude"
        ),
    )

    print(
        "Longitude:",
        first.get(
            "longitude"
        ),
    )

    print(
        "PRES:",
        first.get(
            "pres_dbar"
        ),
        "dbar",
    )

    print(
        "TEMP:",
        first.get(
            "temp_c"
        ),
        "C",
    )

    print(
        "PSAL:",
        first.get(
            "psal_psu"
        ),
        "PSU",
    )

    print(
        "PRES_QC:",
        first.get(
            "pres_qc"
        ),
    )

    print(
        "TEMP_QC:",
        first.get(
            "temp_qc"
        ),
    )

    print(
        "PSAL_QC:",
        first.get(
            "psal_qc"
        ),
    )

    # =========================================================================
    # FRONTEND PROFILE SERIES TEST
    # =========================================================================

    print()
    print(
        "FRONTEND PROFILE SERIES TEST"
    )
    print(
        "-" * 80
    )

    profile_series = engine.get_profile_series(
        platform_number=platform,
        cycle_number=cycle,
    )

    print(
        "Available:",
        profile_series.get(
            "available"
        ),
    )

    print(
        "Platform:",
        profile_series.get(
            "platform_number"
        ),
    )

    print(
        "Cycle:",
        profile_series.get(
            "cycle_number"
        ),
    )

    print(
        "Profile time:",
        profile_series.get(
            "profile_time_utc"
        ),
    )

    print(
        "Profile points:",
        profile_series.get(
            "point_count"
        ),
    )

    print(
        "Pressure unit:",
        profile_series.get(
            "pressure_unit"
        ),
    )

    print(
        "Pressure is depth:",
        profile_series.get(
            "pressure_is_depth"
        ),
    )

    print(
        "Synthetic:",
        profile_series.get(
            "synthetic_data"
        ),
    )

    print(
        "Interpolation:",
        profile_series.get(
            "interpolation"
        ),
    )

    # =========================================================================
    # PROFILE DISCOVERY TEST
    # =========================================================================

    print()
    print(
        "PROFILE DISCOVERY TEST"
    )
    print(
        "-" * 80
    )

    discovery = engine.discover_profiles(
        latitude=-1.7322816666666667,
        longitude=85.17659333333333,
        radius_degrees=0.5,
        limit=10,
    )

    print(
        "Available:",
        discovery.get(
            "available"
        ),
    )

    print(
        "Profile count:",
        discovery.get(
            "profile_count"
        ),
    )

    if discovery.get(
        "profiles"
    ):

        print(
            "First discovered profile:"
        )

        print(
            json.dumps(
                discovery[
                    "profiles"
                ][0],
                indent=2,
            )
        )

    # =========================================================================
    # PRESSURE QUERY TEST
    # =========================================================================

    print()
    print(
        "PRESSURE QUERY TEST"
    )
    print(
        "-" * 80
    )

    result = (
        engine.query_nearest_observation(
            latitude=float(
                profile[
                    "latitude"
                ]
            ),
            longitude=float(
                profile[
                    "longitude"
                ]
            ),
            pressure_dbar=100.0,
            radius_degrees=0.5,
        )
    )

    print(
        json.dumps(
            result,
            indent=2,
        )
    )

    print()
    print(
        "=" * 80
    )

    print(
        "Pressure remains in dbar."
    )

    print(
        "No pressure-to-depth conversion was performed."
    )

    print(
        "Synthetic data:",
        result.get(
            "provenance",
            {},
        ).get(
            "synthetic_data",
            False,
        ),
    )

    print(
        "Interpolation:",
        result.get(
            "provenance",
            {},
        ).get(
            "interpolation",
            False,
        ),
    )

    print(
        "=" * 80
    )


if __name__ == "__main__":
    main()