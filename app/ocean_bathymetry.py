from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import json
from .ocean_geometry import OceanGeometryEngine


PROJECT_ROOT = Path(__file__).resolve().parent.parent
INDEX_PATH = PROJECT_ROOT / "processed" / "gebco_chunk_index.json"


@dataclass(frozen=True)
class BathymetryGrid:
    available: bool
    ocean: str
    latitudes: list[float]
    longitudes: list[float]
    elevation_m: list[list[float | None]]
    missing_mask: list[list[bool]]
    water_mask: list[list[bool]]
    valid_value_count: int
    water_cell_count: int
    source: str
    dataset: str
    source_url: str | None
    chunk_ids: list[str]
    bounding_box: dict[str, float]
    elevation_min_m: float | None
    elevation_max_m: float | None
    bathymetry_resolution_degrees: float | None
    synthetic_data: bool = False
    interpolation: bool = False


class OceanBathymetryEngine:
    """
    Build a real GEBCO bathymetry surface for a selected ocean region.

    Source values are read from already-acquired GEBCO chunks. The engine does
    not interpolate, resample, or invent bathymetry values. The selected
    RECCAP2 ocean geometry is used only as a geographic water mask so land and
    other basins are not exposed as selected-ocean cells.
    """

    MAX_GRID_POINTS = 200_000

    def __init__(
        self,
        index_path: str | Path | None = None,
        geometry_engine: OceanGeometryEngine | None = None,
    ) -> None:
        self.index_path = Path(index_path or INDEX_PATH)
        self.geometry_engine = geometry_engine or OceanGeometryEngine()
        self._index: dict[str, Any] | None = None

    def _load_index(self) -> dict[str, Any]:
        if self._index is not None:
            return self._index
        if not self.index_path.exists():
            raise FileNotFoundError(
                f"GEBCO chunk index not found: {self.index_path}. "
                "Run: python -m app.gebco_chunk_index"
            )
        with self.index_path.open("r", encoding="utf-8") as handle:
            index = json.load(handle)
        if not isinstance(index, dict) or not index.get("chunks"):
            raise RuntimeError("GEBCO chunk index contains no usable chunks.")
        self._index = index
        return index

    @staticmethod
    def _normalize_bbox(
        latitude_min: float,
        latitude_max: float,
        longitude_min: float,
        longitude_max: float,
    ) -> tuple[float, float, float, float]:
        latitude_min=float(latitude_min); latitude_max=float(latitude_max)
        longitude_min=float(longitude_min); longitude_max=float(longitude_max)
        if not (-90.0 <= latitude_min <= 90.0 and -90.0 <= latitude_max <= 90.0):
            raise ValueError("Latitude bounds must be between -90 and 90 degrees.")
        if latitude_min > latitude_max:
            raise ValueError("latitude_min cannot be greater than latitude_max.")
        if not (-180.0 <= longitude_min <= 180.0 and -180.0 <= longitude_max <= 180.0):
            raise ValueError("Longitude bounds must be between -180 and 180 degrees.")
        if longitude_min > longitude_max:
            raise ValueError(
                "longitude_min cannot be greater than longitude_max. "
                "Split antimeridian requests at the API layer."
            )
        return latitude_min, latitude_max, longitude_min, longitude_max

    @staticmethod
    def _intersects(
        chunk: dict[str, Any],
        latitude_min: float,
        latitude_max: float,
        longitude_min: float,
        longitude_max: float,
    ) -> bool:
        return not (
            float(chunk["latitude_max"]) < latitude_min
            or float(chunk["latitude_min"]) > latitude_max
            or float(chunk["longitude_max"]) < longitude_min
            or float(chunk["longitude_min"]) > longitude_max
        )

    @staticmethod
    def _finite_grid(values: np.ndarray) -> list[list[float | None]]:
        return [
            [float(value) if np.isfinite(value) else None for value in row]
            for row in np.asarray(values)
        ]

    @staticmethod
    def _bool_grid(values: np.ndarray) -> list[list[bool]]:
        return [[bool(value) for value in row] for row in np.asarray(values, dtype=bool)]

    @staticmethod
    def _slice_chunk(
        data_path: Path,
        latitude_min: float,
        latitude_max: float,
        longitude_min: float,
        longitude_max: float,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        with np.load(data_path, allow_pickle=False) as data:
            latitudes=np.asarray(data["latitude"],dtype=np.float64)
            longitudes=np.asarray(data["longitude"],dtype=np.float64)
            elevation=np.asarray(data["elevation_m"],dtype=np.float64)
            missing=np.asarray(data["missing_mask"],dtype=bool)

        lat_selector=(latitudes >= latitude_min) & (latitudes <= latitude_max)
        lon_selector=(longitudes >= longitude_min) & (longitudes <= longitude_max)
        lat_idx=np.flatnonzero(lat_selector); lon_idx=np.flatnonzero(lon_selector)
        if lat_idx.size==0 or lon_idx.size==0:
            return (np.array([],dtype=np.float64),np.array([],dtype=np.float64),
                    np.empty((0,0),dtype=np.float64),np.empty((0,0),dtype=bool))
        lat=latitudes[lat_idx]; lon=longitudes[lon_idx]
        elev=elevation[np.ix_(lat_idx,lon_idx)]
        miss=missing[np.ix_(lat_idx,lon_idx)]
        return lat,lon,elev,miss

    def build_surface(
        self,
        *,
        ocean: str,
        latitude_min: float,
        latitude_max: float,
        longitude_min: float,
        longitude_max: float,
    ) -> dict[str, Any]:
        latitude_min,latitude_max,longitude_min,longitude_max=self._normalize_bbox(
            latitude_min,latitude_max,longitude_min,longitude_max
        )
        boundary=self.geometry_engine.boundary(ocean)
        if not boundary.available or boundary.geometry is None:
            raise LookupError(f"No real ocean boundary is available for {boundary.ocean_name}.")

        index=self._load_index()
        chunks=[
            chunk for chunk in index.get("chunks",[])
            if self._intersects(chunk,latitude_min,latitude_max,longitude_min,longitude_max)
        ]
        if not chunks:
            raise LookupError("No cached GEBCO chunk intersects the requested bathymetry region.")

        lat_map: dict[float, tuple[np.ndarray,np.ndarray]]={}
        lon_values:set[float]=set()
        chunk_ids=[]
        for chunk in chunks:
            path=Path(chunk["npz_path"])
            if not path.exists():
                continue
            lat,lon,elev,miss=self._slice_chunk(path,latitude_min,latitude_max,longitude_min,longitude_max)
            if lat.size==0 or lon.size==0:
                continue
            chunk_ids.append(str(chunk["chunk_id"]))
            for row_i,lat_value in enumerate(lat):
                key=round(float(lat_value),12)
                if key not in lat_map:
                    lat_map[key]=(np.asarray(lon), np.asarray(elev[row_i]), np.asarray(miss[row_i]))
                else:
                    old_lon,old_elev,old_miss=lat_map[key]
                    lon_map={round(float(v),12):i for i,v in enumerate(old_lon)}
                    combined_lon=list(old_lon); combined_elev=list(old_elev); combined_miss=list(old_miss)
                    for col_i,lon_value in enumerate(lon):
                        lkey=round(float(lon_value),12)
                        if lkey in lon_map:
                            pos=lon_map[lkey]
                            if bool(combined_miss[pos]) and not bool(miss[row_i,col_i]):
                                combined_elev[pos]=elev[row_i,col_i]; combined_miss[pos]=miss[row_i,col_i]
                        else:
                            lon_map[lkey]=len(combined_lon)
                            combined_lon.append(float(lon_value)); combined_elev.append(float(elev[row_i,col_i])); combined_miss.append(bool(miss[row_i,col_i]))
                    lat_map[key]=(np.asarray(combined_lon),np.asarray(combined_elev),np.asarray(combined_miss))
                lon_values.update(float(v) for v in lon)

        if not lat_map or not lon_values:
            raise LookupError("Intersecting GEBCO chunks contain no requested bathymetry cells.")

        latitudes=np.asarray(sorted(lat_map),dtype=np.float64)
        longitudes=np.asarray(sorted(lon_values),dtype=np.float64)
        point_count=int(latitudes.size*longitudes.size)
        if point_count>self.MAX_GRID_POINTS:
            raise ValueError(
                f"Requested bathymetry grid contains {point_count} cells, exceeding the limit of {self.MAX_GRID_POINTS}."
            )

        elevation=np.full((latitudes.size,longitudes.size),np.nan,dtype=np.float64)
        missing=np.ones((latitudes.size,longitudes.size),dtype=bool)
        for row_i,lat_value in enumerate(latitudes):
            _,row_elev,row_miss=lat_map[round(float(lat_value),12)]
            # Each cached chunk is on the same GEBCO grid; place values by longitude.
            lon_source=lat_map[round(float(lat_value),12)][0]
            positions={round(float(v),12):i for i,v in enumerate(lon_source)}
            for col_i,lon_value in enumerate(longitudes):
                pos=positions.get(round(float(lon_value),12))
                if pos is not None:
                    elevation[row_i,col_i]=row_elev[pos]
                    missing[row_i,col_i]=bool(row_miss[pos])

        try:
            from shapely.geometry import Point, shape
        except ImportError as exc:
            raise RuntimeError("shapely is required for the bathymetry water mask.") from exc
        source_geometry=shape(boundary.geometry)
        water=np.zeros_like(missing,dtype=bool)
        for i,lat_value in enumerate(latitudes):
            for j,lon_value in enumerate(longitudes):
                water[i,j]=bool(source_geometry.covers(Point(float(lon_value),float(lat_value))))

        output_missing=missing | ~water
        output_elevation=elevation.copy()
        output_elevation[~water]=np.nan
        valid=(water & ~output_missing & np.isfinite(output_elevation))
        valid_values=output_elevation[valid]
        minimum=float(np.min(valid_values)) if valid_values.size else None
        maximum=float(np.max(valid_values)) if valid_values.size else None

        resolution=None
        if longitudes.size>1:
            resolution=float(np.median(np.abs(np.diff(longitudes))))

        return {
            "available": bool(valid_values.size),
            "ocean": boundary.ocean_name,
            "grid": {
                "latitudes":[float(v) for v in latitudes],
                "longitudes":[float(v) for v in longitudes],
                "elevation_m":self._finite_grid(output_elevation),
                "missing_mask":self._bool_grid(output_missing),
                "water_mask":self._bool_grid(water),
                "shape":[int(latitudes.size),int(longitudes.size)],
                "cell_count":point_count,
                "valid_value_count":int(np.count_nonzero(valid)),
                "water_cell_count":int(np.count_nonzero(water)),
            },
            "bounding_box":{
                "latitude_min":latitude_min,"latitude_max":latitude_max,
                "longitude_min":longitude_min,"longitude_max":longitude_max,
            },
            "elevation":{
                "minimum_m":minimum,
                "maximum_m":maximum,
                "units":"m",
                "positive_direction":"upward",
                "seafloor_depth_m_note":"Negative elevation values represent positions below sea level.",
            },
            "source":{
                "provider":"GEBCO",
                "dataset":"GEBCO_2026",
                "source_url":index.get("source_url"),
                "chunk_ids":sorted(set(chunk_ids)),
                "selection":"nearest source grid cells; no interpolation",
            },
            "grid_metadata":{
                "resolution_degrees":resolution,
                "coordinate_reference_system":"EPSG:4326",
                "bathymetry_type":"numerical seafloor elevation",
            },
            "boundary":boundary.geometry,
            "scientific_rules":{
                "synthetic_data":False,
                "interpolation":False,
                "water_mask_from_real_ocean_geometry":True,
            },
        }
