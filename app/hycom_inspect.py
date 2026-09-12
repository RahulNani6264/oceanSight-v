
from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

import httpx
import truststore


# =============================================================================
# OCEANSIGHT-V
# REMOTE INCOIS THREDDS / HYCOM INSPECTOR
#
# IMPORTANT:
#   This version NEVER downloads the huge NetCDF file.
#
# Instead it asks the THREDDS/OPeNDAP server for:
#   - DDS  -> structure / dimensions / variable declarations
#   - DAS  -> attributes / units / fill values / long names
#
# We then use that metadata to identify:
#   - latitude
#   - longitude
#   - time
#   - vertical/depth coordinate
#   - temperature
#   - salinity
#   - U current
#   - V current
#   - SSH
#   - MLD
#   - TCHP
#   - possible bathymetry/bottom-depth fields
#
# No full scientific array is downloaded.
# =============================================================================


PROJECT_ROOT = (
    Path(__file__).resolve().parent.parent
)

METADATA_DIR = (
    PROJECT_ROOT / "metadata"
)

METADATA_DIR.mkdir(
    parents=True,
    exist_ok=True,
)


# -----------------------------------------------------------------------------
# Officially listed by the current INCOIS RSMC download page.
# -----------------------------------------------------------------------------

FILE_NAME = "RSMC_hycom_20260911.nc"

THREDDS_ROOT = (
    "https://incois.gov.in/thredds"
)

OPENDAP_BASE = (
    f"{THREDDS_ROOT}/dodsC/osf/currents2"
)

OPENDAP_DATASET = (
    f"{OPENDAP_BASE}/{FILE_NAME}"
)

DDS_URL = (
    f"{OPENDAP_DATASET}.dds"
)

DAS_URL = (
    f"{OPENDAP_DATASET}.das"
)


# -----------------------------------------------------------------------------
# Keywords used only for discovery.
# We DO NOT automatically declare a variable to be scientifically correct
# merely because its name contains one of these strings.
# -----------------------------------------------------------------------------

SCIENTIFIC_GROUPS = {
    "temperature": [
        "temp",
        "temperature",
        "water_temperature",
        "water_temp",
    ],
    "salinity": [
        "sal",
        "salinity",
        "psal",
        "water_salinity",
    ],
    "u_current": [
        "u",
        "uo",
        "uvel",
        "ucur",
        "eastward",
        "zonal",
        "water_u",
    ],
    "v_current": [
        "v",
        "vo",
        "vvel",
        "vcur",
        "northward",
        "meridional",
        "water_v",
    ],
    "ssh": [
        "ssh",
        "sea_surface_height",
        "surface_height",
        "sla",
    ],
    "mld": [
        "mld",
        "mixed_layer",
        "mixed_layer_depth",
    ],
    "tchp": [
        "tchp",
        "tropical_cyclone_heat",
        "heat_potential",
    ],
    "vertical": [
        "depth",
        "depths",
        "z",
        "lev",
        "level",
        "pressure",
        "sigma",
        "isopycnal",
    ],
    "bathymetry": [
        "bathymetry",
        "bathymetric",
        "bottom_depth",
        "seafloor",
        "sea_floor",
        "elevation",
        "topography",
        "topo",
        "bottom",
        "hbot",
    ],
}


def print_separator(title: str) -> None:
    print()
    print("=" * 80)
    print(title)
    print("=" * 80)


def safe_text(value: object) -> str:
    if value is None:
        return ""

    text = str(value)

    if len(text) > 500:
        text = text[:500] + "..."

    return text


def fetch_text(
    client: httpx.Client,
    url: str,
) -> str:
    print()
    print("REQUEST")
    print("-" * 80)
    print(url)

    response = client.get(url)

    print(
        "HTTP status:",
        response.status_code,
    )

    content_type = response.headers.get(
        "content-type",
        "",
    )

    print(
        "Content-Type:",
        content_type,
    )

    if response.status_code != 200:
        print()
        print(
            "SERVER RESPONSE"
        )
        print("-" * 80)
        print(
            response.text[:5000]
        )

        raise RuntimeError(
            f"THREDDS request failed: "
            f"{response.status_code}"
        )

    return response.text


