from __future__ import annotations

import unittest

import numpy as np

from .ocean_volume import OceanVolumeEngine


class FakeBoundary:
    available = True
    ocean_name = "Indian Ocean"
    source_region = "indian"
    geometry = {
        "type": "Polygon",
        "coordinates": [[
            [0.0, 0.0],
            [2.0, 0.0],
            [2.0, 2.0],
            [0.0, 2.0],
            [0.0, 0.0],
        ]],
        "polygon_count": 1,
        "ring_count": 1,
    }
    bounding_box = {
        "min_longitude": 0.0,
        "min_latitude": 0.0,
        "max_longitude": 2.0,
        "max_latitude": 2.0,
    }


class FakeGeometryEngine:
    def boundary(self, ocean: str):
        return FakeBoundary()


class FakeSliceEngine:
    def query_dict(self, **kwargs):
        return {
            "available": True,
            "requested": kwargs,
            "actual": {
                "depth_m": kwargs["depth_m"],
                "time_utc": kwargs["time_utc"],
            },
            "variable": {
                "name": kwargs["variable"],
                "units": "degree_Celsius",
            },
            "grid": {
                "latitudes": [0.5, 1.5],
                "longitudes": [0.5, 1.5],
                "values": [[10.0, 11.0], [12.0, 13.0]],
                "missing_mask": [[False, False], [False, False]],
            },
            "source": {
                "provider": "INCOIS",
                "datasets": ["test.nc"],
                "source_urls": ["https://example.invalid/test.nc"],
                "chunk_files": ["test.npz"],
                "provenance_paths": ["test.json"],
            },
            "provenance": {
                "synthetic_data": False,
                "interpolation": False,
            },
        }


def test_water_mask_only_marks_cells_inside_ocean() -> None:
    mask = OceanVolumeEngine._water_mask(
        latitudes=[0.5, 2.5],
        longitudes=[0.5, 2.5],
        geometry=FakeBoundary.geometry,
    )

    assert mask.tolist() == [[True, False], [False, False]]


def test_build_volume_returns_multiple_real_depth_levels() -> None:
    engine = OceanVolumeEngine(
        slice_engine=FakeSliceEngine(),
        geometry_engine=FakeGeometryEngine(),
    )

    result = engine.build_volume(
        ocean="Indian Ocean",
        latitude_min=0.0,
        latitude_max=2.0,
        longitude_min=0.0,
        longitude_max=2.0,
        time_utc="2026-09-10T06:00:00Z",
        variable="TEMP",
        depths_m=[0.0, 100.0],
    )

    assert result["available"] is True
    assert result["variable"]["name"] == "TEMP"
    assert result["scientific_rules"]["synthetic_data"] is False
    assert result["scientific_rules"]["interpolation"] is False
    assert len(result["levels"]) == 2
    assert result["levels"][0]["water_mask"] == [[True, True], [True, True]]
    assert result["levels"][0]["valid_value_count"] == 4


if __name__ == "__main__":
    unittest.main()
