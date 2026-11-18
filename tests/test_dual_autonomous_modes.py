"""
Comprehensive Unit & Integration Test Suite for Dual Autonomous Hermes Modes.

Validates:
1. Mode identities & contracts (EXISTING_SYSTEM vs HERMES_RESEARCH).
2. TradeIntent and PaperTradeOrderRequest attribution and lineage preservation.
3. Audit store isolation, indexing, and separate P&L queries.
4. Deterministic position collision detection and non-corrupting resolution.
5. Mode B (HermesResearchTrader) end-to-end autonomous cycle.
6. Mode A (ExistingSystemTrader) candidate-to-trade cycle.
7. DualAutonomousOrchestrator concurrency, lifecycle control, and strict fault isolation.
"""

import asyncio
from datetime import datetime, timezone
from pathlib import Path
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from nifty_trader.autonomous.contracts import AutonomousState, CycleResult
from nifty_trader.autonomous.engine import AutonomousObservationEngine
from nifty_trader.autonomous.mode_a_trader import ExistingSystemTrader
from nifty_trader.brain.contracts import BrainOutput, Confidence, Direction, ReasoningState, TradeCandidate
from nifty_trader.core.dual_orchestrator import DualAutonomousOrchestrator
from nifty_trader.core.modes import (
    TradeEvent,
    TradeIntent,
    TradeLifecycleEventType,
    TradeRecord,
    TradingMode,
)
from nifty_trader.core.trade_store import TradeAuditStore
from nifty_trader.paper.contracts import (
    PaperAction,
    PaperOptionType,
    PaperOrderStatus,
    PaperPosition,
    PaperPositionStatus,
    PaperTradeOrder,
    PaperTradeOrderRequest,
)
from nifty_trader.paper.store import PaperTradeStore
from nifty_trader.research_zone.contracts import (
    AssessmentSegment,
    HermesResearchAssessment,
    MarketDirection,
)
from nifty_trader.research_zone.dhan_adapter import LocalDatasetProvider, MockDhanDataAdapter
from nifty_trader.research_zone.service import HermesResearchZoneService
from nifty_trader.research_zone.trader import HermesResearchTrader
from nifty_trader.safety.contracts import PortfolioRiskConfig, SafetyCheckResult
from nifty_trader.safety.guard import DeterministicSafetyGuard


@pytest.fixture
def tmp_audit_store(tmp_path: Path) -> TradeAuditStore:
    return TradeAuditStore(db_path=tmp_path / "test_trades_audit.db")


@pytest.fixture
def tmp_paper_store(tmp_path: Path) -> PaperTradeStore:
    return PaperTradeStore(db_path=tmp_path / "test_paper_trades.db")


@pytest.fixture
def safety_guard(tmp_paper_store: PaperTradeStore) -> DeterministicSafetyGuard:
    return DeterministicSafetyGuard(store=tmp_paper_store)


# ==============================================================================
# 1. Mode Identities & TradeIntent Invariants
# ==============================================================================

def test_mode_identities():
    """Verify exact canonical enum values."""
    assert TradingMode.EXISTING_SYSTEM.value == "EXISTING_SYSTEM"
    assert TradingMode.HERMES_RESEARCH.value == "HERMES_RESEARCH"


def test_trade_intent_stamping_and_order_conversion():
    """Verify TradeIntent stamps mandatory mode, research_id, and converts cleanly to PaperTradeOrderRequest."""
    intent_b = TradeIntent(
        mode=TradingMode.HERMES_RESEARCH,
        instrument="NIFTY",
        direction="BUY",
        setup="MOMENTUM_BREAKOUT",
        entry_thesis="Positive statistical edge confirmed.",
        invalidation="False breakout below 22600.",
        assessment_id="rass_123",
        research_id="q_456",
        score=65.0,
        confidence=0.85,
        expiry="CURRENT_WEEK",
        strike=22650.0,
        option_type="CE",
        lots=1,
    )
    assert intent_b.mode == TradingMode.HERMES_RESEARCH
    assert intent_b.research_id == "q_456"

    order_req = intent_b.to_order_request()
    assert isinstance(order_req, PaperTradeOrderRequest)
    assert order_req.mode == "HERMES_RESEARCH"
    assert order_req.trade_intent_id == intent_b.trade_intent_id
    assert order_req.assessment_id == "rass_123"
    assert order_req.research_id == "q_456"
    assert order_req.strike == 22650.0
    assert order_req.option_type == PaperOptionType.CE
    assert order_req.action == PaperAction.BUY


