from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.config import (
    METADATA_DIR,
    RAW_DIR,
)


def save_metadata(
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


def save_raw_text(
    filename: str,
    text: str,
) -> Path:

    path = (
        RAW_DIR
        / filename
    )

    path.write_text(
        text,
        encoding="utf-8",
    )

    return path