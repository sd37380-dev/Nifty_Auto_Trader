"""
OpenAI Model Provider Adapter.

Integrates official OpenAI API (GPT-4o, o3-mini, etc.) with structured schema outputs.
"""

import os
import time
from typing import Optional, Type, TypeVar
from pydantic import BaseModel
from openai import AsyncOpenAI

from nifty_trader.router.base import ModelProvider, ModelResponse

T = TypeVar("T", bound=BaseModel)


class OpenAIProvider(ModelProvider):
    """
    Adapter for direct OpenAI API.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_key_env: str = "OPENAI_API_KEY",
        default_model: str = "gpt-4o",
    ):
        self._api_key = api_key or os.environ.get(api_key_env)
        self._api_key_env = api_key_env
        self._default_model = default_model
        self._client: Optional[AsyncOpenAI] = None

        if self._api_key:
            self._client = AsyncOpenAI(api_key=self._api_key)

    @property
    def provider_name(self) -> str:
        return "openai"

    def _ensure_client(self) -> AsyncOpenAI:
        if not self._client:
            key = os.environ.get(self._api_key_env)
            if not key:
                raise ValueError(f"OpenAI API key not found in environment variable '{self._api_key_env}'.")
            self._api_key = key
            self._client = AsyncOpenAI(api_key=self._api_key)
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

        messages = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
        messages.append({"role": "user", "content": prompt})

        # Use beta structured outputs
        completion = await client.beta.chat.completions.parse(
            model=target_model,
            messages=messages,
            response_format=response_model,
            temperature=temperature,
        )

        parsed = completion.choices[0].message.parsed
        if not parsed:
            raise ValueError(f"Failed to parse structured output from model '{target_model}'.")
        return parsed

    async def health_check(self) -> bool:
        try:
            client = self._ensure_client()
            resp = await client.models.list()
            return bool(resp and resp.data)
        except Exception:
            return False
