from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]

CHUNK_DIR = PROJECT_ROOT / "processed" / "gebco_chunks"
INDEX_PATH = PROJECT_ROOT / "processed" / "gebco_chunk_index.json"


def main() -> None:
    print("=" * 70)
    print("OceanSight - GEBCO Chunk Index")
    print("=" * 70)

    if not CHUNK_DIR.exists():
        raise FileNotFoundError(
            f"GEBCO chunk directory does not exist:\n{CHUNK_DIR}"
        )

    provenance_files = sorted(CHUNK_DIR.glob("*.json"))

    if not provenance_files:
        raise FileNotFoundError(
            f"No GEBCO provenance files found in:\n{CHUNK_DIR}\n\n"
            "Run gebco_chunk_store.py first."
        )

    chunks = []

    for provenance_path in provenance_files:
        with provenance_path.open("r", encoding="utf-8") as f:
            metadata = json.load(f)

        chunk_id = metadata.get("chunk_id")

        if not chunk_id:
            continue

        npz_path = CHUNK_DIR / f"{chunk_id}.npz"

        if not npz_path.exists():
            print(
                f"WARNING: missing NPZ for {chunk_id}: "
                f"{npz_path}"
            )
            continue

        coordinate_ranges = metadata.get(
            "coordinate_ranges",
            {},
        )

        latitude = coordinate_ranges.get(
            "latitude",
            [],
        )

        longitude = coordinate_ranges.get(
            "longitude",
            [],
        )

        if len(latitude) != 2 or len(longitude) != 2:
            print(
                f"WARNING: invalid coordinate ranges "
                f"for {chunk_id}"
            )
            continue

        chunks.append(
            {
                "chunk_id": chunk_id,
                "npz_path": str(npz_path),
                "provenance_path": str(provenance_path),

                "latitude_min": float(latitude[0]),
                "latitude_max": float(latitude[1]),

                "longitude_min": float(longitude[0]),
                "longitude_max": float(longitude[1]),

                "y_start": int(
                    metadata["index_range"]["y_start"]
                ),
                "y_end": int(
                    metadata["index_range"]["y_end"]
                ),

                "x_start": int(
                    metadata["index_range"]["x_start"]
                ),
                "x_end": int(
                    metadata["index_range"]["x_end"]
                ),

                "shape": metadata.get("shape"),

                "minimum_elevation_m": metadata.get(
                    "minimum_elevation_m"
                ),
                "maximum_elevation_m": metadata.get(
                    "maximum_elevation_m"
                ),

                "finite_count": metadata.get(
                    "finite_count",
                    0,
                ),
                "missing_count": metadata.get(
                    "missing_count",
                    0,
                ),
            }
        )

    chunks.sort(
        key=lambda item: (
            item["latitude_min"],
            item["longitude_min"],
            item["chunk_id"],
        )
    )

    index = {
        "created_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),

        "source": "GEBCO",

        "dataset": "GEBCO_2026",

        "source_url": (
            "https://dap.ceda.ac.uk/thredds/dodsC/"
            "bodc/gebco/global/gebco_2026/"
            "ice_surface_elevation/netcdf/GEBCO_2026.nc"
        ),

        "chunk_directory": str(CHUNK_DIR),

        "chunk_count": len(chunks),

        "chunks": chunks,
    }

    INDEX_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with INDEX_PATH.open(
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            index,
            f,
            indent=2,
            ensure_ascii=False,
        )

    print()
    print("GEBCO chunks discovered:", len(chunks))

    for chunk in chunks:
        print(
            f"  {chunk['chunk_id']}"
        )
        print(
            f"    lat: "
            f"{chunk['latitude_min']} -> "
            f"{chunk['latitude_max']}"
        )
        print(
            f"    lon: "
            f"{chunk['longitude_min']} -> "
            f"{chunk['longitude_max']}"
        )

    print()
    print("Index saved:")
    print(INDEX_PATH)

    print()
    print("=" * 70)
    print("INDEX COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()