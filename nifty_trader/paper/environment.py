"""
Sensibull Environment Safety Detector & Guard.

STRICT INVARIANT:
Must verify that the active screen is explicitly Virtual Portfolio / Paper Trading
and NEVER a live broker order placement screen. If live broker is detected, aborts immediately.
"""

import logging
import re
from typing import Optional, Tuple
from nifty_trader.paper.contracts import SensibullEnvironmentType

logger = logging.getLogger(__name__)


class UnsafeTradingEnvironmentError(Exception):
    """Raised when the browser environment is NOT safely confirmed as Virtual Trading."""
    pass


class SensibullEnvironmentDetector:
    """
    Evaluates browser URL, page text, and DOM elements to certify that the current
    Sensibull session is strictly in Virtual / Paper Trading mode.
    """

    VIRTUAL_URL_PATTERNS = [
        re.compile(r"sensibull\.com/.*virtual[-_]?trade", re.IGNORECASE),
        re.compile(r"sensibull\.com/.*virtual[-_]?portfolio", re.IGNORECASE),
        re.compile(r"sensibull\.com/.*paper[-_]?trade", re.IGNORECASE),
        re.compile(r"sensibull\.com/.*custom[-_]?strategy", re.IGNORECASE),
    ]

    VIRTUAL_TEXT_KEYWORDS = [
        "virtual trade",
        "virtual portfolio",
        "paper trading",
        "virtual positions",
        "virtual p&l",
        "virtual funds",
        "add to virtual portfolio",
        "virtual strategy",
    ]

    LIVE_BROKER_KEYWORDS = [
        "trade with broker",
        "place real order",
        "real broker account",
        "live execution",
        "send to zerodha",
        "send to upstox",
        "send to angel",
        "broker terminal",
        "real order",
    ]

    AUTH_KEYWORDS = [
        "login with broker",
        "log in with",
        "select broker",
        "continue with google",
        "please login to view",
        "authentication required",
        "sign in with google",
    ]

    def detect(self, url: str, page_title: str, visible_text: str) -> Tuple[SensibullEnvironmentType, bool, str]:
        """
        Detects the current environment.
        Returns: (SensibullEnvironmentType, is_safe, reason_explanation)
        """
        text_lower = (visible_text or "").lower()
        url_lower = (url or "").lower()
        title_lower = (page_title or "").lower()

        # 1. Check for Authentication Required
        for auth_kw in self.AUTH_KEYWORDS:
            if auth_kw in text_lower or auth_kw in title_lower:
                return (
                    SensibullEnvironmentType.LOGIN_REQUIRED,
                    False,
                    f"Authentication required: Detected '{auth_kw}' on page.",
                )

        # 2. Check for Dangerous Live Broker Keywords
        for live_kw in self.LIVE_BROKER_KEYWORDS:
            if live_kw in text_lower:
                logger.critical("SAFETY BREACH DETECTED: Live broker keyword '%s' found in DOM!", live_kw)
                return (
                    SensibullEnvironmentType.LIVE_BROKER,
                    False,
                    f"CRITICAL SAFETY VIOLATION: Page contains live broker keyword '{live_kw}'! Aborting order.",
                )

        # 3. Check for Virtual Trading URL Pattern
        is_virtual_url = any(p.search(url_lower) for p in self.VIRTUAL_URL_PATTERNS)

        # 4. Check for Virtual Trading Text Keywords
        matching_v_keywords = [kw for kw in self.VIRTUAL_TEXT_KEYWORDS if kw in text_lower]

        if is_virtual_url or len(matching_v_keywords) >= 1:
            return (
                SensibullEnvironmentType.VIRTUAL_TRADE,
                True,
                f"Verified safe Virtual Trading environment (URL match: {is_virtual_url}, Keywords: {matching_v_keywords[:2]}).",
            )

        # 5. Ambiguous / Unknown State
        return (
            SensibullEnvironmentType.UNKNOWN,
            False,
            "Cannot certify environment as Virtual Trading: Missing virtual trade indicators.",
        )

    def assert_safe_environment(self, url: str, page_title: str, visible_text: str) -> None:
        """
        Enforces safety invariant. Raises UnsafeTradingEnvironmentError if not virtual.
        """
        env_type, is_safe, reason = self.detect(url, page_title, visible_text)
        if not is_safe:
            raise UnsafeTradingEnvironmentError(
                f"Environment safety assertion failed: {env_type.value} - {reason}"
            )
