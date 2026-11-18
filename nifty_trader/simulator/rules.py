"""
Base Strategy Rule Framework and Standard Local Quantitative Rules.

Allows local evaluation of NIFTY market conditions and candlestick patterns
WITHOUT calling external LLM APIs, providing deterministic, fast, zero-latency execution.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
import numpy as np
import pandas as pd

from nifty_trader.simulator.contracts import OptionPosition, SignalType, TradeSignal


class BaseStrategyRule(ABC):
    """
    Abstract base class for all local trading rules.
    Users can inherit from this class to define custom rules.
    """
    name: str = "BaseRule"
    description: str = "Generic Rule"

    @abstractmethod
    def on_candle(
        self,
        candle: pd.Series,
        indicators: Dict[str, Any],
        active_position: Optional[OptionPosition] = None,
    ) -> TradeSignal:
        """
        Evaluates current spot candle and technical indicators.

        Args:
            candle: Current bar containing ['spot_open', 'spot_high', 'spot_low', 'spot_close', 'spot_vol', 'time_str', 'date']
            indicators: Precalculated indicators dictionary (e.g. ema_14, pivots, rsi, vwap, etc.)
            active_position: Current open OptionPosition if in trade, or None if flat.

        Returns:
            TradeSignal with SignalType.BUY_CE, BUY_PE, CLOSE, or HOLD.
        """
        pass


class EMAPivotBounceRule(BaseStrategyRule):
    """
    Empirically validated rule:
    - Long (BUY CE): Spot tests support (S1/CPR/Pivot) and closes above EMA14 with bullish momentum.
    - Short (BUY PE): Spot tests resistance (R1/CPR/Pivot) and closes below EMA14 with bearish momentum.
    - Risk & Reward: 25% of Option Premium as Stop Loss, 1:2.5 or 1:3 RR target.
    """
    name = "EMA14_CPR_Pivot_Bounce"
    description = "Trades bounces and trend continuations off daily CPR pivots conforming to EMA 14."

    def __init__(
        self,
        risk_pct: float = 0.25,
        risk_reward: float = 2.5,
        min_sl_pts: float = 15.0,
        trailing_sl: bool = True,
        trail_pts: float = 10.0,
    ):
        self.risk_pct = risk_pct
        self.risk_reward = risk_reward
        self.min_sl_pts = min_sl_pts
        self.trailing_sl = trailing_sl
        self.trail_pts = trail_pts

    def on_candle(
        self,
        candle: pd.Series,
        indicators: Dict[str, Any],
        active_position: Optional[OptionPosition] = None,
    ) -> TradeSignal:
        # If already in a position, let SL/TP manage it unless early close condition met
        if active_position is not None:
            return TradeSignal(signal_type=SignalType.HOLD, reason="Position Active")

        time_str = candle.get("time_str", "")
        # Avoid first 15 mins (09:15 - 09:30) and after 14:30 IST
        if not ("09:30" <= time_str <= "14:15"):
            return TradeSignal(signal_type=SignalType.HOLD, reason="Outside Entry Window")

        sc = candle["spot_close"]
        so = candle["spot_open"]
        sh = candle["spot_high"]
        sl = candle["spot_low"]
        e14 = indicators.get("ema_14", sc)

        s_levels = [
            indicators.get("s1", 0.0),
            indicators.get("cpr_bot", 0.0),
            indicators.get("pivot", 0.0),
        ]
        r_levels = [
            indicators.get("r1", 0.0),
            indicators.get("cpr_top", 0.0),
            indicators.get("pivot", 0.0),
        ]

        # Spot near support level within 25 points or tested and recovered
        near_support = any(abs(sl - s) <= 25.0 or (sl < s and sc > s) for s in s_levels if s > 0)
        # Spot near resistance level within 25 points or rejected
        near_resistance = any(abs(sh - r) <= 25.0 or (sh > r and sc < r) for r in r_levels if r > 0)

        # Bullish Trigger: Bounced off support, green candle, and trading above EMA 14
        if near_support and sc > e14 and sc > so:
            return TradeSignal(
                signal_type=SignalType.BUY_CE,
                reason=f"Support bounce at {round(sl, 1)} above EMA14 ({round(e14, 1)})",
                sl_points=self.min_sl_pts,
                target_points=self.min_sl_pts * self.risk_reward,
                trailing_sl=self.trailing_sl,
                trail_points=self.trail_pts,
            )

        # Bearish Trigger: Rejected resistance, red candle, and trading below EMA 14
        elif near_resistance and sc < e14 and sc < so:
            return TradeSignal(
                signal_type=SignalType.BUY_PE,
                reason=f"Resistance rejection at {round(sh, 1)} below EMA14 ({round(e14, 1)})",
                sl_points=self.min_sl_pts,
                target_points=self.min_sl_pts * self.risk_reward,
                trailing_sl=self.trailing_sl,
                trail_points=self.trail_pts,
            )

        return TradeSignal(signal_type=SignalType.HOLD, reason="No Setup Detected")


class SupertrendMomentumRule(BaseStrategyRule):
    """
    Momentum breakout rule using Supertrend + RSI filter:
    - BUY CE when Close > Supertrend and RSI > 55
    - BUY PE when Close < Supertrend and RSI < 45
    """
    name = "Supertrend_RSI_Momentum"
    description = "Directional trend following using Supertrend with RSI momentum filter."

    def __init__(self, target_pts: float = 40.0, sl_pts: float = 20.0, trailing_sl: bool = True):
        self.target_pts = target_pts
        self.sl_pts = sl_pts
        self.trailing_sl = trailing_sl

    def on_candle(
        self,
        candle: pd.Series,
        indicators: Dict[str, Any],
        active_position: Optional[OptionPosition] = None,
    ) -> TradeSignal:
        if active_position is not None:
            return TradeSignal(signal_type=SignalType.HOLD, reason="Position Active")

        time_str = candle.get("time_str", "")
        if not ("09:30" <= time_str <= "14:15"):
            return TradeSignal(signal_type=SignalType.HOLD, reason="Outside Entry Window")

        sc = candle["spot_close"]
        st = indicators.get("supertrend", sc)
        st_dir = indicators.get("supertrend_dir", 0) # 1 = Bullish, -1 = Bearish
        rsi = indicators.get("rsi", 50.0)

        # Bullish
        if st_dir == 1 and rsi > 55.0 and sc > st:
            return TradeSignal(
                signal_type=SignalType.BUY_CE,
                reason=f"Bullish Supertrend with RSI {round(rsi, 1)} > 55",
                sl_points=self.sl_pts,
                target_points=self.target_pts,
                trailing_sl=self.trailing_sl,
                trail_points=10.0,
            )
        # Bearish
        elif st_dir == -1 and rsi < 45.0 and sc < st:
            return TradeSignal(
                signal_type=SignalType.BUY_PE,
                reason=f"Bearish Supertrend with RSI {round(rsi, 1)} < 45",
                sl_points=self.sl_pts,
                target_points=self.target_pts,
                trailing_sl=self.trailing_sl,
                trail_points=10.0,
            )

        return TradeSignal(signal_type=SignalType.HOLD, reason="Neutral Trend")
