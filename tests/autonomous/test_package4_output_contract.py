"""
Unit tests for Specification 52A: Explicit Package 4 Output Contract & Invariants.
"""

from datetime import datetime, timezone
from pathlib import Path
import pytest
from unittest.mock import AsyncMock, MagicMock

from nifty_trader.autonomous.contracts import (
    AutonomousState,
    Package4OutputContractValidator,
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
    TimeframeAssessment,
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


def _make_valid_brain_output(state: ReasoningState = ReasoningState.WAIT, candidate=None) -> BrainOutput:
    tf_1h = TimeframeAssessment(
        timeframe="1H",
        summary="1H structural context",
        directional_context=Direction.NEUTRAL,
    )
    tf_15m = TimeframeAssessment(
        timeframe="15M",
        summary="15M tactical state",
        directional_context=Direction.NEUTRAL,
    )
    return BrainOutput(
        brain_request_id="breq_52a_test",
        observation_id="umo_52a_test",
        reasoning_state=state,
        market_context=MarketContext(
            regime=MarketRegime.RANGING,
            regime_confidence=Confidence(value=0.75, basis=["test"]),
            summary="Market in range",
        ),
        timeframe_assessments=[tf_1h, tf_15m],
        candidate=candidate,
        confidence=Confidence(value=0.70, basis=["test"]),
        reasoning_summary=ReasoningSummary(context="Testing 52A", interpretation="Wait"),
    )


# ==============================================================================
# Invariant Validation Tests (Section 52A.9)
# ==============================================================================

def test_validator_candidate_with_candidate_valid():
    cand = TradeCandidate(
        direction=Direction.LONG,
        thesis="Breakout",
        market_context="Bullish",
        reasoning_confidence=Confidence(value=0.8, basis=["test"]),
    )
    out = _make_valid_brain_output(state=ReasoningState.CANDIDATE, candidate=cand)
    is_valid, err = Package4OutputContractValidator.validate(out)
    assert is_valid is True
    assert err is None


def test_validator_candidate_without_candidate_invalid():
    out = _make_valid_brain_output(state=ReasoningState.CANDIDATE, candidate=None)
    is_valid, err = Package4OutputContractValidator.validate(out)
    assert is_valid is False
    assert "reasoning_state == CANDIDATE requires candidate != None" in err


def test_validator_wait_with_candidate_invalid():
    cand = TradeCandidate(
        direction=Direction.LONG,
        thesis="Breakout",
        market_context="Bullish",
        reasoning_confidence=Confidence(value=0.8, basis=["test"]),
    )
    out = _make_valid_brain_output(state=ReasoningState.WAIT, candidate=cand)
    is_valid, err = Package4OutputContractValidator.validate(out)
    assert is_valid is False
    assert "forbids non-null candidate" in err


def test_validator_watch_with_candidate_invalid():
    cand = TradeCandidate(
        direction=Direction.SHORT,
        thesis="Breakdown",
        market_context="Bearish",
        reasoning_confidence=Confidence(value=0.8, basis=["test"]),
    )
    out = _make_valid_brain_output(state=ReasoningState.WATCH, candidate=cand)
    is_valid, err = Package4OutputContractValidator.validate(out)
    assert is_valid is False
    assert "forbids non-null candidate" in err


def test_validator_developing_with_candidate_invalid():
    cand = TradeCandidate(
        direction=Direction.LONG,
        thesis="Breakout",
        market_context="Bullish",
        reasoning_confidence=Confidence(value=0.8, basis=["test"]),
    )
    out = _make_valid_brain_output(state=ReasoningState.DEVELOPING, candidate=cand)
    is_valid, err = Package4OutputContractValidator.validate(out)
    assert is_valid is False
    assert "forbids non-null candidate" in err


def test_validator_no_trade_with_candidate_invalid():
    cand = TradeCandidate(
        direction=Direction.NEUTRAL,
        thesis="None",
        market_context="Chop",
        reasoning_confidence=Confidence(value=0.5, basis=["test"]),
    )
    out = _make_valid_brain_output(state=ReasoningState.NO_TRADE, candidate=cand)
    is_valid, err = Package4OutputContractValidator.validate(out)
    assert is_valid is False
    assert "forbids non-null candidate" in err


def test_validator_missing_timeframe_assessment_invalid():
    # Only 1H assessment, missing 15M
    tf_1h = TimeframeAssessment(timeframe="1H", summary="1H", directional_context=Direction.NEUTRAL)
    out = BrainOutput(
        brain_request_id="breq_1",
        observation_id="umo_1",
        reasoning_state=ReasoningState.WAIT,
        market_context=MarketContext(
            regime=MarketRegime.RANGING,
            regime_confidence=Confidence(value=0.75, basis=["test"]),
            summary="summary",
        ),
        timeframe_assessments=[tf_1h],
        confidence=Confidence(value=0.70, basis=["test"]),
        reasoning_summary=ReasoningSummary(context="c", interpretation="i"),
    )
    is_valid, err = Package4OutputContractValidator.validate(out)
    assert is_valid is False
    assert "both 1H and 15M timeframe assessments are required" in err


# ==============================================================================
# Engine Execution Tests with Spec 52A Enforcements
# ==============================================================================

def _setup_engine(brain_result: BrainResult, tmp_path: Path):
    storage = AutonomousStorage(db_path=tmp_path / "test_52a.db")
    clock = FakeClock(datetime(2026, 9, 25, 5, 0, 0, tzinfo=timezone.utc))

    mock_runtime = MagicMock()
    sess_mgr = MagicMock(spec=MarketSessionManager)
    sess_mgr.get_current_session_status.return_value = MarketSessionStatus.OPEN
    sess_mgr.get_session_status.return_value = MarketSessionStatus.OPEN
    mock_runtime.market_service = MagicMock()
    mock_runtime.market_service.session_manager = sess_mgr

    c15 = CandleObservation(
        timeframe="15M",
        timestamp=datetime(2026, 9, 25, 5, 0, tzinfo=timezone.utc),
        open=25000.0,
        high=25010.0,
        low=24990.0,
        close=25005.0,
    )
    obs = UnifiedMarketObservation(
        observation_id="umo_52a_test",
        observed_at=datetime(2026, 9, 25, 5, 0, tzinfo=timezone.utc),
        numerical=NumericalObservation(candles_15m=[c15]),
        visual=VisualObservation(),
    )
    mock_runtime.get_unified_market_observation = AsyncMock(return_value=obs)
    mock_runtime.reason_market = AsyncMock(return_value=brain_result)

    return AutonomousObservationEngine(
        runtime=mock_runtime,
        clock=clock,
        storage=storage,
    )


@pytest.mark.asyncio
async def test_engine_contract_violation_enters_error_state(tmp_path: Path):
    # Model returns CANDIDATE but candidate is None (Invariant violation)
    bad_output = _make_valid_brain_output(state=ReasoningState.CANDIDATE, candidate=None)
    result = BrainResult(success=True, output=bad_output, failure=None)

    engine = _setup_engine(result, tmp_path)
    cycle_res = await engine.run_single_cycle()

    # Must enter ERROR state rather than silently accepting bad output
    assert cycle_res.success is False
    assert cycle_res.state == AutonomousState.ERROR
    assert engine.current_state == AutonomousState.ERROR
    assert "requires candidate != None" in cycle_res.failure


@pytest.mark.asyncio
async def test_engine_non_retryable_failure_enters_error_state(tmp_path: Path):
    # Non-retryable contract error
    failure = BrainFailure(
        schema_version="1.0",
        brain_request_id="breq_1",
        observation_id="umo_1",
        code="CONTRACT_ERROR",
        message="Fatal schema validation failure",
        retryable=False,
    )
    result = BrainResult(success=False, output=None, failure=failure)

    engine = _setup_engine(result, tmp_path)
    cycle_res = await engine.run_single_cycle()

    # Non-retryable failure enters ERROR immediately
    assert cycle_res.success is False
    assert cycle_res.state == AutonomousState.ERROR
    assert engine.current_state == AutonomousState.ERROR


@pytest.mark.asyncio
async def test_engine_retryable_failure_enters_waiting_state(tmp_path: Path):
    # Retryable provider error
    failure = BrainFailure(
        schema_version="1.0",
        brain_request_id="breq_1",
        observation_id="umo_1",
        code="PROVIDER_UNAVAILABLE",
        message="Rate limit 429",
        retryable=True,
    )
    result = BrainResult(success=False, output=None, failure=failure)

    engine = _setup_engine(result, tmp_path)
    cycle_res = await engine.run_single_cycle()

    # Retryable failure enters WAITING state with backoff
    assert cycle_res.success is False
    assert cycle_res.state == AutonomousState.WAITING
    assert engine.current_state == AutonomousState.WAITING
    assert cycle_res.next_wait.reason == WaitReason.BRAIN_UNAVAILABLE
