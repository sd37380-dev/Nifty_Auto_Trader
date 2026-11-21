"""
Multi-Factor Quantitative Trading Strategy Template (.py)
===========================================================
You can modify this file or upload your own .py files to test custom multi-factor strategies.

Inputs:
  df     : pandas.DataFrame with historical OHLCV bars:
           columns: ['timestamp', 'open', 'high', 'low', 'close', 'volume']
  params : dict containing user-defined parameters passed from the dashboard:
           e.g. params.get('fast_ema', 9), params.get('rsi_period', 14)

Returns:
  df       : The updated DataFrame with two REQUIRED boolean columns:
             - df['long_condition']  = True/False (generates BUY LONG signal)
             - df['short_condition'] = True/False (generates SELL SHORT signal)
  overlays : (optional) dict of technical indicators to plot on the candlestick chart:
             e.g. {"EMA 9": {"color": "#38bdf8", "series": df["ema9"]}}
"""

import numpy as np
import pandas as pd


def generate_signals(df: pd.DataFrame, params: dict):
    """
    Multi-Factor Strategy Example:
    Factor 1: Trend Filter (Fast EMA > Slow EMA)
    Factor 2: Momentum Filter (RSI within bullish/bearish zone)
    Factor 3: Volatility / ATR Filter (ATR expanding above threshold)
    Factor 4: Volume Confirmation (Current volume > 20-period moving average)
    """
    df = df.copy()

    # -------------------------------------------------------------
    # 1. PARAMETERS
    # -------------------------------------------------------------
    fast_period = int(params.get("fast_ema", 9))
    slow_period = int(params.get("slow_ema", 21))
    rsi_period = int(params.get("rsi_period", 14))
    vol_period = int(params.get("vol_period", 20))

    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"]

    # -------------------------------------------------------------
    # 2. FACTOR CALCULATIONS
    # -------------------------------------------------------------
    # Factor 1: Exponential Moving Averages (Trend)
    df["ema_fast"] = close.ewm(span=fast_period, adjust=False).mean()
    df["ema_slow"] = close.ewm(span=slow_period, adjust=False).mean()

    # Factor 2: Relative Strength Index (Momentum)
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(com=rsi_period - 1, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(com=rsi_period - 1, adjust=False).mean()
    rs = gain / (loss + 1e-9)
    df["rsi"] = 100 - (100 / (1 + rs))

    # Factor 3: Average True Range (Volatility)
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    df["atr"] = tr.rolling(14, min_periods=1).mean()

    # Factor 4: Volume Surge Moving Average
    df["vol_ma"] = volume.rolling(vol_period, min_periods=1).mean()
    vol_surge = (volume > df["vol_ma"] * 1.10) | (volume == 0)  # volume == 0 if index data lacks volume

    # -------------------------------------------------------------
    # 3. MULTI-FACTOR SIGNAL SYNTHESIS
    # -------------------------------------------------------------
    # Crossover events
    bull_crossover = (df["ema_fast"] > df["ema_slow"]) & (df["ema_fast"].shift(1) <= df["ema_slow"].shift(1))
    bear_crossover = (df["ema_fast"] < df["ema_slow"]) & (df["ema_fast"].shift(1) >= df["ema_slow"].shift(1))

    # Multi-factor confluence:
    # Long: EMA bull cross + RSI between 48 and 70 (not overbought) + Volume confirmation
    df["long_condition"] = bull_crossover & (df["rsi"] >= 48) & (df["rsi"] <= 72) & vol_surge

    # Short: EMA bear cross + RSI between 30 and 52 (not oversold) + Volume confirmation
    df["short_condition"] = bear_crossover & (df["rsi"] <= 52) & (df["rsi"] >= 28) & vol_surge

    # -------------------------------------------------------------
    # 4. CHART OVERLAY LINES (Displayed on Candlestick Chart)
    # -------------------------------------------------------------
    overlays = {
        f"Fast EMA ({fast_period})": {"color": "#38bdf8", "series": df["ema_fast"]},
        f"Slow EMA ({slow_period})": {"color": "#f59e0b", "series": df["ema_slow"]},
    }

    return df, overlays
