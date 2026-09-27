"""
Package 5: Source Freshness Evaluator.

Assesses the data freshness and operational validity of perception channels
(FRESH, AGING, STALE, EXPIRED, FAILED) based on timestamps and age thresholds.
"""

from datetime import datetime, timezone
import logging
from typing import Dict, Optional

from nifty_trader.autonomous.contracts import SourceFreshnessStatus
from nifty_trader.contracts.models import (
    CanonicalObservationStatus,
    UnifiedMarketObservation,
)

logger = logging.getLogger(__name__)


class SourceFreshnessChecker:
    """
    Evaluates whether observation sources are fresh or require scheduling for refresh.
    """

    DEFAULT_TTLS: Dict[str, float] = {
        "numerical": 300.0,    # 5 minutes
        "sensibull": 180.0,    # 3 minutes
        "tradingview": 300.0,  # 5 minutes
    }

    def __init__(self, ttls: Optional[Dict[str, float]] = None):
        self.ttls = {**self.DEFAULT_TTLS, **(ttls or {})}

    def evaluate_source(
        self,
        source: str,
        observed_at: Optional[datetime],
        status: CanonicalObservationStatus,
        current_time: Optional[datetime] = None,
    ) -> SourceFreshnessStatus:
        """
        Evaluates a single source's freshness tier.
        """
        if status != CanonicalObservationStatus.SUCCESS:
            return SourceFreshnessStatus.FAILED

        if observed_at is None:
            return SourceFreshnessStatus.STALE

        now = current_time or datetime.now(timezone.utc)
        age_seconds = max(0.0, (now - observed_at).total_seconds())
        ttl = self.ttls.get(source.lower(), 300.0)

        if age_seconds < ttl * 0.5:
            return SourceFreshnessStatus.FRESH
        elif age_seconds < ttl:
            return SourceFreshnessStatus.AGING
        elif age_seconds < ttl * 2.0:
            return SourceFreshnessStatus.STALE
        else:
            return SourceFreshnessStatus.EXPIRED

    def evaluate_unified_observation(
        self,
        observation: UnifiedMarketObservation,
        current_time: Optional[datetime] = None,
    ) -> Dict[str, SourceFreshnessStatus]:
        """
        Evaluates freshness for all perception channels inside a UnifiedMarketObservation.
        """
        now = current_time or datetime.now(timezone.utc)
        results: Dict[str, SourceFreshnessStatus] = {}

        # 1. Numerical
        num_stat = observation.source_status.get("numerical")
        status = num_stat.status if num_stat else CanonicalObservationStatus.SUCCESS
        latest_c = observation.numerical.latest_15m or observation.numerical.latest_1h
        obs_time = latest_c.timestamp if latest_c else observation.observed_at
        results["numerical"] = self.evaluate_source("numerical", obs_time, status, now)

        # 2. Sensibull
        if observation.visual.sensibull:
            s = observation.visual.sensibull
            results["sensibull"] = self.evaluate_source("sensibull", s.observed_at, s.status, now)
        else:
            results["sensibull"] = SourceFreshnessStatus.STALE

        # 3. TradingView
        if observation.visual.tradingview:
            tv = observation.visual.tradingview
            results["tradingview"] = self.evaluate_source("tradingview", tv.observed_at, tv.status, now)
        else:
            results["tradingview"] = SourceFreshnessStatus.STALE

        return results
