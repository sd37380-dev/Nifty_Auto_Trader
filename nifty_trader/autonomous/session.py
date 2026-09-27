"""
Package 5: Autonomous Session Controller.

Integrates with Package 3 MarketSessionManager to enforce market session boundaries:
- Prevents observation cycles outside market hours.
- Handles Pre-market waiting (09:00 - 09:15 IST) and wakes exactly at Market Open.
- Terminates cycles cleanly at Market Close (15:30 IST) with SESSION_ENDED.
"""

from datetime import datetime, timezone
import logging
from typing import Dict, Optional, Tuple

from nifty_trader.autonomous.contracts import (
    AutonomousState,
    WaitDecision,
    WaitReason,
)
from nifty_trader.autonomous.wait_policy import WaitPolicy
from nifty_trader.market_data.models import IST, MarketSessionStatus
from nifty_trader.market_data.session import MarketSessionManager

logger = logging.getLogger(__name__)


class AutonomousSessionController:
    """
    Evaluates exchange schedule and guides autonomous state transitions relative to market sessions.
    """

    def __init__(
        self,
        session_manager: Optional[MarketSessionManager] = None,
        wait_policy: Optional[WaitPolicy] = None,
    ):
        self.session_manager = session_manager or MarketSessionManager()
        self.wait_policy = wait_policy or WaitPolicy()

    def evaluate_session(
        self,
        current_time: Optional[datetime] = None,
    ) -> Tuple[MarketSessionStatus, Optional[AutonomousState], Optional[WaitDecision]]:
        """
        Evaluates the current market session status.
        Returns:
          (session_status, recommended_state, optional_wait_decision)
        """
        now = current_time or datetime.now(timezone.utc)
        status = self.session_manager.get_current_session_status(now)
        session_times = self.session_manager.get_session_times(now)

        if status == MarketSessionStatus.OPEN:
            # Market is open for regular trading; active observation permitted
            return status, None, None

        elif status == MarketSessionStatus.PRE_MARKET:
            # In pre-market (09:00 - 09:15 IST); wait for market open
            open_time = session_times["market_open"]
            decision = self.wait_policy.formulate_pre_market_decision(
                market_open_time=open_time,
                current_time=now,
            )
            return status, AutonomousState.SESSION_PAUSED, decision

        elif status == MarketSessionStatus.POST_MARKET or status == MarketSessionStatus.CLOSED:
            # Market is closed; autonomous cycles terminate
            return status, AutonomousState.SESSION_ENDED, None

        return status, None, None

    def get_session_times(self, dt: Optional[datetime] = None) -> Dict[str, datetime]:
        """Returns session boundary times."""
        return self.session_manager.get_session_times(dt)
