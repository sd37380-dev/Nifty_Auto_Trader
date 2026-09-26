"""
Browser Session Manager.

Tracks browser session lifecycle, status transitions, and activity metrics.
"""

import uuid
from datetime import datetime, timezone
from typing import List, Optional
from nifty_trader.browser.models import (
    BrowserAction,
    BrowserActionResult,
    BrowserSession,
    BrowserSessionStatus,
)


class BrowserSessionManager:
    """
    Manages active session metadata and interaction history.
    """

    def __init__(self, session_id: Optional[str] = None):
        self.session = BrowserSession(
            session_id=session_id or f"sess_{uuid.uuid4().hex[:8]}",
            status=BrowserSessionStatus.STARTING,
        )
        self.history: List[BrowserActionResult] = []

    @property
    def session_id(self) -> str:
        return self.session.session_id

    @property
    def status(self) -> BrowserSessionStatus:
        return self.session.status

    def set_status(self, status: BrowserSessionStatus) -> None:
        self.session.status = status
        self.session.last_activity = datetime.now(timezone.utc).isoformat()

    def update_page_info(self, url: str, title: str) -> None:
        self.session.current_url = url
        self.session.current_title = title
        self.session.last_activity = datetime.now(timezone.utc).isoformat()

    def record_action(self, result: BrowserActionResult) -> None:
        self.history.append(result)
        self.session.action_count += 1
        self.session.last_activity = datetime.now(timezone.utc).isoformat()

        # Update URLs from action result if present
        if result.url_after:
            self.session.current_url = result.url_after

    def get_recent_history(self, limit: int = 10) -> List[BrowserActionResult]:
        return self.history[-limit:]
