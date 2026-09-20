from __future__ import annotations

from copy import deepcopy
from typing import Any


# =============================================================================
# OCEANSIGHT-V
# UNIFIED SCIENTIFIC VARIABLE CATALOG
#
# connected=True means the current backend has a verified real-data adapter.
# connected=False means the variable is part of the product catalog but its
# adapter is not yet implemented or operational in the current backend.
#
# source.field contains the actual source variable name where applicable.
# source.fields contains multiple source fields for vector/derived variables.
# =============================================================================


_HYCOM_DEPTH_LEVELS_M: list[float] = [
    0.0,
    10.0,
    50.0,
    100.0,
    250.0,
    500.0,
]


_VARIABLES: tuple[dict[str, Any], ...] = (
    {
        "id": "temperature",
        "name": "Temperature",
        "short_name": "TEMP",
        "unit": "degree_Celsius",
        "category": "ocean",
        "source": {
            "provider": "INCOIS",
            "dataset": "RSMC HYCOM",
            "field": "TEMP",
            "adapter": "OceanSliceEngine",
        },
        "connected": True,
        "live_capable": True,
        "vertical": {
            "supported": True,
            "mode": "depth_levels",
            "depth_unit": "m",
            "real_source_levels_m": _HYCOM_DEPTH_LEVELS_M,
        },
        "render": {
            "kind": "scalar",
            "color_scale": [
                "#313695",
                "#4575B4",
                "#74ADD1",
                "#ABD9E9",
                "#E0F3F8",
                "#FFFFBF",
                "#FEE090",
                "#FDAE61",
                "#F46D43",
                "#D73027",
            ],
        },
    },
    {
        "id": "salinity",
        "name": "Salinity",
        "short_name": "SALN",
        "unit": "PSU",
        "category": "ocean",
        "source": {
            "provider": "INCOIS",
            "dataset": "RSMC HYCOM",
            "field": "SALN",
            "adapter": "OceanSliceEngine",
        },
        "connected": True,
        "live_capable": True,
        "vertical": {
            "supported": True,
            "mode": "depth_levels",
            "depth_unit": "m",
            "real_source_levels_m": _HYCOM_DEPTH_LEVELS_M,
        },
        "render": {
            "kind": "scalar",
            "color_scale": [
                "#440154",
                "#482878",
                "#3E4989",
                "#31688E",
                "#26828E",
                "#35B779",
                "#6CCE59",
                "#B4DE2C",
                "#FDE725",
            ],
        },
    },
    {
        "id": "current_u",
        "name": "Eastward Current",
        "short_name": "UVEL",
        "unit": "m/s",
        "category": "ocean_current",
        "source": {
            "provider": "INCOIS",
            "dataset": "RSMC HYCOM",
            "field": "UVEL",
            "adapter": "OceanSliceEngine",
        },
        "connected": True,
        "live_capable": True,
        "vertical": {
            "supported": True,
            "mode": "depth_levels",
            "depth_unit": "m",
            "real_source_levels_m": _HYCOM_DEPTH_LEVELS_M,
        },
        "render": {
            "kind": "vector_component",
            "component": "u",
            "color_scale": [
                "#313695",
                "#4575B4",
                "#74ADD1",
                "#E0F3F8",
                "#FFFFBF",
                "#FEE090",
                "#F46D43",
                "#A50026",
            ],
        },
    },
    {
        "id": "current_v",
        "name": "Northward Current",
        "short_name": "VVEL",
        "unit": "m/s",
        "category": "ocean_current",
        "source": {
            "provider": "INCOIS",
            "dataset": "RSMC HYCOM",
            "field": "VVEL",
            "adapter": "OceanSliceEngine",
        },
        "connected": True,
        "live_capable": True,
        "vertical": {
            "supported": True,
            "mode": "depth_levels",
            "depth_unit": "m",
            "real_source_levels_m": _HYCOM_DEPTH_LEVELS_M,
        },
        "render": {
            "kind": "vector_component",
            "component": "v",
            "color_scale": [
                "#313695",
                "#4575B4",
                "#74ADD1",
                "#E0F3F8",
                "#FFFFBF",
                "#FEE090",
                "#F46D43",
                "#A50026",
            ],
        },
    },
    {
        "id": "current_speed",
        "name": "Current Speed",
        "short_name": "SPEED",
        "unit": "m/s",
        "category": "ocean_current",
        "source": {
            "type": "derived",
            "provider": "derived/HYCOM",
            "dataset": "RSMC HYCOM",
            "fields": ["UVEL", "VVEL"],
            "formula": "sqrt(UVEL^2 + VVEL^2)",
            "adapter": "OceanSliceEngine",
        },
        "connected": True,
        "live_capable": True,
        "vertical": {
            "supported": True,
            "mode": "depth_levels",
            "depth_unit": "m",
            "real_source_levels_m": _HYCOM_DEPTH_LEVELS_M,
        },
        "render": {
            "kind": "derived_scalar",
            "color_scale": [
                "#0D0887",
                "#46039F",
                "#7201A8",
                "#9C179E",
                "#BD3786",
                "#D8576B",
                "#ED7953",
                "#FB9F3A",
                "#F0F921",
            ],
        },
    },
    {
        "id": "current_direction",
        "name": "Current Direction",
        "short_name": "DIR",
        "unit": "degree",
        "category": "ocean_current",
        "source": {
            "type": "derived",
            "provider": "derived/HYCOM",
            "dataset": "RSMC HYCOM",
            "fields": ["UVEL", "VVEL"],
            "formula": "atan2(VVEL, UVEL)",
            "adapter": "OceanSliceEngine",
        },
        "connected": True,
        "live_capable": True,
        "vertical": {
            "supported": True,
            "mode": "depth_levels",
            "depth_unit": "m",
            "real_source_levels_m": _HYCOM_DEPTH_LEVELS_M,
        },
        "render": {
            "kind": "derived_direction",
            "color_scale": [
                "#440154",
                "#482878",
                "#3E4989",
                "#31688E",
                "#26828E",
                "#35B779",
                "#6CCE59",
                "#B4DE2C",
                "#FDE725",
            ],
        },
    },
    {
        "id": "sea_surface_height",
        "name": "Sea Surface Height",
        "short_name": "SSH",
        "unit": "m",
        "category": "ocean",
        "source": {
            "provider": "INCOIS",
            "dataset": "RSMC HYCOM",
            "field": "SSH",
            "adapter": "OceanSliceEngine",
        },
        "connected": True,
        "live_capable": True,
        "vertical": {
            "supported": False,
            "mode": "surface_only",
            "depth_unit": "m",
            "real_source_levels_m": [0.0],
        },
        "render": {
            "kind": "scalar",
            "color_scale": [
                "#313695",
                "#74ADD1",
                "#E0F3F8",
                "#FFFFBF",
                "#FDAE61",
                "#D73027",
            ],
        },
    },
    {
        "id": "bathymetry",
        "name": "Bathymetry",
        "short_name": "elevation",
        "unit": "m",
        "category": "bathymetry",
        "source": {
            "provider": "GEBCO",
            "dataset": "GEBCO_2026",
            "field": "elevation",
            "adapter": None,
            "status_note": "Cataloged but no verified bathymetry adapter is connected to the current tile pipeline.",
        },
        "connected": False,
        "live_capable": False,
        "vertical": {
            "supported": True,
            "mode": "seafloor",
            "depth_unit": "m",
        },
        "render": {
            "kind": "terrain",
            "color_scale": [
                "#0B1D26",
                "#123C50",
                "#155E75",
                "#1D8A99",
                "#70C1B3",
                "#D9E8A8",
                "#C7B299",
                "#8C6A5D",
            ],
        },
    },
    {
        "id": "argo_temperature",
        "name": "Argo Temperature",
        "short_name": "ARGO_TEMP",
        "unit": "degree_Celsius",
        "category": "observation",
        "source": {
            "provider": "INCOIS",
            "dataset": "Indian_ARGO_Floats",
            "field": "temperature",
            "adapter": None,
            "status_note": "Argo query services exist separately but are not connected to the global tile pipeline.",
        },
        "connected": False,
        "live_capable": False,
        "vertical": {
            "supported": True,
            "mode": "profile_pressure_levels",
            "depth_unit": "dbar",
            "scientific_note": (
                "ARGO PRES is preserved as source pressure and is not "
                "silently converted to depth."
            ),
        },
        "render": {
            "kind": "sensor_scalar",
            "color_scale": [
                "#313695",
                "#4575B4",
                "#74ADD1",
                "#E0F3F8",
                "#FFFFBF",
                "#FDAE61",
                "#D73027",
            ],
        },
    },
    {
        "id": "argo_salinity",
        "name": "Argo Salinity",
        "short_name": "ARGO_SAL",
        "unit": "PSU",
        "category": "observation",
        "source": {
            "provider": "INCOIS",
            "dataset": "Indian_ARGO_Floats",
            "field": "salinity",
            "adapter": None,
            "status_note": "Argo query services exist separately but are not connected to the global tile pipeline.",
        },
        "connected": False,
        "live_capable": False,
        "vertical": {
            "supported": True,
            "mode": "profile_pressure_levels",
            "depth_unit": "dbar",
            "scientific_note": (
                "ARGO PRES is preserved as source pressure and is not "
                "silently converted to depth."
            ),
        },
        "render": {
            "kind": "sensor_scalar",
            "color_scale": [
                "#440154",
                "#482878",
                "#3E4989",
                "#31688E",
                "#26828E",
                "#35B779",
                "#B4DE2C",
                "#FDE725",
            ],
        },
    },
    {
        "id": "argo_pressure",
        "name": "Argo Pressure",
        "short_name": "PRES",
        "unit": "dbar",
        "category": "observation",
        "source": {
            "provider": "INCOIS",
            "dataset": "Indian_ARGO_Floats",
            "field": "pressure",
            "adapter": None,
            "status_note": "Argo query services exist separately but are not connected to the global tile pipeline.",
        },
        "connected": False,
        "live_capable": False,
        "vertical": {
            "supported": True,
            "mode": "profile_pressure_levels",
            "depth_unit": "dbar",
            "scientific_note": (
                "Pressure remains dbar from the source; no silent "
                "pressure-to-depth conversion is performed."
            ),
        },
        "render": {
            "kind": "sensor_scalar",
            "color_scale": [
                "#0D0887",
                "#4C02A1",
                "#7E03A8",
                "#AA2396",
                "#CC4778",
                "#E66C5C",
                "#F99B3B",
                "#F0F921",
            ],
        },
    },
    {
        "id": "wind",
        "name": "Wind",
        "short_name": "WIND",
        "unit": "m/s",
        "category": "atmosphere",
        "source": {
            "provider": "NOAA NCEP",
            "dataset": "NCEP_Global_Best",
            "fields": ["ugrd10m", "vgrd10m"],
            "service": "public NOAA ERDDAP",
            "adapter": "OceanExternalDataEngine",
        },
        "connected": True,
        "live_capable": True,
        "vertical": {
            "supported": False,
            "mode": "surface_only",
            "depth_unit": "m",
        },
        "render": {
            "kind": "vector",
            "color_scale": [
                "#313695",
                "#74ADD1",
                "#FFFFBF",
                "#F46D43",
                "#A50026",
            ],
        },
    },
    {
        "id": "air_pressure",
        "name": "Air Pressure",
        "short_name": "MSLP",
        "unit": "hPa",
        "category": "atmosphere",
        "source": {
            "provider": "NOAA NCEP",
            "dataset": "NCEP_Global_Best",
            "field": "prmslmsl",
            "service": "public NOAA ERDDAP",
            "adapter": "OceanExternalDataEngine",
        },
        "connected": True,
        "live_capable": True,
        "vertical": {
            "supported": False,
            "mode": "surface_only",
            "depth_unit": "m",
        },
        "render": {
            "kind": "scalar",
            "color_scale": [
                "#313695",
                "#74ADD1",
                "#E0F3F8",
                "#FFFFBF",
                "#FDAE61",
                "#D73027",
            ],
        },
    },
    {
        "id": "chlorophyll",
        "name": "Chlorophyll",
        "short_name": "CHL",
        "unit": "mg/m^3",
        "category": "ocean_biogeochemistry",
        "source": {
            "provider": "NOAA NESDIS CoastWatch",
            "dataset": "noaacwNPPN20VIIRSDINEOFDaily",
            "field": "chlor_a",
            "service": "public NOAA ERDDAP",
            "adapter": "OceanExternalDataEngine",
        },
        "connected": True,
        "live_capable": True,
        "vertical": {
            "supported": False,
            "mode": "surface_only",
            "depth_unit": "m",
        },
        "render": {
            "kind": "scalar",
            "color_scale": [
                "#440154",
                "#482878",
                "#3E4989",
                "#31688E",
                "#35B779",
                "#B4DE2B",
                "#FDE725",
            ],
        },
    },
)


