"""
Gemini Model Provider Adapter.

Integrates Google GenAI SDK with structured Pydantic schema validation,
multimodal vision inspection, and health checking.
"""

import os
import time
from typing import Optional, Type, TypeVar
from pydantic import BaseModel
from google import genai
from google.genai import types

from nifty_trader.router.base import ModelProvider, ModelResponse

T = TypeVar("T", bound=BaseModel)


class GeminiProvider(ModelProvider):
    """
    Adapter for Google Gemini models (Gemini 2.0 Flash, Gemini 1.5 Pro, etc.).
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_key_env: str = "GEMINI_API_KEY",
        default_model: str = "gemini-2.0-flash",
    ):
        self._api_key = api_key or os.environ.get(api_key_env) or os.environ.get("GOOGLE_API_KEY")
        self._api_key_env = api_key_env
        self._default_model = default_model
        self._client: Optional[genai.Client] = None

        if self._api_key:
            self._client = genai.Client(api_key=self._api_key)

    @property
    def provider_name(self) -> str:
        return "gemini"

    def _ensure_client(self) -> genai.Client:
        if not self._client:
            key = os.environ.get(self._api_key_env) or os.environ.get("GOOGLE_API_KEY")
            if not key:
                raise ValueError(
                    f"Gemini API key not found in environment variable '{self._api_key_env}' or 'GOOGLE_API_KEY'."
                )
            self._api_key = key
            self._client = genai.Client(api_key=self._api_key)
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

        config = types.GenerateContentConfig(
            temperature=temperature,
            system_instruction=system_instruction,
        )

        response = await client.aio.models.generate_content(
            model=target_model,
            contents=prompt,
            config=config,
        )

        latency = (time.perf_counter() - start_time) * 1000.0
        text_content = response.text or ""

        return ModelResponse(
            provider=self.provider_name,
            model=target_model,
            content=text_content,
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

        contents = []
        if image_bytes:
            image_part = types.Part.from_bytes(data=image_bytes, mime_type=image_mime_type)
            contents.append(image_part)
        contents.append(prompt)

        config = types.GenerateContentConfig(
            temperature=temperature,
            system_instruction=system_instruction,
            response_mime_type="application/json",
            response_schema=response_model,
        )

        response = await client.aio.models.generate_content(
            model=target_model,
            contents=contents,
            config=config,
        )

        if not response.text:
            raise ValueError(f"Empty response received from Gemini model '{target_model}'.")

        # Parse and validate against the Pydantic response_model
        return response_model.model_validate_json(response.text)

    async def health_check(self) -> bool:
        try:
            client = self._ensure_client()
            # Fast ping using minimal tokens
            resp = await client.aio.models.generate_content(
                model=self._default_model,
                contents="ping",
                config=types.GenerateContentConfig(max_output_tokens=5),
            )
            return bool(resp and resp.text)
        except Exception:
            return False
