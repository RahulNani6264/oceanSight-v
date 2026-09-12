from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent

CATALOG_DIR = PROJECT_ROOT / "processed" / "hycom_catalog"

COORDINATE_FILE = CATALOG_DIR / "hycom_coordinates.npz"

PLAN_DIR = PROJECT_ROOT / "processed" / "hycom_plans"

PLAN_DIR.mkdir(parents=True, exist_ok=True)

MAX_LAT_CELLS = 32
MAX_LON_CELLS = 32


@dataclass(frozen=True)
class ChunkPlan:
    time_index: int
    depth_start: int
    depth_count: int
    lat_start: int
    lat_count: int
    lon_start: int
    lon_count: int
    requested_time_utc: str
    lat_min: float
    lat_max: float
    lon_min: float
    lon_max: float


class HycomChunkPlanner:
    """Plan HYCOM chunks for a point or region."""

    def __init__(
        self,
        coordinate_file: Path | str = COORDINATE_FILE,
    ) -> None:
        self.coordinate_file = Path(coordinate_file)

        if not self.coordinate_file.exists():
            raise FileNotFoundError(
                f"HYCOM coordinate catalog not found: {self.coordinate_file}"
            )

        payload = np.load(self.coordinate_file)

        self.lat = np.asarray(payload["LAT"], dtype=float)
        self.lon = np.asarray(payload["LON"], dtype=float)
        self.depth = np.asarray(payload["DEPTH"], dtype=float)
        self.time = np.asarray(payload["TIME"], dtype=float)

        self.max_lat_chunk = MAX_LAT_CELLS
        self.max_lon_chunk = MAX_LON_CELLS

    def _validate_coordinates(
        self,
        latitude: float,
        longitude: float,
    ) -> None:
        """Validate requested latitude and longitude."""
        if not np.isfinite(latitude):
            raise ValueError(f"Invalid latitude: {latitude}")

        if not np.isfinite(longitude):
            raise ValueError(f"Invalid longitude: {longitude}")

        if latitude < float(self.lat.min()) or latitude > float(self.lat.max()):
            raise ValueError(
                f"Latitude {latitude} is outside HYCOM range "
                f"{float(self.lat.min())} to {float(self.lat.max())}"
            )

        if longitude < float(self.lon.min()) or longitude > float(self.lon.max()):
            raise ValueError(
                f"Longitude {longitude} is outside HYCOM range "
                f"{float(self.lon.min())} to {float(self.lon.max())}"
            )

    @staticmethod
    def time_to_numeric(time_utc: str) -> float:
        """Convert ISO UTC time to HYCOM numeric time."""
        if time_utc.endswith("Z"):
            time_utc = time_utc[:-1] + "+00:00"

        dt = datetime.fromisoformat(time_utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)

        epoch = datetime(1900, 12, 31, tzinfo=timezone.utc)
        delta = dt - epoch
        return delta.total_seconds() / 86400.0

    @staticmethod
    def nearest_index(values: np.ndarray, target: float) -> int:
        """Return index of nearest coordinate value."""
        values = np.asarray(values)
        return int(np.abs(values - target).argmin())

    def point_to_region(
        self,
        latitude: float,
        longitude: float,
        radius_degrees: float = 0.25,
    ) -> tuple[float, float, float, float]:
        """Convert a point and radius into a geographic region."""
        if radius_degrees <= 0:
            raise ValueError(
                f"radius_degrees must be greater than zero, got {radius_degrees}"
            )

        self._validate_coordinates(latitude, longitude)

        lat_min = latitude - radius_degrees
        lat_max = latitude + radius_degrees
        lon_min = longitude - radius_degrees
        lon_max = longitude + radius_degrees

        lat_min = max(lat_min, float(self.lat.min()))
        lat_max = min(lat_max, float(self.lat.max()))
        lon_min = max(lon_min, float(self.lon.min()))
        lon_max = min(lon_max, float(self.lon.max()))

        return lat_min, lat_max, lon_min, lon_max

    def plan_point(
        self,
        latitude: float,
        longitude: float,
        time_utc: str,
        radius_degrees: float = 0.25,
    ) -> list[ChunkPlan]:
        """Plan HYCOM chunks covering a requested point."""
        lat_min, lat_max, lon_min, lon_max = self.point_to_region(
            latitude=latitude,
            longitude=longitude,
            radius_degrees=radius_degrees,
        )

        return self.plan_region(
            lat_min=lat_min,
            lat_max=lat_max,
            lon_min=lon_min,
            lon_max=lon_max,
            time_utc=time_utc,
        )

    def plan_region(
        self,
        lat_min: float,
        lat_max: float,
        lon_min: float,
        lon_max: float,
        time_utc: str,
    ) -> list[ChunkPlan]:
        """Plan chunk downloads covering a geographic region."""
        if lat_min > lat_max:
            lat_min, lat_max = lat_max, lat_min

        if lon_min > lon_max:
            lon_min, lon_max = lon_max, lon_min

        self._validate_coordinates(lat_min, lon_min)
        self._validate_coordinates(lat_max, lon_max)

        time_numeric = self.time_to_numeric(time_utc)
        time_index = self.nearest_index(self.time, time_numeric)

        lat_start = int(np.searchsorted(self.lat, lat_min, side="left"))
        lat_end = int(np.searchsorted(self.lat, lat_max, side="right"))

        lon_start = int(np.searchsorted(self.lon, lon_min, side="left"))
        lon_end = int(np.searchsorted(self.lon, lon_max, side="right"))

        lat_start = max(0, lat_start)
        lon_start = max(0, lon_start)
        lat_end = min(len(self.lat), lat_end)
        lon_end = min(len(self.lon), lon_end)

        if lat_start >= lat_end or lon_start >= lon_end:
            return []

        plans: list[ChunkPlan] = []

        for y0 in range(lat_start, lat_end, self.max_lat_chunk):
            y_count = min(self.max_lat_chunk, lat_end - y0)
            y_chunk_end = min(y0 + y_count, len(self.lat))
            lat_min_chunk = float(self.lat[y0])
            lat_max_chunk = float(self.lat[y_chunk_end - 1])

            for x0 in range(lon_start, lon_end, self.max_lon_chunk):
                x_count = min(self.max_lon_chunk, lon_end - x0)
                x_chunk_end = min(x0 + x_count, len(self.lon))
                lon_min_chunk = float(self.lon[x0])
                lon_max_chunk = float(self.lon[x_chunk_end - 1])

                plans.append(
                    ChunkPlan(
                        time_index=time_index,
                        depth_start=0,
                        depth_count=len(self.depth),
                        lat_start=y0,
                        lat_count=y_count,
                        lon_start=x0,
                        lon_count=x_count,
                        requested_time_utc=time_utc,
                        lat_min=lat_min_chunk,
                        lat_max=lat_max_chunk,
                        lon_min=lon_min_chunk,
                        lon_max=lon_max_chunk,
                    )
                )

        return plans

    def save_plan(
        self,
        plans: list[ChunkPlan],
        output_path: Path | str | None = None,
        filename: str | Path | None = None,
    ) -> Path:
        """Save chunk plan as JSON."""
        if output_path is None:
            output_path = filename if filename is not None else Path("hycom_chunk_plan.json")

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        payload = {
            "count": len(plans),
            "plans": [
                asdict(plan)
                for plan in plans
            ],
        }

        output_path.write_text(
            json.dumps(
                payload,
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )

        return output_path



# =============================================================================

# COMMAND LINE

# =============================================================================

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Plan real INCOIS HYCOM chunks "
            "from a point or region."
        )
    )

    parser.add_argument(
        "--latitude",
        type=float,
    )

    parser.add_argument(
        "--longitude",
        type=float,
    )

    parser.add_argument(
        "--radius-degrees",
        type=float,
        default=0.25,
    )

    parser.add_argument(
        "--lat-min",
        type=float,
    )

    parser.add_argument(
        "--lat-max",
        type=float,
    )

    parser.add_argument(
        "--lon-min",
        type=float,
    )

    parser.add_argument(
        "--lon-max",
        type=float,
    )

    parser.add_argument(
        "--time-utc",
        default="2026-09-10T06:00:00Z",
    )

    parser.add_argument(
        "--output",
        default="hycom_chunk_plan.json",
    )

    return parser