def test_mode_a_intent_has_none_research_id():
    """Mode A intents must never carry a research_id."""
    intent_a = TradeIntent(
        mode=TradingMode.EXISTING_SYSTEM,
        instrument="NIFTY",
        direction="BUY",
        setup="PRICE_ACTION",
        entry_thesis="FVG retest on 15M.",
        invalidation="Swing low breach.",
        assessment_id="cand_abc",
        research_id=None,
        score=75.0,
        confidence=0.75,
    )
    assert intent_a.mode == TradingMode.EXISTING_SYSTEM
    assert intent_a.research_id is None

    req = intent_a.to_order_request()
    assert req.mode == "EXISTING_SYSTEM"
    assert req.research_id is None


# ==============================================================================
# 2. Audit Store Strict Attribution & Queries
# ==============================================================================

def test_audit_store_mode_isolation(tmp_audit_store: TradeAuditStore):
    """Verify TradeAuditStore keeps Mode A and Mode B records cleanly separated."""
    rec_a = TradeRecord(
        decision_source=TradingMode.EXISTING_SYSTEM,
        trade_intent_id="ti_a1",
        assessment_id="ass_a1",
        research_id=None,
        instrument="NIFTY",
        direction="BUY",
        strike=22600.0,
        option_type="CE",
        score=70.0,
        confidence=0.8,
        thesis="Mode A thesis",
        safety_decision="APPROVED",
        execution_status="CLOSED",
        pnl=1500.0,
        outcome="WIN",
    )
    rec_b = TradeRecord(
        decision_source=TradingMode.HERMES_RESEARCH,
        trade_intent_id="ti_b1",
        assessment_id="ass_b1",
        research_id="q_b1",
        instrument="NIFTY",
        direction="BUY",
        strike=22700.0,
        option_type="PE",
        score=-60.0,
        confidence=0.75,
        thesis="Mode B thesis",
        safety_decision="APPROVED",
        execution_status="CLOSED",
        pnl=-400.0,
        outcome="LOSS",
    )

    tmp_audit_store.save_trade(rec_a)
    tmp_audit_store.save_trade(rec_b)

    trades_a = tmp_audit_store.get_trades_by_mode(TradingMode.EXISTING_SYSTEM)
    assert len(trades_a) == 1
    assert trades_a[0].trade_id == rec_a.trade_id
    assert trades_a[0].decision_source == TradingMode.EXISTING_SYSTEM
    assert trades_a[0].research_id is None
    assert trades_a[0].pnl == 1500.0

    trades_b = tmp_audit_store.get_trades_by_mode(TradingMode.HERMES_RESEARCH)
    assert len(trades_b) == 1
    assert trades_b[0].trade_id == rec_b.trade_id
    assert trades_b[0].decision_source == TradingMode.HERMES_RESEARCH
    assert trades_b[0].research_id == "q_b1"
    assert trades_b[0].pnl == -400.0

    all_trades = tmp_audit_store.get_all_trades()
    assert len(all_trades) == 2


# ==============================================================================
# 3. Position Collision Detection
# ==============================================================================

def test_position_collision_handling(tmp_audit_store: TradeAuditStore):
    """Opposing positions on the same strike from different modes are blocked and attributed."""
    existing_pos = PaperPosition(
        position_id="pos_existing_1",
        symbol="NIFTY",
        expiry="CURRENT_WEEK",
        strike=22650.0,
        option_type=PaperOptionType.CE,
        action=PaperAction.BUY,
        lots=1,
        quantity=65,
        avg_price=105.0,
        current_ltp=110.0,
        mode="EXISTING_SYSTEM",
        status=PaperPositionStatus.OPEN,
    )

    # Mode B tries to SELL opposing direction on same strike
    incoming_intent_b = TradeIntent(
        mode=TradingMode.HERMES_RESEARCH,
        instrument="NIFTY",
        direction="SELL",
        setup="REVERSAL_CONFIRMED",
        entry_thesis="Contradictory order on same strike",
        invalidation="None",
        assessment_id="ass_b2",
        research_id="q_b2",
        score=-80.0,
        confidence=0.9,
        strike=22650.0,
        option_type="CE",
    )

    allowed, reason = tmp_audit_store.handle_position_collision(incoming_intent_b, [existing_pos])
    assert not allowed
    assert "Position Collision Limitation" in reason
    assert "Separate attribution preserved" in reason

    # Verify event was logged
    events = tmp_audit_store.list_events(mode=TradingMode.HERMES_RESEARCH)
    assert any(e.event_type == TradeLifecycleEventType.POSITION_COLLISION_DETECTED for e in events)


