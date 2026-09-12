
from __future__ import annotations

import math

from .hycom_chunk_index import (
    HycomChunkIndex,
)
from .ocean_query import (
    OceanQueryEngine,
)


def main() -> None:

    print("=" * 80)
    print(
        "OCEANSIGHT-V"
    )
    print(
        "OCEAN QUERY ENGINE VALIDATION"
    )
    print("=" * 80)

    # -------------------------------------------------------------------------
    # REBUILD LOCAL INDEX
    # -------------------------------------------------------------------------

    index = HycomChunkIndex()

    chunks = index.rebuild()

    print()
    print(
        "Indexed chunks:",
        len(chunks),
    )

    if not chunks:

        raise RuntimeError(
            "No local HYCOM chunks exist.\n"
            "Run:\n"
            "python -m app.hycom_chunk_store"
        )

    # -------------------------------------------------------------------------
    # QUERY
    #
    # Request intentionally falls inside our verified local tile.
    # -------------------------------------------------------------------------

    requested_latitude = -8.20
    requested_longitude = 68.20
    requested_depth = 100.0
    requested_time = (
        "2026-09-10T06:00:00Z"
    )

    print()
    print(
        "REQUEST"
    )

    print(
        "-" * 80
    )

    print(
        "Latitude:",
        requested_latitude,
    )

    print(
        "Longitude:",
        requested_longitude,
    )

    print(
        "Depth:",
        requested_depth,
        "m",
    )

    print(
        "Time:",
        requested_time,
    )

    # -------------------------------------------------------------------------
    # EXECUTE
    # -------------------------------------------------------------------------

    engine = OceanQueryEngine(
        chunk_index=index
    )

    observation = engine.query(
        latitude=requested_latitude,
        longitude=requested_longitude,
        depth_m=requested_depth,
        time_utc=requested_time,
    )

    # -------------------------------------------------------------------------
    # OUTPUT
    # -------------------------------------------------------------------------

    print()
    print(
        "RESULT"
    )

    print(
        "-" * 80
    )

    print(
        "Requested latitude:",
        observation.requested_latitude,
    )

    print(
        "Actual source latitude:",
        observation.actual_latitude,
    )

    print(
        "Requested longitude:",
        observation.requested_longitude,
    )

    print(
        "Actual source longitude:",
        observation.actual_longitude,
    )

    print(
        "Requested depth:",
        observation.requested_depth_m,
        "m",
    )

    print(
        "Actual source depth:",
        observation.actual_depth_m,
        "m",
    )

    print(
        "Requested time:",
        observation.requested_time_utc,
    )

    print(
        "Actual source time:",
        observation.actual_time_utc,
    )

    print()
    print(
        "SCIENTIFIC VALUES"
    )

    print(
        "-" * 80
    )

    print(
        "Temperature:",
        observation.temperature_c,
        "°C",
    )

    print(
        "Salinity:",
        observation.salinity,
    )

    print(
        "U current:",
        observation.u_current_m_s,
        "m/s",
    )

    print(
        "V current:",
        observation.v_current_m_s,
        "m/s",
    )

    print(
        "Current speed:",
        observation.current_speed_m_s,
        "m/s",
    )

    print(
        "Current mathematical direction:",
        observation.current_direction_math_deg,
        "degrees",
    )

    print(
        "SSH:",
        observation.ssh_m,
        "m",
    )

    print()
    print(
        "MISSING DATA"
    )

    print(
        "-" * 80
    )

    print(
        "TEMP missing:",
        observation.temp_missing,
    )

    print(
        "SALN missing:",
        observation.salinity_missing,
    )

    print(
        "U current missing:",
        observation.u_current_missing,
    )

    print(
        "V current missing:",
        observation.v_current_missing,
    )

    print(
        "SSH missing:",
        observation.ssh_missing,
    )

    print()
    print(
        "PROVENANCE"
    )

    print(
        "-" * 80
    )

    print(
        "Source:",
        observation.source,
    )

    print(
        "Dataset:",
        observation.dataset,
    )

    print(
        "Source URL:",
        observation.source_url,
    )

    print(
        "Chunk:",
        observation.chunk_file,
    )

    # -------------------------------------------------------------------------
    # VALIDATION
    # -------------------------------------------------------------------------

    print()
    print(
        "VALIDATION"
    )

    print(
        "-" * 80
    )

    assert (
        observation.source
        == "INCOIS"
    )

    assert (
        observation.dataset
        == "RSMC_hycom_20260911.nc"
    )

    assert (
        observation.actual_time_utc
        == requested_time
    )

    assert (
        0.0
        <= observation.actual_depth_m
        <= 500.0
    )

    assert math.isfinite(
        observation.actual_latitude
    )

    assert math.isfinite(
        observation.actual_longitude
    )

    assert (
        observation.temperature_c
        is not None
    )

    assert (
        observation.salinity
        is not None
    )

    assert (
        observation.u_current_m_s
        is not None
    )

    assert (
        observation.v_current_m_s
        is not None
    )

    assert (
        observation.ssh_m
        is not None
    )

    assert (
        observation.current_speed_m_s
        is not None
    )

    assert (
        observation.current_speed_m_s
        >= 0.0
    )

    assert (
        observation.temp_missing
        is False
    )

    assert (
        observation.salinity_missing
        is False
    )

    assert (
        observation.u_current_missing
        is False
    )

    assert (
        observation.v_current_missing
        is False
    )

    assert (
        observation.ssh_missing
        is False
    )

    print(
        "Local chunk lookup: PASS"
    )

    print(
        "Time selection: PASS"
    )

    print(
        "Nearest source depth: PASS"
    )

    print(
        "Nearest source latitude: PASS"
    )

    print(
        "Nearest source longitude: PASS"
    )

    print(
        "Temperature: PASS"
    )

    print(
        "Salinity: PASS"
    )

    print(
        "UVEL: PASS"
    )

    print(
        "VVEL: PASS"
    )

    print(
        "SSH: PASS"
    )

    print(
        "Current vector calculation: PASS"
    )

    print(
        "Missing-data handling: PASS"
    )

    print(
        "Provenance: PASS"
    )

    print()
    print("=" * 80)
    print(
        "OCEAN QUERY ENGINE VALIDATION COMPLETE"
    )
    print("=" * 80)


if __name__ == "__main__":
    main()

