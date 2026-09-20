from __future__ import annotations

import unittest
from pathlib import Path

import numpy as np

from .ocean_bathymetry import OceanBathymetryEngine


class BathymetryUnitTests(unittest.TestCase):
    def test_bbox_validation(self) -> None:
        with self.assertRaises(ValueError):
            OceanBathymetryEngine._normalize_bbox(10, 5, 60, 70)

    def test_intersection(self) -> None:
        chunk = {
            "latitude_min": -10,
            "latitude_max": 0,
            "longitude_min": 60,
            "longitude_max": 70,
        }
        self.assertTrue(OceanBathymetryEngine._intersects(chunk, -5, 5, 65, 75))
        self.assertFalse(OceanBathymetryEngine._intersects(chunk, 1, 5, 65, 75))

    def test_finite_grid(self) -> None:
        grid = np.array([[1.0, np.nan], [-100.0, 2.0]])
        self.assertEqual(
            OceanBathymetryEngine._finite_grid(grid),
            [[1.0, None], [-100.0, 2.0]],
        )

    def test_existing_index_is_not_required_for_import(self) -> None:
        engine = OceanBathymetryEngine(index_path=Path("/does/not/exist"))
        with self.assertRaises(FileNotFoundError):
            engine._load_index()


if __name__ == "__main__":
    unittest.main()
