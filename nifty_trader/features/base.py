"""
Feature Module Contract and Status Enumeration.

Defines the stable interface that every future extension module must implement
to plug cleanly into the NIFTY Autonomous Trader core runtime.
"""

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class FeatureStatus(str, Enum):
    """Lifecycle rollout state of a feature module."""
    INSTALLED = "INSTALLED"
    DISABLED = "DISABLED"
    ENABLED = "ENABLED"
    EXPERIMENTAL = "EXPERIMENTAL"
    DEPRECATED = "DEPRECATED"
    REMOVED = "REMOVED"
    PLANNED = "PLANNED"


class FeatureCapability(BaseModel):
    """Describes a specific functional capability exposed by a feature."""
    name: str
    description: str
    is_operational: bool = True
    metadata: Dict[str, Any] = Field(default_factory=dict)


class FeatureHealth(BaseModel):
    """Health evaluation status of a feature module."""
    feature_name: str
    is_healthy: bool
    status: FeatureStatus
    message: str = "Healthy"
    details: Dict[str, Any] = Field(default_factory=dict)


class FeatureModule(ABC):
    """
    Abstract contract for all modular extensions in the NIFTY Autonomous Trader.
    """

    def __init__(
        self,
        name: str,
        version: str,
        status: FeatureStatus = FeatureStatus.INSTALLED,
        dependencies: Optional[List[str]] = None,
    ):
        self.name = name
        self.version = version
        self.status = status
        self.dependencies = dependencies or []
        self._is_started = False

    @abstractmethod
    async def initialize(self) -> None:
        """Loads configuration and prepares module dependencies."""
        pass

    @abstractmethod
    async def start(self) -> None:
        """Starts background tasks or active services."""
        pass

    @abstractmethod
    async def stop(self) -> None:
        """Stops active services cleanly and releases resources."""
        pass

    @abstractmethod
    async def health_check(self) -> FeatureHealth:
        """Evaluates live operational health."""
        pass

    @abstractmethod
    def capabilities(self) -> List[FeatureCapability]:
        """Lists capabilities provided by this module."""
        pass
