"""
ModelRouter Core Engine.

Coordinates multi-provider selection, task-tier routing, fallback handling,
and provider cooldown management.
"""

import logging
import time
from pathlib import Path
from typing import Any, Dict, Optional, Type, TypeVar, Union
import yaml
from pydantic import BaseModel

from nifty_trader.router.base import ModelProvider, ModelResponse, TaskTier
from nifty_trader.router.gemini import GeminiProvider
from nifty_trader.router.openrouter import OpenRouterProvider
from nifty_trader.router.openai_provider import OpenAIProvider
from nifty_trader.router.anthropic_provider import AnthropicProvider

logger = logging.getLogger("nifty_trader.router")
T = TypeVar("T", bound=BaseModel)

DEFAULT_ROUTER_CONFIG: Dict[str, Any] = {
    "routing": {
        TaskTier.FAST_OBSERVE.value: {
            "provider": "gemini",
            "model": "gemini-2.5-flash",
            "temperature": 0.1,
            "fallback": {
                "provider": "openrouter",
                "model": "google/gemini-2.5-flash",
            },
        },
        TaskTier.MARKET_ANALYSIS.value: {
            "provider": "gemini",
            "model": "gemini-2.5-flash",
            "temperature": 0.2,
            "fallback": {
                "provider": "openrouter",
                "model": "anthropic/claude-3.5-sonnet",
            },
        },
        TaskTier.SETUP_CONFIRMATION.value: {
            "provider": "gemini",
            "model": "gemini-2.5-flash",
            "temperature": 0.1,
            "fallback": {
                "provider": "openrouter",
                "model": "anthropic/claude-3.7-sonnet",
            },
        },
        TaskTier.RESEARCH.value: {
            "provider": "gemini",
            "model": "gemini-2.5-flash",
            "temperature": 0.3,
            "fallback": {
                "provider": "openrouter",
                "model": "perplexity/sonar",
            },
        },
        TaskTier.POST_MORTEM.value: {
            "provider": "gemini",
            "model": "gemini-2.5-flash",
            "temperature": 0.2,
            "fallback": {
                "provider": "openrouter",
                "model": "deepseek/deepseek-r1",
            },
        },
        TaskTier.STRATEGY_IMPROVEMENT.value: {
            "provider": "gemini",
            "model": "gemini-2.5-flash",
            "temperature": 0.3,
            "fallback": {
                "provider": "openrouter",
                "model": "anthropic/claude-3.7-sonnet",
            },
        },
    },
    "providers": {
        "gemini": {
            "api_key_env": "GEMINI_API_KEY",
            "default_model": "gemini-2.5-flash",
        },
        "openrouter": {
            "api_key_env": "OPENROUTER_API_KEY",
            "default_model": "anthropic/claude-3.5-sonnet",
        },
        "openai": {
            "api_key_env": "OPENAI_API_KEY",
            "default_model": "gpt-4o",
        },
        "anthropic": {
            "api_key_env": "ANTHROPIC_API_KEY",
            "default_model": "claude-3-5-sonnet-20241022",
        },
    },
    "settings": {
        "cooldown_seconds": 60.0,
    },
}


