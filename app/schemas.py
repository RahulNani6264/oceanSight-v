from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


# =============================================================================
# OCEANSIGHT-V
# FRONTEND / API RESPONSE SCHEMAS
#
# Scientific rules:
#
#   HYCOM depth          -> meters
#   Argo PRES            -> dbar
#   Argo TEMP            -> degree Celsius
#   Argo PSAL            -> PSU
#   GEBCO elevation      -> meters
#
# IMPORTANT:
#
#   Argo PRES is pressure, not depth.
#   No PRES -> depth conversion is represented by this schema.
#
#   None means unavailable/missing.
#   We never use zero as a substitute for missing scientific data.
# =============================================================================


# =============================================================================
# COMMON
# =============================================================================

class ScientificFlags(BaseModel):
    """
    Global scientific integrity flags.
    """

    synthetic_data: bool = False

    interpolation: bool = False


class RequestModel(BaseModel):
    """
    Original user request.
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
        ...,
        ge=0.0,
    )

    time_utc: str

    argo_pressure_dbar: float | None = Field(
        default=None,
        ge=0.0,
    )

    argo_radius_degrees: float = Field(
        default=2.0,
        gt=0.0,
    )


# =============================================================================
# HYCOM
# =============================================================================

class HYCOMData(BaseModel):
    """
    Selected HYCOM water-column observation.
    """

    requested_latitude: float

    requested_longitude: float

    requested_depth_m: float

    requested_time_utc: str

    actual_latitude: float | None = None

    actual_longitude: float | None = None

    actual_depth_m: float | None = None

    actual_time_utc: str | None = None

    temperature_c: float | None = None

    salinity_psu: float | None = None

    u_current_m_s: float | None = None

    v_current_m_s: float | None = None

    current_speed_m_s: float | None = None

    current_direction_math_deg: float | None = None

    ssh_m: float | None = None


class HYCOMMissing(BaseModel):
    """
    Explicit missing-value status for each HYCOM field.

    True means the source did not provide a valid value.
    """

    temperature: bool = False

    salinity: bool = False

    u_current: bool = False

    v_current: bool = False

    ssh: bool = False


class WaterColumn(BaseModel):
    """
    HYCOM result.
    """

    available: bool

    source: str | None = None

    dataset: str | None = None

    source_url: str | None = None

    data: HYCOMData | None = None

    missing: HYCOMMissing = Field(
        default_factory=HYCOMMissing
    )

    selection: str | None = None

    interpolation: bool = False

    chunk_file: str | None = None

    synthetic_data: bool = False


# =============================================================================
# ARGO
# =============================================================================

class ArgoObservation(BaseModel):
    """
    One real Argo measurement.

    PRES remains in dbar.
    """

    pres_dbar: float | None = None

    pres_qc: str | None = None

    pres_adjusted_dbar: float | None = None

    pres_adjusted_qc: str | None = None

    temp_c: float | None = None

    temp_qc: str | None = None

    temp_adjusted_c: float | None = None

    temp_adjusted_qc: str | None = None

    psal_psu: float | None = None

    psal_qc: str | None = None

    psal_adjusted_psu: float | None = None

    psal_adjusted_qc: str | None = None


class ArgoProfile(BaseModel):
    """
    Identity and actual location/time of the Argo profile.
    """

    platform_number: str

    cycle_number: int

    profile_time_utc: str | None = None

    latitude: float | None = None

    longitude: float | None = None


class ArgoPressure(BaseModel):
    """
    Explicit Argo pressure metadata.

    requested_dbar and actual_dbar are both pressure values.
    Neither represents depth.
    """

    requested_dbar: float | None = None

    actual_dbar: float | None = None

    unit: str = "dbar"

    converted_to_depth: bool = False


class ArgoSourceObservation(BaseModel):
    """
    Complete source metadata attached to an observation.
    """

    platform_number: str

    cycle_number: int

    direction: str | None = None

    profile_time_utc: str | None = None

    juld_location_utc: str | None = None

    latitude: float | None = None

    longitude: float | None = None

    pres_dbar: float | None = None

    pres_qc: str | None = None

    pres_adjusted_dbar: float | None = None

    pres_adjusted_qc: str | None = None

    temp_c: float | None = None

    temp_qc: str | None = None

    temp_adjusted_c: float | None = None

    temp_adjusted_qc: str | None = None

    psal_psu: float | None = None

    psal_qc: str | None = None

    psal_adjusted_psu: float | None = None

    psal_adjusted_qc: str | None = None

    source: str

    source_dataset: str

    source_url: str

    ingested_at_utc: str | None = None


class ArgoMatching(BaseModel):
    """
    How the real Argo observation was selected.
    """

    spatial_distance_degrees: float | None = None

    pressure_difference_dbar: float | None = None

    actual_profile_time_utc: str | None = None


class ArgoAcquisition(BaseModel):
    """
    Live Argo acquisition information.
    """

    available: bool

    source: str = "INCOIS ERDDAP"

    dataset: str = "Indian_ARGO_Floats"

    automatic: bool = False

    synthetic: bool = False

    interpolation: bool = False

    pressure_converted_to_depth: bool = False

    pressure_unit: str = "dbar"

    request: dict[str, Any] = Field(
        default_factory=dict
    )

    profile: dict[str, Any] = Field(
        default_factory=dict
    )

    observation: dict[str, Any] = Field(
        default_factory=dict
    )

    matching: dict[str, Any] = Field(
        default_factory=dict
    )

    provenance: dict[str, Any] = Field(
        default_factory=dict
    )


class ArgoObservationResult(BaseModel):
    """
    Unified Argo result.

    The schema intentionally permits unavailable observations without
    inventing values.
    """

    available: bool

    requested: dict[str, Any] = Field(
        default_factory=dict
    )

    source_observation: ArgoSourceObservation | None = None

    selection: str | None = None

    profile: ArgoProfile | None = None

    observation: ArgoObservation | None = None

    pressure: ArgoPressure = Field(
        default_factory=ArgoPressure
    )

    matching: ArgoMatching | None = None

    provenance: dict[str, Any] = Field(
        default_factory=dict
    )

    live_acquisition: ArgoAcquisition | None = None


# =============================================================================
# ARGO PROFILE / DISCOVERY
# =============================================================================

class ArgoProfilePoint(BaseModel):
    """
    One point in a real Argo vertical profile.

    Scientific rule:

        pressure_dbar is PRES from the source.
        It is NOT depth.
    """

    pressure_dbar: float | None = None

    pressure_qc: str | None = None

    pressure_adjusted_dbar: float | None = None

    pressure_adjusted_qc: str | None = None

    temperature_c: float | None = None

    temperature_qc: str | None = None

    temperature_adjusted_c: float | None = None

    temperature_adjusted_qc: str | None = None

    salinity_psu: float | None = None

    salinity_qc: str | None = None

    salinity_adjusted_psu: float | None = None

    salinity_adjusted_qc: str | None = None


class ArgoProfileSeries(BaseModel):
    """
    Complete real Argo profile selected for frontend visualization.
    """

    platform_number: str

    cycle_number: int

    direction: str | None = None

    profile_time_utc: str | None = None

    juld_location_utc: str | None = None

    latitude: float | None = None

    longitude: float | None = None

    points: list[ArgoProfilePoint] = Field(
        default_factory=list
    )

    point_count: int = 0

    pressure_unit: str = "dbar"

    pressure_is_depth: bool = False


class ArgoFloatSummary(BaseModel):
    """
    Lightweight real Argo float/profile summary for map discovery.
    """

    platform_number: str

    cycle_number: int

    direction: str | None = None

    profile_time_utc: str | None = None

    latitude: float | None = None

    longitude: float | None = None

    source_dataset: str = "Indian_ARGO_Floats"

    source: str = "INCOIS ERDDAP"

    available: bool = True


class ArgoDiscoveryRequest(BaseModel):
    """
    Parameters used to discover real Argo profiles.
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

    radius_degrees: float = Field(
        default=5.0,
        gt=0.0,
        le=20.0,
    )

    time_utc: str | None = None

    platform_number: str | None = None

    cycle_number: int | None = Field(
        default=None,
        ge=0,
    )

    limit: int = Field(
        default=100,
        ge=1,
        le=1000,
    )


