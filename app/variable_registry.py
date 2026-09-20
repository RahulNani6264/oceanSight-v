from __future__ import annotations
from dataclasses import dataclass
from typing import Literal

@dataclass(frozen=True)
class VariableSpec:
    id: str
    representation: Literal["scalar","vector"]
    unit: str
    provider: str
    dataset: str
    fields: tuple[str, ...]
    connected: bool = False

VARIABLES = {
 "temperature": VariableSpec("temperature","scalar","°C","INCOIS/HYCOM","RSMC HYCOM",("temperature",),True),
 "salinity": VariableSpec("salinity","scalar","PSU","INCOIS/HYCOM","RSMC HYCOM",("salinity",),True),
 "current_u": VariableSpec("current_u","vector","m/s","ocean-vector","HYCOM/current",("u",),True),
 "current_v": VariableSpec("current_v","vector","m/s","ocean-vector","HYCOM/current",("v",),True),
 "sea_surface_height": VariableSpec("sea_surface_height","scalar","m","altimetry","altimetry",("ssh",),False),
 "wind": VariableSpec("wind","vector","m/s","atmospheric","atmospheric wind",("u","v"),False),
 "air_pressure": VariableSpec("air_pressure","scalar","hPa","atmospheric","surface pressure",("pressure",),False),
 "chlorophyll": VariableSpec("chlorophyll","scalar","mg/m³","satellite-ocean-color","chlorophyll-a",("chlor_a",),False),
 "bathymetry": VariableSpec("bathymetry","scalar","m","bathymetry","GEBCO",("elevation",),True),
}
ALIASES={"temp":"temperature","sst":"temperature","sal":"salinity","ssh":"sea_surface_height","current":"current_speed"}

def normalize_variable(name:str)->str:
    key=name.strip().lower().replace("-","_").replace(" ","_")
    return ALIASES.get(key,key)

def get_variable(name:str)->VariableSpec:
    key=normalize_variable(name)
    try:return VARIABLES[key]
    except KeyError: raise KeyError(f"Unsupported variable: {name}")

def catalog()->list[dict]:
    return [{"id":v.id,"representation":v.representation,"unit":v.unit,"provider":v.provider,"dataset":v.dataset,"connected":v.connected} for v in VARIABLES.values()]
