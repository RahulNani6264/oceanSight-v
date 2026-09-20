
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware

from .argo_live_manager import ArgoLiveManager
from .argo_query import ArgoQueryEngine
from .navigation_astar import NavigationRouteEngine
from .navigation_models import NavigationRequest, NavigationResult
from .ocean_3d_query import Ocean3DQueryEngine
from .ocean_bathymetry import OceanBathymetryEngine
from .ocean_context import OceanContextEngine
from .ocean_data import OceanDataEngine
from .ocean_geometry import OceanGeometryEngine
from .ocean_regions import OceanRegionEngine
from .ocean_sensors import OceanSensorEngine
from .ocean_slice import OceanSliceEngine
from .ocean_tiles import OceanTileEngine
from .ocean_variables import (
    get_variable_catalog,
    get_variable_definition,
    normalize_variable_name,
)
from .ocean_volume import OceanVolumeEngine
from .provider_registry import catalog_with_providers, provider_for
from .schemas import (
    ArgoProfileDiscoveryResponse,
    ArgoProfileSeries,
    HealthResponse,
    OceanPointResponse,
    RootResponse,
)

try:
    from .ocean_time import OceanTimeEngine  # type: ignore[reportMissingImports]
except ImportError:  # pragma: no cover
    class OceanTimeEngine:  # type: ignore[no-redef]
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            raise RuntimeError(
                "OceanTimeEngine is unavailable because the optional "
                "source module is missing."
            )


# =============================================================================
# APPLICATION
# =============================================================================

app = FastAPI(
    title="OceanSight-V Scientific API",
    version="1.0.0",
    description=(
        "Scientific ocean data API backed by INCOIS HYCOM, INCOIS Argo, "
        "GEBCO, RECCAP2 Ocean regional masks, and the OceanSight-V "
        "4D navigation engine."
    ),
)


# =============================================================================
# CORS
# =============================================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =============================================================================
# SCIENTIFIC ENGINES
# =============================================================================

engine = Ocean3DQueryEngine()
slice_engine = OceanSliceEngine()

ocean_tile_engine = OceanTileEngine(
    slice_engine=slice_engine,
)

argo_engine = ArgoQueryEngine()
argo_live_manager = ArgoLiveManager()
ocean_sensor_engine = OceanSensorEngine()

_ocean_context_engine: OceanContextEngine | None = None
_ocean_time_engine: OceanTimeEngine | None = None
_ocean_region_engine: OceanRegionEngine | None = None
_ocean_geometry_engine: OceanGeometryEngine | None = None
_ocean_volume_engine: OceanVolumeEngine | None = None
_ocean_bathymetry_engine: OceanBathymetryEngine | None = None
_ocean_data_engine: OceanDataEngine | None = None
_navigation_engine: NavigationRouteEngine | None = None


def get_ocean_time_engine() -> OceanTimeEngine:
    """Lazily create the source-timestamp time engine."""
    global _ocean_time_engine

    if _ocean_time_engine is None:
        _ocean_time_engine = OceanTimeEngine()

    return _ocean_time_engine


def get_ocean_region_engine() -> OceanRegionEngine:
    """Lazily create the real ocean-region resolver."""
    global _ocean_region_engine

    if _ocean_region_engine is None:
        _ocean_region_engine = OceanRegionEngine()

    return _ocean_region_engine


def get_ocean_geometry_engine() -> OceanGeometryEngine:
    """Lazily create the exact source-mask ocean geometry engine."""
    global _ocean_geometry_engine

    if _ocean_geometry_engine is None:
        _ocean_geometry_engine = OceanGeometryEngine()

    return _ocean_geometry_engine


def get_ocean_volume_engine() -> OceanVolumeEngine:
    """Lazily create the real multi-depth ocean-volume engine."""
    global _ocean_volume_engine

    if _ocean_volume_engine is None:
        _ocean_volume_engine = OceanVolumeEngine(
            slice_engine=slice_engine,
            geometry_engine=get_ocean_geometry_engine(),
        )

    return _ocean_volume_engine


def get_ocean_bathymetry_engine() -> OceanBathymetryEngine:
    """Lazily create the real bathymetry engine."""
    global _ocean_bathymetry_engine

    if _ocean_bathymetry_engine is None:
        _ocean_bathymetry_engine = OceanBathymetryEngine(
            geometry_engine=get_ocean_geometry_engine(),
        )

    return _ocean_bathymetry_engine


def get_ocean_data_engine() -> OceanDataEngine:
    """Lazily create the unified scientific data router."""
    global _ocean_data_engine

    if _ocean_data_engine is None:
        _ocean_data_engine = OceanDataEngine(
            volume_engine=get_ocean_volume_engine(),
            bathymetry_engine=get_ocean_bathymetry_engine(),
            geometry_engine=get_ocean_geometry_engine(),
        )

    return _ocean_data_engine


