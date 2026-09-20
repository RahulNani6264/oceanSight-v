from fastapi import HTTPException
def unsupported_variable(name:str): return HTTPException(400,detail={"code":"UNSUPPORTED_VARIABLE","message":f"Unsupported variable: {name}"})
def unavailable_coverage(name:str): return HTTPException(503,detail={"code":"DATA_UNAVAILABLE","message":f"No installed dataset covers the requested region/time for {name}.","variable":name})
