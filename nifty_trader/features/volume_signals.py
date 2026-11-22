"""
High-Volume Candlestick Pattern Detector & Day Trading Signal Engine.

Implements Volume-Price Analysis (VPA) / Wyckoff principles for precise intraday entries:
1. Relative Volume (RVOL) calculation vs. rolling moving averages.
2. Volume Breakout Confirmation (Expansion + High RVOL + Extreme Close).
3. Institutional Absorption Detection (High RVOL with rejection wicks / Effort vs. Result).
4. Volume Climax Exhaustion (Exhaustion bars signaling reversals).
5. Automatic Invalidation Stop Loss & Profit Target calculations.
"""

from typing import Any, Dict, Optional, Tuple
import numpy as np
import pandas as pd


class VolumePatternDetector:
    """
    Computes Volume-Price Analysis (VPA) metrics and generates day trading signals.
    Can operate on standard time bars (1M, 5M, 15M) or constant-volume bars.
    """

    def __init__(
        self,
        vol_ma_period: int = 20,
        rvol_threshold: float = 1.8,
        atr_period: int = 14,
    ):
        self.vol_ma_period = vol_ma_period
        self.rvol_threshold = rvol_threshold
        self.atr_period = atr_period

    def compute_volume_metrics(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculates RVOL, ATR, Spreads, Wicks, and Close Location Value (CLV).
        """
        df = df.copy()

        close = df["close"]
        high = df["high"]
        low = df["low"]
        open_ = df["open"]
        volume = df["volume"]

        # 1. Rolling Volume MA and Relative Volume (RVOL)
        df["vol_ma"] = volume.rolling(self.vol_ma_period, min_periods=1).mean()
        # Avoid division by zero
        df["rvol"] = np.where(df["vol_ma"] > 0, round(volume / df["vol_ma"], 2), 1.0)

        # 2. Average True Range (ATR)
        prev_close = close.shift(1).fillna(open_)
        tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
        df["atr"] = tr.rolling(self.atr_period, min_periods=1).mean()

        # 3. Candle Geometry
        spread = (high - low).clip(lower=1e-5)
        df["spread"] = spread
        df["spread_ratio"] = df["spread"] / df["atr"].clip(lower=1e-5)
        df["body"] = (close - open_).abs()
        df["body_ratio"] = df["body"] / spread

        # Upper and Lower Wicks
        df["upper_wick"] = high - np.maximum(open_, close)
        df["lower_wick"] = np.minimum(open_, close) - low
        df["upper_wick_ratio"] = df["upper_wick"] / spread
        df["lower_wick_ratio"] = df["lower_wick"] / spread

        # 4. Close Location Value (CLV): -1.0 (at low) to +1.0 (at high)
        df["clv"] = round(((close - low) - (high - close)) / spread, 2)

        # 5. Effort vs Result (Volume per point of price movement)
        df["effort_vs_result"] = round(volume / spread, 2)

        # 6. Order Flow Buyer & Seller Contribution (Volume Delta Approximation)
        # Buyer Ratio = (Close - Low) / Spread (0.0 to 1.0)
        buyer_pct = ((close - low) / spread).clip(0.0, 1.0)
        df["buyer_pct"] = buyer_pct.round(2)
        df["seller_pct"] = (1.0 - buyer_pct).round(2)
        df["buyer_volume"] = (volume * df["buyer_pct"]).round(0)
        df["seller_volume"] = (volume * df["seller_pct"]).round(0)
        df["net_delta"] = (df["buyer_volume"] - df["seller_volume"]).round(0)

        # 7. Trend Reference (20 EMA)
        df["ema_20"] = close.ewm(span=20, adjust=False).mean()

        return df

    def detect_signals(
        self,
        df: pd.DataFrame,
        rvol_thresh: Optional[float] = None,
        use_absorption: bool = True,
        use_breakouts: bool = True,
        use_climax: bool = True,
    ) -> pd.DataFrame:
        """
        Identifies high-conviction day trading entry opportunities based on volume candles.
        """
        df = self.compute_volume_metrics(df)
        thresh = rvol_thresh or self.rvol_threshold

        # Initialize condition columns
        df["vol_breakout_long"] = False
        df["vol_breakout_short"] = False
        df["vol_absorption_long"] = False
        df["vol_absorption_short"] = False
        df["vol_climax_reversal_long"] = False
        df["vol_climax_reversal_short"] = False

        high_vol = df["rvol"] >= thresh
        expansion = df["spread_ratio"] >= 1.20

        # 1. High Volume Breakout Confirmation
        if use_breakouts:
            # Bullish expansion closing in top 25% of range above EMA 20
            df["vol_breakout_long"] = (
                high_vol & expansion & (df["clv"] >= 0.50) & (df["close"] > df["ema_20"])
            )
            # Bearish expansion closing in bottom 25% of range below EMA 20
            df["vol_breakout_short"] = (
                high_vol & expansion & (df["clv"] <= -0.50) & (df["close"] < df["ema_20"])
            )

        # 2. Institutional Absorption (Effort vs. Result / Rejection)
        if use_absorption:
            # Bullish: Heavy volume test of lows with strong lower wick rejection
            df["vol_absorption_long"] = (
                high_vol & (df["lower_wick_ratio"] >= 0.35) & (df["clv"] >= 0.0)
            )
            # Bearish: Heavy volume test of highs with strong upper wick rejection
            df["vol_absorption_short"] = (
                high_vol & (df["upper_wick_ratio"] >= 0.35) & (df["clv"] <= 0.0)
            )

        # 3. Climax Exhaustion Reversal
        if use_climax:
            ultra_high_vol = df["rvol"] >= max(2.5, thresh * 1.3)
            # Exhaustion sell flush: massive volume down spike, then hammer / reversal
            df["vol_climax_reversal_long"] = (
                ultra_high_vol & (df["lower_wick_ratio"] >= 0.40) & (df["close"] < df["ema_20"])
            )
            # Exhaustion buying blowoff: massive volume up spike, then shooting star / reversal
            df["vol_climax_reversal_short"] = (
                ultra_high_vol & (df["upper_wick_ratio"] >= 0.40) & (df["close"] > df["ema_20"])
            )

        # Unified Day Trading Signals
        df["long_condition"] = (
            df["vol_breakout_long"] | df["vol_absorption_long"] | df["vol_climax_reversal_long"]
        )
        df["short_condition"] = (
            df["vol_breakout_short"] | df["vol_absorption_short"] | df["vol_climax_reversal_short"]
        )

        # Suggested Risk Management Anchor Prices
        # Long Stop Loss: Low of the volume candle minus small buffer (0.1% or 0.2 ATR)
        df["suggested_sl_long"] = np.where(
            df["long_condition"],
            (df["low"] - 0.2 * df["atr"]).round(2),
            np.nan,
        )
        # Short Stop Loss: High of the volume candle plus small buffer
        df["suggested_sl_short"] = np.where(
            df["short_condition"],
            (df["high"] + 0.2 * df["atr"]).round(2),
            np.nan,
        )

        return df