def get_ocean_context_engine() -> OceanContextEngine:
    """Lazily create the unified ocean/block context engine."""
    global _ocean_context_engine

    if _ocean_context_engine is None:
        _ocean_context_engine = OceanContextEngine(
            region_engine=get_ocean_region_engine(),
            geometry_engine=get_ocean_geometry_engine(),
            time_engine=get_ocean_time_engine(),
            sensor_engine=ocean_sensor_engine,
        )

    return _ocean_context_engine


def get_navigation_engine() -> NavigationRouteEngine:
    """Lazily create the verified 4D navigation engine."""
    global _navigation_engine

    if _navigation_engine is None:
        _navigation_engine = NavigationRouteEngine()

    return _navigation_engine


# =============================================================================
# PATHS AND ARGO CONSTANTS
# =============================================================================

PROJECT_ROOT = Path(__file__).resolve().parent.parent

HYCOM_TIME_CATALOG = (
    PROJECT_ROOT
    / "processed"
    / "hycom_catalog"
    / "hycom_times.json"
)

ARGO_SOURCE = "INCOIS ERDDAP"
ARGO_DATASET = "Indian_ARGO_Floats"

ARGO_SOURCE_URL = (
    "https://erddap.incois.gov.in/"
    "erddap/tabledap/"
    "Indian_ARGO_Floats.csv"
)


# =============================================================================
# VALIDATION HELPERS
# =============================================================================

def validate_time_utc(time_utc: str) -> str:
    """Validate and normalize an ISO-8601 timestamp to UTC Z notation."""
    value = str(time_utc).strip()

    if not value:
        raise ValueError("time_utc cannot be empty.")

    normalized = value

    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"

    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(
            "time_utc must be a valid ISO-8601 timestamp with timezone."
        ) from exc

    if parsed.tzinfo is None:
        raise ValueError(
            "time_utc must include an explicit timezone."
        )

    return (
        parsed.astimezone(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def reduce_render_grid(
    result: dict[str, Any],
    max_cells: int,
) -> dict[str, Any]:
    """Reduce returned grids for interactive rendering without changing source queries."""
    data = result.get("data")
    if not isinstance(data, dict):
        return result

    levels = data.get("levels")
    if not isinstance(levels, list):
        return result

    for level in levels:
        if not isinstance(level, dict):
            continue

        latitudes = level.get("latitudes")
        longitudes = level.get("longitudes")
        values = level.get("values")
        water_mask = level.get("water_mask")
        missing_mask = level.get("missing_mask")

        if (
            not isinstance(latitudes, list)
            or not isinstance(longitudes, list)
            or not isinstance(values, list)
            or not latitudes
            or not longitudes
        ):
            continue

        row_step = max(1, (len(latitudes) + max_cells - 1) // max_cells)
        column_step = max(1, (len(longitudes) + max_cells - 1) // max_cells)
        reduced_latitudes = []
        reduced_longitudes = []
        reduced_values = []
        reduced_water_mask = []
        reduced_missing_mask = []

        for row_start in range(0, len(latitudes), row_step):
            row_end = min(len(latitudes), row_start + row_step)
            row_result = []
            row_water = []
            row_missing = []

            for column_start in range(0, len(longitudes), column_step):
                column_end = min(len(longitudes), column_start + column_step)
                block_values = []
                has_water = False

                for row in range(row_start, row_end):
                    for column in range(column_start, column_end):
                        is_water = (
                            not isinstance(water_mask, list)
                            or not isinstance(water_mask[row], list)
                            or water_mask[row][column] is not False
                        )
                        is_missing = (
                            isinstance(missing_mask, list)
                            and isinstance(missing_mask[row], list)
                            and missing_mask[row][column] is True
                        )
                        has_water = has_water or is_water
                        value = values[row][column] if isinstance(values[row], list) else None

                        if is_water and not is_missing and isinstance(value, (int, float)):
                            block_values.append(value)

                row_result.append(
                    sum(block_values) / len(block_values)
                    if block_values
                    else None
                )
                row_water.append(has_water)
                row_missing.append(not block_values)

            reduced_latitudes.append(
                latitudes[
                    min(
                        row_start + (row_end - row_start) // 2,
                        len(latitudes) - 1,
                    )
                ]
            )
            reduced_values.append(row_result)
            reduced_water_mask.append(row_water)
            reduced_missing_mask.append(row_missing)

        for column_start in range(0, len(longitudes), column_step):
            column_end = min(len(longitudes), column_start + column_step)
            reduced_longitudes.append(
                longitudes[
                    min(
                        column_start + (column_end - column_start) // 2,
                        len(longitudes) - 1,
                    )
                ]
            )

        level["latitudes"] = reduced_latitudes
        level["longitudes"] = reduced_longitudes
        level["values"] = reduced_values
        level["water_mask"] = reduced_water_mask
        level["missing_mask"] = reduced_missing_mask
        level["valid_value_count"] = sum(
            1
            for row in reduced_values
            for value in row
            if value is not None
        )

    grid = data.get("grid")
    if isinstance(grid, dict) and levels:
        grid["latitude_count"] = len(levels[0].get("latitudes", []))
        grid["longitude_count"] = len(levels[0].get("longitudes", []))
        grid["point_count"] = (
            grid["latitude_count"] * grid["longitude_count"]
        )
        grid["source_grid_reduced"] = True

    result["render_grid_size"] = max_cells
    return result


def validate_bbox(
    latitude_min: float,
    latitude_max: float,
    longitude_min: float,
    longitude_max: float,
) -> dict[str, float]:
    """Validate and normalize a geographic bounding box."""
    values = {
        "latitude_min": float(latitude_min),
        "latitude_max": float(latitude_max),
        "longitude_min": float(longitude_min),
        "longitude_max": float(longitude_max),
    }

    if values["latitude_min"] > values["latitude_max"]:
        raise ValueError(
            "latitude_min cannot exceed latitude_max."
        )

    if values["longitude_min"] > values["longitude_max"]:
        raise ValueError(
            "longitude_min cannot exceed longitude_max."
        )

    return values


def parse_depths(value: str | None) -> list[float] | None:
    """Parse comma-separated depth values."""
    if value is None or not str(value).strip():
        return None

    try:
        depths = [
            float(part.strip())
            for part in str(value).split(",")
            if part.strip()
        ]
    except ValueError as exc:
        raise ValueError(
            "Depth values must be a comma-separated numeric list."
        ) from exc

    if not depths:
        raise ValueError("At least one depth must be supplied.")

    if any(depth < 0 for depth in depths):
        raise ValueError("Depth values cannot be negative.")

    return depths


# =============================================================================
# ROOT
# =============================================================================

@app.get("/", response_model=RootResponse)
def root() -> dict[str, Any]:
    return {
        "name": "OceanSight-V",
        "service": "Scientific Ocean Data API",
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
                "dataset": "GEBCO",
            },
            "ocean_regions": {
                "provider": "RECCAP2 Ocean",
                "dataset": "RECCAP2 regional ocean masks",
            },
        },
        "scientific_units": {
            "HYCOM_depth": "m",
            "ARGO_pressure": "dbar",
            "ARGO_temperature": "degree_Celsius",
            "ARGO_salinity": "PSU",
            "GEBCO_elevation": "m",
        },
        "scientific_rules": {
            "argo_pressure_converted_to_depth": False,
            "synthetic_data": False,
            "interpolation": False,
            "ocean_region_heuristics": False,
        },
    }


# =============================================================================
# HEALTH
# =============================================================================

@app.get("/api/v1/health", response_model=HealthResponse)
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
            "ocean_region_resolver": "enabled",
            "live_hycom_acquisition": "enabled",
            "live_argo_acquisition": "enabled",
            "live_gebco_acquisition": "enabled",
            "navigation_4d_astar": "enabled",
            "ocean_time_engine": "enabled",
        },
        "scientific_units": {
            "hycom_depth": "m",
            "argo_pressure": "dbar",
            "gebco_elevation": "m",
        },
    }


