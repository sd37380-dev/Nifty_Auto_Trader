"""
Tests for Stage 9: Autonomous Trade Monitoring & Position Management.

Validates:
1. Position detection and thesis preservation from PaperTradeStore.
2. Position-aware BrainContext compilation (Section 10 Open Position Context).
3. Meaningful change gating (skips redundant LLM calls when price/P&L unchanged).
4. AI Brain reassessment dispatch and actions (CONTINUE, WAIT, WATCH, CLOSE).
5. Automated position square-off execution via Stage 8 SensibullPaperTradingService.
6. SQLite persistence of monitoring records, lifecycle state transitions, and audit events.
7. Dual-state reconciliation with remote Sensibull ground truth.
8. Full runtime integration and status reporting.
"""

from datetime import datetime, timezone
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from nifty_trader.brain.context.compiler import BrainContextCompiler
from nifty_trader.brain.contracts import (
    BrainInput,
    BrainOutput,
    BrainResult,
    Confidence,
    Direction,
    MarketContext,
    MarketRegime,
    OpenPositionContext,
    PositionManagementAction,
    ReasoningState,
    ReasoningSummary,
    TimeframeAssessment,
)
from nifty_trader.contracts.builder import UnifiedObservationBuilder
from nifty_trader.contracts.models import (
    CandleObservation,
    CanonicalObservationStatus,
    UnifiedMarketObservation,
)
from nifty_trader.market_data.models import Candle, Timeframe
from nifty_trader.monitoring.context_builder import PositionMonitoringContextBuilder
from nifty_trader.monitoring.contracts import (
    MonitoringState,
    PositionEvent,
    PositionMonitoringRecord,
)
from nifty_trader.monitoring.orchestrator import AutonomousPositionMonitor
from nifty_trader.monitoring.store import PositionMonitoringStore
from nifty_trader.paper.contracts import (
    PaperAction,
    PaperOptionType,
    PaperOrderStatus,
    PaperPortfolioSummary,
    PaperPosition,
    PaperPositionStatus,
    PaperTradeOrder,
    PaperTradeOrderRequest,
    ReconciliationDiscrepancy,
    SensibullEnvironmentType,
)
from nifty_trader.paper.service import SensibullPaperTradingService
from nifty_trader.paper.store import PaperTradeStore


@pytest.fixture
def temp_stores(tmp_path):
    paper_db = tmp_path / "test_paper.db"
    mon_db = tmp_path / "test_monitoring.db"
    return PaperTradeStore(paper_db), PositionMonitoringStore(mon_db)


@pytest.fixture
def sample_position():
    return PaperPosition(
        position_id="pos_nifty_25300ce_001",
        trade_id="order_12345",
        symbol="NIFTY",
        expiry="26SEP",
        strike=25300.0,
        option_type=PaperOptionType.CE,
        lots=1,
        quantity=25,
        avg_price=120.0,
        current_ltp=135.0,
        unrealized_pnl=375.0,
        pnl_percentage=12.5,
        status=PaperPositionStatus.OPEN,
        first_detected_at=datetime.now(timezone.utc),
        last_synced_at=datetime.now(timezone.utc),
    )


@pytest.fixture
def sample_observation():
    now = datetime.now(timezone.utc)
    c1h = [
        Candle(timeframe=Timeframe.H1, timestamp=now, open=25300.0, high=25350.0, low=25280.0, close=25340.0, volume=50000.0, is_closed=True)
    ]
    c15m = [
        Candle(timeframe=Timeframe.M15, timestamp=now, open=25320.0, high=25350.0, low=25310.0, close=25340.0, volume=12000.0, is_closed=True)
    ]
    builder = UnifiedObservationBuilder()
    return builder.build(symbol="NIFTY", h1_candles=c1h, m15_candles=c15m)


def make_mock_brain_output(
    action: PositionManagementAction,
    state: ReasoningState = ReasoningState.WAIT,
    summary: str = "Thesis intact",
) -> BrainOutput:
    return BrainOutput(
        schema_version="1.0",
        brain_request_id="breq_test_001",
        observation_id="obs_test_001",
        reasoning_state=state,
        position_action=action,
        market_context=MarketContext(
            regime=MarketRegime.RANGING,
            regime_confidence=Confidence(value=0.8, basis=["Consolidation structure"]),
            structures=[],
            summary="Market consolidating near support",
        ),
        timeframe_assessments=[
            TimeframeAssessment(timeframe="1H", summary="1H bullish structure", directional_context=Direction.LONG),
            TimeframeAssessment(timeframe="15M", summary="15M pullback", directional_context=Direction.LONG),
        ],
        confidence=Confidence(value=0.8, basis=["Thesis aligned"]),
        reasoning_summary=ReasoningSummary(
            context="NIFTY position monitoring",
            interpretation=summary,
        ),
    )


