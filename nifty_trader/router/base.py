"""
Base interfaces and types for the ModelRouter.

Provides the ModelProvider abstract base class, task tiers, and response wrappers.
"""

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Dict, Optional, Type, TypeVar
from pydantic import BaseModel, Field

T = TypeVar("T", bound=BaseModel)


class TaskTier(str, Enum):
    """
    Task tiers for dynamic, task-based model routing.
    Different trading sub-tasks require different cognitive trade-offs.
    """
    FAST_OBSERVE = "fast_observe"              # Quick status checks, noise filtering, 15M routine ticks
    MARKET_ANALYSIS = "market_analysis"        # 1H trend evaluation, multi-level confluence, vision inspection
    SETUP_CONFIRMATION = "setup_confirmation"  # Precise 15M trade setup validation & invalidation mapping
    RESEARCH = "research"                      # Macro news, RBI statements, sector sentiment
    POST_MORTEM = "post_mortem"                # Deep post-trade failure analysis, mistake classification
    STRATEGY_IMPROVEMENT = "strategy_improvement" # Generating parameter mutation hypotheses for lab testing


class ModelResponse(BaseModel):
    """Standardized response container returned by model providers."""
    provider: str
    model: str
    content: str
    parsed: Optional[Any] = None
    finish_reason: Optional[str] = "stop"
    usage: Dict[str, int] = Field(default_factory=dict)
    latency_ms: float = 0.0


class ModelProvider(ABC):
    """
    Abstract base class for all AI model provider adapters.
    Guarantees interchangeable cognitive backends (Gemini, OpenRouter, OpenAI, Anthropic, Local).
    """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Unique identifier of the provider (e.g., 'gemini', 'openrouter')."""
        pass

    @abstractmethod
    async def generate_text(
        self,
        prompt: str,
        model: str,
        system_instruction: Optional[str] = None,
        temperature: float = 0.2,
    ) -> ModelResponse:
        """
        Generates freeform text from the provider.
        """
        pass

    @abstractmethod
    async def generate_structured(
        self,
        prompt: str,
        response_model: Type[T],
        model: str,
        system_instruction: Optional[str] = None,
        image_bytes: Optional[bytes] = None,
        image_mime_type: str = "image/png",
        temperature: float = 0.1,
    ) -> T:
        """
        Generates structured data strictly conforming to the given Pydantic schema.
        Must validate and return an instantiated Pydantic model.
        """
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """
        Checks whether the provider API is accessible and authenticated.
        Returns True if operational, False otherwise.
        """
        pass