# =============================================================================
# OCEAN REGIONS
# =============================================================================

@app.get("/api/v1/ocean/regions")
def ocean_regions() -> dict[str, Any]:
    try:
        resolver = get_ocean_region_engine()

        return {
            "available": True,
            "oceans": resolver.list_oceans(),
            "source": {
                "provider": "RECCAP2 Ocean",
                "dataset": "RECCAP2 regional ocean masks",
            },
            "scientific_rules": {
                "synthetic_data": False,
                "interpolation": False,
            },
        }

    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Ocean-region resolver unavailable: {exc}",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Ocean-region listing failed: {exc}",
        ) from exc


@app.get("/api/v1/ocean/identify")
def ocean_identify(
    latitude: float = Query(..., ge=-90.0, le=90.0),
    longitude: float = Query(..., ge=-180.0, le=180.0),
) -> dict[str, Any]:
    try:
        result = get_ocean_region_engine().identify_dict(
            latitude=float(latitude),
            longitude=float(longitude),
        )

        result["api"] = {
            "version": "1.0",
            "endpoint": "/api/v1/ocean/identify",
            "synthetic_data": False,
            "interpolation": False,
        }

        return result

    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Ocean-region identification failed: {exc}",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Ocean-region identification failed: {exc}",
        ) from exc


# =============================================================================
# OCEAN GEOMETRY
# =============================================================================

@app.get("/api/v1/ocean/boundary")
def ocean_boundary(
    ocean: str = Query(..., min_length=1),
) -> dict[str, Any]:
    try:
        result = get_ocean_geometry_engine().boundary_dict(
            ocean=ocean,
        )

        result["api"] = {
            "version": "1.1",
            "endpoint": "/api/v1/ocean/boundary",
            "synthetic_data": False,
            "interpolation": False,
        }

        return result

    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Ocean-boundary geometry unavailable: {exc}",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Ocean-boundary geometry generation failed: {exc}",
        ) from exc


