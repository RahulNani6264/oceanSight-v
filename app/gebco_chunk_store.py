from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import xarray as xr


GEBCO_URL = (
    "https://dap.ceda.ac.uk/thredds/dodsC/"
    "bodc/gebco/global/gebco_2026/"
    "ice_surface_elevation/netcdf/GEBCO_2026.nc"
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]

PROCESSED_DIR = PROJECT_ROOT / "processed"
CHUNK_DIR = PROCESSED_DIR / "gebco_chunks"
METADATA_DIR = PROJECT_ROOT / "metadata"

CHUNK_DIR.mkdir(parents=True, exist_ok=True)
METADATA_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------
# Dataset discovery
# ---------------------------------------------------------------------

def find_variable(ds: xr.Dataset, candidates: tuple[str, ...]) -> str | None:
    """
    Find the first matching variable name.
    """
    for name in candidates:
        if name in ds.variables:
            return name

    # Case-insensitive fallback.
    lowered = {name.lower(): name for name in ds.variables}

    for candidate in candidates:
        found = lowered.get(candidate.lower())
        if found:
            return found

    return None


def discover_dataset(ds: xr.Dataset) -> dict[str, str]:
    """
    Discover latitude, longitude and elevation variables.
    """

    lat_name = find_variable(
        ds,
        (
            "lat",
            "latitude",
        ),
    )

    lon_name = find_variable(
        ds,
        (
            "lon",
            "longitude",
        ),
    )

    elevation_name = find_variable(
        ds,
        (
            "elevation",
            "z",
            "topo",
        ),
    )

    if lat_name is None:
        raise RuntimeError(
            "GEBCO latitude variable could not be identified."
        )

    if lon_name is None:
        raise RuntimeError(
            "GEBCO longitude variable could not be identified."
        )

    if elevation_name is None:
        raise RuntimeError(
            "GEBCO elevation variable could not be identified."
        )

    return {
        "lat": lat_name,
        "lon": lon_name,
        "elevation": elevation_name,
    }


# ---------------------------------------------------------------------
# Coordinate helpers
# ---------------------------------------------------------------------

def coordinate_range(
    coordinate: xr.DataArray,
    minimum: float,
    maximum: float,
) -> tuple[int, int]:
    """
    Find the inclusive integer index range covering a coordinate
    bounding box.

    Works for either ascending or descending coordinates.
    """

    values = np.asarray(coordinate.values, dtype=np.float64)

    if values.ndim != 1:
        raise RuntimeError(
            f"Expected a 1-D coordinate, got shape {values.shape}."
        )

    mask = (
        np.isfinite(values)
        & (values >= minimum)
        & (values <= maximum)
    )

    indexes = np.flatnonzero(mask)

    if indexes.size == 0:
        raise ValueError(
            f"No coordinate values found in range "
            f"{minimum} to {maximum}."
        )

    return int(indexes.min()), int(indexes.max())


def coordinate_spacing(values: np.ndarray) -> float | None:
    """
    Estimate coordinate spacing from the first finite differences.
    """

    values = np.asarray(values, dtype=np.float64)

    if values.size < 2:
        return None

    diffs = np.diff(values)

    finite = np.isfinite(diffs)

    if not np.any(finite):
        return None

    return float(np.median(np.abs(diffs[finite])))


# ---------------------------------------------------------------------
# Missing-value handling
# ---------------------------------------------------------------------

def build_missing_mask(
    values: np.ndarray,
    fill_value: float | None,
) -> np.ndarray:
    """
    Build an explicit missing-data mask.

    Missing data includes:
    - NaN
    - source fill value
    - extremely large sentinel values
    """

    arr = np.asarray(values)

    mask = ~np.isfinite(arr)

    if fill_value is not None:
        try:
            mask |= np.isclose(
                arr,
                float(fill_value),
                rtol=0.0,
                atol=max(1e-12, abs(float(fill_value)) * 1e-12),
            )
        except Exception:
            pass

    # GEBCO/netCDF datasets can use large sentinel values.
    mask |= np.abs(arr) > 1.0e20

    return mask


# ---------------------------------------------------------------------
# Single chunk download
# ---------------------------------------------------------------------

