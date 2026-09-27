"""
Tests for BrainStorage SQLite persistence layer.
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
)
from nifty_trader.brain.storage import BrainStorage


def test_brain_storage_lifecycle(tmp_path):
    db_file = tmp_path / "test_brain.db"
    storage = BrainStorage(db_path=db_file)

    output1 = BrainOutput(
        schema_version=PACKAGE4_SCHEMA_VERSION,
        brain_request_id="breq_001",
        observation_id="obs_001",
        reasoning_state=ReasoningState.WAIT,
        market_context=MarketContext(
            regime=MarketRegime.RANGING,
            regime_confidence=Confidence(value=0.7, basis=["Range levels"]),
            structures=[StructureType.CONSOLIDATION],
            summary="Range bound market",
            key_levels=["24800", "25200"],
            evidence=[],
            uncertainties=[],
        ),
        timeframe_assessments=[
            TimeframeAssessment(
                timeframe="1H",
                summary="Consolidation",
                structures=[StructureType.CONSOLIDATION],
                directional_context=Direction.NEUTRAL,
                important_observations=[],
                evidence=[],
                uncertainties=[],
            ),
            TimeframeAssessment(
                timeframe="15M",
                summary="Chop",
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
        confidence=Confidence(value=0.6, basis=["Range levels"]),
        reasoning_summary=ReasoningSummary(
            context="Consolidation",
            key_observations=[],
            interpretation="Ranging market. Stand by.",
            supporting_evidence=[],
            contradictory_evidence=[],
            what_would_change_assessment=[],
        ),
        generated_at=datetime(2026, 9, 26, 10, 0, 0, tzinfo=timezone.utc),
    )

    output2 = BrainOutput(
        schema_version=PACKAGE4_SCHEMA_VERSION,
        brain_request_id="breq_002",
        observation_id="obs_002",
        reasoning_state=ReasoningState.WATCH,
        market_context=MarketContext(
            regime=MarketRegime.TRENDING_UP,
            regime_confidence=Confidence(value=0.85, basis=["Higher highs"]),
            structures=[StructureType.HIGHER_HIGH],
            summary="Trending up strongly",
            key_levels=["25200"],
            evidence=[],
            uncertainties=[],
        ),
        timeframe_assessments=[
            TimeframeAssessment(
                timeframe="1H",
                summary="Macro trend bullish",
                structures=[StructureType.HIGHER_HIGH],
                directional_context=Direction.LONG,
                important_observations=[],
                evidence=[],
                uncertainties=[],
            ),
            TimeframeAssessment(
                timeframe="15M",
                summary="Continuation",
                structures=[StructureType.HIGHER_LOW],
                directional_context=Direction.LONG,
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
        confidence=Confidence(value=0.8, basis=["Trend"]),
        reasoning_summary=ReasoningSummary(
            context="Bullish momentum",
            key_observations=[],
            interpretation="Uptrend active. Watch 25200.",
            supporting_evidence=[],
            contradictory_evidence=[],
            what_would_change_assessment=[],
        ),
        generated_at=datetime(2026, 9, 26, 10, 15, 0, tzinfo=timezone.utc),
    )

    # Save outputs
    rec1 = storage.save_output(output1, model_provider="gemini", model_name="gemini-2.5-flash")
    rec2 = storage.save_output(output2, model_provider="gemini", model_name="gemini-2.5-flash")

    assert rec1.brain_request_id == "breq_001"
    assert rec2.brain_request_id == "breq_002"

    # Get by ID
    fetched1 = storage.get_output("breq_001")
    assert fetched1 is not None
    assert fetched1.brain_request_id == "breq_001"
    assert fetched1.reasoning_state == ReasoningState.WAIT

    # Get latest output
    latest = storage.get_latest_output()
    assert latest is not None
    assert latest.brain_request_id == "breq_002"

    # Reconstruct BrainState from latest output
    state = storage.get_latest_state()
    assert state is not None
    assert state.reasoning_state == ReasoningState.WATCH
    assert state.source_observation_id == "obs_002"

    # List outputs filtered by state
    wait_runs = storage.list_outputs(state=ReasoningState.WAIT)
    assert len(wait_runs) == 1
    assert wait_runs[0].brain_request_id == "breq_001"

    # Get by observation ID
    obs_runs = storage.get_by_observation_id("obs_001")
    assert len(obs_runs) == 1
    assert obs_runs[0].brain_request_id == "breq_001"
