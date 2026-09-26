"""
Tests for Brain Output Validators and Hallucination Defense.
"""

import pytest

from nifty_trader.brain.contracts import (
    BoundedConfidence,
    BrainReasoningOutput,
    CandidateDirection,
    MarketRegime,
    SetupState,
    TradeCandidate,
)
from nifty_trader.brain.validators import BrainOutputValidator


def test_validator_detects_and_neutralizes_prohibited_execution_directives():
    validator = BrainOutputValidator()

    # Attempt to inject prohibited execution directive
    output = BrainReasoningOutput(
        observation_id="obs_val_test",
        regime=MarketRegime.TRENDING_UP,
        regime_confidence=0.9,
        regime_evidence=["Bullish breakout"],
        one_hour_interpretation="Bullish trend",
        fifteen_minute_interpretation="Buy now at market open",  # PROHIBITED!
        multi_source_synthesis="Aligns across sources",
        current_state=SetupState.CANDIDATE,
        state_rationale="Great setup",
        next_observation_needed="Next candle",
        confidence=BoundedConfidence(value=0.85, basis=["Trend"]),
        auditable_summary="Breakout seen.",
    )

    sanitized = validator.validate_and_sanitize(output)

    # State must be demoted to WAIT and rationale updated
    assert sanitized.current_state == SetupState.WAIT
    assert "SAFETY DEMOTION" in sanitized.state_rationale
    assert sanitized.candidate_thesis is None


def test_validator_neutralizes_active_candidate_thesis_in_wait_state():
    validator = BrainOutputValidator()

    candidate = TradeCandidate(
        direction=CandidateDirection.LONG,
        thesis="Breakout thesis",
        market_context="Bullish context",
        uncertainty="Impending economic release",
        reasoning_confidence=0.8,
    )

    output = BrainReasoningOutput(
        observation_id="obs_val_test2",
        regime=MarketRegime.RANGING,
        regime_confidence=0.5,
        regime_evidence=["Range bound"],
        one_hour_interpretation="No clear trend",
        fifteen_minute_interpretation="Chop",
        multi_source_synthesis="Mixed signals",
        current_state=SetupState.WAIT,  # WAIT state
        state_rationale="Conditions not ripe",
        next_observation_needed="Wait for break",
        candidate_thesis=candidate,
        confidence=BoundedConfidence(value=0.5, basis=["Mixed"]),
        auditable_summary="Wait for clarity.",
    )

    sanitized = validator.validate_and_sanitize(output)

    # For WAIT state, candidate direction must be neutralized
    assert sanitized.current_state == SetupState.WAIT
    assert sanitized.candidate_thesis.direction == CandidateDirection.NEUTRAL
