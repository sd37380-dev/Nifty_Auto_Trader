"""
Unit tests for Package 5 AutonomousSessionController.
"""

from datetime import datetime, timezone
import pytest

from nifty_trader.autonomous.contracts import AutonomousState, WaitReason
from nifty_trader.autonomous.session import AutonomousSessionController
from nifty_trader.market_data.models import IST, MarketSessionStatus
from nifty_trader.market_data.session import MarketSessionManager


def test_session_controller_open_session():
    controller = AutonomousSessionController()
    # Friday 2026-09-25 at 10:30 IST (05:00 UTC) -> Market is OPEN
    open_time = datetime(2026, 9, 25, 5, 0, 0, tzinfo=timezone.utc)

    status, rec_state, wait_dec = controller.evaluate_session(open_time)

    assert status == MarketSessionStatus.OPEN
    assert rec_state is None
    assert wait_dec is None


def test_session_controller_pre_market_pauses_until_open():
    controller = AutonomousSessionController()
    # Friday 2026-09-25 at 09:05 IST (03:35 UTC) -> PRE_MARKET
    pre_time = datetime(2026, 9, 25, 3, 35, 0, tzinfo=timezone.utc)

    status, rec_state, wait_dec = controller.evaluate_session(pre_time)

    assert status == MarketSessionStatus.PRE_MARKET
    assert rec_state == AutonomousState.SESSION_PAUSED
    assert wait_dec is not None
    assert wait_dec.reason == WaitReason.MARKET_OPEN
    # Market open is 09:15 IST = 03:45 UTC
    expected_open = datetime(2026, 9, 25, 3, 45, 0, tzinfo=timezone.utc)
    assert wait_dec.earliest_wake_at == expected_open


def test_session_controller_post_market_concludes_session():
    controller = AutonomousSessionController()
    # Friday 2026-09-25 at 15:35 IST (10:05 UTC) -> POST_MARKET
    post_time = datetime(2026, 9, 25, 10, 5, 0, tzinfo=timezone.utc)

    status, rec_state, wait_dec = controller.evaluate_session(post_time)

    assert status == MarketSessionStatus.POST_MARKET
    assert rec_state == AutonomousState.SESSION_ENDED
    assert wait_dec is None


def test_session_controller_weekend_closed():
    controller = AutonomousSessionController()
    # Sunday 2026-09-27 at 11:00 IST -> CLOSED
    sun_time = datetime(2026, 9, 27, 5, 30, 0, tzinfo=timezone.utc)

    status, rec_state, wait_dec = controller.evaluate_session(sun_time)

    assert status == MarketSessionStatus.CLOSED
    assert rec_state == AutonomousState.SESSION_ENDED
