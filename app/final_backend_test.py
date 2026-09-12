from __future__ import annotations

import json
import sys
from typing import Any

import httpx


# =============================================================================
# OCEANSIGHT-V
# FINAL BACKEND INTEGRATION VALIDATION
#
# Purpose:
#
#   Validate the complete HTTP backend contract before frontend development.
#
# Rules:
#
#   - Real scientific data only.
#   - Synthetic data must be false.
#   - Interpolation must be false.
#   - Argo pressure remains dbar.
#   - Argo pressure is never treated as depth.
#   - HYCOM requested and actual source times must match exactly where
#     an exact source time is requested.
# =============================================================================


BASE_URL = "http://127.0.0.1:8001"


class BackendTestError(RuntimeError):
    pass


def get_json(
    client: httpx.Client,
    path: str,
    params: dict[str, Any] | None = None,
) -> Any:

    response = client.get(
        f"{BASE_URL}{path}",
        params=params,
    )

    print()
    print(f"GET {response.request.url}")
    print(f"HTTP {response.status_code}")

    if response.status_code != 200:

        print(response.text[:2000])

        raise BackendTestError(
            f"Request failed: {path} "
            f"with HTTP {response.status_code}"
        )

    try:

        return response.json()

    except ValueError as exc:

        raise BackendTestError(
            f"Endpoint did not return JSON: {path}"
        ) from exc


def require(
    condition: bool,
    message: str,
) -> None:

    if not condition:

        raise BackendTestError(
            message
        )


def test_health(
    client: httpx.Client,
) -> None:

    data = get_json(
        client,
        "/api/v1/health",
    )

    require(
        data.get("status") == "ok",
        "Health status is not ok.",
    )

    require(
        data.get("scientific_engine") == "ready",
        "Scientific engine is not ready.",
    )

    require(
        data.get("synthetic_data") is False,
        "Health reports synthetic data.",
    )

    require(
        data.get("interpolation") is False,
        "Health reports interpolation.",
    )

    components = data.get(
        "components",
        {},
    )

    for name in (
        "hycom",
        "argo",
        "gebco",
        "live_hycom_acquisition",
        "live_argo_acquisition",
        "live_gebco_acquisition",
    ):

        require(
            components.get(name) == "enabled",
            f"Health component is not enabled: {name}",
        )

    print(
        "PASS: health"
    )


def test_hycom_time(
    client: httpx.Client,
) -> None:

    requested_time = (
        "2026-09-14T06:00:00Z"
    )

    data = get_json(
        client,
        "/api/v1/hycom/times",
        {
            "time_utc": requested_time,
        },
    )

    require(
        data.get("available") is True,
        "HYCOM exact time is unavailable.",
    )

    require(
        data.get(
            "requested_time_utc"
        ) == requested_time,
        "HYCOM requested time changed.",
    )

    require(
        data.get(
            "actual_time_utc"
        ) == requested_time,
        "HYCOM actual source time does not exactly match.",
    )

    rules = data.get(
        "scientific_rules",
        {},
    )

    require(
        rules.get(
            "exact_time_match"
        ) is True,
        "HYCOM exact-time flag is false.",
    )

    require(
        rules.get(
            "interpolation"
        ) is False,
        "HYCOM time discovery reports interpolation.",
    )

    require(
        rules.get(
            "synthetic_data"
        ) is False,
        "HYCOM time discovery reports synthetic data.",
    )

    time_record = data.get(
        "time",
        {},
    )

    require(
        time_record.get(
            "dataset"
        ),
        "HYCOM time record has no dataset.",
    )

    require(
        time_record.get(
            "dataset_url"
        ),
        "HYCOM time record has no source URL.",
    )

    print(
        "PASS: HYCOM exact time discovery"
    )


