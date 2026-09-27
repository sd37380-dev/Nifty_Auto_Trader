"""
Tests for Package 4 Canonical Brain Domain Models and Exact Contracts.
"""

from datetime import datetime, timezone
import pytest
from pydantic import ValidationError as PydanticValidationError

from nifty_trader.brain.contracts import (
    PACKAGE4_SCHEMA_VERSION,
    BrainFailure,
    BrainInput,
    BrainOutput,
    BrainRecord,
    BrainResult,
    BrainState,
    Confidence,
    Direction,
    EvidenceType,
    MarketContext,
    MarketHypothesis,
    MarketRegime,
    ObservationReference,
    ObservationRequest,
    ReasoningState,
    ReasoningSummary,
    Scenario,
    SetupCondition,
    Severity,
    StructureType,
    TimeframeAssessment,
    TradeCandidate,
    Uncertainty,
    UncertaintyType,
)
from nifty_trader.contracts.models import (
    CandleObservation,
    CanonicalObservationStatus,
    NumericalObservation,
    SourceStatus,
    UnifiedMarketObservation,
    VisualObservation,
)


def test_brain_contract_enums():
    assert MarketRegime.TRENDING_UP.value == "TRENDING_UP"
    assert StructureType.BREAKOUT_ATTEMPT.value == "BREAKOUT_ATTEMPT"
    assert ReasoningState.WAIT.value == "WAIT"
    assert ReasoningState.NO_TRADE.value == "NO_TRADE"
    assert ReasoningState.WATCH.value == "WATCH"
    assert ReasoningState.CANDIDATE.value == "CANDIDATE"
    assert Direction.LONG.value == "LONG"
    assert Direction.NEUTRAL.value == "NEUTRAL"
    assert EvidenceType.OBSERVATION.value == "OBSERVATION"
    assert UncertaintyType.SOURCE_CONFLICT.value == "SOURCE_CONFLICT"
    assert Severity.HIGH.value == "HIGH"


def test_confidence_validation():
    conf = Confidence(value=0.85, basis=["1H trend alignment", "Volume surge"])
    assert conf.value == 0.85
    assert len(conf.basis) == 2

    # Out of bounds should raise ValidationError
    with pytest.raises(PydanticValidationError):
        Confidence(value=1.5, basis=["Invalid"])

    with pytest.raises(PydanticValidationError):
        Confidence(value=-0.1, basis=["Invalid"])


def test_trade_candidate_non_executable_defaults():
    cand = TradeCandidate(
        candidate_id="cand_test_01",
        direction=Direction.LONG,
        thesis="Breakout above 25000 consolidation range",
        market_context="Strong bullish 1H impulse with ascending 15M structure",
        setup_conditions=[
            SetupCondition(
                condition_id="c1",
                description="15M close above 25050",
                timeframe="15M",
                required=True,
                evidence_required=True,
                satisfied=True,
            ),
            SetupCondition(
                condition_id="c2",
                description="PCR > 1.10",
                timeframe=None,
                required=False,
                evidence_required=False,
                satisfied=None,  # Unknown stays unknown
            ),
        ],
        confirmation_conditions=["Volume expansion on breakout"],
        invalidation_conditions=["15M close below 24950"],
        supporting_evidence=[
            ObservationReference(observation_id="obs_001", source_id="sensibull", description="High put OI")
        ],
        opposing_evidence=[],
        uncertainties=[],
        reasoning_confidence=Confidence(value=0.75, basis=["Multiple timeframe alignment"]),
    )
    assert cand.direction == Direction.LONG
    assert "position_size" in cand.required_downstream_information
    assert "approval_engine_signoff" in cand.required_downstream_information
    # Verify setup conditions unknown preservation
    assert cand.setup_conditions[1].satisfied is None


def test_brain_result_exclusivity_invariant():
    now = datetime.now(timezone.utc)
    output = BrainOutput(
        schema_version=PACKAGE4_SCHEMA_VERSION,
        brain_request_id="breq_001",
        observation_id="obs_001",
        reasoning_state=ReasoningState.WAIT,
        market_context=MarketContext(
            regime=MarketRegime.RANGING,
            regime_confidence=Confidence(value=0.7, basis=["Range bound"]),
            structures=[StructureType.CONSOLIDATION],
            summary="Market consolidating in range",
            key_levels=["25000", "25100"],
            evidence=[],
            uncertainties=[],
        ),
        timeframe_assessments=[
            TimeframeAssessment(
                timeframe="1H",
                summary="Consolidation near resistance",
                structures=[StructureType.CONSOLIDATION],
                directional_context=Direction.NEUTRAL,
                important_observations=["25100 tested twice"],
                evidence=[],
                uncertainties=[],
            ),
            TimeframeAssessment(
                timeframe="15M",
                summary="Contracting volatility",
                structures=[StructureType.CONSOLIDATION],
                directional_context=Direction.NEUTRAL,
                important_observations=["Low volume inside bar"],
                evidence=[],
                uncertainties=[],
            ),
        ],
        scenarios=[
            Scenario(
                scenario_id="sc_1",
                description="Range breakout",
                direction=Direction.LONG,
                supporting_evidence=[],
                contradictory_evidence=[],
                confirmation_conditions=["Break above 25100"],
                invalidation_conditions=["Break below 25000"],
                missing_information=[],
                confidence=Confidence(value=0.6, basis=["Pattern"]),
            )
        ],
        hypotheses=[],
        candidate=None,
        observation_requests=[],
        uncertainties=[],
        confidence=Confidence(value=0.65, basis=["Multi-source"]),
        reasoning_summary=ReasoningSummary(
            context="NIFTY intraday consolidation",
            key_observations=["25000 support held"],
            interpretation="Awaiting breakout confirmation",
            supporting_evidence=[],
            contradictory_evidence=[],
            what_would_change_assessment=["Clear breakout with volume"],
        ),
        generated_at=now,
    )

    failure = BrainFailure(
        schema_version=PACKAGE4_SCHEMA_VERSION,
        brain_request_id="breq_002",
        observation_id="obs_002",
        code="MODEL_ERROR",
        message="Provider timeout",
        retryable=True,
        created_at=now,
    )

    # Valid success result
    res_success = BrainResult(success=True, output=output, failure=None)
    assert res_success.success is True
    assert res_success.output is not None
    assert res_success.failure is None

    # Valid failure result
    res_fail = BrainResult(success=False, output=None, failure=failure)
    assert res_fail.success is False
    assert res_fail.output is None
    assert res_fail.failure is not None

    # Invariant violation: success=True but failure is provided
    with pytest.raises(ValueError):
        BrainResult(success=True, output=output, failure=failure)

    # Invariant violation: success=False but output is provided
    with pytest.raises(ValueError):
        BrainResult(success=False, output=output, failure=None)
