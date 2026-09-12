
from __future__ import annotations

from io import StringIO
from pathlib import Path
from urllib.parse import urlencode

import httpx
import pandas as pd
import truststore


# -----------------------------------------------------------------------------
# OceanSight-V
# Real INCOIS Indian Argo Float Test
#
# Purpose:
#   Retrieve a SMALL real subset from the INCOIS Indian_ARGO_Floats tabledap
#   dataset.
#
#   We deliberately request a narrow time window so we do not accidentally
#   download the entire Argo archive.
#
# Preserved scientific fields:
#   PLATFORM_NUMBER
#   CYCLE_NUMBER
#   DIRECTION
#   time
#   JULD_LOCATION
#   latitude
#   longitude
#   PRES
#   PRES_QC
#   PRES_ADJUSTED
#   PRES_ADJUSTED_QC
#   TEMP
#   TEMP_QC
#   TEMP_ADJUSTED
#   TEMP_ADJUSTED_QC
#   PSAL
#   PSAL_QC
#   PSAL_ADJUSTED
#   PSAL_ADJUSTED_QC
# -----------------------------------------------------------------------------


BASE_URL = (
    "https://erddap.incois.gov.in/erddap/tabledap/"
    "Indian_ARGO_Floats.csv"
)

RAW_DIR = Path(__file__).resolve().parent.parent / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)


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


# The dataset's published coverage currently ends on 2025-04-23.
# Use a small 24-hour window around that date rather than calling it "live".
START_TIME = "2025-04-23T00:00:00Z"
END_TIME = "2025-04-24T00:00:00Z"


def build_url() -> str:
    """
    Build a valid ERDDAP tabledap URL.

    ERDDAP uses:
        dataset.csv?variables&constraints
    """

    variable_selection = ",".join(VARIABLES)

    constraints = (
        f"time>={START_TIME}"
        f"&time<={END_TIME}"
    )

    return (
        f"{BASE_URL}?{variable_selection}&{constraints}"
    )


def parse_erddap_csv(text: str) -> pd.DataFrame:
    """
    Parse an ERDDAP CSV response.

    ERDDAP CSV commonly looks like:

        variable headers
        units row
        data rows

    We remove the units row for pandas processing but print and preserve
    it separately.
    """

    lines = text.splitlines()

    if len(lines) < 3:
        raise ValueError(
            "INCOIS returned too little data. "
            f"Received {len(lines)} lines."
        )

    header = lines[0]
    units = lines[1]

    print()
    print("ERDDAP COLUMN HEADER")
    print("-" * 80)
    print(header)

    print()
    print("ERDDAP UNITS")
    print("-" * 80)
    print(units)

    csv_for_pandas = "\n".join(
        [header] + lines[2:]
    )

    return pd.read_csv(
        StringIO(csv_for_pandas)
    )


