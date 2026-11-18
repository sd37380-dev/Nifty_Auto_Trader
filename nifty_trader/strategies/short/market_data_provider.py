"""
Market Data Providers for NIFTY Futures Short Strategy.

Provides:
- BaseShortMarketDataProvider: Abstract interface delivering normalized MarketSnapshot
- BrokerLiveMarketDataProvider: Live broker ingestion (Dhan HQ API / MockDhanDataAdapter)
- HistoricalMarketDataProvider: Chronological historical replay with zero look-ahead bias

CRITICAL INVARIANTS:
1. Futures price is ALWAYS sourced directly from broker/historical Futures feeds.
2. NEVER estimated or calculated from Spot (Future != Spot + Premium).
3. If Futures data is unavailable: snapshot.futures_price is None -> "FUTURES DATA UNAVAILABLE".
4. If historical option data is unavailable: reports "INSUFFICIENT HISTORICAL OPTION DATA FOR VALID BACKTEST". Never fabricates.
"""

from abc import ABC, abstractmethod
from datetime import datetime, timezone, timedelta
import logging
from typing import Any, Dict, List, Optional

from nifty_trader.research_zone.contracts import NormalizedBar
from nifty_trader.research_zone.dhan_adapter import DhanDataAdapter, MockDhanDataAdapter
from nifty_trader.strategies.short.contracts import (
    Candle5M,
    IST,
    MarketSnapshot,
    OptionChainSnapshot,
    OptionStrikeData,
    PivotLevels,
    PreviousDayOHLC,
)
from nifty_trader.strategies.short.indicators import IndicatorEngine
from nifty_trader.strategies.short.pivot import PivotEngine

logger = logging.getLogger(__name__)


class BaseShortMarketDataProvider(ABC):
    """Abstract data provider interface decoupling strategy from market data sources."""

    @abstractmethod
    def get_market_snapshot(self, timestamp: Optional[datetime] = None) -> MarketSnapshot:
        """Constructs and returns normalized MarketSnapshot."""
        pass