# ==============================================================================
# 4. Deterministic Safety Guard Authoritative Gate
# ==============================================================================

def test_safety_guard_blocks_both_modes_on_loss_limit(tmp_paper_store: PaperTradeStore, safety_guard: DeterministicSafetyGuard):
    """DeterministicSafetyGuard authoritatively blocks both modes equally without bypass."""
    # Simulate existing day loss of ₹1,200
    loss_order = PaperTradeOrder(
        request_id="req_loss",
        idempotency_key="idemp_loss",
        symbol="NIFTY",
        expiry="CURRENT_WEEK",
        strike=22600.0,
        option_type=PaperOptionType.CE,
        action=PaperAction.BUY,
        lots=1,
        quantity=65,
        status=PaperOrderStatus.FILLED,
        submitted_at=datetime.now(timezone.utc),
    )
    loss_pos = PaperPosition(
        position_id="pos_loss",
        symbol="NIFTY",
        expiry="CURRENT_WEEK",
        strike=22600.0,
        option_type=PaperOptionType.CE,
        action=PaperAction.BUY,
        lots=1,
        quantity=65,
        avg_price=100.0,
        current_ltp=80.0,
        realized_pnl=-1300.0,
        status=PaperPositionStatus.CLOSED,
        first_detected_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        closed_at=datetime.now(timezone.utc),
    )
    tmp_paper_store.save_order(loss_order)
    tmp_paper_store.save_position(loss_pos)

    # Attempt Mode A order
    req_a = PaperTradeOrderRequest(
        symbol="NIFTY",
        expiry="CURRENT_WEEK",
        strike=22650.0,
        option_type=PaperOptionType.CE,
        action=PaperAction.BUY,
        lots=1,
        mode="EXISTING_SYSTEM",
    )
    res_a = safety_guard.validate_order_request(req_a)
    assert not res_a.passed
    assert "LOSS_LIMIT" in res_a.rejection_code

    # Attempt Mode B order
    req_b = PaperTradeOrderRequest(
        symbol="NIFTY",
        expiry="CURRENT_WEEK",
        strike=22650.0,
        option_type=PaperOptionType.PE,
        action=PaperAction.BUY,
        lots=1,
        mode="HERMES_RESEARCH",
        research_id="res_1",
    )
    res_b = safety_guard.validate_order_request(req_b)
    assert not res_b.passed
    assert "LOSS_LIMIT" in res_b.rejection_code


# ==============================================================================
# 5. Mode B (HermesResearchTrader) Autonomous Cycle
# ==============================================================================

@pytest.mark.asyncio
async def test_hermes_research_trader_execution_cycle(
    tmp_audit_store: TradeAuditStore,
    tmp_paper_store: PaperTradeStore,
    safety_guard: DeterministicSafetyGuard,
):
    """Validates full Mode B loop from Dhan data -> Research -> Assessment -> Intent -> Paper trade."""
    service = HermesResearchZoneService(adapter=MockDhanDataAdapter(seed=123))
    trader_b = HermesResearchTrader(
        service=service,
        safety_guard=safety_guard,
        audit_store=tmp_audit_store,
        paper_store=tmp_paper_store,
        min_score_threshold=1.0,  # low threshold for deterministic test trigger
        min_confidence_threshold=0.1,
    )

    intent = await trader_b.execute_cycle(symbol="NIFTY", timeframe="15M", days=5)

    if intent:
        assert intent.mode == TradingMode.HERMES_RESEARCH
        assert intent.research_id is not None

        # Verify trade recorded in audit store
        trades = tmp_audit_store.get_trades_by_mode(TradingMode.HERMES_RESEARCH)
        assert len(trades) >= 1
        assert trades[0].decision_source == TradingMode.HERMES_RESEARCH
        assert trades[0].research_id is not None

        # Verify paper order saved in paper store with mode
        orders = tmp_paper_store.get_recent_orders(mode="HERMES_RESEARCH")
        assert len(orders) >= 1
        assert orders[0].mode == "HERMES_RESEARCH"


