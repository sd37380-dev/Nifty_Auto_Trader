"""
Anthropic Model Provider Adapter Stub.

Pluggable adapter interface for Anthropic Claude models (Claude 3.5 / 3.7 Sonnet).
"""

import os
from typing import Optional, Type, TypeVar
from pydantic import BaseModel

from nifty_trader.router.base import ModelProvider, ModelResponse

T = TypeVar("T", bound=BaseModel)


class AnthropicProvider(ModelProvider):
    """
    Pluggable adapter for direct Anthropic API.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_key_env: str = "ANTHROPIC_API_KEY",
        default_model: str = "claude-3-5-sonnet-20241022",
    ):
        self._api_key = api_key or os.environ.get(api_key_env)
        self._api_key_env = api_key_env
        self._default_model = default_model

    @property
    def provider_name(self) -> str:
        return "anthropic"

    async def generate_text(
        self,
        prompt: str,
        model: Optional[str] = None,
        system_instruction: Optional[str] = None,
        temperature: float = 0.2,
    ) -> ModelResponse:
        raise NotImplementedError("Direct Anthropic SDK is reserved for future package. Use OpenRouter provider.")

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
        raise NotImplementedError("Direct Anthropic SDK is reserved for future package. Use OpenRouter provider.")

    async def health_check(self) -> bool:
        return bool(self._api_key)
