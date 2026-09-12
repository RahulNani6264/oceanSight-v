from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query

from .argo_live_manager import ArgoLiveManager
from .argo_query import ArgoQueryEngine
from .ocean_3d_query import Ocean3DQueryEngine
from .ocean_slice import OceanSliceEngine
from .schemas import (
    ArgoProfileDiscoveryResponse,
    ArgoProfileSeries,
    HealthResponse,
    OceanPointResponse,
    RootResponse,
)


# =============================================================================
# OCEANSIGHT-V
# SCIENTIFIC FASTAPI
#
# Sources:
#
#   Ocean state  -> INCOIS HYCOM
#   Observations -> INCOIS Indian Argo
#   Bathymetry   -> GEBCO 2026
#
# API:
#
#   /
#   /api/v1/health
#   /api/v1/hycom/times
#   /api/v1/ocean/point
#   /api/v1/ocean/slice
#   /api/v1/argo/profiles
#   /api/v1/argo/profile
#
# Scientific rules:
#
#   synthetic data = false
#   interpolation  = false
#   Argo PRES      = dbar
#   Argo PRES is never silently converted to depth.
# =============================================================================


app = FastAPI(
    title="OceanSight-V Scientific API",
    version="1.0.0",
    description=(
        "Scientific ocean data API backed by "
        "INCOIS HYCOM, INCOIS Argo, and GEBCO 2026. "
        "Real source observations can be acquired live "
        "when they are not already available locally."
    ),
)


# =============================================================================
# SCIENTIFIC ENGINES
# =============================================================================

engine = Ocean3DQueryEngine()

slice_engine = OceanSliceEngine()

argo_engine = ArgoQueryEngine()

argo_live_manager = ArgoLiveManager()


# =============================================================================
# PATHS
# =============================================================================

PROJECT_ROOT = (
    Path(__file__).resolve().parent.parent
)

HYCOM_TIME_CATALOG = (
    PROJECT_ROOT
    / "processed"
    / "hycom_catalog"
    / "hycom_times.json"
)


# =============================================================================
# ARGO CONSTANTS
# =============================================================================

ARGO_SOURCE = "INCOIS ERDDAP"

ARGO_DATASET = "Indian_ARGO_Floats"

ARGO_SOURCE_URL = (
    "https://erddap.incois.gov.in/"
    "erddap/tabledap/"
    "Indian_ARGO_Floats.csv"
)


# =============================================================================
# TIME VALIDATION
# =============================================================================

def validate_time_utc(
    time_utc: str,
) -> str:
    """
    Validate and normalize an ISO-8601 UTC timestamp.

    Accepted examples:

        2026-09-10T06:00:00Z
        2026-09-10T06:00:00+00:00

    Returned form:

        2026-09-10T06:00:00Z
    """

    value = str(
        time_utc
    ).strip()

    if not value:

        raise ValueError(
            "time_utc cannot be empty."
        )

    try:

        normalized = value

        if normalized.endswith(
            "Z"
        ):

            normalized = (
                normalized[:-1]
                + "+00:00"
            )

        parsed = datetime.fromisoformat(
            normalized
        )

    except ValueError as exc:

        raise ValueError(
            "time_utc must be a valid ISO-8601 "
            "UTC timestamp, for example "
            "2026-09-10T06:00:00Z."
        ) from exc

    if parsed.tzinfo is None:

        raise ValueError(
            "time_utc must include an explicit timezone."
        )

    parsed_utc = parsed.astimezone(
        timezone.utc
    )

    return (
        parsed_utc
        .replace(
            microsecond=0
        )
        .isoformat()
        .replace(
            "+00:00",
            "Z",
        )
    )


# =============================================================================
# ROOT
# =============================================================================

