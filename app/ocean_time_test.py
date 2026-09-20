from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

_module_path = Path(__file__).resolve().with_name("ocean_time.py")
_spec = importlib.util.spec_from_file_location("ocean_time", _module_path)
if _spec is None or _spec.loader is None:  # pragma: no cover
    raise ImportError(f"Could not load module from {_module_path}")
_module = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _module
_spec.loader.exec_module(_module)
OceanTimeEngine = _module.OceanTimeEngine


class OceanTimeEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.catalog_path = Path(self.tmp.name) / "hycom_times.json"
        self.catalog_path.write_text(
            json.dumps(
                {
                    "times": [
                        {
                            "time_utc": "2026-09-12T12:00:00Z",
                            "dataset": "a.nc",
                            "dataset_url": "https://example/a.nc",
                            "time_index": 10,
                            "datasets": ["a.nc"],
                            "dataset_urls": ["https://example/a.nc"],
                        },
                        {
                            "time_utc": "2026-09-13T00:00:00Z",
                            "dataset": "a.nc",
                            "dataset_url": "https://example/a.nc",
                            "time_index": 12,
                            "datasets": ["a.nc"],
                            "dataset_urls": ["https://example/a.nc"],
                        },
                        {
                            "time_utc": "2026-09-13T12:00:00Z",
                            "dataset": "a.nc",
                            "dataset_url": "https://example/a.nc",
                            "time_index": 14,
                            "datasets": ["a.nc"],
                            "dataset_urls": ["https://example/a.nc"],
                        },
                    ]
                }
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_window_uses_only_real_source_times(self) -> None:
        engine = OceanTimeEngine(self.catalog_path)
        result = engine.window(
            reference_time_utc="2026-09-13T00:00:00Z",
            past_hours=24,
            future_hours=24,
        )
        self.assertEqual(result["counts"]["past"], 1)
        self.assertEqual(result["counts"]["present"], 1)
        self.assertEqual(result["counts"]["future"], 1)
        self.assertEqual(len(result["times"]), 3)
        self.assertFalse(result["scientific_rules"]["synthetic_times"])
        self.assertFalse(result["scientific_rules"]["interpolation"])

    def test_calendar_range_returns_existing_source_times_only(self) -> None:
        engine = OceanTimeEngine(self.catalog_path)
        result = engine.range(
            "2026-09-12T18:00:00Z",
            "2026-09-13T06:00:00Z",
        )
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["times"][0]["time_utc"], "2026-09-13T00:00:00Z")

    def test_rejects_reverse_range(self) -> None:
        engine = OceanTimeEngine(self.catalog_path)
        with self.assertRaises(ValueError):
            engine.range(
                "2026-09-13T12:00:00Z",
                "2026-09-12T12:00:00Z",
            )


if __name__ == "__main__":
    unittest.main()
