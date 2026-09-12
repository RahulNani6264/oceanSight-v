from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
import pandas as pd
import truststore

from .argo_store import (
    ARGO_PROVENANCE_DIR,
    RAW_DIR,
    ArgoStore,
)


# =============================================================================
# OCEANSIGHT-V
# INCOIS LIVE ARGO ACQUISITION MANAGER
#
# Real source:
#
#     INCOIS ERDDAP
#     Indian_ARGO_Floats
#
# Scientific rules:
#
#     PRES -> dbar
#     TEMP -> degree Celsius
#     PSAL -> PSU
#
#     No synthetic observations.
#     No interpolation.
#     No pressure-to-depth conversion.
#     Actual source timestamps are preserved.
#     Missing source values remain missing.
#     Real QC fields are preserved.
#
# Supported live operations:
#
#     acquire()
#         Point + pressure acquisition.
#
#     acquire_profile()
#         Complete real profile by platform + cycle.
#
#     discover_profiles()
#         Real profile discovery by geographic region.
# =============================================================================


BASE_URL = (
    "https://erddap.incois.gov.in/erddap/tabledap/"
    "Indian_ARGO_Floats.csv"
)

DATASET_NAME = "Indian_ARGO_Floats"

SOURCE_NAME = "INCOIS ERDDAP"

USER_AGENT = "OceanSight-V/1.0"


