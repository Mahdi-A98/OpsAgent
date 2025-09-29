from abc import ABC, abstractmethod
from core.schemas import TaskInput, TaskOutput


class OpsAgent(ABC):
    """Abstract interface for all operation agents."""

    @abstractmethod
    def execute(self, task: TaskInput) -> TaskOutput:
        pass

    @abstractmethod
    def get_status(self) -> dict:
        pass


class OpsAgentFactory(ABC):
    """Abstract factory for creating operation agents."""

    @abstractmethod
    def create_agent(self) -> OpsAgent:
        pass