def test_monitoring_store_lifecycle(temp_stores):
    _, mon_store = temp_stores

    record = PositionMonitoringRecord(
        position_id="pos_test_1",
        trade_id="trade_1",
        symbol="NIFTY",
        strike=25300.0,
        option_type="CE",
        lots=1,
        quantity=25,
        entry_price=120.0,
        current_price=130.0,
        unrealized_pnl=250.0,
        pnl_percentage=8.33,
        holding_duration_minutes=15.0,
        monitoring_state=MonitoringState.MONITORING,
        brain_position_action=PositionManagementAction.CONTINUE,
        brain_summary="Trend remains supportive above 25300.",
    )
    mon_store.save_record(record)

    records = mon_store.list_records(limit=10)
    assert len(records) == 1
    assert records[0].position_id == "pos_test_1"
    assert records[0].unrealized_pnl == 250.0
    assert records[0].brain_position_action == PositionManagementAction.CONTINUE

    # Test event logging
    event = PositionEvent(
        event_type="test-event",
        position_id="pos_test_1",
        details={"note": "verification pass"},
    )
    mon_store.save_event(event)

    events = mon_store.get_events_for_position("pos_test_1")
    assert len(events) == 1
    assert events[0].event_type == "test-event"
    assert events[0].details["note"] == "verification pass"


def test_position_context_builder_and_compiler(temp_stores, sample_position, sample_observation):
    paper_store, _ = temp_stores

    # Seed an order to verify historical thesis preservation
    order = PaperTradeOrder(
        order_id="order_12345",
        request_id="req_12345",
        idempotency_key="idemp_12345",
        symbol="NIFTY",
        expiry="26SEP",
        strike=25300.0,
        option_type=PaperOptionType.CE,
        action=PaperAction.BUY,
        lots=1,
        quantity=25,
        status=PaperOrderStatus.FILLED,
        entry_price=120.0,
        status_reason="Breakout above 25300 consolidation with rising volume",
    )
    paper_store.save_order(order)

    builder = PositionMonitoringContextBuilder(paper_store)
    brain_input = builder.build_context(
        position=sample_position,
        observation=sample_observation,
    )

    assert brain_input.task == "POSITION_REASSESSMENT"
    assert brain_input.open_position_context is not None
    ctx = brain_input.open_position_context
    assert ctx.position_id == sample_position.position_id
    assert ctx.strike == 25300.0
    assert ctx.lots == 1
    assert ctx.entry_price == 120.0
    assert ctx.current_price == 135.0
    assert ctx.unrealized_pnl == 375.0
    assert "Breakout above 25300" in ctx.opening_candidate_thesis

    # Verify context compiler renders Section 10
    compiler = BrainContextCompiler()
    compiled = compiler.compile(brain_input)
    assert compiled["open_position_context"] is not None
    pos_text = compiled["open_position_context"]
    assert "NIFTY 25300.0 CE" in pos_text
    assert "Rs. 120.00" in pos_text
    assert "Rs. 135.00" in pos_text
    assert "+375.00" in pos_text
    assert "Breakout above 25300" in pos_text


