"""
Browser Agent.

High-level autonomous operator coordinating browser navigation,
DOM inspection, screenshot capture, bounded retry recovery,
and structured observation compilation.
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional
from nifty_trader.browser.base import BrowserProvider
from nifty_trader.browser.errors import BrowserCrashError, BrowserError
from nifty_trader.browser.hermes_adapter import HermesBrowserAdapter
from nifty_trader.browser.models import (
    BrowserAction,
    BrowserActionResult,
    BrowserObservation,
    BrowserSessionStatus,
    SourceType,
)
from nifty_trader.browser.navigation import classify_source_type
from nifty_trader.browser.observation import sanitize_dom_elements, sanitize_web_text

logger = logging.getLogger("nifty_trader.browser.agent")


class BrowserAgent:
    """
    High-level browser operator for autonomous market and web research.
    Completely strategy-agnostic; collects perception, never trading decisions.
    """

    def __init__(
        self,
        provider: Optional[BrowserProvider] = None,
        max_action_retries: int = 2,
        restart_on_disconnect: bool = True,
        max_visible_text_chars: int = 12000,
        max_dom_elements: int = 200,
    ):
        self.provider = provider or HermesBrowserAdapter()
        self.max_retries = max_action_retries
        self.restart_on_disconnect = restart_on_disconnect
        self.max_text_chars = max_visible_text_chars
        self.max_dom_elements = max_dom_elements

    async def start(self) -> None:
        """Starts the underlying browser provider."""
        await self.provider.start()

    async def stop(self) -> None:
        """Stops the underlying browser provider."""
        await self.provider.stop()

    async def _execute_with_retry(self, action_coro_fn):
        """Executes a browser operation with bounded retries and recovery."""
        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                return await action_coro_fn()
            except (BrowserCrashError, Exception) as e:
                last_error = e
                logger.warning("Browser action failed (attempt %d/%d): %s", attempt + 1, self.max_retries + 1, e)
                if attempt < self.max_retries:
                    if self.restart_on_disconnect:
                        logger.info("Attempting browser session restart...")
                        try:
                            await self.provider.stop()
                            await self.provider.start()
                        except Exception as restart_err:
                            logger.error("Failed to restart browser: %s", restart_err)
                    await asyncio.sleep(1.0)

        raise last_error

    async def navigate(self, url: str, capture_screen: bool = True, screenshot_prefix: str = "web") -> BrowserObservation:
        """
        Navigates to URL, waits for stabilization, inspects page, and returns BrowserObservation.
        """
        await self._execute_with_retry(lambda: self.provider.open_url(url))
        return await self.observe_current_page(capture_screen=capture_screen, screenshot_prefix=screenshot_prefix)

    async def observe_current_page(self, capture_screen: bool = True, screenshot_prefix: str = "observe") -> BrowserObservation:
        """
        Performs bounded inspection on the current active page without re-navigating.
        """
        current_url = await self.provider.get_current_url()
        title = await self.provider.get_title()
        source_type = classify_source_type(current_url)

        # 1. Bounded text extraction
        raw_text = await self.provider.get_visible_text(max_chars=self.max_text_chars * 2)
        sanitized_text = sanitize_web_text(raw_text, max_chars=self.max_text_chars)

        # 2. Key DOM elements
        raw_elements = await self.provider.inspect_dom(
            selector="button, a, input, [role='button'], h1, h2, h3, [data-name]",
            max_elements=self.max_dom_elements,
        )
        elements = sanitize_dom_elements(raw_elements, max_elements=self.max_dom_elements)

        # 3. Optional screenshot capture
        shot_path = None
        warnings = []
        errors = []

        if capture_screen:
            try:
                shot_path = await self.provider.capture_screenshot(name_prefix=screenshot_prefix)
            except Exception as e:
                warnings.append(f"Screenshot capture failed: {e}")

        # Check for potential paywall or cookie banner notices
        lower_text = sanitized_text.lower()
        if "accept all cookies" in lower_text or "cookie settings" in lower_text:
            warnings.append("Cookie consent banner detected on page.")
        if "sign in" in lower_text and source_type == SourceType.CHART:
            warnings.append("Chart page prompt for user sign-in detected.")

        return BrowserObservation(
            url=current_url,
            page_title=title,
            source_type=source_type,
            visible_text=sanitized_text,
            important_elements=elements,
            screenshot_path=shot_path,
            warnings=warnings,
            errors=errors,
            metadata={"text_length": len(sanitized_text), "element_count": len(elements)},
        )

    async def inspect_tradingview_nifty(self, timeframe: str = "1h") -> BrowserObservation:
        """
        Targeted capability method for inspecting TradingView NIFTY 50 page.
        Does NOT produce trading signals. Only captures perception.
        """
        target_url = "https://in.tradingview.com/symbols/NSE-NIFTY/"
        logger.info("Navigating to TradingView NIFTY 50 (%s)...", target_url)
        obs = await self.navigate(target_url, capture_screen=True, screenshot_prefix=f"tradingview_nifty_{timeframe}")

        # If timeframe interaction requested, attempt to click the matching button if visible
        if timeframe.lower() in ["1h", "15m"]:
            logger.info("Attempting to locate timeframe control '%s'...", timeframe)
            # Try clicking timeframe button if available on page
            btn_selector = f"button[value='{timeframe}'], [data-value='{timeframe}']"
            if await self.provider.element_exists(btn_selector):
                await self.provider.click(btn_selector)
                await asyncio.sleep(1.0)
                # Re-observe
                obs = await self.observe_current_page(capture_screen=True, screenshot_prefix=f"tradingview_nifty_{timeframe}_selected")

        return obs
