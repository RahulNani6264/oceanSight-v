
from __future__ import annotations

from .argo_store import ArgoStore


PLATFORM = "7902250"
CYCLE = 12


def main() -> None:
    print("=" * 80)
    print("OCEANSIGHT-V")
    print("ARGO STORE VALIDATION")
    print("=" * 80)

    store = ArgoStore()

    print()
    print("DATABASE")
    print("-" * 80)
    print(store.db_path)

    print()
    print("STORE COUNTS")
    print("-" * 80)

    print(
        "Observations:",
        store.count(),
    )

    print(
        "Unique floats:",
        store.unique_floats(),
    )

    print(
        "Unique profiles:",
        store.unique_profiles(),
    )

    # -------------------------------------------------------------------------
    # PROFILE
    # -------------------------------------------------------------------------

    profile = store.get_profile(
        platform_number=PLATFORM,
        cycle_number=CYCLE,
    )

    print()
    print("PROFILE")
    print("-" * 80)

    print(
        f"Float {PLATFORM}, cycle {CYCLE}"
    )

    print(
        "Measurements:",
        len(profile),
    )

    if profile:

        first = profile[0]

        print(
            "Location:",
            first["latitude"],
            first["longitude"],
        )

        print(
            "Time:",
            first["profile_time_utc"],
        )

        print()
        print(
            "PRESSURE / TEMP / SALINITY"
        )
        print("-" * 80)

        for row in profile[:20]:

            print(
                f"PRES={row['pres_dbar']} dbar | "
                f"PRES_QC={row['pres_qc']} | "
                f"TEMP={row['temp_c']} °C | "
                f"TEMP_QC={row['temp_qc']} | "
                f"PSAL={row['psal_psu']} PSU | "
                f"PSAL_QC={row['psal_qc']}"
            )

    # -------------------------------------------------------------------------
    # VALIDATION
    # -------------------------------------------------------------------------

    print()
    print("VALIDATION")
    print("-" * 80)

    pressure_present = all(
        row["pres_dbar"] is not None
        for row in profile
    )

    temperature_present = all(
        row["temp_c"] is not None
        for row in profile
    )

    salinity_present = all(
        row["psal_psu"] is not None
        for row in profile
    )

    qc_present = all(
        row["pres_qc"] is not None
        and row["temp_qc"] is not None
        and row["psal_qc"] is not None
        for row in profile
    )

    profile_identity_present = all(
        row["platform_number"] == PLATFORM
        and row["cycle_number"] == CYCLE
        for row in profile
    )

    provenance_present = all(
        row["source"] == "INCOIS ERDDAP"
        and row["source_dataset"]
        == "Indian_ARGO_Floats"
        and row["source_url"]
        for row in profile
    )

    pressure_is_ascending = all(
        profile[index]["pres_dbar"]
        <= profile[index + 1]["pres_dbar"]
        for index in range(
            len(profile) - 1
        )
    )

    print(
        "Real Argo profile found:",
        len(profile) > 0,
    )

    print(
        "PRES preserved:",
        pressure_present,
    )

    print(
        "TEMP preserved:",
        temperature_present,
    )

    print(
        "PSAL preserved:",
        salinity_present,
    )

    print(
        "QC flags preserved:",
        qc_present,
    )

    print(
        "Float/cycle identity preserved:",
        profile_identity_present,
    )

    print(
        "INCOIS provenance preserved:",
        provenance_present,
    )

    print(
        "Pressure sorted ascending:",
        pressure_is_ascending,
    )

    # -------------------------------------------------------------------------
    # RANGE
    # -------------------------------------------------------------------------

    if profile:

        pressures = [
            row["pres_dbar"]
            for row in profile
            if row["pres_dbar"] is not None
        ]

        temperatures = [
            row["temp_c"]
            for row in profile
            if row["temp_c"] is not None
        ]

        salinities = [
            row["psal_psu"]
            for row in profile
            if row["psal_psu"] is not None
        ]

        print()
        print("PROFILE RANGES")
        print("-" * 80)

        print(
            "PRES:",
            min(pressures),
            "to",
            max(pressures),
            "dbar",
        )

        print(
            "TEMP:",
            min(temperatures),
            "to",
            max(temperatures),
            "°C",
        )

        print(
            "PSAL:",
            min(salinities),
            "to",
            max(salinities),
            "PSU",
        )

    print()
    print("=" * 80)
    print("ARGO STORE VALIDATION COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    main()

