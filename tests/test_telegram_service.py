"""
Unit and integration tests for Telegram Notifications and 15-Minute Armed Execution.
"""

from datetime import datetime, timezone
import json
from pathlib import Path
import time
from unittest.mock import MagicMock, patch
import pytest

from nifty_trader.notifications.telegram_service import (
    TelegramNotificationService,
    PendingTradeManager,
    get_telegram_service,
    get_pending_trade_manager,
)


@pytest.fixture
def mock_root_dir(tmp_path: Path):
    market_dir = tmp_path / "data" / "market"
    market_dir.mkdir(parents=True, exist_ok=True)
    return tmp_path


def test_telegram_service_credentials_and_status(mock_root_dir):
    service = TelegramNotificationService(root_dir=mock_root_dir)
    assert not service.is_configured

    service.set_credentials("1234567890:ABCdefGHIjklMNOpqrs", "987654321")
    assert service.is_configured
    assert service.chat_id == "987654321"

    status = service.get_status()
    assert status["configured"] is True
    assert status["bot_token_set"] is True
    assert status["chat_id_set"] is True
    assert "..." in status["masked_token"]


def test_telegram_message_dispatch_mocked(mock_root_dir):
    service = TelegramNotificationService(root_dir=mock_root_dir)
    service.set_credentials("1234567890:ABCdefGHIjklMNOpqrs", "987654321")

    with patch("httpx.Client.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"ok": True, "result": {"message_id": 42}}
        mock_post.return_value = mock_resp

        # Direct test message
        res = service.send_test_message()
        assert res["status"] == "ok"
        assert "successfully" in res["message"]

        # Level alert
        service.send_level_breakout_alert(
            instrument="NIFTY",
            current_spot=23620.50,
            level_price=23600.0,
            condition="CROSS_ABOVE",
            trigger_reason="Strong 15M candle close above previous day high",
            action_note="Watch for continuation or retest confirmation",
        )

        # Big news alert
        news_item = {
            "id": 101,
            "title": "RBI Cuts Repo Rate by 25 bps in Surprise Move",
            "summary": "Monetary policy committee votes unanimously to stimulate economic growth.",
            "impact_type": "HIGH_BULLISH",
            "impact_score": 5,
            "market_effect": "Massive positive catalyst for BANKNIFTY and NIFTY 50",
            "published_at": "2026-11-18 10:00:00 IST",
        }
        service.send_big_news_alert(news_item)

        # Give background threads a moment to execute
        time.sleep(0.3)
        assert mock_post.call_count >= 1


def test_pending_trade_manager_arm_and_cancel(mock_root_dir):
    service = TelegramNotificationService(root_dir=mock_root_dir)
    pm = PendingTradeManager(root_dir=mock_root_dir)

    with patch.object(service, "send_trade_intent_alert") as mock_intent, \
         patch.object(service, "send_trade_cancelled_alert") as mock_cancel, \
         patch("nifty_trader.notifications.telegram_service.get_telegram_service", return_value=service):

        trade = pm.arm_trade(
            symbol="NIFTY",
            strike=23500,
            option_type="CE",
            lots=2,
            premium=130.0,
            spot_price=23520.0,
            sl_points=25.0,
            target_points=50.0,
            reasoning="Breakout above 23500 resistance with heavy call unwinding",
            custom_countdown=60,  # 60 seconds
        )

        assert trade["status"] == "ARMED_15M"
        assert trade["strike"] == 23500
        assert trade["lots"] == 2
        assert trade["qty"] == 130
        assert trade["sl_price"] == 105.0
        assert trade["target_price"] == 180.0
        assert trade["countdown_seconds"] == 60

        mock_intent.assert_called_once_with(trade)

        # Check list pending trades
        listed = pm.list_pending_trades()
        assert len(listed) >= 1
        found = [t for t in listed if t["pending_id"] == trade["pending_id"]]
        assert len(found) == 1
        assert found[0]["remaining_seconds"] > 0

        # Cancel trade before timer ends
        cancelled = pm.cancel_trade(trade["pending_id"], reason="Manual user test cancellation")
        assert cancelled is True
        assert trade["status"] == "CANCELLED"
        mock_cancel.assert_called_once()


def test_pending_trade_manager_auto_execution(mock_root_dir):
    service = TelegramNotificationService(root_dir=mock_root_dir)
    pm = PendingTradeManager(root_dir=mock_root_dir)

    with patch.object(service, "send_trade_intent_alert"), \
         patch.object(service, "send_trade_executed_alert") as mock_executed, \
         patch("nifty_trader.notifications.telegram_service.get_telegram_service", return_value=service), \
         patch("nifty_trader.market_data.option_chain_service.get_option_chain_service") as mock_get_ocs:

        mock_ocs_instance = MagicMock()
        mock_ocs_instance.execute_option_chain_paper_trade.return_value = {
            "status": "ok",
            "trade_id": "TRADE-SIM-123",
            "symbol": "NIFTY",
            "strike": 23600,
            "option_type": "CE",
        }
        mock_get_ocs.return_value = mock_ocs_instance

        # Arm with ultra-short 1-second countdown to verify auto-execution
        trade = pm.arm_trade(
            symbol="NIFTY",
            strike=23600,
            option_type="CE",
            lots=1,
            premium=95.0,
            spot_price=23610.0,
            sl_points=20.0,
            target_points=40.0,
            reasoning="Automated breakout trigger verification",
            custom_countdown=1,
        )

        assert trade["status"] == "ARMED_15M"

        # Wait for the 1-second countdown to finish and auto-execute
        time.sleep(1.5)

        assert trade["status"] == "EXECUTED"
        assert trade["trade_id"] == "TRADE-SIM-123"
        mock_executed.assert_called_once_with(trade)