# =============================================================================
# BATHYMETRY
# =============================================================================

@app.get("/api/v1/ocean/bathymetry")
def ocean_bathymetry(
    ocean: str = Query(..., min_length=1),
    latitude_min: float = Query(..., ge=-90.0, le=90.0),
    latitude_max: float = Query(..., ge=-90.0, le=90.0),
    longitude_min: float = Query(..., ge=-180.0, le=180.0),
    longitude_max: float = Query(..., ge=-180.0, le=180.0),
) -> dict[str, Any]:
    try:
        bbox = validate_bbox(
            latitude_min,
            latitude_max,
            longitude_min,
            longitude_max,
        )

        result = get_ocean_bathymetry_engine().build_surface(
            ocean=ocean,
            **bbox,
        )

        result["api"] = {
            "version": "3.0",
            "endpoint": "/api/v1/ocean/bathymetry",
            "synthetic_data": False,
            "interpolation": False,
        }

        return result

    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Bathymetry scientific engine unavailable: {exc}",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Bathymetry query failed: {exc}",
        ) from exc


# =============================================================================
# OCEAN VOLUME
# =============================================================================

@app.get("/api/v1/ocean/volume")
def ocean_volume(
    ocean: str = Query(..., min_length=1),
    latitude_min: float = Query(..., ge=-90.0, le=90.0),
    latitude_max: float = Query(..., ge=-90.0, le=90.0),
    longitude_min: float = Query(..., ge=-180.0, le=180.0),
    longitude_max: float = Query(..., ge=-180.0, le=180.0),
    time_utc: str = Query(...),
    variable: str = Query(default="TEMP"),
    depth_m: str | None = Query(default=None),
) -> dict[str, Any]:
    try:
        bbox = validate_bbox(
            latitude_min,
            latitude_max,
            longitude_min,
            longitude_max,
        )

        result = get_ocean_volume_engine().build_volume(
            ocean=ocean,
            **bbox,
            time_utc=validate_time_utc(time_utc),
            variable=str(variable).strip().upper(),
            depths_m=parse_depths(depth_m),
        )

        result["api"] = {
            "version": "2.0",
            "endpoint": "/api/v1/ocean/volume",
            "synthetic_data": False,
            "interpolation": False,
        }

        return result

    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Ocean-volume scientific engine unavailable: {exc}",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Ocean-volume query failed: {exc}",
        ) from exc


# =============================================================================
# UNIFIED OCEAN DATA
# =============================================================================

@app.get("/api/v1/ocean/data")
async def ocean_data(
    mode: str = Query(default="ocean"),
    ocean: str | None = Query(default=None),
    latitude: float | None = Query(default=None, ge=-90.0, le=90.0),
    longitude: float | None = Query(default=None, ge=-180.0, le=180.0),
    radius_km: float = Query(default=50.0, gt=0.0, le=2000.0),
    time_utc: str = Query(...),
    variable: str = Query(default="temperature"),
    depths_m: str | None = Query(default=None),
    render_grid_size: int | None = Query(default=None, ge=16, le=256),
) -> dict[str, Any]:
    try:
        result = await get_ocean_data_engine().build_data(
            mode=mode,
            ocean=ocean,
            latitude=None if latitude is None else float(latitude),
            longitude=None if longitude is None else float(longitude),
            radius_km=float(radius_km),
            time_utc=validate_time_utc(time_utc),
            variable=normalize_variable_name(variable),
            depths_m=parse_depths(depths_m),
        )

        if render_grid_size is not None:
            reduce_render_grid(result, render_grid_size)

        result["api"] = {
            "version": "1.0",
            "endpoint": "/api/v1/ocean/data",
            "synthetic_data": False,
            "interpolation": False,
        }

        return result

    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Unified scientific-data engine unavailable: {exc}",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Unified scientific-data query failed: {exc}",
        ) from exc


# =============================================================================
# GLOBAL OCEAN DATA
# =============================================================================

@app.get("/api/v1/ocean/global")
async def ocean_global(
    time_utc: str = Query(...),
    variable: str = Query(default="temperature"),
    latitude_min: float = Query(-80.0, ge=-90.0, le=90.0),
    latitude_max: float = Query(80.0, ge=-90.0, le=90.0),
    longitude_min: float = Query(-180.0, ge=-180.0, le=180.0),
    longitude_max: float = Query(180.0, ge=-180.0, le=180.0),
    depth_m: float | None = Query(default=None, ge=0.0),
    ocean: str | None = Query(default=None),
) -> dict[str, Any]:
    try:
        bbox = validate_bbox(
            latitude_min,
            latitude_max,
            longitude_min,
            longitude_max,
        )

        result = await get_ocean_data_engine().build_data(
            mode="ocean",
            ocean=ocean,
            latitude=None,
            longitude=None,
            radius_km=50.0,
            time_utc=validate_time_utc(time_utc),
            variable=normalize_variable_name(variable),
            depths_m=None if depth_m is None else [float(depth_m)],
            bbox=bbox,
        )

        result["api"] = {
            "version": "1.0",
            "endpoint": "/api/v1/ocean/global",
            "synthetic_data": False,
            "interpolation": False,
        }

        return result

    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Global ocean scientific engine unavailable: {exc}",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Global ocean query failed: {exc}",
        ) from exc


