"""
Abstract Base Class for Browser Providers.

Decouples the trading application from specific browser automation implementations.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from nifty_trader.browser.models import BrowserActionResult, BrowserSession


class BrowserProvider(ABC):
    """
    Abstract base class for all browser automation providers.
    """

    @abstractmethod
    async def start(self) -> BrowserSession:
        """Starts the browser session."""
        pass

    @abstractmethod
    async def stop(self) -> None:
        """Closes the browser session and releases resources."""
        pass

    @abstractmethod
    async def open_url(self, url: str) -> BrowserActionResult:
        """Navigates to a specific URL."""
        pass

    @abstractmethod
    async def get_current_url(self) -> str:
        """Returns the current URL of the active page."""
        pass

    @abstractmethod
    async def get_title(self) -> str:
        """Returns the document title of the active page."""
        pass

    @abstractmethod
    async def click(self, selector: str) -> BrowserActionResult:
        """Clicks an element matching the given CSS selector."""
        pass

    @abstractmethod
    async def type_text(self, selector: str, text: str) -> BrowserActionResult:
        """Types text into an input element."""
        pass

    @abstractmethod
    async def press_key(self, key: str) -> BrowserActionResult:
        """Presses a keyboard key (e.g. 'Enter', 'Escape')."""
        pass

    @abstractmethod
    async def scroll(self, direction: str = "down", amount: int = 500) -> BrowserActionResult:
        """Scrolls the page up or down."""
        pass

    @abstractmethod
    async def go_back(self) -> BrowserActionResult:
        """Navigates back in browser history."""
        pass

    @abstractmethod
    async def go_forward(self) -> BrowserActionResult:
        """Navigates forward in browser history."""
        pass

    @abstractmethod
    async def reload(self) -> BrowserActionResult:
        """Reloads the current page."""
        pass

    @abstractmethod
    async def get_visible_text(self, max_chars: int = 12000) -> str:
        """Extracts visible text from the page body, bounded to max_chars."""
        pass

    @abstractmethod
    async def inspect_dom(self, selector: str = "button, a, input, h1, h2, h3", max_elements: int = 200) -> List[Dict[str, Any]]:
        """Inspects interactive and structural DOM elements matching selector."""
        pass

    @abstractmethod
    async def capture_screenshot(self, name_prefix: str = "snapshot") -> str:
        """Captures a screenshot and saves it to disk, returning the absolute file path."""
        pass

    @abstractmethod
    async def wait_for_element(self, selector: str, timeout_seconds: float = 10.0) -> bool:
        """Waits until an element matching the selector appears."""
        pass

    @abstractmethod
    async def element_exists(self, selector: str) -> bool:
        """Checks if an element matching selector currently exists in DOM."""
        pass

    @abstractmethod
    async def get_page_state(self) -> Dict[str, Any]:
        """Returns a snapshot of current page status (URL, title, readyState)."""
        pass
