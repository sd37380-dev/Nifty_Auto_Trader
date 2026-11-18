"""
Unit tests for the Deterministic Safety Guard.

Validates the user's non-negotiable risk invariants:
1. Total loss maximum: ₹2,000 per day (portfolio-wide).
2. Position sizing: Exactly 1 lot per trade (25 qty NIFTY / 15 qty BANKNIFTY).
3. Single active instrument constraint: 1 instrument active at a time.
4. NIFTY limit: Max 3 trades per day, ₹1,000 max daily loss.
5. BANKNIFTY limit: Max 3 trades per day, ₹1,000 max daily loss.
6. Risk-to-Reward ratio: Minimum 1:3 (3.0).
"""

from datetime import datetime, timezone
import pytest
from unittest.mock import AsyncMock, MagicMock

from nifty_trader.paper.contracts import (
    PaperAction,
    PaperOptionType,
    PaperOrderStatus,
    PaperPosition,
    PaperPositionStatus,
    PaperTradeOrder,
    PaperTradeOrderRequest,
)
from nifty_trader.paper.executor import SensibullPaperExecutor
from nifty_trader.paper.store import PaperTradeStore
from nifty_trader.safety.contracts import (
    InstrumentRiskConfig,
    PortfolioRiskConfig,
)
from nifty_trader.safety.guard import DeterministicSafetyGuard


@pytest.fixture
def temp_store(tmp_path):
    db_file = tmp_path / "test_safety_store.db"
    return PaperTradeStore(db_path=db_file)


@pytest.fixture
def safety_guard(temp_store):
    return DeterministicSafetyGuard(store=temp_store)


def test_lot_size_enforcement_1_lot(safety_guard):
    """Verify that only 1 lot is allowed and >= 2 lots are deterministically rejected."""
    # 1 Lot — Valid
    valid_req = PaperTradeOrderRequest(
        symbol="NIFTY",
        expiry="26SEP",
        strike=25000.0,
        option_type=PaperOptionType.CE,
        action=PaperAction.BUY,
        lots=1,
    )
    res_valid = safety_guard.validate_order_request(valid_req)
    assert res_valid.passed is True
    assert valid_req.quantity == 65

    # 2 Lots — Prohibited and rejected
    invalid_req = PaperTradeOrderRequest(
        symbol="NIFTY",
        expiry="26SEP",
        strike=25000.0,
        option_type=PaperOptionType.CE,
        action=PaperAction.BUY,
        lots=2,
    )
    res_invalid = safety_guard.validate_order_request(invalid_req)
    assert res_invalid.passed is False
    assert res_invalid.rejection_code == "EXCESS_LOT_SIZE"
    assert "Exactly 1 lot(s) allowed" in res_invalid.reason


def test_banknifty_lot_size_and_quantity(safety_guard):
    """Verify BANKNIFTY resolves 30 qty for 1 lot and rejects > 1 lot."""
    bn_req = PaperTradeOrderRequest(
        symbol="BANKNIFTY",
        expiry="26SEP",
        strike=54000.0,
        option_type=PaperOptionType.PE,
        action=PaperAction.BUY,
        lots=1,
    )
    assert bn_req.quantity == 30
    res = safety_guard.validate_order_request(bn_req)
    assert res.passed is True


def test_max_trades_per_day_nifty(safety_guard, temp_store):
    """Verify maximum 3 trades per day for NIFTY."""
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Insert 3 executed orders for NIFTY today
    for i in range(3):
        order = PaperTradeOrder(
            request_id=f"req_nifty_{i}",
            idempotency_key=f"idem_nifty_{i}",
            symbol="NIFTY",
            expiry="26SEP",
            strike=25000.0 + i * 50,
            option_type=PaperOptionType.CE,
            action=PaperAction.BUY,
            lots=1,
            quantity=25,
            status=PaperOrderStatus.FILLED,
        )
        temp_store.save_order(order)

    # 4th order should be blocked
    req4 = PaperTradeOrderRequest(
        symbol="NIFTY",
        expiry="26SEP",
        strike=25200.0,
        option_type=PaperOptionType.CE,
        action=PaperAction.BUY,
        lots=1,
    )
    res = safety_guard.validate_order_request(req4, target_date=today_str)
    assert res.passed is False
    assert res.rejection_code == "DAILY_TRADE_LIMIT_REACHED"
    assert "already executed 3 of 3 allowed trades today" in res.reason