# =============================================================================
# VARIABLE CATALOG
# =============================================================================

@app.get("/api/v1/ocean/variables")
def ocean_variables(
    variable: str | None = Query(default=None),
) -> dict[str, Any]:
    try:
        if variable is None:
            return {
                "available": True,
                "variables": catalog_with_providers(),
                "scientific_rules": {
                    "synthetic_data": False,
                    "interpolation": False,
                },
            }

        normalized = normalize_variable_name(variable)

        return {
            "available": True,
            "variable": get_variable_definition(normalized),
            "provider": provider_for(normalized),
            "scientific_rules": {
                "synthetic_data": False,
                "interpolation": False,
            },
        }

    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# =============================================================================
# TIME ENDPOINTS
# =============================================================================

@app.get("/api/v1/ocean/time-window")
def ocean_time_window(
    reference_time_utc: str | None = Query(default=None),
    past_hours: float = Query(default=24.0, ge=0.0, le=720.0),
    future_hours: float = Query(default=24.0, ge=0.0, le=720.0),
) -> dict[str, Any]:
    try:
        normalized_reference = (
            None
            if reference_time_utc is None
            else validate_time_utc(reference_time_utc)
        )

        result = get_ocean_time_engine().window(
            reference_time_utc=normalized_reference,
            past_hours=float(past_hours),
            future_hours=float(future_hours),
        )

        result["api"] = {
            "version": "1.0",
            "endpoint": "/api/v1/ocean/time-window",
            "synthetic_data": False,
            "interpolation": False,
        }

        return result

    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Ocean time engine unavailable: {exc}",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Ocean time-window query failed: {exc}",
        ) from exc


@app.get("/api/v1/ocean/time-range")
def ocean_time_range(
    start_time_utc: str = Query(...),
    end_time_utc: str = Query(...),
) -> dict[str, Any]:
    try:
        normalized_start = validate_time_utc(start_time_utc)
        normalized_end = validate_time_utc(end_time_utc)

        result = get_ocean_time_engine().range(
            start_time_utc=normalized_start,
            end_time_utc=normalized_end,
        )

        result["api"] = {
            "version": "1.0",
            "endpoint": "/api/v1/ocean/time-range",
            "synthetic_data": False,
            "interpolation": False,
        }

        return result

    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Ocean time engine unavailable: {exc}",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Ocean time-range query failed: {exc}",
        ) from exc


# =============================================================================
# SENSOR ENDPOINTS
# =============================================================================

@app.get("/api/v1/ocean/sensors")
def ocean_sensors(
    latitude: float = Query(..., ge=-90.0, le=90.0),
    longitude: float = Query(..., ge=-180.0, le=180.0),
    radius_km: float = Query(default=100.0, gt=0.0, le=2000.0),
    time_utc: str | None = Query(default=None),
    sensor_type: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
) -> dict[str, Any]:
    try:
        normalized_time = (
            None
            if time_utc is None
            else validate_time_utc(time_utc)
        )

        sensors = ocean_sensor_engine.discover_local(
            latitude=float(latitude),
            longitude=float(longitude),
            radius_km=float(radius_km),
            time_utc=normalized_time,
            limit=int(limit),
        )

        sensors = ocean_sensor_engine.filter_sensor_type(
            sensors,
            sensor_type=sensor_type,
        )[: int(limit)]

        return {
            "available": bool(sensors),
            "sensors": sensors,
            "sensor_count": len(sensors),
            "request": {
                "latitude": float(latitude),
                "longitude": float(longitude),
                "radius_km": float(radius_km),
                "time_utc": normalized_time,
                "sensor_type": sensor_type,
                "limit": int(limit),
            },
            "sensor_types": ocean_sensor_engine.sensor_types(),
            "source": {
                "verified_connected_sources": [
                    {
                        "sensor_type": "argo_float",
                        "provider": "INCOIS ERDDAP",
                        "dataset": "Indian_ARGO_Floats",
                    }
                ],
            },
            "scientific_rules": {
                "synthetic_data": False,
                "interpolation": False,
                "great_circle_radius_filter": True,
                "argo_pressure_unit": "dbar",
                "argo_pressure_is_depth": False,
                "argo_pressure_to_depth_conversion": False,
            },
        }

    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Ocean sensor discovery failed: {exc}",
        ) from exc


