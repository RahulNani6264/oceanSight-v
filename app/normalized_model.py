from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Literal

class CoverageModel(BaseModel):
    west:float; east:float; south:float; north:float
class Statistics(BaseModel):
    min:float|None=None; max:float|None=None
class NormalizedField(BaseModel):
    variable:str; representation:Literal["scalar","vector"]; unit:str; time_utc:str
    coverage:CoverageModel; width:int=0; height:int=0
    values:list[float]=Field(default_factory=list)
    valid_mask:list[bool]=Field(default_factory=list)
    u_values:list[float]|None=None; v_values:list[float]|None=None
    statistics:Statistics=Field(default_factory=Statistics)
    source:str; dataset:str
