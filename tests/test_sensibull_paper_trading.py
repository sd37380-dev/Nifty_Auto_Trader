"""
Tests for Stage 8: Sensibull Paper-Trading Execution & State Synchronization Engine.

Validates:
1. Environment detection (Virtual Trading safe vs. Live Broker danger abort)
2. Idempotency and duplicate trade submission prevention
3. DOM & page text position extraction (Strike, Quantity, LTP, P&L)
4. SQLite persistence of orders, positions, and reconciliations
5. Dual-state reconciliation against Sensibull ground truth
6. Order execution and visual verification lifecycle
7. Position square-off / closure
8. Telemetry observation feeds for Hermes and AI Brain
"""

from datetime import datetime, timezone
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from nifty_trader.browser.models import BrowserObservation, SourceType
from nifty_trader.paper.contracts import (
    PaperAction,
    PaperOptionType,
    PaperOrderStatus,
    PaperPortfolioSummary,
    PaperPosition,
    PaperPositionStatus,
    PaperTradeOrder,
    PaperTradeOrderRequest,
    SensibullEnvironmentType,
)
from nifty_trader.paper.environment import (
    SensibullEnvironmentDetector,
    UnsafeTradingEnvironmentError,
)
from nifty_trader.paper.executor import SensibullPaperExecutor
from nifty_trader.paper.navigator import SensibullPaperNavigator
from nifty_trader.paper.position_reader import SensibullPositionReader
from nifty_trader.paper.reconciler import SensibullStateReconciler
from nifty_trader.paper.service import SensibullPaperTradingService
from nifty_trader.paper.store import PaperTradeStore


@pytest.fixture
def temp_store(tmp_path):
    db_file = tmp_path / "test_paper_trades.db"
    return PaperTradeStore(db_path=db_file)


@pytest.fixture
def mock_browser():
    browser = MagicMock()
    mock_obs = BrowserObservation(
        url="https://web.sensibull.com/virtual-trade",
        page_title="Sensibull - Virtual Trading Portfolio",
        source_type=SourceType.GENERAL_WEB,
        visible_text="Sensibull Virtual Portfolio\nVirtual Funds: ₹5,00,000\nTotal Unrealized P&L: ₹1,250.00\nNIFTY 24500 CE 26SEP\nQty: 25\nAvg: 110.00\nLTP: 160.00\nP&L: +₹1,250.00 (+45.4%)",
    )
    browser.navigate = AsyncMock(return_value=mock_obs)
    return browser


# ==============================================================================
# 1. Environment Safety Detection Tests
# ==============================================================================

def test_environment_detects_virtual_trade_safely():
    detector = SensibullEnvironmentDetector()
    env, is_safe, reason = detector.detect(
        url="https://web.sensibull.com/virtual-trade",
        page_title="Virtual Portfolio - Sensibull",
        visible_text="Active Virtual Portfolio\nVirtual Funds: ₹5,00,000\nVirtual Positions",
    )
    assert env == SensibullEnvironmentType.VIRTUAL_TRADE
    assert is_safe is True
    assert "Verified safe Virtual Trading" in reason


def test_environment_detects_live_broker_and_aborts():
    detector = SensibullEnvironmentDetector()
    env, is_safe, reason = detector.detect(
        url="https://web.sensibull.com/orders",
        page_title="Sensibull Live Orders",
        visible_text="Place Real Order with Broker\nSend to Zerodha\nBroker Terminal",
    )
    assert env == SensibullEnvironmentType.LIVE_BROKER
    assert is_safe is False
    assert "CRITICAL SAFETY VIOLATION" in reason

    with pytest.raises(UnsafeTradingEnvironmentError):
        detector.assert_safe_environment(
            url="https://web.sensibull.com/orders",
            page_title="Sensibull Live Orders",
            visible_text="Trade with broker\nSend to Upstox",
        )


def test_environment_detects_login_required():
    detector = SensibullEnvironmentDetector()
    env, is_safe, reason = detector.detect(
        url="https://web.sensibull.com/login",
        page_title="Login - Sensibull",
        visible_text="Please Login to view your options\nLogin with Broker or Continue with Google",
    )
    assert env == SensibullEnvironmentType.LOGIN_REQUIRED
    assert is_safe is False


