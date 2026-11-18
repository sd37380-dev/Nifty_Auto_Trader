"""
Indian Market Trading Session Manager.

Tracks market session states (PRE_MARKET, OPEN, POST_MARKET, CLOSED, HOLIDAY)
for the National Stock Exchange (NSE) NIFTY index in Asia/Kolkata timezone.
Enforces:
1. Trading hours: 09:15 AM to 03:30 PM IST (09:15 - 15:30 IST)
2. Saturdays & Sundays: Closed (Stop auto-update)
3. NSE Declared Holidays: Closed (Stop auto-update)
"""

from datetime import datetime, time, timezone
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from nifty_trader.market_data.models import IST, MarketSessionStatus

logger = logging.getLogger(__name__)

# Built-in fallback NSE Trading Holidays (YYYY-MM-DD)
DEFAULT_NSE_HOLIDAYS = {
    # 2025
    "2025-01-26": "Republic Day",
    "2025-02-26": "Mahashivratri",
    "2025-03-14": "Holi",
    "2025-03-31": "Id-Ul-Fitr (Ramzan Id)",
    "2025-04-10": "Mahavir Jayanti",
    "2025-04-14": "Dr. Baba Saheb Ambedkar Jayanti",
    "2025-04-18": "Good Friday",
    "2025-05-01": "Maharashtra Day",
    "2025-06-07": "Bakri Id / Eid ul-Adha",
    "2025-07-06": "Muharram",
    "2025-08-15": "Independence Day",
    "2025-08-27": "Ganesh Chaturthi",
    "2025-10-02": "Mahatma Gandhi Jayanti",
    "2025-10-21": "Dussehra",
    "2025-10-22": "Diwali Balipratipada",
    "2025-11-05": "Prakash Gurpurb Sri Guru Nanak Dev",
    "2025-12-25": "Christmas",
    # 2026
    "2026-01-26": "Republic Day",
    "2026-02-15": "Mahashivratri",
    "2026-03-03": "Holi",
    "2026-03-20": "Id-Ul-Fitr (Ramzan Id)",
    "2026-03-27": "Ram Navami",
    "2026-03-31": "Mahavir Jayanti",
    "2026-04-03": "Good Friday",
    "2026-04-14": "Dr. Baba Saheb Ambedkar Jayanti",
    "2026-05-01": "Maharashtra Day",
    "2026-05-27": "Bakri Id / Eid ul-Adha",
    "2026-06-25": "Muharram",
    "2026-08-15": "Independence Day",
    "2026-08-27": "Milad-un-Nabi",
    "2026-10-02": "Mahatma Gandhi Jayanti",
    "2026-10-20": "Dussehra",
    "2026-11-08": "Diwali Laxmi Pujan",
    "2026-11-10": "Diwali Balipratipada",
    "2026-11-24": "Gurunanak Jayanti",
    "2026-12-25": "Christmas",
    # 2027
    "2027-01-26": "Republic Day",
    "2027-03-07": "Mahashivratri",
    "2027-03-22": "Holi",
    "2027-03-26": "Good Friday",
    "2027-04-14": "Dr. Baba Saheb Ambedkar Jayanti",
    "2027-05-01": "Maharashtra Day",
    "2027-08-15": "Independence Day",
    "2027-10-02": "Mahatma Gandhi Jayanti",
    "2027-10-10": "Dussehra",
    "2027-10-29": "Diwali",
    "2027-12-25": "Christmas",
}


