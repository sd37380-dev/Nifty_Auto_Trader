"""
Volume Candlestick Engine for NIFTY Autonomous Trader.

Generates constant-volume candlesticks (Volume Bars) from granular minute or tick data.
Instead of arbitrary time-based buckets (e.g. 5M, 15M), volume candles close when a
predetermined quantity of volume/contracts has traded.

Benefits for Day Trading:
1. Normalizes activity: Eliminates slow lunchtime chop and noise.
2. Increases resolution during high-liquidity breakouts and opening volatility.
3. Conserves volume and computes intra-bar VWAP and execution speed.
"""

from datetime import datetime, timezone
import math
from typing import Any, Dict, List, Optional, Union
import uuid

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from nifty_trader.research_zone.contracts import NormalizedBar


class VolumeBar(BaseModel):
    """
    Standardized Constant-Volume Candlestick Model.
    """
    bar_id: str = Field(default_factory=lambda: f"vbar_{uuid.uuid4().hex[:8]}")
    symbol: str = "NIFTY"
    target_volume: int
    timestamp_start: datetime
    timestamp: datetime  # Bar close timestamp
    open: float
    high: float
    low: float
    close: float
    volume: float
    vwap: float
    trades_count: int = 0
    open_interest: int = 0
    duration_seconds: float = 0.0

    @property
    def spread(self) -> float:
        """High - Low spread."""
        return round(self.high - self.low, 2)

    @property
    def body(self) -> float:
        """Absolute candle body size."""
        return round(abs(self.close - self.open), 2)

    @property
    def is_bullish(self) -> bool:
        return self.close >= self.open


