"""
Exceptions for the Browser Automation Layer.
"""


class BrowserError(Exception):
    """Base exception for all browser automation errors."""
    pass


class NavigationTimeoutError(BrowserError):
    """Raised when page navigation exceeds the configured timeout."""
    pass


class ElementNotFoundError(BrowserError):
    """Raised when an expected DOM element is not found within the timeout."""
    pass


class BrowserCrashError(BrowserError):
    """Raised when the browser subprocess crashes or loses WebSocket connection."""
    pass


class SecurityViolationError(BrowserError):
    """Raised when an action violates security constraints (e.g. file:// URL access)."""
    pass
