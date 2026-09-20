from __future__ import annotations

import io
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

import httpx
import numpy as np
import xarray as xr


NOAA_GFS_BASE = (
    "https://upwell.pfeg.noaa.gov/erddap/griddap/NCEP_Global_Best"
)

NOAA_CHL_BASE = (
    "https://coastwatch.noaa.gov/erddap/griddap/"
    "noaacwNPPN20VIIRSDINEOFDaily"
)


@dataclass(frozen=True)
class ExternalVariableConfig:
    variable_id: str
    name: str
    dataset_id: str
    field: str
    unit: str
    base_url: str
    source: str
    category: str
    minimum: float | None = None
    maximum: float | None = None
    color_scale: tuple[str, ...] = ()
    vertical: bool = False


CONFIGS: dict[str, ExternalVariableConfig] = {
    "wind": ExternalVariableConfig(
        variable_id="wind",
        name="Wind",
        dataset_id="NCEP_Global_Best",
        field="ugrd10m,vgrd10m",
        unit="m/s",
        base_url=NOAA_GFS_BASE,
        source="NOAA NCEP",
        category="atmosphere",
        minimum=0.0,
        maximum=60.0,
        color_scale=(
            "#313695",
            "#74ADD1",
            "#FFFFBF",
            "#F46D43",
            "#A50026",
        ),
        vertical=False,
    ),
    "air_pressure": ExternalVariableConfig(
        variable_id="air_pressure",
        name="Air pressure",
        dataset_id="NCEP_Global_Best",
        field="prmslmsl",
        unit="hPa",
        base_url=NOAA_GFS_BASE,
        source="NOAA NCEP",
        category="atmosphere",
        minimum=950.0,
        maximum=1050.0,
        color_scale=(
            "#313695",
            "#74ADD1",
            "#FFFFBF",
            "#F46D43",
            "#A50026",
        ),
        vertical=False,
    ),
    "chlorophyll": ExternalVariableConfig(
        variable_id="chlorophyll",
        name="Chlorophyll",
        dataset_id="noaacwNPPN20VIIRSDINEOFDaily",
        field="chlor_a",
        unit="mg/m³",
        base_url=NOAA_CHL_BASE,
        source="NOAA VIIRS",
        category="biology",
        minimum=0.01,
        maximum=20.0,
        color_scale=(
            "#440154",
            "#482878",
            "#3E4989",
            "#31688E",
            "#26828E",
            "#35B779",
            "#6ECE58",
            "#B5DE2B",
            "#FDE725",
        ),
        vertical=False,
    ),
}


