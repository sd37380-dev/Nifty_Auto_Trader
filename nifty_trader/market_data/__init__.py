"""
Market Data & Observation Package.

Provides deterministic multi-timeframe market perception for 1H and 15M NIFTY data,
local caching, session tracking, visual cross-checking, and event generation.
"""

from nifty_trader.market_data.models import (
    Candle,
    Timeframe,
    DataQuality,
    MarketSessionStatus,
    ObservationEvent,
    ObservationEventType,
)
from nifty_trader.market_data.base import MarketDataProvider
from nifty_trader.market_data.providers.yahoo import YahooFinanceProvider
from nifty_trader.market_data.providers.mock import MockMarketDataProvider
from nifty_trader.market_data.cache import MarketDataCache
from nifty_trader.market_data.session import MarketSessionManager
from nifty_trader.market_data.clock import CandleClock
from nifty_trader.market_data.events import EventBus
from nifty_trader.market_data.cross_check import MarketCrossChecker, CrossCheckResult
from nifty_trader.market_data.observation import (
    MarketObservation,
    AgentObservationContext,
    MarketPerceptionOutput,
)
from nifty_trader.market_data.service import MarketObservationService

__all__ = [
    "Candle",
    "Timeframe",
    "DataQuality",
    "MarketSessionStatus",
    "ObservationEvent",
    "ObservationEventType",
    "MarketDataProvider",
    "YahooFinanceProvider",
    "MockMarketDataProvider",
    "MarketDataCache",
    "MarketSessionManager",
    "CandleClock",
    "EventBus",
    "MarketCrossChecker",
    "CrossCheckResult",
    "MarketObservation",
    "AgentObservationContext",
    "MarketPerceptionOutput",
    "MarketObservationService",
]