def download_chunk(
    ds: xr.Dataset,
    variable_names: dict[str, str],
    y_start: int,
    y_end: int,
    x_start: int,
    x_end: int,
    chunk_id: str,
) -> Path:
    """
    Download one numerical GEBCO chunk using OPeNDAP.

    y_end and x_end are inclusive.
    """

    lat_name = variable_names["lat"]
    lon_name = variable_names["lon"]
    elevation_name = variable_names["elevation"]

    print()
    print("-" * 70)
    print(f"Downloading GEBCO chunk: {chunk_id}")
    print("-" * 70)

    print(
        f"Latitude index : {y_start} -> {y_end}"
    )
    print(
        f"Longitude index: {x_start} -> {x_end}"
    )

    latitude = ds[lat_name].isel(
        {ds[lat_name].dims[0]: slice(y_start, y_end + 1)}
    )

    longitude = ds[lon_name].isel(
        {ds[lon_name].dims[0]: slice(x_start, x_end + 1)}
    )

    elevation_subset = ds[elevation_name].isel(
        {
            ds[elevation_name].dims[-2]: slice(y_start, y_end + 1),
            ds[elevation_name].dims[-1]: slice(x_start, x_end + 1),
        }
    )

    print("Requesting numerical values from CEDA OPeNDAP...")

    # This is the point where the remote data are actually retrieved.
    lat_values = np.asarray(latitude.values, dtype=np.float64)
    lon_values = np.asarray(longitude.values, dtype=np.float64)

    raw_values = np.asarray(
        elevation_subset.values,
        dtype=np.float32,
    )

    # Make sure the result is 2-D.
    while raw_values.ndim > 2 and raw_values.shape[0] == 1:
        raw_values = raw_values[0]

    if raw_values.ndim != 2:
        raise RuntimeError(
            "Expected elevation chunk to be 2-D, "
            f"got shape {raw_values.shape}."
        )

    # ---------------------------------------------------------------
    # Source fill value
    # ---------------------------------------------------------------

    fill_value = elevation_subset.attrs.get(
        "_FillValue",
        elevation_subset.encoding.get("_FillValue"),
    )

    missing_mask = build_missing_mask(
        raw_values,
        fill_value,
    )

    # Processed numerical field:
    # unavailable values become NaN, while the explicit mask records
    # exactly where data are unavailable.
    elevation_values = raw_values.astype(
        np.float32,
        copy=True,
    )

    elevation_values[missing_mask] = np.nan

    finite_values = elevation_values[
        np.isfinite(elevation_values)
    ]

    minimum = (
        float(np.min(finite_values))
        if finite_values.size
        else None
    )

    maximum = (
        float(np.max(finite_values))
        if finite_values.size
        else None
    )

    # ---------------------------------------------------------------
    # Coordinates
    # ---------------------------------------------------------------

    lat_spacing = coordinate_spacing(lat_values)
    lon_spacing = coordinate_spacing(lon_values)

    print()
    print("Returned latitude shape :", lat_values.shape)
    print("Returned longitude shape:", lon_values.shape)
    print("Elevation shape         :", raw_values.shape)

    print()
    print("Latitude range :")
    print(
        f"  {float(np.min(lat_values))} "
        f"to "
        f"{float(np.max(lat_values))}"
    )

    print("Longitude range:")
    print(
        f"  {float(np.min(lon_values))} "
        f"to "
        f"{float(np.max(lon_values))}"
    )

    print()
    print("Elevation range:")
    print(" ", minimum, "to", maximum, "meters")

    finite_count = int(np.isfinite(elevation_values).sum())
    total_count = int(elevation_values.size)
    missing_count = int(missing_mask.sum())

    print()
    print("Finite values :", finite_count)
    print("Missing values:", missing_count)
    print("Total values  :", total_count)

    # ---------------------------------------------------------------
    # Save NPZ
    # ---------------------------------------------------------------

    npz_path = CHUNK_DIR / f"{chunk_id}.npz"

    np.savez_compressed(
        npz_path,
        latitude=lat_values,
        longitude=lon_values,

        # Numerical processed field.
        elevation_m=elevation_values,

        # Original remotely returned source values, including
        # source fill/sentinel values.
        elevation_raw=raw_values,

        # Explicit missing-value mask.
        missing_mask=missing_mask,

        # Index information.
        y_start=np.int64(y_start),
        y_end=np.int64(y_end),
        x_start=np.int64(x_start),
        x_end=np.int64(x_end),
    )

    # ---------------------------------------------------------------
    # Provenance
    # ---------------------------------------------------------------

    elevation_attrs = {
        str(key): str(value)
        for key, value in elevation_subset.attrs.items()
    }

    provenance = {
        "source": "GEBCO",
        "dataset": "GEBCO_2026",
        "dataset_variant": "ice_surface_elevation",

        "source_url": GEBCO_URL,

        "provider": (
            "GEBCO Bathymetric Compilation Group"
        ),

        "geospatial_reference": (
            "GEBCO 2026 global terrain model"
        ),

        "created_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),

        "chunk_id": chunk_id,

        "index_range": {
            "y_start": y_start,
            "y_end": y_end,
            "x_start": x_start,
            "x_end": x_end,
        },

        "coordinate_ranges": {
            "latitude": [
                float(np.min(lat_values)),
                float(np.max(lat_values)),
            ],
            "longitude": [
                float(np.min(lon_values)),
                float(np.max(lon_values)),
            ],
        },

        "coordinate_spacing": {
            "latitude_degrees": lat_spacing,
            "longitude_degrees": lon_spacing,
        },

        "shape": list(elevation_values.shape),

        "variable": elevation_name,

        "units": elevation_attrs.get(
            "units",
            "meters",
        ),

        "elevation_attributes": elevation_attrs,

        "source_fill_value": (
            str(fill_value)
            if fill_value is not None
            else None
        ),

        "finite_count": finite_count,
        "missing_count": missing_count,
        "total_count": total_count,

        "minimum_elevation_m": minimum,
        "maximum_elevation_m": maximum,

        "raw_values_preserved": True,
        "missing_mask_preserved": True,

        "global_file_downloaded": False,

        "attribution": (
            "GEBCO Bathymetric Compilation Group 2026 "
            "(2026). The GEBCO_2026 Grid - a continuous "
            "terrain model for oceans and land at 15 "
            "arc-second intervals. "
            "doi:10.5285/4f68d5c7-45eb-f999-e063-7086abc036fa"
        ),
    }

    json_path = CHUNK_DIR / f"{chunk_id}.json"

    with json_path.open(
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            provenance,
            f,
            indent=2,
            ensure_ascii=False,
        )

    print()
    print("Saved chunk:")
    print(" ", npz_path)

    print("Saved provenance:")
    print(" ", json_path)

    return npz_path