class VolumeBarAggregator:
    """
    Transforms granular price/volume bars or ticks into constant-volume candlesticks.
    """

    def __init__(self, default_target_volume: int = 10000):
        self.default_target_volume = default_target_volume

    def aggregate_from_normalized_bars(
        self,
        bars: List[NormalizedBar],
        target_volume: Optional[int] = None,
        slice_overflow: bool = True,
    ) -> List[VolumeBar]:
        """
        Aggregates a chronological sequence of NormalizedBars into VolumeBars.

        Args:
            bars: List of NormalizedBar objects sorted by timestamp.
            target_volume: Number of contracts/shares per volume candle.
            slice_overflow: When True, splits excess volume from a bar into the next candle
                            so every volume candle has exactly target_volume.
        """
        if not bars:
            return []

        target_vol = target_volume or self.default_target_volume
        if target_vol <= 0:
            raise ValueError(f"target_volume must be > 0, got {target_vol}")

        sorted_bars = sorted(bars, key=lambda b: b.timestamp)
        volume_bars: List[VolumeBar] = []

        curr_open: Optional[float] = None
        curr_high = -math.inf
        curr_low = math.inf
        curr_close = 0.0
        curr_vol = 0.0
        curr_pv = 0.0  # Sum of price * volume for VWAP
        curr_trades = 0
        curr_oi = 0
        curr_start_ts: Optional[datetime] = None

        for bar in sorted_bars:
            bar_vol = float(bar.volume)
            if bar_vol <= 0:
                continue

            bar_pv = ((bar.high + bar.low + bar.close) / 3.0) * bar_vol
            remaining_bar_vol = bar_vol

            while remaining_bar_vol > 0:
                if curr_open is None:
                    curr_open = bar.open
                    curr_high = bar.high
                    curr_low = bar.low
                    curr_start_ts = bar.timestamp

                curr_high = max(curr_high, bar.high)
                curr_low = min(curr_low, bar.low)
                curr_close = bar.close
                curr_oi = bar.open_interest

                needed_vol = target_vol - curr_vol

                if slice_overflow and remaining_bar_vol >= needed_vol:
                    # Fill the current volume candle completely
                    portion_ratio = needed_vol / bar_vol if bar_vol > 0 else 1.0
                    curr_vol += needed_vol
                    curr_pv += bar_pv * portion_ratio
                    curr_trades += max(1, int(bar.trades_count * portion_ratio))

                    duration = (bar.timestamp - curr_start_ts).total_seconds()
                    vwap_val = round(curr_pv / curr_vol, 2) if curr_vol > 0 else curr_close

                    vbar = VolumeBar(
                        symbol=bar.symbol,
                        target_volume=target_vol,
                        timestamp_start=curr_start_ts,
                        timestamp=bar.timestamp,
                        open=round(curr_open, 2),
                        high=round(curr_high, 2),
                        low=round(curr_low, 2),
                        close=round(curr_close, 2),
                        volume=round(curr_vol, 2),
                        vwap=vwap_val,
                        trades_count=curr_trades,
                        open_interest=curr_oi,
                        duration_seconds=max(0.0, duration),
                    )
                    volume_bars.append(vbar)

                    # Reset for next volume candle
                    remaining_bar_vol -= needed_vol
                    curr_open = bar.close
                    curr_high = bar.close
                    curr_low = bar.close
                    curr_close = bar.close
                    curr_vol = 0.0
                    curr_pv = 0.0
                    curr_trades = 0
                    curr_start_ts = bar.timestamp

                else:
                    # Accumulate remainder
                    curr_vol += remaining_bar_vol
                    curr_pv += bar_pv * (remaining_bar_vol / bar_vol if bar_vol > 0 else 1.0)
                    curr_trades += bar.trades_count
                    remaining_bar_vol = 0.0

        # Close final partial bar if volume accumulated
        if curr_vol > 0 and curr_open is not None and curr_start_ts is not None:
            duration = (sorted_bars[-1].timestamp - curr_start_ts).total_seconds()
            vwap_val = round(curr_pv / curr_vol, 2) if curr_vol > 0 else curr_close
            volume_bars.append(
                VolumeBar(
                    symbol=sorted_bars[-1].symbol,
                    target_volume=target_vol,
                    timestamp_start=curr_start_ts,
                    timestamp=sorted_bars[-1].timestamp,
                    open=round(curr_open, 2),
                    high=round(curr_high, 2),
                    low=round(curr_low, 2),
                    close=round(curr_close, 2),
                    volume=round(curr_vol, 2),
                    vwap=vwap_val,
                    trades_count=curr_trades,
                    open_interest=curr_oi,
                    duration_seconds=max(0.0, duration),
                )
            )

        return volume_bars

    def aggregate_from_dataframe(
        self,
        df: pd.DataFrame,
        target_volume: Optional[int] = None,
        slice_overflow: bool = True,
    ) -> pd.DataFrame:
        """
        Aggregates a standard OHLCV DataFrame into a Volume-based OHLCV DataFrame.

        Required columns in df:
            ['timestamp', 'open', 'high', 'low', 'close', 'volume']
        """
        if df.empty:
            return pd.DataFrame()

        target_vol = target_volume or self.default_target_volume
        df = df.copy()

        # Ensure datetime timestamps
        if not pd.api.types.is_datetime64_any_dtype(df["timestamp"]):
            df["timestamp"] = pd.to_datetime(df["timestamp"])

        df = df.sort_values("timestamp").reset_index(drop=True)

        bars = []
        for _, row in df.iterrows():
            bars.append(
                NormalizedBar(
                    symbol=str(row.get("symbol", "NIFTY")),
                    timeframe="1M",
                    timestamp=row["timestamp"].to_pydatetime() if hasattr(row["timestamp"], "to_pydatetime") else row["timestamp"],
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=int(row["volume"]),
                    open_interest=int(row.get("open_interest", 0)),
                    vwap=float(row.get("vwap", 0.0)),
                    trades_count=int(row.get("trades_count", 1)),
                )
            )

        vbars = self.aggregate_from_normalized_bars(
            bars=bars,
            target_volume=target_vol,
            slice_overflow=slice_overflow,
        )

        rows = []
        for vb in vbars:
            rows.append({
                "timestamp": vb.timestamp,
                "timestamp_start": vb.timestamp_start,
                "open": vb.open,
                "high": vb.high,
                "low": vb.low,
                "close": vb.close,
                "volume": vb.volume,
                "vwap": vb.vwap,
                "duration_seconds": vb.duration_seconds,
                "trades_count": vb.trades_count,
                "open_interest": vb.open_interest,
            })

        return pd.DataFrame(rows)
