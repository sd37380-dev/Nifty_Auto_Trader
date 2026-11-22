"""
Volume Candle Day Trading Strategy (.py)
=========================================
Integrated Day Trading Strategy combining Volume-Price Analysis (VPA) and Trend Confluence.

Setup & Entry Logic:
1. Relative Volume (RVOL) Surge: Filters for institutional liquidity (RVOL >= threshold).
2. Volume Expansion Breakout:
   - Wide spread candle (> ATR) closing near its high/low (Close Location Value |CLV| >= 0.40).
   - Direction aligned with EMA 20 and EMA 50 (Trend Filter).
3. Institutional Absorption (Effort vs. Result):
   - Heavy volume rejection wick (>= 35% of total candle range).
   - Price rejected off EMA 20 / VWMA dynamic support/resistance.
4. Signal Debouncing: Ensures fresh triggers at the start of a move rather than redundant whipsaws.

Returns:
  df: DataFrame with required ['long_condition'] and ['short_condition'] boolean columns
  overlays: Chart overlay lines (e.g. EMA 20, EMA 50, VWMA 20)
"""

import numpy as np
import pandas as pd

from nifty_trader.features.volume_signals import VolumePatternDetector


def generate_signals(df: pd.DataFrame, params: dict):
    """
    Day trading entry strategy based on volume candles and volume-price analysis.
    """
    df = df.copy()

    # User-defined parameters
    rvol_thresh = float(params.get("rvol_threshold", 1.5))
    vol_ma_period = int(params.get("vol_ma_period", 20))
    atr_period = int(params.get("atr_period", 14))
    use_breakouts = bool(params.get("use_breakouts", True))
    use_absorption = bool(params.get("use_absorption", True))
    use_trend_filter = bool(params.get("use_trend_filter", True))

    detector = VolumePatternDetector(
        vol_ma_period=vol_ma_period,
        rvol_threshold=rvol_thresh,
        atr_period=atr_period,
    )

    df = detector.compute_volume_metrics(df)

    # 1. Moving Averages for Trend Confluence
    close = df["close"]
    volume = df["volume"]
    df["ema_20"] = close.ewm(span=20, adjust=False).mean()
    df["ema_50"] = close.ewm(span=50, adjust=False).mean()

    # 2. Volume-Weighted Moving Average (VWMA 20)
    pv = close * volume
    vol_roll = volume.rolling(20, min_periods=1).sum().clip(lower=1.0)
    df["vwma_20"] = (pv.rolling(20, min_periods=1).sum() / vol_roll).round(2)

    # 3. Base Filters
    high_vol = df["rvol"] >= rvol_thresh
    expansion = df["spread_ratio"] >= 1.05

    bull_trend = (df["close"] > df["ema_20"]) & (df["ema_20"] >= df["ema_50"]) if use_trend_filter else True
    bear_trend = (df["close"] < df["ema_20"]) & (df["ema_20"] <= df["ema_50"]) if use_trend_filter else True

    # 4. Pattern Conditions with Buyer/Seller Delta Rule (Buyer >= 60% for CE, Seller >= 60% for PE)
    buyer_dominant = df["buyer_pct"] >= float(params.get("min_buyer_pct", 0.60))
    seller_dominant = df["seller_pct"] >= float(params.get("min_seller_pct", 0.60))

    # Breakout with Delta Confirmation
    long_breakout = high_vol & expansion & (df["clv"] >= 0.40) & bull_trend & buyer_dominant if use_breakouts else False
    short_breakout = high_vol & expansion & (df["clv"] <= -0.40) & bear_trend & seller_dominant if use_breakouts else False

    # Absorption at Support/Resistance
    long_absorption = high_vol & (df["lower_wick_ratio"] >= 0.35) & (df["clv"] >= 0.0) & (df["close"] >= df["ema_50"]) & buyer_dominant if use_absorption else False
    short_absorption = high_vol & (df["upper_wick_ratio"] >= 0.35) & (df["clv"] <= 0.0) & (df["close"] <= df["ema_50"]) & seller_dominant if use_absorption else False

    raw_long = long_breakout | long_absorption
    raw_short = short_breakout | short_absorption

    # 5. Debounce: Only trigger on the initial entry candle (first bar of trigger)
    prev_long = raw_long.shift(1).fillna(False).astype(bool)
    prev_short = raw_short.shift(1).fillna(False).astype(bool)
    df["long_condition"] = raw_long & (~prev_long)
    df["short_condition"] = raw_short & (~prev_short)

    overlays = {
        "EMA 20": {"color": "#38bdf8", "series": df["ema_20"].round(2)},
        "EMA 50": {"color": "#f59e0b", "series": df["ema_50"].round(2)},
        "VWMA 20": {"color": "#a855f7", "series": df["vwma_20"]},
    }

    return df, overlays
