
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .argo_live_manager import ArgoLiveManager
from .argo_query import ArgoQueryEngine
from .gebco_live_manager import GEBCOLiveManager
from .gebco_query import GEBCOQuery
from .hycom_live_manager import HycomLiveManager
from .ocean_query import OceanQueryEngine


PROJECT_ROOT = Path(__file__).resolve().parent.parent

HYCOM_INDEX = (
    PROJECT_ROOT
    / "processed"
    / "hycom_chunk_index.json"
)

GEBCO_INDEX = (
    PROJECT_ROOT
    / "processed"
    / "gebco_chunk_index.json"
)

ARGO_DB = (
    PROJECT_ROOT
    / "processed"
    / "argo_store.sqlite"
)


class Ocean3DQueryEngine:
    """
    Unified scientific query engine.

    Scientific units:

        HYCOM depth   = meters
        Argo pressure = dbar
        GEBCO elevation = meters

    Rules:

        No pressure-to-depth conversion.
        No synthetic data.
        No interpolation.

    Live acquisition:

        HYCOM  -> INCOIS THREDDS / OPeNDAP
        Argo   -> INCOIS ERDDAP
        GEBCO  -> GEBCO 2026 OPeNDAP
    """

    def __init__(
        self,
        hycom_index_path: Path = HYCOM_INDEX,
        gebco_index_path: Path = GEBCO_INDEX,
        argo_db_path: Path = ARGO_DB,
    ) -> None:

        self.hycom_index_path = Path(
            hycom_index_path
        )

        self.gebco_index_path = Path(
            gebco_index_path
        )

        self.argo_db_path = Path(
            argo_db_path
        )

        # ---------------------------------------------------------------------
        # HYCOM
        # ---------------------------------------------------------------------

        self.hycom = OceanQueryEngine()

        self.hycom_live = HycomLiveManager()

        # ---------------------------------------------------------------------
        # GEBCO
        # ---------------------------------------------------------------------

        self.gebco = GEBCOQuery(
            index_path=self.gebco_index_path
        )

        self.gebco_live = GEBCOLiveManager()

        # ---------------------------------------------------------------------
        # ARGO
        # ---------------------------------------------------------------------

        self.argo = ArgoQueryEngine(
            db_path=self.argo_db_path
        )

        # Live Argo manager writes into the same SQLite database used by
        # ArgoQueryEngine.
        self.argo_live = ArgoLiveManager()

    # =========================================================================
    # TIME
    # =========================================================================

    @staticmethod
    def _now_utc_iso() -> str:
        return (
            datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace(
                "+00:00",
                "Z",
            )
        )

    # =========================================================================
    # ARGO QUERY
    # =========================================================================

    def _query_argo_once(
        self,
        latitude: float,
        longitude: float,
        pressure_dbar: float | None,
        radius_degrees: float,
    ) -> dict[str, Any]:

        if pressure_dbar is None:

            nearest = (
                self.argo.find_nearest_profile(
                    latitude=latitude,
                    longitude=longitude,
                    radius_degrees=radius_degrees,
                )
            )

            if not nearest.get(
                "available",
                False,
            ):
                return nearest

            profile_ref = nearest[
                "nearest_profile"
            ]

            profile = self.argo.get_profile(
                platform_number=profile_ref[
                    "platform_number"
                ],
                cycle_number=int(
                    profile_ref[
                        "cycle_number"
                    ]
                ),
            )

            return {
                "available": profile.get(
                    "available",
                    False,
                ),
                "selection": (
                    "nearest Argo profile"
                ),
                "profile": profile,
                "pressure": {
                    "unit": "dbar",
                    "requested_dbar": None,
                    "converted_to_depth": False,
                },
                "provenance": {
                    **profile.get(
                        "provenance",
                        {},
                    ),
                    "synthetic_data": False,
                    "interpolation": False,
                },
            }

        return (
            self.argo.query_nearest_observation(
                latitude=latitude,
                longitude=longitude,
                pressure_dbar=float(
                    pressure_dbar
                ),
                radius_degrees=radius_degrees,
            )
        )

    def _query_argo(
        self,
        latitude: float,
        longitude: float,
        pressure_dbar: float | None,
        radius_degrees: float,
        time_utc: str | None = None,
    ) -> tuple[
        dict[str, Any],
        dict[str, Any] | None,
    ]:
        """
        Query local Argo first.

        If no suitable local Argo data exists, automatically query
        real INCOIS ERDDAP data and ingest the acquired profile into
        the same local SQLite store.

        Returns:

            (
                argo_result,
                acquisition_result_or_none
            )
        """

        local_result = self._query_argo_once(
            latitude=latitude,
            longitude=longitude,
            pressure_dbar=pressure_dbar,
            radius_degrees=radius_degrees,
        )

        # ---------------------------------------------------------------------
        # Local Argo exists.
        # ---------------------------------------------------------------------

        if local_result.get(
            "available",
            False,
        ):

            return (
                local_result,
                None,
            )

        # ---------------------------------------------------------------------
        # No local Argo.
        #
        # A pressure is required for the live acquisition because the live
        # manager searches around a requested scientific PRES value.
        #
        # When no pressure was supplied, use a conservative shallow Argo
        # search pressure of 0 dbar only as a profile-discovery request.
        # No observation is fabricated and no pressure conversion occurs.
        # ---------------------------------------------------------------------

        acquisition_pressure = (
            float(pressure_dbar)
            if pressure_dbar is not None
            else 0.0
        )

        acquisition = (
            self.argo_live.acquire(
                latitude=latitude,
                longitude=longitude,
                pressure_dbar=acquisition_pressure,
                time_utc=time_utc,
                radius_degrees=radius_degrees,
            )
        )

        # ---------------------------------------------------------------------
        # Live acquisition failed / no real Argo observation available.
        # ---------------------------------------------------------------------

        if not acquisition.get(
            "available",
            False,
        ):

            return (
                {
                    **local_result,
                    "live_acquisition": acquisition,
                },
                acquisition,
            )

        # ---------------------------------------------------------------------
        # Recreate the local Argo query engine so the query uses the newly
        # ingested database records.
        # ---------------------------------------------------------------------

        self.argo = ArgoQueryEngine(
            db_path=self.argo_db_path
        )

        refreshed_result = self._query_argo_once(
            latitude=latitude,
            longitude=longitude,
            pressure_dbar=pressure_dbar,
            radius_degrees=radius_degrees,
        )

        # ---------------------------------------------------------------------
        # If the caller did not request a particular pressure, the live
        # manager acquired a real profile. Return that acquisition result when
        # the generic local query cannot select a point.
        # ---------------------------------------------------------------------

        if not refreshed_result.get(
            "available",
            False,
        ):

            refreshed_result = {
                **acquisition,
                "live_acquisition": acquisition,
            }

        else:

            refreshed_result = {
                **refreshed_result,
                "live_acquisition": acquisition,
            }

        return (
            refreshed_result,
            acquisition,
        )

    # =========================================================================
    # HYCOM QUERY
    # =========================================================================

    def _query_hycom_with_acquisition(
        self,
        latitude: float,
        longitude: float,
        depth_m: float,
        time_utc: str,
    ) -> tuple[
        Any | None,
        dict[str, Any] | None,
    ]:
        """
        Query local HYCOM first.

        If the required chunk is missing, automatically acquire the real
        INCOIS HYCOM chunk and retry.

        Always returns:

            (observation_or_none, acquisition_result_or_none)
        """

        try:

            result = self.hycom.query(
                latitude=latitude,
                longitude=longitude,
                depth_m=depth_m,
                time_utc=time_utc,
            )

            return (
                result,
                None,
            )

        except Exception as exc:

            message = str(exc)

            if (
                "No locally stored HYCOM chunk covers"
                not in message
            ):
                raise

            acquisition = (
                self.hycom_live.ensure_hycom_chunk(
                    latitude=latitude,
                    longitude=longitude,
                    time_utc=time_utc,
                    radius_degrees=0.25,
                )
            )

            if not acquisition.get(
                "available",
                False,
            ):

                return (
                    None,
                    acquisition,
                )

            # Reload the query engine because the live manager may have
            # created new coordinate/chunk/index files.

            self.hycom = OceanQueryEngine()

            result = self.hycom.query(
                latitude=latitude,
                longitude=longitude,
                depth_m=depth_m,
                time_utc=time_utc,
            )

            return (
                result,
                acquisition,
            )

    # =========================================================================
    # MAIN QUERY
    # =========================================================================

    def query(
        self,
        latitude: float,
        longitude: float,
        depth_m: float,
        time_utc: str,
        *,
        argo_pressure_dbar: float | None = None,
        argo_radius_degrees: float = 2.0,
    ) -> dict[str, Any]:

        latitude = float(
            latitude
        )

        longitude = float(
            longitude
        )

        depth_m = float(
            depth_m
        )

        time_utc = str(
            time_utc
        )

        # ---------------------------------------------------------------------
        # HYCOM
        # ---------------------------------------------------------------------

        (
            hycom,
            hycom_acquisition,
        ) = self._query_hycom_with_acquisition(
            latitude=latitude,
            longitude=longitude,
            depth_m=depth_m,
            time_utc=time_utc,
        )

        # ---------------------------------------------------------------------
        # INCOIS HYCOM RESULT
        # ---------------------------------------------------------------------

        if hycom is None:

            water_column = {
                "available": False,
                "source": "INCOIS",
                "dataset": None,
                "source_url": None,
                "data": None,
                "missing": {
                    "temperature": True,
                    "salinity": True,
                    "u_current": True,
                    "v_current": True,
                    "ssh": True,
                },
                "interpolation": False,
                "synthetic_data": False,
            }

        else:

            water_column = {
                "available": True,
                "source": hycom.source,
                "dataset": hycom.dataset,
                "source_url": hycom.source_url,

                "data": {
                    "requested_latitude": (
                        hycom.requested_latitude
                    ),
                    "requested_longitude": (
                        hycom.requested_longitude
                    ),
                    "requested_depth_m": (
                        hycom.requested_depth_m
                    ),
                    "requested_time_utc": (
                        hycom.requested_time_utc
                    ),
                    "actual_latitude": (
                        hycom.actual_latitude
                    ),
                    "actual_longitude": (
                        hycom.actual_longitude
                    ),
                    "actual_depth_m": (
                        hycom.actual_depth_m
                    ),
                    "actual_time_utc": (
                        hycom.actual_time_utc
                    ),
                    "temperature_c": (
                        hycom.temperature_c
                    ),
                    "salinity_psu": (
                        hycom.salinity
                    ),
                    "u_current_m_s": (
                        hycom.u_current_m_s
                    ),
                    "v_current_m_s": (
                        hycom.v_current_m_s
                    ),
                    "current_speed_m_s": (
                        hycom.current_speed_m_s
                    ),
                    "current_direction_math_deg": (
                        hycom.current_direction_math_deg
                    ),
                    "ssh_m": (
                        hycom.ssh_m
                    ),
                },

                "missing": {
                    "temperature": (
                        hycom.temp_missing
                    ),
                    "salinity": (
                        hycom.salinity_missing
                    ),
                    "u_current": (
                        hycom.u_current_missing
                    ),
                    "v_current": (
                        hycom.v_current_missing
                    ),
                    "ssh": (
                        hycom.ssh_missing
                    ),
                },

                "selection": (
                    "nearest-neighbour"
                ),

                "interpolation": False,

                "chunk_file": (
                    hycom.chunk_file
                ),

                "synthetic_data": False,
            }

        # ---------------------------------------------------------------------
        # GEBCO
        # ---------------------------------------------------------------------

        try:

            bathymetry = self.gebco.query(
                lat=latitude,
                lon=longitude,
            )

        except (
            FileNotFoundError,
            RuntimeError,
        ):

            bathymetry = (
                self.gebco_live.query_or_acquire(
                    latitude=latitude,
                    longitude=longitude,
                    radius_degrees=0.25,
                )
            )

        else:

            if not bathymetry.get(
                "available",
                False,
            ):

                bathymetry = (
                    self.gebco_live.query_or_acquire(
                        latitude=latitude,
                        longitude=longitude,
                        radius_degrees=0.25,
                    )
                )

        elevation_m = bathymetry.get(
            "elevation_m"
        )

        if (
            bathymetry.get(
                "available",
                False,
            )
            and elevation_m is not None
            and float(elevation_m) < 0.0
        ):

            seafloor_depth_m = abs(
                float(elevation_m)
            )

        else:

            seafloor_depth_m = None

        bathymetry_result = {
            **bathymetry,
            "depth_below_sea_level_m": (
                seafloor_depth_m
            ),
        }

        # ---------------------------------------------------------------------
        # INCOIS ARGO
        # ---------------------------------------------------------------------

        (
            argo,
            argo_acquisition,
        ) = self._query_argo(
            latitude=latitude,
            longitude=longitude,
            pressure_dbar=argo_pressure_dbar,
            radius_degrees=argo_radius_degrees,
            time_utc=time_utc,
        )

        # ---------------------------------------------------------------------
        # Physical relationship
        # ---------------------------------------------------------------------

        below_seafloor = None

        if seafloor_depth_m is not None:

            below_seafloor = (
                depth_m
                > seafloor_depth_m
            )

        # ---------------------------------------------------------------------
        # Provenance
        # ---------------------------------------------------------------------

        provenance = {
            "ocean_state": {
                "source": (
                    water_column.get(
                        "source"
                    )
                ),
                "dataset": (
                    water_column.get(
                        "dataset"
                    )
                ),
                "source_url": (
                    water_column.get(
                        "source_url"
                    )
                ),
            },

            "argo": argo.get(
                "provenance",
                {},
            ),

            "bathymetry": {
                "source": (
                    bathymetry_result.get(
                        "source"
                    )
                ),
                "dataset": (
                    bathymetry_result.get(
                        "dataset"
                    )
                ),
                "source_url": (
                    bathymetry_result.get(
                        "source_url"
                    )
                ),
            },

            "interpolation": False,

            "synthetic_data": False,

            "argo_pressure_conversion": {
                "converted_to_depth": False,
                "preserved_as_source_pressure": True,
                "unit": "dbar",
            },
        }

        # ---------------------------------------------------------------------
        # HYCOM acquisition provenance
        # ---------------------------------------------------------------------

        if hycom_acquisition is not None:

            provenance[
                "hycom_acquisition"
            ] = {
                "automatic": True,
                "available": (
                    hycom_acquisition.get(
                        "available",
                        False,
                    )
                ),
                "dataset": (
                    hycom_acquisition.get(
                        "dataset"
                    )
                ),
                "coordinate_catalog": (
                    hycom_acquisition.get(
                        "coordinate_catalog"
                    )
                ),
                "planned_chunks": (
                    hycom_acquisition.get(
                        "planned_chunks",
                        0,
                    )
                ),
                "downloaded": (
                    hycom_acquisition.get(
                        "downloaded",
                        [],
                    )
                ),
                "skipped_existing": (
                    hycom_acquisition.get(
                        "skipped_existing",
                        [],
                    )
                ),
                "synthetic_data": False,
                "interpolation": False,
                "full_netcdf_downloaded": False,
            }

        # ---------------------------------------------------------------------
        # ARGO acquisition provenance
        # ---------------------------------------------------------------------

        if argo_acquisition is not None:

            provenance[
                "argo_acquisition"
            ] = {
                "automatic": True,
                "available": (
                    argo_acquisition.get(
                        "available",
                        False,
                    )
                ),
                "source": (
                    argo_acquisition.get(
                        "source",
                        "INCOIS ERDDAP",
                    )
                ),
                "dataset": (
                    argo_acquisition.get(
                        "dataset",
                        "Indian_ARGO_Floats",
                    )
                ),
                "synthetic_data": False,
                "interpolation": False,
                "pressure_unit": "dbar",
                "pressure_converted_to_depth": False,
                "provenance": (
                    argo_acquisition.get(
                        "provenance",
                        {},
                    )
                ),
            }

        # ---------------------------------------------------------------------
        # Final response
        # ---------------------------------------------------------------------

        return {
            "timestamp_utc": (
                self._now_utc_iso()
            ),

            "request": {
                "latitude": latitude,
                "longitude": longitude,
                "depth_m": depth_m,
                "time_utc": time_utc,
                "argo_pressure_dbar": (
                    argo_pressure_dbar
                ),
                "argo_radius_degrees": (
                    argo_radius_degrees
                ),
            },

            "water_column": water_column,

            "argo_observation": argo,

            "bathymetry": bathymetry_result,

            "physical_relationship": {
                "requested_depth_m": depth_m,
                "seafloor_depth_m": (
                    seafloor_depth_m
                ),
                "below_seafloor": (
                    below_seafloor
                ),
            },

            "provenance": provenance,
        }


