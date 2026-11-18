"""
Price-Only Long/Short Data Validation Strategy Engine.
Implements Phase 7 deterministic trading rules for empirical data validation.

Rules:
- 15M Trend Filter:
    LONG: Close > EMA20 > EMA50, EMA20(t) > EMA20(t-1)
    SHORT: Close < EMA20 < EMA50, EMA20(t) < EMA20(t-1)
- 5M Pullback & Bullish/Bearish Rejection:
    LONG: Low <= EMA20, Close >= EMA20, 0 <= (Close - EMA20) <= ATR14 * 0.25, Close > Open
    SHORT: High >= EMA20, Close <= EMA20, 0 <= (EMA20 - Close) <= ATR14 * 0.25, Close < Open
- Optional Breakout Confirmation:
    LONG: Close > previous 5m High
    SHORT: Close < previous 5m Low
- Execution:
    Signal triggers at 5m candle close (T).
    Execution strictly at NEXT 5m candle Open (T+1).
- Risk Management:
    LONG: SL = Rejection Low - 5 pts, Target = Entry + 2 * (Entry - SL) [2R]
    SHORT: SL = Rejection High + 5 pts, Target = Entry - 2 * (SL - Entry) [2R]
- Constraints:
    One active position at a time.
    Intraday only: Cutoff at 15:00 (no new entries after 15:00 IST).
    EOD Square-off: All positions closed before session close (at 15:25 bar close).
"""

from dataclasses import dataclass, field
from datetime import datetime, time, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
import pandas as pd


class Direction(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class ExitReason(str, Enum):
    TARGET = "TARGET"
    STOP_LOSS = "STOP_LOSS"
    EOD_SQUAREOFF = "EOD_SQUAREOFF"


@dataclass
class TransactionCostModel:
    """
    Configurable transaction costs model based on NSE derivative schedules.
    All rates are expressed as decimals or rupees per order.
    """
    brokerage_per_order: float = 20.0       # Flat ₹20 per order (₹40 round-trip)
    exchange_charge_rate: float = 0.0000173  # 0.00173% of turnover
    stt_rate_sell: float = 0.0002           # 0.02% on sell turnover (Futures)
    sebi_charge_rate: float = 0.000001      # ₹10 per crore (0.0001%)
    stamp_duty_rate_buy: float = 0.00002    # 0.002% on buy turnover
    gst_rate: float = 0.18                  # 18% on (brokerage + exchange + sebi)
    slippage_points_per_side: float = 0.5   # 0.5 point slippage on entry and exit (1.0 pt roundtrip)
    lot_size: int = 50                      # 1 standard lot = 50 index units

    def calculate_trade_costs(
        self,
        entry_price: float,
        exit_price: float,
        direction: Direction,
    ) -> Dict[str, float]:
        """Calculates granular line-item costs in INR for a completed round-trip trade."""
        entry_turnover = entry_price * self.lot_size
        exit_turnover = exit_price * self.lot_size
        total_turnover = entry_turnover + exit_turnover

        # Brokerage (₹20 entry + ₹20 exit)
        brokerage = self.brokerage_per_order * 2.0

        # Exchange turnover charge
        exchange_charges = total_turnover * self.exchange_charge_rate

        # SEBI turnover charge
        sebi_charges = total_turnover * self.sebi_charge_rate

        # GST on brokerage + exchange + SEBI
        gst = (brokerage + exchange_charges + sebi_charges) * self.gst_rate

        # Stamp duty (on buy side only)
        buy_turnover = entry_turnover if direction == Direction.LONG else exit_turnover
        stamp_duty = buy_turnover * self.stamp_duty_rate_buy

        # STT (on sell side only for futures)
        sell_turnover = exit_turnover if direction == Direction.LONG else entry_turnover
        stt = sell_turnover * self.stt_rate_sell

        statutory_taxes = brokerage + exchange_charges + sebi_charges + gst + stamp_duty + stt

        # Slippage cost in rupees
        total_slippage_points = self.slippage_points_per_side * 2.0
        slippage_cost_inr = total_slippage_points * self.lot_size

        return {
            "brokerage": round(brokerage, 2),
            "exchange_charges": round(exchange_charges, 2),
            "sebi_charges": round(sebi_charges, 2),
            "gst": round(gst, 2),
            "stamp_duty": round(stamp_duty, 2),
            "stt": round(stt, 2),
            "total_statutory_taxes": round(statutory_taxes, 2),
            "slippage_points": total_slippage_points,
            "slippage_cost_inr": round(slippage_cost_inr, 2),
            "total_friction_inr": round(statutory_taxes + slippage_cost_inr, 2),
        }


@dataclass
class BacktestConfig:
    ema_fast_15m: int = 20
    ema_slow_15m: int = 50
    ema_5m: int = 20
    atr_period_5m: int = 14
    atr_distance_mult: float = 0.25
    sl_buffer_points: float = 5.0
    risk_reward_ratio: float = 2.0
    cutoff_time: time = field(default_factory=lambda: time(15, 0))       # No new trades after 15:00 IST
    square_off_time: time = field(default_factory=lambda: time(15, 25))  # Square off open positions at 15:25 IST
    require_breakout: bool = False                                       # Optional Close > prev High/Low
    mode: str = "LONG_AND_SHORT"                                        # "LONG_ONLY", "SHORT_ONLY", "LONG_AND_SHORT"


@dataclass
class TradeRecord:
    trade_id: int
    direction: Direction
    signal_time: datetime
    entry_time: datetime
    entry_price: float
    sl_price: float
    target_price: float
    risk_points: float
    exit_time: datetime
    exit_price: float
    exit_reason: ExitReason
    gross_points: float
    net_points: float
    gross_pnl_inr: float
    net_pnl_inr: float
    total_costs_inr: float
    slippage_points: float
    holding_bars: int
    holding_minutes: int
    is_win: bool


def calculate_wilder_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Calculates Wilder's Average True Range (ATR)."""
    close_prev = close.shift(1)
    tr1 = high - low
    tr2 = (high - close_prev).abs()
    tr3 = (low - close_prev).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1.0 / period, adjust=False).mean()
    return atr


