from pydantic import BaseModel, Field
from typing import Optional, Mapping, List, Union


class ContainerSpec(BaseModel):
    image: str = Field(..., description="Docker image name or ID (e.g. 'mysql:8.0')")
    name: Optional[str] = Field(None, description="Optional container name")
    ports: Optional[Mapping] = Field(
        None, description="Port mappings {host_port: container_port}"
    )
    env: Optional[dict[str, str] | list[str]] = Field(
        None, description="Environment variables for the container"
    )
    volumes: Optional[List[str]] = Field(
        None, description="Volume mounts in Docker format ['host_path:container_path']"
    )
    detach: bool = Field(
        True, description="Run container in detached mode"
    )
    
    
class ContainerTask(BaseModel):
    container_name: str = Field(..., description="docker container name")
    command: List[str] = Field(..., description="list of commands to execute on the container")
