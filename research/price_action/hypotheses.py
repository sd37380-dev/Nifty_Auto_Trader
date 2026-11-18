"""
Mathematical Definitions of Price-Action Hypotheses for 5-Year NIFTY Research.
All signals return Optional[Tuple[Direction, float]] where float is the base SL level.
Strictly look-ahead-free: signals depend solely on bar i and prior bars.
"""

from datetime import time
from typing import Callable, Dict, List, Optional, Tuple
import pandas as pd
import numpy as np

from nifty_trader.strategies.price_validation_strategy import Direction
from research.price_action.engine import HypothesisDefinition


def get_all_hypotheses() -> List[HypothesisDefinition]:
    """Returns the master list of 12 predefined price-action hypotheses."""

    # -----------------------------------------------------------------
    # H01: ORB-15 Breakout Continuation
    # -----------------------------------------------------------------
    def signal_h01(df: pd.DataFrame, i: int) -> Optional[Tuple[Direction, float]]:
        t = df['time_ist'].iloc[i]
        if not (time(9, 30) <= t <= time(11, 30)):
            return None
        orb_h = df['orb15_high'].iloc[i]
        orb_l = df['orb15_low'].iloc[i]
        if pd.isna(orb_h) or pd.isna(orb_l):
            return None

        c = df['close'].iloc[i]
        o = df['open'].iloc[i]
        l = df['low'].iloc[i]
        h = df['high'].iloc[i]
        prev_c = df['prev_close'].iloc[i]
        body_ratio = df['body_ratio'].iloc[i]

        # Long: first breakout above ORB high with solid body
        if c > orb_h and prev_c <= orb_h and body_ratio >= 0.35 and c > o:
            return (Direction.LONG, l)
        # Short: first breakout below ORB low with solid body
        if c < orb_l and prev_c >= orb_l and body_ratio >= 0.35 and c < o:
            return (Direction.SHORT, h)
        return None

    h01 = HypothesisDefinition(
        hypothesis_id="H01_ORB15_BREAKOUT",
        name="ORB-15 Breakout Continuation",
        category="BREAKOUT",
        description="First candle breaking out of initial 15-minute range between 09:30 and 11:30 IST.",
        signal_func=signal_h01,
        target_rr=2.0,
        sl_buffer=5.0,
    )

    # -----------------------------------------------------------------
    # H02: ORB-30 Breakout Continuation
    # -----------------------------------------------------------------
    def signal_h02(df: pd.DataFrame, i: int) -> Optional[Tuple[Direction, float]]:
        t = df['time_ist'].iloc[i]
        if not (time(9, 45) <= t <= time(12, 0)):
            return None
        orb_h = df['orb30_high'].iloc[i]
        orb_l = df['orb30_low'].iloc[i]
        if pd.isna(orb_h) or pd.isna(orb_l):
            return None

        c = df['close'].iloc[i]
        o = df['open'].iloc[i]
        l = df['low'].iloc[i]
        h = df['high'].iloc[i]
        prev_c = df['prev_close'].iloc[i]
        body_ratio = df['body_ratio'].iloc[i]

        if c > orb_h and prev_c <= orb_h and body_ratio >= 0.35 and c > o:
            return (Direction.LONG, l)
        if c < orb_l and prev_c >= orb_l and body_ratio >= 0.35 and c < o:
            return (Direction.SHORT, h)
        return None

    h02 = HypothesisDefinition(
        hypothesis_id="H02_ORB30_BREAKOUT",
        name="ORB-30 Breakout Continuation",
        category="BREAKOUT",
        description="First candle breaking out of initial 30-minute range between 09:45 and 12:00 IST.",
        signal_func=signal_h02,
        target_rr=2.0,
        sl_buffer=5.0,
    )

    # -----------------------------------------------------------------
    # H03: Previous Day High / Low (PDH/PDL) Breakout Continuation
    # -----------------------------------------------------------------
    def signal_h03(df: pd.DataFrame, i: int) -> Optional[Tuple[Direction, float]]:
        pdh = df['pdh'].iloc[i]
        pdl = df['pdl'].iloc[i]
        if pd.isna(pdh) or pd.isna(pdl):
            return None

        c = df['close'].iloc[i]
        o = df['open'].iloc[i]
        l = df['low'].iloc[i]
        h = df['high'].iloc[i]
        prev_c = df['prev_close'].iloc[i]

        # Breakout above PDH
        if c > pdh and prev_c <= pdh and c > o:
            return (Direction.LONG, l)
        # Breakout below PDL
        if c < pdl and prev_c >= pdl and c < o:
            return (Direction.SHORT, h)
        return None

    h03 = HypothesisDefinition(
        hypothesis_id="H03_PDH_PDL_BREAKOUT",
        name="PDH / PDL Breakout Continuation",
        category="BREAKOUT",
        description="First 5M candle breaking and closing beyond previous day's high or low.",
        signal_func=signal_h03,
        target_rr=2.0,
        sl_buffer=5.0,
    )

    # -----------------------------------------------------------------
    # H04: Inside-Bar Compression Breakout
    # -----------------------------------------------------------------
    def signal_h04(df: pd.DataFrame, i: int) -> Optional[Tuple[Direction, float]]:
        if i < 2:
            return None
        # Previous bar was inside bar
        was_inside = df['is_inside_bar'].iloc[i - 1]
        if not was_inside:
            return None

        mother_h = df['high'].iloc[i - 2]
        mother_l = df['low'].iloc[i - 2]
        c = df['close'].iloc[i]
        o = df['open'].iloc[i]
        l = df['low'].iloc[i]
        h = df['high'].iloc[i]

        # Bullish breakout above mother bar high
        if c > mother_h and c > o:
            return (Direction.LONG, mother_l)
        # Bearish breakout below mother bar low
        if c < mother_l and c < o:
            return (Direction.SHORT, mother_h)
        return None

    h04 = HypothesisDefinition(
        hypothesis_id="H04_INSIDE_BAR_BREAKOUT",
        name="Inside-Bar Breakout",
        category="COMPRESSION",
        description="Expansion candle breaking out beyond the range of a previous inside-bar mother candle.",
        signal_func=signal_h04,
        target_rr=2.0,
        sl_buffer=5.0,
    )

    # -----------------------------------------------------------------
    # H05: PDH / PDL Liquidity Sweep & Failure (Reversal / Trap)
    # -----------------------------------------------------------------
    def signal_h05(df: pd.DataFrame, i: int) -> Optional[Tuple[Direction, float]]:
        pdh = df['pdh'].iloc[i]
        pdl = df['pdl'].iloc[i]
        if pd.isna(pdh) or pd.isna(pdl):
            return None

        h = df['high'].iloc[i]
        l = df['low'].iloc[i]
        c = df['close'].iloc[i]
        upper_wick_ratio = df['upper_wick_ratio'].iloc[i]
        lower_wick_ratio = df['lower_wick_ratio'].iloc[i]

        # Sweep High: penetrates above PDH but closes back inside with rejection wick
        if h > pdh and c < pdh and upper_wick_ratio >= 0.35:
            return (Direction.SHORT, h)

        # Sweep Low: penetrates below PDL but closes back inside with rejection wick
        if l < pdl and c > pdl and lower_wick_ratio >= 0.35:
            return (Direction.LONG, l)

        return None

    h05 = HypothesisDefinition(
        hypothesis_id="H05_PDH_PDL_SWEEP_REVERSAL",
        name="PDH / PDL Liquidity Sweep & Reversal",
        category="REVERSAL",
        description="False breakout trap: price pierces PDH/PDL but closes back inside with long rejection wick.",
        signal_func=signal_h05,
        target_rr=2.0,
        sl_buffer=5.0,
    )

    # -----------------------------------------------------------------
    # H06: First-Hour High/Low Liquidity Sweep & Reversal
    # -----------------------------------------------------------------
    def signal_h06(df: pd.DataFrame, i: int) -> Optional[Tuple[Direction, float]]:
        t = df['time_ist'].iloc[i]
        if not (time(10, 15) <= t <= time(14, 0)):
            return None

        fh_h = df['first_hour_high'].iloc[i]
        fh_l = df['first_hour_low'].iloc[i]
        if pd.isna(fh_h) or pd.isna(fh_l):
            return None

        h = df['high'].iloc[i]
        l = df['low'].iloc[i]
        c = df['close'].iloc[i]
        upper_wick_ratio = df['upper_wick_ratio'].iloc[i]
        lower_wick_ratio = df['lower_wick_ratio'].iloc[i]

        # Pierces First-Hour High then closes below with upper rejection wick
        if h > fh_h and c < fh_h and upper_wick_ratio >= 0.35:
            return (Direction.SHORT, h)
        # Pierces First-Hour Low then closes above with lower rejection wick
        if l < fh_l and c > fh_l and lower_wick_ratio >= 0.35:
            return (Direction.LONG, l)
        return None

    h06 = HypothesisDefinition(
        hypothesis_id="H06_FIRST_HOUR_SWEEP_REVERSAL",
        name="First-Hour High/Low Sweep Reversal",
        category="REVERSAL",
        description="Intraday false breakout of 10:15 first-hour boundaries followed by mean-reversion wick.",
        signal_func=signal_h06,
        target_rr=2.0,
        sl_buffer=5.0,
    )

    # -----------------------------------------------------------------
    # H07: Dynamic EMA20 Pin-Bar / Long-Wick Rejection
    # -----------------------------------------------------------------
    def signal_h07(df: pd.DataFrame, i: int) -> Optional[Tuple[Direction, float]]:
        is_bull_pin = df['is_bullish_pinbar'].iloc[i]
        is_bear_pin = df['is_bearish_pinbar'].iloc[i]
        ema20 = df['ema20'].iloc[i]
        ema50 = df['ema50'].iloc[i]
        l = df['low'].iloc[i]
        h = df['high'].iloc[i]
        c = df['close'].iloc[i]

        # Bullish pinbar testing EMA20 during uptrend (EMA20 > EMA50)
        if is_bull_pin and ema20 > ema50 and l <= ema20 and c >= ema20:
            return (Direction.LONG, l)

        # Bearish pinbar testing EMA20 during downtrend (EMA20 < EMA50)
        if is_bear_pin and ema20 < ema50 and h >= ema20 and c <= ema20:
            return (Direction.SHORT, h)

        return None

    h07 = HypothesisDefinition(
        hypothesis_id="H07_EMA20_PINBAR_REJECTION",
        name="Dynamic EMA20 Pin-Bar Rejection",
        category="REVERSAL",
        description="Pin-bar wick testing dynamic 20-period EMA aligned with dominant 50-period trend.",
        signal_func=signal_h07,
        target_rr=2.0,
        sl_buffer=5.0,
    )

    # -----------------------------------------------------------------
    # H08: Engulfing Candle Reversal at Session Extreme
    # -----------------------------------------------------------------
    def signal_h08(df: pd.DataFrame, i: int) -> Optional[Tuple[Direction, float]]:
        bull_engulf = df['is_bullish_engulfing'].iloc[i]
        bear_engulf = df['is_bearish_engulfing'].iloc[i]
        sess_h = df['session_high_prev'].iloc[i]
        sess_l = df['session_low_prev'].iloc[i]
        if pd.isna(sess_h) or pd.isna(sess_l):
            return None

        l = df['low'].iloc[i]
        h = df['high'].iloc[i]

        # Bullish engulfing occurring near session low (within 10 pts)
        if bull_engulf and (l <= sess_l + 10.0):
            return (Direction.LONG, l)

        # Bearish engulfing occurring near session high (within 10 pts)
        if bear_engulf and (h >= sess_h - 10.0):
            return (Direction.SHORT, h)

        return None

    h08 = HypothesisDefinition(
        hypothesis_id="H08_SESSION_EXTREME_ENGULFING",
        name="Session Extreme Engulfing Reversal",
        category="REVERSAL",
        description="Engulfing pattern occurring at intraday session extreme indicating momentum exhaustion.",
        signal_func=signal_h08,
        target_rr=2.0,
        sl_buffer=5.0,
    )

    # -----------------------------------------------------------------
    # H09: 3-Consecutive Directional Candle Exhaustion Reversal
    # -----------------------------------------------------------------
    def signal_h09(df: pd.DataFrame, i: int) -> Optional[Tuple[Direction, float]]:
        if i < 4:
            return None
        consec_prev = df['consec_dir_candles'].iloc[i - 1]
        c = df['close'].iloc[i]
        o = df['open'].iloc[i]
        l = df['low'].iloc[i]
        h = df['high'].iloc[i]
        close_pos = df['close_position'].iloc[i]

        # Prior 3+ candles were consecutive bearish, current candle is strong bullish rejection
        if consec_prev <= -3 and c > o and close_pos >= 0.70:
            return (Direction.LONG, l)

        # Prior 3+ candles were consecutive bullish, current candle is strong bearish rejection
        if consec_prev >= 3 and c < o and close_pos <= 0.30:
            return (Direction.SHORT, h)

        return None

    h09 = HypothesisDefinition(
        hypothesis_id="H09_CONSECUTIVE_EXHAUSTION",
        name="3-Candle Exhaustion Reversal",
        category="REVERSAL",
        description="Exhaustion reversal candle following 3 or more consecutive directional thrust candles.",
        signal_func=signal_h09,
        target_rr=2.0,
        sl_buffer=5.0,
    )

    # -----------------------------------------------------------------
    # H10: Morning Momentum Breakout (09:30–10:30 only with 15M Trend)
    # -----------------------------------------------------------------
    def signal_h10(df: pd.DataFrame, i: int) -> Optional[Tuple[Direction, float]]:
        t = df['time_ist'].iloc[i]
        if not (time(9, 30) <= t <= time(10, 30)):
            return None

        sess_h = df['session_high_prev'].iloc[i]
        sess_l = df['session_low_prev'].iloc[i]
        if pd.isna(sess_h) or pd.isna(sess_l):
            return None

        c = df['close'].iloc[i]
        o = df['open'].iloc[i]
        l = df['low'].iloc[i]
        h = df['high'].iloc[i]
        prev_h = df['prev_high'].iloc[i]
        prev_l = df['prev_low'].iloc[i]
        trend_l_15m = df['trend_long_15m'].iloc[i]
        trend_s_15m = df['trend_short_15m'].iloc[i]
        body_ratio = df['body_ratio'].iloc[i]

        if trend_l_15m and h > sess_h and c > prev_h and body_ratio >= 0.40 and c > o:
            return (Direction.LONG, l)

        if trend_s_15m and l < sess_l and c < prev_l and body_ratio >= 0.40 and c < o:
            return (Direction.SHORT, h)

        return None

    h10 = HypothesisDefinition(
        hypothesis_id="H10_MORNING_MOMENTUM_BREAKOUT",
        name="Morning Momentum Breakout",
        category="REGIME_FILTERED",
        description="Opening session momentum expansion between 09:30 and 10:30 aligned with 15M trend.",
        signal_func=signal_h10,
        target_rr=2.0,
        sl_buffer=5.0,
    )

    # -----------------------------------------------------------------
    # H11: Afternoon Session Sweep & Mean-Reversion (12:30–14:30)
    # -----------------------------------------------------------------
    def signal_h11(df: pd.DataFrame, i: int) -> Optional[Tuple[Direction, float]]:
        t = df['time_ist'].iloc[i]
        if not (time(12, 30) <= t <= time(14, 30)):
            return None

        sess_h = df['session_high_prev'].iloc[i]
        sess_l = df['session_low_prev'].iloc[i]
        if pd.isna(sess_h) or pd.isna(sess_l):
            return None

        h = df['high'].iloc[i]
        l = df['low'].iloc[i]
        c = df['close'].iloc[i]
        o = df['open'].iloc[i]
        upper_wick_ratio = df['upper_wick_ratio'].iloc[i]
        lower_wick_ratio = df['lower_wick_ratio'].iloc[i]

        # Sweeps new session high in afternoon but fails to hold and forms upper wick
        if h > sess_h and c < o and upper_wick_ratio >= 0.40:
            return (Direction.SHORT, h)

        # Sweeps new session low in afternoon but fails to hold and forms lower wick
        if l < sess_l and c > o and lower_wick_ratio >= 0.40:
            return (Direction.LONG, l)

        return None

    h11 = HypothesisDefinition(
        hypothesis_id="H11_AFTERNOON_SWEEP_REVERSAL",
        name="Afternoon Sweep & Mean Reversion",
        category="REGIME_FILTERED",
        description="Midday liquidity grab: price sweeps session high/low between 12:30 and 14:30 followed by rejection.",
        signal_func=signal_h11,
        target_rr=2.0,
        sl_buffer=5.0,
    )

    # -----------------------------------------------------------------
    # H12: NR4 Compression Breakout with 15M Trend Filter
    # -----------------------------------------------------------------
    def signal_h12(df: pd.DataFrame, i: int) -> Optional[Tuple[Direction, float]]:
        if i < 5:
            return None
        # Bar i-1 was Narrowest Range of 4 bars (NR4)
        r1 = df['range'].iloc[i - 1]
        r2 = df['range'].iloc[i - 2]
        r3 = df['range'].iloc[i - 3]
        r4 = df['range'].iloc[i - 4]
        is_nr4 = (r1 < r2) and (r1 < r3) and (r1 < r4)
        if not is_nr4:
            return None

        nr4_h = df['high'].iloc[i - 1]
        nr4_l = df['low'].iloc[i - 1]
        c = df['close'].iloc[i]
        o = df['open'].iloc[i]
        trend_l_15m = df['trend_long_15m'].iloc[i]
        trend_s_15m = df['trend_short_15m'].iloc[i]

        if trend_l_15m and c > nr4_h and c > o:
            return (Direction.LONG, nr4_l)

        if trend_s_15m and c < nr4_l and c < o:
            return (Direction.SHORT, nr4_h)

        return None

    h12 = HypothesisDefinition(
        hypothesis_id="H12_NR4_COMPRESSION_BREAKOUT",
        name="NR4 Compression Breakout",
        category="COMPRESSION",
        description="Volatility contraction breakout following the narrowest 5M candle of the last 4 candles.",
        signal_func=signal_h12,
        target_rr=2.0,
        sl_buffer=5.0,
    )

    return [h01, h02, h03, h04, h05, h06, h07, h08, h09, h10, h11, h12]