def main() -> None:
    parser = build_parser()

    args = parser.parse_args()

    print("=" * 80)
    print("OCEANSIGHT-V")
    print("HYCOM CHUNK PLANNER")
    print("=" * 80)

    planner = HycomChunkPlanner()

    region_values = (
        args.lat_min,
        args.lat_max,
        args.lon_min,
        args.lon_max,
    )

    any_region = any(
        value is not None
        for value in region_values
    )

    all_region = all(
        value is not None
        for value in region_values
    )

    if any_region:

        if not all_region:
            raise ValueError(
                "Region mode requires "
                "--lat-min --lat-max "
                "--lon-min --lon-max"
            )

        plans = planner.plan_region(
            lat_min=args.lat_min,
            lat_max=args.lat_max,
            lon_min=args.lon_min,
            lon_max=args.lon_max,
            time_utc=args.time_utc,
        )

        mode = "REGION"

    elif (
        args.latitude is not None
        or args.longitude is not None
    ):

        if (
            args.latitude is None
            or args.longitude is None
        ):
            raise ValueError(
                "Point mode requires "
                "--latitude and --longitude."
            )

        plans = planner.plan_point(
            latitude=args.latitude,
            longitude=args.longitude,
            time_utc=args.time_utc,
            radius_degrees=args.radius_degrees,
        )

        mode = "POINT"

    else:

        plans = planner.plan_region(
            lat_min=-8.4,
            lat_max=-7.9,
            lon_min=68.0,
            lon_max=68.5,
            time_utc="2026-09-10T06:00:00Z",
        )

        mode = "DEMO"

    plan_path = planner.save_plan(
        plans,
        filename=args.output,
    )

    print()
    print("REQUEST MODE:", mode)

    print()
    print(
        "CATALOG:"
    )

    print(
        "LAT:",
        len(planner.lat),
    )

    print(
        "LON:",
        len(planner.lon),
    )

    print(
        "DEPTH:",
        len(planner.depth),
    )

    print(
        "TIME:",
        len(planner.time),
    )

    print()
    print(
        "PLANNED CHUNKS:",
        len(plans),
    )

    for number, plan in enumerate(
        plans,
        start=1,
    ):

        print()
        print(
            f"[{number}]"
        )

        print(
            "time index:",
            plan.time_index,
        )

        print(
            "depth index:",
            plan.depth_start,
            "count:",
            plan.depth_count,
        )

        print(
            "latitude index:",
            plan.lat_start,
            "count:",
            plan.lat_count,
        )

        print(
            "longitude index:",
            plan.lon_start,
            "count:",
            plan.lon_count,
        )

        print(
            "latitude coverage:",
            plan.lat_min,
            "to",
            plan.lat_max,
        )

        print(
            "longitude coverage:",
            plan.lon_min,
            "to",
            plan.lon_max,
        )

    print()
    print(
        "Plan saved:"
    )

    print(
        plan_path
    )

    print()
    print("=" * 80)
    print(
        "HYCOM CHUNK PLANNER COMPLETE"
    )
    print("=" * 80)


if __name__ == "__main__":
    main()
