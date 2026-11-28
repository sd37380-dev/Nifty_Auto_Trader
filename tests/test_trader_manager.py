"""
Tests for Autonomous Trader Process Manager, Market Schedule & Remote Operations.
Verifies Option B (Telegram listener), Option C (Dashboard Trader Manager), and 09:00 AM schedule gating.
"""

from datetime import datetime, time, timedelta, timezone
from pathlib import Path
import pytest

from nifty_trader.execution.trader_manager import AutonomousTraderManager, get_trader_manager
from nifty_trader.notifications.telegram_service import TelegramNotificationService, get_telegram_service
from scripts.autonomous_price_action_trader import get_trading_session_phase

IST = timezone(timedelta(hours=5, minutes=30))


def test_trader_manager_singleton():
    tm1 = get_trader_manager()
    tm2 = get_trader_manager()
    assert tm1 is tm2
    assert isinstance(tm1, AutonomousTraderManager)


def test_trader_manager_status_idle():
    tm = get_trader_manager()
    status = tm.get_status()
    assert status["status"] == "ok"
    assert "is_running" in status
    assert "uptime_seconds" in status
    assert "recent_logs" in status
    assert "session_phase" in status
    assert "session_message" in status
    assert isinstance(status["recent_logs"], list)


def test_telegram_service_listener_init():
    tele = get_telegram_service()
    assert hasattr(tele, "start_command_listener")
    assert hasattr(tele, "stop_command_listener")
    assert hasattr(tele, "_handle_command")


def test_market_schedule_before_9am_standby():
    # Test 8:00 AM on a Monday (2026-11-30 is Monday)
    dt_8am = datetime(2026, 11, 30, 8, 0, 0, tzinfo=IST)
    sched = AutonomousTraderManager.get_session_schedule(dt_8am)
    assert sched["is_trade_day"] is True
    assert sched["is_monitoring_active"] is False
    assert sched["phase"] == "STANDBY_AWAITING_OPEN"
    assert "09:00 AM" in sched["message"]

    # Also test trader script phase function
    trader_sched = get_trading_session_phase(dt_8am)
    assert trader_sched["is_monitoring_active"] is False
    assert trader_sched["phase"] == "STANDBY_AWAITING_OPEN"


def test_market_schedule_premarket_9am():
    # Test 9:05 AM on Monday (pre-market window)
    dt_905am = datetime(2026, 11, 30, 9, 5, 0, tzinfo=IST)
    sched = AutonomousTraderManager.get_session_schedule(dt_905am)
    assert sched["is_trade_day"] is True
    assert sched["is_monitoring_active"] is True
    assert sched["phase"] == "PRE_MARKET_MONITORING"


def test_market_schedule_regular_trading_session():
    # Test 10:30 AM on Monday (active trading session)
    dt_1030am = datetime(2026, 11, 30, 10, 30, 0, tzinfo=IST)
    sched = AutonomousTraderManager.get_session_schedule(dt_1030am)
    assert sched["is_trade_day"] is True
    assert sched["is_monitoring_active"] is True
    assert sched["phase"] == "LIVE_MARKET_MONITORING"


def test_market_schedule_weekend_closed():
    # Test Saturday (2026-11-28 is Saturday)
    dt_sat = datetime(2026, 11, 28, 10, 0, 0, tzinfo=IST)
    sched = AutonomousTraderManager.get_session_schedule(dt_sat)
    assert sched["is_trade_day"] is False
    assert sched["is_monitoring_active"] is False
    assert sched["phase"] == "WEEKEND_CLOSED"
