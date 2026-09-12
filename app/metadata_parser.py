from __future__ import annotations

from typing import Any


def extract_variables(
    metadata: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    Extract variable metadata from an ERDDAP
    info/index.json response.
    """

    variables: list[
        dict[str, Any]
    ] = []

    table = (
        metadata.get("table")
        if isinstance(
            metadata,
            dict,
        )
        else None
    )

    if not table:
        return variables

    rows = table.get("rows", [])

    for row in rows:

        if not isinstance(
            row,
            list,
        ):
            continue

        if len(row) < 2:
            continue

        row_type = str(
            row[0]
        ).strip()

        variable = str(
            row[1]
        ).strip()

        if row_type.lower() in {
            "variable",
            "attribute",
        }:
            variables.append(
                {
                    "type":
                        row_type,
                    "name":
                        variable,
                    "raw":
                        row,
                }
            )

    return variables