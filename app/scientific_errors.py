from fastapi import HTTPException

def unsupported_variable(name: str):
 return HTTPException(400, detail={'code':'UNSUPPORTED_VARIABLE','variable':name,'message':f"Unsupported variable '{name}'."})
def unavailable_data(variable: str, reason: str):
 return HTTPException(503, detail={'code':'DATA_UNAVAILABLE','variable':variable,'message':reason})
