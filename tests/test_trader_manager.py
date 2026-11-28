"""
Tests for Autonomous Trader Process Manager & Remote Operations.
Verifies Option B (Telegram listener) and Option C (Dashboard Trader Manager).
"""

from pathlib import Path
import time
import pytest

from nifty_trader.execution.trader_manager import AutonomousTraderManager, get_trader_manager
from nifty_trader.notifications.telegram_service import TelegramNotificationService, get_telegram_service


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
    assert isinstance(status["recent_logs"], list)


def test_telegram_service_listener_init():
    tele = get_telegram_service()
    assert hasattr(tele, "start_command_listener")
    assert hasattr(tele, "stop_command_listener")
    assert hasattr(tele, "_handle_command")
