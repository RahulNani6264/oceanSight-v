from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

import numpy as np

from .ocean_geometry import OceanGeometryEngine


PROJECT_ROOT = Path(__file__).resolve().parent.parent
REGION_FILE = (
    PROJECT_ROOT
    / "data"
    / "ocean_regions"
    / "RECCAP2_region_masks_all_v20221025.nc"
)


def test_source_mask_shape_is_converted_to_real_polygon() -> None:
    latitudes = np.array(
        [-1.5, -0.5, 0.5, 1.5],
        dtype=float,
    )
    longitudes = np.array(
        [0.5, 1.5, 2.5, 3.5],
        dtype=float,
    )

    mask = np.array(
        [
            [False, True, True, False],
            [True, True, True, False],
            [True, True, False, False],
            [False, False, False, False],
        ],
        dtype=bool,
    )

    geometry = OceanGeometryEngine._build_geometry_from_arrays(
        mask=mask,
        latitudes=latitudes,
        longitudes=longitudes,
    )

    assert geometry["type"] == "Polygon"
    assert geometry["polygon_count"] == 1
    assert geometry["ring_count"] == 1
    assert geometry["coordinates"]
    assert geometry["longitude_mode"] == "-180_to_180"


@unittest.skipUnless(
    importlib.util.find_spec("netCDF4") is not None,
    "netCDF4 is required for the real-region test",
)
def test_real_indian_ocean_mask_is_available() -> None:

    engine = OceanGeometryEngine(
        region_file=REGION_FILE,
    )

    boundary = engine.boundary(
        "Indian Ocean"
    )

    assert boundary.available is True
    assert boundary.ocean_name == "Indian Ocean"
    assert boundary.source_region == "indian"
    assert boundary.geometry is not None
    assert boundary.geometry["type"] in {
        "Polygon",
        "MultiPolygon",
    }
    assert boundary.geometry["coordinates"]
    assert boundary.synthetic_data is False
    assert boundary.interpolation is False