def prepare_multi_timeframe_data(
    df_5m: pd.DataFrame,
    df_15m: pd.DataFrame,
    config: BacktestConfig,
) -> pd.DataFrame:
    """
    Computes technical indicators across 15M and 5M timeframes and merges them
    with STRICT zero look-ahead alignment.
    """
    # 1. Prepare 15M indicators
    df_15 = df_15m.copy()
    df_15['dt'] = pd.to_datetime(df_15['timestamp'], format='ISO8601')
    df_15 = df_15.sort_values('dt').reset_index(drop=True)
    
    # 15M candle close time: bar starts at dt, ends at dt + 15 min
    df_15['close_time'] = df_15['dt'] + pd.Timedelta(minutes=15)
    
    df_15['ema20'] = df_15['close'].ewm(span=config.ema_fast_15m, adjust=False).mean()
    df_15['ema50'] = df_15['close'].ewm(span=config.ema_slow_15m, adjust=False).mean()
    df_15['ema20_prev'] = df_15['ema20'].shift(1)
    
    df_15['trend_long'] = (
        (df_15['close'] > df_15['ema20']) &
        (df_15['ema20'] > df_15['ema50']) &
        (df_15['ema20'] > df_15['ema20_prev'])
    )
    df_15['trend_short'] = (
        (df_15['close'] < df_15['ema20']) &
        (df_15['ema20'] < df_15['ema50']) &
        (df_15['ema20'] < df_15['ema20_prev'])
    )
    
    # 2. Prepare 5M indicators
    df_5 = df_5m.copy()
    df_5['dt'] = pd.to_datetime(df_5['timestamp'], format='ISO8601')
    df_5 = df_5.sort_values('dt').reset_index(drop=True)
    
    # 5M candle close time: bar starts at dt, ends at dt + 5 min
    df_5['close_time'] = df_5['dt'] + pd.Timedelta(minutes=5)
    df_5['dt_ist'] = df_5['dt'].dt.tz_convert('Asia/Kolkata')
    df_5['time_ist'] = df_5['dt_ist'].dt.time
    df_5['date_ist'] = df_5['dt_ist'].dt.date
    
    df_5['ema20'] = df_5['close'].ewm(span=config.ema_5m, adjust=False).mean()
    df_5['atr14'] = calculate_wilder_atr(df_5['high'], df_5['low'], df_5['close'], period=config.atr_period_5m)
    df_5['prev_high'] = df_5['high'].shift(1)
    df_5['prev_low'] = df_5['low'].shift(1)
    
    # 3. Look-Ahead Free Merge:
    # At 5M candle close time T, what was the latest COMPLETED 15M candle?
    # A 15M candle that closed at T_15 <= T is known and finalized.
    cols_15 = ['close_time', 'trend_long', 'trend_short', 'ema20', 'ema50']
    df_15_subset = df_15[cols_15].rename(columns={
        'close_time': 'tf15_close_time',
        'trend_long': 'trend_long_15m',
        'trend_short': 'trend_short_15m',
        'ema20': 'ema20_15m',
        'ema50': 'ema50_15m',
    })
    
    # Use merge_asof backward: matches on tf15_close_time <= 5M close_time
    df_merged = pd.merge_asof(
        df_5,
        df_15_subset,
        left_on='close_time',
        right_on='tf15_close_time',
        direction='backward',
    )
    
    df_merged['trend_long_15m'] = df_merged['trend_long_15m'].fillna(False)
    df_merged['trend_short_15m'] = df_merged['trend_short_15m'].fillna(False)
    
    return df_merged