# ---------------------------------------------------------------------
# Bounding-box downloader
# ---------------------------------------------------------------------

def download_bbox(
    lat_min: float,
    lat_max: float,
    lon_min: float,
    lon_max: float,
    chunk_lat_cells: int = 256,
    chunk_lon_cells: int = 256,
) -> list[Path]:
    """
    Download GEBCO data for a geographic bounding box.

    Large requests are divided into independent lat/lon chunks.
    """

    print()
    print("=" * 70)
    print("OceanSight - GEBCO 2026 Chunk Downloader")
    print("=" * 70)

    print()
    print("Source:")
    print(GEBCO_URL)

    print()
    print("Requested region:")
    print(f"  Latitude : {lat_min} to {lat_max}")
    print(f"  Longitude: {lon_min} to {lon_max}")

    print()
    print("Opening remote dataset...")

    ds = xr.open_dataset(
        GEBCO_URL,
        engine="netcdf4",
        decode_cf=False,
        mask_and_scale=False,
    )

    try:
        variable_names = discover_dataset(ds)

        print()
        print("Discovered variables:")
        print("  Latitude :", variable_names["lat"])
        print("  Longitude:", variable_names["lon"])
        print("  Elevation:", variable_names["elevation"])

        lat = ds[variable_names["lat"]]
        lon = ds[variable_names["lon"]]

        y_start, y_end = coordinate_range(
            lat,
            lat_min,
            lat_max,
        )

        x_start, x_end = coordinate_range(
            lon,
            lon_min,
            lon_max,
        )

        print()
        print("Requested source indexes:")
        print(f"  Y: {y_start} -> {y_end}")
        print(f"  X: {x_start} -> {x_end}")

        saved_chunks: list[Path] = []

        total_y = y_end - y_start + 1
        total_x = x_end - x_start + 1

        y = y_start

        while y <= y_end:
            chunk_y_end = min(
                y + chunk_lat_cells - 1,
                y_end,
            )

            x = x_start

            while x <= x_end:
                chunk_x_end = min(
                    x + chunk_lon_cells - 1,
                    x_end,
                )

                chunk_id = (
                    f"gebco_"
                    f"y{y:05d}-{chunk_y_end:05d}_"
                    f"x{x:05d}-{chunk_x_end:05d}"
                )

                npz_path = download_chunk(
                    ds=ds,
                    variable_names=variable_names,
                    y_start=y,
                    y_end=chunk_y_end,
                    x_start=x,
                    x_end=chunk_x_end,
                    chunk_id=chunk_id,
                )

                saved_chunks.append(npz_path)

                x = chunk_x_end + 1

            y = chunk_y_end + 1

        print()
        print("=" * 70)
        print("GEBCO CHUNK DOWNLOAD COMPLETE")
        print("=" * 70)

        print()
        print("Requested cells:")
        print(f"  Latitude cells : {total_y}")
        print(f"  Longitude cells: {total_x}")
        print(f"  Total cells    : {total_y * total_x}")

        print()
        print("Chunks saved:", len(saved_chunks))

        for path in saved_chunks:
            print(" ", path)

        return saved_chunks

    finally:
        ds.close()