@pytest.mark.asyncio
async def test_meaningful_change_gating(temp_stores, sample_position, sample_observation):
    paper_store, mon_store = temp_stores
    paper_store.save_position(sample_position)

    mock_service = MagicMock(spec=SensibullPaperTradingService)
    mock_service.store = paper_store
    mock_service.sync_and_reconcile = AsyncMock(return_value=(MagicMock(), []))

    mock_brain = MagicMock()
    mock_brain.analyze = AsyncMock(return_value=BrainResult(
        success=True,
        output=make_mock_brain_output(
            action=PositionManagementAction.CONTINUE,
            summary="Position thesis intact, hold above 25320",
        ),
    ))

    monitor = AutonomousPositionMonitor(
        paper_service=mock_service,
        brain_engine=mock_brain,
        paper_store=paper_store,
        monitoring_store=mon_store,
    )

    # First run: no prior assessment -> triggers brain
    records1 = await monitor.monitor_once(force_reassessment=False)
    assert len(records1) == 1
    assert records1[0].monitoring_state == MonitoringState.MONITORING
    assert records1[0].brain_position_action == PositionManagementAction.CONTINUE
    assert mock_brain.analyze.call_count == 1

    # Second run immediately: price unchanged (135.0 -> 135.0) -> gated, AI Brain skipped
    records2 = await monitor.monitor_once(force_reassessment=False)
    assert len(records2) == 1
    assert records2[0].monitoring_state == MonitoringState.WAITING
    assert "No meaningful change" in records2[0].wake_reason
    assert mock_brain.analyze.call_count == 1  # Unchanged!

    # Third run with force_reassessment=True -> triggers brain again
    records3 = await monitor.monitor_once(force_reassessment=True)
    assert len(records3) == 1
    assert mock_brain.analyze.call_count == 2


@pytest.mark.asyncio
async def test_reassessment_close_action_executes_squareoff(temp_stores, sample_position):
    paper_store, mon_store = temp_stores
    paper_store.save_position(sample_position)

    closed_pos = sample_position.model_copy()
    closed_pos.status = PaperPositionStatus.CLOSED
    closed_pos.realized_pnl = 450.0

    mock_service = MagicMock(spec=SensibullPaperTradingService)
    mock_service.store = paper_store
    mock_service.sync_and_reconcile = AsyncMock(return_value=(MagicMock(), []))
    mock_service.close_position = AsyncMock(return_value=(True, closed_pos))

    mock_brain = MagicMock()
    mock_brain.analyze = AsyncMock(return_value=BrainResult(
        success=True,
        output=make_mock_brain_output(
            action=PositionManagementAction.CLOSE,
            state=ReasoningState.NO_TRADE,
            summary="Thesis invalidated: 15M broke lower with heavy volume",
        ),
    ))

    monitor = AutonomousPositionMonitor(
        paper_service=mock_service,
        brain_engine=mock_brain,
        paper_store=paper_store,
        monitoring_store=mon_store,
    )

    records = await monitor.monitor_once(force_reassessment=True)
    assert len(records) == 1
    rec = records[0]
    assert rec.monitoring_state == MonitoringState.CLOSED
    assert rec.brain_position_action == PositionManagementAction.CLOSE
    assert rec.action_executed == "CLOSE_POSITION"
    assert "Realized P&L: Rs. +450.00" in rec.action_result

    # Verify Stage 8 square-off was called
    mock_service.close_position.assert_called_once_with(
        position_id=sample_position.position_id,
        reason="Thesis invalidated: 15M broke lower with heavy volume",
    )

    # Verify event trail
    events = mon_store.get_events_for_position(sample_position.position_id)
    event_types = [e.event_type for e in events]
    assert "position-close-requested" in event_types
    assert "position-closed" in event_types


@pytest.mark.asyncio
async def test_reassessment_wait_action(temp_stores, sample_position):
    paper_store, mon_store = temp_stores
    paper_store.save_position(sample_position)

    mock_service = MagicMock(spec=SensibullPaperTradingService)
    mock_service.store = paper_store
    mock_service.sync_and_reconcile = AsyncMock(return_value=(MagicMock(), []))
    mock_service.close_position = AsyncMock()

    mock_brain = MagicMock()
    mock_brain.analyze = AsyncMock(return_value=BrainResult(
        success=True,
        output=make_mock_brain_output(
            action=PositionManagementAction.WAIT,
            state=ReasoningState.WAIT,
            summary="Wait for 1H candle close before adjusting trailing stop",
        ),
    ))

    monitor = AutonomousPositionMonitor(
        paper_service=mock_service,
        brain_engine=mock_brain,
        paper_store=paper_store,
        monitoring_store=mon_store,
    )

    records = await monitor.monitor_once(force_reassessment=True)
    assert len(records) == 1
    assert records[0].monitoring_state == MonitoringState.WAITING
    assert records[0].brain_position_action == PositionManagementAction.WAIT
    # Ensure close was NOT called
    mock_service.close_position.assert_not_called()


