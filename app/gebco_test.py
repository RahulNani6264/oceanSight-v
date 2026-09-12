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
METADATA_DIR = PROJECT_ROOT / "metadata"
LOG_DIR = PROJECT_ROOT / "logs"

METADATA_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)


def print_header(title: str) -> None:
    print()
    print("=" * 70)
    print(title)
    print("=" * 70)


def safe_range(values: np.ndarray) -> tuple[float | None, float | None]:
    arr = np.asarray(values, dtype=np.float64)

    finite = np.isfinite(arr)
    if not np.any(finite):
        return None, None

    valid = arr[finite]
    return float(valid.min()), float(valid.max())


def main() -> None:
    started = datetime.now(timezone.utc)

    print_header("OceanSight - GEBCO 2026 OPeNDAP Test")

    print("Project root :", PROJECT_ROOT)
    print("GEBCO URL    :", GEBCO_URL)
    print()

    print("Opening GEBCO remotely...")
    print("Only a very small inspection is performed.")
    print()

    try:
        # We do NOT download the complete global file.
        ds = xr.open_dataset(
            GEBCO_URL,
            engine="netcdf4",
            decode_cf=False,
            mask_and_scale=False,
        )

    except Exception as exc:
        print("FAILED to open GEBCO endpoint.")
        print()
        print("Error type :", type(exc).__name__)
        print("Error      :", exc)
        print()
        print(
            "This test requires your Windows machine to be able to reach "
            "dap.ceda.ac.uk."
        )
        return

    try:
        print_header("Dataset opened successfully")

        print("Dimensions:")
        for name, size in ds.sizes.items():
            print(f"  {name:20s} = {size}")

        print()
        print("Variables:")
        for name, var in ds.variables.items():
            print(
                f"  {name:20s} "
                f"dims={tuple(var.dims)} "
                f"dtype={var.dtype}"
            )

        print()

        metadata = {
            "source": "GEBCO",
            "dataset": "GEBCO_2026",
            "url": GEBCO_URL,
            "variant": "ice_surface_elevation",
            "opened_at_utc": started.isoformat(),
            "dimensions": {
                name: int(size)
                for name, size in ds.sizes.items()
            },
            "variables": {
                name: {
                    "dimensions": list(var.dims),
                    "dtype": str(var.dtype),
                }
                for name, var in ds.variables.items()
            },
        }

        # ---------------------------------------------------------
        # Coordinate discovery
        # ---------------------------------------------------------

        print_header("Coordinate discovery")

        lat_name = None
        lon_name = None
        elevation_name = None

        for candidate in ("lat", "latitude"):
            if candidate in ds.variables:
                lat_name = candidate
                break

        for candidate in ("lon", "longitude"):
            if candidate in ds.variables:
                lon_name = candidate
                break

        # GEBCO normally uses elevation as "elevation".
        for candidate in ("elevation", "z", "topo"):
            if candidate in ds.variables:
                elevation_name = candidate
                break

        print("Latitude variable :", lat_name)
        print("Longitude variable:", lon_name)
        print("Elevation variable:", elevation_name)

        if lat_name is None or lon_name is None:
            raise RuntimeError(
                "Could not identify latitude/longitude variables."
            )

        if elevation_name is None:
            raise RuntimeError(
                "Could not identify GEBCO elevation variable."
            )

        lat = ds[lat_name]
        lon = ds[lon_name]
        elevation = ds[elevation_name]

        print()
        print("Latitude dimensions :", lat.dims)
        print("Longitude dimensions:", lon.dims)
        print("Elevation dimensions:", elevation.dims)

        print()
        print("Latitude size :", lat.size)
        print("Longitude size:", lon.size)

        # Do not read the full grid.
        # Only fetch a few coordinate values for verification.
        lat_sample = np.asarray(lat.isel({lat.dims[0]: slice(0, 5)}).values)
        lon_sample = np.asarray(lon.isel({lon.dims[0]: slice(0, 5)}).values)

        print()
        print("First latitude values :", lat_sample)
        print("First longitude values:", lon_sample)

        # ---------------------------------------------------------
        # Variable attributes
        # ---------------------------------------------------------

        print_header("Elevation metadata")

        for key, value in elevation.attrs.items():
            print(f"{key:20s}: {value}")

        metadata["elevation_attributes"] = {
            str(key): str(value)
            for key, value in elevation.attrs.items()
        }

        # ---------------------------------------------------------
        # Small Indian Ocean test
        # ---------------------------------------------------------
        #
        # IMPORTANT:
        # We are deliberately requesting only a tiny area.
        #
        # Around:
        #   latitude  : 8 to 9 N
        #   longitude : 80 to 81 E
        #
        # This is enough to prove that actual numerical
        # bathymetry values can be queried remotely.
        # ---------------------------------------------------------

        print_header("Tiny Indian Ocean numerical test")

        lat_min = 8.0
        lat_max = 9.0
        lon_min = 80.0
        lon_max = 81.0

        print(f"Requested latitude : {lat_min} to {lat_max}")
        print(f"Requested longitude: {lon_min} to {lon_max}")
        print()

        # GEBCO coordinates are normally 1-D.
        # Use nearest/within selection without loading the full grid.

        lat_selection = lat.where(
            (lat >= lat_min) & (lat <= lat_max),
            drop=True,
        )

        lon_selection = lon.where(
            (lon >= lon_min) & (lon <= lon_max),
            drop=True,
        )

        print("Selected latitude points :", lat_selection.size)
        print("Selected longitude points:", lon_selection.size)

        if lat_selection.size == 0 or lon_selection.size == 0:
            print()
            print("No coordinate points found in requested test region.")
            return

        lat_slice_values = lat_selection.values
        lon_slice_values = lon_selection.values

        lat_start = float(np.min(lat_slice_values))
        lat_end = float(np.max(lat_slice_values))
        lon_start = float(np.min(lon_slice_values))
        lon_end = float(np.max(lon_slice_values))

        print()
        print("Actual latitude range :", lat_start, "to", lat_end)
        print("Actual longitude range:", lon_start, "to", lon_end)

        # Select the corresponding elevation rectangle.
        #
        # .sel with slice works for regularly ordered 1-D coordinates.
        data = elevation.sel(
            {
                lat_name: slice(lat_start, lat_end),
                lon_name: slice(lon_start, lon_end),
            }
        )

        # IMPORTANT:
        # This is where the remote subset is actually fetched.
        values = np.asarray(data.values)

        print()
        print("Fetched subset shape:", values.shape)
        print("Fetched dtype       :", values.dtype)

        vmin, vmax = safe_range(values)

        print("Valid minimum elevation:", vmin)
        print("Valid maximum elevation:", vmax)

        finite_count = int(np.isfinite(values).sum())
        total_count = int(values.size)

        print("Finite readings:", finite_count)
        print("Total readings :", total_count)

        if total_count > 0:
            valid_percent = 100.0 * finite_count / total_count
        else:
            valid_percent = 0.0

        print(f"Valid percent  : {valid_percent:.2f}%")

        metadata["test_region"] = {
            "requested_latitude": [lat_min, lat_max],
            "requested_longitude": [lon_min, lon_max],
            "actual_latitude": [lat_start, lat_end],
            "actual_longitude": [lon_start, lon_end],
            "shape": list(values.shape),
            "dtype": str(values.dtype),
            "finite_count": finite_count,
            "total_count": total_count,
            "valid_percent": valid_percent,
            "min_elevation": vmin,
            "max_elevation": vmax,
        }

        # ---------------------------------------------------------
        # Sample actual values
        # ---------------------------------------------------------

        print_header("Actual bathymetry samples")

        flat = values.reshape(-1)

        sample_count = min(10, flat.size)

        printed = 0

        for value in flat:
            if np.isfinite(value):
                print(
                    f"  elevation = {float(value):.3f} meters"
                )
                printed += 1

                if printed >= sample_count:
                    break

        if printed == 0:
            print("No finite values found in sample.")

        # ---------------------------------------------------------
        # Save provenance
        # ---------------------------------------------------------

        metadata_file = (
            METADATA_DIR / "gebco_2026_test_provenance.json"
        )

        with metadata_file.open(
            "w",
            encoding="utf-8",
        ) as f:
            json.dump(
                metadata,
                f,
                indent=2,
                ensure_ascii=False,
            )

        print()
        print("Provenance saved to:")
        print(metadata_file)

        print()
        print_header("GEBCO TEST COMPLETE")

        print(
            "SUCCESS: OceanSight can remotely query numerical "
            "GEBCO bathymetry."
        )

        print()
        print(
            "Next implementation step:"
        )
        print(
            "Create a chunked bathymetry downloader/cache using "
            "the same architecture as the HYCOM chunk store."
        )

    finally:
        ds.close()


if __name__ == "__main__":
    main()