class BrokerLiveMarketDataProvider(BaseShortMarketDataProvider):
    """
    Live broker market data provider.
    Ingests live NIFTY Futures prices, 5-minute candles, and option chain from broker.
    """

    def __init__(
        self,
        broker_adapter: Optional[DhanDataAdapter] = None,
        symbol: str = "NIFTY",
    ):
        self.broker = broker_adapter or MockDhanDataAdapter()
        self.symbol = symbol

    def get_market_snapshot(self, timestamp: Optional[datetime] = None) -> MarketSnapshot:
        """
        Polls broker for live Futures price, recent 5M candles, and option chain snapshot.
        """
        now = timestamp or datetime.now(timezone.utc)

        # 1. Fetch 5-Minute Futures Bars
        try:
            from_dt = now - timedelta(days=5)
            raw_bars = self.broker.fetch_historical_bars(
                symbol=f"{self.symbol}_FUT",
                timeframe="5M",
                from_date=from_dt,
                to_date=now,
            )
        except Exception as e:
            logger.error("Failed fetching broker futures bars: %s", e)
            raw_bars = []

        if not raw_bars:
            # Fallback check if symbol without suffix is futures
            try:
                raw_bars = self.broker.fetch_historical_bars(
                    symbol=self.symbol,
                    timeframe="5M",
                    from_date=from_dt,
                    to_date=now,
                )
            except Exception:
                raw_bars = []

        candles: List[Candle5M] = [
            Candle5M(
                timestamp=b.timestamp,
                open=b.open,
                high=b.high,
                low=b.low,
                close=b.close,
                volume=b.volume,
                open_interest=b.open_interest,
            )
            for b in raw_bars
        ]

        # Determine Futures price directly from broker feed
        futures_price: Optional[float] = None
        if candles:
            futures_price = candles[-1].close

        # 2. Fetch Option Chain Snapshot
        option_chain: Optional[OptionChainSnapshot] = None
        try:
            raw_chain = self.broker.fetch_option_chain_snapshot(symbol=self.symbol)
            if raw_chain and "strikes" in raw_chain:
                strikes_data: List[OptionStrikeData] = []
                for s in raw_chain["strikes"]:
                    strikes_data.append(
                        OptionStrikeData(
                            strike=float(s["strike"]),
                            calls_oi=float(s.get("call", {}).get("oi", 0.0)),
                            calls_change_oi=float(s.get("call", {}).get("oi_change", 0.0)),
                            puts_oi=float(s.get("put", {}).get("oi", 0.0)),
                            puts_change_oi=float(s.get("put", {}).get("oi_change", 0.0)),
                            call_ltp=float(s.get("call", {}).get("ltp", 0.0)) if "ltp" in s.get("call", {}) else None,
                            put_ltp=float(s.get("put", {}).get("ltp", 0.0)) if "ltp" in s.get("put", {}) else None,
                        )
                    )
                option_chain = OptionChainSnapshot(
                    timestamp=now,
                    underlying=self.symbol,
                    expiry=raw_chain.get("expiry"),
                    strikes=strikes_data,
                )
        except Exception as e:
            logger.error("Failed fetching broker option chain snapshot: %s", e)
            option_chain = None

        # 3. Derive Previous Day OHLC
        prev_day_ohlc: Optional[PreviousDayOHLC] = None
        if len(candles) >= 75:
            # Group completed candles by date and pick previous trading day
            dates = sorted(list(set(c.timestamp.date() for c in candles)))
            if len(dates) >= 2:
                prev_date = dates[-2]
                day_candles = [c for c in candles if c.timestamp.date() == prev_date]
                if day_candles:
                    prev_day_ohlc = PreviousDayOHLC(
                        date=prev_date.isoformat(),
                        high=max(c.high for c in day_candles),
                        low=min(c.low for c in day_candles),
                        close=day_candles[-1].close,
                        open=day_candles[0].open,
                    )

        # 4. Indicators (EMA20, EMA50, ATR14)
        ema20 = None
        ema50 = None
        ema20_prev = None
        atr14 = None
        if candles:
            closes = [c.close for c in candles]
            highs = [c.high for c in candles]
            lows = [c.low for c in candles]
            e20_s = IndicatorEngine.calculate_ema_series(closes, 20)
            e50_s = IndicatorEngine.calculate_ema_series(closes, 50)
            atr_s = IndicatorEngine.calculate_atr_series(highs, lows, closes, 14)
            ema20 = e20_s[-1] if e20_s else None
            ema20_prev = e20_s[-2] if len(e20_s) > 1 else ema20
            ema50 = e50_s[-1] if e50_s else None
            atr14 = atr_s[-1] if atr_s else None

        pivot_levels = PivotEngine.calculate_pivots(prev_day_ohlc) if prev_day_ohlc else None

        return MarketSnapshot(
            timestamp=now,
            futures_price=futures_price,
            spot_price=None, # Never calculate futures from spot
            futures_candles=candles,
            option_chain=option_chain,
            previous_day_ohlc=prev_day_ohlc,
            ema20=ema20,
            ema50=ema50,
            ema20_prev=ema20_prev,
            atr14=atr14,
            pivot_levels=pivot_levels,
        )