_ALIASES: dict[str, str] = {
    "temp": "temperature",
    "temperature": "temperature",
    "sst": "temperature",
    "sal": "salinity",
    "salinity": "salinity",
    "saln": "salinity",
    "current_u": "current_u",
    "uvel": "current_u",
    "u": "current_u",
    "eastward_current": "current_u",
    "current_v": "current_v",
    "vvel": "current_v",
    "v": "current_v",
    "northward_current": "current_v",
    "current_speed": "current_speed",
    "speed": "current_speed",
    "current_direction": "current_direction",
    "direction": "current_direction",
    "ssh": "sea_surface_height",
    "sea_surface_height": "sea_surface_height",
    "bathymetry": "bathymetry",
    "elevation": "bathymetry",
    "argo_temperature": "argo_temperature",
    "argo_temp": "argo_temperature",
    "argo_salinity": "argo_salinity",
    "argo_sal": "argo_salinity",
    "argo_pressure": "argo_pressure",
    "argo_pres": "argo_pressure",
    "pres": "argo_pressure",
    "wind": "wind",
    "mslp": "air_pressure",
    "air_pressure": "air_pressure",
    "pressure": "air_pressure",
    "chlorophyll": "chlorophyll",
    "chl": "chlorophyll",
}


def normalize_variable_name(variable: str) -> str:
    """
    Normalize a user/API variable name to its canonical catalog ID.

    Examples:
        TEMP -> temperature
        SALN -> salinity
        UVEL -> current_u
        SSH -> sea_surface_height
    """
    value = (
        str(variable)
        .strip()
        .lower()
        .replace("-", "_")
        .replace(" ", "_")
    )

    if not value:
        raise ValueError("variable cannot be empty.")

    try:
        return _ALIASES[value]
    except KeyError as exc:
        supported = ", ".join(item["id"] for item in _VARIABLES)
        raise ValueError(
            f"Unsupported variable '{variable}'. "
            f"Supported variable ids: {supported}."
        ) from exc