def test_hycom_point(
    client: httpx.Client,
) -> None:

    data = get_json(
        client,
        "/api/v1/ocean/point",
        {
            "latitude": -8.2,
            "longitude": 68.2,
            "depth_m": 100,
            "time_utc": "2026-09-10T06:00:00Z",
        },
    )

    require(
        data.get("water_column", {}).get(
            "available"
        ) is True,
        "HYCOM point is unavailable.",
    )

    water = data[
        "water_column"
    ]

    require(
        water.get(
            "synthetic_data"
        ) is False,
        "HYCOM point reports synthetic data.",
    )

    require(
        water.get(
            "interpolation"
        ) is False,
        "HYCOM point reports interpolation.",
    )

    require(
        water.get(
            "dataset"
        ),
        "HYCOM point has no dataset.",
    )

    require(
        water.get(
            "source_url"
        ),
        "HYCOM point has no source URL.",
    )

    point = water.get(
        "data",
        {},
    )

    require(
        point.get(
            "actual_time_utc"
        ) == "2026-09-10T06:00:00Z",
        "HYCOM point actual time is incorrect.",
    )

    require(
        point.get(
            "actual_depth_m"
        ) == 100.0,
        "HYCOM point actual depth is incorrect.",
    )

    require(
        point.get(
            "temperature_c"
        ) is not None,
        "HYCOM temperature is missing.",
    )

    require(
        point.get(
            "salinity_psu"
        ) is not None,
        "HYCOM salinity is missing.",
    )

    require(
        point.get(
            "u_current_m_s"
        ) is not None,
        "HYCOM U current is missing.",
    )

    require(
        point.get(
            "v_current_m_s"
        ) is not None,
        "HYCOM V current is missing.",
    )

    print(
        "PASS: HYCOM point"
    )


def test_hycom_slice(
    client: httpx.Client,
    variable: str,
    depth_m: float,
) -> None:

    data = get_json(
        client,
        "/api/v1/ocean/slice",
        {
            "latitude_min": -8.25,
            "latitude_max": -8.15,
            "longitude_min": 68.15,
            "longitude_max": 68.25,
            "depth_m": depth_m,
            "time_utc": "2026-09-10T06:00:00Z",
            "variable": variable,
        },
    )

    require(
        data.get("available") is True,
        f"{variable} slice is unavailable.",
    )

    require(
        data.get("interpolation") is False,
        f"{variable} slice reports interpolation.",
    )

    require(
        data.get("synthetic_data") is False,
        f"{variable} slice reports synthetic data.",
    )

    actual = data.get(
        "actual",
        {},
    )

    require(
        actual.get(
            "time_utc"
        ) == "2026-09-10T06:00:00Z",
        f"{variable} slice actual time is incorrect.",
    )

    variable_info = data.get(
        "variable",
        {},
    )

    require(
        variable_info.get(
            "name"
        ) == variable,
        f"{variable} slice variable name is incorrect.",
    )

    statistics = data.get(
        "statistics",
        {},
    )

    require(
        statistics.get(
            "valid_cells",
            0
        ) > 0,
        f"{variable} slice contains no valid cells.",
    )

    require(
        statistics.get(
            "missing_cells"
        ) == 0,
        f"{variable} slice unexpectedly contains missing cells.",
    )

    print(
        f"PASS: HYCOM {variable} slice"
    )


def test_argo_discovery(
    client: httpx.Client,
) -> None:

    data = get_json(
        client,
        "/api/v1/argo/profiles",
        {
            "latitude": -1.73228,
            "longitude": 85.17659,
            "radius_degrees": 0.5,
            "limit": 10,
        },
    )

    require(
        data.get("available") is True,
        "Argo discovery is unavailable.",
    )

    require(
        data.get(
            "profile_count",
            0
        ) > 0,
        "Argo discovery returned zero profiles.",
    )

    rules = data.get(
        "scientific_rules",
        {},
    )

    require(
        rules.get(
            "synthetic_data"
        ) is False,
        "Argo discovery reports synthetic data.",
    )

    require(
        rules.get(
            "interpolation"
        ) is False,
        "Argo discovery reports interpolation.",
    )

    require(
        rules.get(
            "pressure_unit"
        ) == "dbar",
        "Argo discovery pressure unit is not dbar.",
    )

    require(
        rules.get(
            "pressure_is_depth"
        ) is False,
        "Argo discovery incorrectly treats pressure as depth.",
    )

    profiles = data.get(
        "profiles",
        [],
    )

    first = profiles[0]

    require(
        first.get(
            "platform_number"
        ),
        "Argo profile has no platform number.",
    )

    require(
        first.get(
            "cycle_number"
        ) is not None,
        "Argo profile has no cycle number.",
    )

    require(
        first.get(
            "profile_time_utc"
        ),
        "Argo profile has no timestamp.",
    )

    require(
        first.get(
            "latitude"
        ) is not None,
        "Argo profile has no latitude.",
    )

    require(
        first.get(
            "longitude"
        ) is not None,
        "Argo profile has no longitude.",
    )

    print(
        "PASS: Argo profile discovery"
    )


