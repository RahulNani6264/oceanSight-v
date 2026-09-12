from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.argo_query import ArgoQueryEngine
from app.gebco_query import GEBCOQuery
from app.ocean_query import OceanQueryEngine


# =============================================================================
# OCEANSIGHT-V
# UNIFIED SCIENTIFIC QUERY ENGINE
#
# Sources
# -------
# 1. INCOIS RSMC HYCOM
#    - temperature
#    - salinity
#    - U/V currents
#    - current speed
#    - current direction
#    - SSH
#
# 2. INCOIS Indian_ARGO_Floats
#    - actual profile observations
#    - PRES in dbar
#    - TEMP
#    - PSAL
#    - QC fields
#    - float/cycle/time/location metadata
#
# 3. GEBCO 2026
#    - numerical bathymetry
#    - seafloor elevation
#
# Scientific rules
# ----------------
# - No synthetic values.
# - No interpolation.
# - HYCOM depth remains depth in meters.
# - Argo PRES remains pressure in dbar.
# - Argo PRES is never silently converted to depth.
# - Missing values remain None.
# - Provenance is preserved separately for each source.
# =============================================================================


PROJECT_ROOT = (
    Path(__file__).resolve().parent.parent
)

GEBCO_INDEX_PATH = (
    PROJECT_ROOT
    / "processed"
    / "gebco_chunk_index.json"
)


