"""
Data Loader & Quantitative Feature Engineering for Price-Action Research.
Loads 5-minute NIFTY Spot series, applies strict market session filtering,
and calculates price-action features with ZERO look-ahead.
"""

from datetime import datetime, time, timezone
import sqlite3
from typing import Dict, List, Optional, Tuple
import numpy as np
import pandas as pd


def load_and_clean_nifty_5m(
    db_path: str = "data/hermes_research/market_data.db"
) -> Tuple[pd.DataFrame, Dict[str, any]]:
    """
    Loads raw 5M NIFTY bars from SQLite, flags corrupted bars, filters to
    standard NSE market hours (09:15 - 15:30 IST), and attaches day/time metadata.
    """
    conn = sqlite3.connect(db_path)
    df_raw = pd.read_sql_query("""
        SELECT bar_id, symbol, timeframe, timestamp, open, high, low, close, volume, open_interest
        FROM normalized_bars
        WHERE symbol = 'NIFTY' AND timeframe = '5M'
        ORDER BY timestamp ASC
    """, conn)
    conn.close()

    total_loaded = len(df_raw)

    # Convert timestamp to UTC and IST
    df = df_raw.copy()
    df['dt_utc'] = pd.to_datetime(df['timestamp'], format='ISO8601')
    df['dt_ist'] = df['dt_utc'].dt.tz_convert('Asia/Kolkata')
    df['date_ist'] = df['dt_ist'].dt.date
    df['time_ist'] = df['dt_ist'].dt.time
    df['day_of_week'] = df['dt_ist'].dt.dayofweek

    # Candle close time: 5m bar starts at dt_utc, ends at dt_utc + 5 min
    df['close_time_utc'] = df['dt_utc'] + pd.Timedelta(minutes=5)
    df['close_time_ist'] = df['dt_ist'] + pd.Timedelta(minutes=5)

    # Detect corrupted OHLC bars
    invalid_mask = (
        (df['high'] < df['low']) |
        (df['high'] < df['open']) |
        (df['high'] < df['close']) |
        (df['low'] > df['open']) |
        (df['low'] > df['close']) |
        (df['open'] <= 0) | (df['close'] <= 0)
    )
    invalid_count = invalid_mask.sum()
    invalid_rows = df[invalid_mask][['timestamp', 'open', 'high', 'low', 'close']].to_dict(orient='records')

    # Flag invalid bars
    df['is_valid_ohlc'] = ~invalid_mask

    # Market session filter: Standard regular trading 09:15 to 15:25 bar start (15:25 bar closes at 15:30)
    # Weekdays: Monday(0) to Friday(4). Keep special Muhurat sessions only if within standard times.
    regular_hours_mask = (df['time_ist'] >= time(9, 15)) & (df['time_ist'] <= time(15, 25))
    df = df[regular_hours_mask].copy()

    # Sort strictly by timestamp
    df = df.sort_values('dt_utc').reset_index(drop=True)

    metadata = {
        "total_loaded": total_loaded,
        "total_in_session": len(df),
        "invalid_ohlc_count": int(invalid_count),
        "invalid_rows": invalid_rows,
        "unique_trading_days": df['date_ist'].nunique(),
        "earliest_ist": str(df['dt_ist'].min()),
        "latest_ist": str(df['dt_ist'].max()),
    }

    return df, metadata