# =============================================================================
# COMMAND LINE
# =============================================================================

def main() -> None:

    print(
        "=" * 78
    )

    print(
        "OceanSight - Unified Scientific Query"
    )

    print(
        "=" * 78
    )

    engine = Ocean3DQueryEngine()

    result = engine.query(
        latitude=-8.2,
        longitude=68.2,
        depth_m=100.0,
        time_utc="2026-09-10T06:00:00Z",
        argo_pressure_dbar=100.0,
        argo_radius_degrees=2.0,
    )

    print(
        json.dumps(
            result,
            indent=2,
            default=str,
        )
    )

    print()

    print(
        "=" * 78
    )

    print(
        "HYCOM depth unit: m"
    )

    print(
        "ARGO pressure unit: dbar"
    )

    print(
        "ARGO pressure-to-depth conversion: FALSE"
    )

    print(
        "Synthetic data:",
        result[
            "provenance"
        ][
            "synthetic_data"
        ],
    )

    print(
        "Interpolation:",
        result[
            "provenance"
        ][
            "interpolation"
        ],
    )

    print(
        "ARGO live acquisition:",
        result[
            "provenance"
        ].get(
            "argo_acquisition",
            {}
        ).get(
            "automatic",
            False,
        ),
    )

    print(
        "=" * 78
    )


if __name__ == "__main__":
    main()

