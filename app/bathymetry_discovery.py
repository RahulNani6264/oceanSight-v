
from __future__ import annotations

from io import StringIO
from pathlib import Path

import httpx
import pandas as pd
import truststore


# =============================================================================
# OCEANSIGHT-V
# REAL INCOIS BATHYMETRY DISCOVERY
#
# We deliberately DO NOT assume a bathymetry dataset ID.
#
# This program:
#
#   1. Downloads INCOIS's active allDatasets catalog
#   2. Saves the complete catalog locally
#   3. Searches dataset titles/summaries/metadata for:
#
#        bathymetry
#        bathymetric
#        depth
#        elevation
#        seabed
#        ocean floor
#        topo
#        topography
#
#   4. Reports datasets that appear relevant
#   5. Reports altitude/depth metadata when available
#
# No scientific data is fabricated.
# =============================================================================


BASE_URL = (
    "https://erddap.incois.gov.in/erddap/"
    "tabledap/allDatasets.csv"
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent

METADATA_DIR = (
    PROJECT_ROOT / "metadata"
)

RAW_DIR = (
    PROJECT_ROOT / "raw"
)

METADATA_DIR.mkdir(
    parents=True,
    exist_ok=True,
)

RAW_DIR.mkdir(
    parents=True,
    exist_ok=True,
)


# These are fields published by the INCOIS allDatasets catalog.
FIELDS = [
    "datasetID",
    "accessible",
    "institution",
    "dataStructure",
    "cdm_data_type",
    "class",
    "title",
    "minLongitude",
    "maxLongitude",
    "longitudeSpacing",
    "minLatitude",
    "maxLatitude",
    "latitudeSpacing",
    "minAltitude",
    "maxAltitude",
    "minTime",
    "maxTime",
    "timeSpacing",
    "griddap",
    "tabledap",
    "metadata",
    "sourceUrl",
    "infoUrl",
    "testOutOfDate",
    "outOfDate",
    "summary",
]


SEARCH_TERMS = [
    "bathymetry",
    "bathymetric",
    "bathymetric",
    "depth",
    "elevation",
    "seabed",
    "sea floor",
    "ocean floor",
    "topography",
    "topo",
    "terrain",
]


def build_url() -> str:
    return (
        f"{BASE_URL}?"
        + ",".join(FIELDS)
    )


def safe_text(value: object) -> str:
    if value is None:
        return ""

    try:
        if pd.isna(value):
            return ""
    except (
        TypeError,
        ValueError,
    ):
        pass

    return str(value).strip()


def search_score(row: pd.Series) -> tuple[int, list[str]]:
    """
    Score a dataset based on explicit metadata wording.

    This is discovery only.
    It does NOT declare that a dataset is bathymetry.
    """

    title = safe_text(
        row.get("title")
    ).lower()

    summary = safe_text(
        row.get("summary")
    ).lower()

    dataset_id = safe_text(
        row.get("datasetID")
    ).lower()

    combined = (
        f"{title} {summary} {dataset_id}"
    )

    matched: list[str] = []

    score = 0

    for term in SEARCH_TERMS:

        if term.lower() in combined:

            matched.append(term)

            # Stronger signals first.
            if term in {
                "bathymetry",
                "bathymetric",
            }:
                score += 10

            elif term in {
                "seabed",
                "sea floor",
                "ocean floor",
                "topography",
            }:
                score += 8

            elif term in {
                "elevation",
                "depth",
            }:
                score += 4

            else:
                score += 1

    return score, matched


def print_dataset(
    row: pd.Series,
    score: int,
    matched: list[str],
) -> None:

    print()
    print("=" * 80)
    print("CANDIDATE")
    print("=" * 80)

    print(
        "Dataset ID:",
        safe_text(row.get("datasetID")),
    )

    print(
        "Title:",
        safe_text(row.get("title")),
    )

    print(
        "Structure:",
        safe_text(row.get("dataStructure")),
    )

    print(
        "CDM type:",
        safe_text(row.get("cdm_data_type")),
    )

    print(
        "Institution:",
        safe_text(row.get("institution")),
    )

    print(
        "Accessible:",
        safe_text(row.get("accessible")),
    )

    print()
    print("GEOGRAPHIC COVERAGE")
    print("-" * 80)

    print(
        "Longitude:",
        safe_text(row.get("minLongitude")),
        "to",
        safe_text(row.get("maxLongitude")),
    )

    print(
        "Latitude:",
        safe_text(row.get("minLatitude")),
        "to",
        safe_text(row.get("maxLatitude")),
    )

    print(
        "Longitude spacing:",
        safe_text(row.get("longitudeSpacing")),
    )

    print(
        "Latitude spacing:",
        safe_text(row.get("latitudeSpacing")),
    )

    print()
    print("VERTICAL / ELEVATION METADATA")
    print("-" * 80)

    print(
        "Minimum altitude / negative depth:",
        safe_text(row.get("minAltitude")),
        "m",
    )

    print(
        "Maximum altitude / negative depth:",
        safe_text(row.get("maxAltitude")),
        "m",
    )

    print()
    print("TIME")
    print("-" * 80)

    print(
        "Minimum:",
        safe_text(row.get("minTime")),
    )

    print(
        "Maximum:",
        safe_text(row.get("maxTime")),
    )

    print(
        "Time spacing:",
        safe_text(row.get("timeSpacing")),
    )

    print()
    print("MATCHED TERMS")
    print("-" * 80)

    print(
        ", ".join(matched)
        if matched
        else "none"
    )

    print()
    print("DISCOVERY SCORE")
    print("-" * 80)

    print(score)

    print()
    print("ACCESS URLS")
    print("-" * 80)

    print(
        "griddap:",
        safe_text(row.get("griddap")),
    )

    print(
        "tabledap:",
        safe_text(row.get("tabledap")),
    )

    print(
        "metadata:",
        safe_text(row.get("metadata")),
    )

    print(
        "info:",
        safe_text(row.get("infoUrl")),
    )

    print()
    print("SUMMARY")
    print("-" * 80)

    print(
        safe_text(row.get("summary"))
    )


def main() -> None:
    truststore.inject_into_ssl()

    print("=" * 80)
    print("OCEANSIGHT-V")
    print("INCOIS REAL BATHYMETRY DISCOVERY")
    print("=" * 80)

    url = build_url()

    print()
    print("CATALOG URL")
    print("-" * 80)
    print(url)

    timeout = httpx.Timeout(
        connect=20.0,
        read=120.0,
        write=30.0,
        pool=30.0,
    )

    print()
    print("DOWNLOADING ACTIVE INCOIS DATASET CATALOG...")
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

    print(
        "HTTP status:",
        response.status_code,
    )

    if response.status_code != 200:

        print()
        print(response.text[:5000])

        raise RuntimeError(
            "Could not retrieve INCOIS allDatasets catalog."
        )

    if not response.text.strip():

        raise RuntimeError(
            "INCOIS returned an empty catalog."
        )

    # -------------------------------------------------------------------------
    # SAVE RAW CATALOG
    # -------------------------------------------------------------------------

    raw_path = (
        RAW_DIR
        / "incois_allDatasets.csv"
    )

    raw_path.write_text(
        response.text,
        encoding="utf-8",
    )

    print()
    print("RAW CATALOG SAVED")
    print("-" * 80)
    print(raw_path)

    # -------------------------------------------------------------------------
    # PARSE
    # -------------------------------------------------------------------------

    dataframe = pd.read_csv(
        StringIO(response.text)
    )

    print()
    print("CATALOG SUMMARY")
    print("-" * 80)

    print(
        "Datasets returned:",
        len(dataframe),
    )

    print(
        "Columns returned:",
        len(dataframe.columns),
    )

    # -------------------------------------------------------------------------
    # SEARCH
    # -------------------------------------------------------------------------

    candidates: list[
        tuple[int, list[str], int]
    ] = []

    for index, row in dataframe.iterrows():

        score, matched = search_score(row)

        if score > 0:

            candidates.append(
                (
                    score,
                    matched,
                    index,
                )
            )

    candidates.sort(
        key=lambda item: item[0],
        reverse=True,
    )

    print()
    print("DISCOVERY RESULTS")
    print("-" * 80)

    if not candidates:

        print(
            "No active INCOIS dataset matched the bathymetry/depth "
            "discovery terms."
        )

        print()
        print(
            "This does NOT prove INCOIS has no bathymetry data."
        )

        print(
            "It means no currently active allDatasets record exposed "
            "matching wording in the searched metadata."
        )

    else:

        print(
            "Candidate datasets:",
            len(candidates),
        )

        for position, (
            score,
            matched,
            index,
        ) in enumerate(
            candidates,
            start=1,
        ):

            row = dataframe.iloc[index]

            print()
            print(
                f"[{position}] "
                f"{safe_text(row.get('datasetID'))}"
            )

            print(
                "    Title:",
                safe_text(row.get("title")),
            )

            print(
                "    Structure:",
                safe_text(row.get("dataStructure")),
            )

            print(
                "    Altitude/depth range:",
                safe_text(row.get("minAltitude")),
                "to",
                safe_text(row.get("maxAltitude")),
                "m",
            )

            print(
                "    Matched:",
                ", ".join(matched),
            )

            print(
                "    Score:",
                score,
            )

    # -------------------------------------------------------------------------
    # DETAILED CANDIDATES
    # -------------------------------------------------------------------------

    output_rows = []

    for score, matched, index in candidates:

        row = dataframe.iloc[index]

        output_rows.append(
            {
                "datasetID": safe_text(
                    row.get("datasetID")
                ),
                "title": safe_text(
                    row.get("title")
                ),
                "dataStructure": safe_text(
                    row.get("dataStructure")
                ),
                "cdm_data_type": safe_text(
                    row.get("cdm_data_type")
                ),
                "accessible": safe_text(
                    row.get("accessible")
                ),
                "minLongitude": safe_text(
                    row.get("minLongitude")
                ),
                "maxLongitude": safe_text(
                    row.get("maxLongitude")
                ),
                "minLatitude": safe_text(
                    row.get("minLatitude")
                ),
                "maxLatitude": safe_text(
                    row.get("maxLatitude")
                ),
                "latitudeSpacing": safe_text(
                    row.get("latitudeSpacing")
                ),
                "longitudeSpacing": safe_text(
                    row.get("longitudeSpacing")
                ),
                "minAltitude": safe_text(
                    row.get("minAltitude")
                ),
                "maxAltitude": safe_text(
                    row.get("maxAltitude")
                ),
                "minTime": safe_text(
                    row.get("minTime")
                ),
                "maxTime": safe_text(
                    row.get("maxTime")
                ),
                "griddap": safe_text(
                    row.get("griddap")
                ),
                "tabledap": safe_text(
                    row.get("tabledap")
                ),
                "metadata": safe_text(
                    row.get("metadata")
                ),
                "infoUrl": safe_text(
                    row.get("infoUrl")
                ),
                "summary": safe_text(
                    row.get("summary")
                ),
                "matched_terms": matched,
                "discovery_score": score,
            }
        )

    # -------------------------------------------------------------------------
    # SAVE DISCOVERY JSON
    # -------------------------------------------------------------------------

    import json

    json_path = (
        METADATA_DIR
        / "bathymetry_candidates.json"
    )

    json_path.write_text(
        json.dumps(
            {
                "source": (
                    "INCOIS ERDDAP allDatasets"
                ),
                "catalog_url": url,
                "candidate_count": len(
                    output_rows
                ),
                "candidates": output_rows,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print()
    print("DISCOVERY JSON SAVED")
    print("-" * 80)
    print(json_path)

    # -------------------------------------------------------------------------
    # SAVE COMPLETE PARSED CATALOG
    # -------------------------------------------------------------------------

    catalog_path = (
        METADATA_DIR
        / "incois_allDatasets_catalog.csv"
    )

    dataframe.to_csv(
        catalog_path,
        index=False,
    )

    print()
    print("PARSED CATALOG SAVED")
    print("-" * 80)
    print(catalog_path)

    # -------------------------------------------------------------------------
    # END
    # -------------------------------------------------------------------------

    print()
    print("=" * 80)
    print("BATHYMETRY DISCOVERY COMPLETE")
    print("=" * 80)

    print()
    print(
        "IMPORTANT:"
    )

    print(
        "No bathymetry dataset has been selected automatically."
    )

    print(
        "A candidate must be inspected and its actual variables "
        "verified before any seabed is built."
    )


if __name__ == "__main__":
    main()