# ---------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------


def main() -> None:
    """
    Download real GEBCO data around a requested geographic point.

    A radius in degrees is converted to a latitude/longitude bounding box.
    The existing download_bbox() function then handles chunking and
    preservation of the original GEBCO values and missing-data mask.
    """

    import argparse

    parser = argparse.ArgumentParser(
        description="OceanSight real GEBCO 2026 point downloader"
    )

    parser.add_argument(
        "--latitude",
        type=float,
        required=True,
        help="Requested latitude in decimal degrees.",
    )

    parser.add_argument(
        "--longitude",
        type=float,
        required=True,
        help="Requested longitude in decimal degrees.",
    )

    parser.add_argument(
        "--radius-degrees",
        type=float,
        default=0.25,
        help="Latitude/longitude radius in degrees.",
    )

    parser.add_argument(
        "--chunk-lat-cells",
        type=int,
        default=256,
        help="Maximum latitude cells per downloaded chunk.",
    )

    parser.add_argument(
        "--chunk-lon-cells",
        type=int,
        default=256,
        help="Maximum longitude cells per downloaded chunk.",
    )

    args = parser.parse_args()

    if args.radius_degrees <= 0:
        raise ValueError(
            "radius-degrees must be greater than zero."
        )

    if not np.isfinite(args.latitude):
        raise ValueError(
            f"Invalid latitude: {args.latitude}"
        )

    if not np.isfinite(args.longitude):
        raise ValueError(
            f"Invalid longitude: {args.longitude}"
        )

    if not -90.0 <= args.latitude <= 90.0:
        raise ValueError(
            f"Latitude must be between -90 and 90. Got {args.latitude}."
        )

    if not -180.0 <= args.longitude <= 180.0:
        raise ValueError(
            f"Longitude must be between -180 and 180. Got {args.longitude}."
        )

    if args.chunk_lat_cells <= 0:
        raise ValueError(
            "chunk-lat-cells must be greater than zero."
        )

    if args.chunk_lon_cells <= 0:
        raise ValueError(
            "chunk-lon-cells must be greater than zero."
        )

    lat_min = max(
        -90.0,
        args.latitude - args.radius_degrees,
    )

    lat_max = min(
        90.0,
        args.latitude + args.radius_degrees,
    )

    lon_min = max(
        -180.0,
        args.longitude - args.radius_degrees,
    )

    lon_max = min(
        180.0,
        args.longitude + args.radius_degrees,
    )

    print()
    print("=" * 70)
    print("OCEANSIGHT-V")
    print("REAL GEBCO 2026 POINT DOWNLOADER")
    print("=" * 70)

    print()
    print("REQUEST MODE: POINT")

    print()
    print("REQUEST:")
    print(f"  Latitude       : {args.latitude}")
    print(f"  Longitude      : {args.longitude}")
    print(f"  Radius degrees : {args.radius_degrees}")

    print()
    print("BOUNDING BOX:")
    print(f"  Latitude       : {lat_min} to {lat_max}")
    print(f"  Longitude      : {lon_min} to {lon_max}")

    download_bbox(
        lat_min=lat_min,
        lat_max=lat_max,
        lon_min=lon_min,
        lon_max=lon_max,
        chunk_lat_cells=args.chunk_lat_cells,
        chunk_lon_cells=args.chunk_lon_cells,
    )


if __name__ == "__main__":
    main()

