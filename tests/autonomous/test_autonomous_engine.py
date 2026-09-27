"""
Unit tests for Package 5 AutonomousObservationEngine integration and lifecycle.
"""

import asyncio
from datetime import datetime, timezone
from pathlib import Path
import pytest
from unittest.mock import AsyncMock, MagicMock

from nifty_trader.autonomous.contracts import (
    AutonomousLimits,
    AutonomousState,
    WaitReason,
)
from nifty_trader.autonomous.engine import AutonomousObservationEngine
from nifty_trader.autonomous.persistence import AutonomousStorage
from nifty_trader.autonomous.scheduler import FakeClock
from nifty_trader.brain.contracts import (
    BrainFailure,
    BrainOutput,
    BrainResult,
    Confidence,
    Direction,
    MarketContext,
    MarketRegime,
    ObservationRequest,
    ReasoningState,
    ReasoningSummary,
    TradeCandidate,
)
from nifty_trader.contracts.models import (
    CandleObservation,
    CanonicalObservationStatus,
    NumericalObservation,
    UnifiedMarketObservation,
    VisualObservation,
)
from nifty_trader.market_data.models import MarketSessionStatus
from nifty_trader.market_data.session import MarketSessionManager


def _create_mock_runtime(market_status: MarketSessionStatus = MarketSessionStatus.OPEN):
    mock = MagicMock()

    # Session Manager
    sess_mgr = MagicMock(spec=MarketSessionManager)
    sess_mgr.get_current_session_status.return_value = market_status
    sess_mgr.get_session_status.return_value = market_status
    sess_mgr.get_session_times.return_value = {
        "pre_market_start": datetime(2026, 9, 25, 3, 30, tzinfo=timezone.utc),
        "market_open": datetime(2026, 9, 25, 3, 45, tzinfo=timezone.utc),
        "market_close": datetime(2026, 9, 25, 10, 0, tzinfo=timezone.utc),
        "post_market_close": datetime(2026, 9, 25, 10, 30, tzinfo=timezone.utc),
    }
    mock.market_service = MagicMock()
    mock.market_service.session_manager = sess_mgr

    # Market observation builder
    def get_obs(**kwargs):
        c15 = CandleObservation(
            timeframe="15M",
            timestamp=datetime(2026, 9, 25, 5, 0, tzinfo=timezone.utc),
            open=25000.0,
            high=25010.0,
            low=24990.0,
            close=25005.0,
        )
        return UnifiedMarketObservation(
            observation_id="umo_test_auto_1",
            observed_at=datetime(2026, 9, 25, 5, 0, tzinfo=timezone.utc),
            numerical=NumericalObservation(candles_15m=[c15]),
            visual=VisualObservation(),
        )

    mock.get_unified_market_observation = AsyncMock(side_effect=get_obs)

    # Brain reasoning result default
    def get_brain_result(**kwargs):
        out = BrainOutput(
            brain_request_id="breq_mock_1",
            observation_id="umo_test_auto_1",
            reasoning_state=ReasoningState.WAIT,
            market_context=MarketContext(
                regime=MarketRegime.RANGING,
                regime_confidence=Confidence(value=0.8, basis=["test"]),
                summary="Consolidating near 25000",
            ),
            observation_requests=[],
            confidence=Confidence(value=0.75, basis=["test"]),
            reasoning_summary=ReasoningSummary(
                context="Waiting for 15M breakout confirmation",
                interpretation="Wait",
            ),
        )
        return BrainResult(success=True, output=out, failure=None)

    mock.reason_market = AsyncMock(side_effect=get_brain_result)
    return mock


@pytest.mark.asyncio
async def test_engine_single_cycle_wait(tmp_path: Path):
    storage = AutonomousStorage(db_path=tmp_path / "test_auto.db")
    # Friday 10:30 IST (05:00 UTC)
    clock = FakeClock(datetime(2026, 9, 25, 5, 0, 0, tzinfo=timezone.utc))
    runtime = _create_mock_runtime()

    engine = AutonomousObservationEngine(
        runtime=runtime,
        clock=clock,
        storage=storage,
    )

    # Run one cycle
    await engine.start(symbol="NIFTY", run_once=True)

    assert engine.current_state == AutonomousState.WAITING
    status = engine.get_status()
    assert status["status"] == "WAITING"
    assert status["cycles_completed"] == 1
    assert status["model_calls"] == 1
    assert status["wait_reason"] == "NEXT_CANDLE"

    # Verify SQLite persistence
    cycles = storage.list_cycles()
    assert len(cycles) == 1
    assert cycles[0].resulting_state == AutonomousState.WAITING


