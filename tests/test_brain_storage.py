"""
Tests for BrainStorage SQLite persistence layer.
"""

from datetime import datetime, timezone
import pytest

from nifty_trader.brain.contracts import (
    BoundedConfidence,
    BrainReasoningOutput,
    MarketRegime,
    SetupState,
)
from nifty_trader.brain.storage import BrainStorage


def test_brain_storage_lifecycle(tmp_path):
    db_file = tmp_path / "test_brain.db"
    storage = BrainStorage(db_path=db_file)

    output1 = BrainReasoningOutput(
        brain_run_id="run_001",
        observation_id="obs_001",
        timestamp=datetime(2026, 9, 26, 10, 0, 0, tzinfo=timezone.utc),
        regime=MarketRegime.RANGING,
        regime_confidence=0.7,
        regime_evidence=["Evidence 1"],
        one_hour_interpretation="Range bound",
        fifteen_minute_interpretation="Consolidation",
        multi_source_synthesis="Agreement across sources",
        current_state=SetupState.WAIT,
        state_rationale="Waiting for volume confirmation",
        next_observation_needed="Next 15M candle",
        confidence=BoundedConfidence(value=0.6, basis=["Range levels"]),
        auditable_summary="Ranging market. Stand by.",
    )

    output2 = BrainReasoningOutput(
        brain_run_id="run_002",
        observation_id="obs_002",
        timestamp=datetime(2026, 9, 26, 10, 15, 0, tzinfo=timezone.utc),
        regime=MarketRegime.TRENDING_UP,
        regime_confidence=0.85,
        regime_evidence=["Evidence 2"],
        one_hour_interpretation="Trending up",
        fifteen_minute_interpretation="Higher highs",
        multi_source_synthesis="Agreement",
        current_state=SetupState.WATCH,
        state_rationale="Watching key level 25200",
        next_observation_needed="Test of 25200",
        confidence=BoundedConfidence(value=0.8, basis=["Trend"]),
        auditable_summary="Uptrend active.",
    )

    # Save runs
    storage.save_run(output1, model_provider="gemini", model_name="gemini-2.5-flash")
    storage.save_run(output2, model_provider="gemini", model_name="gemini-2.5-flash")

    # Get by ID
    fetched1 = storage.get_run("run_001")
    assert fetched1 is not None
    assert fetched1.brain_run_id == "run_001"
    assert fetched1.current_state == SetupState.WAIT

    # Get latest
    latest = storage.get_latest()
    assert latest is not None
    assert latest.brain_run_id == "run_002"

    # List runs filtered by state
    wait_runs = storage.list_runs(state=SetupState.WAIT)
    assert len(wait_runs) == 1
    assert wait_runs[0].brain_run_id == "run_001"

    # Get by observation ID
    obs_runs = storage.get_by_observation_id("obs_001")
    assert len(obs_runs) == 1
    assert obs_runs[0].brain_run_id == "run_001"