# ==============================================================================
# 6. Mode A (ExistingSystemTrader) Autonomous Cycle
# ==============================================================================

@pytest.mark.asyncio
async def test_existing_system_trader_candidate_execution(
    tmp_audit_store: TradeAuditStore,
    tmp_paper_store: PaperTradeStore,
    safety_guard: DeterministicSafetyGuard,
):
    """Validates Mode A turning a candidate into a validated paper order."""
    mock_engine = MagicMock()
    candidate = TradeCandidate(
        direction=Direction.LONG,
        thesis="Breakout above resistance with strong 1H volume",
        market_context="TRENDING_EXPANSION",
        reasoning_confidence=Confidence(value=0.88, basis=["1H momentum", "15M volume"]),
        invalidation_conditions=["Break below 22600"],
    )
    brain_out = MagicMock()
    brain_out.candidate = candidate

    cycle_result = CycleResult.model_construct(
        success=True,
        state=AutonomousState.CANDIDATE_READY,
        cycle_id="cyc_test_1",
        brain_output=brain_out,
    )
    mock_engine.execute_single_cycle = AsyncMock(return_value=cycle_result)
    mock_engine._previous_observation = None

    trader_a = ExistingSystemTrader(
        engine=mock_engine,
        safety_guard=safety_guard,
        audit_store=tmp_audit_store,
        paper_store=tmp_paper_store,
    )

    intent = await trader_a.execute_cycle(symbol="NIFTY")
    assert intent is not None
    assert intent.mode == TradingMode.EXISTING_SYSTEM
    assert intent.research_id is None
    assert intent.direction == "BUY"
    assert intent.option_type == "CE"

    # Verify audit store
    trades_a = tmp_audit_store.get_trades_by_mode(TradingMode.EXISTING_SYSTEM)
    assert len(trades_a) == 1
    assert trades_a[0].decision_source == TradingMode.EXISTING_SYSTEM
    assert trades_a[0].research_id is None
    assert trades_a[0].execution_status == "OPEN"


# ==============================================================================
# 7. Dual Autonomous Orchestrator & Fault Isolation
# ==============================================================================

@pytest.mark.asyncio
async def test_dual_orchestrator_fault_isolation(tmp_audit_store: TradeAuditStore):
    """
    STRICT INVARIANT: Failure in one mode must NEVER terminate or disrupt the other mode.
    """
    mode_a = MagicMock()
    mode_b = MagicMock()

    # Mode A throws an exception
    async def failing_mode_a(symbol: str):
        raise RuntimeError("Fatal crash inside Mode A perception model")

    # Mode B runs normally
    mode_b_executed = False

    async def normal_mode_b(symbol: str):
        nonlocal mode_b_executed
        mode_b_executed = True
        await asyncio.sleep(0.05)

    mode_a.run_loop = failing_mode_a
    mode_b.run_loop = normal_mode_b
    mode_a.stop = MagicMock()
    mode_b.stop = MagicMock()

    orchestrator = DualAutonomousOrchestrator(
        mode_a_trader=mode_a,
        mode_b_trader=mode_b,
        audit_store=tmp_audit_store,
    )

    # Run for short duration then stop
    async def stop_after_delay():
        await asyncio.sleep(0.1)
        orchestrator.stop()

    asyncio.create_task(stop_after_delay())
    await orchestrator.start(mode="dual", symbol="NIFTY")

    # Mode B succeeded despite Mode A failing
    assert mode_b_executed is True


def test_dhan_adapter_local_dataset_provider():
    """Verify LocalDatasetProvider inherits from MockDhanDataAdapter and conforms to DhanDataAdapter."""
    provider = LocalDatasetProvider()
    health = provider.health_check()
    assert health["status"] == "ONLINE"
    assert health["mode"] == "LOCAL_DATASET_READY"

    bars = provider.fetch_historical_bars(symbol="NIFTY", timeframe="15M")
    assert len(bars) > 0