class ArgoProfileDiscoveryResponse(BaseModel):
    """
    Frontend-facing Argo profile/discovery response.

    All returned profiles must correspond to real source observations.
    """

    available: bool

    source: str = "INCOIS ERDDAP"

    dataset: str = "Indian_ARGO_Floats"

    request: ArgoDiscoveryRequest

    profiles: list[ArgoFloatSummary] = Field(
        default_factory=list
    )

    profile_count: int = 0

    selected_profile: ArgoProfileSeries | None = None

    scientific_rules: dict[str, Any] = Field(
        default_factory=lambda: {
            "synthetic_data": False,
            "interpolation": False,
            "pressure_unit": "dbar",
            "pressure_is_depth": False,
            "pressure_converted_to_depth": False,
        }
    )

    provenance: dict[str, Any] = Field(
        default_factory=dict
    )


# =============================================================================
# GEBCO
# =============================================================================

class GEBCORequested(BaseModel):
    """
    Requested bathymetry location.
    """

    latitude: float

    longitude: float


class GEBCOSourceGrid(BaseModel):
    """
    Actual GEBCO grid cell used.
    """

    latitude: float | None = None

    longitude: float | None = None


class Bathymetry(BaseModel):
    """
    GEBCO bathymetry result.
    """

    available: bool

    requested: GEBCORequested | None = None

    source_grid: GEBCOSourceGrid | None = None

    elevation_m: float | None = None

    missing: bool = False

    selection: str | None = None

    chunk_id: str | None = None

    source: str | None = None

    dataset: str | None = None

    source_url: str | None = None

    provenance_path: str | None = None

    depth_below_sea_level_m: float | None = None


