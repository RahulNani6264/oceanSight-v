
from __future__ import annotations

import sqlite3

from .argo_store import ARGO_DB


def main() -> None:
    print("=" * 80)
    print("OCEANSIGHT-V")
    print("CLEAN ARGO DUPLICATES")
    print("=" * 80)

    print()
    print("Database:")
    print(ARGO_DB)

    with sqlite3.connect(ARGO_DB) as connection:

        # ---------------------------------------------------------------------
        # Count before cleanup
        # ---------------------------------------------------------------------

        before_row = connection.execute(
            """
            SELECT COUNT(*)
            FROM argo_observations
            """
        ).fetchone()

        before = int(before_row[0])

        print()
        print("Rows before cleanup:")
        print(before)

        # ---------------------------------------------------------------------
        # Remove exact scientific duplicates.
        #
        # Keep the first physical row and delete later copies having the same:
        #
        #   source dataset
        #   platform
        #   cycle
        #   profile time
        #   latitude
        #   longitude
        #   pressure
        #
        # These fields identify the actual sampled measurement.
        # ---------------------------------------------------------------------

        connection.execute(
            """
            DELETE FROM argo_observations
            WHERE id NOT IN (
                SELECT MIN(id)
                FROM argo_observations
                GROUP BY
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

        # ---------------------------------------------------------------------
        # Create a unique index.
        #
        # From this point onward, the same physical observation cannot be
        # inserted again.
        # ---------------------------------------------------------------------

        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS
            uq_argo_observation
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

        connection.commit()

        # ---------------------------------------------------------------------
        # Count after cleanup
        # ---------------------------------------------------------------------

        after_row = connection.execute(
            """
            SELECT COUNT(*)
            FROM argo_observations
            """
        ).fetchone()

        after = int(after_row[0])

    print()
    print("Rows after cleanup:")
    print(after)

    print()
    print("Duplicates removed:")
    print(before - after)

    print()
    print("Unique-index protection:")
    print("ENABLED")

    print()
    print("=" * 80)
    print("ARGO DUPLICATE CLEANUP COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    main()