@app.get(
    "/",
    response_model=RootResponse,
)
def root() -> dict[str, Any]:

    return {
        "name": "OceanSight-V",

        "service": (
            "Scientific Ocean Data API"
        ),

        "status": "running",

        "scientific_engine": {
            "status": "ready",
            "synthetic_data": False,
            "interpolation": False,
        },

        "sources": {
            "ocean_state": {
                "provider": "INCOIS",
                "dataset": "RSMC HYCOM",
            },

            "observations": {
                "provider": "INCOIS",
                "dataset": "Indian_ARGO_Floats",
            },

            "bathymetry": {
                "provider": "GEBCO",
                "dataset": "GEBCO_2026",
            },
        },

        "scientific_units": {
            "HYCOM_depth": "m",
            "ARGO_pressure": "dbar",
            "ARGO_temperature": (
                "degree_Celsius"
            ),
            "ARGO_salinity": "PSU",
            "GEBCO_elevation": "m",
        },

        "scientific_rules": {
            "argo_pressure_converted_to_depth": False,
            "synthetic_data": False,
            "interpolation": False,
        },
    }


# =============================================================================
# HEALTH
# =============================================================================

@app.get(
    "/api/v1/health",
    response_model=HealthResponse,
)
def health() -> dict[str, Any]:

    return {
        "status": "ok",

        "scientific_engine": "ready",

        "synthetic_data": False,

        "interpolation": False,

        "components": {
            "hycom": "enabled",
            "argo": "enabled",
            "gebco": "enabled",

            "live_hycom_acquisition": (
                "enabled"
            ),

            "live_argo_acquisition": (
                "enabled"
            ),

            "live_gebco_acquisition": (
                "enabled"
            ),
        },

        "scientific_units": {
            "hycom_depth": "m",
            "argo_pressure": "dbar",
            "gebco_elevation": "m",
        },
    }


# =============================================================================
# HYCOM TIME-STEP DISCOVERY
# =============================================================================

@app.get(
    "/api/v1/hycom/times",
)
def hycom_times(
    time_utc: str | None = Query(
        default=None,
        description=(
            "Optional exact HYCOM source time "
            "to look up."
        ),
    ),
) -> dict[str, Any]:

    try:

        if not HYCOM_TIME_CATALOG.exists():

            raise HTTPException(
                status_code=503,
                detail=(
                    "HYCOM time catalog is not available. "
                    "Run: python -m app.hycom_times"
                ),
            )

        with HYCOM_TIME_CATALOG.open(
            "r",
            encoding="utf-8",
        ) as file:

            catalog = json.load(
                file
            )

        if not isinstance(
            catalog,
            dict,
        ):

            raise HTTPException(
                status_code=503,
                detail=(
                    "HYCOM time catalog has an invalid format."
                ),
            )

        # ---------------------------------------------------------------------
        # Complete catalog.
        # ---------------------------------------------------------------------

        if time_utc is None:

            return {
                "api": {
                    "version": "1.0",
                    "endpoint": (
                        "/api/v1/hycom/times"
                    ),
                    "synthetic_data": False,
                    "interpolation": False,
                },

                "source": {
                    "provider": "INCOIS",
                    "dataset": "RSMC HYCOM",
                    "service": "THREDDS OPeNDAP",
                },

                "catalog": catalog,
            }

        # ---------------------------------------------------------------------
        # Exact lookup.
        # ---------------------------------------------------------------------

        normalized_time_utc = (
            validate_time_utc(
                time_utc
            )
        )

        time_records = catalog.get(
            "times",
            [],
        )

        if not isinstance(
            time_records,
            list,
        ):

            raise HTTPException(
                status_code=503,
                detail=(
                    "HYCOM time catalog contains "
                    "an invalid times collection."
                ),
            )

        exact_match = None

        for record in time_records:

            if not isinstance(
                record,
                dict,
            ):

                continue

            if (
                record.get(
                    "time_utc"
                )
                == normalized_time_utc
            ):

                exact_match = record

                break

        if exact_match is None:

            return {
                "api": {
                    "version": "1.0",
                    "endpoint": (
                        "/api/v1/hycom/times"
                    ),
                    "synthetic_data": False,
                    "interpolation": False,
                },

                "source": {
                    "provider": "INCOIS",
                    "dataset": "RSMC HYCOM",
                    "service": "THREDDS OPeNDAP",
                },

                "available": False,

                "requested_time_utc": (
                    normalized_time_utc
                ),

                "actual_time_utc": None,

                "time": None,

                "scientific_rules": {
                    "exact_time_match": True,
                    "interpolation": False,
                    "synthetic_data": False,
                },
            }

        return {
            "api": {
                "version": "1.0",
                "endpoint": (
                    "/api/v1/hycom/times"
                ),
                "synthetic_data": False,
                "interpolation": False,
            },

            "source": {
                "provider": "INCOIS",
                "dataset": "RSMC HYCOM",
                "service": "THREDDS OPeNDAP",
            },

            "available": True,

            "requested_time_utc": (
                normalized_time_utc
            ),

            "actual_time_utc": (
                exact_match.get(
                    "time_utc"
                )
            ),

            "time": exact_match,

            "scientific_rules": {
                "exact_time_match": True,
                "interpolation": False,
                "synthetic_data": False,
            },
        }

    except HTTPException:

        raise

    except ValueError as exc:

        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    except json.JSONDecodeError as exc:

        raise HTTPException(
            status_code=503,
            detail=(
                "HYCOM time catalog contains invalid JSON: "
                f"{exc}"
            ),
        ) from exc

    except OSError as exc:

        raise HTTPException(
            status_code=503,
            detail=(
                "Unable to read HYCOM time catalog: "
                f"{exc}"
            ),
        ) from exc

    except Exception as exc:

        raise HTTPException(
            status_code=500,
            detail=(
                "HYCOM time discovery API failed: "
                f"{exc}"
            ),
        ) from exc


