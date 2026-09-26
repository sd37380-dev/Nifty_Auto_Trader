"""
Candle Clock and Periodic Boundary Timer.

Calculates exact candle closing intervals (15M, 1H) for the Indian market session
and triggers deterministic observation refresh events.
"""

from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from nifty_trader.market_data.models import Timeframe
from nifty_trader.market_data.session import IST, MarketSessionManager

logger = logging = None


class CandleClock:
    """
    Deterministic clock for 15M and 1H candle boundaries.
    """

    @staticmethod
    def is_candle_closed(
        candle_timestamp: datetime,
        timeframe: Timeframe,
        as_of: Optional[datetime] = None,
        current_time: Optional[datetime] = None,
    ) -> bool:
        """
        Determines whether a candle starting at candle_timestamp has completed its period.
        """
        ref = current_time or as_of or datetime.now(timezone.utc)
        duration = timedelta(hours=1) if timeframe == Timeframe.H1 else timedelta(minutes=15)
        return ref >= (candle_timestamp + duration)

    @staticmethod
    def get_candle_close_time(candle_timestamp: datetime, timeframe: Timeframe) -> datetime:
        """Returns the exact timestamp when a candle starting at candle_timestamp closes."""
        duration = timedelta(hours=1) if timeframe == Timeframe.H1 else timedelta(minutes=15)
        return candle_timestamp + duration

    @classmethod
    def get_next_candle_close(
        cls,
        timeframe: Timeframe,
        as_of: Optional[datetime] = None,
        current_time: Optional[datetime] = None,
    ) -> datetime:
        """Alias for get_next_close_time supporting current_time."""
        return cls.get_next_close_time(timeframe, as_of=current_time or as_of)

    @staticmethod
    def get_next_close_time(timeframe: Timeframe, as_of: Optional[datetime] = None) -> datetime:
        """
        Calculates the upcoming candle close timestamp for the given timeframe.
        """
        ref = as_of or datetime.now(timezone.utc)
        ist_dt = ref.astimezone(IST)

        if timeframe == Timeframe.M15:
            # 15M boundaries at 0, 15, 30, 45 mins
            minute = (ist_dt.minute // 15 + 1) * 15
            if minute >= 60:
                next_ist = ist_dt.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
            else:
                next_ist = ist_dt.replace(minute=minute, second=0, microsecond=0)
        else:  # Timeframe.H1
            # 1H boundaries at top of hour
            next_ist = ist_dt.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)

        return next_ist.astimezone(timezone.utc)

    @staticmethod
    def get_completed_boundaries_between(
        timeframe: Timeframe,
        start_time: datetime,
        end_time: datetime,
    ) -> List[datetime]:
        """
        Returns all completed candle close timestamps between start_time and end_time.
        """
        step = timedelta(hours=1) if timeframe == Timeframe.H1 else timedelta(minutes=15)
        closes = []
        cur = start_time
        while cur + step <= end_time:
            cur += step
            closes.append(cur)
        return closes
