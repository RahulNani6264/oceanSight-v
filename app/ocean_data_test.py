from __future__ import annotations

import math
import unittest

from .ocean_data import OceanDataEngine


class FakeVolume:
    def build_volume(self, **kwargs):
        vals = [[1.0, 2.0], [None, 4.0]]
        if kwargs["variable"] == "VVEL":
            vals = [[3.0, 4.0], [None, 0.0]]
        return {
            "available": True,
            "request": {"variable": kwargs["variable"]},
            "levels": [{
                "requested_depth_m": 0.0, "actual_depth_m": 0.0, "latitudes": [0.0, 1.0], "longitudes": [70.0, 71.0],
                "values": vals, "missing_mask": [[False, False], [True, False]],
                "water_mask": [[True, True], [False, True]], "actual_time_utc": kwargs["time_utc"]
            }],
            "variable": {"name": kwargs["variable"]},
            "source": {"provider": "INCOIS"}
        }

class FakeBathy:
    def build_surface(self, **kwargs): return {"available": True}

class FakeGeometry:
    def normalize_ocean_name(self, value): return "Indian Ocean", "indian"
    def boundary(self, value):
        class B:
            available=True; ocean_name="Indian Ocean"; source_region="indian"; geometry={"type":"Polygon","coordinates":[]}
            bounding_box={"min_longitude":60.0,"min_latitude":-20.0,"max_longitude":100.0,"max_latitude":25.0}
        return B()

class TestOceanDataEngine(unittest.TestCase):
    def setUp(self):
        self.e = OceanDataEngine(volume_engine=FakeVolume(), bathymetry_engine=FakeBathy(), geometry_engine=FakeGeometry())

    def test_current_speed_is_derived_from_real_components(self):
        result = self.e.build_data(mode="ocean", ocean="Indian Ocean", latitude=None, longitude=None, radius_km=50, time_utc="2026-09-11T00:00:00Z", variable="current_speed", depths_m=[0])
        values = result["data"]["levels"][0]["values"]
        self.assertAlmostEqual(values[0][0], math.hypot(1,3))
        self.assertAlmostEqual(values[0][1], math.hypot(2,4))
        self.assertIsNone(values[1][0])

    def test_block_selection_builds_radius_bbox(self):
        result = self.e.build_data(mode="block", ocean=None, latitude=10, longitude=80, radius_km=100, time_utc="2026-09-11T00:00:00Z", variable="temperature", depths_m=[0])
        bbox = result["selection"]["bounding_box"]
        self.assertLess(bbox["latitude_min"], 10)
        self.assertGreater(bbox["latitude_max"], 10)

if __name__ == "__main__": unittest.main()
