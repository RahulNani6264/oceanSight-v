from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .ocean_variables import (
    get_variable_catalog,
    get_variable_definition,
    normalize_variable_name,
)


@dataclass(frozen=True)
class ProviderSpec:
    provider: str
    dataset: str
    kind: str
    status: str
    coverage: str
    notes: str


_DEFAULT = ProviderSpec(
    provider="unconfigured",
    dataset="none",
    kind="scalar",
    status="unavailable",
    coverage="unknown",
    notes=(
        "No connected real-data adapter is configured for this variable."
    ),
)


_PROVIDER_BY_VARIABLE: dict[str, ProviderSpec] = {
    "temperature": ProviderSpec(
        provider="HYCOM/INCOIS",
        dataset="RSMC_hycom",
        kind="scalar",
        status="connected",
        coverage="catalog-defined",
        notes="Real ocean temperature source.",
    ),
    "salinity": ProviderSpec(
        provider="HYCOM/INCOIS",
        dataset="RSMC_hycom",
        kind="scalar",
        status="connected",
        coverage="catalog-defined",
        notes="Real ocean salinity source.",
    ),
    "current_u": ProviderSpec(
        provider="HYCOM/INCOIS",
        dataset="RSMC_hycom",
        kind="vector-component",
        status="connected",
        coverage="catalog-defined",
        notes="Real eastward ocean-current component.",
    ),
    "current_v": ProviderSpec(
        provider="HYCOM/INCOIS",
        dataset="RSMC_hycom",
        kind="vector-component",
        status="connected",
        coverage="catalog-defined",
        notes="Real northward ocean-current component.",
    ),
    "current_speed": ProviderSpec(
        provider="derived/HYCOM",
        dataset="RSMC_hycom",
        kind="scalar-derived",
        status="connected",
        coverage="catalog-defined",
        notes=(
            "Derived from real current_u and current_v values using "
            "sqrt(UVEL^2 + VVEL^2)."
        ),
    ),
    "current_direction": ProviderSpec(
        provider="derived/HYCOM",
        dataset="RSMC_hycom",
        kind="scalar-derived",
        status="connected",
        coverage="catalog-defined",
        notes=(
            "Derived from real current_u and current_v values using "
            "atan2(VVEL, UVEL)."
        ),
    ),
    "sea_surface_height": ProviderSpec(
        provider="HYCOM/INCOIS",
        dataset="RSMC_hycom",
        kind="scalar",
        status="connected",
        coverage="surface-only",
        notes="Real sea-surface-height field from HYCOM.",
    ),
}


def provider_for(variable: str) -> dict[str, Any]:
    """
    Return provider information for one variable.

    The variable is normalized through the canonical catalog first.
    Unknown or not-yet-connected catalog variables return the explicit
    unavailable provider specification.
    """
    key = normalize_variable_name(variable)
    definition = get_variable_definition(key)

    provider = _PROVIDER_BY_VARIABLE.get(key, _DEFAULT)
    result = asdict(provider)

    result["variable"] = key
    result["name"] = definition.get("name")
    result["short_name"] = definition.get("short_name")
    result["unit"] = definition.get("unit")
    result["connected"] = bool(definition.get("connected", False))
    result["live_capable"] = bool(definition.get("live_capable", False))

    if not result["connected"]:
        result["status"] = "unavailable"
        result["notes"] = (
            definition.get("source", {}).get("status_note")
            or result["notes"]
        )

    return result


def catalog_with_providers() -> list[dict[str, Any]]:
    """
    Return the complete variable catalog enriched with provider metadata.
    """
    result: list[dict[str, Any]] = []

    for item in get_variable_catalog():
        key = item.get("id")

        if not key:
            continue

        enriched = dict(item)
        enriched["provider"] = provider_for(str(key))
        result.append(enriched)

    return result