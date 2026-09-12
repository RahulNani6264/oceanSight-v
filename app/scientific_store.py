
from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from .config import PROCESSED_DIR, RAW_DIR


# -----------------------------------------------------------------------------
# OceanSight-V Scientific Store
#
# Purpose:
#   Convert verified INCOIS CSV responses into:
#
#   1. A normalized local CSV archive
#   2. A SQLite query/index database
#   3. A metadata/provenance JSON document
#
# Important:
#   - Original pressure/depth coordinate (ZAX) is preserved.
#   - TIME, LATITUDE, LONGITUDE are preserved.
#   - Missing/fill values remain identifiable.
#   - Source and dataset provenance are stored.
#   - No synthetic values are created.
# -----------------------------------------------------------------------------


STORE_DB = PROCESSED_DIR / "scientific_store.sqlite"
NORMALIZED_DIR = PROCESSED_DIR / "normalized"
PROVENANCE_DIR = PROCESSED_DIR / "provenance"

NORMALIZED_DIR.mkdir(parents=True, exist_ok=True)
PROVENANCE_DIR.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class Observation:
    dataset_id: str
    variable: str

    timestamp_utc: str

    latitude: float
    longitude: float

    pressure_m: float | None
    depth_m: float | None

    value: float | None
    units: str

    is_missing: bool

    source: str
    source_url: str

    ingested_at_utc: str