@pytest.mark.asyncio
async def test_dual_state_reconciliation_resolves_discrepancies(temp_stores, sample_position):
    paper_store, mon_store = temp_stores
    paper_store.save_position(sample_position)

    discrepancy = ReconciliationDiscrepancy(
        discrepancy_type="MISSING_REMOTE",
        hermes_state={"position_id": sample_position.position_id},
        sensibull_state=None,
        resolution_action="Mark position CLOSED locally as it does not exist on Sensibull",
    )

    mock_service = MagicMock(spec=SensibullPaperTradingService)
    mock_service.store = paper_store
    mock_service.sync_and_reconcile = AsyncMock(return_value=(MagicMock(), [discrepancy]))

    monitor = AutonomousPositionMonitor(
        paper_service=mock_service,
        brain_engine=MagicMock(),
        paper_store=paper_store,
        monitoring_store=mon_store,
    )

    summary, discrepancies = await monitor.reconcile_positions()
    assert len(discrepancies) == 1
    assert discrepancies[0].discrepancy_type == "MISSING_REMOTE"

    events = mon_store.get_events_for_position(sample_position.position_id)
    assert len(events) == 1
    assert events[0].event_type == "reconciliation-resolved"
    assert "Mark position CLOSED" in events[0].details["action"]


@pytest.mark.asyncio
async def test_reassessment_watch_action(temp_stores, sample_position):
    paper_store, mon_store = temp_stores
    paper_store.save_position(sample_position)

    mock_service = MagicMock(spec=SensibullPaperTradingService)
    mock_service.store = paper_store
    mock_service.sync_and_reconcile = AsyncMock(return_value=(MagicMock(), []))
    mock_service.close_position = AsyncMock()

    mock_brain = MagicMock()
    mock_brain.analyze = AsyncMock(return_value=BrainResult(
        success=True,
        output=make_mock_brain_output(
            action=PositionManagementAction.WATCH,
            state=ReasoningState.WATCH,
            summary="Watch 25300 support closely for potential reversal",
        ),
    ))

    monitor = AutonomousPositionMonitor(
        paper_service=mock_service,
        brain_engine=mock_brain,
        paper_store=paper_store,
        monitoring_store=mon_store,
    )

    records = await monitor.monitor_once(force_reassessment=True)
    assert len(records) == 1
    assert records[0].monitoring_state == MonitoringState.MONITORING
    assert records[0].brain_position_action == PositionManagementAction.WATCH
    mock_service.close_position.assert_not_called()


@pytest.mark.asyncio
async def test_reassessment_brain_failure_handling(temp_stores, sample_position):
    paper_store, mon_store = temp_stores
    paper_store.save_position(sample_position)

    mock_service = MagicMock(spec=SensibullPaperTradingService)
    mock_service.store = paper_store
    mock_service.sync_and_reconcile = AsyncMock(return_value=(MagicMock(), []))
    mock_service.close_position = AsyncMock()

    from nifty_trader.brain.contracts import BrainFailure
    mock_brain = MagicMock()
    mock_brain.analyze = AsyncMock(return_value=BrainResult(
        success=False,
        failure=BrainFailure(
            brain_request_id="breq_fail_001",
            observation_id="obs_fail_001",
            code="TIMEOUT",
            message="Model provider timeout during position reassessment",
            retryable=True,
        ),
    ))

    monitor = AutonomousPositionMonitor(
        paper_service=mock_service,
        brain_engine=mock_brain,
        paper_store=paper_store,
        monitoring_store=mon_store,
    )

    records = await monitor.monitor_once(force_reassessment=True)
    assert len(records) == 1
    assert records[0].monitoring_state == MonitoringState.MONITORING
    assert "timeout" in records[0].error.lower()
    # Ensure no rogue order closure occurred
    mock_service.close_position.assert_not_called()


@pytest.mark.asyncio
async def test_runtime_stage9_wiring():
    from nifty_trader.core.runtime import NiftyTraderRuntime
    runtime = NiftyTraderRuntime()
    assert hasattr(runtime, "position_monitor")
    assert hasattr(runtime, "monitoring_store")
    assert runtime.position_monitor is not None
    assert runtime.monitoring_store is not None

    status = await runtime.get_status()
    assert "monitoring" in status
    assert "open_monitored_positions" in status["monitoring"]
    assert "total_records" in status["monitoring"]
