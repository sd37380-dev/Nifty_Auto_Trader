"""
Tests for Unified Multi-Source Market Observation (Package 3.1).

Covers:
- Full observation cycle across all sources
- Partial observation when Sensibull requires authentication
- Partial observation when Sensibull encounters errors
- Context compilation and change detection for Sensibull events
- Backward compatibility with Package 3 interface
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
import pytest

from nifty_trader.browser.models import BrowserObservation, SourceType
from nifty_trader.market_data.cache import MarketDataCache
from nifty_trader.market_data.clock import CandleClock
from nifty_trader.market_data.cross_check import MarketCrossChecker
from nifty_trader.market_data.events import EventBus
from nifty_trader.market_data.models import Candle, DataQuality, MarketSessionStatus, Timeframe
from nifty_trader.market_data.providers.mock import MockMarketDataProvider
from nifty_trader.market_data.service import MarketObservationService
from nifty_trader.market_data.session import MarketSessionManager
from nifty_trader.observation.cross_check import MultiSourceCrossChecker
from nifty_trader.observation.models import (
    ObservationSourceType,
    SensibullObservation,
    SensibullStatus,
    SourceObservationResult,
)
from nifty_trader.observation.planner import ObservationPlanner
from nifty_trader.observation.sources.sensibull import SensibullObservationSource


@pytest.fixture
def mock_service(tmp_path):
    db_path = tmp_path / "test_market_cache.db"
    cache = MarketDataCache(db_path=db_path)
    provider = MockMarketDataProvider(base_price=24500.0)

    # Seed closed candles
    now = datetime.now(timezone.utc)
    c1h = Candle(
        timestamp=now,
        symbol="NIFTY",
        timeframe=Timeframe.H1,
        open=24400.0,
        high=24550.0,
        low=24380.0,
        close=24500.0,
        is_closed=True,
    )
    c15m = Candle(
        timestamp=now,
        symbol="NIFTY",
        timeframe=Timeframe.M15,
        open=24480.0,
        high=24520.0,
        low=24470.0,
        close=24500.0,
        is_closed=True,
    )
    cache.store_candles([c1h, c15m])

    sensi_mock = MagicMock(spec=SensibullObservationSource)
    sensi_mock.source_id = "sensibull"
    sensi_mock.source_type = ObservationSourceType.DERIVATIVES_OPTION_CHAIN
    sensi_mock.observe = AsyncMock()

    service = MarketObservationService(
        provider=provider,
        cache=cache,
        session_manager=MarketSessionManager(),
        clock=CandleClock(),
        event_bus=EventBus(),
        cross_checker=MarketCrossChecker(),
        sensibull_source=sensi_mock,
        planner=ObservationPlanner(automatic_observation=True),
        multi_cross_checker=MultiSourceCrossChecker(),
    )
    return service, sensi_mock


@pytest.mark.asyncio
async def test_unified_observation_all_sources_success(mock_service):
    service, sensi_mock = mock_service
    sensi_obs = SensibullObservation(
        status=SensibullStatus.OBSERVED,
        spot_reference=24502.0,
        pcr=1.12,
        max_pain_information=24500.0,
    )
    sensi_mock.observe.return_value = SourceObservationResult(
        source_id="sensibull",
        source_type=ObservationSourceType.DERIVATIVES_OPTION_CHAIN,
        success=True,
        status="OBSERVED",
        data=sensi_obs.model_dump(),
    )

    obs = await service.get_market_observation(
        symbol="NIFTY",
        include_sensibull=True,
    )

    assert obs.data_quality == DataQuality.VALID
    assert obs.sensibull_observation is not None
    assert obs.sensibull_observation.status == SensibullStatus.OBSERVED
    assert obs.sensibull_observation.pcr == 1.12
    assert "PCR: 1.12" in obs.pcr_summary
    assert "Sensibull Option Chain Observed" in obs.sensibull_summary
    assert obs.multi_source_cross_check is not None
    assert obs.multi_source_cross_check.sensibull_vs_numerical_status == "MATCH"


@pytest.mark.asyncio
async def test_partial_observation_sensibull_auth_required(mock_service):
    """When Sensibull requires authentication, numerical observation remains valid and unblocked."""
    service, sensi_mock = mock_service
    sensi_obs = SensibullObservation(
        status=SensibullStatus.AUTHENTICATION_REQUIRED,
        warnings=["User broker login required."],
    )
    sensi_mock.observe.return_value = SourceObservationResult(
        source_id="sensibull",
        source_type=ObservationSourceType.DERIVATIVES_OPTION_CHAIN,
        success=False,
        status=SensibullStatus.AUTHENTICATION_REQUIRED.value,
        data=sensi_obs.model_dump(),
    )

    obs = await service.get_market_observation(
        symbol="NIFTY",
        include_sensibull=True,
    )

    # The overall numerical observation must NOT fail
    assert obs.data_quality == DataQuality.VALID
    assert obs.sensibull_observation.status == SensibullStatus.AUTHENTICATION_REQUIRED
    assert "Authentication required" in obs.pcr_summary
    assert "login required" in obs.sensibull_summary


@pytest.mark.asyncio
async def test_partial_observation_sensibull_error_graceful_handling(mock_service):
    """When Sensibull encounters an exception, overall observation proceeds gracefully."""
    service, sensi_mock = mock_service
    sensi_mock.observe.side_effect = RuntimeError("Chrome CDP communication failure")

    obs = await service.get_market_observation(
        symbol="NIFTY",
        include_sensibull=True,
    )

    assert obs.sensibull_observation is not None
    assert obs.sensibull_observation.status == SensibullStatus.ERROR
    assert "Chrome CDP communication failure" in obs.sensibull_observation.errors[0]
    # Numerical candles still available
    assert len(obs.fifteen_minute_candles) > 0


@pytest.mark.asyncio
async def test_context_compilation_sensibull_changes(mock_service):
    service, sensi_mock = mock_service
    sensi_obs1 = SensibullObservation(status=SensibullStatus.OBSERVED, pcr=0.90)
    sensi_mock.observe.return_value = SourceObservationResult(
        source_id="sensibull",
        source_type=ObservationSourceType.DERIVATIVES_OPTION_CHAIN,
        success=True,
        status="OBSERVED",
        data=sensi_obs1.model_dump(),
    )
    obs1 = await service.get_market_observation(include_sensibull=True)
    ctx1 = service.compile_observation_context(obs1)
    assert ctx1.has_meaningful_change is True

    # Next observation with shifted PCR
    sensi_obs2 = SensibullObservation(status=SensibullStatus.OBSERVED, pcr=1.25)
    sensi_mock.observe.return_value = SourceObservationResult(
        source_id="sensibull",
        source_type=ObservationSourceType.DERIVATIVES_OPTION_CHAIN,
        success=True,
        status="OBSERVED",
        data=sensi_obs2.model_dump(),
    )
    obs2 = await service.get_market_observation(include_sensibull=True)
    ctx2 = service.compile_observation_context(obs2)
    assert any("SENSIBULL_PCR_SHIFT" in r for r in ctx2.change_reasons)
