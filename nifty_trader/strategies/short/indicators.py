"""
Indicator and ATM Engine for NIFTY Futures Short Strategy.

Calculates:
- ATM and ATM ±5 strikes (11 strikes) based on Futures price
- EMA20, EMA50, ATR14 computed chronologically on 5-minute candles
- Bearish trend conditions
- EMA distance validation
"""

from typing import List, Optional, Tuple


class IndicatorEngine:
    """
    Deterministic technical indicator and ATM calculation engine.
    Ensures zero look-ahead bias and strict mathematical correctness.
    """

    @staticmethod
    def calculate_atm_strike(futures_price: float, strike_step: float = 50.0) -> float:
        """
        Calculates ATM strike from current Futures price.
        Example: Futures = 23891.25 -> ATM = 23900.
        """
        return round(futures_price / strike_step) * strike_step

    @staticmethod
    def get_atm_plus_minus_5_strikes(futures_price: float, strike_step: float = 50.0) -> List[float]:
        """
        Returns exactly 11 strikes centered at ATM (ATM - 5 to ATM + 5).
        """
        atm = IndicatorEngine.calculate_atm_strike(futures_price, strike_step)
        return [atm + (i * strike_step) for i in range(-5, 6)]

    @staticmethod
    def calculate_ema_series(data: List[float], period: int) -> List[Optional[float]]:
        """
        Chronological Exponential Moving Average.
        Uses initial SMA seed followed by standard exponential smoothing.
        """
        if len(data) < period:
            return [None] * len(data)

        multiplier = 2.0 / (period + 1)
        initial_sma = sum(data[:period]) / period
        res: List[Optional[float]] = [None] * (period - 1)
        res.append(initial_sma)

        current_ema = initial_sma
        for val in data[period:]:
            current_ema = (val - current_ema) * multiplier + current_ema
            res.append(current_ema)

        return res

    @staticmethod
    def calculate_atr_series(
        highs: List[float],
        lows: List[float],
        closes: List[float],
        period: int = 14,
    ) -> List[Optional[float]]:
        """
        Chronological Average True Range (ATR 14).
        """
        if len(closes) <= period:
            return [None] * len(closes)

        tr: List[float] = [highs[0] - lows[0]]
        for i in range(1, len(closes)):
            h = highs[i]
            l = lows[i]
            prev_c = closes[i - 1]
            true_range = max(h - l, abs(h - prev_c), abs(l - prev_c))
            tr.append(true_range)

        res: List[Optional[float]] = [None] * (period - 1)
        # Initial ATR seed as SMA of TR
        initial_atr = sum(tr[:period]) / period
        res.append(initial_atr)

        current_atr = initial_atr
        for val in tr[period:]:
            # Wilder's smoothing: (prev_atr * (period - 1) + tr) / period
            current_atr = (current_atr * (period - 1) + val) / period
            res.append(current_atr)

        return res

    @staticmethod
    def check_bearish_trend(
        futures_price: float,
        ema20: Optional[float],
        ema50: Optional[float],
        ema20_prev: Optional[float],
    ) -> Tuple[bool, str]:
        """
        Evaluates bearish trend conditions:
        1. FUTURES_PRICE < EMA20
        2. EMA20 < EMA50
        3. EMA20_CURRENT < EMA20_PREVIOUS
        """
        if ema20 is None or ema50 is None:
            return False, "EMA data unavailable"

        if ema20_prev is None:
            ema20_prev = ema20

        cond1 = futures_price < ema20
        cond2 = ema20 < ema50
        cond3 = ema20 < ema20_prev

        is_bearish = cond1 and cond2 and cond3
        if not is_bearish:
            return False, "BEARISH TREND NOT CONFIRMED"

        return True, "OK"

    @staticmethod
    def check_ema_distance(
        futures_price: float,
        ema20: Optional[float],
        atr14: Optional[float],
        multiplier: float = 0.25,
    ) -> Tuple[bool, Optional[float], str]:
        """
        Evaluates distance of Futures price to EMA20:
        EMA_DISTANCE = EMA20 - FUTURES_PRICE
        MAX_EMA_DISTANCE = ATR14 * multiplier
        Conditions: EMA_DISTANCE >= 0 AND EMA_DISTANCE <= MAX_EMA_DISTANCE
        """
        if ema20 is None:
            return False, None, "EMA20 unavailable"
        if atr14 is None or atr14 <= 0:
            return False, None, "ATR14 unavailable"

        if futures_price >= ema20:
            return False, ema20 - futures_price, "PRICE ABOVE EMA20"

        ema_distance = ema20 - futures_price
        max_ema_distance = atr14 * multiplier

        if ema_distance > max_ema_distance:
            return False, ema_distance, "PRICE TOO FAR BELOW EMA20"

        return True, ema_distance, "OK"