@pytest.mark.asyncio
async def test_engine_candidate_stops_loop(tmp_path: Path):
    storage = AutonomousStorage(db_path=tmp_path / "test_candidate.db")
    clock = FakeClock(datetime(2026, 9, 25, 5, 0, 0, tzinfo=timezone.utc))
    runtime = _create_mock_runtime()

    # Override brain to return CANDIDATE
    cand = TradeCandidate(
        candidate_id="cand_test_99",
        direction=Direction.LONG,
        thesis="Breakout above 25050 on high volume",
        market_context="Bullish momentum",
        reasoning_confidence=Confidence(value=0.85, basis=["test"]),
    )
    cand_output = BrainOutput(
        brain_request_id="breq_cand_1",
        observation_id="umo_cand_1",
        reasoning_state=ReasoningState.CANDIDATE,
        market_context=MarketContext(
            regime=MarketRegime.TRENDING_UP,
            regime_confidence=Confidence(value=0.85, basis=["test"]),
            summary="Uptrend intact",
        ),
        candidate=cand,
        confidence=Confidence(value=0.85, basis=["test"]),
        reasoning_summary=ReasoningSummary(context="Candidate ready", interpretation="Long candidate"),
    )
    runtime.reason_market = AsyncMock(return_value=BrainResult(success=True, output=cand_output, failure=None))

    engine = AutonomousObservationEngine(
        runtime=runtime,
        clock=clock,
        storage=storage,
    )

    result = await engine.run_single_cycle()

    # Cycle halts at CANDIDATE_READY
    assert result.state == AutonomousState.CANDIDATE_READY
    assert engine.current_state == AutonomousState.CANDIDATE_READY
    assert result.next_wait.should_wait is False
    assert result.brain_output.candidate is not None
    assert result.brain_output.candidate.direction == Direction.LONG


@pytest.mark.asyncio
async def test_engine_user_stop_has_highest_priority(tmp_path: Path):
    storage = AutonomousStorage(db_path=tmp_path / "test_stop.db")
    clock = FakeClock(datetime(2026, 9, 25, 5, 0, 0, tzinfo=timezone.utc))
    runtime = _create_mock_runtime()

    engine = AutonomousObservationEngine(
        runtime=runtime,
        clock=clock,
        storage=storage,
    )

    await engine.start(symbol="NIFTY", run_once=True)
    assert engine.current_state == AutonomousState.WAITING

    # Issue STOP command
    await engine.stop(reason="Operator emergency stop")
    assert engine.current_state == AutonomousState.STOPPED
    assert engine.is_running is False


@pytest.mark.asyncio
async def test_engine_pause_and_resume(tmp_path: Path):
    storage = AutonomousStorage(db_path=tmp_path / "test_pause.db")
    clock = FakeClock(datetime(2026, 9, 25, 5, 0, 0, tzinfo=timezone.utc))
    runtime = _create_mock_runtime()

    engine = AutonomousObservationEngine(
        runtime=runtime,
        clock=clock,
        storage=storage,
    )

    await engine.start(symbol="NIFTY", run_once=True)
    assert engine.current_state == AutonomousState.WAITING

    await engine.pause("Temporary maintenance")
    assert engine.current_state == AutonomousState.SESSION_PAUSED

    await engine.resume("Maintenance complete")
    assert engine.current_state == AutonomousState.WAITING


@pytest.mark.asyncio
async def test_engine_brain_failure_safe_backoff(tmp_path: Path):
    storage = AutonomousStorage(db_path=tmp_path / "test_fail.db")
    clock = FakeClock(datetime(2026, 9, 25, 5, 0, 0, tzinfo=timezone.utc))
    runtime = _create_mock_runtime()

    # Model failure
    failure = BrainFailure(
        schema_version="1.0",
        brain_request_id="breq_fail",
        observation_id="umo_fail",
        code="MODEL_ERROR",
        message="Gemini API timeout",
        retryable=True,
    )
    runtime.reason_market = AsyncMock(return_value=BrainResult(success=False, output=None, failure=failure))

    engine = AutonomousObservationEngine(
        runtime=runtime,
        clock=clock,
        storage=storage,
    )

    result = await engine.run_single_cycle()

    assert result.success is False
    assert result.state == AutonomousState.WAITING
    assert engine.current_state == AutonomousState.WAITING
    assert result.next_wait.reason == WaitReason.RETRY_BACKOFF
    # No fabricated output
    assert result.brain_output is None