class ModelRouter:
    """
    Decoupled cognitive model router.
    Routes tasks to configured providers and manages resilient failovers.
    """

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        config_path: Optional[Union[str, Path]] = None,
    ):
        if config is not None:
            self._config = config
        elif config_path is not None and Path(config_path).exists():
            with open(config_path, "r", encoding="utf-8") as f:
                self._config = yaml.safe_load(f) or DEFAULT_ROUTER_CONFIG
        else:
            self._config = DEFAULT_ROUTER_CONFIG

        self._providers: Dict[str, ModelProvider] = {}
        self._provider_cooldowns: Dict[str, float] = {}  # provider_name -> cooldown_expiry_epoch
        self._cooldown_duration = self._config.get("settings", {}).get("cooldown_seconds", 60.0)

        self._init_providers()

    def _init_providers(self) -> None:
        prov_configs = self._config.get("providers", {})

        # Gemini
        gemini_cfg = prov_configs.get("gemini", {})
        self._providers["gemini"] = GeminiProvider(
            api_key_env=gemini_cfg.get("api_key_env", "GEMINI_API_KEY"),
            default_model=gemini_cfg.get("default_model", "gemini-2.5-flash"),
        )

        # OpenRouter
        openrouter_cfg = prov_configs.get("openrouter", {})
        self._providers["openrouter"] = OpenRouterProvider(
            api_key_env=openrouter_cfg.get("api_key_env", "OPENROUTER_API_KEY"),
            default_model=openrouter_cfg.get("default_model", "anthropic/claude-3.5-sonnet"),
        )

        # OpenAI
        openai_cfg = prov_configs.get("openai", {})
        self._providers["openai"] = OpenAIProvider(
            api_key_env=openai_cfg.get("api_key_env", "OPENAI_API_KEY"),
            default_model=openai_cfg.get("default_model", "gpt-4o"),
        )

        # Anthropic
        anthropic_cfg = prov_configs.get("anthropic", {})
        self._providers["anthropic"] = AnthropicProvider(
            api_key_env=anthropic_cfg.get("api_key_env", "ANTHROPIC_API_KEY"),
            default_model=anthropic_cfg.get("default_model", "claude-3-5-sonnet-20241022"),
        )

    def register_provider(self, provider: ModelProvider) -> None:
        """Dynamically registers or overrides a provider adapter."""
        self._providers[provider.provider_name] = provider

    def is_in_cooldown(self, provider_name: str) -> bool:
        expiry = self._provider_cooldowns.get(provider_name, 0.0)
        return time.time() < expiry

    def set_cooldown(self, provider_name: str) -> None:
        logger.warning("Placing provider '%s' in cooldown for %ss", provider_name, self._cooldown_duration)
        self._provider_cooldowns[provider_name] = time.time() + self._cooldown_duration

    def clear_cooldown(self, provider_name: str) -> None:
        if provider_name in self._provider_cooldowns:
            del self._provider_cooldowns[provider_name]

    def get_tier_config(self, task_tier: TaskTier) -> Dict[str, Any]:
        routing = self._config.get("routing", {})
        return routing.get(task_tier.value, DEFAULT_ROUTER_CONFIG["routing"][task_tier.value])

    async def route_structured(
        self,
        task_tier: TaskTier,
        prompt: str,
        response_model: Type[T],
        system_instruction: Optional[str] = None,
        image_bytes: Optional[bytes] = None,
        image_mime_type: str = "image/png",
    ) -> T:
        """
        Routes a structured schema generation request with automatic failover.
        """
        tier_cfg = self.get_tier_config(task_tier)
        primary_name = tier_cfg.get("provider", "gemini")
        primary_model = tier_cfg.get("model", "gemini-2.5-flash")
        temperature = tier_cfg.get("temperature", 0.1)
        fallback_cfg = tier_cfg.get("fallback")

        last_error = None

        # Try Primary if not in cooldown
        if not self.is_in_cooldown(primary_name):
            try:
                provider = self._providers.get(primary_name)
                if not provider:
                    raise ValueError(f"Provider '{primary_name}' not registered.")
                return await provider.generate_structured(
                    prompt=prompt,
                    response_model=response_model,
                    model=primary_model,
                    system_instruction=system_instruction,
                    image_bytes=image_bytes,
                    image_mime_type=image_mime_type,
                    temperature=temperature,
                )
            except Exception as e:
                logger.error("Primary provider '%s' failed for tier '%s': %s", primary_name, task_tier.value, e)
                last_error = e
                self.set_cooldown(primary_name)

        # Try Fallback if primary failed or was in cooldown
        if fallback_cfg:
            fb_name = fallback_cfg.get("provider")
            fb_model = fallback_cfg.get("model")
            logger.info("Attempting fallback provider '%s' (%s) for tier '%s'", fb_name, fb_model, task_tier.value)
            provider = self._providers.get(fb_name)
            if provider:
                try:
                    return await provider.generate_structured(
                        prompt=prompt,
                        response_model=response_model,
                        model=fb_model,
                        system_instruction=system_instruction,
                        image_bytes=image_bytes,
                        image_mime_type=image_mime_type,
                        temperature=temperature,
                    )
                except Exception as fb_err:
                    logger.error("Fallback provider '%s' also failed: %s", fb_name, fb_err)
                    raise RuntimeError(f"All providers exhausted for '{task_tier.value}'. Primary error: {last_error}; Fallback error: {fb_err}")

        raise RuntimeError(f"All providers exhausted for task tier '{task_tier.value}'. Error: {last_error}")

    async def route_text(
        self,
        task_tier: TaskTier,
        prompt: str,
        system_instruction: Optional[str] = None,
    ) -> ModelResponse:
        """
        Routes a freeform text generation request with automatic failover.
        """
        tier_cfg = self.get_tier_config(task_tier)
        primary_name = tier_cfg.get("provider", "gemini")
        primary_model = tier_cfg.get("model", "gemini-2.5-flash")
        temperature = tier_cfg.get("temperature", 0.2)
        fallback_cfg = tier_cfg.get("fallback")

        last_error = None

        if not self.is_in_cooldown(primary_name):
            try:
                provider = self._providers.get(primary_name)
                if not provider:
                    raise ValueError(f"Provider '{primary_name}' not registered.")
                return await provider.generate_text(
                    prompt=prompt,
                    model=primary_model,
                    system_instruction=system_instruction,
                    temperature=temperature,
                )
            except Exception as e:
                logger.error("Primary provider '%s' failed for tier '%s': %s", primary_name, task_tier.value, e)
                last_error = e
                self.set_cooldown(primary_name)

        if fallback_cfg:
            fb_name = fallback_cfg.get("provider")
            fb_model = fallback_cfg.get("model")
            provider = self._providers.get(fb_name)
            if provider:
                try:
                    return await provider.generate_text(
                        prompt=prompt,
                        model=fb_model,
                        system_instruction=system_instruction,
                        temperature=temperature,
                    )
                except Exception as fb_err:
                    raise RuntimeError(f"All providers exhausted for '{task_tier.value}'. Primary: {last_error}; Fallback: {fb_err}")

        raise RuntimeError(f"All providers exhausted for task tier '{task_tier.value}'. Error: {last_error}")

    async def health_check_all(self) -> Dict[str, bool]:
        """Runs health checks on all registered providers."""
        results = {}
        for name, provider in self._providers.items():
            results[name] = await provider.health_check()
        return results
