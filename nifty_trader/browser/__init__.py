"""
Browser Automation Package.
"""

from nifty_trader.browser.base import BrowserProvider
from nifty_trader.browser.browser_agent import BrowserAgent
from nifty_trader.browser.errors import (
    BrowserCrashError,
    BrowserError,
    ElementNotFoundError,
    NavigationTimeoutError,
    SecurityViolationError,
)
from nifty_trader.browser.hermes_adapter import HermesBrowserAdapter
from nifty_trader.browser.models import (
    BrowserAction,
    BrowserActionResult,
    BrowserObservation,
    BrowserSession,
    BrowserSessionStatus,
    SourceType,
)
from nifty_trader.browser.screenshot import ScreenshotManager
from nifty_trader.browser.session import BrowserSessionManager

__all__ = [
    "BrowserProvider",
    "HermesBrowserAdapter",
    "BrowserAgent",
    "ScreenshotManager",
    "BrowserSessionManager",
    "BrowserObservation",
    "BrowserSession",
    "BrowserSessionStatus",
    "BrowserAction",
    "BrowserActionResult",
    "SourceType",
    "BrowserError",
    "NavigationTimeoutError",
    "ElementNotFoundError",
    "BrowserCrashError",
    "SecurityViolationError",
]
