"""
Unit tests for Package 5 WaitPolicy and WakeConditionEvaluator.
"""

from datetime import datetime, timedelta, timezone
import pytest

from nifty_trader.autonomous.contracts import (
    AutonomousLimits,
    WaitReason,
    WakeCondition,
    WakeConditionType,
)
from nifty_trader.autonomous.wait_policy import WaitPolicy
from nifty_trader.autonomous.wake_conditions import WakeConditionEvaluator, WakeConditionFactory
from nifty_trader.brain.contracts import (
    BrainFailure,
    BrainOutput,
    Confidence,
    Direction,
    MarketContext,
    MarketRegime,
    ObservationRequest,
    ReasoningState,
    ReasoningSummary,
)
from nifty_trader.contracts.models import (
    CandleObservation,
    CanonicalObservationStatus,
    NumericalObservation,
    UnifiedMarketObservation,
    VisualObservation,
)


def _make_dummy_brain_output(state: ReasoningState, obs_requests=None) -> BrainOutput:
    return BrainOutput(
        brain_request_id="breq_test_123",
        observation_id="umo_test_123",
        reasoning_state=state,
        market_context=MarketContext(
            regime=MarketRegime.RANGING,
            regime_confidence=Confidence(value=0.75, basis=["test"]),
            summary="Market in range",
        ),
        observation_requests=obs_requests or [],
        confidence=Confidence(value=0.70, basis=["test"]),
        reasoning_summary=ReasoningSummary(
            context="Testing wait policy",
            interpretation="Waiting for next candle",
        ),
    )


def test_wait_policy_wait_state_next_candle():
    policy = WaitPolicy()
    # 10:07 UTC -> Next 15M candle close is 10:15 UTC
    ref_time = datetime(2026, 9, 27, 10, 7, 0, tzinfo=timezone.utc)
    brain_out = _make_dummy_brain_output(ReasoningState.WAIT)

    decision = policy.formulate_decision(brain_output=brain_out, current_time=ref_time)

    assert decision.should_wait is True
    assert decision.reason == WaitReason.NEXT_CANDLE
    # Earliest wake should be at 10:15 UTC
    assert decision.earliest_wake_at == datetime(2026, 9, 27, 10, 15, 0, tzinfo=timezone.utc)

    # Check candle condition is included
    candle_conds = [c for c in decision.wake_conditions if c.type == WakeConditionType.CANDLE_COMPLETION]
    assert len(candle_conds) == 1
    assert candle_conds[0].timeframe == "15M"


def test_wait_policy_watch_state():
    policy = WaitPolicy()
    ref_time = datetime(2026, 9, 27, 10, 7, 0, tzinfo=timezone.utc)
    brain_out = _make_dummy_brain_output(ReasoningState.WATCH)

    decision = policy.formulate_decision(brain_output=brain_out, current_time=ref_time)

    assert decision.should_wait is True
    assert decision.reason in (WaitReason.STRUCTURAL_CHANGE, WaitReason.NEXT_CANDLE)
    assert len(decision.wake_conditions) >= 2


def test_wait_policy_no_trade_state():
    policy = WaitPolicy()
    ref_time = datetime(2026, 9, 27, 10, 7, 0, tzinfo=timezone.utc)
    brain_out = _make_dummy_brain_output(ReasoningState.NO_TRADE)

    decision = policy.formulate_decision(brain_output=brain_out, current_time=ref_time)

    # NO_TRADE must not permanently stop session; it should wait for next candle/event
    assert decision.should_wait is True
    assert decision.earliest_wake_at > ref_time


def test_wait_policy_candidate_halts():
    policy = WaitPolicy()
    brain_out = _make_dummy_brain_output(ReasoningState.CANDIDATE)

    decision = policy.formulate_decision(brain_output=brain_out)

    # CANDIDATE must not schedule another wait; should_wait is False
    assert decision.should_wait is False
    assert "Candidate" in decision.explanation