def main() -> None:
    truststore.inject_into_ssl()

    print("=" * 80)
    print("OCEANSIGHT-V")
    print("REAL INCOIS INDIAN ARGO FLOAT TEST")
    print("=" * 80)

    url = build_url()

    print()
    print("DATASET")
    print("-" * 80)
    print("Indian_ARGO_Floats")
    print("Provider: INCOIS")
    print("Service: ERDDAP tabledap")

    print()
    print("TIME WINDOW")
    print("-" * 80)
    print(f"Start: {START_TIME}")
    print(f"End  : {END_TIME}")

    print()
    print("REQUEST URL")
    print("-" * 80)
    print(url)

    timeout = httpx.Timeout(
        connect=20.0,
        read=120.0,
        write=30.0,
        pool=30.0,
    )

    print()
    print("DOWNLOADING REAL INCOIS DATA...")
    print("-" * 80)

    with httpx.Client(
        verify=True,
        timeout=timeout,
        follow_redirects=True,
        headers={
            "User-Agent": "OceanSight-V/1.0"
        },
    ) as client:

        response = client.get(url)

    print(f"HTTP status: {response.status_code}")

    if response.status_code != 200:
        print()
        print("SERVER RESPONSE")
        print("-" * 80)
        print(response.text[:4000])

        raise RuntimeError(
            "INCOIS Argo request failed."
        )

    if not response.text.strip():
        raise RuntimeError(
            "INCOIS returned an empty response."
        )

    dataframe = parse_erddap_csv(
        response.text
    )

    if dataframe.empty:
        raise RuntimeError(
            "INCOIS returned no Argo rows for the selected time window."
        )

    # -------------------------------------------------------------------------
    # BASIC INFORMATION
    # -------------------------------------------------------------------------

    print()
    print("RESULT")
    print("-" * 80)

    print(f"Rows received: {len(dataframe)}")
    print(
        "Columns received:",
        len(dataframe.columns),
    )

    print()
    print("COLUMN NAMES")
    print("-" * 80)

    for column in dataframe.columns:
        print(column)

    # -------------------------------------------------------------------------
    # FLOAT / LOCATION SUMMARY
    # -------------------------------------------------------------------------

    print()
    print("FLOAT SUMMARY")
    print("-" * 80)

    if "PLATFORM_NUMBER" in dataframe.columns:
        print(
            "Unique floats:",
            dataframe["PLATFORM_NUMBER"]
            .dropna()
            .astype(str)
            .nunique(),
        )

        print(
            "Example float IDs:",
            dataframe["PLATFORM_NUMBER"]
            .dropna()
            .astype(str)
            .drop_duplicates()
            .head(10)
            .tolist(),
        )

    if "CYCLE_NUMBER" in dataframe.columns:
        numeric_cycle = pd.to_numeric(
            dataframe["CYCLE_NUMBER"],
            errors="coerce",
        )

        print(
            "Minimum cycle:",
            numeric_cycle.min(),
        )

        print(
            "Maximum cycle:",
            numeric_cycle.max(),
        )

    # -------------------------------------------------------------------------
    # PRESSURE CHECK
    # -------------------------------------------------------------------------

    print()
    print("PRESSURE CHECK")
    print("-" * 80)

    if "PRES" in dataframe.columns:
        pressure = pd.to_numeric(
            dataframe["PRES"],
            errors="coerce",
        )

        print(
            "Minimum PRES:",
            pressure.min(),
            "decibar",
        )

        print(
            "Maximum PRES:",
            pressure.max(),
            "decibar",
        )

        print(
            "Valid PRES rows:",
            int(pressure.notna().sum()),
        )

    if "PRES_QC" in dataframe.columns:
        print(
            "PRES_QC values:",
            sorted(
                dataframe["PRES_QC"]
                .dropna()
                .astype(str)
                .unique()
                .tolist()
            ),
        )

    # -------------------------------------------------------------------------
    # TEMPERATURE CHECK
    # -------------------------------------------------------------------------

    print()
    print("TEMPERATURE CHECK")
    print("-" * 80)

    if "TEMP" in dataframe.columns:
        temperature = pd.to_numeric(
            dataframe["TEMP"],
            errors="coerce",
        )

        print(
            "Minimum TEMP:",
            temperature.min(),
            "°C",
        )

        print(
            "Maximum TEMP:",
            temperature.max(),
            "°C",
        )

        print(
            "Valid TEMP rows:",
            int(temperature.notna().sum()),
        )

    if "TEMP_QC" in dataframe.columns:
        print(
            "TEMP_QC values:",
            sorted(
                dataframe["TEMP_QC"]
                .dropna()
                .astype(str)
                .unique()
                .tolist()
            ),
        )

    # -------------------------------------------------------------------------
    # SALINITY CHECK
    # -------------------------------------------------------------------------

    print()
    print("SALINITY CHECK")
    print("-" * 80)

    if "PSAL" in dataframe.columns:
        salinity = pd.to_numeric(
            dataframe["PSAL"],
            errors="coerce",
        )

        print(
            "Minimum PSAL:",
            salinity.min(),
            "PSU",
        )

        print(
            "Maximum PSAL:",
            salinity.max(),
            "PSU",
        )

        print(
            "Valid PSAL rows:",
            int(salinity.notna().sum()),
        )

    if "PSAL_QC" in dataframe.columns:
        print(
            "PSAL_QC values:",
            sorted(
                dataframe["PSAL_QC"]
                .dropna()
                .astype(str)
                .unique()
                .tolist()
            ),
        )

    # -------------------------------------------------------------------------
    # LOCATION CHECK
    # -------------------------------------------------------------------------

    print()
    print("LOCATION CHECK")
    print("-" * 80)

    if "latitude" in dataframe.columns:
        latitude = pd.to_numeric(
            dataframe["latitude"],
            errors="coerce",
        )

        print(
            "Latitude range:",
            latitude.min(),
            "to",
            latitude.max(),
        )

    if "longitude" in dataframe.columns:
        longitude = pd.to_numeric(
            dataframe["longitude"],
            errors="coerce",
        )

        print(
            "Longitude range:",
            longitude.min(),
            "to",
            longitude.max(),
        )

    # -------------------------------------------------------------------------
    # SAMPLE REAL ROWS
    # -------------------------------------------------------------------------

    print()
    print("FIRST 20 REAL ARGO OBSERVATIONS")
    print("-" * 80)

    preferred_columns = [
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

    available_columns = [
        column
        for column in preferred_columns
        if column in dataframe.columns
    ]

    print(
        dataframe[
            available_columns
        ].head(20).to_string(index=False)
    )

    # -------------------------------------------------------------------------
    # SAVE RAW RESPONSE
    # -------------------------------------------------------------------------

    raw_path = (
        RAW_DIR
        / "Indian_ARGO_Floats_test.csv"
    )

    raw_path.write_text(
        response.text,
        encoding="utf-8",
    )

    print()
    print("RAW RESPONSE SAVED")
    print("-" * 80)
    print(raw_path)

    # -------------------------------------------------------------------------
    # SAVE PARSED COPY
    # -------------------------------------------------------------------------

    parsed_path = (
        RAW_DIR
        / "Indian_ARGO_Floats_test_parsed.csv"
    )

    dataframe.to_csv(
        parsed_path,
        index=False,
    )

    print()
    print("PARSED COPY SAVED")
    print("-" * 80)
    print(parsed_path)

    # -------------------------------------------------------------------------
    # FINAL VALIDATION
    # -------------------------------------------------------------------------

    required_columns = [
        "PLATFORM_NUMBER",
        "CYCLE_NUMBER",
        "time",
        "latitude",
        "longitude",
        "PRES",
        "TEMP",
        "PSAL",
        "PRES_QC",
        "TEMP_QC",
        "PSAL_QC",
    ]

    missing_required = [
        column
        for column in required_columns
        if column not in dataframe.columns
    ]

    print()
    print("VALIDATION")
    print("-" * 80)

    print(
        "Required columns present:",
        not missing_required,
    )

    if missing_required:
        print(
            "Missing:",
            ", ".join(missing_required),
        )
    else:
        print("Pressure preserved: PASS")
        print("Temperature preserved: PASS")
        print("Salinity preserved: PASS")
        print("Float ID preserved: PASS")
        print("Cycle number preserved: PASS")
        print("Location preserved: PASS")
        print("Time preserved: PASS")
        print("Pressure QC preserved: PASS")
        print("Temperature QC preserved: PASS")
        print("Salinity QC preserved: PASS")

    print()
    print("=" * 80)
    print("ARGO TEST COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    main()