def simulate_strategy(
    df: pd.DataFrame,
    config: BacktestConfig,
    cost_model: TransactionCostModel,
) -> Tuple[List[TradeRecord], pd.DataFrame]:
    """
    Executes bar-by-bar deterministic backtest simulation with ZERO look-ahead.
    """
    trades: List[TradeRecord] = []
    trade_id_seq = 1
    
    # Active position state
    in_position = False
    pos_direction: Optional[Direction] = None
    pos_entry_price: float = 0.0
    pos_sl_price: float = 0.0
    pos_target_price: float = 0.0
    pos_risk_points: float = 0.0
    pos_entry_time: Optional[datetime] = None
    pos_signal_time: Optional[datetime] = None
    pos_entry_idx: int = 0
    
    # Signal state from previous candle
    pending_signal: Optional[Direction] = None
    pending_signal_time: Optional[datetime] = None
    pending_rejection_low: float = 0.0
    pending_rejection_high: float = 0.0
    
    # Pre-extract numpy arrays for high-performance iteration
    n = len(df)
    opens = df['open'].values
    highs = df['high'].values
    lows = df['low'].values
    closes = df['close'].values
    times_ist = df['time_ist'].values
    dates_ist = df['date_ist'].values
    dts_ist = np.array(df['dt_ist'].dt.to_pydatetime())
    ema20s = df['ema20'].values
    atr14s = df['atr14'].values
    prev_highs = df['prev_high'].values
    prev_lows = df['prev_low'].values
    trend_longs = df['trend_long_15m'].values
    trend_shorts = df['trend_short_15m'].values
    
    for i in range(1, n):
        curr_open = opens[i]
        curr_high = highs[i]
        curr_low = lows[i]
        curr_close = closes[i]
        curr_time = times_ist[i]
        curr_dt = dts_ist[i]
        curr_date = dates_ist[i]
        
        # ------------------------------------------------------------
        # STEP 1: Process Open Position Exits during candle i
        # ------------------------------------------------------------
        if in_position:
            holding_bars = i - pos_entry_idx + 1
            holding_minutes = holding_bars * 5
            exit_occurred = False
            exit_price = 0.0
            exit_reason = None
            
            # Check EOD square-off (at or after square_off_time, e.g. 15:25)
            # or if day changed unexpectedly
            is_eod = (curr_time >= config.square_off_time) or (curr_date != dates_ist[pos_entry_idx])
            
            if pos_direction == Direction.LONG:
                sl_hit = (curr_low <= pos_sl_price)
                tgt_hit = (curr_high >= pos_target_price)
                
                if sl_hit and tgt_hit:
                    # Conservative assumption: worst-case stop loss hit first
                    exit_occurred = True
                    exit_price = pos_sl_price
                    exit_reason = ExitReason.STOP_LOSS
                elif sl_hit:
                    exit_occurred = True
                    exit_price = pos_sl_price
                    exit_reason = ExitReason.STOP_LOSS
                elif tgt_hit:
                    exit_occurred = True
                    exit_price = pos_target_price
                    exit_reason = ExitReason.TARGET
                elif is_eod:
                    exit_occurred = True
                    exit_price = curr_close
                    exit_reason = ExitReason.EOD_SQUAREOFF
                    
            elif pos_direction == Direction.SHORT:
                sl_hit = (curr_high >= pos_sl_price)
                tgt_hit = (curr_low <= pos_target_price)
                
                if sl_hit and tgt_hit:
                    exit_occurred = True
                    exit_price = pos_sl_price
                    exit_reason = ExitReason.STOP_LOSS
                elif sl_hit:
                    exit_occurred = True
                    exit_price = pos_sl_price
                    exit_reason = ExitReason.STOP_LOSS
                elif tgt_hit:
                    exit_occurred = True
                    exit_price = pos_target_price
                    exit_reason = ExitReason.TARGET
                elif is_eod:
                    exit_occurred = True
                    exit_price = curr_close
                    exit_reason = ExitReason.EOD_SQUAREOFF
            
            if exit_occurred:
                # Record trade
                if pos_direction == Direction.LONG:
                    gross_points = exit_price - pos_entry_price
                else:
                    gross_points = pos_entry_price - exit_price
                
                slippage_pts = cost_model.slippage_points_per_side * 2.0
                net_points = gross_points - slippage_pts
                gross_pnl_inr = gross_points * cost_model.lot_size
                costs_dict = cost_model.calculate_trade_costs(pos_entry_price, exit_price, pos_direction)
                net_pnl_inr = gross_pnl_inr - costs_dict["total_friction_inr"]
                
                trades.append(TradeRecord(
                    trade_id=trade_id_seq,
                    direction=pos_direction,
                    signal_time=pos_signal_time,
                    entry_time=pos_entry_time,
                    entry_price=pos_entry_price,
                    sl_price=pos_sl_price,
                    target_price=pos_target_price,
                    risk_points=pos_risk_points,
                    exit_time=curr_dt,
                    exit_price=exit_price,
                    exit_reason=exit_reason,
                    gross_points=round(gross_points, 2),
                    net_points=round(net_points, 2),
                    gross_pnl_inr=round(gross_pnl_inr, 2),
                    net_pnl_inr=round(net_pnl_inr, 2),
                    total_costs_inr=costs_dict["total_statutory_taxes"],
                    slippage_points=slippage_pts,
                    holding_bars=holding_bars,
                    holding_minutes=holding_minutes,
                    is_win=(net_points > 0),
                ))
                trade_id_seq += 1
                in_position = False
                pos_direction = None
        
        # ------------------------------------------------------------
        # STEP 2: Execute Pending Signal at candle i OPEN
        # ------------------------------------------------------------
        if not in_position and pending_signal is not None:
            # Check if entry is within trading hours (entry time <= cutoff_time, e.g. 15:00)
            # and within same session date
            if curr_time <= config.cutoff_time and curr_date == dates_ist[i - 1]:
                entry_price = curr_open
                
                if pending_signal == Direction.LONG:
                    sl_price = pending_rejection_low - config.sl_buffer_points
                    risk = entry_price - sl_price
                    if risk > 0:
                        target_price = entry_price + (risk * config.risk_reward_ratio)
                        in_position = True
                        pos_direction = Direction.LONG
                        pos_entry_price = entry_price
                        pos_sl_price = sl_price
                        pos_target_price = target_price
                        pos_risk_points = risk
                        pos_entry_time = curr_dt
                        pos_signal_time = pending_signal_time
                        pos_entry_idx = i
                        
                elif pending_signal == Direction.SHORT:
                    sl_price = pending_rejection_high + config.sl_buffer_points
                    risk = sl_price - entry_price
                    if risk > 0:
                        target_price = entry_price - (risk * config.risk_reward_ratio)
                        in_position = True
                        pos_direction = Direction.SHORT
                        pos_entry_price = entry_price
                        pos_sl_price = sl_price
                        pos_target_price = target_price
                        pos_risk_points = risk
                        pos_entry_time = curr_dt
                        pos_signal_time = pending_signal_time
                        pos_entry_idx = i
                
                # If entered on candle i open, check if it hits SL or Target inside candle i
                if in_position:
                    sl_hit = (curr_low <= pos_sl_price) if pos_direction == Direction.LONG else (curr_high >= pos_sl_price)
                    tgt_hit = (curr_high >= pos_target_price) if pos_direction == Direction.LONG else (curr_low <= pos_target_price)
                    is_eod = (curr_time >= config.square_off_time)
                    
                    exit_occurred = False
                    exit_price = 0.0
                    exit_reason = None
                    
                    if sl_hit and tgt_hit:
                        exit_occurred = True
                        exit_price = pos_sl_price
                        exit_reason = ExitReason.STOP_LOSS
                    elif sl_hit:
                        exit_occurred = True
                        exit_price = pos_sl_price
                        exit_reason = ExitReason.STOP_LOSS
                    elif tgt_hit:
                        exit_occurred = True
                        exit_price = pos_target_price
                        exit_reason = ExitReason.TARGET
                    elif is_eod:
                        exit_occurred = True
                        exit_price = curr_close
                        exit_reason = ExitReason.EOD_SQUAREOFF
                        
                    if exit_occurred:
                        gross_points = (exit_price - pos_entry_price) if pos_direction == Direction.LONG else (pos_entry_price - exit_price)
                        slippage_pts = cost_model.slippage_points_per_side * 2.0
                        net_points = gross_points - slippage_pts
                        gross_pnl_inr = gross_points * cost_model.lot_size
                        costs_dict = cost_model.calculate_trade_costs(pos_entry_price, exit_price, pos_direction)
                        net_pnl_inr = gross_pnl_inr - costs_dict["total_friction_inr"]
                        
                        trades.append(TradeRecord(
                            trade_id=trade_id_seq,
                            direction=pos_direction,
                            signal_time=pos_signal_time,
                            entry_time=pos_entry_time,
                            entry_price=pos_entry_price,
                            sl_price=pos_sl_price,
                            target_price=pos_target_price,
                            risk_points=pos_risk_points,
                            exit_time=curr_dt,
                            exit_price=exit_price,
                            exit_reason=exit_reason,
                            gross_points=round(gross_points, 2),
                            net_points=round(net_points, 2),
                            gross_pnl_inr=round(gross_pnl_inr, 2),
                            net_pnl_inr=round(net_pnl_inr, 2),
                            total_costs_inr=costs_dict["total_statutory_taxes"],
                            slippage_points=slippage_pts,
                            holding_bars=1,
                            holding_minutes=5,
                            is_win=(net_points > 0),
                        ))
                        trade_id_seq += 1
                        in_position = False
                        pos_direction = None
            
            # Pending signal consumed or expired
            pending_signal = None
            pending_signal_time = None
        
        # ------------------------------------------------------------
        # STEP 3: Evaluate Signal at candle i CLOSE
        # ------------------------------------------------------------
        # Signals only evaluated if NOT already in position
        # and bar time is strictly before or at cutoff_time
        if not in_position and curr_time <= config.cutoff_time:
            # LONG EVALUATION
            if config.mode in ("LONG_ONLY", "LONG_AND_SHORT"):
                if trend_longs[i]:  # 15m trend filter
                    # 5m pullback
                    pullback_ok = (curr_low <= ema20s[i]) and (curr_close >= ema20s[i])
                    # Extension filter
                    ema_dist = curr_close - ema20s[i]
                    max_allowed_dist = atr14s[i] * config.atr_distance_mult
                    dist_ok = (0.0 <= ema_dist <= max_allowed_dist)
                    # Bullish rejection
                    rejection_ok = (curr_close > curr_open) and (curr_close > ema20s[i]) and (curr_low <= ema20s[i])
                    # Breakout confirmation (optional)
                    breakout_ok = True
                    if config.require_breakout:
                        breakout_ok = (curr_close > prev_highs[i])
                    
                    if pullback_ok and dist_ok and rejection_ok and breakout_ok:
                        pending_signal = Direction.LONG
                        pending_signal_time = curr_dt
                        pending_rejection_low = curr_low
                        pending_rejection_high = curr_high
            
            # SHORT EVALUATION (only if no Long signal generated)
            if pending_signal is None and config.mode in ("SHORT_ONLY", "LONG_AND_SHORT"):
                if trend_shorts[i]:  # 15m trend filter
                    # 5m pullback
                    pullback_ok = (curr_high >= ema20s[i]) and (curr_close <= ema20s[i])
                    # Extension filter
                    ema_dist = ema20s[i] - curr_close
                    max_allowed_dist = atr14s[i] * config.atr_distance_mult
                    dist_ok = (0.0 <= ema_dist <= max_allowed_dist)
                    # Bearish rejection
                    rejection_ok = (curr_close < curr_open) and (curr_close < ema20s[i]) and (curr_high >= ema20s[i])
                    # Breakout confirmation (optional)
                    breakout_ok = True
                    if config.require_breakout:
                        breakout_ok = (curr_close < prev_lows[i])
                    
                    if pullback_ok and dist_ok and rejection_ok and breakout_ok:
                        pending_signal = Direction.SHORT
                        pending_signal_time = curr_dt
                        pending_rejection_low = curr_low
                        pending_rejection_high = curr_high

    # Convert trade records to DataFrame
    trade_dicts = [t.__dict__ for t in trades]
    df_trades = pd.DataFrame(trade_dicts) if trade_dicts else pd.DataFrame()
    return trades, df_trades