def extract_names_from_dds(
    dds_text: str,
) -> list[str]:
    """
    Best-effort extraction of variable names from DDS.

    THREDDS/OPeNDAP DDS commonly contains declarations such as:

        Float32 temperature[time=1][depth=6][lat=...][lon=...];

    We extract the identifier before the first '['.

    This is intentionally parser-light because DDS syntax can vary.
    """

    names: list[str] = []

    for raw_line in dds_text.splitlines():

        line = raw_line.strip()

        if not line:
            continue

        if line.startswith(
            (
                "Dataset",
                "Grid",
                "Sequence",
                "Structure",
                "Map",
            )
        ):
            continue

        if "[" not in line:
            continue

        left = line.split(
            "[",
            1,
        )[0].strip()

        parts = left.split()

        if len(parts) < 2:
            continue

        name = parts[-1].strip(
            ";"
        )

        if not name:
            continue

        if name not in names:
            names.append(name)

    return names


def print_dds(
    dds_text: str,
) -> list[str]:

    print_separator(
        "OPENDAP DDS - DATA STRUCTURE"
    )

    print(
        dds_text
    )

    variable_names = extract_names_from_dds(
        dds_text
    )

    print_separator(
        "VARIABLE NAMES DISCOVERED FROM DDS"
    )

    if variable_names:

        for name in variable_names:
            print(
                f"- {name}"
            )

    else:

        print(
            "No variable names could be extracted automatically."
        )

    return variable_names


def print_das(
    das_text: str,
) -> None:

    print_separator(
        "OPENDAP DAS - VARIABLE ATTRIBUTES"
    )

    print(
        das_text
    )


def find_metadata_matches(
    dds_text: str,
    das_text: str,
) -> dict[str, list[str]]:

    combined = (
        dds_text
        + "\n"
        + das_text
    ).lower()

    matches: dict[str, list[str]] = {}

    # -------------------------------------------------------------------------
    # Extract any likely variable-like identifiers from DDS.
    # -------------------------------------------------------------------------

    variable_names = extract_names_from_dds(
        dds_text
    )

    for category, terms in SCIENTIFIC_GROUPS.items():

        category_matches: list[str] = []

        for name in variable_names:

            lower_name = name.lower()

            if any(
                term.lower() in lower_name
                for term in terms
            ):

                category_matches.append(
                    name
                )

        matches[category] = (
            category_matches
        )

    # If names don't reveal something, search DAS text too.
    # This is only a clue for the human inspection stage.
    for category, terms in SCIENTIFIC_GROUPS.items():

        if matches[category]:
            continue

        found: list[str] = []

        for term in terms:

            if term.lower() in combined:

                found.append(term)

        matches[category] = found

    return matches


def print_matches(
    matches: dict[str, list[str]],
) -> None:

    print_separator(
        "SCIENTIFIC VARIABLE DISCOVERY"
    )

    for category, items in matches.items():

        print()
        print(
            f"{category}:"
        )

        if items:

            for item in items:

                print(
                    f"  - {item}"
                )

        else:

            print(
                "  No obvious match"
            )


