"""
Price-Action Strategy Engine & Hypothesis Testing Framework.
Supports systematic simulation of breakout, reversal, candle structure,
and multi-timeframe price-action strategies with ZERO look-ahead.
"""

from dataclasses import dataclass, field
from datetime import datetime, time, date
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple
import numpy as np
import pandas as pd

from nifty_trader.strategies.price_validation_strategy import (
    Direction,
    ExitReason,
    TransactionCostModel,
)


@dataclass
class TradeResult:
    trade_id: int
    hypothesis_id: str
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
    year: int
    tod_bucket: str


@dataclass
class HypothesisDefinition:
    hypothesis_id: str
    name: str
    category: str  # "BREAKOUT", "REVERSAL", "COMPRESSION", "REGIME_FILTERED"
    description: str
    signal_func: Callable[[pd.DataFrame, int], Optional[Tuple[Direction, float]]]  # returns (Direction, SL_level) or None
    target_rr: float = 2.0
    sl_buffer: float = 5.0
    allowed_direction: str = "BOTH"  # "LONG_ONLY", "SHORT_ONLY", "BOTH"
    cutoff_time: time = field(default_factory=lambda: time(15, 0))
    square_off_time: time = field(default_factory=lambda: time(15, 25))


def run_hypothesis_simulation(
    df: pd.DataFrame,
    hyp: HypothesisDefinition,
    cost_model: Optional[TransactionCostModel] = None,
    target_rr: Optional[float] = None,
    sl_buffer: Optional[float] = None,
    direction_mode: Optional[str] = None,
) -> Tuple[List[TradeResult], pd.DataFrame]:
    """
    Executes a sequential bar-by-bar backtest of a single hypothesis.
    Ensures strict zero look-ahead: signals evaluated at candle i close;
    entry occurs strictly at candle i+1 OPEN.
    """
    if cost_model is None:
        cost_model = TransactionCostModel(lot_size=50, slippage_points_per_side=0.5)

    rr = target_rr if target_rr is not None else hyp.target_rr
    buffer = sl_buffer if sl_buffer is not None else hyp.sl_buffer
    dir_mode = direction_mode if direction_mode is not None else hyp.allowed_direction

    trades: List[TradeResult] = []
    trade_id_seq = 1

    # Active position state
    in_pos = False
    pos_direction: Optional[Direction] = None
    pos_entry_price: float = 0.0
    pos_sl_price: float = 0.0
    pos_target_price: float = 0.0
    pos_risk_pts: float = 0.0
    pos_entry_time: Optional[datetime] = None
    pos_signal_time: Optional[datetime] = None
    pos_entry_idx: int = 0
    pos_tod: str = ""

    # Pending signal from previous candle close
    pending_signal: Optional[Direction] = None
    pending_sl_base: float = 0.0
    pending_signal_time: Optional[datetime] = None
    pending_tod: str = ""

    n = len(df)
    opens = df['open'].values
    highs = df['high'].values
    lows = df['low'].values
    closes = df['close'].values
    times_ist = df['time_ist'].values
    dates_ist = df['date_ist'].values
    dts_ist = np.array(df['dt_ist'].dt.to_pydatetime())
    tod_buckets = df['tod_bucket'].values

    # Pre-evaluate signal condition for each bar to optimize loop speed
    # We call hyp.signal_func
    for i in range(1, n):
        curr_open = opens[i]
        curr_high = highs[i]
        curr_low = lows[i]
        curr_close = closes[i]
        curr_time = times_ist[i]
        curr_dt = dts_ist[i]
        curr_date = dates_ist[i]
        curr_tod = tod_buckets[i]

        # ----------------------------------------------------
        # 1. Evaluate open position exits
        # ----------------------------------------------------
        if in_pos:
            holding_bars = i - pos_entry_idx + 1
            holding_mins = holding_bars * 5
            exit_occurred = False
            exit_price = 0.0
            exit_reason = None

            is_eod = (curr_time >= hyp.square_off_time) or (curr_date != dates_ist[pos_entry_idx])

            if pos_direction == Direction.LONG:
                sl_hit = (curr_low <= pos_sl_price)
                tgt_hit = (curr_high >= pos_target_price)

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
                gross_pts = (exit_price - pos_entry_price) if pos_direction == Direction.LONG else (pos_entry_price - exit_price)
                slippage_pts = cost_model.slippage_points_per_side * 2.0
                net_pts = gross_pts - slippage_pts
                gross_pnl = gross_pts * cost_model.lot_size
                costs = cost_model.calculate_trade_costs(pos_entry_price, exit_price, pos_direction)
                net_pnl = gross_pnl - costs["total_friction_inr"]

                trades.append(TradeResult(
                    trade_id=trade_id_seq,
                    hypothesis_id=hyp.hypothesis_id,
                    direction=pos_direction,
                    signal_time=pos_signal_time,
                    entry_time=pos_entry_time,
                    entry_price=pos_entry_price,
                    sl_price=pos_sl_price,
                    target_price=pos_target_price,
                    risk_points=pos_risk_pts,
                    exit_time=curr_dt,
                    exit_price=exit_price,
                    exit_reason=exit_reason,
                    gross_points=round(gross_pts, 2),
                    net_points=round(net_pts, 2),
                    gross_pnl_inr=round(gross_pnl, 2),
                    net_pnl_inr=round(net_pnl, 2),
                    total_costs_inr=costs["total_statutory_taxes"],
                    slippage_points=slippage_pts,
                    holding_bars=holding_bars,
                    holding_minutes=holding_mins,
                    is_win=(net_pts > 0),
                    year=curr_dt.year,
                    tod_bucket=pos_tod,
                ))
                trade_id_seq += 1
                in_pos = False
                pos_direction = None

        # ----------------------------------------------------
        # 2. Execute pending signal at candle i OPEN
        # ----------------------------------------------------
        if not in_pos and pending_signal is not None:
            if curr_time <= hyp.cutoff_time and curr_date == dates_ist[i - 1]:
                entry_price = curr_open

                if pending_signal == Direction.LONG:
                    sl_price = pending_sl_base - buffer
                    risk = entry_price - sl_price
                    if risk > 0 and (risk <= 100.0):  # Cap outlier risk > 100 pts
                        target_price = entry_price + (risk * rr)
                        in_pos = True
                        pos_direction = Direction.LONG
                        pos_entry_price = entry_price
                        pos_sl_price = sl_price
                        pos_target_price = target_price
                        pos_risk_pts = risk
                        pos_entry_time = curr_dt
                        pos_signal_time = pending_signal_time
                        pos_entry_idx = i
                        pos_tod = pending_tod

                elif pending_signal == Direction.SHORT:
                    sl_price = pending_sl_base + buffer
                    risk = sl_price - entry_price
                    if risk > 0 and (risk <= 100.0):  # Cap outlier risk > 100 pts
                        target_price = entry_price - (risk * rr)
                        in_pos = True
                        pos_direction = Direction.SHORT
                        pos_entry_price = entry_price
                        pos_sl_price = sl_price
                        pos_target_price = target_price
                        pos_risk_pts = risk
                        pos_entry_time = curr_dt
                        pos_signal_time = pending_signal_time
                        pos_entry_idx = i
                        pos_tod = pending_tod

                # Immediate intra-candle exit check on entry candle i
                if in_pos:
                    sl_hit = (curr_low <= pos_sl_price) if pos_direction == Direction.LONG else (curr_high >= pos_sl_price)
                    tgt_hit = (curr_high >= pos_target_price) if pos_direction == Direction.LONG else (curr_low <= pos_target_price)
                    is_eod = (curr_time >= hyp.square_off_time)

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
                        gross_pts = (exit_price - pos_entry_price) if pos_direction == Direction.LONG else (pos_entry_price - exit_price)
                        slippage_pts = cost_model.slippage_points_per_side * 2.0
                        net_pts = gross_pts - slippage_pts
                        gross_pnl = gross_pts * cost_model.lot_size
                        costs = cost_model.calculate_trade_costs(pos_entry_price, exit_price, pos_direction)
                        net_pnl = gross_pnl - costs["total_friction_inr"]

                        trades.append(TradeResult(
                            trade_id=trade_id_seq,
                            hypothesis_id=hyp.hypothesis_id,
                            direction=pos_direction,
                            signal_time=pos_signal_time,
                            entry_time=pos_entry_time,
                            entry_price=pos_entry_price,
                            sl_price=pos_sl_price,
                            target_price=pos_target_price,
                            risk_points=pos_risk_pts,
                            exit_time=curr_dt,
                            exit_price=exit_price,
                            exit_reason=exit_reason,
                            gross_points=round(gross_pts, 2),
                            net_points=round(net_pts, 2),
                            gross_pnl_inr=round(gross_pnl, 2),
                            net_pnl_inr=round(net_pnl, 2),
                            total_costs_inr=costs["total_statutory_taxes"],
                            slippage_points=slippage_pts,
                            holding_bars=1,
                            holding_minutes=5,
                            is_win=(net_pts > 0),
                            year=curr_dt.year,
                            tod_bucket=pos_tod,
                        ))
                        trade_id_seq += 1
                        in_pos = False
                        pos_direction = None

            pending_signal = None

        # ----------------------------------------------------
        # 3. Evaluate Signal at candle i CLOSE
        # ----------------------------------------------------
        if not in_pos and curr_time <= hyp.cutoff_time:
            sig = hyp.signal_func(df, i)
            if sig is not None:
                d, sl_base = sig
                if dir_mode == "BOTH" or (dir_mode == "LONG_ONLY" and d == Direction.LONG) or (dir_mode == "SHORT_ONLY" and d == Direction.SHORT):
                    pending_signal = d
                    pending_sl_base = sl_base
                    pending_signal_time = curr_dt
                    pending_tod = curr_tod

    df_trades = pd.DataFrame([t.__dict__ for t in trades]) if trades else pd.DataFrame()
    return trades, df_trades


