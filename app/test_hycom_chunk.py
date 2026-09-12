
from __future__ import annotations

import json
from pathlib import Path

import numpy as np


# =============================================================================
# OCEANSIGHT-V
# HYCOM LOCAL CHUNK VALIDATOR
# =============================================================================


PROJECT_ROOT = (
    Path(__file__).resolve().parent.parent
)

CHUNK_DIR = (
    PROJECT_ROOT
    / "processed"
    / "hycom_chunks"
)

PROVENANCE_DIR = (
    PROJECT_ROOT
    / "processed"
    / "hycom_chunk_provenance"
)


def main() -> None:

    print("=" * 80)
    print(
        "OCEANSIGHT-V"
    )
    print(
        "HYCOM LOCAL CHUNK VALIDATION"
    )
    print("=" * 80)

    # -------------------------------------------------------------------------
    # FIND CHUNK
    # -------------------------------------------------------------------------

    chunks = sorted(
        CHUNK_DIR.glob(
            "*.npz"
        )
    )

    if not chunks:

        raise FileNotFoundError(
            "No HYCOM .npz chunks found.\n\n"
            "Run first:\n"
            "python -m app.hycom_chunk_store"
        )

    chunk_path = chunks[-1]

    print()
    print(
        "Chunk:"
    )

    print(
        chunk_path
    )

    # -------------------------------------------------------------------------
    # OPEN CHUNK
    # -------------------------------------------------------------------------

    with np.load(
        chunk_path,
        allow_pickle=False,
    ) as data:

        required = [
            "time_numeric",
            "time_iso",
            "depth",
            "lat",
            "lon",

            "TEMP",
            "SALN",
            "UVEL",
            "VVEL",
            "SSH",

            "TEMP_missing",
            "SALN_missing",
            "UVEL_missing",
            "VVEL_missing",
            "SSH_missing",
        ]

        print()
        print(
            "REQUIRED ARRAYS"
        )

        print(
            "-" * 80
        )

        missing_names: list[str] = []

        for name in required:

            exists = (
                name in data.files
            )

            print(
                f"{name}: {exists}"
            )

            if not exists:
                missing_names.append(
                    name
                )

        if missing_names:

            raise RuntimeError(
                "Missing arrays:\n"
                + "\n".join(
                    missing_names
                )
            )

        # ---------------------------------------------------------------------
        # LOAD
        # ---------------------------------------------------------------------

        time_numeric = data[
            "time_numeric"
        ]

        time_iso = data[
            "time_iso"
        ]

        depth = data[
            "depth"
        ]

        lat = data[
            "lat"
        ]

        lon = data[
            "lon"
        ]

        temp = data[
            "TEMP"
        ]

        saln = data[
            "SALN"
        ]

        uvel = data[
            "UVEL"
        ]

        vvel = data[
            "VVEL"
        ]

        ssh = data[
            "SSH"
        ]

        temp_missing = data[
            "TEMP_missing"
        ]

        saln_missing = data[
            "SALN_missing"
        ]

        uvel_missing = data[
            "UVEL_missing"
        ]

        vvel_missing = data[
            "VVEL_missing"
        ]

        ssh_missing = data[
            "SSH_missing"
        ]

        # ---------------------------------------------------------------------
        # DIMENSIONS
        # ---------------------------------------------------------------------

        print()
        print(
            "DIMENSIONS"
        )

        print(
            "-" * 80
        )

        print(
            "TIME:",
            len(time_numeric),
        )

        print(
            "DEPTH:",
            len(depth),
        )

        print(
            "LAT:",
            len(lat),
        )

        print(
            "LON:",
            len(lon),
        )

        expected_4d = (
            1,
            len(depth),
            len(lat),
            len(lon),
        )

        expected_3d = (
            1,
            len(lat),
            len(lon),
        )

        print()
        print(
            "Expected TEMP/SALN/UVEL/VVEL:",
            expected_4d,
        )

        print(
            "Expected SSH:",
            expected_3d,
        )

        print()
        print(
            "Actual:"
        )

        print(
            "TEMP:",
            temp.shape,
        )

        print(
            "SALN:",
            saln.shape,
        )

        print(
            "UVEL:",
            uvel.shape,
        )

        print(
            "VVEL:",
            vvel.shape,
        )

        print(
            "SSH:",
            ssh.shape,
        )

        assert temp.shape == expected_4d
        assert saln.shape == expected_4d
        assert uvel.shape == expected_4d
        assert vvel.shape == expected_4d
        assert ssh.shape == expected_3d

        print()
        print(
            "Scientific shapes: PASS"
        )

        # ---------------------------------------------------------------------
        # MASK SHAPES
        # ---------------------------------------------------------------------

        print()
        print(
            "MISSING MASK SHAPES"
        )

        print(
            "-" * 80
        )

        assert (
            temp_missing.shape
            == temp.shape
        )

        assert (
            saln_missing.shape
            == saln.shape
        )

        assert (
            uvel_missing.shape
            == uvel.shape
        )

        assert (
            vvel_missing.shape
            == vvel.shape
        )

        assert (
            ssh_missing.shape
            == ssh.shape
        )

        print(
            "TEMP mask:",
            temp_missing.shape,
        )

        print(
            "SALN mask:",
            saln_missing.shape,
        )

        print(
            "UVEL mask:",
            uvel_missing.shape,
        )

        print(
            "VVEL mask:",
            vvel_missing.shape,
        )

        print(
            "SSH mask:",
            ssh_missing.shape,
        )

        print()
        print(
            "Missing-mask shape consistency: PASS"
        )

        # ---------------------------------------------------------------------
        # COORDINATES
        # ---------------------------------------------------------------------

        print()
        print(
            "COORDINATES"
        )

        print(
            "-" * 80
        )

        print(
            "DEPTH:",
            depth.tolist(),
        )

        print(
            "LAT:",
            lat.tolist(),
        )

        print(
            "LON:",
            lon.tolist(),
        )

        print(
            "TIME numeric:",
            time_numeric.tolist(),
        )

        print(
            "TIME ISO:",
            time_iso.tolist(),
        )

        assert (
            len(depth) == 6
        )

        assert (
            len(lat) == 8
        )

        assert (
            len(lon) == 8
        )

        assert np.all(
            np.isfinite(depth)
        )

        assert np.all(
            np.diff(depth) >= 0
        )

        assert np.all(
            np.isfinite(lat)
        )

        assert np.all(
            np.isfinite(lon)
        )

        print()
        print(
            "Depth coordinate: PASS"
        )

        print(
            "Latitude coordinate: PASS"
        )

        print(
            "Longitude coordinate: PASS"
        )

        # ---------------------------------------------------------------------
        # REAL NUMERICAL DATA
        # ---------------------------------------------------------------------

        print()
        print(
            "REAL NUMERICAL DATA"
        )

        print(
            "-" * 80
        )

        temp_valid = temp[
            ~np.isnan(temp)
        ]

        saln_valid = saln[
            ~np.isnan(saln)
        ]

        uvel_valid = uvel[
            ~np.isnan(uvel)
        ]

        vvel_valid = vvel[
            ~np.isnan(vvel)
        ]

        ssh_valid = ssh[
            ~np.isnan(ssh)
        ]

        print(
            "TEMP valid:",
            temp_valid.size,
        )

        print(
            "SALN valid:",
            saln_valid.size,
        )

        print(
            "UVEL valid:",
            uvel_valid.size,
        )

        print(
            "VVEL valid:",
            vvel_valid.size,
        )

        print(
            "SSH valid:",
            ssh_valid.size,
        )

        assert temp_valid.size > 0
        assert saln_valid.size > 0
        assert uvel_valid.size > 0
        assert vvel_valid.size > 0
        assert ssh_valid.size > 0

        print()
        print(
            "TEMP range:",
            float(temp_valid.min()),
            "to",
            float(temp_valid.max()),
            "°C",
        )

        print(
            "SALN range:",
            float(saln_valid.min()),
            "to",
            float(saln_valid.max()),
        )

        print(
            "UVEL range:",
            float(uvel_valid.min()),
            "to",
            float(uvel_valid.max()),
            "m/s",
        )

        print(
            "VVEL range:",
            float(vvel_valid.min()),
            "to",
            float(vvel_valid.max()),
            "m/s",
        )

        print(
            "SSH range:",
            float(ssh_valid.min()),
            "to",
            float(ssh_valid.max()),
            "m",
        )

        # ---------------------------------------------------------------------
        # REAL VARIATION
        # ---------------------------------------------------------------------

        print()
        print(
            "DATA VARIATION"
        )

        print(
            "-" * 80
        )

        checks = {
            "TEMP": (
                np.unique(
                    temp_valid
                ).size > 1
            ),

            "SALN": (
                np.unique(
                    saln_valid
                ).size > 1
            ),

            "UVEL": (
                np.unique(
                    uvel_valid
                ).size > 1
            ),

            "VVEL": (
                np.unique(
                    vvel_valid
                ).size > 1
            ),

            "SSH": (
                np.unique(
                    ssh_valid
                ).size > 1
            ),
        }

        for name, result in checks.items():

            print(
                f"{name} varies: {result}"
            )

            assert result

        print()
        print(
            "Real-value variation: PASS"
        )

        # ---------------------------------------------------------------------
        # MASK / NaN CONSISTENCY
        # ---------------------------------------------------------------------

        print()
        print(
            "MISSING-VALUE CONSISTENCY"
        )

        print(
            "-" * 80
        )

        assert np.array_equal(
            temp_missing,
            np.isnan(temp),
        )

        assert np.array_equal(
            saln_missing,
            np.isnan(saln),
        )

        assert np.array_equal(
            uvel_missing,
            np.isnan(uvel),
        )

        assert np.array_equal(
            vvel_missing,
            np.isnan(vvel),
        )

        assert np.array_equal(
            ssh_missing,
            np.isnan(ssh),
        )

        print(
            "TEMP: PASS"
        )

        print(
            "SALN: PASS"
        )

        print(
            "UVEL: PASS"
        )

        print(
            "VVEL: PASS"
        )

        print(
            "SSH: PASS"
        )

        # ---------------------------------------------------------------------
        # CURRENT VECTOR
        # ---------------------------------------------------------------------

        print()
        print(
            "CURRENT VECTOR"
        )

        print(
            "-" * 80
        )

        u = float(
            uvel[0, 0, 0, 0]
        )

        v = float(
            vvel[0, 0, 0, 0]
        )

        speed = float(
            np.hypot(
                u,
                v,
            )
        )

        angle = float(
            np.degrees(
                np.arctan2(
                    v,
                    u,
                )
            )
        )

        print(
            "UVEL:",
            u,
            "m/s",
        )

        print(
            "VVEL:",
            v,
            "m/s",
        )

        print(
            "Speed:",
            speed,
            "m/s",
        )

        print(
            "Mathematical angle:",
            angle,
            "degrees from east",
        )

        assert np.isfinite(u)
        assert np.isfinite(v)
        assert speed >= 0.0

        print()
        print(
            "Real U/V current vector: PASS"
        )

        # ---------------------------------------------------------------------
        # PROVENANCE
        # ---------------------------------------------------------------------

        provenance_path = (
            PROVENANCE_DIR
            / (
                chunk_path.stem
                + ".json"
            )
        )

        print()
        print(
            "PROVENANCE"
        )

        print(
            "-" * 80
        )

        print(
            provenance_path
        )

        if not provenance_path.exists():

            raise FileNotFoundError(
                "Provenance JSON is missing."
            )

        provenance = json.loads(
            provenance_path.read_text(
                encoding="utf-8"
            )
        )

        provider = provenance.get(
            "provider"
        )

        service = provenance.get(
            "service"
        )

        dataset_file = provenance.get(
            "dataset_file"
        )

        source_rules = (
            provenance.get(
                "source_request_rules",
                {},
            )
        )

        subset_method = (
            source_rules.get(
                "subset_method"
            )
        )

        complete_download = (
            source_rules.get(
                "complete_netcdf_download"
            )
        )

        print(
            "Provider:",
            provider,
        )

        print(
            "Service:",
            service,
        )

        print(
            "Dataset:",
            dataset_file,
        )

        print(
            "Subset method:",
            subset_method,
        )

        print(
            "Complete NetCDF download:",
            complete_download,
        )

        assert provider == "INCOIS"

        assert service == (
            "THREDDS OPeNDAP"
        )

        assert dataset_file == (
            "RSMC_hycom_20260911.nc"
        )

        assert subset_method == (
            "OPeNDAP indexed constraint"
        )

        assert complete_download is False

        print()
        print(
            "INCOIS provenance: PASS"
        )

    # =========================================================================
    # FINAL
    # =========================================================================

    print()
    print("=" * 80)
    print(
        "HYCOM CHUNK VALIDATION COMPLETE"
    )
    print("=" * 80)

    print()
    print(
        "ALL HYCOM LOCAL-CHUNK CHECKS PASSED."
    )

    print(
        "Real INCOIS data is stored locally."
    )

    print(
        "No complete 9+ GiB NetCDF was downloaded."
    )

    print("=" * 80)


if __name__ == "__main__":
    main()

