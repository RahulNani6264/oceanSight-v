
from __future__ import annotations

from .scientific_store import ScientificStore


DATASET = "incois_argo_10d_VAM"
LATITUDE = 0.5
LONGITUDE = 70.5
TIME = "2026-07-30T00:00:00Z"


def main() -> None:
    print("=" * 80)
    print("OCEANSIGHT-V")
    print("SCIENTIFIC STORE VALIDATION")
    print("=" * 80)

    store = ScientificStore()

    print()
    print("DATABASE")
    print("-" * 80)
    print(store.db_path)

    print()
    print("TOTAL OBSERVATIONS")
    print("-" * 80)

    temp_count = store.count_observations(
        dataset_id=DATASET,
        variable="TEMP",
    )

    sal_count = store.count_observations(
        dataset_id=DATASET,
        variable="SAL",
    )

    print(f"TEMP: {temp_count}")
    print(f"SAL : {sal_count}")

    # -------------------------------------------------------------------------
    # TEMP PROFILE
    # -------------------------------------------------------------------------

    print()
    print("TEMP PROFILE")
    print("-" * 80)

    temp_profile = store.profile(
        dataset_id=DATASET,
        variable="TEMP",
        latitude=LATITUDE,
        longitude=LONGITUDE,
        timestamp_utc=TIME,
    )

    print(
        f"Found {len(temp_profile)} TEMP observations"
    )

    for item in temp_profile:
        print(
            f"time={item.timestamp_utc} | "
            f"lat={item.latitude} | "
            f"lon={item.longitude} | "
            f"ZAX={item.pressure_m} m | "
            f"depth={item.depth_m} m | "
            f"value={item.value} | "
            f"units={item.units} | "
            f"missing={item.is_missing}"
        )

    # -------------------------------------------------------------------------
    # SAL PROFILE
    # -------------------------------------------------------------------------

    print()
    print("SAL PROFILE")
    print("-" * 80)

    sal_profile = store.profile(
        dataset_id=DATASET,
        variable="SAL",
        latitude=LATITUDE,
        longitude=LONGITUDE,
        timestamp_utc=TIME,
    )

    print(
        f"Found {len(sal_profile)} SAL observations"
    )

    for item in sal_profile:
        print(
            f"time={item.timestamp_utc} | "
            f"lat={item.latitude} | "
            f"lon={item.longitude} | "
            f"ZAX={item.pressure_m} m | "
            f"depth={item.depth_m} m | "
            f"value={item.value} | "
            f"units={item.units} | "
            f"missing={item.is_missing}"
        )

    # -------------------------------------------------------------------------
    # CHECKS
    # -------------------------------------------------------------------------

    print()
    print("VALIDATION CHECKS")
    print("-" * 80)

    temp_depths = [
        item.depth_m
        for item in temp_profile
        if item.depth_m is not None
    ]

    sal_depths = [
        item.depth_m
        for item in sal_profile
        if item.depth_m is not None
    ]

    expected_depths = [
        5.0,
        10.0,
        20.0,
        30.0,
        50.0,
        75.0,
        100.0,
        125.0,
        150.0,
        200.0,
        250.0,
        300.0,
        400.0,
        500.0,
        600.0,
        700.0,
        800.0,
        900.0,
        1000.0,
        1200.0,
        1400.0,
        1600.0,
        1800.0,
        2000.0,
    ]

    print(
        "TEMP has 24 levels:",
        len(temp_profile) == 24,
    )

    print(
        "SAL has 24 levels:",
        len(sal_profile) == 24,
    )

    print(
        "TEMP depth grid preserved:",
        temp_depths == expected_depths,
    )

    print(
        "SAL depth grid preserved:",
        sal_depths == expected_depths,
    )

    print(
        "TEMP latest time correct:",
        all(
            item.timestamp_utc == TIME
            for item in temp_profile
        ),
    )

    print(
        "SAL latest time correct:",
        all(
            item.timestamp_utc == TIME
            for item in sal_profile
        ),
    )

    print(
        "TEMP provenance present:",
        all(
            item.source == "INCOIS ERDDAP"
            and item.source_url
            for item in temp_profile
        ),
    )

    print(
        "SAL provenance present:",
        all(
            item.source == "INCOIS ERDDAP"
            and item.source_url
            for item in sal_profile
        ),
    )

    print()
    print("=" * 80)
    print("SCIENTIFIC STORE VALIDATION COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    main()

