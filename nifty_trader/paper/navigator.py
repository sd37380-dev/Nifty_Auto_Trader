"""
Sensibull Virtual Portfolio Navigation & Browser Session Manager.

Handles safe navigation to Sensibull's Virtual Trade / Paper Portfolio interface,
detecting environment safety, session recovery, and tab management.
"""

from datetime import datetime, timezone
import logging
from typing import Optional, Tuple
from nifty_trader.browser.browser_agent import BrowserAgent
from nifty_trader.browser.models import BrowserObservation
from nifty_trader.paper.contracts import SensibullEnvironmentType
from nifty_trader.paper.environment import (
    SensibullEnvironmentDetector,
    UnsafeTradingEnvironmentError,
)

logger = logging.getLogger(__name__)


class SensibullPaperNavigator:
    """
    Directs browser navigation to Sensibull Virtual Trading endpoints,
    certifies environment safety, and handles session interruptions.
    """

    DEFAULT_VIRTUAL_TRADE_URL = "https://web.sensibull.com/virtual-trade"

    def __init__(
        self,
        browser_agent: BrowserAgent,
        detector: Optional[SensibullEnvironmentDetector] = None,
        virtual_trade_url: str = DEFAULT_VIRTUAL_TRADE_URL,
    ):
        self.browser = browser_agent
        self.detector = detector or SensibullEnvironmentDetector()
        self.virtual_trade_url = virtual_trade_url

    async def navigate_to_virtual_portfolio(
        self,
        capture_screen: bool = True,
    ) -> Tuple[BrowserObservation, SensibullEnvironmentType, bool]:
        """
        Navigates to the Sensibull Virtual Portfolio, evaluates the environment,
        and returns: (observation, environment_type, is_safe).
        """
        logger.info("Navigating to Sensibull Virtual Portfolio at %s...", self.virtual_trade_url)

        obs = await self.browser.navigate(
            url=self.virtual_trade_url,
            capture_screen=capture_screen,
            screenshot_prefix="sensibull_virtual",
        )

        env_type, is_safe, reason = self.detector.detect(
            url=obs.url,
            page_title=obs.page_title,
            visible_text=obs.visible_text,
        )

        if not is_safe:
            logger.warning("Sensibull environment safety check failed: %s (%s)", env_type.value, reason)
            if env_type == SensibullEnvironmentType.LIVE_BROKER:
                raise UnsafeTradingEnvironmentError(
                    f"CRITICAL: Live broker detected at {obs.url}! Aborting immediately."
                )

        logger.info("Sensibull environment detected: %s (Safe: %s)", env_type.value, is_safe)
        return obs, env_type, is_safe

    async def refresh_virtual_portfolio(self) -> BrowserObservation:
        """Refreshes the current virtual portfolio view."""
        return await self.browser.navigate(
            url=self.virtual_trade_url,
            capture_screen=True,
            screenshot_prefix="sensibull_refresh",
        )
