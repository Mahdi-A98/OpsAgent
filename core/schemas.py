from pydantic import BaseModel
from typing import Optional

class TaskInput(BaseModel):
    action: str
    command: Optional[str] = None
    target: Optional[str] = None

class TaskOutput(BaseModel):
    success: bool
    output: str
    error: Optional[str] = None
