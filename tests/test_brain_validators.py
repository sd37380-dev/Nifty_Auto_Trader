"""
Tests for Brain Output Validators and Domain Invariant Defense (Package 4 Rules 1-10).
"""

from datetime import datetime, timezone
import pytest

from nifty_trader.brain.contracts import (
    PACKAGE4_SCHEMA_VERSION,
    BrainOutput,
    Confidence,
    Direction,
    MarketContext,
    MarketRegime,
    ReasoningState,
    ReasoningSummary,
    StructureType,
    TimeframeAssessment,
    TradeCandidate,
    Uncertainty,
    UncertaintyType,
)
from nifty_trader.brain.validators import BrainOutputValidator


@pytest.fixture
def base_brain_output():
    now = datetime.now(timezone.utc)
    return BrainOutput(
        schema_version=PACKAGE4_SCHEMA_VERSION,
        brain_request_id="breq_val_01",
        observation_id="obs_val_01",
        reasoning_state=ReasoningState.WAIT,
        market_context=MarketContext(
            regime=MarketRegime.RANGING,
            regime_confidence=Confidence(value=0.7, basis=["Range levels"]),
            structures=[StructureType.CONSOLIDATION],
            summary="Price in consolidation band",
            key_levels=["24800", "25200"],
            evidence=[],
            uncertainties=[],
        ),
        timeframe_assessments=[
            TimeframeAssessment(
                timeframe="1H",
                summary="Consolidating near 50-SMA",
                structures=[StructureType.CONSOLIDATION],
                directional_context=Direction.NEUTRAL,
                important_observations=[],
                evidence=[],
                uncertainties=[],
            ),
            TimeframeAssessment(
                timeframe="15M",
                summary="Chop inside range",
                structures=[StructureType.CONSOLIDATION],
                directional_context=Direction.NEUTRAL,
                important_observations=[],
                evidence=[],
                uncertainties=[],
            ),
        ],
        scenarios=[],
        hypotheses=[],
        candidate=None,
        observation_requests=[],
        uncertainties=[],
        confidence=Confidence(value=0.7, basis=["Range"]),
        reasoning_summary=ReasoningSummary(
            context="Consolidation context",
            key_observations=["Range bound"],
            interpretation="Wait for structural clarity",
            supporting_evidence=[],
            contradictory_evidence=[],
            what_would_change_assessment=["Breakout"],
        ),
        generated_at=now,
    )


def test_validator_neutralizes_prohibited_execution_directives(base_brain_output):
    validator = BrainOutputValidator()
    # Inject prohibited execution directive into interpretation
    base_brain_output.reasoning_summary.interpretation = "Buy now at market open for maximum profits"
    base_brain_output.reasoning_state = ReasoningState.CANDIDATE

    sanitized = validator.validate_and_sanitize(base_brain_output)

    # State must be demoted to WAIT and rationale updated
    assert sanitized.reasoning_state == ReasoningState.WAIT
    assert "SAFETY DEMOTION" in sanitized.reasoning_summary.interpretation
    assert sanitized.candidate is None


def test_validator_enforces_rules_1_to_3_candidate_null(base_brain_output):
    validator = BrainOutputValidator()

    candidate = TradeCandidate(
        candidate_id="cand_01",
        direction=Direction.LONG,
        thesis="Breakout thesis",
        market_context="Bullish context",
        setup_conditions=[],
        confirmation_conditions=[],
        invalidation_conditions=[],
        supporting_evidence=[],
        opposing_evidence=[],
        uncertainties=[],
        reasoning_confidence=Confidence(value=0.8, basis=["Trend"]),
    )

    # Rule 1: NO_TRADE -> candidate == None
    base_brain_output.reasoning_state = ReasoningState.NO_TRADE
    base_brain_output.candidate = candidate
    sanitized = validator.validate_and_sanitize(base_brain_output)
    assert sanitized.candidate is None

    # Rule 2: WAIT -> candidate == None
    base_brain_output.reasoning_state = ReasoningState.WAIT
    base_brain_output.candidate = candidate
    sanitized = validator.validate_and_sanitize(base_brain_output)
    assert sanitized.candidate is None

    # Rule 3: WATCH -> candidate == None
    base_brain_output.reasoning_state = ReasoningState.WATCH
    base_brain_output.candidate = candidate
    sanitized = validator.validate_and_sanitize(base_brain_output)
    assert sanitized.candidate is None


def test_validator_enforces_rule_5_candidate_required(base_brain_output):
    validator = BrainOutputValidator()

    # Rule 5: CANDIDATE state requires candidate != None, else demoted to DEVELOPING
    base_brain_output.reasoning_state = ReasoningState.CANDIDATE
    base_brain_output.candidate = None

    sanitized = validator.validate_and_sanitize(base_brain_output)
    assert sanitized.reasoning_state == ReasoningState.DEVELOPING


def test_validator_enforces_rule_10_stale_data_uncertainty(base_brain_output):
    validator = BrainOutputValidator()

    freshness = {
        "numerical": True,
        "sensibull": False,  # Stale!
    }

    sanitized = validator.validate_and_sanitize(base_brain_output, source_freshness_flags=freshness)
    stale_uncertainties = [u for u in sanitized.uncertainties if u.type == UncertaintyType.STALE_DATA]
    assert len(stale_uncertainties) == 1
    assert "sensibull" in stale_uncertainties[0].description