# ==============================================================================
# 2. Idempotency & Duplicate Prevention Tests
# ==============================================================================

def test_idempotency_key_deterministic():
    req1 = PaperTradeOrderRequest(
        symbol="NIFTY",
        expiry="26SEP2026",
        strike=24500.0,
        option_type=PaperOptionType.CE,
        action=PaperAction.BUY,
        lots=1,
    )
    req2 = PaperTradeOrderRequest(
        symbol="NIFTY",
        expiry="26SEP2026",
        strike=24500.0,
        option_type=PaperOptionType.CE,
        action=PaperAction.BUY,
        lots=1,
    )
    # Different request_id but identical trade parameters
    assert req1.request_id != req2.request_id
    assert req1.idempotency_key == req2.idempotency_key


@pytest.mark.asyncio
async def test_executor_prevents_duplicate_submission(temp_store, mock_browser):
    executor = SensibullPaperExecutor(browser_agent=mock_browser, store=temp_store)

    req = PaperTradeOrderRequest(
        symbol="NIFTY",
        expiry="26SEP2026",
        strike=24500.0,
        option_type=PaperOptionType.CE,
        action=PaperAction.BUY,
        lots=1,
        limit_price=120.0,
    )

    # First submission
    order1 = await executor.execute_paper_order(req)
    assert order1.status in [PaperOrderStatus.OPEN, PaperOrderStatus.FILLED]

    # Second submission with same parameters
    order2 = await executor.execute_paper_order(req)
    assert order2.order_id == order1.order_id
    assert order2.idempotency_key == order1.idempotency_key


# ==============================================================================
# 3. Position Reader & DOM Parsing Tests
# ==============================================================================

def test_position_reader_parses_positions_and_pnl():
    reader = SensibullPositionReader()
    text = (
        "Sensibull Virtual Trading\n"
        "Total Unrealized P&L: ₹2,450.00\n"
        "Total Realized P&L: ₹1,000.00\n"
        "NIFTY 24600 CE 26SEP\n"
        "Qty: 50\n"
        "Avg: ₹120.00\n"
        "LTP: ₹169.00\n"
        "P&L: +₹2,450.00 (+40.8%)\n"
    )
    summary = reader.parse_portfolio(text)

    assert summary.is_safe_environment is True
    assert summary.total_unrealized_pnl == 2450.00
    assert summary.total_realized_pnl == 1000.00
    assert summary.net_pnl == 3450.00
    assert len(summary.positions) == 1

    pos = summary.positions[0]
    assert pos.strike == 24600.0
    assert pos.option_type == PaperOptionType.CE
    assert pos.quantity == 50
    assert pos.lots == 2
    assert pos.avg_price == 120.00
    assert pos.current_ltp == 169.00


def test_position_reader_empty_portfolio():
    reader = SensibullPositionReader()
    text = "Sensibull Virtual Trading\nNo active virtual positions found.\nStart adding trades."
    summary = reader.parse_portfolio(text)

    assert summary.total_positions == 0
    assert summary.open_positions_count == 0
    assert summary.total_unrealized_pnl == 0.0


# ==============================================================================
# 4. SQLite Persistence & Reconciler Tests
# ==============================================================================

def test_store_orders_and_positions_persistence(temp_store):
    order = PaperTradeOrder(
        request_id="req_test_1",
        idempotency_key="hash_abc_123",
        symbol="NIFTY",
        expiry="26SEP",
        strike=24500.0,
        option_type=PaperOptionType.CE,
        action=PaperAction.BUY,
        lots=1,
        quantity=25,
        entry_price=150.0,
        status=PaperOrderStatus.OPEN,
    )
    temp_store.save_order(order)

    fetched_order = temp_store.get_order_by_idempotency_key("hash_abc_123")
    assert fetched_order is not None
    assert fetched_order.strike == 24500.0
    assert fetched_order.status == PaperOrderStatus.OPEN

    pos = PaperPosition(
        position_id="pos_test_1",
        symbol="NIFTY",
        expiry="26SEP",
        strike=24500.0,
        option_type=PaperOptionType.CE,
        action=PaperAction.BUY,
        lots=1,
        quantity=25,
        avg_price=150.0,
        current_ltp=165.0,
        unrealized_pnl=375.0,
        status=PaperPositionStatus.OPEN,
    )
    temp_store.save_position(pos)

    open_positions = temp_store.get_open_positions()
    assert len(open_positions) == 1
    assert open_positions[0].position_id == "pos_test_1"


