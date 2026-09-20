from __future__ import annotations

import math
import sqlite3
import tempfile
import unittest
from pathlib import Path

from .ocean_sensors import OceanSensorEngine


class OceanSensorEngineTest(unittest.TestCase):
    def _make_db(self, directory: Path) -> Path:
        db_path = directory / "argo.sqlite"
        connection = sqlite3.connect(db_path)
        connection.execute(
            """
            CREATE TABLE argo_observations (
                id INTEGER PRIMARY KEY,
                platform_number TEXT,
                cycle_number INTEGER,
                direction TEXT,
                profile_time_utc TEXT,
                juld_location_utc TEXT,
                latitude REAL,
                longitude REAL,
                pres_dbar REAL,
                pres_qc TEXT,
                pres_adjusted_dbar REAL,
                pres_adjusted_qc TEXT,
                temp_c REAL,
                temp_qc TEXT,
                temp_adjusted_c REAL,
                temp_adjusted_qc TEXT,
                psal_psu REAL,
                psal_qc TEXT,
                psal_adjusted_psu REAL,
                psal_adjusted_qc TEXT,
                source TEXT NOT NULL,
                source_dataset TEXT NOT NULL,
                source_url TEXT NOT NULL,
                ingested_at_utc TEXT NOT NULL
            )
            """
        )
        rows = [
            (
                1, "2900001", 1, "A", "2026-09-12T00:00:00Z", "2026-09-12T00:00:00Z",
                10.0, 80.0, 10.0, "1", 10.0, "1", 25.0, "1", 25.0, "1",
                35.0, "1", 35.0, "1", "INCOIS ERDDAP", "Indian_ARGO_Floats", "https://example.test", "2026-09-12T00:00:00Z"
            ),
            (
                2, "2900002", 1, "A", "2026-09-11T00:00:00Z", "2026-09-11T00:00:00Z",
                10.5, 80.5, 10.0, "1", 10.0, "1", 25.0, "1", 25.0, "1",
                35.0, "1", 35.0, "1", "INCOIS ERDDAP", "Indian_ARGO_Floats", "https://example.test", "2026-09-12T00:00:00Z"
            ),
        ]
        connection.executemany(
            "INSERT INTO argo_observations VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
        connection.commit()
        connection.close()
        return db_path

    def test_great_circle_discovery(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._make_db(Path(tmp))
            engine = OceanSensorEngine(db_path=db_path)
            sensors = engine.discover_local(
                latitude=10.0,
                longitude=80.0,
                radius_km=20.0,
            )
            self.assertEqual(len(sensors), 1)
            self.assertEqual(sensors[0]["sensor_type"], "argo_float")
            self.assertFalse(sensors[0]["vertical_information"]["pressure_is_depth"])
            self.assertTrue(math.isfinite(sensors[0]["distance_from_query_km"]))

    def test_sensor_types_explicitly_mark_unconnected_sources(self) -> None:
        catalog = OceanSensorEngine.sensor_types()
        self.assertTrue(any(item["id"] == "argo_float" and item["connected"] for item in catalog))
        self.assertTrue(any(item["id"] == "surface_buoy" and not item["connected"] for item in catalog))


if __name__ == "__main__":
    unittest.main()
