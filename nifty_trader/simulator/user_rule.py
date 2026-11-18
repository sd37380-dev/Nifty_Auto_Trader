"""
========================================================================================
                  USER CUSTOM TRADING RULE CONFIGURATION
========================================================================================
Edit this file to define your own custom local trading rules!
No AI or external API calls are made — execution is 100% local, fast, and deterministic.

Available Candle Fields:
- candle['spot_open']  : Open price of NIFTY spot
- candle['spot_high']  : High price of NIFTY spot
- candle['spot_low']   : Low price of NIFTY spot
- candle['spot_close'] : Close price of NIFTY spot
- candle['spot_vol']   : Bar volume
- candle['time_str']   : Time of day in IST (e.g., '09:30', '13:15')

Available Indicators Dictionary:
- indicators['ema_9']        : 9-period Exponential Moving Average
- indicators['ema_14']       : 14-period Exponential Moving Average
- indicators['ema_21']       : 21-period Exponential Moving Average
- indicators['ema_50']       : 50-period Exponential Moving Average
- indicators['ema_200']      : 200-period Exponential Moving Average
- indicators['vwap']         : Intraday Volume Weighted Average Price
- indicators['rsi']          : 14-period RSI (0 - 100)
- indicators['supertrend']   : Supertrend value (10, 3)
- indicators['supertrend_dir']: Supertrend direction (1 = Bullish, -1 = Bearish)
- indicators['pivot']        : Daily Standard Pivot Point
- indicators['r1']           : Daily Resistance 1
- indicators['s1']           : Daily Support 1
- indicators['cpr_top']      : Top Central Pivot (CPR)
- indicators['cpr_bot']      : Bottom Central Pivot (CPR)
- indicators['atr']          : 14-period Average True Range

Return Values:
- TradeSignal(SignalType.BUY_CE, reason="...", sl_points=20.0, target_points=40.0, trailing_sl=True)
- TradeSignal(SignalType.BUY_PE, reason="...", sl_points=20.0, target_points=40.0, trailing_sl=True)
- TradeSignal(SignalType.HOLD, reason="No setup")
========================================================================================
"""

from typing import Any, Dict, Optional
import pandas as pd

from nifty_trader.simulator.contracts import OptionPosition, SignalType, TradeSignal
from nifty_trader.simulator.rules import BaseStrategyRule


class CustomUserRule(BaseStrategyRule):
    """
    Your custom trading rule.
    Modify the logic inside `on_candle` below to test your own strategies!
    """
    name = "My_Custom_Strategy"
    description = "User-defined custom local strategy for NIFTY Options paper trading."

    def __init__(
        self,
        target_points: float = 35.0,  # Target gain in option premium (e.g. Rs. 35)
        sl_points: float = 18.0,      # Stop loss in option premium (e.g. Rs. 18)
        trailing_sl: bool = True,     # Enable trailing stop loss
        trail_step: float = 10.0,     # Trail every 10 points
    ):
        self.target_points = target_points
        self.sl_points = sl_points
        self.trailing_sl = trailing_sl
        self.trail_step = trail_step

    def on_candle(
        self,
        candle: pd.Series,
        indicators: Dict[str, Any],
        active_position: Optional[OptionPosition] = None,
    ) -> TradeSignal:
        """
        Write your trading logic here!
        Called on every candle (5M or 15M).
        """
        # If we already have an open position, let SL and Target manage it
        if active_position is not None:
            return TradeSignal(signal_type=SignalType.HOLD, reason="Position already active")

        # Time filter: Only enter trades between 09:30 and 14:15 IST
        time_str = candle.get("time_str", "")
        if not ("09:30" <= time_str <= "14:15"):
            return TradeSignal(signal_type=SignalType.HOLD, reason="Outside trading hours")

        # Current Price
        spot_close = candle["spot_close"]
        spot_open = candle["spot_open"]

        # Indicator values
        ema_9 = indicators.get("ema_9", spot_close)
        ema_21 = indicators.get("ema_21", spot_close)
        rsi = indicators.get("rsi", 50.0)
        vwap = indicators.get("vwap", spot_close)
        st_dir = indicators.get("supertrend_dir", 0)

        # -------------------------------------------------------------
        # EXAMPLE RULE (You can change this!):
        # 1. BUY CALL (CE) Setup:
        #    - 9 EMA is above 21 EMA (Short-term trend is UP)
        #    - Price is above intraday VWAP
        #    - RSI is bullish between 55 and 70 (not overbought)
        # -------------------------------------------------------------
        bullish_setup = (ema_9 > ema_21) and (spot_close > vwap) and (55.0 <= rsi <= 72.0)

        if bullish_setup:
            return TradeSignal(
                signal_type=SignalType.BUY_CE,
                reason=f"Bullish EMA crossover (9 > 21) & Close above VWAP with RSI={round(rsi, 1)}",
                sl_points=self.sl_points,
                target_points=self.target_points,
                trailing_sl=self.trailing_sl,
                trail_points=self.trail_step,
            )

        # -------------------------------------------------------------
        # 2. BUY PUT (PE) Setup:
        #    - 9 EMA is below 21 EMA (Short-term trend is DOWN)
        #    - Price is below intraday VWAP
        #    - RSI is bearish between 30 and 45 (not oversold)
        # -------------------------------------------------------------
        bearish_setup = (ema_9 < ema_21) and (spot_close < vwap) and (28.0 <= rsi <= 45.0)

        if bearish_setup:
            return TradeSignal(
                signal_type=SignalType.BUY_PE,
                reason=f"Bearish EMA crossover (9 < 21) & Close below VWAP with RSI={round(rsi, 1)}",
                sl_points=self.sl_points,
                target_points=self.target_points,
                trailing_sl=self.trailing_sl,
                trail_points=self.trail_step,
            )

        # Default: No trade condition met
        return TradeSignal(signal_type=SignalType.HOLD, reason="Waiting for setup")