def summarize_trade_metrics(trades: List[TradeResult], total_days: int = 1242) -> Dict[str, Any]:
    """Calculates comprehensive quantitative metrics for a trade list."""
    if not trades:
        return {
            "total_trades": 0, "long_trades": 0, "short_trades": 0,
            "wins": 0, "losses": 0, "win_rate": 0.0,
            "gross_points": 0.0, "net_points": 0.0,
            "gross_pnl_inr": 0.0, "net_pnl_inr": 0.0,
            "total_costs_inr": 0.0, "total_slippage_inr": 0.0,
            "profit_factor": 0.0, "expectancy_pts": 0.0,
            "max_drawdown_pts": 0.0, "max_drawdown_inr": 0.0,
            "avg_trade_pts": 0.0, "avg_winner_pts": 0.0, "avg_loser_pts": 0.0,
            "avg_holding_mins": 0.0, "trades_per_day": 0.0,
            "max_consecutive_losses": 0, "max_consecutive_wins": 0,
            "yearly_stats": {}, "tod_stats": {},
        }

    df_t = pd.DataFrame([t.__dict__ for t in trades])
    total = len(df_t)
    longs = len(df_t[df_t['direction'] == Direction.LONG])
    shorts = len(df_t[df_t['direction'] == Direction.SHORT])
    wins = len(df_t[df_t['is_win']])
    losses = total - wins
    win_rate = round(wins / total * 100.0, 2)

    gross_pts = round(df_t['gross_points'].sum(), 2)
    net_pts = round(df_t['net_points'].sum(), 2)
    gross_pnl = round(df_t['gross_pnl_inr'].sum(), 2)
    net_pnl = round(df_t['net_pnl_inr'].sum(), 2)
    costs = round(df_t['total_costs_inr'].sum(), 2)
    slippage = round(df_t['slippage_points'].sum() * 50.0, 2)

    win_pts = df_t[df_t['net_points'] > 0]['net_points'].sum()
    loss_pts = abs(df_t[df_t['net_points'] < 0]['net_points'].sum())
    profit_factor = round(win_pts / loss_pts, 2) if loss_pts > 0 else 999.0

    expectancy = round(net_pts / total, 2)
    avg_win = round(df_t[df_t['is_win']]['net_points'].mean(), 2) if wins > 0 else 0.0
    avg_loss = round(df_t[~df_t['is_win']]['net_points'].mean(), 2) if losses > 0 else 0.0
    avg_holding = round(df_t['holding_minutes'].mean(), 1)
    trades_per_day = round(total / max(1, total_days), 2)

    # Drawdown
    df_t['cum'] = df_t['net_points'].cumsum()
    df_t['dd'] = df_t['cum'].cummax() - df_t['cum']
    max_dd_pts = round(df_t['dd'].max(), 2)
    max_dd_inr = round(max_dd_pts * 50.0, 2)

    # Streaks
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

    # Yearly breakdown
    yearly_stats = {}
    for y, y_grp in df_t.groupby('year'):
        y_tot = len(y_grp)
        y_win = len(y_grp[y_grp['is_win']])
        y_pts = round(y_grp['net_points'].sum(), 2)
        y_gross = round(y_grp['gross_points'].sum(), 2)
        y_pnl = round(y_grp['net_pnl_inr'].sum(), 2)
        y_w_pts = y_grp[y_grp['net_points'] > 0]['net_points'].sum()
        y_l_pts = abs(y_grp[y_grp['net_points'] < 0]['net_points'].sum())
        y_pf = round(y_w_pts / y_l_pts, 2) if y_l_pts > 0 else 999.0
        y_grp_copy = y_grp.copy()
        y_grp_copy['cum'] = y_grp_copy['net_points'].cumsum()
        y_dd = round((y_grp_copy['cum'].cummax() - y_grp_copy['cum']).max(), 2)
        yearly_stats[int(y)] = {
            "year": int(y), "trades": y_tot, "win_rate": round(y_win / y_tot * 100.0, 2),
            "gross_points": y_gross, "net_points": y_pts, "net_pnl_inr": y_pnl,
            "profit_factor": y_pf, "max_dd_pts": y_dd,
        }

    # Time of Day breakdown
    tod_stats = {}
    for tod, t_grp in df_t.groupby('tod_bucket'):
        t_tot = len(t_grp)
        t_win = len(t_grp[t_grp['is_win']])
        t_pts = round(t_grp['net_points'].sum(), 2)
        t_w_pts = t_grp[t_grp['net_points'] > 0]['net_points'].sum()
        t_l_pts = abs(t_grp[t_grp['net_points'] < 0]['net_points'].sum())
        t_pf = round(t_w_pts / t_l_pts, 2) if t_l_pts > 0 else 999.0
        tod_stats[str(tod)] = {
            "tod": str(tod), "trades": t_tot, "win_rate": round(t_win / t_tot * 100.0, 2),
            "net_points": t_pts, "profit_factor": t_pf,
        }

    return {
        "total_trades": total, "long_trades": longs, "short_trades": shorts,
        "wins": wins, "losses": losses, "win_rate": win_rate,
        "gross_points": gross_pts, "net_points": net_pts,
        "gross_pnl_inr": gross_pnl, "net_pnl_inr": net_pnl,
        "total_costs_inr": costs, "total_slippage_inr": slippage,
        "profit_factor": profit_factor, "expectancy_pts": expectancy,
        "max_drawdown_pts": max_dd_pts, "max_drawdown_inr": max_dd_inr,
        "avg_trade_pts": expectancy, "avg_winner_pts": avg_win, "avg_loser_pts": avg_loss,
        "avg_holding_mins": avg_holding, "trades_per_day": trades_per_day,
        "max_consecutive_losses": max_loss_streak, "max_consecutive_wins": max_win_streak,
        "yearly_stats": yearly_stats, "tod_stats": tod_stats,
    }