class OceanExternalDataEngine:
    """
    Downloads real external gridded data from NOAA ERDDAP.

    Important ERDDAP rules:

    - Time and geographic coordinate values must be wrapped in parentheses.
    - Array indexes must not be used for latitude/longitude values.
    - A global longitude request must not collapse into a single longitude.
    - NOAA longitude axes may use either -180..180 or 0..360.
    """

    def __init__(
        self,
        *,
        timeout_seconds: float = 90.0,
        max_points: int = 120_000,
        geometry_engine: Any | None = None,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.max_points = max_points
        self.geometry_engine = geometry_engine

    @staticmethod
    def _format_number(number: float) -> str:
        return f"{number:.8f}".rstrip("0").rstrip(".")

    @staticmethod
    def _format_constraint(value: float) -> str:
        """
        Format a coordinate value for an ERDDAP coordinate constraint.

        Example:
            -80.0 -> (-80)
            180.0 -> (180)
        """
        return f"({OceanExternalDataEngine._format_number(float(value))})"

    @staticmethod
    def _time_token(time_utc: str) -> str:
        """
        Normalize an incoming ISO timestamp to ERDDAP format.
        """
        value = str(time_utc).strip()

        if value.endswith("Z"):
            value = value[:-1] + "+00:00"

        parsed = datetime.fromisoformat(value)

        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)

        parsed = parsed.astimezone(timezone.utc)

        return parsed.strftime("%Y-%m-%dT%H:%M:%SZ")

    @staticmethod
    def _as_360(longitude: float) -> float:
        """
        Convert a longitude to the 0..360 convention.

        This method is used only when a dataset is known to use
        0..360 longitudes.
        """
        value = float(longitude)

        while value < 0.0:
            value += 360.0

        while value > 360.0:
            value -= 360.0

        if abs(value - 360.0) < 1e-9:
            value = 0.0

        return value

    @staticmethod
    def _is_global_longitude_range(
        longitude_min: float,
        longitude_max: float,
    ) -> bool:
        width = float(longitude_max) - float(longitude_min)
        return width >= 359.0

    def _longitude_constraint(
        self,
        *,
        longitude_min: float,
        longitude_max: float,
        stride: int,
    ) -> str:
        """
        Build a safe longitude constraint.

        NCEP_Global_Best uses a longitude axis that is effectively
        0..360. A full global request must be expressed as 0..359
        rather than (180):stride:(180).

        For regional requests, preserve the requested range after
        converting it to 0..360.
        """
        if self._is_global_longitude_range(
            longitude_min,
            longitude_max,
        ):
            start = 0.0
            stop = 359.0
        else:
            start = self._as_360(longitude_min)
            stop = self._as_360(longitude_max)

            if stop < start:
                stop += 360.0

            if stop > 360.0:
                stop = 360.0

        return (
            f"[{self._format_constraint(start)}:"
            f"{int(stride)}:"
            f"{self._format_constraint(stop)}]"
        )

    def _latitude_constraint(
        self,
        *,
        latitude_min: float,
        latitude_max: float,
        stride: int,
    ) -> str:
        start = max(-90.0, min(90.0, float(latitude_min)))
        stop = max(-90.0, min(90.0, float(latitude_max)))

        if stop < start:
            start, stop = stop, start

        return (
            f"[{self._format_constraint(start)}:"
            f"{int(stride)}:"
            f"{self._format_constraint(stop)}]"
        )

    @staticmethod
    def _index_constraint(
        start: int,
        stop: int,
        stride: int,
    ) -> str:
        return f"[{int(start)}:{int(stride)}:{int(stop)}]"

    @staticmethod
    def _safe_stride(
        *,
        latitude_min: float,
        latitude_max: float,
        longitude_min: float,
        longitude_max: float,
        max_points: int,
    ) -> int:
        latitude_span = max(
            1.0,
            abs(float(latitude_max) - float(latitude_min)),
        )

        longitude_span = max(
            1.0,
            abs(float(longitude_max) - float(longitude_min)),
        )

        estimated_points = latitude_span * longitude_span

        if estimated_points <= max_points:
            return 1

        stride = int(
            math.ceil(
                math.sqrt(estimated_points / max_points)
            )
        )

        return max(1, stride)

    @staticmethod
    def _validate_bbox(
        latitude_min: float,
        latitude_max: float,
        longitude_min: float,
        longitude_max: float,
    ) -> None:
        values = (
            latitude_min,
            latitude_max,
            longitude_min,
            longitude_max,
        )

        if not all(math.isfinite(float(value)) for value in values):
            raise ValueError("Bounding-box coordinates must be finite")

        if latitude_min < -90 or latitude_min > 90:
            raise ValueError("latitude_min must be between -90 and 90")

        if latitude_max < -90 or latitude_max > 90:
            raise ValueError("latitude_max must be between -90 and 90")

        if latitude_min >= latitude_max:
            raise ValueError(
                "latitude_min must be smaller than latitude_max"
            )

        if longitude_min < -180 or longitude_min > 180:
            raise ValueError(
                "longitude_min must be between -180 and 180"
            )

        if longitude_max < -180 or longitude_max > 180:
            raise ValueError(
                "longitude_max must be between -180 and 180"
            )

        if longitude_min >= longitude_max:
            raise ValueError(
                "longitude_min must be smaller than longitude_max"
            )

    def _erddap_url(
        self,
        *,
        config: ExternalVariableConfig,
        time_utc: str,
        latitude_min: float,
        latitude_max: float,
        longitude_min: float,
        longitude_max: float,
        stride: int,
    ) -> str:
        """
        Build a valid NOAA ERDDAP griddap URL.

        Coordinate-value syntax:

            [(2026-09-10T00:00:00Z)]
            [(-80):5:(80)]
            [(0):5:(359)]

        The previous implementation incorrectly used:

            [(180):5:(180)]

        for a global longitude range. That returned only one longitude
        column and caused all decoded values to become null.
        """
        time_token = self._time_token(time_utc)

        latitude_range = self._latitude_constraint(
            latitude_min=latitude_min,
            latitude_max=latitude_max,
            stride=stride,
        )

        longitude_range = self._longitude_constraint(
            longitude_min=longitude_min,
            longitude_max=longitude_max,
            stride=stride,
        )

        # ISO-8601 times are textual ERDDAP coordinate values, whereas
        # latitude and longitude are numeric values.
        time_range = f"[({time_token})]"

        if config.variable_id == "wind":
            query = (
                "ugrd10m"
                f"{time_range}"
                f"{latitude_range}"
                f"{longitude_range},"
                "vgrd10m"
                f"{time_range}"
                f"{latitude_range}"
                f"{longitude_range}"
            )

        elif config.variable_id == "chlorophyll":
            query = (
                "chlor_a"
                f"{time_range}"
                "[(0)]"
                f"{latitude_range}"
                f"{longitude_range}"
            )

        else:
            query = (
                f"{config.field}"
                f"[{self._format_constraint(time_token)}]"
                f"{latitude_range}"
                f"{longitude_range}"
            )

        return f"{config.base_url}.nc?{query}"

    @staticmethod
    def _decode_netcdf(content: bytes) -> xr.Dataset:
        try:
            return xr.open_dataset(
                io.BytesIO(content),
                engine="scipy",
            )
        except Exception:
            return xr.open_dataset(
                io.BytesIO(content),
            )

    @staticmethod
    def _find_dimension(
        dataset: xr.Dataset,
        candidates: Iterable[str],
    ) -> str | None:
        names = set(dataset.dims) | set(dataset.coords)

        lowered = {
            str(name).lower(): str(name)
            for name in names
        }

        for candidate in candidates:
            if candidate.lower() in lowered:
                return lowered[candidate.lower()]

        for name in names:
            lowered_name = str(name).lower()

            for candidate in candidates:
                if candidate.lower() in lowered_name:
                    return str(name)

        return None

    @staticmethod
    def _to_float_array(value: Any) -> np.ndarray:
        return np.asarray(value, dtype=np.float64)

    @staticmethod
    def _clean_values(values: np.ndarray) -> np.ndarray:
        array = np.asarray(values, dtype=np.float64)

        array[~np.isfinite(array)] = np.nan

        return array

    @staticmethod
    def _apply_scale(
        values: np.ndarray,
        config: ExternalVariableConfig,
    ) -> np.ndarray:
        """
        Convert pressure from Pa to hPa.

        NOAA sea-level pressure is commonly returned in Pa.
        """
        array = np.asarray(values, dtype=np.float64)

        if config.variable_id == "air_pressure":
            finite = array[np.isfinite(array)]

            if finite.size and float(np.nanmedian(finite)) > 2_000:
                array = array / 100.0

        return array

    @staticmethod
    def _flatten_grid(
        values: np.ndarray,
    ) -> list[list[float | None]]:
        array = np.asarray(values, dtype=np.float64)

        if array.ndim == 0:
            array = array.reshape(1, 1)
        elif array.ndim == 1:
            array = array.reshape(1, -1)
        elif array.ndim > 2:
            array = np.squeeze(array)

            while array.ndim > 2:
                array = array[0]

        output: list[list[float | None]] = []

        for row in array:
            converted_row: list[float | None] = []

            for value in row:
                if not np.isfinite(value):
                    converted_row.append(None)
                else:
                    converted_row.append(float(value))

            output.append(converted_row)

        return output

    @staticmethod
    def _coordinate_values(
        dataset: xr.Dataset,
        candidates: Iterable[str],
    ) -> np.ndarray | None:
        dimension = OceanExternalDataEngine._find_dimension(
            dataset,
            candidates,
        )

        if dimension is None:
            return None

        if dimension in dataset.coords:
            return np.asarray(
                dataset.coords[dimension].values,
                dtype=np.float64,
            )

        if dimension in dataset.variables:
            return np.asarray(
                dataset[dimension].values,
                dtype=np.float64,
            )

        return None

    @staticmethod
    def _select_data_variable(
        dataset: xr.Dataset,
        preferred: str,
    ) -> xr.DataArray:
        if preferred in dataset.data_vars:
            return dataset[preferred]

        if preferred in dataset.variables:
            return dataset[preferred]

        for name, value in dataset.data_vars.items():
            if name.lower() == preferred.lower():
                return value

        candidates = [
            value
            for value in dataset.data_vars.values()
            if np.issubdtype(value.dtype, np.number)
        ]

        if not candidates:
            raise ValueError(
                f"No numeric data variable found for {preferred}"
            )

        return candidates[0]

    def _decode_field(
        self,
        *,
        dataset: xr.Dataset,
        variable_name: str,
        config: ExternalVariableConfig,
    ) -> dict[str, Any]:
        data = self._select_data_variable(
            dataset,
            variable_name,
        )

        values = self._clean_values(data.values)
        values = self._apply_scale(values, config)

        latitude_values = self._coordinate_values(
            dataset,
            (
                "latitude",
                "lat",
                "y",
            ),
        )

        longitude_values = self._coordinate_values(
            dataset,
            (
                "longitude",
                "lon",
                "x",
            ),
        )

        if latitude_values is None:
            latitude_values = np.arange(
                values.shape[-2] if values.ndim >= 2 else 1,
                dtype=np.float64,
            )

        if longitude_values is None:
            longitude_values = np.arange(
                values.shape[-1] if values.ndim >= 1 else 1,
                dtype=np.float64,
            )

        if values.ndim >= 2:
            values = np.squeeze(values)

        if values.ndim == 1:
            values = values.reshape(1, -1)

        if values.ndim > 2:
            values = values.reshape(
                values.shape[-2],
                values.shape[-1],
            )

        if latitude_values.size == values.shape[-1]:
            values = np.transpose(values)

        if latitude_values.size > 1:
            if latitude_values[0] < latitude_values[-1]:
                latitude_values = latitude_values[::-1]
                values = np.flip(values, axis=0)

        return {
            "latitudes": [
                float(value)
                for value in latitude_values
            ],
            "longitudes": [
                float(value)
                for value in longitude_values
            ],
            "values": self._flatten_grid(values),
        }

    async def _download(
        self,
        *,
        url: str,
    ) -> bytes:
        headers = {
            "User-Agent": "OceanSight/1.0",
            "Accept": "application/x-netcdf,application/octet-stream,*/*",
        }

        async with httpx.AsyncClient(
            timeout=self.timeout_seconds,
            follow_redirects=True,
            headers=headers,
        ) as client:
            response = await client.get(url)

        if response.status_code != 200:
            detail = response.text[:1_000]

            raise RuntimeError(
                "NOAA ERDDAP returned HTTP "
                f"{response.status_code}: {detail}"
            )

        if not response.content:
            raise RuntimeError(
                "NOAA ERDDAP returned an empty response"
            )

        return response.content

    @staticmethod
    def _valid_values(
        values: list[list[float | None]],
    ) -> list[float]:
        return [
            float(value)
            for row in values
            for value in row
            if value is not None and math.isfinite(float(value))
        ]

    @staticmethod
    def _missing_mask(
        values: list[list[float | None]],
    ) -> list[list[bool]]:
        return [
            [
                value is None
                for value in row
            ]
            for row in values
        ]

    @staticmethod
    def _water_mask(
        values: list[list[float | None]],
    ) -> list[list[bool]]:
        """
        External atmospheric datasets do not provide an ocean mask.

        The ocean-region engine applies the real regional mask later.
        """
        return [
            [
                False
                for _ in row
            ]
            for row in values
        ]

    def _field_result(
        self,
        *,
        output_name: str,
        units: str,
        depth_m: float,
        decoded: dict[str, Any],
    ) -> dict[str, Any]:
        values = decoded["values"]
        valid = self._valid_values(values)

        return {
            "output_name": output_name,
            "units": units,
            "depth_m": depth_m,
            "latitudes": decoded["latitudes"],
            "longitudes": decoded["longitudes"],
            "values": values,
            "missing_mask": self._missing_mask(values),
            "water_mask": self._water_mask(values),
            "valid_value_count": len(valid),
            "min": min(valid) if valid else None,
            "max": max(valid) if valid else None,
        }

    async def build_data(
        self,
        *,
        variable_id: str,
        time_utc: str,
        latitude_min: float = -80.0,
        latitude_max: float = 80.0,
        longitude_min: float = -180.0,
        longitude_max: float = 180.0,
        stride: int | None = None,
    ) -> dict[str, Any]:
        if variable_id not in CONFIGS:
            raise ValueError(
                f"Unsupported external variable: {variable_id}"
            )

        config = CONFIGS[variable_id]

        self._validate_bbox(
            latitude_min,
            latitude_max,
            longitude_min,
            longitude_max,
        )

        selected_stride = (
            int(stride)
            if stride is not None
            else self._safe_stride(
                latitude_min=latitude_min,
                latitude_max=latitude_max,
                longitude_min=longitude_min,
                longitude_max=longitude_max,
                max_points=self.max_points,
            )
        )

        selected_stride = max(1, selected_stride)

        request_url = self._erddap_url(
            config=config,
            time_utc=time_utc,
            latitude_min=latitude_min,
            latitude_max=latitude_max,
            longitude_min=longitude_min,
            longitude_max=longitude_max,
            stride=selected_stride,
        )

        content = await self._download(
            url=request_url,
        )

        dataset = self._decode_netcdf(content)

        try:
            actual_time = None

            for name in dataset.coords:
                if "time" in str(name).lower():
                    values = dataset.coords[name].values

                    if np.size(values):
                        actual_time = str(np.asarray(values).reshape(-1)[0])
                        break

            if variable_id == "wind":
                wind_u = self._decode_field(
                    dataset=dataset,
                    variable_name="ugrd10m",
                    config=config,
                )

                wind_v = self._decode_field(
                    dataset=dataset,
                    variable_name="vgrd10m",
                    config=config,
                )

                u_values = wind_u["values"]
                v_values = wind_v["values"]

                speed_values: list[list[float | None]] = []
                direction_values: list[list[float | None]] = []

                for u_row, v_row in zip(u_values, v_values):
                    speed_row: list[float | None] = []
                    direction_row: list[float | None] = []

                    for u_value, v_value in zip(u_row, v_row):
                        if u_value is None or v_value is None:
                            speed_row.append(None)
                            direction_row.append(None)
                            continue

                        speed = math.sqrt(
                            float(u_value) ** 2
                            + float(v_value) ** 2
                        )

                        direction = (
                            math.degrees(
                                math.atan2(
                                    float(v_value),
                                    float(u_value),
                                )
                            )
                            + 360.0
                        ) % 360.0

                        speed_row.append(speed)
                        direction_row.append(direction)

                    speed_values.append(speed_row)
                    direction_values.append(direction_row)

                wind_speed = self._field_result(
                    output_name="wind_speed",
                    units="m/s",
                    depth_m=0.0,
                    decoded={
                        "latitudes": wind_u["latitudes"],
                        "longitudes": wind_u["longitudes"],
                        "values": speed_values,
                    },
                )

                wind_direction = self._field_result(
                    output_name="wind_direction",
                    units="degree",
                    depth_m=0.0,
                    decoded={
                        "latitudes": wind_u["latitudes"],
                        "longitudes": wind_u["longitudes"],
                        "values": direction_values,
                    },
                )

                fields = [
                    self._field_result(
                        output_name="wind_u",
                        units="m/s",
                        depth_m=0.0,
                        decoded=wind_u,
                    ),
                    self._field_result(
                        output_name="wind_v",
                        units="m/s",
                        depth_m=0.0,
                        decoded=wind_v,
                    ),
                    wind_speed,
                    wind_direction,
                ]

            else:
                decoded = self._decode_field(
                    dataset=dataset,
                    variable_name=config.field,
                    config=config,
                )

                fields = [
                    self._field_result(
                        output_name=variable_id,
                        units=config.unit,
                        depth_m=0.0,
                        decoded=decoded,
                    )
                ]

            return {
                "available": True,
                "variable_id": variable_id,
                "data_kind": "external_surface_grid",
                "source": {
                    "provider": config.source,
                    "dataset": (
                        config.dataset_id
                    ),
                    "field": config.field,
                    "service": "public NOAA ERDDAP",
                    "request_url": request_url,
                },
                "request": {
                    "latitude_min": latitude_min,
                    "latitude_max": latitude_max,
                    "longitude_min": longitude_min,
                    "longitude_max": longitude_max,
                    "time_utc": time_utc,
                    "stride": selected_stride,
                },
                "actual_time_utc": actual_time,
                "levels": fields,
                "scientific_rules": {
                    "synthetic_data": False,
                    "interpolation": False,
                    "source_grid_values": True,
                    "real_external_provider": True,
                },
            }

        finally:
            dataset.close()