def compute_price_action_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Computes candle structural features, technical indicators, and look-ahead-free
    session/previous-day levels.
    """
    df = df.copy()

    if 'close_time_utc' not in df.columns:
        df['close_time_utc'] = df['dt_utc'] + pd.Timedelta(minutes=5)
    if 'close_time_ist' not in df.columns:
        df['close_time_ist'] = df['dt_ist'] + pd.Timedelta(minutes=5)

    # 1. Basic Candle Geometry
    # Add epsilon to prevent division by zero on rare doji candles
    candle_range = df['high'] - df['low']
    safe_range = np.where(candle_range == 0, 0.05, candle_range)
    df['range'] = candle_range
    df['body_size'] = (df['close'] - df['open']).abs()
    df['body_ratio'] = df['body_size'] / safe_range

    upper_wick = df['high'] - np.maximum(df['open'], df['close'])
    lower_wick = np.minimum(df['open'], df['close']) - df['low']
    df['upper_wick'] = upper_wick
    df['lower_wick'] = lower_wick
    df['upper_wick_ratio'] = upper_wick / safe_range
    df['lower_wick_ratio'] = lower_wick / safe_range
    df['close_position'] = (df['close'] - df['low']) / safe_range

    df['is_bullish'] = df['close'] > df['open']
    df['is_bearish'] = df['close'] < df['open']
    df['is_doji'] = df['body_ratio'] <= 0.10

    # 2. Previous Bar Relationships
    df['prev_open'] = df['open'].shift(1)
    df['prev_high'] = df['high'].shift(1)
    df['prev_low'] = df['low'].shift(1)
    df['prev_close'] = df['close'].shift(1)
    df['prev_range'] = df['range'].shift(1)

    # Inside Bar & Outside Bar
    df['is_inside_bar'] = (df['high'] <= df['prev_high']) & (df['low'] >= df['prev_low'])
    df['is_outside_bar'] = (df['high'] > df['prev_high']) & (df['low'] < df['prev_low'])

    # Engulfing Patterns
    df['is_bullish_engulfing'] = (
        (df['prev_close'] < df['prev_open']) &  # Previous candle was bearish
        (df['close'] > df['open']) &            # Current candle is bullish
        (df['close'] >= df['prev_open']) &      # Closes above previous open
        (df['open'] <= df['prev_close'])        # Opens at or below previous close
    )
    df['is_bearish_engulfing'] = (
        (df['prev_close'] > df['prev_open']) &  # Previous candle was bullish
        (df['close'] < df['open']) &            # Current candle is bearish
        (df['close'] <= df['prev_open']) &      # Closes below previous open
        (df['open'] >= df['prev_close'])        # Opens at or above previous close
    )

    # Pin Bars (Hammer / Shooting Star style rejection wicks)
    df['is_bullish_pinbar'] = (
        (df['lower_wick_ratio'] >= 0.60) &
        (df['upper_wick_ratio'] <= 0.20) &
        (df['close_position'] >= 0.65)
    )
    df['is_bearish_pinbar'] = (
        (df['upper_wick_ratio'] >= 0.60) &
        (df['lower_wick_ratio'] <= 0.20) &
        (df['close_position'] <= 0.35)
    )

    # Consecutive Candles
    # Consecutive direction counter (up to 5 candles)
    dir_sign = np.where(df['close'] > df['open'], 1, np.where(df['close'] < df['open'], -1, 0))
    consec = np.zeros(len(df), dtype=int)
    current_count = 0
    current_dir = 0
    for i in range(len(df)):
        d = dir_sign[i]
        if d == current_dir and d != 0:
            current_count += 1
        else:
            current_dir = d
            current_count = 1 if d != 0 else 0
        consec[i] = current_count * current_dir
    df['consec_dir_candles'] = consec

    # 3. Technical Indicators
    # True Range & ATR14 (Wilder's)
    tr1 = df['high'] - df['low']
    tr2 = (df['high'] - df['prev_close']).abs()
    tr3 = (df['low'] - df['prev_close']).abs()
    df['tr'] = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    df['atr14'] = df['tr'].ewm(alpha=1.0 / 14, adjust=False).mean()

    # Moving Averages
    df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()
    df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()
    df['ema200'] = df['close'].ewm(span=200, adjust=False).mean()

    # 4. Previous-Day Levels (Strictly Look-Ahead-Free)
    # Aggregate daily bars first
    daily_bars = df.groupby('date_ist').agg(
        day_open=('open', 'first'),
        day_high=('high', 'max'),
        day_low=('low', 'min'),
        day_close=('close', 'last'),
        day_volume=('volume', 'sum'),
        bar_count=('open', 'count')
    ).reset_index()

    # Shift daily stats by 1 to get PREVIOUS DAY values
    daily_bars['pdh'] = daily_bars['day_high'].shift(1)
    daily_bars['pdl'] = daily_bars['day_low'].shift(1)
    daily_bars['pdc'] = daily_bars['day_close'].shift(1)
    daily_bars['pdo'] = daily_bars['day_open'].shift(1)
    daily_bars['p_range'] = (daily_bars['pdh'] - daily_bars['pdl']).shift(1)

    # Merge back onto 5M dataframe by date_ist
    df = pd.merge(
        df,
        daily_bars[['date_ist', 'day_open', 'pdh', 'pdl', 'pdc', 'pdo']],
        on='date_ist',
        how='left'
    )
    df['opening_gap'] = df['day_open'] - df['pdc']

    # 5. Intraday Session Reference Levels (Rolling Look-Ahead-Free)
    # Group by date to compute cumulative session high/low up to bar T-1
    # On bar 0 of the day (09:15), session high/low so far does not exist yet.
    df['session_high_prev'] = df.groupby('date_ist')['high'].shift(1).groupby(df['date_ist']).cummax()
    df['session_low_prev'] = df.groupby('date_ist')['low'].shift(1).groupby(df['date_ist']).cummin()

    # Opening Range Breakout (ORB) Levels:
    # ORB 15: 09:15-09:30 (bars at 09:15, 09:20, 09:25). Ready at 09:30 open!
    orb15_df = df[df['time_ist'] < time(9, 30)].groupby('date_ist').agg(
        orb15_high=('high', 'max'),
        orb15_low=('low', 'min')
    ).reset_index()
    df = pd.merge(df, orb15_df, on='date_ist', how='left')

    # ORB 30: 09:15-09:45 (bars at 09:15 to 09:40). Ready at 09:45 open!
    orb30_df = df[df['time_ist'] < time(9, 45)].groupby('date_ist').agg(
        orb30_high=('high', 'max'),
        orb30_low=('low', 'min')
    ).reset_index()
    df = pd.merge(df, orb30_df, on='date_ist', how='left')

    # First Hour: 09:15-10:15 (bars at 09:15 to 10:10). Ready at 10:15 open!
    first_hour_df = df[df['time_ist'] < time(10, 15)].groupby('date_ist').agg(
        first_hour_high=('high', 'max'),
        first_hour_low=('low', 'min')
    ).reset_index()
    df = pd.merge(df, first_hour_df, on='date_ist', how='left')

    # 6. Higher Timeframe Resampling (15M & 1H with Zero Look-Ahead)
    # Resample 5M to 15M
    df_15m = df.set_index('dt_utc').resample('15min', closed='left', label='left').agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last'
    }).dropna().reset_index()
    df_15m['close_time_utc'] = df_15m['dt_utc'] + pd.Timedelta(minutes=15)
    df_15m['ema20_15m'] = df_15m['close'].ewm(span=20, adjust=False).mean()
    df_15m['ema50_15m'] = df_15m['close'].ewm(span=50, adjust=False).mean()
    df_15m['trend_long_15m'] = (df_15m['close'] > df_15m['ema20_15m']) & (df_15m['ema20_15m'] > df_15m['ema50_15m'])
    df_15m['trend_short_15m'] = (df_15m['close'] < df_15m['ema20_15m']) & (df_15m['ema20_15m'] < df_15m['ema50_15m'])

    # Merge 15M onto 5M where 15M close_time <= 5M close_time
    cols_15 = ['close_time_utc', 'trend_long_15m', 'trend_short_15m', 'ema20_15m']
    df_15_sub = df_15m[cols_15].rename(columns={'close_time_utc': 'tf15_closed_at'})
    if not df_15_sub.empty:
        df = df.sort_values('close_time_utc').reset_index(drop=True)
        df_15_sub = df_15_sub.sort_values('tf15_closed_at').reset_index(drop=True)
        df = pd.merge_asof(
            df,
            df_15_sub,
            left_on='close_time_utc',
            right_on='tf15_closed_at',
            direction='backward'
        )
    else:
        df['trend_long_15m'] = False
        df['trend_short_15m'] = False
        df['ema20_15m'] = df['close']

    df['trend_long_15m'] = df['trend_long_15m'].fillna(False).astype(bool)
    df['trend_short_15m'] = df['trend_short_15m'].fillna(False).astype(bool)

    # 7. Time of Day Classification
    def classify_tod(t: time) -> str:
        if t < time(9, 30):
            return "09:15-09:30"
        elif t < time(10, 0):
            return "09:30-10:00"
        elif t < time(11, 0):
            return "10:00-11:00"
        elif t < time(12, 0):
            return "11:00-12:00"
        elif t < time(13, 0):
            return "12:00-13:00"
        elif t < time(14, 0):
            return "13:00-14:00"
        elif t < time(15, 0):
            return "14:00-15:00"
        else:
            return "15:00-15:25"

    df['tod_bucket'] = df['time_ist'].apply(classify_tod)

    return df


if __name__ == "__main__":
    df_clean, meta = load_and_clean_nifty_5m()
    print("Metadata:", meta)
    df_feats = compute_price_action_features(df_clean)
    print("Features shape:", df_feats.shape)
    print("Columns:", df_feats.columns.tolist())
    print("\nSample 3 rows:")
    print(df_feats[['dt_ist', 'time_ist', 'open', 'high', 'low', 'close', 'range', 'body_ratio', 'pdh', 'pdl', 'orb15_high']].head(3))