class ScientificStore:
    """
    Local scientific archive and query index for OceanSight-V.
    """

    def __init__(self, db_path: Path = STORE_DB) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize_database()

    # -------------------------------------------------------------------------
    # DATABASE INITIALIZATION
    # -------------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize_database(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                PRAGMA synchronous=NORMAL;

                CREATE TABLE IF NOT EXISTS observations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,

                    dataset_id TEXT NOT NULL,
                    variable TEXT NOT NULL,

                    timestamp_utc TEXT NOT NULL,

                    latitude REAL NOT NULL,
                    longitude REAL NOT NULL,

                    pressure_m REAL,
                    depth_m REAL,

                    value REAL,
                    units TEXT NOT NULL,

                    is_missing INTEGER NOT NULL,

                    source TEXT NOT NULL,
                    source_url TEXT NOT NULL,

                    ingested_at_utc TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_obs_dataset_variable
                ON observations(dataset_id, variable);

                CREATE INDEX IF NOT EXISTS idx_obs_time
                ON observations(timestamp_utc);

                CREATE INDEX IF NOT EXISTS idx_obs_lat_lon
                ON observations(latitude, longitude);

                CREATE INDEX IF NOT EXISTS idx_obs_pressure
                ON observations(pressure_m);

                CREATE INDEX IF NOT EXISTS idx_obs_variable_time
                ON observations(variable, timestamp_utc);

                CREATE TABLE IF NOT EXISTS ingestion_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,

                    dataset_id TEXT NOT NULL,
                    variable TEXT NOT NULL,

                    input_file TEXT NOT NULL,
                    normalized_file TEXT NOT NULL,

                    row_count INTEGER NOT NULL,
                    valid_count INTEGER NOT NULL,
                    missing_count INTEGER NOT NULL,

                    started_at_utc TEXT NOT NULL,
                    completed_at_utc TEXT NOT NULL,

                    source_url TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS dataset_metadata (
                    dataset_id TEXT PRIMARY KEY,

                    metadata_json TEXT NOT NULL,

                    updated_at_utc TEXT NOT NULL
                );
                """
            )

    # -------------------------------------------------------------------------
    # TIME
    # -------------------------------------------------------------------------

    @staticmethod
    def _utc_now() -> str:
        return (
            datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )

    # -------------------------------------------------------------------------
    # NORMALIZATION
    # -------------------------------------------------------------------------

    @staticmethod
    def _find_column(
        columns: Iterable[str],
        candidates: Iterable[str],
    ) -> str | None:
        lookup = {str(column).strip().lower(): str(column) for column in columns}

        for candidate in candidates:
            found = lookup.get(candidate.lower())
            if found is not None:
                return found

        return None

    @staticmethod
    def _as_float(value: Any) -> float | None:
        if value is None:
            return None

        if pd.isna(value):
            return None

        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _parse_units_from_header(
        header_lines: list[str],
        variable: str,
    ) -> str:
        """
        INCOIS ERDDAP CSV commonly contains:

        time,ZAX,latitude,longitude,TEMP
        UTC,METERS,degrees_north,degrees_east,degs
        ...
        """
        if len(header_lines) >= 2:
            columns = [item.strip() for item in header_lines[0].split(",")]
            units = [item.strip() for item in header_lines[1].split(",")]

            for index, column in enumerate(columns):
                if column.strip().lower() == variable.lower():
                    if index < len(units):
                        return units[index]

        return "unknown"

    def normalize_erddap_csv(
        self,
        csv_path: Path,
        dataset_id: str,
        variable: str,
        source_url: str,
        output_name: str | None = None,
    ) -> Path:
        """
        Normalize an ERDDAP CSV into a canonical local CSV.

        Required source columns:
            time
            ZAX
            latitude
            longitude
            <variable>

        The second ERDDAP line contains units, so it is preserved separately
        before pandas parses the actual rows.
        """

        csv_path = Path(csv_path)

        if not csv_path.exists():
            raise FileNotFoundError(f"Input CSV does not exist: {csv_path}")

        text = csv_path.read_text(encoding="utf-8")

        raw_lines = text.splitlines()

        if len(raw_lines) < 3:
            raise ValueError(
                f"ERDDAP response is too small to normalize: {csv_path}"
            )

        units = self._parse_units_from_header(raw_lines[:2], variable)

        # Skip the ERDDAP units row.
        data_lines = [raw_lines[0]] + raw_lines[2:]

        from io import StringIO

        dataframe = pd.read_csv(StringIO("\n".join(data_lines)))

        dataframe.columns = [
            str(column).strip()
            for column in dataframe.columns
        ]

        time_column = self._find_column(
            dataframe.columns,
            ["time"],
        )

        zax_column = self._find_column(
            dataframe.columns,
            ["ZAX", "zax"],
        )

        latitude_column = self._find_column(
            dataframe.columns,
            ["latitude", "lat"],
        )

        longitude_column = self._find_column(
            dataframe.columns,
            ["longitude", "lon"],
        )

        value_column = self._find_column(
            dataframe.columns,
            [variable],
        )

        missing_columns = []

        if time_column is None:
            missing_columns.append("time")

        if zax_column is None:
            missing_columns.append("ZAX")

        if latitude_column is None:
            missing_columns.append("latitude")

        if longitude_column is None:
            missing_columns.append("longitude")

        if value_column is None:
            missing_columns.append(variable)

        if missing_columns:
            raise ValueError(
                "Required columns are missing: "
                + ", ".join(missing_columns)
            )

        normalized_rows: list[dict[str, Any]] = []

        ingested_at = self._utc_now()

        for _, row in dataframe.iterrows():
            timestamp_value = str(row[time_column]).strip()

            if timestamp_value in {"", "nan", "NaT"}:
                continue

            latitude = self._as_float(row[latitude_column])
            longitude = self._as_float(row[longitude_column])
            pressure = self._as_float(row[zax_column])
            value = self._as_float(row[value_column])

            if latitude is None or longitude is None:
                continue

            # INCOIS ZAX is a vertical coordinate in meters.
            # We preserve it as BOTH pressure_m and depth_m here because
            # this particular dataset explicitly describes ZAX units as METERS.
            #
            # We do NOT perform a pressure conversion such as dbar -> meters.
            # A future dataset with true pressure in dbar will remain separate.
            depth_m = pressure

            is_missing = (
                value is None
                or value == -9999.0
            )

            if is_missing:
                stored_value: float | None = None
            else:
                stored_value = value

            normalized_rows.append(
                {
                    "dataset_id": dataset_id,
                    "variable": variable,
                    "timestamp_utc": timestamp_value,
                    "latitude": latitude,
                    "longitude": longitude,
                    "pressure_m": pressure,
                    "depth_m": depth_m,
                    "value": stored_value,
                    "units": units,
                    "is_missing": is_missing,
                    "source": "INCOIS ERDDAP",
                    "source_url": source_url,
                    "ingested_at_utc": ingested_at,
                }
            )

        normalized_dataframe = pd.DataFrame(normalized_rows)

        if output_name is None:
            output_name = (
                f"{dataset_id}_{variable}_normalized.csv"
            )

        output_path = NORMALIZED_DIR / output_name

        normalized_dataframe.to_csv(
            output_path,
            index=False,
        )

        return output_path

    # -------------------------------------------------------------------------
    # INSERT NORMALIZED DATA
    # -------------------------------------------------------------------------

    def ingest_normalized_csv(
        self,
        normalized_csv: Path,
    ) -> int:
        normalized_csv = Path(normalized_csv)

        if not normalized_csv.exists():
            raise FileNotFoundError(
                f"Normalized CSV does not exist: {normalized_csv}"
            )

        dataframe = pd.read_csv(normalized_csv)

        required = {
            "dataset_id",
            "variable",
            "timestamp_utc",
            "latitude",
            "longitude",
            "pressure_m",
            "depth_m",
            "value",
            "units",
            "is_missing",
            "source",
            "source_url",
            "ingested_at_utc",
        }

        missing = required - set(dataframe.columns)

        if missing:
            raise ValueError(
                "Normalized CSV missing columns: "
                + ", ".join(sorted(missing))
            )

        rows = dataframe.to_dict(orient="records")

        if not rows:
            return 0

        dataset_id = str(rows[0]["dataset_id"])
        variable = str(rows[0]["variable"])
        source_url = str(rows[0]["source_url"])

        started_at = self._utc_now()

        valid_count = 0
        missing_count = 0

        with self._connect() as connection:
            for row in rows:
                value = self._as_float(row["value"])

                is_missing = bool(
                    int(row["is_missing"])
                )

                if is_missing:
                    missing_count += 1
                else:
                    valid_count += 1

                connection.execute(
                    """
                    INSERT INTO observations (
                        dataset_id,
                        variable,
                        timestamp_utc,
                        latitude,
                        longitude,
                        pressure_m,
                        depth_m,
                        value,
                        units,
                        is_missing,
                        source,
                        source_url,
                        ingested_at_utc
                    )
                    VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                    )
                    """,
                    (
                        dataset_id,
                        variable,
                        str(row["timestamp_utc"]),
                        float(row["latitude"]),
                        float(row["longitude"]),
                        self._as_float(row["pressure_m"]),
                        self._as_float(row["depth_m"]),
                        value,
                        str(row["units"]),
                        int(is_missing),
                        str(row["source"]),
                        str(row["source_url"]),
                        str(row["ingested_at_utc"]),
                    ),
                )

            completed_at = self._utc_now()

            connection.execute(
                """
                INSERT INTO ingestion_runs (
                    dataset_id,
                    variable,
                    input_file,
                    normalized_file,
                    row_count,
                    valid_count,
                    missing_count,
                    started_at_utc,
                    completed_at_utc,
                    source_url
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    dataset_id,
                    variable,
                    str(normalized_csv),
                    str(normalized_csv),
                    len(rows),
                    valid_count,
                    missing_count,
                    started_at,
                    completed_at,
                    source_url,
                ),
            )

        return len(rows)

    # -------------------------------------------------------------------------
    # METADATA / PROVENANCE
    # -------------------------------------------------------------------------

    def save_dataset_metadata(
        self,
        dataset_id: str,
        metadata: dict[str, Any],
    ) -> Path:
        updated_at = self._utc_now()

        payload = {
            "dataset_id": dataset_id,
            "updated_at_utc": updated_at,
            "metadata": metadata,
        }

        output_path = (
            PROVENANCE_DIR
            / f"{dataset_id}_provenance.json"
        )

        output_path.write_text(
            json.dumps(
                payload,
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO dataset_metadata (
                    dataset_id,
                    metadata_json,
                    updated_at_utc
                )
                VALUES (?, ?, ?)
                ON CONFLICT(dataset_id)
                DO UPDATE SET
                    metadata_json = excluded.metadata_json,
                    updated_at_utc = excluded.updated_at_utc
                """,
                (
                    dataset_id,
                    json.dumps(
                        payload,
                        ensure_ascii=False,
                    ),
                    updated_at,
                ),
            )

        return output_path

    # -------------------------------------------------------------------------
    # QUERY HELPERS
    # -------------------------------------------------------------------------

    def count_observations(
        self,
        dataset_id: str | None = None,
        variable: str | None = None,
    ) -> int:
        conditions = []
        parameters: list[Any] = []

        if dataset_id is not None:
            conditions.append("dataset_id = ?")
            parameters.append(dataset_id)

        if variable is not None:
            conditions.append("variable = ?")
            parameters.append(variable)

        where = ""

        if conditions:
            where = "WHERE " + " AND ".join(conditions)

        query = f"""
            SELECT COUNT(*) AS count
            FROM observations
            {where}
        """

        with self._connect() as connection:
            row = connection.execute(
                query,
                parameters,
            ).fetchone()

        return int(row["count"])

    def latest_observation_time(
        self,
        dataset_id: str,
        variable: str,
    ) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT MAX(timestamp_utc) AS latest_time
                FROM observations
                WHERE dataset_id = ?
                  AND variable = ?
                """,
                (
                    dataset_id,
                    variable,
                ),
            ).fetchone()

        if row is None:
            return None

        return row["latest_time"]

    def profile(
        self,
        dataset_id: str,
        variable: str,
        latitude: float,
        longitude: float,
        timestamp_utc: str | None = None,
    ) -> list[Observation]:

        parameters: list[Any] = [
            dataset_id,
            variable,
            latitude,
            longitude,
        ]

        query = """
            SELECT
                dataset_id,
                variable,
                timestamp_utc,
                latitude,
                longitude,
                pressure_m,
                depth_m,
                value,
                units,
                is_missing,
                source,
                source_url,
                ingested_at_utc
            FROM observations
            WHERE dataset_id = ?
              AND variable = ?
              AND ABS(latitude - ?) < 0.000001
              AND ABS(longitude - ?) < 0.000001
        """

        if timestamp_utc is not None:
            query += """
              AND timestamp_utc = ?
            """
            parameters.append(timestamp_utc)

        query += """
            ORDER BY pressure_m ASC
        """

        with self._connect() as connection:
            rows = connection.execute(
                query,
                parameters,
            ).fetchall()

        result: list[Observation] = []

        for row in rows:
            result.append(
                Observation(
                    dataset_id=row["dataset_id"],
                    variable=row["variable"],
                    timestamp_utc=row["timestamp_utc"],
                    latitude=float(row["latitude"]),
                    longitude=float(row["longitude"]),
                    pressure_m=(
                        float(row["pressure_m"])
                        if row["pressure_m"] is not None
                        else None
                    ),
                    depth_m=(
                        float(row["depth_m"])
                        if row["depth_m"] is not None
                        else None
                    ),
                    value=(
                        float(row["value"])
                        if row["value"] is not None
                        else None
                    ),
                    units=row["units"],
                    is_missing=bool(row["is_missing"]),
                    source=row["source"],
                    source_url=row["source_url"],
                    ingested_at_utc=row["ingested_at_utc"],
                )
            )

        return result


def build_store_from_verified_profiles() -> None:
    """
    Ingest the two verified INCOIS profile test files.
    """

    store = ScientificStore()

    dataset_id = "incois_argo_10d_VAM"

    temp_raw = RAW_DIR / (
        "incois_argo_10d_VAM_TEMP_profile.csv"
    )

    sal_raw = RAW_DIR / (
        "incois_argo_10d_VAM_SAL_profile.csv"
    )

    temp_url = (
        "https://erddap.incois.gov.in/erddap/griddap/"
        "incois_argo_10d_VAM.csv?"
        "TEMP%5B%28last%29%5D%5B0:1:23%5D%5B30%5D%5B40%5D"
    )

    sal_url = (
        "https://erddap.incois.gov.in/erddap/griddap/"
        "incois_argo_10d_VAM.csv?"
        "SAL%5B%28last%29%5D%5B0:1:23%5D%5B30%5D%5B40%5D"
    )

    print("=" * 80)
    print("OCEANSIGHT-V")
    print("BUILDING LOCAL SCIENTIFIC STORE")
    print("=" * 80)

    print()
    print("Input files:")
    print(f"  TEMP: {temp_raw}")
    print(f"  SAL : {sal_raw}")

    if not temp_raw.exists():
        raise FileNotFoundError(
            f"TEMP profile file not found: {temp_raw}"
        )

    if not sal_raw.exists():
        raise FileNotFoundError(
            f"SAL profile file not found: {sal_raw}"
        )

    # -------------------------------------------------------------------------
    # TEMP
    # -------------------------------------------------------------------------

    print()
    print("-" * 80)
    print("NORMALIZING TEMP")
    print("-" * 80)

    temp_normalized = store.normalize_erddap_csv(
        csv_path=temp_raw,
        dataset_id=dataset_id,
        variable="TEMP",
        source_url=temp_url,
        output_name=(
            "incois_argo_10d_VAM_TEMP_normalized.csv"
        ),
    )

    temp_count = store.ingest_normalized_csv(
        temp_normalized
    )

    print(f"Normalized TEMP: {temp_normalized}")
    print(f"Rows inserted: {temp_count}")

    # -------------------------------------------------------------------------
    # SAL
    # -------------------------------------------------------------------------

    print()
    print("-" * 80)
    print("NORMALIZING SAL")
    print("-" * 80)

    sal_normalized = store.normalize_erddap_csv(
        csv_path=sal_raw,
        dataset_id=dataset_id,
        variable="SAL",
        source_url=sal_url,
        output_name=(
            "incois_argo_10d_VAM_SAL_normalized.csv"
        ),
    )

    sal_count = store.ingest_normalized_csv(
        sal_normalized
    )

    print(f"Normalized SAL: {sal_normalized}")
    print(f"Rows inserted: {sal_count}")

    # -------------------------------------------------------------------------
    # PROVENANCE
    # -------------------------------------------------------------------------

    print()
    print("-" * 80)
    print("SAVING DATASET PROVENANCE")
    print("-" * 80)

    provenance = {
        "dataset_id": dataset_id,
        "provider": "INCOIS",
        "service": "ERDDAP",
        "dataset_type": "gridded ARGO-derived ocean data",
        "variables": [
            {
                "name": "TEMP",
                "meaning": "Temperature",
                "units": "degs",
                "fill_value": -9999.0,
            },
            {
                "name": "SAL",
                "meaning": "Sea-water practical salinity",
                "units": "PSU",
                "fill_value": -9999.0,
            },
        ],
        "vertical_coordinate": {
            "name": "ZAX",
            "units": "METERS",
            "axis": "Z",
            "point_spacing": "uneven",
            "levels_m": [
                5.0,
                10.0,
                20.0,
                30.0,
                50.0,
                75.0,
                100.0,
                125.0,
                150.0,
                200.0,
                250.0,
                300.0,
                400.0,
                500.0,
                600.0,
                700.0,
                800.0,
                900.0,
                1000.0,
                1200.0,
                1400.0,
                1600.0,
                1800.0,
                2000.0,
            ],
            "important_note": (
                "ZAX is preserved exactly. This dataset reports "
                "the coordinate in meters. It must not be treated "
                "as a converted dbar pressure field."
            ),
        },
        "time": {
            "units": "seconds since 1970-01-01T00:00:00Z",
            "latest_verified_available": (
                "2026-07-30T00:00:00Z"
            ),
        },
        "missing_data": {
            "fill_value": -9999.0,
            "storage_rule": (
                "Missing values are stored as NULL with "
                "is_missing=1 rather than converted to zero."
            ),
        },
    }

    provenance_path = store.save_dataset_metadata(
        dataset_id=dataset_id,
        metadata=provenance,
    )

    print(f"Provenance saved: {provenance_path}")

    # -------------------------------------------------------------------------
    # SUMMARY
    # -------------------------------------------------------------------------

    print()
    print("=" * 80)
    print("STORE SUMMARY")
    print("=" * 80)

    print(f"SQLite database: {store.db_path}")

    print(
        "TEMP observations:",
        store.count_observations(
            dataset_id=dataset_id,
            variable="TEMP",
        ),
    )

    print(
        "SAL observations:",
        store.count_observations(
            dataset_id=dataset_id,
            variable="SAL",
        ),
    )

    print(
        "Latest TEMP time:",
        store.latest_observation_time(
            dataset_id=dataset_id,
            variable="TEMP",
        ),
    )

    print(
        "Latest SAL time:",
        store.latest_observation_time(
            dataset_id=dataset_id,
            variable="SAL",
        ),
    )

    print()
    print("STORE BUILD COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    build_store_from_verified_profiles()