@app.get("/api/v1/ocean/sensor")
def ocean_sensor(
    platform_number: str = Query(..., min_length=1),
    cycle_number: int = Query(..., ge=0),
) -> dict[str, Any]:
    try:
        normalized_platform = str(platform_number).strip()
        normalized_cycle = int(cycle_number)

        result = argo_engine.get_profile_series(
            platform_number=normalized_platform,
            cycle_number=normalized_cycle,
        )

        if not result.get("available"):
            raise HTTPException(
                status_code=404,
                detail=(
                    "No real Argo sensor profile was found for "
                    f"platform {normalized_platform}, cycle {normalized_cycle}."
                ),
            )

        result["api"] = {
            "version": "1.0",
            "endpoint": "/api/v1/ocean/sensor",
            "synthetic_data": False,
            "interpolation": False,
        }

        result["sensor"] = {
            "sensor_id": (
                f"argo:{normalized_platform}:{normalized_cycle}"
            ),
            "sensor_type": "argo_float",
            "platform_number": normalized_platform,
            "cycle_number": normalized_cycle,
            "position_semantics": {
                "latitude_longitude": "real profile location from source",
                "pressure_unit": "dbar",
                "pressure_is_depth": False,
                "pressure_to_depth_conversion_performed": False,
            },
        }

        return result

    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Ocean sensor profile query failed: {exc}",
        ) from exc


@app.get("/api/v1/ocean/sensor-types")
def ocean_sensor_types() -> dict[str, Any]:
    return {
        "sensor_types": ocean_sensor_engine.sensor_types(),
        "scientific_rules": {
            "synthetic_data": False,
            "interpolation": False,
        },
    }


# =============================================================================
# HYCOM TIMES
# =============================================================================

@app.get("/api/v1/hycom/times")
def hycom_times(
    time_utc: str | None = Query(default=None),
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

        with HYCOM_TIME_CATALOG.open("r", encoding="utf-8") as file:
            catalog = json.load(file)

        if not isinstance(catalog, dict):
            raise HTTPException(
                status_code=503,
                detail="HYCOM time catalog has an invalid format.",
            )

        if time_utc is None:
            return {
                "api": {
                    "version": "1.0",
                    "endpoint": "/api/v1/hycom/times",
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

        normalized_time = validate_time_utc(time_utc)
        records = catalog.get("times", [])

        if not isinstance(records, list):
            raise HTTPException(
                status_code=503,
                detail="HYCOM time catalog contains an invalid times collection.",
            )

        exact_match = next(
            (
                record
                for record in records
                if isinstance(record, dict)
                and record.get("time_utc") == normalized_time
            ),
            None,
        )

        base = {
            "api": {
                "version": "1.0",
                "endpoint": "/api/v1/hycom/times",
                "synthetic_data": False,
                "interpolation": False,
            },
            "source": {
                "provider": "INCOIS",
                "dataset": "RSMC HYCOM",
                "service": "THREDDS OPeNDAP",
            },
            "requested_time_utc": normalized_time,
            "scientific_rules": {
                "exact_time_match": True,
                "interpolation": False,
                "synthetic_data": False,
            },
        }

        if exact_match is None:
            return {
                **base,
                "available": False,
                "actual_time_utc": None,
                "time": None,
            }

        return {
            **base,
            "available": True,
            "actual_time_utc": exact_match.get("time_utc"),
            "time": exact_match,
        }

    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"HYCOM time catalog contains invalid JSON: {exc}",
        ) from exc
    except OSError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Unable to read HYCOM time catalog: {exc}",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"HYCOM time discovery API failed: {exc}",
        ) from exc


# =============================================================================
# OCEAN CONTEXT
# =============================================================================

@app.get("/api/v1/ocean/context")
def ocean_context(
    mode: str = Query(default="ocean"),
    ocean: str | None = Query(default=None),
    latitude: float | None = Query(default=None, ge=-90.0, le=90.0),
    longitude: float | None = Query(default=None, ge=-180.0, le=180.0),
    radius_km: float = Query(default=50.0, gt=0.0, le=2000.0),
    variable: str = Query(default="TEMP"),
    reference_time_utc: str | None = Query(default=None),
    past_hours: float = Query(default=24.0, ge=0.0, le=720.0),
    future_hours: float = Query(default=24.0, ge=0.0, le=720.0),
    include_sensors: bool = Query(default=True),
    sensor_limit: int = Query(default=100, ge=1, le=1000),
) -> dict[str, Any]:
    try:
        normalized_reference = (
            None
            if reference_time_utc is None
            else validate_time_utc(reference_time_utc)
        )

        result = get_ocean_context_engine().build_context(
            mode=mode,
            ocean=ocean,
            latitude=None if latitude is None else float(latitude),
            longitude=None if longitude is None else float(longitude),
            radius_km=float(radius_km),
            variable=normalize_variable_name(variable),
            reference_time_utc=normalized_reference,
            past_hours=float(past_hours),
            future_hours=float(future_hours),
            include_sensors=bool(include_sensors),
            sensor_limit=int(sensor_limit),
        )

        result["api"] = {
            "version": "1.0",
            "endpoint": "/api/v1/ocean/context",
            "synthetic_data": False,
            "interpolation": False,
        }

        return result

    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Unified ocean context unavailable: {exc}",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Unified ocean context query failed: {exc}",
        ) from exc