class MarketSessionManager:
    """
    Evaluates exchange trading hours and calendar schedules for NIFTY, BANKNIFTY, GIFT NIFTY.
    Enforces:
      - 09:15 - 15:30 IST: Active Trading & Auto-Update Session (Mon - Fri)
      - Saturdays & Sundays: Stopped (Standby)
      - NSE Holidays: Stopped (Standby)
    """

    PRE_MARKET_START = time(9, 0)
    REGULAR_MARKET_START = time(9, 15)
    REGULAR_MARKET_CLOSE = time(15, 30)
    POST_MARKET_CLOSE = time(16, 0)

    _holidays_cache: Optional[Dict[str, str]] = None

    @classmethod
    def load_holidays(cls) -> Dict[str, str]:
        """Loads holidays from data/market/nse_holidays.json merged with built-in list."""
        if cls._holidays_cache is not None:
            return cls._holidays_cache

        holidays = dict(DEFAULT_NSE_HOLIDAYS)
        json_path = Path("data/market/nse_holidays.json")
        if not json_path.exists():
            json_path = Path(__file__).resolve().parent.parent.parent / "data" / "market" / "nse_holidays.json"

        if json_path.exists():
            try:
                data = json.loads(json_path.read_text(encoding="utf-8"))
                custom = data.get("holidays", {})
                holidays.update(custom)
            except Exception as e:
                logger.debug("Failed loading nse_holidays.json: %s", e)

        cls._holidays_cache = holidays
        return cls._holidays_cache

    @classmethod
    def is_holiday(cls, dt: Optional[datetime] = None) -> Tuple[bool, Optional[str]]:
        """Checks if target date is an official NSE trading holiday."""
        ref_dt = dt or datetime.now(timezone.utc)
        ist_dt = ref_dt.astimezone(IST)
        date_str = ist_dt.strftime("%Y-%m-%d")
        holidays = cls.load_holidays()
        if date_str in holidays:
            return True, holidays[date_str]
        return False, None

    @classmethod
    def is_weekend(cls, dt: Optional[datetime] = None) -> Tuple[bool, Optional[str]]:
        """Checks if target date is Saturday or Sunday."""
        ref_dt = dt or datetime.now(timezone.utc)
        ist_dt = ref_dt.astimezone(IST)
        wd = ist_dt.weekday()
        if wd == 5:
            return True, "Saturday (Weekend - Market Closed)"
        elif wd == 6:
            return True, "Sunday (Weekend - Market Closed)"
        return False, None

    @classmethod
    def get_auto_update_window_status(cls, dt: Optional[datetime] = None) -> Dict[str, Any]:
        """
        Validates whether database auto-update should be running:
        Starts at 09:15 AM IST and stops at 03:30 PM IST on trading days.
        Stops on Saturdays, Sundays, and NSE holidays.
        """
        ref_dt = dt or datetime.now(timezone.utc)
        ist_dt = ref_dt.astimezone(IST)
        t = ist_dt.time()
        time_str = ist_dt.strftime("%H:%M:%S")

        # 1. Weekend check
        is_wknd, wknd_name = cls.is_weekend(ist_dt)
        if is_wknd:
            return {
                "active": False,
                "reason": wknd_name,
                "session_state": "WEEKEND_CLOSED",
                "badge_status": "STANDBY: WEEKEND (CLOSED)",
                "next_session_desc": "Resumes Monday at 09:15 AM IST",
                "ist_time": time_str,
            }

        # 2. Holiday check
        is_hday, hday_name = cls.is_holiday(ist_dt)
        if is_hday:
            return {
                "active": False,
                "reason": f"NSE Trading Holiday: {hday_name}",
                "session_state": "HOLIDAY_CLOSED",
                "badge_status": f"STANDBY: HOLIDAY ({hday_name})",
                "next_session_desc": "Resumes next trading day at 09:15 AM IST",
                "ist_time": time_str,
            }

        # 3. Trading hours check: 09:15 to 15:30 IST
        if t < cls.REGULAR_MARKET_START:
            return {
                "active": False,
                "reason": f"Pre-Market (Auto-update starts at 09:15 AM IST, current: {time_str} IST)",
                "session_state": "PRE_MARKET_STANDBY",
                "badge_status": "STANDBY: STARTS AT 09:15 AM IST",
                "next_session_desc": "Auto-update begins at 09:15 AM IST today",
                "ist_time": time_str,
            }
        elif t >= cls.REGULAR_MARKET_CLOSE:
            return {
                "active": False,
                "reason": f"Post-Market (Market closed at 03:30 PM IST, current: {time_str} IST)",
                "session_state": "POST_MARKET_CLOSED",
                "badge_status": "STANDBY: CLOSED AT 03:30 PM IST",
                "next_session_desc": "Resumes tomorrow at 09:15 AM IST",
                "ist_time": time_str,
            }
        else:
            return {
                "active": True,
                "reason": "Regular Trading Session Active (09:15 AM – 03:30 PM IST)",
                "session_state": "SESSION_ACTIVE",
                "badge_status": "🟢 AUTO-ACTIVE (09:15–15:30 IST)",
                "next_session_desc": "Auto-updating database every 5 minutes until 03:30 PM IST",
                "ist_time": time_str,
            }

    @classmethod
    def get_current_session_status(cls, dt: Optional[datetime] = None) -> MarketSessionStatus:
        """Determines market status for the given datetime (defaults to current UTC now)."""
        ref_dt = dt or datetime.now(timezone.utc)
        if ref_dt.tzinfo is None:
            ref_dt = ref_dt.replace(tzinfo=timezone.utc)
        ist_dt = ref_dt.astimezone(IST)

        # Weekend check
        is_wknd, _ = cls.is_weekend(ist_dt)
        if is_wknd:
            return MarketSessionStatus.CLOSED

        # Holiday check
        is_hday, _ = cls.is_holiday(ist_dt)
        if is_hday:
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