# Complete scientific field set preserved in the local store.
VARIABLES = [
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


# Small projection used for candidate observation discovery.
CANDIDATE_VARIABLES = [
    "PLATFORM_NUMBER",
    "CYCLE_NUMBER",
    "time",
    "latitude",
    "longitude",
    "PRES",
    "PRES_QC",
    "TEMP",
    "TEMP_QC",
    "PSAL",
    "PSAL_QC",
]


# Projection for geographic profile discovery.
PROFILE_DISCOVERY_VARIABLES = [
    "PLATFORM_NUMBER",
    "CYCLE_NUMBER",
    "DIRECTION",
    "time",
    "JULD_LOCATION",
    "latitude",
    "longitude",
]


class ArgoLiveManager:
    """
    Live acquisition manager for real INCOIS Indian Argo observations.
    """

    def __init__(
        self,
        store: ArgoStore | None = None,
        timeout_seconds: float = 120.0,
    ) -> None:

        self.store = (
            store
            if store is not None
            else ArgoStore()
        )

        self.timeout_seconds = float(
            timeout_seconds
        )

        truststore.inject_into_ssl()

    # =========================================================================
    # TIME
    # =========================================================================

    @staticmethod
    def utc_now() -> str:

        return (
            datetime.now(
                timezone.utc
            )
            .replace(
                microsecond=0
            )
            .isoformat()
            .replace(
                "+00:00",
                "Z",
            )
        )

    @staticmethod
    def parse_time(
        value: str,
    ) -> datetime:

        parsed = pd.to_datetime(
            value,
            utc=True,
            errors="raise",
        )

        if isinstance(
            parsed,
            pd.DatetimeIndex,
        ):

            raise ValueError(
                f"Expected one timestamp, got: {value}"
            )

        return parsed.to_pydatetime()

    @staticmethod
    def format_time(
        value: datetime,
    ) -> str:

        return (
            value.astimezone(
                timezone.utc
            )
            .replace(
                microsecond=0
            )
            .isoformat()
            .replace(
                "+00:00",
                "Z",
            )
        )

    # =========================================================================
    # LONGITUDE
    # =========================================================================

    @staticmethod
    def normalize_longitude(
        longitude: float,
    ) -> float:

        longitude = float(
            longitude
        )

        if not math.isfinite(
            longitude
        ):

            raise ValueError(
                "Longitude must be finite."
            )

        while longitude > 180.0:

            longitude -= 360.0

        while longitude < -180.0:

            longitude += 360.0

        return longitude

    # =========================================================================
    # HTTP CLIENT
    # =========================================================================

    def _client(
        self,
    ) -> httpx.Client:

        timeout = httpx.Timeout(
            connect=20.0,
            read=self.timeout_seconds,
            write=30.0,
            pool=30.0,
        )

        return httpx.Client(
            verify=True,
            timeout=timeout,
            follow_redirects=True,
            headers={
                "User-Agent": USER_AGENT,
            },
        )

    # =========================================================================
    # URL BUILDING
    # =========================================================================

    @staticmethod
    def _constraint(
        expression: str,
    ) -> str:
        """
        URL-encode one ERDDAP constraint.

        Quotes are intentionally not treated as safe.
        """

        return quote(
            expression,
            safe="<>!=.:-_()",
        )

    @classmethod
    def build_url(
        cls,
        variables: list[str],
        constraints: list[str],
    ) -> str:

        projection = ",".join(
            variables
        )

        if not constraints:

            return (
                f"{BASE_URL}?{projection}"
            )

        encoded_constraints = "&".join(
            cls._constraint(
                item
            )
            for item in constraints
        )

        return (
            f"{BASE_URL}?"
            f"{projection}&"
            f"{encoded_constraints}"
        )

    # =========================================================================
    # ERDDAP CSV PARSER
    # =========================================================================

    @staticmethod
    def parse_erddap_csv(
        text: str,
    ) -> tuple[pd.DataFrame, str]:

        lines = text.splitlines()

        if len(lines) < 2:

            raise ValueError(
                "INCOIS returned too little ERDDAP data."
            )

        header = lines[0].strip()

        units = lines[1].strip()

        csv_for_pandas = "\n".join(
            [header]
            + lines[2:]
        )

        dataframe = pd.read_csv(
            StringIO(
                csv_for_pandas
            )
        )

        return (
            dataframe,
            units,
        )

    # =========================================================================
    # HTTP REQUEST
    # =========================================================================

    def request_dataframe(
        self,
        url: str,
    ) -> tuple[pd.DataFrame, str]:

        print()
        print(
            "INCOIS LIVE ARGO REQUEST"
        )
        print(
            "-" * 80
        )
        print(url)

        with self._client() as client:

            response = client.get(
                url
            )

        print(
            "HTTP status:",
            response.status_code,
        )

        # ERDDAP uses 404 for no matching results.
        if response.status_code == 404:

            response_text = (
                response.text.strip()
            )

            no_match = (
                "Your query produced no matching results"
                in response_text
                or "actual_range"
                in response_text
                or "outside of the variable"
                in response_text
            )

            if no_match:

                print()
                print(
                    "INCOIS reports NO MATCHING ARGO RESULTS."
                )

                print()
                print(
                    response_text[:4000]
                )

                return (
                    pd.DataFrame(),
                    "",
                )

        if response.status_code != 200:

            print()
            print(
                "SERVER RESPONSE"
            )
            print(
                "-" * 80
            )
            print(
                response.text[:4000]
            )

            raise RuntimeError(
                "INCOIS live Argo request failed "
                f"with HTTP {response.status_code}."
            )

        if not response.text.strip():

            return (
                pd.DataFrame(),
                "",
            )

        return self.parse_erddap_csv(
            response.text
        )

    # =========================================================================
    # RAW HTTP TEXT
    # =========================================================================

    def fetch_text(
        self,
        url: str,
    ) -> str:

        print()
        print(
            "DOWNLOADING COMPLETE REAL ARGO PROFILE"
        )
        print(
            "-" * 80
        )
        print(url)

        with self._client() as client:

            response = client.get(
                url
            )

        if response.status_code != 200:

            raise RuntimeError(
                "INCOIS profile request failed "
                f"with HTTP {response.status_code}."
            )

        if not response.text.strip():

            raise RuntimeError(
                "INCOIS returned an empty profile response."
            )

        return response.text

    # =========================================================================
    # CANDIDATE SEARCH
    # =========================================================================

    def search_candidates(
        self,
        latitude: float,
        longitude: float,
        pressure_dbar: float,
        time_utc: str | None,
        radius_degrees: float,
        pressure_tolerance_dbar: float,
        time_window_days: float,
    ) -> tuple[
        pd.DataFrame,
        str,
        dict[str, Any],
    ]:

        if radius_degrees <= 0:

            raise ValueError(
                "radius_degrees must be greater than zero."
            )

        if pressure_dbar < 0:

            raise ValueError(
                "pressure_dbar cannot be negative."
            )

        if pressure_tolerance_dbar < 0:

            raise ValueError(
                "pressure_tolerance_dbar cannot be negative."
            )

        if time_window_days < 0:

            raise ValueError(
                "time_window_days cannot be negative."
            )

        longitude = self.normalize_longitude(
            longitude
        )

        pressure_low = max(
            0.0,
            pressure_dbar
            - pressure_tolerance_dbar,
        )

        pressure_high = (
            pressure_dbar
            + pressure_tolerance_dbar
        )

        constraints = [
            (
                f"latitude>="
                f"{latitude - radius_degrees}"
            ),

            (
                f"latitude<="
                f"{latitude + radius_degrees}"
            ),

            (
                f"longitude>="
                f"{longitude - radius_degrees}"
            ),

            (
                f"longitude<="
                f"{longitude + radius_degrees}"
            ),

            (
                f"PRES>="
                f"{pressure_low}"
            ),

            (
                f"PRES<="
                f"{pressure_high}"
            ),
        ]

        requested_time: datetime | None = None

        if time_utc is not None:

            requested_time = (
                self.parse_time(
                    time_utc
                )
            )

            delta = timedelta(
                days=float(
                    time_window_days
                )
            )

            start_time = (
                requested_time
                - delta
            )

            end_time = (
                requested_time
                + delta
            )

            constraints.extend(
                [
                    (
                        "time>="
                        + self.format_time(
                            start_time
                        )
                    ),

                    (
                        "time<="
                        + self.format_time(
                            end_time
                        )
                    ),
                ]
            )

        url = self.build_url(
            CANDIDATE_VARIABLES,
            constraints,
        )

        dataframe, units = (
            self.request_dataframe(
                url
            )
        )

        metadata = {
            "request_type": (
                "candidate_search"
            ),

            "latitude": latitude,

            "longitude": longitude,

            "pressure_requested_dbar": (
                pressure_dbar
            ),

            "pressure_low_dbar": (
                pressure_low
            ),

            "pressure_high_dbar": (
                pressure_high
            ),

            "radius_degrees": (
                radius_degrees
            ),

            "time_requested_utc": (
                time_utc
            ),

            "time_window_days": (
                time_window_days
            ),

            "url": url,

            "units_row": units,
        }

        if requested_time is not None:

            metadata[
                "time_start_utc"
            ] = self.format_time(
                requested_time
                - timedelta(
                    days=float(
                        time_window_days
                    )
                )
            )

            metadata[
                "time_end_utc"
            ] = self.format_time(
                requested_time
                + timedelta(
                    days=float(
                        time_window_days
                    )
                )
            )

        return (
            dataframe,
            url,
            metadata,
        )

    # =========================================================================
    # PROFILE DISCOVERY SEARCH
    # =========================================================================

    def search_profile_candidates(
        self,
        latitude: float,
        longitude: float,
        radius_degrees: float = 5.0,
        time_utc: str | None = None,
        time_window_days: float = 30.0,
    ) -> tuple[
        pd.DataFrame,
        str,
        dict[str, Any],
    ]:
        """
        Search real Argo profile locations.

        This intentionally does not apply a pressure constraint because the
        purpose is profile discovery for the frontend map.

        The result contains real platform/cycle/location/time records.
        """

        latitude = float(
            latitude
        )

        longitude = self.normalize_longitude(
            longitude
        )

        radius_degrees = float(
            radius_degrees
        )

        time_window_days = float(
            time_window_days
        )

        if not math.isfinite(
            latitude
        ):

            raise ValueError(
                "Latitude must be finite."
            )

        if not math.isfinite(
            longitude
        ):

            raise ValueError(
                "Longitude must be finite."
            )

        if not (
            -90.0 <= latitude <= 90.0
        ):

            raise ValueError(
                "Latitude must be between -90 and 90."
            )

        if radius_degrees <= 0:

            raise ValueError(
                "radius_degrees must be greater than zero."
            )

        if time_window_days < 0:

            raise ValueError(
                "time_window_days cannot be negative."
            )

        constraints = [
            (
                f"latitude>="
                f"{latitude - radius_degrees}"
            ),

            (
                f"latitude<="
                f"{latitude + radius_degrees}"
            ),

            (
                f"longitude>="
                f"{longitude - radius_degrees}"
            ),

            (
                f"longitude<="
                f"{longitude + radius_degrees}"
            ),
        ]

        if time_utc is not None:

            requested_time = (
                self.parse_time(
                    time_utc
                )
            )

            delta = timedelta(
                days=time_window_days
            )

            constraints.extend(
                [
                    (
                        "time>="
                        + self.format_time(
                            requested_time
                            - delta
                        )
                    ),

                    (
                        "time<="
                        + self.format_time(
                            requested_time
                            + delta
                        )
                    ),
                ]
            )

        url = self.build_url(
            PROFILE_DISCOVERY_VARIABLES,
            constraints,
        )

        dataframe, units = (
            self.request_dataframe(
                url
            )
        )

        metadata = {
            "request_type": (
                "profile_discovery"
            ),

            "latitude": latitude,

            "longitude": longitude,

            "radius_degrees": radius_degrees,

            "time_requested_utc": time_utc,

            "time_window_days": time_window_days,

            "url": url,

            "units_row": units,
        }

        return (
            dataframe,
            url,
            metadata,
        )

    # =========================================================================
    # LONGITUDE DIFFERENCE
    # =========================================================================

    @staticmethod
    def longitude_difference(
        longitude_a: float,
        longitude_b: float,
    ) -> float:

        difference = (
            longitude_a
            - longitude_b
        )

        while difference > 180.0:

            difference -= 360.0

        while difference < -180.0:

            difference += 360.0

        return abs(
            difference
        )

    # =========================================================================
    # APPROXIMATE DISTANCE
    # =========================================================================

    @classmethod
    def approximate_distance_degrees(
        cls,
        latitude_a: float,
        longitude_a: float,
        latitude_b: float,
        longitude_b: float,
    ) -> float:

        latitude_difference = (
            latitude_a
            - latitude_b
        )

        longitude_difference = (
            cls.longitude_difference(
                longitude_a,
                longitude_b,
            )
        )

        mean_latitude = math.radians(
            (
                latitude_a
                + latitude_b
            )
            / 2.0
        )

        adjusted_longitude = (
            longitude_difference
            * math.cos(
                mean_latitude
            )
        )

        return math.sqrt(
            latitude_difference**2
            + adjusted_longitude**2
        )

    # =========================================================================
    # BEST CANDIDATE
    # =========================================================================

    def select_best_candidate(
        self,
        dataframe: pd.DataFrame,
        latitude: float,
        longitude: float,
        pressure_dbar: float,
        time_utc: str | None,
    ) -> dict[str, Any] | None:

        if dataframe.empty:

            return None

        required = [
            "PLATFORM_NUMBER",
            "CYCLE_NUMBER",
            "time",
            "latitude",
            "longitude",
            "PRES",
        ]

        missing = [
            item
            for item in required
            if item not in dataframe.columns
        ]

        if missing:

            raise ValueError(
                "Live Argo candidate response is missing "
                "required fields:\n"
                + "\n".join(
                    f"  - {item}"
                    for item in missing
                )
            )

        working = dataframe.copy()

        working[
            "latitude_numeric"
        ] = pd.to_numeric(
            working["latitude"],
            errors="coerce",
        )

        working[
            "longitude_numeric"
        ] = pd.to_numeric(
            working["longitude"],
            errors="coerce",
        )

        working[
            "pres_numeric"
        ] = pd.to_numeric(
            working["PRES"],
            errors="coerce",
        )

        working[
            "time_parsed"
        ] = pd.to_datetime(
            working["time"],
            utc=True,
            errors="coerce",
        )

        working = working.dropna(
            subset=[
                "PLATFORM_NUMBER",
                "CYCLE_NUMBER",
                "latitude_numeric",
                "longitude_numeric",
                "pres_numeric",
            ]
        )

        if working.empty:

            return None

        working[
            "spatial_distance_degrees"
        ] = working.apply(
            lambda row:
            self.approximate_distance_degrees(
                latitude,
                longitude,
                float(
                    row[
                        "latitude_numeric"
                    ]
                ),
                float(
                    row[
                        "longitude_numeric"
                    ]
                ),
            ),
            axis=1,
        )

        working[
            "pressure_difference_dbar"
        ] = (
            working[
                "pres_numeric"
            ]
            - pressure_dbar
        ).abs()

        if time_utc is not None:

            requested_time = (
                self.parse_time(
                    time_utc
                )
            )

            working[
                "time_difference_seconds"
            ] = (
                working[
                    "time_parsed"
                ]
                - requested_time
            ).abs().dt.total_seconds()

        else:

            working[
                "time_difference_seconds"
            ] = 0.0

        working = working.sort_values(
            by=[
                "spatial_distance_degrees",
                "pressure_difference_dbar",
                "time_difference_seconds",
            ],
            ascending=[
                True,
                True,
                True,
            ],
        )

        selected = working.iloc[0]

        profile_time = None

        if not pd.isna(
            selected[
                "time_parsed"
            ]
        ):

            profile_time = (
                self.format_time(
                    selected[
                        "time_parsed"
                    ].to_pydatetime()
                )
            )

        return {
            "platform_number": str(
                selected[
                    "PLATFORM_NUMBER"
                ]
            ),

            "cycle_number": int(
                float(
                    selected[
                        "CYCLE_NUMBER"
                    ]
                )
            ),

            "profile_time_utc": (
                profile_time
            ),

            "latitude": float(
                selected[
                    "latitude_numeric"
                ]
            ),

            "longitude": float(
                selected[
                    "longitude_numeric"
                ]
            ),

            "pres_dbar": float(
                selected[
                    "pres_numeric"
                ]
            ),

            "spatial_distance_degrees": float(
                selected[
                    "spatial_distance_degrees"
                ]
            ),

            "pressure_difference_dbar": float(
                selected[
                    "pressure_difference_dbar"
                ]
            ),

            "time_difference_seconds": float(
                selected[
                    "time_difference_seconds"
                ]
            ),
        }

    # =========================================================================
    # PROFILE DISCOVERY NORMALIZATION
    # =========================================================================

    def normalize_profile_discovery(
        self,
        dataframe: pd.DataFrame,
        latitude: float,
        longitude: float,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """
        Convert raw live discovery rows into unique real profile summaries.

        Duplicate measurement rows are collapsed to one platform/cycle/time/
        location record.
        """

        if dataframe.empty:

            return []

        required = [
            "PLATFORM_NUMBER",
            "CYCLE_NUMBER",
            "DIRECTION",
            "time",
            "JULD_LOCATION",
            "latitude",
            "longitude",
        ]

        missing = [
            item
            for item in required
            if item not in dataframe.columns
        ]

        if missing:

            raise ValueError(
                "Live Argo profile discovery response is missing "
                "required fields:\n"
                + "\n".join(
                    f"  - {item}"
                    for item in missing
                )
            )

        working = dataframe.copy()

        working[
            "latitude_numeric"
        ] = pd.to_numeric(
            working["latitude"],
            errors="coerce",
        )

        working[
            "longitude_numeric"
        ] = pd.to_numeric(
            working["longitude"],
            errors="coerce",
        )

        working[
            "cycle_numeric"
        ] = pd.to_numeric(
            working["CYCLE_NUMBER"],
            errors="coerce",
        )

        working[
            "time_parsed"
        ] = pd.to_datetime(
            working["time"],
            utc=True,
            errors="coerce",
        )

        working[
            "juld_location_parsed"
        ] = pd.to_datetime(
            working["JULD_LOCATION"],
            utc=True,
            errors="coerce",
        )

        working = working.dropna(
            subset=[
                "PLATFORM_NUMBER",
                "CYCLE_NUMBER",
                "latitude_numeric",
                "longitude_numeric",
            ]
        )

        if working.empty:

            return []

        working[
            "spatial_distance_degrees"
        ] = working.apply(
            lambda row:
            self.approximate_distance_degrees(
                latitude,
                longitude,
                float(
                    row[
                        "latitude_numeric"
                    ]
                ),
                float(
                    row[
                        "longitude_numeric"
                    ]
                ),
            ),
            axis=1,
        )

        records: list[
            dict[str, Any]
        ] = []

        # ---------------------------------------------------------------------
        # Group rows representing the same actual Argo profile.
        # ---------------------------------------------------------------------

        grouped = working.groupby(
            [
                "PLATFORM_NUMBER",
                "cycle_numeric",
                "time_parsed",
                "latitude_numeric",
                "longitude_numeric",
            ],
            dropna=False,
        )

        for key, group in grouped:

            (
                platform_value,
                cycle_value,
                profile_time_value,
                latitude_value,
                longitude_value,
            ) = key

            profile_time = None

            if not pd.isna(
                profile_time_value
            ):

                profile_time = (
                    self.format_time(
                        profile_time_value
                        .to_pydatetime()
                    )
                )

            juld_location = None

            location_series = group[
                "juld_location_parsed"
            ].dropna()

            if not location_series.empty:

                juld_location = (
                    self.format_time(
                        location_series.iloc[0]
                        .to_pydatetime()
                    )
                )

            direction = None

            direction_series = (
                group[
                    "DIRECTION"
                ]
                .dropna()
                .astype(str)
                .str.strip()
            )

            if not direction_series.empty:

                direction = (
                    direction_series.iloc[0]
                )

            records.append(
                {
                    "platform_number": str(
                        platform_value
                    ),

                    "cycle_number": int(
                        float(
                            cycle_value
                        )
                    ),

                    "direction": direction,

                    "profile_time_utc": (
                        profile_time
                    ),

                    "juld_location_utc": (
                        juld_location
                    ),

                    "latitude": float(
                        latitude_value
                    ),

                    "longitude": float(
                        longitude_value
                    ),

                    "spatial_distance_degrees": float(
                        group[
                            "spatial_distance_degrees"
                        ].min()
                    ),
                }
            )

        records.sort(
            key=lambda record: (
                record[
                    "spatial_distance_degrees"
                ],
                record.get(
                    "profile_time_utc"
                )
                or "",
            )
        )

        return records[
            :limit
        ]

    # =========================================================================
    # BUILD PROFILE URL
    # =========================================================================

    def build_profile_url(
        self,
        platform_number: str,
        cycle_number: int,
    ) -> str:

        platform_number = str(
            platform_number
        ).strip()

        cycle_number = int(
            cycle_number
        )

        constraints = [
            (
                "PLATFORM_NUMBER="
                f'"{platform_number}"'
            ),

            (
                "CYCLE_NUMBER="
                f"{cycle_number}"
            ),
        ]

        return self.build_url(
            VARIABLES,
            constraints,
        )

    # =========================================================================
    # FETCH FULL PROFILE
    # =========================================================================

    def fetch_full_profile(
        self,
        platform_number: str,
        cycle_number: int,
    ) -> tuple[
        pd.DataFrame,
        str,
        str,
        str,
    ]:

        url = self.build_profile_url(
            platform_number=platform_number,
            cycle_number=cycle_number,
        )

        raw_text = self.fetch_text(
            url
        )

        dataframe, units = (
            self.parse_erddap_csv(
                raw_text
            )
        )

        return (
            dataframe,
            units,
            url,
            raw_text,
        )

    # =========================================================================
    # PROFILE VALIDATION
    # =========================================================================

    @staticmethod
    def validate_profile(
        dataframe: pd.DataFrame,
        platform_number: str,
        cycle_number: int,
    ) -> None:

        if dataframe.empty:

            raise RuntimeError(
                "INCOIS returned an empty Argo profile."
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
                "Full Argo profile is missing required "
                "scientific fields:\n"
                + "\n".join(
                    f"  - {item}"
                    for item in missing
                )
            )

        platform_values = (
            dataframe[
                "PLATFORM_NUMBER"
            ]
            .dropna()
            .astype(str)
            .unique()
            .tolist()
        )

        if platform_number not in platform_values:

            raise RuntimeError(
                "The returned Argo profile does not contain "
                f"platform {platform_number}."
            )

        cycle_values = (
            pd.to_numeric(
                dataframe[
                    "CYCLE_NUMBER"
                ],
                errors="coerce",
            )
            .dropna()
            .astype(int)
            .unique()
            .tolist()
        )

        if cycle_number not in cycle_values:

            raise RuntimeError(
                "The returned Argo profile does not contain "
                f"cycle {cycle_number}."
            )

        pressure = pd.to_numeric(
            dataframe[
                "PRES"
            ],
            errors="coerce",
        )

        if pressure.notna().sum() == 0:

            raise RuntimeError(
                "The returned Argo profile contains no valid PRES values."
            )

    # =========================================================================
    # SAVE RAW RESPONSE
    # =========================================================================

    def save_raw_response(
        self,
        response_text: str,
        suffix: str,
    ) -> Path:

        timestamp = (
            datetime.now(
                timezone.utc
            )
            .strftime(
                "%Y%m%dT%H%M%SZ"
            )
        )

        path = (
            RAW_DIR
            / (
                f"Indian_ARGO_Floats_live_"
                f"{timestamp}_"
                f"{suffix}.csv"
            )
        )

        path.write_text(
            response_text,
            encoding="utf-8",
        )

        return path

    # =========================================================================
    # SAVE PARSED RESPONSE
    # =========================================================================

    def save_parsed_dataframe(
        self,
        dataframe: pd.DataFrame,
        suffix: str,
    ) -> Path:

        timestamp = (
            datetime.now(
                timezone.utc
            )
            .strftime(
                "%Y%m%dT%H%M%SZ"
            )
        )

        path = (
            RAW_DIR
            / (
                f"Indian_ARGO_Floats_live_"
                f"{timestamp}_"
                f"{suffix}_parsed.csv"
            )
        )

        dataframe.to_csv(
            path,
            index=False,
        )

        return path

    # =========================================================================
    # DATABASE SOURCE UPDATE
    # =========================================================================

    def update_profile_source_url(
        self,
        platform_number: str,
        cycle_number: int,
        source_url: str,
    ) -> None:

        with self.store._connect() as connection:

            connection.execute(
                """
                UPDATE argo_observations

                SET source = ?,
                    source_dataset = ?,
                    source_url = ?

                WHERE platform_number = ?
                  AND cycle_number = ?
                """,
                (
                    SOURCE_NAME,
                    DATASET_NAME,
                    source_url,
                    platform_number,
                    cycle_number,
                ),
            )

    # =========================================================================
    # UNIQUE INDEX
    # =========================================================================

    def ensure_unique_observation_index(
        self,
    ) -> None:

        with self.store._connect() as connection:

            connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS
                idx_argo_unique_observation
                ON argo_observations(
                    source_dataset,
                    platform_number,
                    cycle_number,
                    profile_time_utc,
                    latitude,
                    longitude,
                    pres_dbar
                )
                """
            )

    # =========================================================================
    # PROVENANCE
    # =========================================================================

    def write_provenance(
        self,
        provenance: dict[str, Any],
        platform_number: str,
        cycle_number: int,
    ) -> Path:

        timestamp = (
            datetime.now(
                timezone.utc
            )
            .strftime(
                "%Y%m%dT%H%M%SZ"
            )
        )

        path = (
            ARGO_PROVENANCE_DIR
            / (
                f"argo_live_"
                f"{platform_number}_"
                f"cycle_{cycle_number}_"
                f"{timestamp}.json"
            )
        )

        path.write_text(
            json.dumps(
                provenance,
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        return path

    # =========================================================================
    # LIVE COMPLETE PROFILE ACQUISITION
    # =========================================================================

    def acquire_profile(
        self,
        platform_number: str,
        cycle_number: int,
    ) -> dict[str, Any]:
        """
        Download and ingest one complete real Argo profile.

        This is the live path used when the requested platform/cycle is not
        already present in the local SQLite store.
        """

        platform_number = str(
            platform_number
        ).strip()

        cycle_number = int(
            cycle_number
        )

        if not platform_number:

            raise ValueError(
                "platform_number cannot be empty."
            )

        if cycle_number < 0:

            raise ValueError(
                "cycle_number cannot be negative."
            )

        print()
        print(
            "=" * 80
        )
        print(
            "OCEANSIGHT-V"
        )
        print(
            "LIVE INCOIS ARGO PROFILE ACQUISITION"
        )
        print(
            "=" * 80
        )

        print()
        print(
            "Platform:",
            platform_number,
        )

        print(
            "Cycle:",
            cycle_number,
        )

        (
            profile,
            profile_units,
            profile_url,
            raw_text,
        ) = self.fetch_full_profile(
            platform_number=platform_number,
            cycle_number=cycle_number,
        )

        self.validate_profile(
            dataframe=profile,
            platform_number=platform_number,
            cycle_number=cycle_number,
        )

        raw_path = (
            self.save_raw_response(
                response_text=raw_text,
                suffix=(
                    f"profile_"
                    f"{platform_number}_"
                    f"cycle_{cycle_number}"
                ),
            )
        )

        parsed_profile, _ = (
            self.parse_erddap_csv(
                raw_text
            )
        )

        parsed_path = (
            self.save_parsed_dataframe(
                dataframe=parsed_profile,
                suffix=(
                    f"profile_"
                    f"{platform_number}_"
                    f"cycle_{cycle_number}"
                ),
            )
        )

        self.ensure_unique_observation_index()

        normalized_path = (
            self.store.normalize(
                parsed_path,
                output_name=(
                    f"Indian_ARGO_Floats_live_"
                    f"{platform_number}_"
                    f"cycle_{cycle_number}_"
                    f"normalized.csv"
                ),
            )
        )

        inserted = self.store.ingest(
            normalized_path
        )

        self.update_profile_source_url(
            platform_number=platform_number,
            cycle_number=cycle_number,
            source_url=profile_url,
        )

        stored_profile = (
            self.store.get_profile(
                platform_number=platform_number,
                cycle_number=cycle_number,
            )
        )

        if not stored_profile:

            raise RuntimeError(
                "Live Argo profile was downloaded and ingested, "
                "but could not be read back from the local store."
            )

        profile_time_values = (
            pd.to_datetime(
                profile["time"],
                utc=True,
                errors="coerce",
            )
            .dropna()
        )

        actual_profile_time = None

        if not profile_time_values.empty:

            actual_profile_time = (
                self.format_time(
                    profile_time_values.iloc[0]
                    .to_pydatetime()
                )
            )

        latitude_values = pd.to_numeric(
            profile["latitude"],
            errors="coerce",
        ).dropna()

        longitude_values = pd.to_numeric(
            profile["longitude"],
            errors="coerce",
        ).dropna()

        actual_latitude = (
            float(
                latitude_values.iloc[0]
            )
            if not latitude_values.empty
            else None
        )

        actual_longitude = (
            float(
                longitude_values.iloc[0]
            )
            if not longitude_values.empty
            else None
        )

        provenance = {
            "provider": "INCOIS",

            "service": "ERDDAP tabledap",

            "dataset": DATASET_NAME,

            "source": SOURCE_NAME,

            "automatic": True,

            "synthetic": False,

            "interpolation": False,

            "profile_request": {
                "platform_number": (
                    platform_number
                ),

                "cycle_number": (
                    cycle_number
                ),

                "url": profile_url,

                "units_row": profile_units,
            },

            "profile_identity": {
                "platform_number": (
                    platform_number
                ),

                "cycle_number": (
                    cycle_number
                ),

                "actual_profile_time_utc": (
                    actual_profile_time
                ),

                "latitude": (
                    actual_latitude
                ),

                "longitude": (
                    actual_longitude
                ),
            },

            "files": {
                "raw": str(
                    raw_path
                ),

                "parsed": str(
                    parsed_path
                ),

                "normalized": str(
                    normalized_path
                ),
            },

            "database": {
                "database": str(
                    self.store.db_path
                ),

                "rows_inserted": inserted,

                "profile_rows_available": (
                    len(
                        stored_profile
                    )
                ),
            },

            "scientific_rules": {
                "PRES_units": "dbar",

                "PRES_converted_to_depth": False,

                "TEMP_units": "degree_Celsius",

                "PSAL_units": "PSU",

                "missing_values_preserved_as_null": True,

                "interpolation_performed": False,

                "synthetic_values_created": False,

                "actual_profile_time_preserved": True,
            },

            "acquired_at_utc": (
                self.utc_now()
            ),
        }

        provenance_path = (
            self.write_provenance(
                provenance=provenance,
                platform_number=platform_number,
                cycle_number=cycle_number,
            )
        )

        return {
            "available": True,

            "source": SOURCE_NAME,

            "dataset": DATASET_NAME,

            "automatic": True,

            "synthetic": False,

            "interpolation": False,

            "pressure_converted_to_depth": False,

            "profile": {
                "platform_number": (
                    platform_number
                ),

                "cycle_number": (
                    cycle_number
                ),

                "profile_time_utc": (
                    actual_profile_time
                ),

                "latitude": (
                    actual_latitude
                ),

                "longitude": (
                    actual_longitude
                ),
            },

            "row_count": len(
                stored_profile
            ),

            "provenance": {
                "profile_url": profile_url,

                "raw_file": str(
                    raw_path
                ),

                "parsed_file": str(
                    parsed_path
                ),

                "normalized_file": str(
                    normalized_path
                ),

                "provenance_file": str(
                    provenance_path
                ),
            },

            "scientific_rules": {
                "pressure_unit": "dbar",

                "pressure_is_depth": False,

                "pressure_converted_to_depth": False,

                "synthetic_data": False,

                "interpolation": False,
            },
        }

    # =========================================================================
    # LIVE PROFILE DISCOVERY
    # =========================================================================

    def discover_profiles(
        self,
        latitude: float,
        longitude: float,
        radius_degrees: float = 5.0,
        time_utc: str | None = None,
        time_window_days: float = 30.0,
        limit: int = 100,
    ) -> dict[str, Any]:
        """
        Discover real Argo profiles directly from INCOIS.

        This method does NOT download complete profiles for every float.
        It returns lightweight real platform/cycle/location/time summaries.

        A specific profile can then be acquired with acquire_profile().
        """

        latitude = float(
            latitude
        )

        longitude = self.normalize_longitude(
            longitude
        )

        radius_degrees = float(
            radius_degrees
        )

        time_window_days = float(
            time_window_days
        )

        limit = int(
            limit
        )

        if not (
            math.isfinite(
                latitude
            )
            and math.isfinite(
                longitude
            )
            and math.isfinite(
                radius_degrees
            )
            and math.isfinite(
                time_window_days
            )
        ):

            raise ValueError(
                "Latitude, longitude, radius and time window "
                "must be finite."
            )

        if not (
            -90.0 <= latitude <= 90.0
        ):

            raise ValueError(
                "Latitude must be between -90 and 90."
            )

        if radius_degrees <= 0:

            raise ValueError(
                "radius_degrees must be greater than zero."
            )

        if time_window_days < 0:

            raise ValueError(
                "time_window_days cannot be negative."
            )

        if not (
            1 <= limit <= 1000
        ):

            raise ValueError(
                "limit must be between 1 and 1000."
            )

        (
            dataframe,
            discovery_url,
            discovery_metadata,
        ) = self.search_profile_candidates(
            latitude=latitude,
            longitude=longitude,
            radius_degrees=radius_degrees,
            time_utc=time_utc,
            time_window_days=time_window_days,
        )

        profiles = (
            self.normalize_profile_discovery(
                dataframe=dataframe,
                latitude=latitude,
                longitude=longitude,
                limit=limit,
            )
        )

        return {
            "available": bool(
                profiles
            ),

            "source": SOURCE_NAME,

            "dataset": DATASET_NAME,

            "automatic": True,

            "profile_count": len(
                profiles
            ),

            "profiles": profiles,

            "request": {
                "latitude": latitude,

                "longitude": longitude,

                "radius_degrees": radius_degrees,

                "time_utc": time_utc,

                "time_window_days": time_window_days,

                "limit": limit,
            },

            "provenance": {
                "discovery_url": (
                    discovery_url
                ),

                "discovery_metadata": (
                    discovery_metadata
                ),

                "scientific_rules": {
                    "synthetic_data": False,

                    "interpolation": False,

                    "pressure_unit": "dbar",

                    "pressure_is_depth": False,

                    "pressure_converted_to_depth": False,
                },
            },
        }

    # =========================================================================
    # MAIN POINT + PRESSURE ACQUISITION
    # =========================================================================

    def acquire(
        self,
        latitude: float,
        longitude: float,
        pressure_dbar: float,
        time_utc: str | None = None,
        radius_degrees: float = 0.5,
        pressure_tolerance_dbar: float = 25.0,
        time_window_days: float = 30.0,
        fallback_spatial_only: bool = True,
    ) -> dict[str, Any]:

        print()
        print(
            "=" * 80
        )
        print(
            "OCEANSIGHT-V"
        )
        print(
            "LIVE INCOIS ARGO ACQUISITION"
        )
        print(
            "=" * 80
        )

        print()
        print(
            "REQUEST"
        )
        print(
            "-" * 80
        )

        print(
            "Latitude:",
            latitude,
        )

        print(
            "Longitude:",
            longitude,
        )

        print(
            "Requested PRES:",
            pressure_dbar,
            "dbar",
        )

        print(
            "Requested time:",
            time_utc,
        )

        print(
            "Radius:",
            radius_degrees,
            "degrees",
        )

        (
            candidates,
            candidate_url,
            candidate_metadata,
        ) = self.search_candidates(
            latitude=latitude,
            longitude=longitude,
            pressure_dbar=pressure_dbar,
            time_utc=time_utc,
            radius_degrees=radius_degrees,
            pressure_tolerance_dbar=(
                pressure_tolerance_dbar
            ),
            time_window_days=(
                time_window_days
            ),
        )

        search_mode = (
            "spatial_pressure_time"
        )

        if (
            candidates.empty
            and fallback_spatial_only
        ):

            print()
            print(
                "No real Argo observation matched "
                "the requested time window."
            )

            print()
            print(
                "FALLBACK"
            )
            print(
                "-" * 80
            )

            (
                candidates,
                candidate_url,
                candidate_metadata,
            ) = self.search_candidates(
                latitude=latitude,
                longitude=longitude,
                pressure_dbar=pressure_dbar,
                time_utc=None,
                radius_degrees=radius_degrees,
                pressure_tolerance_dbar=(
                    pressure_tolerance_dbar
                ),
                time_window_days=(
                    time_window_days
                ),
            )

            search_mode = (
                "spatial_pressure_only"
            )

        if candidates.empty:

            return {
                "available": False,

                "source": SOURCE_NAME,

                "dataset": DATASET_NAME,

                "automatic": True,

                "reason": (
                    "INCOIS returned no real Argo "
                    "observation within the requested "
                    "location and pressure limits."
                ),

                "request": {
                    "latitude": latitude,

                    "longitude": longitude,

                    "pressure_dbar": pressure_dbar,

                    "time_utc": time_utc,

                    "radius_degrees": (
                        radius_degrees
                    ),

                    "pressure_tolerance_dbar": (
                        pressure_tolerance_dbar
                    ),
                },

                "search_mode": search_mode,

                "synthetic": False,

                "interpolation": False,

                "pressure_converted_to_depth": False,

                "provenance": {
                    "candidate_search": {
                        "url": candidate_url,

                        "metadata": candidate_metadata,
                    },

                    "scientific_rules": {
                        "PRES_units": "dbar",

                        "PRES_converted_to_depth": False,

                        "synthetic_values_created": False,

                        "interpolation_performed": False,
                    },
                },
            }

        candidate = (
            self.select_best_candidate(
                dataframe=candidates,

                latitude=latitude,

                longitude=longitude,

                pressure_dbar=pressure_dbar,

                time_utc=(
                    time_utc
                    if search_mode
                    == "spatial_pressure_time"
                    else None
                ),
            )
        )

        if candidate is None:

            return {
                "available": False,

                "source": SOURCE_NAME,

                "dataset": DATASET_NAME,

                "automatic": True,

                "reason": (
                    "INCOIS returned candidate rows, "
                    "but none contained a valid scientific "
                    "Argo observation."
                ),

                "request": {
                    "latitude": latitude,

                    "longitude": longitude,

                    "pressure_dbar": pressure_dbar,

                    "time_utc": time_utc,
                },

                "search_mode": search_mode,

                "synthetic": False,

                "interpolation": False,

                "pressure_converted_to_depth": False,
            }

        platform_number = (
            candidate[
                "platform_number"
            ]
        )

        cycle_number = (
            candidate[
                "cycle_number"
            ]
        )

        print()
        print(
            "SELECTED REAL ARGO OBSERVATION"
        )
        print(
            "-" * 80
        )

        print(
            "Platform:",
            platform_number,
        )

        print(
            "Cycle:",
            cycle_number,
        )

        print(
            "Actual profile time:",
            candidate[
                "profile_time_utc"
            ],
        )

        print(
            "Profile latitude:",
            candidate[
                "latitude"
            ],
        )

        print(
            "Profile longitude:",
            candidate[
                "longitude"
            ],
        )

        print(
            "Actual PRES:",
            candidate[
                "pres_dbar"
            ],
            "dbar",
        )

        (
            profile,
            profile_units,
            profile_url,
            raw_text,
        ) = self.fetch_full_profile(
            platform_number=platform_number,
            cycle_number=cycle_number,
        )

        self.validate_profile(
            dataframe=profile,

            platform_number=platform_number,

            cycle_number=cycle_number,
        )

        raw_path = (
            self.save_raw_response(
                response_text=raw_text,

                suffix=(
                    f"profile_"
                    f"{platform_number}_"
                    f"cycle_{cycle_number}"
                ),
            )
        )

        parsed_profile, _ = (
            self.parse_erddap_csv(
                raw_text
            )
        )

        parsed_path = (
            self.save_parsed_dataframe(
                dataframe=parsed_profile,

                suffix=(
                    f"profile_"
                    f"{platform_number}_"
                    f"cycle_{cycle_number}"
                ),
            )
        )

        self.ensure_unique_observation_index()

        normalized_path = (
            self.store.normalize(
                parsed_path,

                output_name=(
                    f"Indian_ARGO_Floats_live_"
                    f"{platform_number}_"
                    f"cycle_{cycle_number}_"
                    f"normalized.csv"
                ),
            )
        )

        inserted = self.store.ingest(
            normalized_path
        )

        self.update_profile_source_url(
            platform_number=platform_number,

            cycle_number=cycle_number,

            source_url=profile_url,
        )

        stored_profile = (
            self.store.get_profile(
                platform_number=platform_number,

                cycle_number=cycle_number,
            )
        )

        if not stored_profile:

            raise RuntimeError(
                "Live Argo profile was downloaded and ingested, "
                "but could not be read back from the local store."
            )

        valid_pressure_rows = [
            row
            for row in stored_profile
            if row.get(
                "pres_dbar"
            ) is not None
        ]

        if not valid_pressure_rows:

            raise RuntimeError(
                "The ingested Argo profile contains no valid PRES values."
            )

        selected_stored = min(
            valid_pressure_rows,

            key=lambda row:
            abs(
                float(
                    row[
                        "pres_dbar"
                    ]
                )
                - pressure_dbar
            ),
        )

        pressure_values = [
            float(
                row[
                    "pres_dbar"
                ]
            )
            for row in stored_profile
            if row.get(
                "pres_dbar"
            ) is not None
        ]

        temperature_values = [
            float(
                row[
                    "temp_c"
                ]
            )
            for row in stored_profile
            if row.get(
                "temp_c"
            ) is not None
        ]

        salinity_values = [
            float(
                row[
                    "psal_psu"
                ]
            )
            for row in stored_profile
            if row.get(
                "psal_psu"
            ) is not None
        ]

        provenance = {
            "provider": "INCOIS",

            "service": "ERDDAP tabledap",

            "dataset": DATASET_NAME,

            "source": SOURCE_NAME,

            "automatic": True,

            "synthetic": False,

            "interpolation": False,

            "request": {
                "latitude": latitude,

                "longitude": longitude,

                "pressure_requested_dbar": (
                    pressure_dbar
                ),

                "time_requested_utc": (
                    time_utc
                ),

                "radius_degrees": (
                    radius_degrees
                ),

                "pressure_tolerance_dbar": (
                    pressure_tolerance_dbar
                ),

                "time_window_days": (
                    time_window_days
                ),
            },

            "candidate_selection": {
                "mode": search_mode,

                "platform_number": (
                    platform_number
                ),

                "cycle_number": (
                    cycle_number
                ),

                "actual_profile_time_utc": (
                    candidate[
                        "profile_time_utc"
                    ]
                ),

                "actual_profile_latitude": (
                    candidate[
                        "latitude"
                    ]
                ),

                "actual_profile_longitude": (
                    candidate[
                        "longitude"
                    ]
                ),

                "matched_pressure_dbar": (
                    candidate[
                        "pres_dbar"
                    ]
                ),

                "spatial_distance_degrees": (
                    candidate[
                        "spatial_distance_degrees"
                    ]
                ),

                "pressure_difference_dbar": (
                    candidate[
                        "pressure_difference_dbar"
                    ]
                ),

                "time_difference_seconds": (
                    candidate[
                        "time_difference_seconds"
                    ]
                ),
            },

            "candidate_request": {
                "url": candidate_url,

                "metadata": candidate_metadata,
            },

            "profile_request": {
                "url": profile_url,

                "units_row": profile_units,
            },

            "files": {
                "raw": str(
                    raw_path
                ),

                "parsed": str(
                    parsed_path
                ),

                "normalized": str(
                    normalized_path
                ),
            },

            "database": {
                "database": str(
                    self.store.db_path
                ),

                "rows_inserted": inserted,

                "profile_rows_available": (
                    len(
                        stored_profile
                    )
                ),
            },

            "profile_statistics": {
                "pressure_min_dbar": (
                    min(
                        pressure_values
                    )
                    if pressure_values
                    else None
                ),

                "pressure_max_dbar": (
                    max(
                        pressure_values
                    )
                    if pressure_values
                    else None
                ),

                "temperature_min_c": (
                    min(
                        temperature_values
                    )
                    if temperature_values
                    else None
                ),

                "temperature_max_c": (
                    max(
                        temperature_values
                    )
                    if temperature_values
                    else None
                ),

                "salinity_min_psu": (
                    min(
                        salinity_values
                    )
                    if salinity_values
                    else None
                ),

                "salinity_max_psu": (
                    max(
                        salinity_values
                    )
                    if salinity_values
                    else None
                ),
            },

            "scientific_rules": {
                "PRES_units": "dbar",

                "PRES_converted_to_depth": False,

                "TEMP_units": "degree_Celsius",

                "PSAL_units": "PSU",

                "missing_values_preserved_as_null": True,

                "interpolation_performed": False,

                "synthetic_values_created": False,

                "actual_profile_time_preserved": True,
            },

            "acquired_at_utc": (
                self.utc_now()
            ),
        }

        provenance_path = (
            self.write_provenance(
                provenance=provenance,

                platform_number=platform_number,

                cycle_number=cycle_number,
            )
        )

        return {
            "available": True,

            "source": SOURCE_NAME,

            "dataset": DATASET_NAME,

            "automatic": True,

            "synthetic": False,

            "interpolation": False,

            "pressure_converted_to_depth": False,

            "request": {
                "latitude": latitude,

                "longitude": longitude,

                "pressure_dbar": pressure_dbar,

                "time_utc": time_utc,
            },

            "profile": {
                "platform_number": (
                    platform_number
                ),

                "cycle_number": (
                    cycle_number
                ),

                "profile_time_utc": (
                    selected_stored[
                        "profile_time_utc"
                    ]
                ),

                "latitude": (
                    selected_stored[
                        "latitude"
                    ]
                ),

                "longitude": (
                    selected_stored[
                        "longitude"
                    ]
                ),
            },

            "observation": {
                "pres_dbar": (
                    selected_stored[
                        "pres_dbar"
                    ]
                ),

                "pres_qc": (
                    selected_stored[
                        "pres_qc"
                    ]
                ),

                "pres_adjusted_dbar": (
                    selected_stored[
                        "pres_adjusted_dbar"
                    ]
                ),

                "pres_adjusted_qc": (
                    selected_stored[
                        "pres_adjusted_qc"
                    ]
                ),

                "temp_c": (
                    selected_stored[
                        "temp_c"
                    ]
                ),

                "temp_qc": (
                    selected_stored[
                        "temp_qc"
                    ]
                ),

                "temp_adjusted_c": (
                    selected_stored[
                        "temp_adjusted_c"
                    ]
                ),

                "temp_adjusted_qc": (
                    selected_stored[
                        "temp_adjusted_qc"
                    ]
                ),

                "psal_psu": (
                    selected_stored[
                        "psal_psu"
                    ]
                ),

                "psal_qc": (
                    selected_stored[
                        "psal_qc"
                    ]
                ),

                "psal_adjusted_psu": (
                    selected_stored[
                        "psal_adjusted_psu"
                    ]
                ),

                "psal_adjusted_qc": (
                    selected_stored[
                        "psal_adjusted_qc"
                    ]
                ),
            },

            "matching": {
                "spatial_distance_degrees": (
                    candidate[
                        "spatial_distance_degrees"
                    ]
                ),

                "pressure_difference_dbar": (
                    abs(
                        float(
                            selected_stored[
                                "pres_dbar"
                            ]
                        )
                        - pressure_dbar
                    )
                    if selected_stored[
                        "pres_dbar"
                    ] is not None
                    else None
                ),

                "actual_profile_time_utc": (
                    selected_stored[
                        "profile_time_utc"
                    ]
                ),
            },

            "provenance": {
                "candidate_url": candidate_url,

                "profile_url": profile_url,

                "raw_file": str(
                    raw_path
                ),

                "parsed_file": str(
                    parsed_path
                ),

                "normalized_file": str(
                    normalized_path
                ),

                "provenance_file": str(
                    provenance_path
                ),
            },
        }


# =============================================================================
# COMMAND LINE TEST
# =============================================================================

def main() -> None:

    import argparse

    parser = argparse.ArgumentParser(
        description=(
            "Acquire or discover real Argo observations "
            "from INCOIS ERDDAP."
        )
    )

    subparsers = parser.add_subparsers(
        dest="command"
    )

    # -------------------------------------------------------------------------
    # acquire
    # -------------------------------------------------------------------------

    acquire_parser = subparsers.add_parser(
        "acquire"
    )

    acquire_parser.add_argument(
        "--latitude",
        type=float,
        required=True,
    )

    acquire_parser.add_argument(
        "--longitude",
        type=float,
        required=True,
    )

    acquire_parser.add_argument(
        "--pressure-dbar",
        type=float,
        required=True,
    )

    acquire_parser.add_argument(
        "--time-utc",
        type=str,
        default=None,
    )

    acquire_parser.add_argument(
        "--radius-degrees",
        type=float,
        default=0.5,
    )

    acquire_parser.add_argument(
        "--pressure-tolerance-dbar",
        type=float,
        default=25.0,
    )

    acquire_parser.add_argument(
        "--time-window-days",
        type=float,
        default=30.0,
    )

    # -------------------------------------------------------------------------
    # profile
    # -------------------------------------------------------------------------

    profile_parser = subparsers.add_parser(
        "profile"
    )

    profile_parser.add_argument(
        "--platform-number",
        type=str,
        required=True,
    )

    profile_parser.add_argument(
        "--cycle-number",
        type=int,
        required=True,
    )

    # -------------------------------------------------------------------------
    # discover
    # -------------------------------------------------------------------------

    discover_parser = subparsers.add_parser(
        "discover"
    )

    discover_parser.add_argument(
        "--latitude",
        type=float,
        required=True,
    )

    discover_parser.add_argument(
        "--longitude",
        type=float,
        required=True,
    )

    discover_parser.add_argument(
        "--radius-degrees",
        type=float,
        default=5.0,
    )

    discover_parser.add_argument(
        "--time-utc",
        type=str,
        default=None,
    )

    discover_parser.add_argument(
        "--time-window-days",
        type=float,
        default=30.0,
    )

    discover_parser.add_argument(
        "--limit",
        type=int,
        default=100,
    )

    args = parser.parse_args()

    manager = ArgoLiveManager()

    # =========================================================================
    # PROFILE ACQUISITION
    # =========================================================================

    if args.command == "profile":

        result = manager.acquire_profile(
            platform_number=(
                args.platform_number
            ),

            cycle_number=(
                args.cycle_number
            ),
        )

        print()
        print(
            json.dumps(
                result,
                indent=2,
                ensure_ascii=False,
                default=str,
            )
        )

        return

    # =========================================================================
    # PROFILE DISCOVERY
    # =========================================================================

    if args.command == "discover":

        result = manager.discover_profiles(
            latitude=args.latitude,

            longitude=args.longitude,

            radius_degrees=args.radius_degrees,

            time_utc=args.time_utc,

            time_window_days=(
                args.time_window_days
            ),

            limit=args.limit,
        )

        print()
        print(
            json.dumps(
                result,
                indent=2,
                ensure_ascii=False,
                default=str,
            )
        )

        return

    # =========================================================================
    # POINT + PRESSURE
    # =========================================================================

    if args.command == "acquire":

        result = manager.acquire(
            latitude=args.latitude,

            longitude=args.longitude,

            pressure_dbar=args.pressure_dbar,

            time_utc=args.time_utc,

            radius_degrees=args.radius_degrees,

            pressure_tolerance_dbar=(
                args.pressure_tolerance_dbar
            ),

            time_window_days=(
                args.time_window_days
            ),
        )

        print()
        print(
            json.dumps(
                result,
                indent=2,
                ensure_ascii=False,
                default=str,
            )
        )

        return

    parser.print_help()


if __name__ == "__main__":
    main()