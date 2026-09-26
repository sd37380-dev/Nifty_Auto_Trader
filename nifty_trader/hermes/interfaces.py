"""
Stable Adapter Interfaces for Hermes Integration.

Isolates NIFTY Autonomous Trader from Hermes internal implementation details.
Trading logic interacts exclusively with these stable abstract interfaces.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from pydantic import BaseModel


class AdapterHealth(BaseModel):
    is_healthy: bool
    version: str
    hermes_commit: str
    domains_ready: List[str]
    details: Dict[str, Any] = {}


class ToolDefinition(BaseModel):
    name: str
    description: str
    parameters: Dict[str, Any]


class ToolExecutionResult(BaseModel):
    tool_name: str
    success: bool
    output: Any
    error: Optional[str] = None


class HermesAgentAdapter(ABC):
    """Abstract contract for driving agent actions via Hermes platform."""

    @abstractmethod
    async def initialize(self) -> None:
        """Initializes the adapter and verifies Hermes platform prerequisites."""
        pass

    @abstractmethod
    async def health_check(self) -> AdapterHealth:
        """Evaluates health of the Hermes bridge and underlying services."""
        pass

    @abstractmethod
    async def shutdown(self) -> None:
        """Gracefully closes all Hermes resources, sessions, and child processes."""
        pass


class HermesToolAdapter(ABC):
    """Abstract contract for registering and executing agent tools safely."""

    @abstractmethod
    def register_tool(self, tool_def: ToolDefinition) -> bool:
        """Registers a custom trading tool with the agent platform."""
        pass

    @abstractmethod
    async def execute_tool(self, tool_name: str, arguments: Dict[str, Any]) -> ToolExecutionResult:
        """Invokes a registered tool within the agent's safe sandbox."""
        pass

    @abstractmethod
    def list_tools(self) -> List[ToolDefinition]:
        """Lists all registered tools."""
        pass


class HermesMemoryAdapter(ABC):
    """Abstract contract for accessing agent memory without internal store coupling."""

    @abstractmethod
    async def save_observation(self, key: str, data: Dict[str, Any]) -> bool:
        """Persists observation data into memory."""
        pass

    @abstractmethod
    async def retrieve_observation(self, key: str) -> Optional[Dict[str, Any]]:
        """Retrieves observation data from memory."""
        pass


class HermesUpdateChecker(ABC):
    """Abstract contract for checking upstream Hermes updates."""

    @abstractmethod
    async def check_for_updates(self) -> Dict[str, Any]:
        """Checks for new commits on upstream Hermes."""
        pass

    @abstractmethod
    async def inspect_changes(self, target_commit: str) -> Dict[str, Any]:
        """Analyzes commit diffs and interface impacts."""
        pass
