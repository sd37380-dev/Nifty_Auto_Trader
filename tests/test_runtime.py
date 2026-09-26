"""
Unit tests for the NiftyTraderRuntime.
"""

import pytest
from nifty_trader.core.runtime import NiftyTraderRuntime
from nifty_trader.core.state import TradingState, MarketObservationOutput, MarketAction


@pytest.mark.asyncio
async def test_runtime_initialization():
    """Verify runtime initializes in STARTUP state with valid settings."""
    runtime = NiftyTraderRuntime()
    assert runtime.state == TradingState.STARTUP
    assert runtime.settings["app"]["name"] == "NIFTY Autonomous Trader"
    assert runtime.settings["risk"]["max_risk_per_trade"] == 0.01
    assert runtime.settings["risk"]["max_daily_loss"] == 5000
    assert runtime.settings["risk"]["max_trades_per_day"] == 3
    assert runtime.settings["risk"]["minimum_rr"] == 2.0


@pytest.mark.asyncio
async def test_runtime_status():
    """Verify get_status returns complete diagnostic structure."""
    runtime = NiftyTraderRuntime()
    status = await runtime.get_status()

    assert "app" in status
    assert "version" in status
    assert "state" in status
    assert "providers" in status
    assert "risk_policies" in status
    assert status["risk_policies"]["max_risk_per_trade"] == 0.01


@pytest.mark.asyncio
async def test_market_observation_output_schema():
    """Verify MarketObservationOutput schema validates and accepts WAIT or NO_TRADE."""
    sample = {
        "market_context": "Market is consolidating near resistance.",
        "one_hour_bias": "NEUTRAL",
        "fifteen_minute_state": "RANGE",
        "setup_status": "NONE",
        "action": "WAIT",
        "important_levels": [25300.0, 25400.0],
        "reasoning": ["Price trapped between EMAs", "Volume below average"],
        "uncertainties": ["Impending RBI policy statement"],
        "next_observation": "Wait for breakout of 25400",
    }

    parsed = MarketObservationOutput.model_validate(sample)
    assert parsed.action == MarketAction.WAIT
    assert len(parsed.important_levels) == 2

    # Also test NO_TRADE
    sample["action"] = "NO_TRADE"
    parsed_no_trade = MarketObservationOutput.model_validate(sample)
    assert parsed_no_trade.action == MarketAction.NO_TRADE


@pytest.mark.asyncio
async def test_runtime_unified_observation_contract():
    """Verify runtime produces valid canonical UnifiedMarketObservation."""
    runtime = NiftyTraderRuntime()
    unified = await runtime.get_unified_market_observation(cross_check=False)

    assert unified.schema_version == "1.0"
    assert unified.observation_id.startswith("umo_")
    assert unified.instrument == "NIFTY"
    assert isinstance(unified.numerical.candles_1h, list)
    assert isinstance(unified.numerical.candles_15m, list)
    assert isinstance(unified.source_status, dict)
    assert isinstance(unified.evidence, list)
