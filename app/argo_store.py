
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from .config import PROCESSED_DIR, RAW_DIR


# =============================================================================
# OCEANSIGHT-V
# INCOIS INDIAN ARGO LOCAL STORE
#
# This store is deliberately separate from the gridded ZAX store.
#
# Argo pressure:
#     PRES -> decibar
#
# Gridded ZAX:
#     ZAX -> meters
#
# NEVER silently convert one into the other.
#
# Preserved information:
#     PLATFORM_NUMBER
#     CYCLE_NUMBER
#     DIRECTION
#     time
#     JULD_LOCATION
#     latitude
#     longitude
#     PRES
#     PRES_QC
#     PRES_ADJUSTED
#     PRES_ADJUSTED_QC
#     TEMP
#     TEMP_QC
#     TEMP_ADJUSTED
#     TEMP_ADJUSTED_QC
#     PSAL
#     PSAL_QC
#     PSAL_ADJUSTED
#     PSAL_ADJUSTED_QC
# =============================================================================


ARGO_DB = PROCESSED_DIR / "argo_store.sqlite"

ARGO_NORMALIZED_DIR = (
    PROCESSED_DIR / "argo_normalized"
)

ARGO_PROVENANCE_DIR = (
    PROCESSED_DIR / "argo_provenance"
)

ARGO_NORMALIZED_DIR.mkdir(
    parents=True,
    exist_ok=True,
)

ARGO_PROVENANCE_DIR.mkdir(
    parents=True,
    exist_ok=True,
)


