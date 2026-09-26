"""
OpenRouter Model Provider Adapter.

Integrates OpenRouter for universal multi-model access (DeepSeek, Claude, Llama, etc.)
via OpenAI-compatible standard endpoints.
"""

import os
import time
from typing import Optional, Type, TypeVar
from pydantic import BaseModel
from openai import AsyncOpenAI

from nifty_trader.router.base import ModelProvider, ModelResponse

T = TypeVar("T", bound=BaseModel)


class OpenRouterProvider(ModelProvider):
    """
    Adapter for OpenRouter API.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_key_env: str = "OPENROUTER_API_KEY",
        base_url: str = "https://openrouter.ai/api/v1",
        default_model: str = "anthropic/claude-3.5-sonnet",
    ):
        self._api_key = api_key or os.environ.get(api_key_env)
        self._api_key_env = api_key_env
        self._base_url = base_url
        self._default_model = default_model
        self._client: Optional[AsyncOpenAI] = None

        if self._api_key:
            self._client = AsyncOpenAI(api_key=self._api_key, base_url=self._base_url)

    @property
    def provider_name(self) -> str:
        return "openrouter"

    def _ensure_client(self) -> AsyncOpenAI:
        if not self._client:
            key = os.environ.get(self._api_key_env)
            if not key:
                raise ValueError(
                    f"OpenRouter API key not found in environment variable '{self._api_key_env}'."
                )
            self._api_key = key
            self._client = AsyncOpenAI(api_key=self._api_key, base_url=self._base_url)
        return self._client

    async def generate_text(
        self,
        prompt: str,
        model: Optional[str] = None,
        system_instruction: Optional[str] = None,
        temperature: float = 0.2,
    ) -> ModelResponse:
        client = self._ensure_client()
        target_model = model or self._default_model
        start_time = time.perf_counter()

        messages = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
        messages.append({"role": "user", "content": prompt})

        response = await client.chat.completions.create(
            model=target_model,
            messages=messages,
            temperature=temperature,
        )

        latency = (time.perf_counter() - start_time) * 1000.0
        content = response.choices[0].message.content or ""

        return ModelResponse(
            provider=self.provider_name,
            model=target_model,
            content=content,
            latency_ms=round(latency, 2),
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
        client = self._ensure_client()
        target_model = model or self._default_model

        json_schema = response_model.model_json_schema()
        system_msg = (system_instruction or "") + (
            f"\n\nYou MUST respond with valid JSON matching this schema:\n{json_schema}"
        )

        messages = [{"role": "system", "content": system_msg.strip()}]
        messages.append({"role": "user", "content": prompt})

        response = await client.chat.completions.create(
            model=target_model,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=temperature,
        )

        raw_json = response.choices[0].message.content or ""
        return response_model.model_validate_json(raw_json)

    async def health_check(self) -> bool:
        try:
            client = self._ensure_client()
            resp = await client.models.list()
            return bool(resp and resp.data)
        except Exception:
            return False