def save_results(
    dds_text: str,
    das_text: str,
    matches: dict[str, list[str]],
) -> None:

    dds_path = (
        METADATA_DIR
        / f"{FILE_NAME}.dds.txt"
    )

    das_path = (
        METADATA_DIR
        / f"{FILE_NAME}.das.txt"
    )

    summary_path = (
        METADATA_DIR
        / f"{FILE_NAME}_remote_inspection.txt"
    )

    dds_path.write_text(
        dds_text,
        encoding="utf-8",
    )

    das_path.write_text(
        das_text,
        encoding="utf-8",
    )

    lines: list[str] = []

    lines.append(
        "OCEANSIGHT-V REMOTE INCOIS HYCOM INSPECTION"
    )

    lines.append(
        f"File: {FILE_NAME}"
    )

    lines.append(
        f"OPeNDAP: {OPENDAP_DATASET}"
    )

    lines.append(
        ""
    )

    lines.append(
        "IMPORTANT:"
    )

    lines.append(
        "No full NetCDF file was downloaded."
    )

    lines.append(
        "Only DDS and DAS metadata were requested."
    )

    lines.append(
        ""
    )

    lines.append(
        "SCIENTIFIC DISCOVERY:"
    )

    for category, items in matches.items():

        lines.append(
            f"{category}: "
            + (
                ", ".join(items)
                if items
                else "no obvious match"
            )
        )

    summary_path.write_text(
        "\n".join(lines),
        encoding="utf-8",
    )

    print()
    print("SAVED METADATA")
    print("-" * 80)

    print(
        "DDS:",
        dds_path,
    )

    print(
        "DAS:",
        das_path,
    )

    print(
        "Summary:",
        summary_path,
    )


def main() -> None:

    truststore.inject_into_ssl()

    print_separator(
        "OCEANSIGHT-V"
    )

    print(
        "REAL INCOIS HYCOM REMOTE METADATA INSPECTOR"
    )

    print()
    print(
        "Dataset:",
        FILE_NAME,
    )

    print()
    print(
        "The previous 9.85 GiB download is intentionally NOT used."
    )

    timeout = httpx.Timeout(
        connect=30.0,
        read=60.0,
        write=30.0,
        pool=30.0,
    )

    with httpx.Client(
        verify=True,
        timeout=timeout,
        follow_redirects=True,
        headers={
            "User-Agent": (
                "OceanSight-V/1.0 "
                "remote-metadata-inspector"
            )
        },
    ) as client:

        # ---------------------------------------------------------------------
        # DDS
        # ---------------------------------------------------------------------

        print_separator(
            "FETCHING DDS METADATA ONLY"
        )

        dds_text = fetch_text(
            client,
            DDS_URL,
        )

        variable_names = print_dds(
            dds_text
        )

        # ---------------------------------------------------------------------
        # DAS
        # ---------------------------------------------------------------------

        print_separator(
            "FETCHING DAS METADATA ONLY"
        )

        das_text = fetch_text(
            client,
            DAS_URL,
        )

        print_das(
            das_text
        )

    # -------------------------------------------------------------------------
    # DISCOVERY
    # -------------------------------------------------------------------------

    matches = find_metadata_matches(
        dds_text,
        das_text,
    )

    print_matches(
        matches
    )

    # -------------------------------------------------------------------------
    # IMPORTANT INTERPRETATION
    # -------------------------------------------------------------------------

    print_separator(
        "BATHYMETRY INTERPRETATION"
    )

    bathy = matches.get(
        "bathymetry",
        [],
    )

    vertical = matches.get(
        "vertical",
        [],
    )

    if bathy:

        print(
            "Bathymetry-related metadata was detected:"
        )

        for item in bathy:
            print(
                f"  - {item}"
            )

        print()
        print(
            "This is only a candidate signal."
        )

        print(
            "We must inspect its dimensions, units and values "
            "before accepting it as the seabed."
        )

    else:

        print(
            "No explicit bathymetry variable name was detected."
        )

        if vertical:

            print()
            print(
                "A vertical/depth coordinate appears to exist:"
            )

            for item in vertical:
                print(
                    f"  - {item}"
                )

        print()
        print(
            "A vertical model coordinate is NOT automatically bathymetry."
        )

    # -------------------------------------------------------------------------
    # SAVE
    # -------------------------------------------------------------------------

    save_results(
        dds_text=dds_text,
        das_text=das_text,
        matches=matches,
    )

    print_separator(
        "REMOTE HYCOM INSPECTION COMPLETE"
    )

    print()
    print(
        "SUCCESS: Only metadata was downloaded."
    )

    print(
        f"Variables discovered: {len(variable_names)}"
    )

    print()
    print(
        "Next step depends on the actual DDS/DAS output."
    )


if __name__ == "__main__":
    main()