def test_wait_policy_brain_failure_exponential_backoff():
    limits = AutonomousLimits(min_wait_seconds=5.0, max_wait_seconds=60.0)
    policy = WaitPolicy(limits)
    ref_time = datetime(2026, 9, 27, 10, 0, 0, tzinfo=timezone.utc)

    failure = BrainFailure(
        schema_version="1.0",
        brain_request_id="breq_fail",
        observation_id="obs_1",
        code="PROVIDER_UNAVAILABLE",
        message="Model quota exhausted",
        retryable=True,
    )

    # Attempt 1: 5s * 2^0 = 5s
    d1 = policy.formulate_decision(failure=failure, consecutive_failures=0, current_time=ref_time)
    assert d1.should_wait is True
    assert d1.reason == WaitReason.BRAIN_UNAVAILABLE
    assert (d1.earliest_wake_at - ref_time).total_seconds() == 5.0

    # Attempt 2: 5s * 2^1 = 10s
    d2 = policy.formulate_decision(failure=failure, consecutive_failures=1, current_time=ref_time)
    assert (d2.earliest_wake_at - ref_time).total_seconds() == 10.0

    # Attempt 3: 5s * 2^2 = 20s
    d3 = policy.formulate_decision(failure=failure, consecutive_failures=2, current_time=ref_time)
    assert (d3.earliest_wake_at - ref_time).total_seconds() == 20.0


def test_wake_condition_evaluator_time():
    now = datetime(2026, 9, 27, 10, 15, 0, tzinfo=timezone.utc)
    scheduled = datetime(2026, 9, 27, 10, 15, 0, tzinfo=timezone.utc)
    cond = WakeCondition(
        type=WakeConditionType.TIME,
        scheduled_at=scheduled,
        reason="Time reached",
    )

    is_met, _ = WakeConditionEvaluator.evaluate(cond, current_time=now)
    assert is_met is True

    # Earlier than scheduled
    earlier = datetime(2026, 9, 27, 10, 14, 59, tzinfo=timezone.utc)
    is_met_early, _ = WakeConditionEvaluator.evaluate(cond, current_time=earlier)
    assert is_met_early is False


def test_wake_condition_evaluator_price_change():
    cond = WakeCondition(
        type=WakeConditionType.PRICE_CHANGE,
        threshold=0.001,  # 0.1%
        scheduled_at=datetime.now(timezone.utc),
        reason="Price change",
        metadata={"reference_price": 25000.0},
    )

    # 1. Price moved to 25030 (+0.12% >= 0.10%)
    c15 = CandleObservation(
        timeframe="15M",
        timestamp=datetime.now(timezone.utc),
        open=25000.0,
        high=25035.0,
        low=24995.0,
        close=25030.0,
    )
    obs = UnifiedMarketObservation(
        numerical=NumericalObservation(candles_15m=[c15]),
    )

    is_met, reason = WakeConditionEvaluator.evaluate(cond, current_time=datetime.now(timezone.utc), latest_observation=obs)
    assert is_met is True
    assert "Price moved" in reason

    # 2. Minor price move to 25005 (+0.02% < 0.10%)
    c15_small = CandleObservation(
        timeframe="15M",
        timestamp=datetime.now(timezone.utc),
        open=25000.0,
        high=25010.0,
        low=24995.0,
        close=25005.0,
    )
    obs_small = UnifiedMarketObservation(
        numerical=NumericalObservation(candles_15m=[c15_small]),
    )
    is_met_small, _ = WakeConditionEvaluator.evaluate(cond, current_time=datetime.now(timezone.utc), latest_observation=obs_small)
    assert is_met_small is False


def test_wake_condition_evaluator_manual_instruction():
    cond = WakeCondition(
        type=WakeConditionType.MANUAL_INSTRUCTION,
        scheduled_at=datetime.now(timezone.utc),
        reason="Manual instruction",
    )

    # No instructions
    is_met, _ = WakeConditionEvaluator.evaluate(cond, current_time=datetime.now(timezone.utc), new_instructions_count=0)
    assert is_met is False

    # 1 new instruction
    is_met_new, reason = WakeConditionEvaluator.evaluate(cond, current_time=datetime.now(timezone.utc), new_instructions_count=1)
    assert is_met_new is True
    assert "1 new operator instruction" in reason