# =============================================================================
# NAVIGATION
# =============================================================================

@app.post("/api/v1/navigation/route", response_model=NavigationResult)
def navigation_route(
    request: NavigationRequest,
) -> NavigationResult:
    try:
        return get_navigation_engine().route(request)

    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Navigation scientific engine unavailable: {exc}",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Navigation route calculation failed: {exc}",
        ) from exc


# =============================================================================
# ARGO PROFILE HELPERS
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


@app.get(
    "/api/v1/argo/profiles",
    response_model=ArgoProfileDiscoveryResponse,
)
def argo_profiles(
    latitude: float = Query(..., ge=-90.0, le=90.0),
    longitude: float = Query(..., ge=-180.0, le=180.0),
    radius_degrees: float = Query(default=5.0, gt=0.0, le=20.0),
    time_utc: str | None = Query(default=None),
    platform_number: str | None = Query(default=None),
    cycle_number: int | None = Query(default=None, ge=0),
    limit: int = Query(default=100, ge=1, le=1000),
) -> dict[str, Any]:
    try:
        normalized_time = (
            None
            if time_utc is None
            else validate_time_utc(time_utc)
        )

        normalized_platform = (
            None
            if platform_number is None
            else str(platform_number).strip()
        )

        normalized_cycle = (
            None
            if cycle_number is None
            else int(cycle_number)
        )

        local_result = _local_argo_discovery(
            latitude=float(latitude),
            longitude=float(longitude),
            radius_degrees=float(radius_degrees),
            time_utc=normalized_time,
            platform_number=normalized_platform,
            cycle_number=normalized_cycle,
            limit=int(limit),
        )

        profiles = local_result.get("profiles", [])
        acquisition: dict[str, Any]

        if not profiles:
            live_result = argo_live_manager.discover_profiles(
                latitude=float(latitude),
                longitude=float(longitude),
                radius_degrees=float(radius_degrees),
                time_utc=normalized_time,
                time_window_days=30.0,
                limit=int(limit),
            )

            profiles = live_result.get("profiles", [])

            acquisition = {
                "mode": "live",
                "automatic": True,
                "source": ARGO_SOURCE,
                "dataset": ARGO_DATASET,
                "available": bool(profiles),
            }
        else:
            acquisition = {
                "mode": "local",
                "automatic": False,
                "source": ARGO_SOURCE,
                "dataset": ARGO_DATASET,
                "available": True,
            }

        if normalized_platform:
            profiles = [
                profile
                for profile in profiles
                if str(profile.get("platform_number")).strip()
                == normalized_platform
            ]

        if normalized_cycle is not None:
            profiles = [
                profile
                for profile in profiles
                if int(profile.get("cycle_number")) == normalized_cycle
            ]

        profiles = profiles[: int(limit)]

        summaries = [
            {
                "platform_number": str(profile.get("platform_number")),
                "cycle_number": int(profile.get("cycle_number")),
                "direction": profile.get("direction"),
                "profile_time_utc": profile.get("profile_time_utc"),
                "latitude": profile.get("latitude"),
                "longitude": profile.get("longitude"),
                "source_dataset": ARGO_DATASET,
                "source": ARGO_SOURCE,
                "available": True,
            }
            for profile in profiles
        ]

        return {
            "available": bool(summaries),
            "source": ARGO_SOURCE,
            "dataset": ARGO_DATASET,
            "request": {
                "latitude": float(latitude),
                "longitude": float(longitude),
                "radius_degrees": float(radius_degrees),
                "time_utc": normalized_time,
                "platform_number": normalized_platform,
                "cycle_number": normalized_cycle,
                "limit": int(limit),
            },
            "profiles": summaries,
            "profile_count": len(summaries),
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
                "storage": "local SQLite or live INCOIS ERDDAP",
                "synthetic_data": False,
                "interpolation": False,
            },
        }

    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Argo profile discovery failed: {exc}",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Argo profile discovery failed: {exc}",
        ) from exc


@app.get(
    "/api/v1/argo/profile",
    response_model=ArgoProfileSeries,
)
def argo_profile(
    platform_number: str = Query(..., min_length=1),
    cycle_number: int = Query(..., ge=0),
) -> dict[str, Any]:
    try:
        normalized_platform = str(platform_number).strip()
        normalized_cycle = int(cycle_number)

        local_profile = argo_engine.get_profile_series(
            platform_number=normalized_platform,
            cycle_number=normalized_cycle,
        )

        if local_profile.get("available"):
            local_profile["live_acquisition"] = {
                "used": False,
                "mode": "local",
                "automatic": False,
                "source": ARGO_SOURCE,
                "dataset": ARGO_DATASET,
            }
            return local_profile

        live_acquisition = argo_live_manager.acquire_profile(
            platform_number=normalized_platform,
            cycle_number=normalized_cycle,
        )

        if not live_acquisition.get("available"):
            raise HTTPException(
                status_code=404,
                detail=(
                    "No real Argo profile was found for "
                    f"platform {normalized_platform}, cycle {normalized_cycle}."
                ),
            )

        refreshed_profile = argo_engine.get_profile_series(
            platform_number=normalized_platform,
            cycle_number=normalized_cycle,
        )

        if not refreshed_profile.get("available"):
            raise RuntimeError(
                "Live Argo profile was acquired successfully, but the "
                "refreshed local profile could not be read."
            )

        refreshed_profile["live_acquisition"] = {
            "used": True,
            "mode": "live",
            "automatic": True,
            "source": ARGO_SOURCE,
            "dataset": ARGO_DATASET,
            "acquisition": live_acquisition,
        }

        refreshed_profile["scientific_rules"] = {
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
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Argo profile acquisition/query failed: {exc}",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Argo profile acquisition/query failed: {exc}",
        ) from exc