def test_reconciler_synchronizes_state(temp_store):
    reconciler = SensibullStateReconciler(temp_store)

    # 1. Store a local position
    local_pos = PaperPosition(
        position_id="pos_local_1",
        symbol="NIFTY",
        expiry="26SEP",
        strike=24500.0,
        option_type=PaperOptionType.CE,
        action=PaperAction.BUY,
        lots=1,
        quantity=25,
        avg_price=100.0,
        current_ltp=100.0,
        status=PaperPositionStatus.OPEN,
    )
    temp_store.save_position(local_pos)

    # Remote summary where local position has updated LTP
    remote_pos = PaperPosition(
        position_id="pos_remote_1",
        symbol="NIFTY",
        expiry="26SEP",
        strike=24500.0,
        option_type=PaperOptionType.CE,
        action=PaperAction.BUY,
        lots=1,
        quantity=25,
        avg_price=100.0,
        current_ltp=135.0,
        unrealized_pnl=875.0,
        status=PaperPositionStatus.OPEN,
    )
    remote_summary = PaperPortfolioSummary(
        environment=SensibullEnvironmentType.VIRTUAL_TRADE,
        is_safe_environment=True,
        positions=[remote_pos],
    )

    reconciled, discrepancies = reconciler.reconcile(remote_summary)
    assert len(reconciled) == 1
    assert reconciled[0].current_ltp == 135.0
    assert reconciled[0].unrealized_pnl == 875.0

    # 2. Remote summary with empty positions (local position closed externally)
    empty_remote = PaperPortfolioSummary(
        environment=SensibullEnvironmentType.VIRTUAL_TRADE,
        is_safe_environment=True,
        positions=[],
    )
    reconciled_after, discrepancies_after = reconciler.reconcile(empty_remote)
    assert len(temp_store.get_open_positions()) == 0
    assert len(discrepancies_after) == 1
    assert discrepancies_after[0].discrepancy_type == "MISSING_REMOTE"


# ==============================================================================
# 5. Service Facade & Position Square-Off Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_paper_trading_service_lifecycle(temp_store, mock_browser):
    service = SensibullPaperTradingService(browser_agent=mock_browser, store=temp_store)

    # 1. Execute paper order
    req = PaperTradeOrderRequest(
        symbol="NIFTY",
        expiry="26SEP2026",
        strike=24500.0,
        option_type=PaperOptionType.CE,
        action=PaperAction.BUY,
        lots=1,
        limit_price=150.0,
    )
    order = await service.execute_trade(req)
    assert order.status in [PaperOrderStatus.OPEN, PaperOrderStatus.FILLED]

    # 2. Check open positions
    open_positions = temp_store.get_open_positions()
    assert len(open_positions) == 1
    pos_id = open_positions[0].position_id

    # 3. Close position (square-off)
    success, closed_pos = await service.close_position(pos_id, reason="Test take profit")
    assert success is True
    assert closed_pos.status == PaperPositionStatus.CLOSED

    # Verify no open positions remain
    assert len(temp_store.get_open_positions()) == 0


@pytest.mark.asyncio
async def test_paper_observation_telemetry_generation(temp_store, mock_browser):
    service = SensibullPaperTradingService(browser_agent=mock_browser, store=temp_store)

    # Put a position in store
    pos = PaperPosition(
        position_id="pos_telemetry_1",
        symbol="NIFTY",
        expiry="26SEP",
        strike=24700.0,
        option_type=PaperOptionType.PE,
        action=PaperAction.BUY,
        lots=2,
        quantity=50,
        avg_price=120.0,
        current_ltp=140.0,
        unrealized_pnl=1000.0,
        status=PaperPositionStatus.OPEN,
    )
    temp_store.save_position(pos)

    obs = await service.get_paper_observation()
    assert obs.has_open_position is True
    assert obs.net_exposure_lots == 2
    assert obs.unrealized_pnl == 1000.0
    assert len(obs.open_positions) == 1