def test_argo_profile(
    client: httpx.Client,
) -> None:

    data = get_json(
        client,
        "/api/v1/argo/profile",
        {
            "platform_number": "2900570",
            "cycle_number": 56,
        },
    )

    require(
        data.get(
            "platform_number"
        ) == "2900570",
        "Argo returned the wrong platform.",
    )

    require(
        int(
            data.get(
                "cycle_number"
            )
        ) == 56,
        "Argo returned the wrong cycle.",
    )

    require(
        data.get(
            "point_count",
            0
        ) > 0,
        "Argo profile contains no points.",
    )

    require(
        data.get(
            "pressure_unit"
        ) == "dbar",
        "Argo profile pressure unit is not dbar.",
    )

    require(
        data.get(
            "pressure_is_depth"
        ) is False,
        "Argo profile incorrectly treats pressure as depth.",
    )

    points = data.get(
        "points",
        [],
    )

    require(
        len(points) > 0,
        "Argo profile point array is empty.",
    )

    first = points[0]

    require(
        first.get(
            "pressure_dbar"
        ) is not None,
        "Argo first pressure value is missing.",
    )

    require(
        first.get(
            "temperature_c"
        ) is not None,
        "Argo first temperature is missing.",
    )

    require(
        first.get(
            "salinity_psu"
        ) is not None,
        "Argo first salinity is missing.",
    )

    print(
        "PASS: Argo complete profile"
    )


def test_openapi(
    client: httpx.Client,
) -> None:

    data = get_json(
        client,
        "/openapi.json",
    )

    paths = data.get(
        "paths",
        {},
    )

    expected_paths = [
        "/api/v1/health",
        "/api/v1/hycom/times",
        "/api/v1/ocean/point",
        "/api/v1/ocean/slice",
        "/api/v1/argo/profiles",
        "/api/v1/argo/profile",
    ]

    for path in expected_paths:

        require(
            path in paths,
            f"OpenAPI route missing: {path}",
        )

    print(
        "PASS: OpenAPI contract"
    )


def main() -> int:

    print("=" * 80)

    print(
        "OCEANSIGHT-V"
    )

    print(
        "FINAL BACKEND INTEGRATION VALIDATION"
    )

    print("=" * 80)

    try:

        with httpx.Client(
            timeout=120.0,
            follow_redirects=True,
        ) as client:

            test_health(
                client
            )

            test_hycom_time(
                client
            )

            test_hycom_point(
                client
            )

            test_hycom_slice(
                client,
                "TEMP",
                100.0,
            )

            test_hycom_slice(
                client,
                "SALN",
                100.0,
            )

            test_hycom_slice(
                client,
                "UVEL",
                100.0,
            )

            test_hycom_slice(
                client,
                "VVEL",
                100.0,
            )

            test_hycom_slice(
                client,
                "SSH",
                0.0,
            )

            test_argo_discovery(
                client
            )

            test_argo_profile(
                client
            )

            test_openapi(
                client
            )

        print()
        print("=" * 80)
        print(
            "ALL BACKEND INTEGRATION TESTS PASSED"
        )
        print("=" * 80)

        print()
        print(
            "Scientific integrity:"
        )

        print(
            "  synthetic_data = False"
        )

        print(
            "  interpolation  = False"
        )

        print(
            "  Argo PRES      = dbar"
        )

        print(
            "  PRES != depth"
        )

        print()
        print(
            "Backend status: READY FOR FRONTEND"
        )

        return 0

    except (
        httpx.HTTPError,
        BackendTestError,
    ) as exc:

        print()
        print("=" * 80)
        print(
            "BACKEND INTEGRATION TEST FAILED"
        )
        print("=" * 80)

        print()
        print(
            str(exc)
        )

        return 1

    except Exception as exc:

        print()
        print("=" * 80)
        print(
            "UNEXPECTED BACKEND TEST ERROR"
        )
        print("=" * 80)

        print()
        print(
            repr(exc)
        )

        return 1


if __name__ == "__main__":

    sys.exit(
        main()
    )