def test_max_trades_per_day_banknifty(safety_guard, temp_store):
    """Verify maximum 3 trades per day for BANKNIFTY."""
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Insert 3 executed orders for BANKNIFTY today
    for i in range(3):
        order = PaperTradeOrder(
            request_id=f"req_bn_{i}",
            idempotency_key=f"idem_bn_{i}",
            symbol="BANKNIFTY",
            expiry="26SEP",
            strike=54000.0 + i * 100,
            option_type=PaperOptionType.PE,
            action=PaperAction.BUY,
            lots=1,
            quantity=15,
            status=PaperOrderStatus.FILLED,
        )
        temp_store.save_order(order)

    # 4th order should be blocked
    req4 = PaperTradeOrderRequest(
        symbol="BANKNIFTY",
        expiry="26SEP",
        strike=54500.0,
        option_type=PaperOptionType.PE,
        action=PaperAction.BUY,
        lots=1,
    )
    res = safety_guard.validate_order_request(req4, target_date=today_str)
    assert res.passed is False
    assert res.rejection_code == "DAILY_TRADE_LIMIT_REACHED"
    assert "already executed 3 of 3 allowed trades today" in res.reason


def test_instrument_daily_loss_limit_1000(safety_guard, temp_store):
    """Verify ₹1,000 maximum daily loss limit per instrument (NIFTY)."""
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Record a realized loss of -₹1,000 on NIFTY today
    loss_pos = PaperPosition(
        position_id="pos_loss_1",
        symbol="NIFTY",
        expiry="26SEP",
        strike=25000.0,
        option_type=PaperOptionType.CE,
        action=PaperAction.BUY,
        lots=1,
        quantity=25,
        avg_price=100.0,
        current_ltp=60.0,
        unrealized_pnl=0.0,
        pnl_percentage=-40.0,
        realized_pnl=-1000.0,
        status=PaperPositionStatus.CLOSED,
        first_detected_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        closed_at=datetime.now(timezone.utc),
    )
    temp_store.save_position(loss_pos)

    # Subsequent order on NIFTY must be rejected
    req = PaperTradeOrderRequest(
        symbol="NIFTY",
        expiry="26SEP",
        strike=25100.0,
        option_type=PaperOptionType.CE,
        action=PaperAction.BUY,
        lots=1,
    )
    res = safety_guard.validate_order_request(req, target_date=today_str)
    assert res.passed is False
    assert res.rejection_code == "INSTRUMENT_LOSS_LIMIT_REACHED"
    assert "Cumulative session loss for NIFTY is ₹1,000.00" in res.reason


def test_portfolio_daily_loss_limit_2000(safety_guard, temp_store):
    """Verify ₹2,000 maximum daily loss limit for the overall portfolio."""
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Record two losses totaling -₹2,050
    pos1 = PaperPosition(
        position_id="pos_p1",
        symbol="NIFTY",
        expiry="26SEP",
        strike=25000.0,
        option_type=PaperOptionType.CE,
        action=PaperAction.BUY,
        lots=1,
        quantity=25,
        avg_price=100.0,
        current_ltp=60.0,
        unrealized_pnl=0.0,
        pnl_percentage=-40.0,
        realized_pnl=-950.0,
        status=PaperPositionStatus.CLOSED,
        first_detected_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        closed_at=datetime.now(timezone.utc),
    )
    pos2 = PaperPosition(
        position_id="pos_p2",
        symbol="BANKNIFTY",
        expiry="26SEP",
        strike=54000.0,
        option_type=PaperOptionType.PE,
        action=PaperAction.BUY,
        lots=1,
        quantity=15,
        avg_price=200.0,
        current_ltp=130.0,
        unrealized_pnl=0.0,
        pnl_percentage=-35.0,
        realized_pnl=-1100.0,
        status=PaperPositionStatus.CLOSED,
        first_detected_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        closed_at=datetime.now(timezone.utc),
    )
    temp_store.save_position(pos1)
    temp_store.save_position(pos2)

    # Any new trade should trigger portfolio circuit breaker
    req = PaperTradeOrderRequest(
        symbol="NIFTY",
        expiry="26SEP",
        strike=25000.0,
        option_type=PaperOptionType.CE,
        action=PaperAction.BUY,
        lots=1,
    )
    res = safety_guard.validate_order_request(req, target_date=today_str)
    assert res.passed is False
    assert res.rejection_code == "PORTFOLIO_LOSS_LIMIT_REACHED"
    assert "Portfolio daily loss circuit breaker triggered" in res.reason