# =============================================================================
# ARGO LOCAL PROFILE DISCOVERY HELPER
# =============================================================================

def _local_argo_discovery(
    latitude: float,
    longitude: float,
    radius_degrees: float,
    time_utc: str | None,
    platform_number: str | None,
    cycle_number: int | None,
    limit: int,
) -> dict[str, Any]:

    return argo_engine.discover_profiles(
        latitude=latitude,
        longitude=longitude,
        radius_degrees=radius_degrees,
        time_utc=time_utc,
        platform_number=platform_number,
        cycle_number=cycle_number,
        limit=limit,
    )


# =============================================================================
# ARGO PROFILE DISCOVERY
# =============================================================================

@app.get(
    "/api/v1/argo/profiles",
    response_model=ArgoProfileDiscoveryResponse,
)
def argo_profiles(
    latitude: float = Query(
        ...,
        ge=-90.0,
        le=90.0,
        description=(
            "Center latitude in degrees."
        ),
    ),

    longitude: float = Query(
        ...,
        ge=-180.0,
        le=180.0,
        description=(
            "Center longitude in degrees."
        ),
    ),

    radius_degrees: float = Query(
        default=5.0,
        gt=0.0,
        le=20.0,
        description=(
            "Argo profile discovery radius in degrees."
        ),
    ),

    time_utc: str | None = Query(
        default=None,
        description=(
            "Optional exact Argo profile time."
        ),
    ),

    platform_number: str | None = Query(
        default=None,
        description=(
            "Optional Argo platform number."
        ),
    ),

    cycle_number: int | None = Query(
        default=None,
        ge=0,
        description=(
            "Optional Argo cycle number."
        ),
    ),

    limit: int = Query(
        default=100,
        ge=1,
        le=1000,
        description=(
            "Maximum number of profiles."
        ),
    ),
) -> dict[str, Any]:

    try:

        normalized_time = None

        if time_utc is not None:

            normalized_time = (
                validate_time_utc(
                    time_utc
                )
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

        # ---------------------------------------------------------------------
        # FIRST: query local real observations.
        # ---------------------------------------------------------------------

        local_result = (
            _local_argo_discovery(
                latitude=float(
                    latitude
                ),

                longitude=float(
                    longitude
                ),

                radius_degrees=float(
                    radius_degrees
                ),

                time_utc=normalized_time,

                platform_number=(
                    normalized_platform
                ),

                cycle_number=(
                    normalized_cycle
                ),

                limit=int(
                    limit
                ),
            )
        )

        local_profiles = local_result.get(
            "profiles",
            [],
        )

        # ---------------------------------------------------------------------
        # SECOND: if local store has no profiles, use the live INCOIS source.
        #
        # This is deliberately a fallback rather than downloading complete
        # profiles for every map marker.
        # ---------------------------------------------------------------------

        acquisition = None

        profiles = local_profiles

        if not profiles:

            live_result = (
                argo_live_manager.discover_profiles(
                    latitude=float(
                        latitude
                    ),

                    longitude=float(
                        longitude
                    ),

                    radius_degrees=float(
                        radius_degrees
                    ),

                    time_utc=normalized_time,

                    time_window_days=30.0,

                    limit=int(
                        limit
                    ),
                )
            )

            profiles = live_result.get(
                "profiles",
                []
            )

            acquisition = {
                "mode": "live",
                "automatic": True,
                "source": ARGO_SOURCE,
                "dataset": ARGO_DATASET,
                "available": bool(
                    profiles
                ),
            }

        else:

            acquisition = {
                "mode": "local",
                "automatic": False,
                "source": ARGO_SOURCE,
                "dataset": ARGO_DATASET,
                "available": True,
            }

        # ---------------------------------------------------------------------
        # Apply platform/cycle filtering to live discovery too.
        # ---------------------------------------------------------------------

        if normalized_platform:

            profiles = [
                profile
                for profile in profiles
                if str(
                    profile.get(
                        "platform_number"
                    )
                ).strip()
                == normalized_platform
            ]

        if normalized_cycle is not None:

            profiles = [
                profile
                for profile in profiles
                if int(
                    profile.get(
                        "cycle_number"
                    )
                )
                == normalized_cycle
            ]

        profiles = profiles[
            : int(limit)
        ]

        profile_summaries = []

        for profile in profiles:

            profile_summaries.append(
                {
                    "platform_number": str(
                        profile.get(
                            "platform_number"
                        )
                    ),

                    "cycle_number": int(
                        profile.get(
                            "cycle_number"
                        )
                    ),

                    "direction": profile.get(
                        "direction"
                    ),

                    "profile_time_utc": profile.get(
                        "profile_time_utc"
                    ),

                    "latitude": profile.get(
                        "latitude"
                    ),

                    "longitude": profile.get(
                        "longitude"
                    ),

                    "source_dataset": (
                        ARGO_DATASET
                    ),

                    "source": ARGO_SOURCE,

                    "available": True,
                }
            )

        return {
            "available": bool(
                profile_summaries
            ),

            "source": ARGO_SOURCE,

            "dataset": ARGO_DATASET,

            "request": {
                "latitude": float(
                    latitude
                ),

                "longitude": float(
                    longitude
                ),

                "radius_degrees": float(
                    radius_degrees
                ),

                "time_utc": normalized_time,

                "platform_number": (
                    normalized_platform
                ),

                "cycle_number": (
                    normalized_cycle
                ),

                "limit": int(
                    limit
                ),
            },

            "profiles": profile_summaries,

            "profile_count": len(
                profile_summaries
            ),

            "selected_profile": None,

            "scientific_rules": {
                "synthetic_data": False,

                "interpolation": False,

                "pressure_unit": "dbar",

                "pressure_is_depth": False,

                "pressure_converted_to_depth": False,
            },

            "provenance": {
                "source": ARGO_SOURCE,

                "dataset": ARGO_DATASET,

                "source_url": ARGO_SOURCE_URL,

                "acquisition": acquisition,

                "storage": (
                    "local SQLite or live INCOIS ERDDAP"
                ),

                "synthetic_data": False,

                "interpolation": False,
            },
        }

    except HTTPException:

        raise

    except ValueError as exc:

        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    except FileNotFoundError as exc:

        raise HTTPException(
            status_code=503,
            detail=str(exc),
        ) from exc

    except RuntimeError as exc:

        raise HTTPException(
            status_code=503,
            detail=(
                "Argo profile discovery failed: "
                f"{exc}"
            ),
        ) from exc

    except Exception as exc:

        raise HTTPException(
            status_code=500,
            detail=(
                "Argo profile discovery failed: "
                f"{exc}"
            ),
        ) from exc


# =============================================================================
# ARGO COMPLETE PROFILE
# =============================================================================

@app.get(
    "/api/v1/argo/profile",
    response_model=ArgoProfileSeries,
)
def argo_profile(
    platform_number: str = Query(
        ...,
        min_length=1,
        description=(
            "Real Argo platform number."
        ),
    ),

    cycle_number: int = Query(
        ...,
        ge=0,
        description=(
            "Real Argo cycle number."
        ),
    ),
) -> dict[str, Any]:

    try:

        normalized_platform = str(
            platform_number
        ).strip()

        normalized_cycle = int(
            cycle_number
        )

        if not normalized_platform:

            raise ValueError(
                "platform_number cannot be empty."
            )

        # ---------------------------------------------------------------------
        # FIRST: local real profile.
        # ---------------------------------------------------------------------

        local_profile = (
            argo_engine.get_profile_series(
                platform_number=(
                    normalized_platform
                ),

                cycle_number=(
                    normalized_cycle
                ),
            )
        )

        if local_profile.get(
            "available"
        ):

            local_profile[
                "live_acquisition"
            ] = {
                "used": False,

                "mode": "local",

                "automatic": False,

                "source": ARGO_SOURCE,

                "dataset": ARGO_DATASET,
            }

            return local_profile

        # ---------------------------------------------------------------------
        # SECOND: live INCOIS profile acquisition.
        # ---------------------------------------------------------------------

        live_acquisition = (
            argo_live_manager.acquire_profile(
                platform_number=(
                    normalized_platform
                ),

                cycle_number=(
                    normalized_cycle
                ),
            )
        )

        if not live_acquisition.get(
            "available"
        ):

            raise HTTPException(
                status_code=404,
                detail=(
                    "No real Argo profile was found "
                    f"for platform {normalized_platform}, "
                    f"cycle {normalized_cycle}."
                ),
            )

        # ---------------------------------------------------------------------
        # Refresh from SQLite after live acquisition.
        #
        # The live manager has already validated, normalized and ingested the
        # exact real profile.
        # ---------------------------------------------------------------------

        refreshed_profile = (
            argo_engine.get_profile_series(
                platform_number=(
                    normalized_platform
                ),

                cycle_number=(
                    normalized_cycle
                ),
            )
        )

        if not refreshed_profile.get(
            "available"
        ):

            raise RuntimeError(
                "Live Argo profile was acquired successfully, "
                "but the refreshed local profile could not be read."
            )

        refreshed_profile[
            "live_acquisition"
        ] = {
            "used": True,

            "mode": "live",

            "automatic": True,

            "source": ARGO_SOURCE,

            "dataset": ARGO_DATASET,

            "acquisition": live_acquisition,
        }

        refreshed_profile[
            "scientific_rules"
        ] = {
            "pressure_unit": "dbar",

            "pressure_is_depth": False,

            "pressure_converted_to_depth": False,

            "synthetic_data": False,

            "interpolation": False,
        }

        return refreshed_profile

    except HTTPException:

        raise

    except ValueError as exc:

        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    except FileNotFoundError as exc:

        raise HTTPException(
            status_code=503,
            detail=str(exc),
        ) from exc

    except RuntimeError as exc:

        raise HTTPException(
            status_code=503,
            detail=(
                "Argo profile acquisition/query failed: "
                f"{exc}"
            ),
        ) from exc

    except Exception as exc:

        raise HTTPException(
            status_code=500,
            detail=(
                "Argo profile acquisition/query failed: "
                f"{exc}"
            ),
        ) from exc


# =============================================================================
# OCEAN POINT
# =============================================================================

@app.get(
    "/api/v1/ocean/point",
    response_model=OceanPointResponse,
)
def ocean_point(
    latitude: float = Query(
        ...,
        ge=-90.0,
        le=90.0,
        description=(
            "Requested latitude in degrees."
        ),
    ),

    longitude: float = Query(
        ...,
        ge=-180.0,
        le=180.0,
        description=(
            "Requested longitude in degrees."
        ),
    ),

    depth_m: float = Query(
        ...,
        ge=0.0,
        description=(
            "Requested HYCOM depth in meters."
        ),
    ),

    time_utc: str = Query(
        ...,
        description=(
            "Requested ocean-state time as an "
            "ISO-8601 UTC timestamp."
        ),
    ),

    argo_pressure_dbar: float | None = Query(
        default=None,
        ge=0.0,
        description=(
            "Optional requested Argo pressure in dbar."
        ),
    ),

    argo_radius_degrees: float = Query(
        default=2.0,
        gt=0.0,
        le=20.0,
        description=(
            "Argo search radius in geographic degrees."
        ),
    ),
) -> dict[str, Any]:

    try:

        normalized_time_utc = (
            validate_time_utc(
                time_utc
            )
        )

        result = engine.query(
            latitude=float(
                latitude
            ),

            longitude=float(
                longitude
            ),

            depth_m=float(
                depth_m
            ),

            time_utc=normalized_time_utc,

            argo_pressure_dbar=(
                None
                if argo_pressure_dbar
                is None
                else float(
                    argo_pressure_dbar
                )
            ),

            argo_radius_degrees=float(
                argo_radius_degrees
            ),
        )

        result["api"] = {
            "version": "1.0",

            "endpoint": (
                "/api/v1/ocean/point"
            ),

            "live_acquisition_enabled": True,

            "synthetic_data": False,

            "interpolation": False,
        }

        return result

    except ValueError as exc:

        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    except FileNotFoundError as exc:

        raise HTTPException(
            status_code=503,
            detail=str(exc),
        ) from exc

    except RuntimeError as exc:

        raise HTTPException(
            status_code=503,
            detail=(
                "Scientific data acquisition/query failed: "
                f"{exc}"
            ),
        ) from exc

    except Exception as exc:

        raise HTTPException(
            status_code=500,
            detail=(
                "Scientific query failed: "
                f"{exc}"
            ),
        ) from exc


# =============================================================================
# OCEAN SLICE
# =============================================================================

@app.get(
    "/api/v1/ocean/slice",
)
def ocean_slice(
    latitude_min: float = Query(
        ...,
        ge=-90.0,
        le=90.0,
    ),

    latitude_max: float = Query(
        ...,
        ge=-90.0,
        le=90.0,
    ),

    longitude_min: float = Query(
        ...,
        ge=-180.0,
        le=180.0,
    ),

    longitude_max: float = Query(
        ...,
        ge=-180.0,
        le=180.0,
    ),

    depth_m: float = Query(
        ...,
        ge=0.0,
    ),

    time_utc: str = Query(
        ...,
    ),

    variable: str = Query(
        default="TEMP",
    ),
) -> dict[str, Any]:

    try:

        normalized_time_utc = (
            validate_time_utc(
                time_utc
            )
        )

        result = (
            slice_engine.query_dict(
                latitude_min=float(
                    latitude_min
                ),

                latitude_max=float(
                    latitude_max
                ),

                longitude_min=float(
                    longitude_min
                ),

                longitude_max=float(
                    longitude_max
                ),

                depth_m=float(
                    depth_m
                ),

                time_utc=normalized_time_utc,

                variable=str(
                    variable
                ).strip().upper(),
            )
        )

        result["api"] = {
            "version": "1.0",

            "endpoint": (
                "/api/v1/ocean/slice"
            ),

            "live_acquisition_enabled": False,

            "synthetic_data": False,

            "interpolation": False,

            "local_chunk_backed": True,
        }

        return result

    except ValueError as exc:

        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    except LookupError as exc:

        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc

    except FileNotFoundError as exc:

        raise HTTPException(
            status_code=503,
            detail=str(exc),
        ) from exc

    except RuntimeError as exc:

        raise HTTPException(
            status_code=503,
            detail=(
                "HYCOM slice query failed: "
                f"{exc}"
            ),
        ) from exc

    except Exception as exc:

        raise HTTPException(
            status_code=500,
            detail=(
                "HYCOM slice query failed: "
                f"{exc}"
            ),
        ) from exc


# =============================================================================
# LOCAL DEVELOPMENT SERVER
# =============================================================================

if __name__ == "__main__":

    import uvicorn

    uvicorn.run(
        "app.api:app",
        host="127.0.0.1",
        port=8001,
        reload=False,
    )