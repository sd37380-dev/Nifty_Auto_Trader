"""
NVIDIA NIM Model Provider Adapter.

Integrates NVIDIA NIM endpoints (e.g. integrate.api.nvidia.com/v1) for models like
nvidia/nemotron-3-ultra-550b-a55b with extended reasoning and thinking support.
"""

import json
import logging
import os
import re
import time
from typing import Any, Dict, Optional, Type, TypeVar
from pydantic import BaseModel
from openai import AsyncOpenAI

from nifty_trader.router.base import ModelProvider, ModelResponse

logger = logging.getLogger("nifty_trader.router.nvidia")
T = TypeVar("T", bound=BaseModel)


class NvidiaProvider(ModelProvider):
    """
    Adapter for NVIDIA NIM API with OpenAI-compatible client.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_key_env: str = "NVIDIA_API_KEY",
        base_url: str = "https://integrate.api.nvidia.com/v1",
        default_model: str = "nvidia/nemotron-3-ultra-550b-a55b",
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
        return "nvidia"

    def _ensure_client(self) -> AsyncOpenAI:
        if not self._client:
            key = os.environ.get(self._api_key_env)
            if not key:
                raise ValueError(
                    f"NVIDIA API key not found in environment variable '{self._api_key_env}'."
                )
            self._api_key = key
            self._client = AsyncOpenAI(api_key=self._api_key, base_url=self._base_url)
        return self._client

    async def _execute_chat_completion(
        self,
        client: AsyncOpenAI,
        target_model: str,
        messages: list,
        temperature: float,
    ):
        """
        Executes chat completion with thinking template if supported,
        automatically falling back if server rejects thinking parameters.
        """
        extra_body: Dict[str, Any] = {
            "chat_template_kwargs": {"enable_thinking": True},
        }

        try:
            return await client.chat.completions.create(
                model=target_model,
                messages=messages,
                temperature=temperature,
                top_p=0.95,
                max_tokens=16384,
                extra_body=extra_body,
            )
        except Exception as e:
            err_msg = str(e).lower()
            if "thinking" in err_msg or "budget" in err_msg or "runner" in err_msg or "400" in err_msg:
                logger.warning("NVIDIA extra_body rejected (%s). Retrying without extra_body...", e)
                return await client.chat.completions.create(
                    model=target_model,
                    messages=messages,
                    temperature=temperature,
                    top_p=0.95,
                    max_tokens=16384,
                )
            raise

    async def generate_text(
        self,
        prompt: str,
        model: Optional[str] = None,
        system_instruction: Optional[str] = None,
        temperature: float = 1.0,
    ) -> ModelResponse:
        client = self._ensure_client()
        target_model = model or self._default_model
        start_time = time.perf_counter()

        messages = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
        messages.append({"role": "user", "content": prompt})

        response = await self._execute_chat_completion(
            client=client,
            target_model=target_model,
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
        temperature: float = 0.7,
    ) -> T:
        client = self._ensure_client()
        target_model = model or self._default_model

        json_schema = response_model.model_json_schema()
        system_msg = (system_instruction or "") + (
            f"\n\nYou MUST respond with valid JSON matching this schema:\n{json.dumps(json_schema, indent=2)}\n"
            "Return ONLY the JSON object, or place it inside ```json ... ``` code blocks."
        )

        messages = [{"role": "system", "content": system_msg.strip()}]
        messages.append({"role": "user", "content": prompt})

        response = await self._execute_chat_completion(
            client=client,
            target_model=target_model,
            messages=messages,
            temperature=temperature,
        )

        raw_content = response.choices[0].message.content or ""
        
        # Clean thought tags if present
        clean_content = re.sub(r"<thought>.*?</thought>", "", raw_content, flags=re.DOTALL).strip()
        
        # Extract markdown json block if present
        json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", clean_content, re.DOTALL)
        if json_match:
            clean_json = json_match.group(1).strip()
        else:
            # Fallback to finding outermost { ... }
            outer_match = re.search(r"(\{.*\})", clean_content, re.DOTALL)
            clean_json = outer_match.group(1).strip() if outer_match else clean_content.strip()

        return response_model.model_validate_json(clean_json)

    async def health_check(self) -> bool:
        try:
            client = self._ensure_client()
            resp = await client.models.list()
            return bool(resp and resp.data)
        except Exception as e:
            logger.warning("NvidiaProvider health check failed: %s", e)
            return False
