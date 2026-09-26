"""
Unit tests for the ModelRouter and provider adapters.
"""

import pytest
from pydantic import BaseModel, Field
from typing import Optional, Type, TypeVar

from nifty_trader.router.base import ModelProvider, ModelResponse, TaskTier
from nifty_trader.router.router import ModelRouter

T = TypeVar("T", bound=BaseModel)


class DummyOutput(BaseModel):
    bias: str = Field(description="Directional bias")
    confidence: float = Field(description="Confidence level 0 to 1")


class MockProvider(ModelProvider):
    def __init__(self, name: str, should_fail: bool = False):
        self._name = name
        self.should_fail = should_fail
        self.call_count = 0

    @property
    def provider_name(self) -> str:
        return self._name

    async def generate_text(
        self,
        prompt: str,
        model: Optional[str] = None,
        system_instruction: Optional[str] = None,
        temperature: float = 0.2,
    ) -> ModelResponse:
        self.call_count += 1
        if self.should_fail:
            raise RuntimeError(f"Simulated failure in provider '{self._name}'")
        return ModelResponse(
            provider=self._name,
            model=model or "mock-model",
            content=f"Mock response to: {prompt}",
        )

    async def generate_structured(
        self,
        prompt: str,
        response_model: Type[T],
        model: Optional[str] = None,
        system_instruction: Optional[str] = None,
        image_bytes: Optional[bytes] = None,
        image_mime_type: str = "image/png",
        temperature: float = 0.1,
    ) -> T:
        self.call_count += 1
        if self.should_fail:
            raise RuntimeError(f"Simulated failure in provider '{self._name}'")
        # Return valid mock object
        return response_model.model_validate({"bias": "BULLISH", "confidence": 0.85})

    async def health_check(self) -> bool:
        return not self.should_fail


@pytest.mark.asyncio
async def test_router_task_tier_routing():
    """Verify task tier dispatches to primary provider."""
    mock_primary = MockProvider("gemini")
    mock_fallback = MockProvider("openrouter")

    router = ModelRouter()
    router.register_provider(mock_primary)
    router.register_provider(mock_fallback)

    result = await router.route_structured(
        task_tier=TaskTier.MARKET_ANALYSIS,
        prompt="Analyze NIFTY 1H trend",
        response_model=DummyOutput,
    )

    assert result.bias == "BULLISH"
    assert result.confidence == 0.85
    assert mock_primary.call_count == 1
    assert mock_fallback.call_count == 0


@pytest.mark.asyncio
async def test_router_fallback_and_cooldown():
    """Verify router automatically fails over to fallback on primary failure and latches cooldown."""
    mock_failing_primary = MockProvider("gemini", should_fail=True)
    mock_healthy_fallback = MockProvider("openrouter", should_fail=False)

    router = ModelRouter()
    router.register_provider(mock_failing_primary)
    router.register_provider(mock_healthy_fallback)

    assert not router.is_in_cooldown("gemini")

    # First call: primary fails -> fallback takes over
    result = await router.route_structured(
        task_tier=TaskTier.FAST_OBSERVE,
        prompt="Routine 15M tick",
        response_model=DummyOutput,
    )

    assert result.bias == "BULLISH"
    assert mock_failing_primary.call_count == 1
    assert mock_healthy_fallback.call_count == 1
    assert router.is_in_cooldown("gemini")

    # Second call: primary is in cooldown, router routes directly to fallback
    result2 = await router.route_structured(
        task_tier=TaskTier.FAST_OBSERVE,
        prompt="Next 15M tick",
        response_model=DummyOutput,
    )

    assert result2.bias == "BULLISH"
    assert mock_failing_primary.call_count == 1  # Not called again while in cooldown
    assert mock_healthy_fallback.call_count == 2


@pytest.mark.asyncio
async def test_router_health_checks():
    """Verify health_check_all queries all registered providers."""
    router = ModelRouter()
    router.register_provider(MockProvider("p1", should_fail=False))
    router.register_provider(MockProvider("p2", should_fail=True))

    results = await router.health_check_all()
    assert results["p1"] is True
    assert results["p2"] is False