def calculate_performance_metrics(trades: List[TradeRecord], df_5m: pd.DataFrame) -> Dict[str, Any]:
    """Computes comprehensive performance statistics for backtest evaluation."""
    if not trades:
        return {
            "total_trades": 0,
            "long_trades": 0,
            "short_trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0.0,
            "gross_points": 0.0,
            "net_points": 0.0,
            "gross_pnl_inr": 0.0,
            "net_pnl_inr": 0.0,
            "total_costs_inr": 0.0,
            "total_slippage_inr": 0.0,
            "profit_factor": 0.0,
            "expectancy_pts": 0.0,
            "max_drawdown_pts": 0.0,
            "max_drawdown_inr": 0.0,
            "avg_trade_pts": 0.0,
            "avg_winner_pts": 0.0,
            "avg_loser_pts": 0.0,
            "avg_holding_mins": 0.0,
            "trades_per_day": 0.0,
            "max_consecutive_losses": 0,
            "max_consecutive_wins": 0,
            "yearly_stats": {},
        }
    
    df_t = pd.DataFrame([t.__dict__ for t in trades])
    
    total_trades = len(df_t)
    long_trades = len(df_t[df_t['direction'] == Direction.LONG])
    short_trades = len(df_t[df_t['direction'] == Direction.SHORT])
    
    wins = len(df_t[df_t['is_win']])
    losses = total_trades - wins
    win_rate = round(wins / total_trades * 100.0, 2)
    
    gross_pts = round(df_t['gross_points'].sum(), 2)
    net_pts = round(df_t['net_points'].sum(), 2)
    gross_pnl = round(df_t['gross_pnl_inr'].sum(), 2)
    net_pnl = round(df_t['net_pnl_inr'].sum(), 2)
    total_costs = round(df_t['total_costs_inr'].sum(), 2)
    total_slippage = round(df_t['slippage_points'].sum() * 50, 2)
    
    win_points = df_t[df_t['net_points'] > 0]['net_points'].sum()
    loss_points = abs(df_t[df_t['net_points'] < 0]['net_points'].sum())
    profit_factor = round(win_points / loss_points, 2) if loss_points > 0 else 999.0
    
    expectancy_pts = round(net_pts / total_trades, 2)
    avg_trade_pts = expectancy_pts
    avg_winner_pts = round(df_t[df_t['is_win']]['net_points'].mean(), 2) if wins > 0 else 0.0
    avg_loser_pts = round(df_t[~df_t['is_win']]['net_points'].mean(), 2) if losses > 0 else 0.0
    avg_holding_mins = round(df_t['holding_minutes'].mean(), 1)
    
    # Calculate trading days
    total_days = df_5m['date_ist'].nunique() if 'date_ist' in df_5m.columns else 1247
    trades_per_day = round(total_trades / max(1, total_days), 2)
    
    # Drawdown calculation
    df_t['cum_net_pts'] = df_t['net_points'].cumsum()
    df_t['peak_pts'] = df_t['cum_net_pts'].cummax()
    df_t['dd_pts'] = df_t['peak_pts'] - df_t['cum_net_pts']
    max_dd_pts = round(df_t['dd_pts'].max(), 2)
    max_dd_inr = round(max_dd_pts * 50, 2)
    
    # Consecutive wins / losses
    streaks = df_t['is_win'].tolist()
    max_loss_streak = 0
    curr_loss_streak = 0
    max_win_streak = 0
    curr_win_streak = 0
    for w in streaks:
        if w:
            curr_win_streak += 1
            max_win_streak = max(max_win_streak, curr_win_streak)
            curr_loss_streak = 0
        else:
            curr_loss_streak += 1
            max_loss_streak = max(max_loss_streak, curr_loss_streak)
            curr_win_streak = 0
            
    # Year-by-year performance
    df_t['entry_dt'] = pd.to_datetime(df_t['entry_time'])
    df_t['year'] = df_t['entry_dt'].dt.year
    yearly_stats = {}
    for y, y_group in df_t.groupby('year'):
        y_total = len(y_group)
        y_wins = len(y_group[y_group['is_win']])
        y_win_rate = round(y_wins / y_total * 100.0, 2)
        y_net_pts = round(y_group['net_points'].sum(), 2)
        y_net_pnl = round(y_group['net_pnl_inr'].sum(), 2)
        y_win_pts = y_group[y_group['net_points'] > 0]['net_points'].sum()
        y_loss_pts = abs(y_group[y_group['net_points'] < 0]['net_points'].sum())
        y_pf = round(y_win_pts / y_loss_pts, 2) if y_loss_pts > 0 else 999.0
        
        y_group = y_group.copy()
        y_group['cum'] = y_group['net_points'].cumsum()
        y_dd = (y_group['cum'].cummax() - y_group['cum']).max()
        
        yearly_stats[int(y)] = {
            "year": int(y),
            "trades": y_total,
            "win_rate": y_win_rate,
            "net_points": y_net_pts,
            "net_pnl_inr": y_net_pnl,
            "profit_factor": y_pf,
            "max_dd_points": round(y_dd, 2),
        }
        
    return {
        "total_trades": total_trades,
        "long_trades": long_trades,
        "short_trades": short_trades,
        "wins": wins,
        "losses": losses,
        "win_rate": win_rate,
        "gross_points": gross_pts,
        "net_points": net_pts,
        "gross_pnl_inr": gross_pnl,
        "net_pnl_inr": net_pnl,
        "total_costs_inr": total_costs,
        "total_slippage_inr": total_slippage,
        "profit_factor": profit_factor,
        "expectancy_pts": expectancy_pts,
        "max_drawdown_pts": max_dd_pts,
        "max_drawdown_inr": max_dd_inr,
        "avg_trade_pts": avg_trade_pts,
        "avg_winner_pts": avg_winner_pts,
        "avg_loser_pts": avg_loser_pts,
        "avg_holding_mins": avg_holding_mins,
        "trades_per_day": trades_per_day,
        "max_consecutive_losses": max_loss_streak,
        "max_consecutive_wins": max_win_streak,
        "yearly_stats": yearly_stats,
    }