class ArgoStore:
    """
    Local SQLite store for real INCOIS Indian Argo observations.
    """

    def __init__(
        self,
        db_path: Path = ARGO_DB,
    ) -> None:
        self.db_path = Path(db_path)

        self.db_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self._initialize_database()

    # -------------------------------------------------------------------------
    # CONNECTION
    # -------------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.db_path
        )

        connection.row_factory = sqlite3.Row

        return connection

    # -------------------------------------------------------------------------
    # DATABASE
    # -------------------------------------------------------------------------

    def _initialize_database(self) -> None:
        with self._connect() as connection:

            connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                PRAGMA synchronous=NORMAL;

                CREATE TABLE IF NOT EXISTS argo_observations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,

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
                );

                CREATE INDEX IF NOT EXISTS
                idx_argo_platform
                ON argo_observations(platform_number);

                CREATE INDEX IF NOT EXISTS
                idx_argo_cycle
                ON argo_observations(
                    platform_number,
                    cycle_number
                );

                CREATE INDEX IF NOT EXISTS
                idx_argo_time
                ON argo_observations(profile_time_utc);

                CREATE INDEX IF NOT EXISTS
                idx_argo_location
                ON argo_observations(
                    latitude,
                    longitude
                );

                CREATE INDEX IF NOT EXISTS
                idx_argo_pressure
                ON argo_observations(
                    pres_dbar
                );

                CREATE INDEX IF NOT EXISTS
                idx_argo_temp
                ON argo_observations(
                    temp_c
                );

                CREATE INDEX IF NOT EXISTS
                idx_argo_salinity
                ON argo_observations(
                    psal_psu
                );

                CREATE INDEX IF NOT EXISTS
                idx_argo_source_profile
                ON argo_observations(
                    source_dataset,
                    platform_number,
                    cycle_number
                );
                """
            )

    # -------------------------------------------------------------------------
    # TIME
    # -------------------------------------------------------------------------

    @staticmethod
    def utc_now() -> str:
        return (
            datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )

    # -------------------------------------------------------------------------
    # NUMBER HELPERS
    # -------------------------------------------------------------------------

    @staticmethod
    def to_float(
        value: Any,
    ) -> float | None:

        if value is None:
            return None

        try:
            if pd.isna(value):
                return None
        except (TypeError, ValueError):
            pass

        try:
            return float(value)
        except (
            TypeError,
            ValueError,
        ):
            return None

    @staticmethod
    def to_int(
        value: Any,
    ) -> int | None:

        if value is None:
            return None

        try:
            if pd.isna(value):
                return None
        except (TypeError, ValueError):
            pass

        try:
            return int(float(value))
        except (
            TypeError,
            ValueError,
        ):
            return None

    @staticmethod
    def clean_text(
        value: Any,
    ) -> str | None:

        if value is None:
            return None

        try:
            if pd.isna(value):
                return None
        except (TypeError, ValueError):
            pass

        value = str(value).strip()

        if not value:
            return None

        if value.lower() in {
            "nan",
            "nat",
            "none",
            "null",
        }:
            return None

        return value

    # -------------------------------------------------------------------------
    # NORMALIZATION
    # -------------------------------------------------------------------------

    def normalize(
        self,
        input_csv: Path,
        output_name: str = (
            "Indian_ARGO_Floats_normalized.csv"
        ),
    ) -> Path:
        """
        Read a parsed INCOIS Argo CSV and produce a canonical normalized CSV.

        The raw source CSV remains untouched.
        """

        input_csv = Path(input_csv)

        if not input_csv.exists():
            raise FileNotFoundError(
                f"Argo CSV not found: {input_csv}"
            )

        dataframe = pd.read_csv(
            input_csv,
            dtype={
                "PLATFORM_NUMBER": "string",
                "DIRECTION": "string",
            },
        )

        required_columns = [
            "PLATFORM_NUMBER",
            "CYCLE_NUMBER",
            "DIRECTION",
            "time",
            "JULD_LOCATION",
            "latitude",
            "longitude",
            "PRES",
            "PRES_QC",
            "PRES_ADJUSTED",
            "PRES_ADJUSTED_QC",
            "TEMP",
            "TEMP_QC",
            "TEMP_ADJUSTED",
            "TEMP_ADJUSTED_QC",
            "PSAL",
            "PSAL_QC",
            "PSAL_ADJUSTED",
            "PSAL_ADJUSTED_QC",
        ]

        missing = [
            column
            for column in required_columns
            if column not in dataframe.columns
        ]

        if missing:
            raise ValueError(
                "The Argo CSV is missing required "
                "scientific fields:\n"
                + "\n".join(
                    f"  - {item}"
                    for item in missing
                )
            )

        normalized_rows: list[dict[str, Any]] = []

        ingested_at = self.utc_now()

        for _, row in dataframe.iterrows():

            platform = self.clean_text(
                row["PLATFORM_NUMBER"]
            )

            cycle = self.to_int(
                row["CYCLE_NUMBER"]
            )

            direction = self.clean_text(
                row["DIRECTION"]
            )

            profile_time = self.clean_text(
                row["time"]
            )

            juld_location = self.clean_text(
                row["JULD_LOCATION"]
            )

            latitude = self.to_float(
                row["latitude"]
            )

            longitude = self.to_float(
                row["longitude"]
            )

            pres = self.to_float(
                row["PRES"]
            )

            pres_adjusted = self.to_float(
                row["PRES_ADJUSTED"]
            )

            temp = self.to_float(
                row["TEMP"]
            )

            temp_adjusted = self.to_float(
                row["TEMP_ADJUSTED"]
            )

            psal = self.to_float(
                row["PSAL"]
            )

            psal_adjusted = self.to_float(
                row["PSAL_ADJUSTED"]
            )

            # -------------------------------------------------------------
            # We discard nothing scientifically.
            #
            # NaN / missing numeric values become NULL.
            # QC values remain exactly as supplied.
            # -------------------------------------------------------------

            normalized_rows.append(
                {
                    "platform_number": platform,
                    "cycle_number": cycle,
                    "direction": direction,

                    "profile_time_utc": profile_time,
                    "juld_location_utc": juld_location,

                    "latitude": latitude,
                    "longitude": longitude,

                    "pres_dbar": pres,
                    "pres_qc": self.clean_text(
                        row["PRES_QC"]
                    ),

                    "pres_adjusted_dbar": (
                        pres_adjusted
                    ),

                    "pres_adjusted_qc": (
                        self.clean_text(
                            row["PRES_ADJUSTED_QC"]
                        )
                    ),

                    "temp_c": temp,
                    "temp_qc": self.clean_text(
                        row["TEMP_QC"]
                    ),

                    "temp_adjusted_c": (
                        temp_adjusted
                    ),

                    "temp_adjusted_qc": (
                        self.clean_text(
                            row["TEMP_ADJUSTED_QC"]
                        )
                    ),

                    "psal_psu": psal,
                    "psal_qc": self.clean_text(
                        row["PSAL_QC"]
                    ),

                    "psal_adjusted_psu": (
                        psal_adjusted
                    ),

                    "psal_adjusted_qc": (
                        self.clean_text(
                            row["PSAL_ADJUSTED_QC"]
                        )
                    ),

                    "source": "INCOIS ERDDAP",
                    "source_dataset": (
                        "Indian_ARGO_Floats"
                    ),

                    "source_url": (
                        "https://erddap.incois.gov.in/"
                        "erddap/tabledap/"
                        "Indian_ARGO_Floats.csv"
                    ),

                    "ingested_at_utc": ingested_at,
                }
            )

        normalized = pd.DataFrame(
            normalized_rows
        )

        output_path = (
            ARGO_NORMALIZED_DIR
            / output_name
        )

        normalized.to_csv(
            output_path,
            index=False,
        )

        return output_path

    # -------------------------------------------------------------------------
    # INSERT
    # -------------------------------------------------------------------------

    def ingest(
        self,
        normalized_csv: Path,
    ) -> int:

        normalized_csv = Path(
            normalized_csv
        )

        if not normalized_csv.exists():
            raise FileNotFoundError(
                f"Normalized Argo CSV not found: "
                f"{normalized_csv}"
            )

        dataframe = pd.read_csv(
            normalized_csv,
            keep_default_na=True,
        )

        if dataframe.empty:
            return 0

        inserted = 0

        with self._connect() as connection:

            for _, row in dataframe.iterrows():

                connection.execute(
                    """
                    INSERT OR IGNORE INTO argo_observations (
                        platform_number,
                        cycle_number,
                        direction,
                        profile_time_utc,
                        juld_location_utc,
                        latitude,
                        longitude,
                        pres_dbar,
                        pres_qc,
                        pres_adjusted_dbar,
                        pres_adjusted_qc,
                        temp_c,
                        temp_qc,
                        temp_adjusted_c,
                        temp_adjusted_qc,
                        psal_psu,
                        psal_qc,
                        psal_adjusted_psu,
                        psal_adjusted_qc,
                        source,
                        source_dataset,
                        source_url,
                        ingested_at_utc
                    )
                    VALUES (
                        ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?, ?, ?
                    )
                    """,
                    (
                        self.clean_text(
                            row["platform_number"]
                        ),

                        self.to_int(
                            row["cycle_number"]
                        ),

                        self.clean_text(
                            row["direction"]
                        ),

                        self.clean_text(
                            row["profile_time_utc"]
                        ),

                        self.clean_text(
                            row["juld_location_utc"]
                        ),

                        self.to_float(
                            row["latitude"]
                        ),

                        self.to_float(
                            row["longitude"]
                        ),

                        self.to_float(
                            row["pres_dbar"]
                        ),

                        self.clean_text(
                            row["pres_qc"]
                        ),

                        self.to_float(
                            row["pres_adjusted_dbar"]
                        ),

                        self.clean_text(
                            row["pres_adjusted_qc"]
                        ),

                        self.to_float(
                            row["temp_c"]
                        ),

                        self.clean_text(
                            row["temp_qc"]
                        ),

                        self.to_float(
                            row["temp_adjusted_c"]
                        ),

                        self.clean_text(
                            row["temp_adjusted_qc"]
                        ),

                        self.to_float(
                            row["psal_psu"]
                        ),

                        self.clean_text(
                            row["psal_qc"]
                        ),

                        self.to_float(
                            row["psal_adjusted_psu"]
                        ),

                        self.clean_text(
                            row["psal_adjusted_qc"]
                        ),

                        self.clean_text(
                            row["source"]
                        ) or "INCOIS ERDDAP",

                        self.clean_text(
                            row["source_dataset"]
                        ) or "Indian_ARGO_Floats",

                        self.clean_text(
                            row["source_url"]
                        ) or "",

                        self.clean_text(
                            row["ingested_at_utc"]
                        ) or self.utc_now(),
                    ),
                )

                inserted += 1

        return inserted

    # -------------------------------------------------------------------------
    # PROFILE QUERY
    # -------------------------------------------------------------------------

    def get_profile(
        self,
        platform_number: str,
        cycle_number: int,
    ) -> list[dict[str, Any]]:

        with self._connect() as connection:

            rows = connection.execute(
                """
                SELECT
                    platform_number,
                    cycle_number,
                    direction,
                    profile_time_utc,
                    juld_location_utc,
                    latitude,
                    longitude,

                    pres_dbar,
                    pres_qc,
                    pres_adjusted_dbar,
                    pres_adjusted_qc,

                    temp_c,
                    temp_qc,
                    temp_adjusted_c,
                    temp_adjusted_qc,

                    psal_psu,
                    psal_qc,
                    psal_adjusted_psu,
                    psal_adjusted_qc,

                    source,
                    source_dataset,
                    source_url,
                    ingested_at_utc

                FROM argo_observations

                WHERE platform_number = ?
                  AND cycle_number = ?

                ORDER BY
                    pres_dbar ASC
                """,
                (
                    platform_number,
                    cycle_number,
                ),
            ).fetchall()

        return [
            dict(row)
            for row in rows
        ]

    # -------------------------------------------------------------------------
    # LOCATION QUERY
    # -------------------------------------------------------------------------

    def find_near_location(
        self,
        latitude: float,
        longitude: float,
        radius_degrees: float = 2.0,
        limit: int = 100,
    ) -> list[dict[str, Any]]:

        with self._connect() as connection:

            rows = connection.execute(
                """
                SELECT
                    platform_number,
                    cycle_number,
                    profile_time_utc,
                    latitude,
                    longitude,
                    COUNT(*) AS measurement_count,
                    MIN(pres_dbar) AS minimum_pressure_dbar,
                    MAX(pres_dbar) AS maximum_pressure_dbar

                FROM argo_observations

                WHERE latitude BETWEEN ?
                              AND ?
                  AND longitude BETWEEN ?
                              AND ?

                GROUP BY
                    platform_number,
                    cycle_number,
                    profile_time_utc,
                    latitude,
                    longitude

                ORDER BY
                    ABS(latitude - ?) +
                    ABS(longitude - ?)

                LIMIT ?
                """,
                (
                    latitude - radius_degrees,
                    latitude + radius_degrees,
                    longitude - radius_degrees,
                    longitude + radius_degrees,
                    latitude,
                    longitude,
                    limit,
                ),
            ).fetchall()

        return [
            dict(row)
            for row in rows
        ]

    # -------------------------------------------------------------------------
    # STATISTICS
    # -------------------------------------------------------------------------

    def count(self) -> int:

        with self._connect() as connection:

            row = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM argo_observations
                """
            ).fetchone()

        return int(row["count"])

    def unique_floats(self) -> int:

        with self._connect() as connection:

            row = connection.execute(
                """
                SELECT COUNT(
                    DISTINCT platform_number
                ) AS count
                FROM argo_observations
                """
            ).fetchone()

        return int(row["count"])

    def unique_profiles(self) -> int:

        with self._connect() as connection:

            row = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM (
                    SELECT DISTINCT
                        platform_number,
                        cycle_number
                    FROM argo_observations
                )
                """
            ).fetchone()

        return int(row["count"])

    def pressure_range(self) -> tuple[
        float | None,
        float | None,
    ]:

        with self._connect() as connection:

            row = connection.execute(
                """
                SELECT
                    MIN(pres_dbar) AS minimum,
                    MAX(pres_dbar) AS maximum
                FROM argo_observations
                """
            ).fetchone()

        return (
            self.to_float(row["minimum"]),
            self.to_float(row["maximum"]),
        )

    def temperature_range(self) -> tuple[
        float | None,
        float | None,
    ]:

        with self._connect() as connection:

            row = connection.execute(
                """
                SELECT
                    MIN(temp_c) AS minimum,
                    MAX(temp_c) AS maximum
                FROM argo_observations
                """
            ).fetchone()

        return (
            self.to_float(row["minimum"]),
            self.to_float(row["maximum"]),
        )

    def salinity_range(self) -> tuple[
        float | None,
        float | None,
    ]:

        with self._connect() as connection:

            row = connection.execute(
                """
                SELECT
                    MIN(psal_psu) AS minimum,
                    MAX(psal_psu) AS maximum
                FROM argo_observations
                """
            ).fetchone()

        return (
            self.to_float(row["minimum"]),
            self.to_float(row["maximum"]),
        )


def build_argo_store() -> None:
    """
    Build the local Argo SQLite store from the verified test response.
    """

    raw_parsed = (
        RAW_DIR
        / "Indian_ARGO_Floats_test_parsed.csv"
    )

    if not raw_parsed.exists():

        raise FileNotFoundError(
            f"Expected Argo test file was not found:\n"
            f"{raw_parsed}\n\n"
            "Run first:\n"
            "python -m app.argo_test"
        )

    print("=" * 80)
    print("OCEANSIGHT-V")
    print("BUILD INCOIS ARGO STORE")
    print("=" * 80)

    store = ArgoStore()

    print()
    print("DATABASE")
    print("-" * 80)
    print(store.db_path)

    print()
    print("INPUT")
    print("-" * 80)
    print(raw_parsed)

    # -------------------------------------------------------------------------
    # NORMALIZE
    # -------------------------------------------------------------------------

    normalized_path = store.normalize(
        raw_parsed
    )

    print()
    print("NORMALIZED FILE")
    print("-" * 80)
    print(normalized_path)

    # -------------------------------------------------------------------------
    # INSERT
    # -------------------------------------------------------------------------

    inserted = store.ingest(
        normalized_path
    )

    print()
    print("ROWS INSERTED")
    print("-" * 80)
    print(inserted)

    # -------------------------------------------------------------------------
    # PROVENANCE
    # -------------------------------------------------------------------------

    provenance = {
        "provider": "INCOIS",
        "service": "ERDDAP tabledap",
        "dataset": "Indian_ARGO_Floats",

        "source_url": (
            "https://erddap.incois.gov.in/"
            "erddap/tabledap/"
            "Indian_ARGO_Floats"
        ),

        "scientific_fields": {
            "PRES": {
                "meaning": "Sea-water pressure",
                "units": "decibar",
            },
            "TEMP": {
                "meaning": "In-situ temperature",
                "units": "degree_Celsius",
            },
            "PSAL": {
                "meaning": "Practical salinity",
                "units": "PSU",
            },
        },

        "quality_control": [
            "PRES_QC",
            "TEMP_QC",
            "PSAL_QC",
            "PRES_ADJUSTED_QC",
            "TEMP_ADJUSTED_QC",
            "PSAL_ADJUSTED_QC",
        ],

        "identity_fields": [
            "PLATFORM_NUMBER",
            "CYCLE_NUMBER",
            "DIRECTION",
        ],

        "coordinates": [
            "time",
            "JULD_LOCATION",
            "latitude",
            "longitude",
        ],

        "important_rule": (
            "Argo PRES is stored in decibar and is kept separate "
            "from the ZAX coordinate used by INCOIS gridded products."
        ),
    }

    provenance["store_statistics"] = {
        "rows": store.count(),
        "unique_floats": store.unique_floats(),
        "unique_profiles": store.unique_profiles(),
        "pressure_range_dbar": store.pressure_range(),
        "temperature_range_c": store.temperature_range(),
        "salinity_range_psu": store.salinity_range(),
    }

    provenance_path = (
        ARGO_PROVENANCE_DIR
        / "Indian_ARGO_Floats_provenance.json"
    )

    provenance_path.write_text(
        json.dumps(
            provenance,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print()
    print("PROVENANCE")
    print("-" * 80)
    print(provenance_path)

    # -------------------------------------------------------------------------
    # SUMMARY
    # -------------------------------------------------------------------------

    print()
    print("=" * 80)
    print("ARGO STORE SUMMARY")
    print("=" * 80)

    print(
        "Total observations:",
        store.count(),
    )

    print(
        "Unique floats:",
        store.unique_floats(),
    )

    print(
        "Unique profiles:",
        store.unique_profiles(),
    )

    pressure_min, pressure_max = (
        store.pressure_range()
    )

    temp_min, temp_max = (
        store.temperature_range()
    )

    sal_min, sal_max = (
        store.salinity_range()
    )

    print(
        "Pressure range:",
        pressure_min,
        "to",
        pressure_max,
        "dbar",
    )

    print(
        "Temperature range:",
        temp_min,
        "to",
        temp_max,
        "°C",
    )

    print(
        "Salinity range:",
        sal_min,
        "to",
        sal_max,
        "PSU",
    )

    print()
    print("ARGO STORE BUILD COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    build_argo_store()

