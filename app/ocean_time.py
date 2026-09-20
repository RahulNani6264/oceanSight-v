from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CATALOG = PROJECT_ROOT / "processed" / "hycom_catalog" / "hycom_times.json"


@dataclass(frozen=True)
class TimeRecord:
    time_utc: str
    dataset: str | None
    dataset_url: str | None
    time_index: int | None
    datasets: tuple[str, ...]
    dataset_urls: tuple[str, ...]


class OceanTimeEngine:
    """
    Build frontend-ready time windows from real source timestamps.

    Rules:
      - timestamps come only from the INCOIS HYCOM catalog;
      - no synthetic timestamps are added;
      - no temporal interpolation is performed;
      - arbitrary calendar ranges are filtered against actual source times;
      - past/future labels are relative to the selected reference time.
    """

    def __init__(self, catalog_file: str | Path | None = None) -> None:
        self.catalog_file = Path(catalog_file or DEFAULT_CATALOG)
        if not self.catalog_file.exists():
            raise FileNotFoundError(
                f"HYCOM time catalog was not found: {self.catalog_file}"
            )
        self._records: list[TimeRecord] | None = None

    @staticmethod
    def _parse(value: str) -> datetime:
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            raise ValueError("Time must include an explicit timezone.")
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _iso(value: datetime) -> str:
        return (
            value.astimezone(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )

    def _load(self) -> list[TimeRecord]:
        if self._records is not None:
            return self._records
        try:
            with self.catalog_file.open("r", encoding="utf-8") as handle:
                catalog = json.load(handle)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Invalid HYCOM time catalog JSON: {exc}") from exc
        except OSError as exc:
            raise RuntimeError(f"Unable to read HYCOM time catalog: {exc}") from exc

        raw_times = catalog.get("times") if isinstance(catalog, dict) else None
        if not isinstance(raw_times, list):
            raise RuntimeError("HYCOM time catalog does not contain a valid 'times' list.")

        records: list[TimeRecord] = []
        for raw in raw_times:
            if not isinstance(raw, dict) or not raw.get("time_utc"):
                continue
            time_utc = self._iso(self._parse(str(raw["time_utc"])))
            datasets = raw.get("datasets")
            dataset_urls = raw.get("dataset_urls")
            records.append(
                TimeRecord(
                    time_utc=time_utc,
                    dataset=str(raw["dataset"]) if raw.get("dataset") else None,
                    dataset_url=str(raw["dataset_url"]) if raw.get("dataset_url") else None,
                    time_index=int(raw["time_index"]) if raw.get("time_index") is not None else None,
                    datasets=tuple(str(x) for x in datasets) if isinstance(datasets, list) else tuple(),
                    dataset_urls=tuple(str(x) for x in dataset_urls) if isinstance(dataset_urls, list) else tuple(),
                )
            )

        records.sort(key=lambda item: self._parse(item.time_utc))
        self._records = records
        return records

    @staticmethod
    def _record_dict(record: TimeRecord, reference: datetime | None = None) -> dict[str, Any]:
        result: dict[str, Any] = {
            "time_utc": record.time_utc,
            "dataset": record.dataset,
            "dataset_url": record.dataset_url,
            "time_index": record.time_index,
            "datasets": list(record.datasets),
            "dataset_urls": list(record.dataset_urls),
        }
        if reference is not None:
            current = OceanTimeEngine._parse(record.time_utc)
            if current < reference:
                phase = "past"
            elif current > reference:
                phase = "future"
            else:
                phase = "present"
            result["relative_to_reference"] = phase
            result["offset_hours"] = round((current - reference).total_seconds() / 3600.0, 6)
        return result

    def catalog_summary(self) -> dict[str, Any]:
        records = self._load()
        return {
            "available": bool(records),
            "source": {
                "provider": "INCOIS",
                "service": "THREDDS OPeNDAP",
                "model": "RSMC HYCOM",
                "catalog_file": str(self.catalog_file),
            },
            "time_count": len(records),
            "earliest_time_utc": records[0].time_utc if records else None,
            "latest_time_utc": records[-1].time_utc if records else None,
            "times": [self._record_dict(record) for record in records],
            "scientific_rules": {
                "source_times_only": True,
                "synthetic_times": False,
                "interpolation": False,
            },
        }

    def window(
        self,
        reference_time_utc: str | None = None,
        past_hours: float = 24.0,
        future_hours: float = 24.0,
    ) -> dict[str, Any]:
        if past_hours < 0 or future_hours < 0:
            raise ValueError("past_hours and future_hours cannot be negative.")

        records = self._load()
        if not records:
            return {
                "available": False,
                "reference_time_utc": reference_time_utc,
                "times": [],
                "past_times": [],
                "present_times": [],
                "future_times": [],
                "missing_source_times": True,
            }

        if reference_time_utc is None:
            reference = datetime.now(timezone.utc).replace(microsecond=0)
        else:
            reference = self._parse(reference_time_utc).replace(microsecond=0)

        start = reference - timedelta(hours=float(past_hours))
        end = reference + timedelta(hours=float(future_hours))

        selected = [
            record for record in records
            if start <= self._parse(record.time_utc) <= end
        ]

        past = [record for record in selected if self._parse(record.time_utc) < reference]
        present = [record for record in selected if self._parse(record.time_utc) == reference]
        future = [record for record in selected if self._parse(record.time_utc) > reference]

        return {
            "available": True,
            "reference_time_utc": self._iso(reference),
            "window": {
                "start_time_utc": self._iso(start),
                "end_time_utc": self._iso(end),
                "past_hours": float(past_hours),
                "future_hours": float(future_hours),
            },
            "times": [self._record_dict(record, reference) for record in selected],
            "past_times": [self._record_dict(record, reference) for record in past],
            "present_times": [self._record_dict(record, reference) for record in present],
            "future_times": [self._record_dict(record, reference) for record in future],
            "counts": {
                "total": len(selected),
                "past": len(past),
                "present": len(present),
                "future": len(future),
            },
            "coverage": {
                "requested_start_time_utc": self._iso(start),
                "requested_end_time_utc": self._iso(end),
                "source_earliest_time_utc": records[0].time_utc,
                "source_latest_time_utc": records[-1].time_utc,
                "fully_covered": bool(selected)
                and self._parse(selected[0].time_utc) <= start
                and self._parse(selected[-1].time_utc) >= end,
            },
            "scientific_rules": {
                "source_times_only": True,
                "synthetic_times": False,
                "interpolation": False,
                "past_semantics": "source_timestamp_before_reference",
                "future_semantics": "source_timestamp_after_reference",
            },
        }

    def range(
        self,
        start_time_utc: str,
        end_time_utc: str,
    ) -> dict[str, Any]:
        start = self._parse(start_time_utc)
        end = self._parse(end_time_utc)
        if end < start:
            raise ValueError("end_time_utc must be greater than or equal to start_time_utc.")
        records = self._load()
        selected = [
            record for record in records
            if start <= self._parse(record.time_utc) <= end
        ]
        return {
            "available": bool(selected),
            "request": {
                "start_time_utc": self._iso(start),
                "end_time_utc": self._iso(end),
            },
            "times": [self._record_dict(record) for record in selected],
            "count": len(selected),
            "source_coverage": {
                "earliest_time_utc": records[0].time_utc if records else None,
                "latest_time_utc": records[-1].time_utc if records else None,
            },
            "scientific_rules": {
                "source_times_only": True,
                "synthetic_times": False,
                "interpolation": False,
            },
        }


__all__ = ["OceanTimeEngine", "TimeRecord"]
