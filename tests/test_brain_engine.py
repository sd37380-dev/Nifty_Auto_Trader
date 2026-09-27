"""
Tests for TradingBrainEngine and Safe Fallback Orchestration.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
import pytest

from nifty_trader.brain.contracts import (
    PACKAGE4_SCHEMA_VERSION,
    BrainFailure,
    BrainInput,
    BrainOutput,
    BrainResult,
    Confidence,
    Direction,
    MarketContext,
    MarketRegime,
    ReasoningState,
    ReasoningSummary,
    StructureType,
    TimeframeAssessment,
)
from nifty_trader.brain.engine import TradingBrainEngine
from nifty_trader.brain.storage import BrainStorage
from nifty_trader.contracts.models import (
    CandleObservation,
    CanonicalObservationStatus,
    NumericalObservation,
    SourceStatus,
    UnifiedMarketObservation,
    VisualObservation,
)


@pytest.fixture
def mock_observation():
    now = datetime.now(timezone.utc)
    return UnifiedMarketObservation(
        observation_id="obs_engine_test_01",
        observed_at=now,
        instrument="NIFTY",
        session="OPEN",
        numerical=NumericalObservation(
            candles_1h=[
                CandleObservation(
                    instrument="NIFTY",
                    timeframe="1H",
                    timestamp=now,
                    open=25000.0,
                    high=25100.0,
                    low=24950.0,
                    close=25080.0,
                    volume=100000.0,
                )
            ],
            candles_15m=[
                CandleObservation(
                    instrument="NIFTY",
                    timeframe="15M",
                    timestamp=now,
                    open=25050.0,
                    high=25090.0,
                    low=25040.0,
                    close=25080.0,
                    volume=25000.0,
                )
            ],
        ),
        visual=VisualObservation(),
        source_status={
            "numerical": SourceStatus(source_id="numerical", status=CanonicalObservationStatus.SUCCESS, completeness=1.0)
        },
    )


@pytest.mark.asyncio
async def test_trading_brain_engine_successful_reasoning(tmp_path, mock_observation):
    db_file = tmp_path / "brain_test.db"
    storage = BrainStorage(db_path=db_file)

    mock_router = MagicMock()
    mock_router.get_tier_config.return_value = {"provider": "gemini", "model": "gemini-2.5-flash"}

    now = datetime.now(timezone.utc)
    expected_output = BrainOutput(
        schema_version=PACKAGE4_SCHEMA_VERSION,
        brain_request_id="breq_engine_01",
        observation_id="obs_engine_test_01",
        reasoning_state=ReasoningState.WATCH,
        market_context=MarketContext(
            regime=MarketRegime.TRENDING_UP,
            regime_confidence=Confidence(value=0.85, basis=["Higher highs"]),
            structures=[StructureType.HIGHER_HIGH],
            summary="Macro trend bullish",
            key_levels=["25100"],
            evidence=[],
            uncertainties=[],
        ),
        timeframe_assessments=[
            TimeframeAssessment(
                timeframe="1H",
                summary="Bullish continuation",
                structures=[StructureType.HIGHER_HIGH],
                directional_context=Direction.LONG,
                important_observations=[],
                evidence=[],
                uncertainties=[],
            ),
            TimeframeAssessment(
                timeframe="15M",
                summary="Local consolidation flag",
                structures=[StructureType.CONSOLIDATION],
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
        confidence=Confidence(value=0.8, basis=["Price structure"]),
        reasoning_summary=ReasoningSummary(
            context="Bullish flag",
            key_observations=[],
            interpretation="Watching potential breakout above 25100. No action authorized.",
            supporting_evidence=[],
            contradictory_evidence=[],
            what_would_change_assessment=["15M close below 25000"],
        ),
        generated_at=now,
    )
    mock_router.route_structured = AsyncMock(return_value=expected_output)

    engine = TradingBrainEngine(router=mock_router, storage=storage)
    result = await engine.reason(mock_observation)

    assert result.success is True
    assert result.output is not None
    assert result.failure is None
    assert result.output.observation_id == "obs_engine_test_01"
    assert result.output.reasoning_state == ReasoningState.WATCH
    assert result.output.market_context.regime == MarketRegime.TRENDING_UP

    # Check persistence in storage
    saved = storage.get_latest_output()
    assert saved is not None
    assert saved.observation_id == "obs_engine_test_01"
    assert saved.reasoning_state == ReasoningState.WATCH


@pytest.mark.asyncio
async def test_trading_brain_engine_safe_fallback_on_provider_error(tmp_path, mock_observation):
    db_file = tmp_path / "brain_test_fb.db"
    storage = BrainStorage(db_path=db_file)

    mock_router = MagicMock()
    mock_router.get_tier_config.return_value = {"provider": "gemini", "model": "gemini-2.5-flash"}
    # Simulate complete LLM API outage
    mock_router.route_structured = AsyncMock(side_effect=RuntimeError("All providers exhausted. Connection refused."))

    engine = TradingBrainEngine(router=mock_router, storage=storage)

    # Must NOT raise exception; must return BrainResult(success=False, failure=BrainFailure)
    result = await engine.reason(mock_observation)

    assert result.success is False
    assert result.output is None
    assert result.failure is not None
    assert result.failure.code == "PROVIDER_UNAVAILABLE"
    assert result.failure.observation_id == "obs_engine_test_01"
    assert result.failure.retryable is True
