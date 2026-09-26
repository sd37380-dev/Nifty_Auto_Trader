"""
Nifty Autonomous Trader Runtime.

Core orchestration runtime initializing ModelRouter, BrowserAgent,
state machine, and cognitive analysis pipeline.
"""

import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional
import yaml
from pydantic import BaseModel, Field

from nifty_trader.browser.browser_agent import BrowserAgent
from nifty_trader.browser.hermes_adapter import HermesBrowserAdapter
from nifty_trader.browser.models import BrowserObservation
from nifty_trader.browser.screenshot import ScreenshotManager
from nifty_trader.core.state import MarketObservationOutput, TradingState
from nifty_trader.router.base import TaskTier
from nifty_trader.router.router import ModelRouter

logger = logging.getLogger("nifty_trader.runtime")


class VisualPerceptionOutput(BaseModel):
    """
    Schema for purely neutral visual perception verification.
    STRICTLY PROHIBITS trading conclusions (no BUY, SELL, target, stop loss).
    """
    page_description: str = Field(description="Objective factual description of the visible webpage or chart.")
    detected_timeframe: str = Field(description="Visible timeframe on chart or 'N/A' if not a chart.")
    visible_components: list[str] = Field(default_factory=list, description="List of recognized UI components (e.g. candlestick series, volume bars, header).")
    symbol_identified: str = Field(description="Ticker or title identified on page.")


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

        # Load environment variables
        self._load_environment(env_file)

        # Load settings
        self.settings = self._load_yaml(self.config_dir / "settings.yaml")

        # Initialize Model Router
        models_config_path = self.config_dir / "models.yaml"
        self.router = ModelRouter(config_path=models_config_path)

        # Initialize Browser Subsystem
        browser_cfg = self.settings.get("browser", {})
        shots_dir = self.root_dir / browser_cfg.get("screenshots", {}).get("directory", "data/browser/screenshots")
        retention = browser_cfg.get("screenshots", {}).get("retention_days", 7)
        screenshot_mgr = ScreenshotManager(storage_dir=shots_dir, retention_days=retention)

        adapter = HermesBrowserAdapter(
            chrome_path=browser_cfg.get("chrome_path", r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
            user_data_dir=self.root_dir / "data" / "browser" / "chrome_profile",
            remote_port=browser_cfg.get("remote_port", 9225),
            headless=browser_cfg.get("headless", True),
            navigation_timeout_seconds=browser_cfg.get("navigation_timeout_seconds", 30.0),
            element_timeout_seconds=browser_cfg.get("element_timeout_seconds", 10.0),
            screenshot_manager=screenshot_mgr,
        )

        extraction_cfg = browser_cfg.get("extraction", {})
        self.browser = BrowserAgent(
            provider=adapter,
            max_action_retries=browser_cfg.get("max_action_retries", 2),
            restart_on_disconnect=browser_cfg.get("restart_on_disconnect", True),
            max_visible_text_chars=extraction_cfg.get("max_visible_text_chars", 12000),
            max_dom_elements=extraction_cfg.get("max_dom_elements", 200),
        )

        logger.info("NiftyTraderRuntime initialized in state: %s", self.state.value)

    def _load_environment(self, env_file: Optional[Path]) -> None:
        from dotenv import load_dotenv

        candidate = env_file or (self.root_dir / ".env")
        if candidate.exists():
            load_dotenv(candidate)
            return

        ref_env = Path("C:/Users/Administrator/AppData/Local/hermes/.env")
        if ref_env.exists():
            load_dotenv(ref_env)

    def _load_yaml(self, path: Path) -> Dict[str, Any]:
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        return {}

    async def get_status(self) -> Dict[str, Any]:
        """Returns runtime status, AI provider health, and browser session state."""
        provider_health = await self.router.health_check_all()
        try:
            browser_state = await self.browser.provider.get_page_state()
        except Exception:
            browser_state = {"status": "STOPPED", "url": "none"}

        return {
            "app": self.settings.get("app", {}).get("name", "NIFTY Autonomous Trader"),
            "version": self.settings.get("app", {}).get("version", "0.1.0"),
            "mode": self.settings.get("app", {}).get("mode", "RESEARCH"),
            "state": self.state.value,
            "providers": provider_health,
            "browser": browser_state,
            "risk_policies": self.settings.get("risk", {}),
        }

    async def test_brain(self, custom_scenario: Optional[str] = None) -> MarketObservationOutput:
        """Sends a test market scenario through ModelRouter to Gemini."""
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

        return await self.router.route_structured(
            task_tier=TaskTier.MARKET_ANALYSIS,
            prompt=prompt,
            response_model=MarketObservationOutput,
            system_instruction=system_instruction,
        )

    async def verify_multimodal_perception(self, obs: BrowserObservation) -> VisualPerceptionOutput:
        """
        Sends the browser screenshot and page metadata to ModelRouter for neutral visual verification.
        Strictly prohibits trading decisions.
        """
        image_bytes = None
        if obs.screenshot_path and Path(obs.screenshot_path).exists():
            with open(obs.screenshot_path, "rb") as f:
                image_bytes = f.read()

        system_instruction = (
            "You are an objective computer vision perception observer. "
            "Describe the visible visual components, text, and layout of the supplied webpage screenshot. "
            "DO NOT produce trading advice, buy/sell recommendations, entry prices, or price predictions. "
            "Your output must be strictly factual, neutral, and descriptive matching the requested JSON schema."
        )

        prompt = (
            f"Page Title: {obs.page_title}\n"
            f"URL: {obs.url}\n"
            f"Source Type: {obs.source_type.value}\n\n"
            f"Describe what visual information, charts, or UI controls are visible on this page."
        )

        return await self.router.route_structured(
            task_tier=TaskTier.FAST_OBSERVE,
            prompt=prompt,
            response_model=VisualPerceptionOutput,
            system_instruction=system_instruction,
            image_bytes=image_bytes,
            image_mime_type="image/png",
        )

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
