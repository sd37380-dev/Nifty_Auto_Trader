"""
Tests for TradingBrainEngine and Safe Fallback Orchestration.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
import pytest

from nifty_trader.brain.contracts import (
    BoundedConfidence,
    BrainReasoningOutput,
    MarketRegime,
    SetupState,
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

    expected_output = BrainReasoningOutput(
        observation_id="obs_engine_test_01",
        regime=MarketRegime.TRENDING_UP,
        regime_confidence=0.85,
        regime_evidence=["Higher highs and higher lows"],
        one_hour_interpretation="Macro trend bullish",
        fifteen_minute_interpretation="Local continuation flag",
        multi_source_synthesis="Numerical data confirms uptrend",
        current_state=SetupState.WATCH,
        state_rationale="Watch for breakout confirmation above 25100",
        next_observation_needed="15M close above 25100",
        confidence=BoundedConfidence(value=0.8, basis=["Price structure"]),
        auditable_summary="Watching potential breakout. No action authorized.",
    )
    mock_router.route_structured = AsyncMock(return_value=expected_output)

    engine = TradingBrainEngine(router=mock_router, storage=storage)
    result = await engine.reason(mock_observation)

    assert result.observation_id == "obs_engine_test_01"
    assert result.current_state == SetupState.WATCH
    assert result.regime == MarketRegime.TRENDING_UP

    # Check persistence in storage
    saved = storage.get_latest()
    assert saved is not None
    assert saved.observation_id == "obs_engine_test_01"
    assert saved.current_state == SetupState.WATCH


@pytest.mark.asyncio
async def test_trading_brain_engine_safe_fallback_on_provider_error(tmp_path, mock_observation):
    db_file = tmp_path / "brain_test_fb.db"
    storage = BrainStorage(db_path=db_file)

    mock_router = MagicMock()
    mock_router.get_tier_config.return_value = {"provider": "gemini", "model": "gemini-2.5-flash"}
    # Simulate complete LLM API outage
    mock_router.route_structured = AsyncMock(side_effect=RuntimeError("All providers exhausted. Connection refused."))

    engine = TradingBrainEngine(router=mock_router, storage=storage)

    # Must NOT raise exception; must return safe fallback WAIT state
    result = await engine.reason(mock_observation)

    assert result.observation_id == "obs_engine_test_01"
    assert result.current_state == SetupState.WAIT
    assert result.regime == MarketRegime.UNCLEAR
    assert result.confidence.value == 0.0
    assert "COGNITIVE_FAILOVER" in result.state_rationale
    assert result.candidate_thesis is None

    # Check that fallback was also persisted to SQLite
    saved = storage.get_latest()
    assert saved is not None
    assert saved.current_state == SetupState.WAIT
    assert "SAFETY ENGAGED" in saved.auditable_summary
