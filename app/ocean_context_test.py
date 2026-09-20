from __future__ import annotations

import unittest

from .ocean_context import OceanContextEngine


class FakeRegionEngine:
    def identify_dict(self, latitude: float, longitude: float):
        return {
            "available": True,
            "ocean": {"name": "Indian Ocean", "source_region": "indian"},
            "requested": {"latitude": latitude, "longitude": longitude},
        }


class FakeGeometry:
    def __init__(self):
        self.geometry = {
            "type": "Polygon",
            "coordinates": [[[-1.0, -1.0], [1.0, -1.0], [1.0, 1.0], [-1.0, 1.0], [-1.0, -1.0]]],
        }
        self.available = True
        self.ocean_name = "Indian Ocean"
        self.source_region = "indian"
        self.bounding_box = {
            "min_longitude": 20.0,
            "min_latitude": -50.0,
            "max_longitude": 120.0,
            "max_latitude": 30.0,
        }

    def normalize_ocean_name(self, ocean):
        if str(ocean).lower().replace(" ocean", "") != "indian":
            raise ValueError("unsupported")
        return "Indian Ocean", "indian"

    def boundary(self, ocean):
        return self.geometry


class FakeTime:
    def window(self, **kwargs):
        return {"available": True, "counts": {"total": 1, "past": 1, "present": 0, "future": 0}, "times": []}


class FakeSensors:
    def discover_local(self, **kwargs):
        return [{"sensor_id": "argo:1:1", "sensor_type": "argo_float"}]


class TestOceanContextEngine(unittest.TestCase):
    def setUp(self):
        self.geometry = FakeGeometry()
        self.engine = OceanContextEngine(
            region_engine=FakeRegionEngine(),
            geometry_engine=self.geometry,
            time_engine=FakeTime(),
            sensor_engine=FakeSensors(),
        )
        # Adapt fake geometry's boundary call to return an object-like boundary.
        class BoundaryAdapter:
            available = True
            ocean_name = "Indian Ocean"
            source_region = "indian"
            geometry = self.geometry.geometry
            bounding_box = self.geometry.bounding_box

        self.geometry.boundary = lambda ocean: BoundaryAdapter()

    def test_ocean_context(self):
        result = self.engine.build_context(
            mode="ocean",
            ocean="Indian Ocean",
            variable="TEMP",
            include_sensors=False,
        )
        self.assertTrue(result["available"])
        self.assertEqual(result["mode"], "ocean")
        self.assertEqual(result["selection"]["ocean"]["name"], "Indian Ocean")
        self.assertEqual(result["spatial"]["type"], "ocean_basin")
        self.assertFalse(result["scientific_rules"]["synthetic_data"])

    def test_block_context_from_coordinate(self):
        result = self.engine.build_context(
            mode="block",
            latitude=10.0,
            longitude=80.0,
            radius_km=50.0,
            variable="TEMP",
        )
        self.assertEqual(result["mode"], "block")
        self.assertEqual(result["spatial"]["type"], "radius_block")
        self.assertEqual(result["sensors"]["count"], 1)


if __name__ == "__main__":
    unittest.main()