# =============================================================================
# PHYSICAL RELATIONSHIP
# =============================================================================

class PhysicalRelationship(BaseModel):
    """
    Relationship between requested water depth and seafloor depth.
    """

    requested_depth_m: float

    seafloor_depth_m: float | None = None

    below_seafloor: bool | None = None


# =============================================================================
# PROVENANCE
# =============================================================================

class SourceProvenance(BaseModel):
    """
    Basic source identity.
    """

    source: str | None = None

    dataset: str | None = None

    source_url: str | None = None


class ArgoPressureConversion(BaseModel):
    """
    Explicit protection against pressure/depth confusion.
    """

    converted_to_depth: bool = False

    preserved_as_source_pressure: bool = True

    unit: str = "dbar"


class AcquisitionProvenance(BaseModel):
    """
    General automatic acquisition metadata.
    """

    automatic: bool = False

    available: bool = False

    dataset: str | None = None

    coordinate_catalog: str | None = None

    planned_chunks: int = 0

    downloaded: list[Any] = Field(
        default_factory=list
    )

    skipped_existing: list[Any] = Field(
        default_factory=list
    )

    synthetic_data: bool = False

    interpolation: bool = False

    full_netcdf_downloaded: bool = False

    source: str | None = None

    pressure_unit: str | None = None

    pressure_converted_to_depth: bool | None = None

    provenance: dict[str, Any] = Field(
        default_factory=dict
    )


class Provenance(BaseModel):
    """
    Complete scientific provenance.
    """

    ocean_state: SourceProvenance = Field(
        default_factory=SourceProvenance
    )

    argo: SourceProvenance = Field(
        default_factory=SourceProvenance
    )

    bathymetry: SourceProvenance = Field(
        default_factory=SourceProvenance
    )

    interpolation: bool = False

    synthetic_data: bool = False

    argo_pressure_conversion: ArgoPressureConversion = Field(
        default_factory=ArgoPressureConversion
    )

    hycom_acquisition: AcquisitionProvenance | None = None

    argo_acquisition: AcquisitionProvenance | None = None

    gebco_acquisition: AcquisitionProvenance | None = None


# =============================================================================
# API METADATA
# =============================================================================

class APIMetadata(BaseModel):
    """
    HTTP API metadata.
    """

    version: str

    endpoint: str

    live_acquisition_enabled: bool = True

    synthetic_data: bool = False

    interpolation: bool = False


# =============================================================================
# FINAL OCEAN POINT RESPONSE
# =============================================================================

class OceanPointResponse(BaseModel):
    """
    Canonical response for:

        GET /api/v1/ocean/point

    This is the frontend-facing scientific contract.
    """

    timestamp_utc: str

    request: RequestModel

    water_column: WaterColumn

    argo_observation: ArgoObservationResult

    bathymetry: Bathymetry

    physical_relationship: PhysicalRelationship

    provenance: Provenance

    api: APIMetadata | None = None


# =============================================================================
# HEALTH
# =============================================================================

class ComponentStatus(BaseModel):
    """
    Backend component availability.
    """

    hycom: str

    argo: str

    gebco: str

    live_hycom_acquisition: str

    live_argo_acquisition: str

    live_gebco_acquisition: str


class HealthResponse(BaseModel):
    """
    API health response.
    """

    status: str

    scientific_engine: str

    synthetic_data: bool = False

    interpolation: bool = False

    components: ComponentStatus

    scientific_units: dict[str, str]


# =============================================================================
# ROOT RESPONSE
# =============================================================================

class RootResponse(BaseModel):
    """
    Root API information.
    """

    name: str

    service: str

    status: str

    scientific_engine: dict[str, Any]

    sources: dict[str, Any]

    scientific_units: dict[str, str]

    scientific_rules: dict[str, Any]