from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any

from app.config import METADATA_DIR
from app.incois_client import IncoisClient


class DatasetDiscovery:
    """
    Discovers datasets from the live INCOIS ERDDAP server.

    The goal is to inspect metadata before downloading
    any large scientific dataset.
    """

    def __init__(
        self,
        client: IncoisClient | None = None,
    ) -> None:
        self.client = (
            client
            if client is not None
            else IncoisClient()
        )

    async def catalog(
        self,
    ) -> Any:
        return await (
            self.client
            .get_erddap_catalog()
        )

    async def all_datasets(
        self,
    ) -> list[dict[str, str]]:
        text = await (
            self.client
            .get_all_datasets()
        )

        reader = csv.DictReader(
            io.StringIO(text)
        )

        result: list[
            dict[str, str]
        ] = []

        for row in reader:

            dataset_id = (
                row.get("datasetID")
                or ""
            ).strip()

            title = (
                row.get("title")
                or ""
            ).strip()

            accessible = (
                row.get("accessible")
                or ""
            ).strip()

            if not dataset_id:
                continue

            result.append(
                {
                    "dataset_id":
                        dataset_id,
                    "title":
                        title,
                    "accessible":
                        accessible,
                }
            )

        return result

    async def dataset_metadata(
        self,
        dataset_id: str,
    ) -> Any:
        return await (
            self.client
            .get_dataset_info(
                dataset_id
            )
        )

    @staticmethod
    def save_json(
        filename: str,
        payload: Any,
    ) -> Path:

        path = (
            METADATA_DIR
            / filename
        )

        path.write_text(
            json.dumps(
                payload,
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        return path

    @staticmethod
    def find_candidates(
        datasets: list[
            dict[str, str]
        ],
        keywords: list[str],
    ) -> list[
        dict[str, str]
    ]:

        normalized_keywords = [
            keyword.lower()
            for keyword in keywords
        ]

        matches: list[
            dict[str, str]
        ] = []

        for dataset in datasets:

            haystack = (
                dataset[
                    "dataset_id"
                ]
                + " "
                + dataset[
                    "title"
                ]
            ).lower()

            if any(
                keyword
                in haystack
                for keyword
                in normalized_keywords
            ):
                matches.append(
                    dataset
                )

        return matches