def test_single_active_instrument_policy(safety_guard, temp_store):
    """Verify only 1 instrument can be traded at a time."""
    # Open an active position in NIFTY
    open_nifty = PaperPosition(
        position_id="pos_active_nifty",
        symbol="NIFTY",
        expiry="26SEP",
        strike=25000.0,
        option_type=PaperOptionType.CE,
        action=PaperAction.BUY,
        lots=1,
        quantity=25,
        avg_price=120.0,
        current_ltp=125.0,
        unrealized_pnl=125.0,
        pnl_percentage=4.16,
        realized_pnl=0.0,
        status=PaperPositionStatus.OPEN,
        first_detected_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    temp_store.save_position(open_nifty)

    # Attempt to place order in BANKNIFTY while NIFTY is active
    bn_order = PaperTradeOrderRequest(
        symbol="BANKNIFTY",
        expiry="26SEP",
        strike=54000.0,
        option_type=PaperOptionType.PE,
        action=PaperAction.BUY,
        lots=1,
    )
    res = safety_guard.validate_order_request(bn_order)
    assert res.passed is False
    assert res.rejection_code == "SINGLE_INSTRUMENT_BREACH"
    assert "Open position already exists in ['NIFTY']" in res.reason


def test_risk_to_reward_minimum_1_to_3(safety_guard):
    """Verify that trades must satisfy minimum 1:3 Risk-to-Reward ratio."""
    # Scenario A: Entry = 100, Stop Loss = 90 (Risk = 10).
    # Target = 120 (Reward = 20) -> R:R = 1:2.0 -> Must be REJECTED!
    req_sub_rr = PaperTradeOrderRequest(
        symbol="NIFTY",
        expiry="26SEP",
        strike=25000.0,
        option_type=PaperOptionType.CE,
        action=PaperAction.BUY,
        lots=1,
        limit_price=100.0,
        stop_loss_price=90.0,
        target_price=120.0,
    )
    res_sub = safety_guard.validate_order_request(req_sub_rr)
    assert res_sub.passed is False
    assert res_sub.rejection_code == "INSUFFICIENT_RR"
    assert "Proposed trade R:R is 1:2.00, which is below the mandatory minimum 1:3.0" in res_sub.reason

    # Scenario B: Entry = 100, Stop Loss = 90 (Risk = 10).
    # Target = 130 (Reward = 30) -> R:R = 1:3.0 -> Must PASS!
    req_exact_rr = PaperTradeOrderRequest(
        symbol="NIFTY",
        expiry="26SEP",
        strike=25000.0,
        option_type=PaperOptionType.CE,
        action=PaperAction.BUY,
        lots=1,
        limit_price=100.0,
        stop_loss_price=90.0,
        target_price=130.0,
    )
    res_exact = safety_guard.validate_order_request(req_exact_rr)
    assert res_exact.passed is True


@pytest.mark.asyncio
async def test_paper_executor_rejects_violating_order(temp_store):
    """Verify SensibullPaperExecutor rejects order if Safety Guard fails."""
    mock_browser = MagicMock()
    mock_browser.navigate = AsyncMock()
    guard = DeterministicSafetyGuard(store=temp_store)

    executor = SensibullPaperExecutor(
        browser_agent=mock_browser,
        store=temp_store,
        safety_guard=guard,
    )

    # Attempt to execute an order with 3 lots (violating the 1-lot limit)
    violating_req = PaperTradeOrderRequest(
        symbol="NIFTY",
        expiry="26SEP",
        strike=25000.0,
        option_type=PaperOptionType.CE,
        action=PaperAction.BUY,
        lots=3,
    )
    order = await executor.execute_paper_order(violating_req)

    assert order.status == PaperOrderStatus.REJECTED
    assert "SAFETY_GUARD_REJECTION" in order.status_reason
    assert "Exactly 1 lot(s) allowed per trade" in order.status_reason
    # Browser was NOT even navigated because safety guard rejected before external action
    mock_browser.navigate.assert_not_called()
