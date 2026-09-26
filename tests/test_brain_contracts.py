"""
Tests for Package 4 Brain Contracts and Domain Models.
"""

from datetime import datetime, timezone
import pytest
from pydantic import ValidationError as PydanticValidationError

from nifty_trader.brain.contracts import (
    BoundedConfidence,
    BrainReasoningOutput,
    CandidateDirection,
    MarketHypothesis,
    MarketRegime,
    ObservationRequest,
    Scenario,
    SetupState,
    TradeCandidate,
    Uncertainty,
    UncertaintyType,
)


def test_brain_contract_enums():
    assert MarketRegime.TRENDING_UP.value == "TRENDING_UP"
    assert MarketRegime.RANGING.value == "RANGING"
    assert SetupState.WAIT.value == "WAIT"
    assert SetupState.NO_TRADE.value == "NO_TRADE"
    assert SetupState.WATCH.value == "WATCH"
    assert SetupState.CANDIDATE.value == "CANDIDATE"
    assert CandidateDirection.LONG.value == "LONG"


def test_bounded_confidence_validation():
    conf = BoundedConfidence(value=0.85, basis=["1H trend alignment", "Volume surge"])
    assert conf.value == 0.85
    assert len(conf.basis) == 2

    # Out of bounds should raise ValidationError
    with pytest.raises(PydanticValidationError):
        BoundedConfidence(value=1.5, basis=["Invalid"])

    with pytest.raises(PydanticValidationError):
        BoundedConfidence(value=-0.1, basis=["Invalid"])


def test_trade_candidate_non_executable_defaults():
    cand = TradeCandidate(
        direction=CandidateDirection.LONG,
        thesis="Breakout above 25000 consolidation range",
        market_context="Strong bullish 1H impulse with ascending 15M structure",
        setup_conditions=["15M close above 25050", "PCR > 1.10"],
        confirmation_conditions=["Volume expansion on breakout"],
        invalidation_conditions=["15M close below 24950"],
        uncertainty="Impending RBI interest rate announcement",
        reasoning_confidence=0.75,
    )
    assert cand.direction == CandidateDirection.LONG
    assert "position_size" in cand.required_downstream_information
    assert "approval_engine_signoff" in cand.required_downstream_information


def test_brain_reasoning_output_serialization():
    output = BrainReasoningOutput(
        observation_id="obs_test_123",
        regime=MarketRegime.RANGING,
        regime_confidence=0.8,
        regime_evidence=["Price bouncing between 24800 and 25100"],
        one_hour_interpretation="Consolidating near 50-day moving average",
        fifteen_minute_interpretation="Contracting within symmetrical triangle",
        multi_source_synthesis="TradingView shows resistance at 25100; Sensibull shows heavy call writing at 25100 strike.",
        current_state=SetupState.WAIT,
        state_rationale="Awaiting structural breakout from 24800-25100 corridor before forming thesis.",
        next_observation_needed="Observe 15M candle close relative to 25100 resistance.",
        confidence=BoundedConfidence(value=0.7, basis=["Multi-source alignment"]),
        auditable_summary="Market is in a well-defined range. Zero trades recommended.",
    )
    assert output.schema_version == "1.0"
    assert output.current_state == SetupState.WAIT
    assert output.candidate_thesis is None

    json_str = output.model_dump_json()
    reloaded = BrainReasoningOutput.model_validate_json(json_str)
    assert reloaded.observation_id == "obs_test_123"
    assert reloaded.regime == MarketRegime.RANGING
