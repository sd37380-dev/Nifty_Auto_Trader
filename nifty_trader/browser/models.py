"""
Data models and schemas for Browser Automation.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class SourceType(str, Enum):
    """Classification of the visited web source."""
    CHART = "CHART"               # TradingView, chart platforms
    NSE = "NSE"                   # National Stock Exchange official portal
    NEWS = "NEWS"                 # Financial news (Moneycontrol, ET, Reuters)
    SEARCH = "SEARCH"             # Search engines (Google, DuckDuckGo)
    GENERAL_WEB = "GENERAL_WEB"   # Permitted public informational websites
    UNKNOWN = "UNKNOWN"           # Unclassified sources


class BrowserSessionStatus(str, Enum):
    """Lifecycle status of a browser session."""
    STARTING = "STARTING"
    READY = "READY"
    BUSY = "BUSY"
    RECOVERING = "RECOVERING"
    FAILED = "FAILED"
    STOPPED = "STOPPED"


class BrowserAction(str, Enum):
    """Deterministic browser interaction commands."""
    OPEN_URL = "OPEN_URL"
    CLICK = "CLICK"
    TYPE = "TYPE"
    PRESS_KEY = "PRESS_KEY"
    SCROLL = "SCROLL"
    BACK = "BACK"
    FORWARD = "FORWARD"
    RELOAD = "RELOAD"
    WAIT_FOR_ELEMENT = "WAIT_FOR_ELEMENT"
    CAPTURE_SCREENSHOT = "CAPTURE_SCREENSHOT"
    GET_VISIBLE_TEXT = "GET_VISIBLE_TEXT"
    INSPECT_DOM = "INSPECT_DOM"


class BrowserActionResult(BaseModel):
    """Structured result produced by a single browser interaction action."""
    action: BrowserAction
    success: bool
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    duration_ms: float = 0.0
    url_before: str = ""
    url_after: str = ""
    message: str = ""
    error: Optional[str] = None


class BrowserSession(BaseModel):
    """State tracking of an active browser session."""
    session_id: str
    started_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    current_url: str = "about:blank"
    current_title: str = ""
    status: BrowserSessionStatus = BrowserSessionStatus.STARTING
    last_activity: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    action_count: int = 0


class BrowserObservation(BaseModel):
    """
    Structured perceptual observation extracted from a web page.
    NOTE: Represents pure perception, NOT trading judgment.
    Strictly excludes trading conclusions (no signals, entry prices, stops, or targets).
    """
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    url: str = Field(description="URL of the inspected webpage.")
    page_title: str = Field(description="Title of the inspected webpage.")
    source_type: SourceType = Field(default=SourceType.UNKNOWN, description="Classified category of the webpage.")
    visible_text: str = Field(default="", description="Sanitized and bounded text extracted from the webpage.")
    important_elements: List[Dict[str, Any]] = Field(default_factory=list, description="Key interactive elements (buttons, inputs, headings).")
    screenshot_path: Optional[str] = Field(default=None, description="Local filesystem path to captured screenshot if taken.")
    interaction_history: List[BrowserActionResult] = Field(default_factory=list, description="Recent interaction trace.")
    warnings: List[str] = Field(default_factory=list, description="Non-fatal warnings encountered (e.g. popups, paywall text detected).")
    errors: List[str] = Field(default_factory=list, description="Errors encountered during observation.")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Session and environment metadata.")
