"""
Abstract Base Contract for Pluggable Market Observation Sources.

All observation sources (TradingView, Sensibull, Numerical Market Data)
implement this interface to ensure uniform execution and source independence.
"""

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from nifty_trader.observation.models import ObservationSourceType, SourceObservationResult


class IMarketObservationSource(ABC):
    """
    Contract for any market observation provider.
    Strategy-agnostic: strictly collects perception data.
    """

    @property
    @abstractmethod
    def source_id(self) -> str:
        """Unique identifier for the source (e.g. 'tradingview', 'sensibull', 'numerical')."""
        pass

    @property
    @abstractmethod
    def source_type(self) -> ObservationSourceType:
        """Categorization of this observation source."""
        pass

    @property
    @abstractmethod
    def capabilities(self) -> List[str]:
        """List of observation capabilities provided (e.g. ['chart', 'candlesticks', 'option_chain', 'pcr'])."""
        pass

    @abstractmethod
    async def is_available(self) -> bool:
        """Checks if the observation source is operational and ready to observe."""
        pass

    @abstractmethod
    async def observe(self, symbol: str = "NIFTY", **kwargs) -> SourceObservationResult:
        """
        Executes an observation cycle on this source.
        Returns a structured SourceObservationResult.
        """
        pass