class ScientificQueryEngine:
    """
    Single application-level entry point for OceanSight scientific data.
    """

    def __init__(self) -> None:

        self.hycom = (
            OceanQueryEngine()
        )

        self.argo = (
            ArgoQueryEngine()
        )

        self.gebco = (
            GEBCOQuery(
                GEBCO_INDEX_PATH
            )
        )

    # =========================================================================
    # VALIDATION
    # =========================================================================

    @staticmethod
    def _validate_latitude(
        latitude: float,
    ) -> float:

        latitude = float(
            latitude
        )

        if not math.isfinite(
            latitude
        ):

            raise ValueError(
                "Latitude must be finite."
            )

        if not (
            -90.0
            <= latitude
            <= 90.0
        ):

            raise ValueError(
                "Latitude must be between -90 and 90."
            )

        return latitude

    @staticmethod
    def _normalize_longitude(
        longitude: float,
    ) -> float:

        longitude = float(
            longitude
        )

        if not math.isfinite(
            longitude
        ):

            raise ValueError(
                "Longitude must be finite."
            )

        while longitude > 180.0:

            longitude -= 360.0

        while longitude < -180.0:

            longitude += 360.0

        return longitude

    @staticmethod
    def _validate_depth(
        depth_m: float,
    ) -> float:

        depth_m = float(
            depth_m
        )

        if not math.isfinite(
            depth_m
        ):

            raise ValueError(
                "Depth must be finite."
            )

        if depth_m < 0.0:

            raise ValueError(
                "Depth cannot be negative."
            )

        return depth_m

    @staticmethod
    def _validate_pressure(
        pressure_dbar: float,
    ) -> float:

        pressure_dbar = float(
            pressure_dbar
        )

        if not math.isfinite(
            pressure_dbar
        ):

            raise ValueError(
                "Pressure must be finite."
            )

        if pressure_dbar < 0.0:

            raise ValueError(
                "Pressure cannot be negative."
            )

        return pressure_dbar

    # =========================================================================
    # SIMPLE VALUE HELPERS
    # =========================================================================

    @staticmethod
    def _finite_or_none(
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
    # HYCOM
    # =========================================================================

    def _query_hycom(
        self,
        latitude: float,
        longitude: float,
        depth_m: float,
        time_utc: str | None,
    ) -> dict[str, Any]:

        try:

            result = (
                self.hycom.query_dict(
                    latitude=latitude,
                    longitude=longitude,
                    depth_m=depth_m,
                    time_utc=time_utc,
                )
            )

            return {
                "available": True,

                "source": (
                    result.get(
                        "source"
                    )
                    or "INCOIS"
                ),

                "dataset": (
                    result.get(
                        "dataset"
                    )
                    or "RSMC HYCOM"
                ),

                "source_url": (
                    result.get(
                        "source_url"
                    )
                ),

                "requested": {
                    "latitude": result.get(
                        "requested_latitude"
                    ),
                    "longitude": result.get(
                        "requested_longitude"
                    ),
                    "depth_m": result.get(
                        "requested_depth_m"
                    ),
                    "time_utc": result.get(
                        "requested_time_utc"
                    ),
                },

                "actual": {
                    "latitude": result.get(
                        "actual_latitude"
                    ),
                    "longitude": result.get(
                        "actual_longitude"
                    ),
                    "depth_m": result.get(
                        "actual_depth_m"
                    ),
                    "time_utc": result.get(
                        "actual_time_utc"
                    ),
                },

                "values": {
                    "temperature_c": result.get(
                        "temperature_c"
                    ),

                    "salinity_psu": result.get(
                        "salinity"
                    ),

                    "u_current_m_s": result.get(
                        "u_current_m_s"
                    ),

                    "v_current_m_s": result.get(
                        "v_current_m_s"
                    ),

                    "current_speed_m_s": result.get(
                        "current_speed_m_s"
                    ),

                    "current_direction_math_deg": (
                        result.get(
                            "current_direction_math_deg"
                        )
                    ),

                    "ssh_m": result.get(
                        "ssh_m"
                    ),
                },

                "missing": {
                    "temperature": result.get(
                        "temp_missing"
                    ),

                    "salinity": result.get(
                        "salinity_missing"
                    ),

                    "u_current": result.get(
                        "u_current_missing"
                    ),

                    "v_current": result.get(
                        "v_current_missing"
                    ),

                    "ssh": result.get(
                        "ssh_missing"
                    ),
                },

                "selection": (
                    "nearest-neighbour"
                ),

                "interpolation": False,

                "chunk_file": result.get(
                    "chunk_file"
                ),

                "synthetic_data": False,
            }

        except Exception as exc:

            return {
                "available": False,

                "source": "INCOIS",

                "dataset": (
                    "RSMC HYCOM"
                ),

                "source_url": (
                    "https://incois.gov.in/"
                    "thredds/dodsC/"
                    "osf/currents2/"
                    "RSMC_hycom_20260911.nc"
                ),

                "reason": str(
                    exc
                ),

                "synthetic_data": False,
            }

    # =========================================================================
    # ARGO
    # =========================================================================

    def _query_argo(
        self,
        latitude: float,
        longitude: float,
        pressure_dbar: float | None,
        radius_degrees: float,
    ) -> dict[str, Any]:

        try:

            nearest_profile = (
                self.argo.find_nearest_profile(
                    latitude=latitude,
                    longitude=longitude,
                    radius_degrees=radius_degrees,
                )
            )

            if not nearest_profile.get(
                "available"
            ):

                return nearest_profile

            profile = (
                nearest_profile[
                    "nearest_profile"
                ]
            )

            platform_number = str(
                profile[
                    "platform_number"
                ]
            )

            cycle_number = int(
                profile[
                    "cycle_number"
                ]
            )

            full_profile = (
                self.argo.get_profile(
                    platform_number=platform_number,
                    cycle_number=cycle_number,
                )
            )

            if not full_profile.get(
                "available"
            ):

                return full_profile

            response: dict[str, Any] = {

                "available": True,

                "source": (
                    "INCOIS ERDDAP"
                ),

                "dataset": (
                    "Indian_ARGO_Floats"
                ),

                "source_url": (
                    "https://erddap.incois.gov.in/"
                    "erddap/tabledap/"
                    "Indian_ARGO_Floats.csv"
                ),

                "nearest_profile": {

                    "platform_number": (
                        platform_number
                    ),

                    "cycle_number": (
                        cycle_number
                    ),

                    "profile_time_utc": (
                        full_profile.get(
                            "profile_time_utc"
                        )
                    ),

                    "latitude": (
                        full_profile.get(
                            "latitude"
                        )
                    ),

                    "longitude": (
                        full_profile.get(
                            "longitude"
                        )
                    ),

                    "measurement_count": (
                        full_profile.get(
                            "measurement_count"
                        )
                    ),
                },

                "pressure": (
                    full_profile.get(
                        "pressure"
                    )
                ),

                "observations": (
                    full_profile.get(
                        "observations",
                        [],
                    )
                ),

                "selection": {
                    "profile": (
                        "nearest-profile"
                    ),

                    "observation": (
                        "nearest-observed-PRES"
                        if pressure_dbar
                        is not None
                        else None
                    ),
                },

                "synthetic_data": False,
            }

            # ---------------------------------------------------------------
            # Optional pressure-specific Argo observation.
            #
            # IMPORTANT:
            # pressure remains dbar.
            # ---------------------------------------------------------------

            if pressure_dbar is not None:

                pressure_result = (
                    self.argo.query_nearest_observation(
                        latitude=latitude,
                        longitude=longitude,
                        pressure_dbar=pressure_dbar,
                        radius_degrees=radius_degrees,
                    )
                )

                response[
                    "pressure_query"
                ] = pressure_result

            else:

                response[
                    "pressure_query"
                ] = None

            return response

        except Exception as exc:

            return {
                "available": False,

                "source": (
                    "INCOIS ERDDAP"
                ),

                "dataset": (
                    "Indian_ARGO_Floats"
                ),

                "source_url": (
                    "https://erddap.incois.gov.in/"
                    "erddap/tabledap/"
                    "Indian_ARGO_Floats.csv"
                ),

                "reason": str(
                    exc
                ),

                "synthetic_data": False,
            }

    # =========================================================================
    # GEBCO
    # =========================================================================

    def _query_gebco(
        self,
        latitude: float,
        longitude: float,
    ) -> dict[str, Any]:

        try:

            result = (
                self.gebco.query(
                    latitude,
                    longitude,
                )
            )

            elevation = (
                self._finite_or_none(
                    result.get(
                        "elevation_m"
                    )
                )
            )

            seafloor_depth_m = None

            if (
                elevation is not None
                and elevation < 0.0
            ):

                seafloor_depth_m = abs(
                    elevation
                )

            return {

                "available": bool(
                    result.get(
                        "available",
                        False,
                    )
                ),

                "source": "GEBCO",

                "dataset": (
                    "GEBCO_2026"
                ),

                "source_url": (
                    result.get(
                        "source_url"
                    )
                ),

                "elevation_m": (
                    elevation
                ),

                "depth_below_sea_level_m": (
                    seafloor_depth_m
                ),

                "missing": bool(
                    result.get(
                        "missing",
                        True,
                    )
                ),

                "source_grid": (
                    result.get(
                        "source_grid"
                    )
                ),

                "chunk_id": (
                    result.get(
                        "chunk_id"
                    )
                ),

                "selection": (
                    "nearest-neighbour"
                ),

                "interpolation": False,

                "synthetic_data": False,
            }

        except Exception as exc:

            return {
                "available": False,

                "source": "GEBCO",

                "dataset": (
                    "GEBCO_2026"
                ),

                "reason": str(
                    exc
                ),

                "synthetic_data": False,
            }

    # =========================================================================
    # UNIFIED QUERY
    # =========================================================================

    def query(
        self,
        latitude: float,
        longitude: float,
        depth_m: float,
        time_utc: str | None = None,
        pressure_dbar: float | None = None,
        argo_radius_degrees: float = 2.0,
    ) -> dict[str, Any]:

        latitude = (
            self._validate_latitude(
                latitude
            )
        )

        longitude = (
            self._normalize_longitude(
                longitude
            )
        )

        depth_m = (
            self._validate_depth(
                depth_m
            )
        )

        if pressure_dbar is not None:

            pressure_dbar = (
                self._validate_pressure(
                    pressure_dbar
                )
            )

        if (
            not math.isfinite(
                float(
                    argo_radius_degrees
                )
            )
            or float(
                argo_radius_degrees
            ) <= 0.0
        ):

            raise ValueError(
                "Argo radius must be greater than zero."
            )

        # ---------------------------------------------------------------
        # Query each source independently.
        # ---------------------------------------------------------------

        hycom = self._query_hycom(
            latitude=latitude,
            longitude=longitude,
            depth_m=depth_m,
            time_utc=time_utc,
        )

        argo = self._query_argo(
            latitude=latitude,
            longitude=longitude,
            pressure_dbar=pressure_dbar,
            radius_degrees=float(
                argo_radius_degrees
            ),
        )

        gebco = self._query_gebco(
            latitude=latitude,
            longitude=longitude,
        )

        # ---------------------------------------------------------------
        # Physical geometry.
        # ---------------------------------------------------------------

        seafloor_depth_m = (
            self._finite_or_none(
                gebco.get(
                    "depth_below_sea_level_m"
                )
            )
        )

        below_seafloor = None

        if seafloor_depth_m is not None:

            below_seafloor = (
                depth_m
                > seafloor_depth_m
            )

        # ---------------------------------------------------------------
        # Unified response.
        # ---------------------------------------------------------------

        return {

            "timestamp_utc": (
                datetime.now(
                    timezone.utc
                )
                .replace(
                    microsecond=0
                )
                .isoformat()
                .replace(
                    "+00:00",
                    "Z",
                )
            ),

            "request": {

                "latitude": latitude,

                "longitude": longitude,

                "depth_m": depth_m,

                "time_utc": time_utc,

                "pressure_dbar": (
                    pressure_dbar
                ),
            },

            "sources": {

                "incois_hycom": hycom,

                "incois_argo": argo,

                "gebco_bathymetry": gebco,
            },

            "physical_relationship": {

                "requested_water_depth_m": (
                    depth_m
                ),

                "seafloor_depth_m": (
                    seafloor_depth_m
                ),

                "below_seafloor": (
                    below_seafloor
                ),
            },

            "scientific_rules": {

                "synthetic_data": False,

                "interpolation": False,

                "hycom_depth_unit": "m",

                "argo_pressure_unit": "dbar",

                "argo_pressure_preserved": True,

                "argo_pressure_converted_to_depth": False,

                "missing_values_replaced_with_zero": False,
            },

            "provenance": {

                "primary_ocean_model": {

                    "source": "INCOIS",

                    "dataset": (
                        "RSMC HYCOM"
                    ),

                    "url": (
                        hycom.get(
                            "source_url"
                        )
                    ),
                },

                "observations": {

                    "source": (
                        "INCOIS ERDDAP"
                    ),

                    "dataset": (
                        "Indian_ARGO_Floats"
                    ),

                    "url": (
                        "https://erddap.incois.gov.in/"
                        "erddap/tabledap/"
                        "Indian_ARGO_Floats.csv"
                    ),
                },

                "bathymetry": {

                    "source": "GEBCO",

                    "dataset": (
                        "GEBCO_2026"
                    ),

                    "url": (
                        gebco.get(
                            "source_url"
                        )
                    ),
                },
            },
        }


# =============================================================================
# TEST
# =============================================================================


def main() -> None:

    print(
        "=" * 80
    )

    print(
        "OCEANSIGHT-V"
    )

    print(
        "UNIFIED SCIENTIFIC QUERY"
    )

    print(
        "=" * 80
    )

    engine = (
        ScientificQueryEngine()
    )

    # -------------------------------------------------------------------------
    # Use your proven HYCOM location for the first combined test.
    #
    # HYCOM:
    #     2026-09-10T06:00:00Z
    #     100 m
    #
    # Argo:
    #     search near this geographic location
    #     at 100 dbar
    #
    # IMPORTANT:
    #     100 m and 100 dbar are intentionally separate.
    # -------------------------------------------------------------------------

    result = engine.query(
        latitude=-8.20,
        longitude=68.20,

        depth_m=100.0,

        time_utc=(
            "2026-09-10T06:00:00Z"
        ),

        pressure_dbar=100.0,

        argo_radius_degrees=5.0,
    )

    print()

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

    hycom = result[
        "sources"
    ][
        "incois_hycom"
    ]

    if hycom.get(
        "available"
    ):

        print(
            "INCOIS HYCOM: AVAILABLE"
        )

        values = hycom[
            "values"
        ]

        print(
            "  Temperature:",
            values[
                "temperature_c"
            ],
            "C",
        )

        print(
            "  Salinity:",
            values[
                "salinity_psu"
            ],
            "PSU",
        )

        print(
            "  U:",
            values[
                "u_current_m_s"
            ],
            "m/s",
        )

        print(
            "  V:",
            values[
                "v_current_m_s"
            ],
            "m/s",
        )

        print(
            "  Current speed:",
            values[
                "current_speed_m_s"
            ],
            "m/s",
        )

        print(
            "  SSH:",
            values[
                "ssh_m"
            ],
            "m",
        )

        print(
            "  Actual source time:",
            hycom[
                "actual"
            ][
                "time_utc"
            ],
        )

    else:

        print(
            "INCOIS HYCOM: NOT AVAILABLE"
        )

        print(
            "  Reason:",
            hycom.get(
                "reason"
            ),
        )

    print()

    argo = result[
        "sources"
    ][
        "incois_argo"
    ]

    if argo.get(
        "available"
    ):

        profile = argo[
            "nearest_profile"
        ]

        print(
            "INCOIS ARGO: AVAILABLE"
        )

        print(
            "  Platform:",
            profile[
                "platform_number"
            ],
        )

        print(
            "  Cycle:",
            profile[
                "cycle_number"
            ],
        )

        print(
            "  Profile time:",
            profile[
                "profile_time_utc"
            ],
        )

        pressure_query = argo.get(
            "pressure_query"
        )

        if (
            isinstance(
                pressure_query,
                dict,
            )
            and pressure_query.get(
                "available"
            )
        ):

            observation = (
                pressure_query[
                    "source_observation"
                ]
            )

            print(
                "  Requested pressure:",
                pressure_query[
                    "pressure"
                ][
                    "requested_dbar"
                ],
                "dbar",
            )

            print(
                "  Actual observed pressure:",
                observation[
                    "pres_dbar"
                ],
                "dbar",
            )

            print(
                "  Observed temperature:",
                observation[
                    "temp_c"
                ],
                "C",
            )

            print(
                "  Observed salinity:",
                observation[
                    "psal_psu"
                ],
                "PSU",
            )

            print(
                "  PRES_QC:",
                observation[
                    "pres_qc"
                ],
            )

            print(
                "  TEMP_QC:",
                observation[
                    "temp_qc"
                ],
            )

            print(
                "  PSAL_QC:",
                observation[
                    "psal_qc"
                ],
            )

        else:

            print(
                "  No Argo observation found "
                "for requested pressure."
            )

    else:

        print(
            "INCOIS ARGO: NO LOCAL PROFILE "
            "WITHIN SEARCH RADIUS"
        )

    print()

    gebco = result[
        "sources"
    ][
        "gebco_bathymetry"
    ]

    if gebco.get(
        "available"
    ):

        print(
            "GEBCO 2026: AVAILABLE"
        )

        print(
            "  Seafloor elevation:",
            gebco[
                "elevation_m"
            ],
            "m",
        )

        print(
            "  Seafloor depth:",
            gebco[
                "depth_below_sea_level_m"
            ],
            "m",
        )

    else:

        print(
            "GEBCO 2026: NOT AVAILABLE"
        )

    print()

    print(
        "Scientific rules:"
    )

    print(
        "  Synthetic:",
        result[
            "scientific_rules"
        ][
            "synthetic_data"
        ],
    )

    print(
        "  Interpolation:",
        result[
            "scientific_rules"
        ][
            "interpolation"
        ],
    )

    print(
        "  Argo pressure preserved:",
        result[
            "scientific_rules"
        ][
            "argo_pressure_preserved"
        ],
    )

    print(
        "  Argo pressure converted to depth:",
        result[
            "scientific_rules"
        ][
            "argo_pressure_converted_to_depth"
        ],
    )

    print(
        "=" * 80
    )


if __name__ == "__main__":
    main()