def get_variable_catalog() -> list[dict[str, Any]]:
    """
    Return a deep copy so callers cannot mutate the source catalog.
    """
    return deepcopy(list(_VARIABLES))


def get_variable_definition(variable: str) -> dict[str, Any]:
    """
    Return the complete definition for one normalized variable.
    """
    normalized = normalize_variable_name(variable)

    for item in _VARIABLES:
        if item["id"] == normalized:
            return deepcopy(item)

    raise ValueError(f"Variable '{variable}' is not defined in the catalog.")


def is_variable_connected(variable: str) -> bool:
    """
    Return whether the current backend has a verified adapter.
    """
    definition = get_variable_definition(variable)
    return bool(definition.get("connected", False))


def source_field_for(variable: str) -> str | None:
    """
    Return the single source field for a variable.

    Derived/vector variables may use source_fields_for() instead.
    """
    definition = get_variable_definition(variable)
    source = definition.get("source", {})

    field = source.get("field")
    return str(field) if field else None


def source_fields_for(variable: str) -> list[str]:
    """
    Return all source fields required by a variable.

    For scalar variables this returns a one-item list.
    For derived current variables it returns ['UVEL', 'VVEL'].
    """
    definition = get_variable_definition(variable)
    source = definition.get("source", {})

    fields = source.get("fields")
    if fields:
        return [str(field) for field in fields]

    field = source.get("field")
    if field:
        return [str(field)]

    return []


def variable_requires_depth(variable: str) -> bool:
    """
    Return whether depth is scientifically meaningful for the variable.
    """
    definition = get_variable_definition(variable)
    vertical = definition.get("vertical", {})
    return bool(vertical.get("supported", False))


def variable_is_surface_only(variable: str) -> bool:
    """
    Return whether the variable is defined only at the surface.
    """
    definition = get_variable_definition(variable)
    vertical = definition.get("vertical", {})
    return vertical.get("mode") == "surface_only"


def supported_depths_for(variable: str) -> list[float]:
    """
    Return the real source depth levels.

    Surface-only and non-depth variables return their declared source levels,
    or [0.0] when no explicit levels exist.
    """
    definition = get_variable_definition(variable)
    vertical = definition.get("vertical", {})

    levels = vertical.get("real_source_levels_m")
    if levels:
        return [float(level) for level in levels]

    if vertical.get("mode") in {"surface_only", "seafloor"}:
        return [0.0]

    return []
