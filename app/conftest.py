from __future__ import annotations

from collections.abc import Generator

import httpx
import pytest


@pytest.fixture
def client() -> Generator[httpx.Client, None, None]:
    """
    HTTP client used by final backend integration tests.

    The FastAPI server must already be running on the local development
    address used by the project.
    """
    with httpx.Client(
        base_url="http://127.0.0.1:8001",
        timeout=120.0,
        follow_redirects=True,
    ) as test_client:
        yield test_client


@pytest.fixture(params=("TEMP", "SALN", "UVEL", "VVEL"))
def variable(request: pytest.FixtureRequest) -> str:
    """
    Exercise every currently supported gridded HYCOM field used by the
    final integration slice test.

    SSH is intentionally not included here because the existing final test
    requests depth=100 m, while sea-surface height is a surface quantity.
    """
    return str(request.param)


@pytest.fixture
def depth_m() -> float:
    """Use a real HYCOM depth supported by the current test dataset."""
    return 100.0
