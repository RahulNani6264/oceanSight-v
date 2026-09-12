from __future__ import annotations

from typing import Any

import httpx
import truststore

from app.config import (
    INCOIS_ERDDAP_BASE_URL,
    INCOIS_TIMEOUT_SECONDS,
)


class IncoisClient:
    """
    Low-level INCOIS ERDDAP client.

    This class only downloads real responses.
    It never creates mock or synthetic ocean data.
    """

    def __init__(
        self,
        base_url: str = INCOIS_ERDDAP_BASE_URL,
        timeout: int = INCOIS_TIMEOUT_SECONDS,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

        # Use the operating system trust store.
        self.ssl_context = (
            truststore.SSLContext()
        )

    async def get_text(
        self,
        url: str,
    ) -> str:
        headers = {
            "User-Agent": (
                "OceanSight-v/0.1 "
                "INCOIS Scientific Data Client"
            ),
            "Accept": (
                "application/json,"
                "text/csv,"
                "text/plain,*/*;q=0.8"
            ),
        }

        async with httpx.AsyncClient(
            verify=self.ssl_context,
            timeout=self.timeout,
            follow_redirects=True,
            headers=headers,
        ) as client:

            response = await client.get(url)

        if response.status_code != 200:
            raise RuntimeError(
                "INCOIS request failed.\n"
                f"HTTP: {response.status_code}\n"
                f"URL: {url}\n"
                f"Response:\n"
                f"{response.text[:2000]}"
            )

        return response.text

    async def get_json(
        self,
        url: str,
    ) -> Any:
        text = await self.get_text(url)

        try:
            import json

            return json.loads(text)

        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "INCOIS returned invalid JSON.\n"
                f"URL: {url}\n"
                f"Response:\n"
                f"{text[:1000]}"
            ) from exc

    async def get_erddap_catalog(
        self,
    ) -> Any:
        url = (
            f"{self.base_url}"
            "/info/index.json"
        )

        return await self.get_json(url)

    async def get_all_datasets(
        self,
    ) -> str:
        """
        ERDDAP all-datasets table.

        This is useful for discovering datasets
        without guessing dataset IDs.
        """

        url = (
            f"{self.base_url}"
            "/tabledap/allDatasets.csv"
            "?datasetID,title,accessible"
        )

        return await self.get_text(url)

    async def get_dataset_info(
        self,
        dataset_id: str,
    ) -> Any:
        dataset_id = dataset_id.strip()

        if not dataset_id:
            raise ValueError(
                "dataset_id cannot be empty."
            )

        url = (
            f"{self.base_url}"
            "/info/"
            f"{dataset_id}"
            "/index.json"
        )

        return await self.get_json(url)

    async def get_dataset_page(
        self,
        dataset_id: str,
    ) -> str:
        dataset_id = dataset_id.strip()

        if not dataset_id:
            raise ValueError(
                "dataset_id cannot be empty."
            )

        url = (
            f"{self.base_url}"
            "/griddap/"
            f"{dataset_id}.html"
        )

        return await self.get_text(url)

    async def get_tabledap_page(
        self,
        dataset_id: str,
    ) -> str:
        dataset_id = dataset_id.strip()

        if not dataset_id:
            raise ValueError(
                "dataset_id cannot be empty."
            )

        url = (
            f"{self.base_url}"
            "/tabledap/"
            f"{dataset_id}.html"
        )

        return await self.get_text(url)