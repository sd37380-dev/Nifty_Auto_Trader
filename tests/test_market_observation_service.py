"""
Unit tests for MarketObservationService coordination.
"""

from datetime import datetime, timezone, timedelta
from pathlib import Path
import tempfile
import pytest

from nifty_trader.instruction.manager import InstructionManager
from nifty_trader.instruction.models import InstructionPriority
from nifty_trader.instruction.storage import InstructionStore
from nifty_trader.market_data.cache import MarketDataCache
from nifty_trader.market_data.cross_check import MarketCrossChecker
from nifty_trader.market_data.events import EventBus
from nifty_trader.market_data.models import ObservationEventType, Timeframe
from nifty_trader.market_data.providers.mock import MockMarketDataProvider
from nifty_trader.market_data.service import MarketObservationService


@pytest.fixture
def mock_service(tmp_path):
    cache_path = tmp_path / "test_cache.db"
    inst_path = tmp_path / "test_instructions.db"

    provider = MockMarketDataProvider(base_price=23140.50)
    cache = MarketDataCache(db_path=cache_path)
    event_bus = EventBus()
    cross_checker = MarketCrossChecker(tolerance_pct=0.5)
    store = InstructionStore(db_path=inst_path)
    inst_mgr = InstructionManager(store=store)

    service = MarketObservationService(
        provider=provider,
        cache=cache,
        event_bus=event_bus,
        cross_checker=cross_checker,
        instruction_manager=inst_mgr,
    )
    return service


@pytest.mark.asyncio
async def test_service_initial_and_incremental_sync(mock_service):
    events_received = []

    def on_candle_closed(event):
        events_received.append(event)

    mock_service.event_bus.subscribe(ObservationEventType.CANDLE_CLOSED, on_candle_closed)

    # Initial sync
    results = await mock_service.sync_data(symbol="NIFTY")
    assert results[Timeframe.H1.value] > 0
    assert results[Timeframe.M15.value] > 0

    # Events should be emitted
    assert len(events_received) >= 1

    # Incremental sync immediately after should fetch minimal or 0 new candles
    results_2 = await mock_service.sync_data(symbol="NIFTY")
    assert isinstance(results_2, dict)


@pytest.mark.asyncio
async def test_service_get_market_observation(mock_service):
    await mock_service.sync_data(symbol="NIFTY")
    obs = await mock_service.observe_market(symbol="NIFTY", perform_cross_check=False)

    assert obs.symbol == "NIFTY"
    assert len(obs.one_hour_candles) > 0
    assert len(obs.fifteen_minute_candles) > 0
    assert obs.latest_1h is not None
    assert obs.latest_15m is not None
    assert obs.h1_summary is not None
    assert obs.m15_summary is not None


@pytest.mark.asyncio
async def test_service_meaningful_change_detection(mock_service):
    await mock_service.sync_data(symbol="NIFTY")

    # First context retrieval
    ctx1 = await mock_service.get_agent_observation_context(symbol="NIFTY")
    assert ctx1.has_meaningful_change is True  # Initial observation is meaningful

    # Second context retrieval immediately after with no changes
    ctx2 = await mock_service.get_agent_observation_context(symbol="NIFTY")
    assert ctx2.has_meaningful_change is False

    # Submit a new operator instruction
    mock_service.instruction_mgr.submit_instruction(
        text="Check breakout above 23150",
        priority=InstructionPriority.HIGH,
    )

    # Third context retrieval: new instruction should trigger meaningful change
    ctx3 = await mock_service.get_agent_observation_context(symbol="NIFTY")
    assert ctx3.has_meaningful_change is True
    assert any("instruction" in r.lower() for r in ctx3.change_reasons)
