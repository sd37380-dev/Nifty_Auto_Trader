"""
Indian Market Trading Session Manager.

Tracks market session states (PRE_MARKET, OPEN, POST_MARKET, CLOSED)
for the National Stock Exchange (NSE) NIFTY index in Asia/Kolkata timezone.
"""

from datetime import datetime, time, timezone
from typing import Dict, Optional

from nifty_trader.market_data.models import IST, MarketSessionStatus


class MarketSessionManager:
    """
    Evaluates exchange trading hours and calendar schedules for NIFTY.
    Trading Schedule (Monday - Friday):
      - 09:00 - 09:15 IST: Pre-Market Session
      - 09:15 - 15:30 IST: Regular Continuous Trading Session
      - 15:30 - 16:00 IST: Post-Market / Closing Price Session
      - 16:00 - 09:00 IST & Weekends: Closed
    """

    PRE_MARKET_START = time(9, 0)
    REGULAR_MARKET_START = time(9, 15)
    REGULAR_MARKET_CLOSE = time(15, 30)
    POST_MARKET_CLOSE = time(16, 0)

    @classmethod
    def get_current_session_status(cls, dt: Optional[datetime] = None) -> MarketSessionStatus:
        """
        Determines market status for the given datetime (defaults to current UTC now).
        """
        ref_dt = dt or datetime.now(timezone.utc)
        if ref_dt.tzinfo is None:
            ref_dt = ref_dt.replace(tzinfo=timezone.utc)

        ist_dt = ref_dt.astimezone(IST)

        # Check weekend (Monday is 0, Sunday is 6)
        if ist_dt.weekday() >= 5:
            return MarketSessionStatus.CLOSED

        t = ist_dt.time()

        if cls.PRE_MARKET_START <= t < cls.REGULAR_MARKET_START:
            return MarketSessionStatus.PRE_MARKET
        elif cls.REGULAR_MARKET_START <= t < cls.REGULAR_MARKET_CLOSE:
            return MarketSessionStatus.OPEN
        elif cls.REGULAR_MARKET_CLOSE <= t < cls.POST_MARKET_CLOSE:
            return MarketSessionStatus.POST_MARKET
        else:
            return MarketSessionStatus.CLOSED

    @classmethod
    def get_session_status(cls, dt: Optional[datetime] = None) -> MarketSessionStatus:
        """Alias for get_current_session_status."""
        return cls.get_current_session_status(dt)

    @classmethod
    def is_market_open(cls, dt: Optional[datetime] = None) -> bool:
        """Returns True if the market is currently in regular continuous trading session."""
        return cls.get_current_session_status(dt) == MarketSessionStatus.OPEN

    @classmethod
    def get_session_times(cls, dt: Optional[datetime] = None) -> Dict[str, datetime]:
        """Returns session boundary datetimes in UTC for the target date."""
        ref_dt = dt or datetime.now(timezone.utc)
        ist_dt = ref_dt.astimezone(IST)
        date = ist_dt.date()

        def make_dt(t: time) -> datetime:
            return datetime.combine(date, t, tzinfo=IST).astimezone(timezone.utc)

        return {
            "pre_market_start": make_dt(cls.PRE_MARKET_START),
            "market_open": make_dt(cls.REGULAR_MARKET_START),
            "market_close": make_dt(cls.REGULAR_MARKET_CLOSE),
            "post_market_close": make_dt(cls.POST_MARKET_CLOSE),
        }