# =============================================================================
# OCEAN POINT
# =============================================================================

@app.get(
    "/api/v1/ocean/point",
    response_model=OceanPointResponse,
)
def ocean_point(
    latitude: float = Query(..., ge=-90.0, le=90.0),
    longitude: float = Query(..., ge=-180.0, le=180.0),
    depth_m: float = Query(..., ge=0.0),
    time_utc: str = Query(...),
    argo_pressure_dbar: float | None = Query(default=None, ge=0.0),
    argo_radius_degrees: float = Query(default=2.0, gt=0.0, le=20.0),
) -> dict[str, Any]:
    try:
        result = engine.query(
            latitude=float(latitude),
            longitude=float(longitude),
            depth_m=float(depth_m),
            time_utc=validate_time_utc(time_utc),
            argo_pressure_dbar=(
                None
                if argo_pressure_dbar is None
                else float(argo_pressure_dbar)
            ),
            argo_radius_degrees=float(argo_radius_degrees),
        )

        result["api"] = {
            "version": "1.0",
            "endpoint": "/api/v1/ocean/point",
            "live_acquisition_enabled": True,
            "synthetic_data": False,
            "interpolation": False,
        }

        return result

    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Scientific data acquisition/query failed: {exc}",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Scientific query failed: {exc}",
        ) from exc


# =============================================================================
# OCEAN SLICE
# =============================================================================

@app.get("/api/v1/ocean/slice")
def ocean_slice(
    latitude_min: float = Query(..., ge=-90.0, le=90.0),
    latitude_max: float = Query(..., ge=-90.0, le=90.0),
    longitude_min: float = Query(..., ge=-180.0, le=180.0),
    longitude_max: float = Query(..., ge=-180.0, le=180.0),
    depth_m: float = Query(..., ge=0.0),
    time_utc: str = Query(...),
    variable: str = Query(default="TEMP"),
) -> dict[str, Any]:
    try:
        bbox = validate_bbox(
            latitude_min,
            latitude_max,
            longitude_min,
            longitude_max,
        )

        result = slice_engine.query_dict(
            **bbox,
            depth_m=float(depth_m),
            time_utc=validate_time_utc(time_utc),
            variable=str(variable).strip().upper(),
        )

        result["api"] = {
            "version": "1.0",
            "endpoint": "/api/v1/ocean/slice",
            "live_acquisition_enabled": False,
            "synthetic_data": False,
            "interpolation": False,
            "local_chunk_backed": True,
        }

        return result

    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"HYCOM slice query failed: {exc}",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"HYCOM slice query failed: {exc}",
        ) from exc


# =============================================================================
# OCEAN BINARY TILE
# =============================================================================

@app.get("/api/v1/ocean/tile")
def ocean_tile(
    level: int = Query(default=0, ge=0, le=6),
    x: int = Query(default=0, ge=0),
    y: int = Query(default=0, ge=0),
    time_utc: str = Query(...),
    variable: str = Query(default="TEMP"),
    depth_m: float = Query(default=0.0, ge=0.0),
) -> Response:
    try:
        normalized_time = validate_time_utc(time_utc)

        tile_count = 2 ** int(level)

        if int(x) >= tile_count or int(y) >= tile_count:
            raise ValueError(
                f"Tile x and y must be less than {tile_count} at level {level}."
            )

        metadata, payload = ocean_tile_engine.build_tile(
            level=int(level),
            x=int(x),
            y=int(y),
            time_utc=normalized_time,
            variable=str(variable).strip().upper(),
            depth_m=float(depth_m),
        )

        return Response(
            content=payload,
            media_type="application/octet-stream",
            headers={
                "Cache-Control": "public, max-age=300",
                "X-OceanSight-Tile-Format": "oceansight-f32-v1",
                "X-OceanSight-Tile-Level": str(metadata["level"]),
                "X-OceanSight-Tile-X": str(metadata["x"]),
                "X-OceanSight-Tile-Y": str(metadata["y"]),
            },
        )

    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Ocean tile scientific engine unavailable: {exc}",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Ocean tile query failed: {exc}",
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