"""
Nifty Autonomous Trader Runtime.

Core orchestration runtime initializing ModelRouter, state machine,
and cognitive analysis pipeline.
"""

import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional
import yaml

from nifty_trader.core.state import MarketAction, MarketObservationOutput, TradingState
from nifty_trader.router.base import TaskTier
from nifty_trader.router.router import ModelRouter

logger = logging.getLogger("nifty_trader.runtime")


class NiftyTraderRuntime:
    """
    Independent runtime for NIFTY Autonomous Trader.
    """

    def __init__(
        self,
        config_dir: Optional[Path] = None,
        env_file: Optional[Path] = None,
    ):
        self.root_dir = Path(__file__).resolve().parent.parent.parent
        self.config_dir = config_dir or (self.root_dir / "config")
        self.state = TradingState.STARTUP

        # Load environment variables if .env exists
        self._load_environment(env_file)

        # Load settings
        self.settings = self._load_yaml(self.config_dir / "settings.yaml")

        # Initialize Model Router
        models_config_path = self.config_dir / "models.yaml"
        self.router = ModelRouter(config_path=models_config_path)

        logger.info("NiftyTraderRuntime initialized in state: %s", self.state.value)

    def _load_environment(self, env_file: Optional[Path]) -> None:
        from dotenv import load_dotenv

        candidate = env_file or (self.root_dir / ".env")
        if candidate.exists():
            load_dotenv(candidate)
            return

        # Fallback to local AppData reference .env if present for testing convenience
        ref_env = Path("C:/Users/Administrator/AppData/Local/hermes/.env")
        if ref_env.exists():
            load_dotenv(ref_env)

    def _load_yaml(self, path: Path) -> Dict[str, Any]:
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        return {}

    async def get_status(self) -> Dict[str, Any]:
        """Returns runtime status and AI provider health."""
        provider_health = await self.router.health_check_all()
        return {
            "app": self.settings.get("app", {}).get("name", "NIFTY Autonomous Trader"),
            "version": self.settings.get("app", {}).get("version", "0.1.0"),
            "mode": self.settings.get("app", {}).get("mode", "RESEARCH"),
            "state": self.state.value,
            "providers": provider_health,
            "risk_policies": self.settings.get("risk", {}),
        }

    async def test_brain(self, custom_scenario: Optional[str] = None) -> MarketObservationOutput:
        """
        Sends a test market scenario through the ModelRouter to Gemini/primary model
        and validates structured reasoning output.
        """
        scenario = custom_scenario or (
            "NIFTY 50 is trading at 25,350. On the 1H timeframe, price is in an established "
            "bullish uptrend making higher highs above the 50 EMA. On the 15M timeframe, "
            "price has pulled back into the 20 EMA (25,340) on declining volume and formed a "
            "rejection hammer candle. No high-impact macroeconomic events are scheduled."
        )

        system_instruction = (
            "You are the reasoning brain for an autonomous NIFTY trading agent. "
            "Analyze market structure with institutional discipline. "
            "You are ALWAYS allowed to recommend 'WAIT' or 'NO_TRADE'. "
            "Never fabricate certainty. Strictly adhere to the requested JSON schema."
        )

        prompt = f"Analyze the following market condition and determine the appropriate action:\n\n{scenario}"

        logger.info("Dispatching test analysis through ModelRouter (TaskTier: MARKET_ANALYSIS)...")
        result = await self.router.route_structured(
            task_tier=TaskTier.MARKET_ANALYSIS,
            prompt=prompt,
            response_model=MarketObservationOutput,
            system_instruction=system_instruction,
        )

        return result

    async def start(self) -> None:
        """Starts the autonomous trading runtime."""
        logger.info("Starting NIFTY Autonomous Trader...")
        self.state = TradingState.STARTUP

        # Verify brain health
        health = await self.router.health_check_all()
        logger.info("Provider health check: %s", health)

        # Transition to initial observation state
        self.state = TradingState.OBSERVE_1H
        logger.info("Runtime transitioned to state: %s", self.state.value)
