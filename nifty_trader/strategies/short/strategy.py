"""
NIFTY Futures Short Strategy Engine.

Unified implementation used identically in:
1. Live Mode
2. Paper-Trading Mode
3. Historical Backtest Mode

Implements the 10-step bearish confluence architecture:
Broker Market Data -> Live/Historical Futures -> Live/Historical Options ->
ATM ±5 Option Chain -> OI Resistance Engine -> Pivot Engine ->
EMA20 / EMA50 / ATR14 -> Bearish Trend Confirmation ->
OI + Pivot Resistance Confluence -> Bearish Price Rejection ->
Short Strategy -> Risk Engine -> Approval Engine.
"""

from datetime import datetime
import logging
from typing import Optional, Tuple

from nifty_trader.strategies.short.approval import ApprovalEngine
from nifty_trader.strategies.short.contracts import (
    Candle5M,
    MarketSnapshot,
    PivotLevels,
    ShortStrategyConfig,
    SignalType,
    StrategyResult,
)
from nifty_trader.strategies.short.indicators import IndicatorEngine
from nifty_trader.strategies.short.oi_resistance import OIResistanceEngine
from nifty_trader.strategies.short.pivot import PivotEngine

logger = logging.getLogger(__name__)


class NiftyFuturesShortStrategy:
    """
    Isolated, broker-agnostic NIFTY Futures SHORT Strategy.
    Receives normalized MarketSnapshot and evaluates short setups deterministically.
    """

    def __init__(
        self,
        config: Optional[ShortStrategyConfig] = None,
        approval_engine: Optional[ApprovalEngine] = None,
    ):
        self.config = config or ShortStrategyConfig()
        self.approval_engine = approval_engine or ApprovalEngine(config=self.config)

    def evaluate(
        self,
        snapshot: MarketSnapshot,
        has_active_position: bool = False,
        bypass_risk_engine: bool = False,
    ) -> StrategyResult:
        """
        Evaluates the MarketSnapshot against all 10 SHORT conditions.
        Returns a rich StrategyResult containing the signal, debug telemetry,
        and precise no-signal reasons.
        """
        ts = snapshot.timestamp

        # ----------------------------------------------------------------------
        # 1. FUTURES DATA VALIDATION (CRITICAL INVARIANT)
        # ----------------------------------------------------------------------
        # NEVER calculate Futures from Spot. Spot and Futures are separate instruments.
        if snapshot.futures_price is None or not snapshot.futures_candles:
            result = StrategyResult(
                signal=SignalType.NO_SIGNAL,
                reason="FUTURES DATA UNAVAILABLE",
                timestamp=ts,
            )
            result.debug_output = result.format_debug_output()
            return result

        futures_price = snapshot.futures_price
        rejection_candle = snapshot.futures_candles[-1]

        # ----------------------------------------------------------------------
        # 2. OPTION DATA VALIDATION
        # ----------------------------------------------------------------------
        if snapshot.option_chain is None or not snapshot.option_chain.strikes:
            result = StrategyResult(
                signal=SignalType.NO_SIGNAL,
                reason="OPTION DATA UNAVAILABLE",
                timestamp=ts,
                futures_price=futures_price,
            )
            result.debug_output = result.format_debug_output()
            return result

        # ----------------------------------------------------------------------
        # 3. ATM CALCULATION (ATM ±5 Strikes = 11 strikes)
        # ----------------------------------------------------------------------
        atm_strike = IndicatorEngine.calculate_atm_strike(futures_price, strike_step=50.0)
        atm_strikes = IndicatorEngine.get_atm_plus_minus_5_strikes(futures_price, strike_step=50.0)

        # ----------------------------------------------------------------------
        # 4. OI RESISTANCE ENGINE (CALL OI)
        # ----------------------------------------------------------------------
        oi_resistance, oi_resistance_strength = OIResistanceEngine.identify_call_oi_resistance(
            futures_price=futures_price,
            option_chain=snapshot.option_chain,
            atm_strikes=atm_strikes,
        )

        if oi_resistance is None:
            result = StrategyResult(
                signal=SignalType.NO_SIGNAL,
                reason="OI RESISTANCE NOT FOUND",
                timestamp=ts,
                futures_price=futures_price,
                atm_strike=atm_strike,
            )
            result.debug_output = result.format_debug_output()
            return result

        # ----------------------------------------------------------------------
        # 5. PIVOT RESISTANCE ENGINE
        # ----------------------------------------------------------------------
        pivots = snapshot.pivot_levels
        if pivots is None and snapshot.previous_day_ohlc is not None:
            pivots = PivotEngine.calculate_pivots(snapshot.previous_day_ohlc)

        pivot_resistance = PivotEngine.identify_pivot_resistance(futures_price, pivots)
        if pivot_resistance is None:
            result = StrategyResult(
                signal=SignalType.NO_SIGNAL,
                reason="PIVOT RESISTANCE NOT FOUND",
                timestamp=ts,
                futures_price=futures_price,
                atm_strike=atm_strike,
                oi_resistance=oi_resistance,
                oi_resistance_strength=oi_resistance_strength,
            )
            result.debug_output = result.format_debug_output()
            return result

        # ----------------------------------------------------------------------
        # 6. OI + PIVOT RESISTANCE CONFLUENCE
        # ----------------------------------------------------------------------
        resistance_distance = abs(oi_resistance - pivot_resistance)
        is_confluent = resistance_distance <= self.config.max_resistance_distance

        if not is_confluent:
            result = StrategyResult(
                signal=SignalType.NO_SIGNAL,
                reason="OI RESISTANCE AND PIVOT RESISTANCE NOT IN CONFLUENCE",
                timestamp=ts,
                futures_price=futures_price,
                atm_strike=atm_strike,
                oi_resistance=oi_resistance,
                oi_resistance_strength=oi_resistance_strength,
                pivot_resistance=pivot_resistance,
                resistance_distance=resistance_distance,
            )
            result.debug_output = result.format_debug_output()
            return result

        # ----------------------------------------------------------------------
        # 7. INDICATOR CALCULATIONS (EMA20, EMA50, ATR14)
        # ----------------------------------------------------------------------
        ema20 = snapshot.ema20
        ema50 = snapshot.ema50
        ema20_prev = snapshot.ema20_prev
        atr14 = snapshot.atr14

        # Compute on the fly if not pre-computed in snapshot
        if ema20 is None or ema50 is None or atr14 is None:
            closes = [c.close for c in snapshot.futures_candles]
            highs = [c.high for c in snapshot.futures_candles]
            lows = [c.low for c in snapshot.futures_candles]

            ema20_series = IndicatorEngine.calculate_ema_series(closes, self.config.ema_fast)
            ema50_series = IndicatorEngine.calculate_ema_series(closes, self.config.ema_trend)
            atr14_series = IndicatorEngine.calculate_atr_series(highs, lows, closes, self.config.atr_period)

            ema20 = ema20_series[-1] if ema20_series else None
            ema20_prev = ema20_series[-2] if len(ema20_series) > 1 else ema20
            ema50 = ema50_series[-1] if ema50_series else None
            atr14 = atr14_series[-1] if atr14_series else None

        # ----------------------------------------------------------------------
        # 8. PRICE BELOW EMA20
        # ----------------------------------------------------------------------
        if ema20 is None or futures_price >= ema20:
            result = StrategyResult(
                signal=SignalType.NO_SIGNAL,
                reason="PRICE ABOVE EMA20",
                timestamp=ts,
                futures_price=futures_price,
                atm_strike=atm_strike,
                ema20=ema20,
                ema50=ema50,
                ema20_prev=ema20_prev,
                atr14=atr14,
                oi_resistance=oi_resistance,
                oi_resistance_strength=oi_resistance_strength,
                pivot_resistance=pivot_resistance,
                resistance_distance=resistance_distance,
                trend_bearish=False,
                price_below_ema20=False,
            )
            result.debug_output = result.format_debug_output()
            return result

        # ----------------------------------------------------------------------
        # 9. BEARISH TREND CONFIRMATION
        # ----------------------------------------------------------------------
        is_trend_bearish, trend_msg = IndicatorEngine.check_bearish_trend(
            futures_price=futures_price,
            ema20=ema20,
            ema50=ema50,
            ema20_prev=ema20_prev,
        )

        if not is_trend_bearish:
            result = StrategyResult(
                signal=SignalType.NO_SIGNAL,
                reason="BEARISH TREND NOT CONFIRMED",
                timestamp=ts,
                futures_price=futures_price,
                atm_strike=atm_strike,
                ema20=ema20,
                ema50=ema50,
                ema20_prev=ema20_prev,
                atr14=atr14,
                oi_resistance=oi_resistance,
                oi_resistance_strength=oi_resistance_strength,
                pivot_resistance=pivot_resistance,
                resistance_distance=resistance_distance,
                trend_bearish=False,
                price_below_ema20=True,
            )
            result.debug_output = result.format_debug_output()
            return result

        # ----------------------------------------------------------------------
        # 10. PRICE CLOSE TO EMA20 (EMA DISTANCE <= ATR14 * MULTIPLIER)
        # ----------------------------------------------------------------------
        dist_ok, ema_distance, dist_msg = IndicatorEngine.check_ema_distance(
            futures_price=futures_price,
            ema20=ema20,
            atr14=atr14,
            multiplier=self.config.ema_distance_atr_multiplier,
        )

        if not dist_ok:
            result = StrategyResult(
                signal=SignalType.NO_SIGNAL,
                reason=dist_msg,
                timestamp=ts,
                futures_price=futures_price,
                atm_strike=atm_strike,
                ema20=ema20,
                ema50=ema50,
                ema20_prev=ema20_prev,
                atr14=atr14,
                ema_distance=ema_distance,
                oi_resistance=oi_resistance,
                oi_resistance_strength=oi_resistance_strength,
                pivot_resistance=pivot_resistance,
                resistance_distance=resistance_distance,
                trend_bearish=True,
                price_below_ema20=True,
                ema_distance_ok=False,
            )
            result.debug_output = result.format_debug_output()
            return result

        # ----------------------------------------------------------------------
        # 11. BEARISH PRICE REJECTION FROM RESISTANCE ZONE
        # ----------------------------------------------------------------------
        # Zone lower boundary is min(OI_RESISTANCE, PIVOT_RESISTANCE)
        zone_lower = min(oi_resistance, pivot_resistance)

        # Condition 1: Candle High pushed into or above zone lower boundary
        # Condition 2: Candle Close failed below the resistance zone
        # Condition 3: Candle Close < Candle Open (bearish red candle)
        is_rejection = (
            (rejection_candle.high >= zone_lower)
            and (rejection_candle.close < zone_lower)
            and (rejection_candle.close < rejection_candle.open)
        )

        if not is_rejection:
            result = StrategyResult(
                signal=SignalType.NO_SIGNAL,
                reason="NO BEARISH RESISTANCE REJECTION",
                timestamp=ts,
                futures_price=futures_price,
                atm_strike=atm_strike,
                ema20=ema20,
                ema50=ema50,
                ema20_prev=ema20_prev,
                atr14=atr14,
                ema_distance=ema_distance,
                oi_resistance=oi_resistance,
                oi_resistance_strength=oi_resistance_strength,
                pivot_resistance=pivot_resistance,
                resistance_distance=resistance_distance,
                trend_bearish=True,
                price_below_ema20=True,
                ema_distance_ok=True,
                resistance_rejection=False,
            )
            result.debug_output = result.format_debug_output()
            return result

        # ----------------------------------------------------------------------
        # 12. TRADE PARAMETERS (STOP LOSS & TARGET)
        # ----------------------------------------------------------------------
        # SL = Rejection candle HIGH + SL_BUFFER
        stop_loss = rejection_candle.high + self.config.sl_buffer
        entry_est = futures_price
        risk = stop_loss - entry_est
        target = entry_est - (risk * self.config.risk_reward)

        # ----------------------------------------------------------------------
        # 13. SESSION CUTOFF & RISK CLEARANCE (APPROVAL ENGINE)
        # ----------------------------------------------------------------------
        cutoff_ok, cutoff_reason = self.approval_engine.check_session_cutoff(ts)
        if not cutoff_ok:
            result = StrategyResult(
                signal=SignalType.NO_SIGNAL,
                reason="SESSION CUTOFF REACHED",
                timestamp=ts,
                futures_price=futures_price,
                atm_strike=atm_strike,
                ema20=ema20,
                ema50=ema50,
                ema20_prev=ema20_prev,
                atr14=atr14,
                ema_distance=ema_distance,
                oi_resistance=oi_resistance,
                oi_resistance_strength=oi_resistance_strength,
                pivot_resistance=pivot_resistance,
                resistance_distance=resistance_distance,
                trend_bearish=True,
                price_below_ema20=True,
                ema_distance_ok=True,
                resistance_rejection=True,
                entry_price=entry_est,
                stop_loss=stop_loss,
                target=target,
            )
            result.debug_output = result.format_debug_output()
            return result

        if not bypass_risk_engine:
            risk_ok, risk_msg = self.approval_engine.validate_risk_clearance(
                entry_price=entry_est,
                stop_loss=stop_loss,
                target=target,
                has_active_position=has_active_position,
            )
            if not risk_ok:
                result = StrategyResult(
                    signal=SignalType.NO_SIGNAL,
                    reason="RISK CHECK FAILED",
                    timestamp=ts,
                    futures_price=futures_price,
                    atm_strike=atm_strike,
                    ema20=ema20,
                    ema50=ema50,
                    ema20_prev=ema20_prev,
                    atr14=atr14,
                    ema_distance=ema_distance,
                    oi_resistance=oi_resistance,
                    oi_resistance_strength=oi_resistance_strength,
                    pivot_resistance=pivot_resistance,
                    resistance_distance=resistance_distance,
                    trend_bearish=True,
                    price_below_ema20=True,
                    ema_distance_ok=True,
                    resistance_rejection=True,
                    risk_check_passed=False,
                    entry_price=entry_est,
                    stop_loss=stop_loss,
                    target=target,
                )
                result.debug_output = result.format_debug_output()
                return result

        # ----------------------------------------------------------------------
        # ALL CONDITIONS SATISFIED -> GENERATE SHORT SIGNAL
        # ----------------------------------------------------------------------
        final_result = StrategyResult(
            signal=SignalType.SHORT,
            reason="ALL SHORT CONDITIONS SATISFIED",
            direction="SHORT",
            timestamp=ts,
            futures_price=futures_price,
            atm_strike=atm_strike,
            ema20=ema20,
            ema50=ema50,
            ema20_prev=ema20_prev,
            atr14=atr14,
            ema_distance=ema_distance,
            oi_resistance=oi_resistance,
            oi_resistance_strength=oi_resistance_strength,
            pivot_resistance=pivot_resistance,
            resistance_distance=resistance_distance,
            trend_bearish=True,
            price_below_ema20=True,
            ema_distance_ok=True,
            resistance_rejection=True,
            risk_check_passed=True,
            entry_price=entry_est,
            stop_loss=stop_loss,
            target=target,
        )
        final_result.debug_output = final_result.format_debug_output()
        return final_result