class HistoricalMarketDataProvider(BaseShortMarketDataProvider):
    """
    Chronological historical market data provider for backtesting.
    Enforces strict no look-ahead bias: at timestamp T, only data up to T is accessible.
    """

    def __init__(
        self,
        futures_candles: List[Candle5M],
        option_chain_snapshots: Optional[Dict[str, OptionChainSnapshot]] = None,
        daily_ohlc: Optional[Dict[str, PreviousDayOHLC]] = None,
    ):
        # Sort candles chronologically
        self.candles = sorted(futures_candles, key=lambda c: c.timestamp)
        self.option_snapshots = option_chain_snapshots or {}
        self.daily_ohlc = daily_ohlc or {}
        self._current_index = 0

    def set_current_index(self, index: int) -> None:
        """Sets current evaluation index for chronological replay."""
        if 0 <= index < len(self.candles):
            self._current_index = index

    def has_sufficient_option_data(self) -> bool:
        """Checks exact-time snapshot, strike, and CE/PE OI coverage per candle."""
        # Date-only keys, unrelated snapshots, empty chains, or OI fields that
        # normalize to zero are not sufficient historical option coverage.
        if not self.candles or not self.option_snapshots:
            return False
        snapshots_by_time = {
            self._utc(s.timestamp): s
            for s in self.option_snapshots.values()
            if s.strikes
            and any(strike.calls_oi > 0 for strike in s.strikes)
            and any(strike.puts_oi > 0 for strike in s.strikes)
        }
        return all(self._utc(c.timestamp) in snapshots_by_time for c in self.candles)

    @staticmethod
    def _utc(ts: datetime) -> datetime:
        return (ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)

    def _option_snapshot_at(self, evaluation_ts: datetime) -> Optional[OptionChainSnapshot]:
        eligible = [
            snapshot for snapshot in self.option_snapshots.values()
            if self._utc(snapshot.timestamp) == self._utc(evaluation_ts)
        ]
        if not eligible:
            return None
        return max(
            eligible,
            key=lambda s: self._utc(s.timestamp),
        )

    def get_market_snapshot(self, timestamp: Optional[datetime] = None) -> MarketSnapshot:
        """
        Builds a historical MarketSnapshot at the current candle index.
        Uses ONLY information at or before timestamp T.
        """
        if not self.candles or self._current_index >= len(self.candles):
            return MarketSnapshot(
                timestamp=timestamp or datetime.now(timezone.utc),
                futures_price=None,
            )

        # Visible candles up to current index T
        visible_candles = self.candles[: self._current_index + 1]
        current_candle = visible_candles[-1]
        t = current_candle.timestamp
        if timestamp is not None and self._utc(timestamp) != self._utc(t):
            # The replay cursor is authoritative; never return candle data
            # from one instant under a different requested evaluation time.
            return MarketSnapshot(timestamp=timestamp, futures_price=None)

        # Futures price is directly the 5M candle close at T
        futures_price = current_candle.close

        # Historical option chain must match T exactly. Older observations are
        # stale; later observations would introduce look-ahead.
        option_chain = self._option_snapshot_at(t)

        # Previous Completed Trading Day OHLC (Must be strictly before current date)
        curr_date = t.date()
        prev_day_ohlc: Optional[PreviousDayOHLC] = None
        if self.daily_ohlc:
            prior_dates = [d for d in sorted(self.daily_ohlc.keys()) if d < curr_date.isoformat()]
            if prior_dates:
                prev_day_ohlc = self.daily_ohlc[prior_dates[-1]]
        else:
            # Aggregate from visible candles of previous dates
            prior_candles = [c for c in visible_candles if c.timestamp.date() < curr_date]
            if prior_candles:
                prior_dates = sorted(list(set(c.timestamp.date() for c in prior_candles)))
                last_completed_date = prior_dates[-1]
                day_c = [c for c in prior_candles if c.timestamp.date() == last_completed_date]
                if day_c:
                    prev_day_ohlc = PreviousDayOHLC(
                        date=last_completed_date.isoformat(),
                        high=max(c.high for c in day_c),
                        low=min(c.low for c in day_c),
                        close=day_c[-1].close,
                        open=day_c[0].open,
                    )

        # Chronological Indicators up to T
        closes = [c.close for c in visible_candles]
        highs = [c.high for c in visible_candles]
        lows = [c.low for c in visible_candles]

        e20_s = IndicatorEngine.calculate_ema_series(closes, 20)
        e50_s = IndicatorEngine.calculate_ema_series(closes, 50)
        atr_s = IndicatorEngine.calculate_atr_series(highs, lows, closes, 14)

        ema20 = e20_s[-1] if e20_s else None
        ema20_prev = e20_s[-2] if len(e20_s) > 1 else ema20
        ema50 = e50_s[-1] if e50_s else None
        atr14 = atr_s[-1] if atr_s else None

        pivot_levels = PivotEngine.calculate_pivots(prev_day_ohlc) if prev_day_ohlc else None

        return MarketSnapshot(
            timestamp=t,
            futures_price=futures_price,
            spot_price=None, # Never calculate futures from spot
            futures_candles=visible_candles,
            option_chain=option_chain,
            previous_day_ohlc=prev_day_ohlc,
            ema20=ema20,
            ema50=ema50,
            ema20_prev=ema20_prev,
            atr14=atr14,
            pivot_levels=pivot_levels,
        )
