"""
Backtest Engine for NIFTY Futures Short Strategy.

Features:
- Chronological simulation with zero look-ahead bias
- Next 5-minute candle OPEN entry execution
- Real-time position tracking (Stop Loss, Target, 15:00 Cutoff)
- Single position enforcement (no overlapping trades)
- Full Indian market transaction costs (Brokerage, STT, Exchange, GST, SEBI, Stamp)
- Realistic configurable slippage on entry and exit
- Detailed TradeLog, Performance Report, and Equity Curve generation
- Strict validation: reports "INSUFFICIENT HISTORICAL OPTION DATA FOR VALID BACKTEST" if options missing
"""

from datetime import datetime, time
import logging
from typing import Dict, List, Optional, Tuple

from nifty_trader.contracts.models import IST
from nifty_trader.strategies.short.contracts import (
    BacktestReport,
    Candle5M,
    EquityPoint,
    ShortStrategyConfig,
    SignalType,
    StrategyResult,
    TradeLog,
    TransactionCostConfig,
)
from nifty_trader.strategies.short.market_data_provider import HistoricalMarketDataProvider
from nifty_trader.strategies.short.strategy import NiftyFuturesShortStrategy

logger = logging.getLogger(__name__)


class BacktestEngine:
    """
    Historical backtest simulation runner for NiftyFuturesShortStrategy.
    """

    def __init__(
        self,
        strategy: Optional[NiftyFuturesShortStrategy] = None,
        cost_config: Optional[TransactionCostConfig] = None,
        initial_capital: float = 500000.0, # ₹5,00,000 base capital
    ):
        self.strategy = strategy or NiftyFuturesShortStrategy()
        self.cost_config = cost_config or TransactionCostConfig()
        self.initial_capital = initial_capital

    def run(
        self,
        data_provider: HistoricalMarketDataProvider,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        verbose: bool = False,
    ) -> Tuple[Optional[BacktestReport], str]:
        """
        Executes backtest over historical candles.
        Returns: (BacktestReport, status_message)
        """
        if not data_provider.has_sufficient_option_data():
            msg = "INSUFFICIENT HISTORICAL OPTION DATA FOR VALID BACKTEST"
            logger.warning(msg)
            return None, msg

        candles = data_provider.candles
        if len(candles) < 50:
            return None, "INSUFFICIENT CANDLE DATA FOR BACKTEST"

        cfg = self.strategy.config
        quantity = cfg.lot_size
        slippage_pts = self.cost_config.slippage_points

        trades: List[TradeLog] = []
        equity_curve: List[EquityPoint] = [
            EquityPoint(timestamp=candles[0].timestamp.isoformat(), equity=self.initial_capital)
        ]
        current_equity = self.initial_capital

        # Tracking state
        in_position = False
        pending_entry = False
        pending_setup: Optional[StrategyResult] = None
        pending_sl: float = 0.0
        rejection_candle_high: float = 0.0

        active_entry_price: float = 0.0
        active_entry_time: str = ""
        active_sl: float = 0.0
        active_target: float = 0.0
        active_setup_snapshot: Optional[StrategyResult] = None
        entry_candle_idx: int = 0

        # Run chronologically from candle 50 onwards
        for i in range(50, len(candles)):
            candle = candles[i]
            ts = candle.timestamp
            ist_dt = ts.astimezone(IST) if ts.tzinfo else ts
            date_str = ist_dt.strftime("%Y-%m-%d")
            time_str = ist_dt.strftime("%H:%M")

            # Date range filter
            if start_date and date_str < start_date:
                continue
            if end_date and date_str > end_date:
                break

            # ------------------------------------------------------------------
            # 1. EXECUTE PENDING SHORT ENTRY AT NEXT CANDLE OPEN
            # ------------------------------------------------------------------
            if pending_entry and not in_position:
                # SHORT entry at the NEXT candle OPEN (with slippage)
                # For SHORT (sell), slippage reduces execution price: open - slippage
                raw_entry = candle.open
                active_entry_price = raw_entry - slippage_pts
                active_entry_time = ist_dt.strftime("%Y-%m-%d %H:%M:%S")

                # Stop loss based on previous rejection candle HIGH + SL_BUFFER
                active_sl = rejection_candle_high + cfg.sl_buffer
                risk = active_sl - active_entry_price

                if risk <= 0:
                    # Invalid risk setup, cancel entry
                    pending_entry = False
                    pending_setup = None
                else:
                    active_target = active_entry_price - (risk * cfg.risk_reward)
                    active_setup_snapshot = pending_setup
                    entry_candle_idx = i
                    in_position = True
                    pending_entry = False
                    pending_setup = None

            # ------------------------------------------------------------------
            # 2. MONITOR ACTIVE SHORT POSITION EXITS
            # ------------------------------------------------------------------
            if in_position:
                exit_price: Optional[float] = None
                exit_reason: str = ""

                # Exit Rule 1: Stop Loss
                # For SHORT: position loses if price rises above SL
                if candle.high >= active_sl:
                    # Executed at SL or opened above SL due to gap
                    raw_exit = max(active_sl, candle.open)
                    exit_price = raw_exit + slippage_pts  # Slippage increases buy-to-cover price
                    exit_reason = "STOP_LOSS"

                # Exit Rule 2: Target
                # For SHORT: position wins if price falls to or below target
                elif candle.low <= active_target:
                    # Executed at Target or opened below target due to gap
                    raw_exit = min(active_target, candle.open)
                    exit_price = raw_exit + slippage_pts
                    exit_reason = "TARGET"

                # Exit Rule 3: Session Cutoff (e.g. >= 15:00)
                elif time_str >= cfg.session_end:
                    raw_exit = candle.close
                    exit_price = raw_exit + slippage_pts
                    exit_reason = "SESSION_CUTOFF"

                # Handle trade closure
                if exit_price is not None:
                    # Gross P&L = (Entry Price - Exit Price) * Quantity
                    gross_pnl = (active_entry_price - exit_price) * quantity
                    charges_dict = self.cost_config.calculate_charges(
                        entry_price=active_entry_price,
                        exit_price=exit_price,
                        quantity=quantity,
                    )
                    charges = charges_dict["total_charges"]
                    slippage_cost = charges_dict["slippage_cost"]
                    net_pnl = round(gross_pnl - charges, 2)

                    current_equity += net_pnl
                    equity_curve.append(
                        EquityPoint(
                            timestamp=ist_dt.strftime("%Y-%m-%d %H:%M:%S"),
                            equity=round(current_equity, 2),
                        )
                    )

                    snap = active_setup_snapshot
                    trade_log = TradeLog(
                        date=date_str,
                        entry_time=active_entry_time,
                        entry_price=round(active_entry_price, 2),
                        exit_time=ist_dt.strftime("%Y-%m-%d %H:%M:%S"),
                        exit_price=round(exit_price, 2),
                        quantity=quantity,
                        oi_resistance=snap.oi_resistance or 0.0 if snap else 0.0,
                        oi_resistance_strength=snap.oi_resistance_strength or 0.0 if snap else 0.0,
                        pivot_resistance=snap.pivot_resistance or 0.0 if snap else 0.0,
                        resistance_distance=snap.resistance_distance or 0.0 if snap else 0.0,
                        ema20=snap.ema20 or 0.0 if snap else 0.0,
                        ema50=snap.ema50 or 0.0 if snap else 0.0,
                        atr14=snap.atr14 or 0.0 if snap else 0.0,
                        ema_distance=snap.ema_distance or 0.0 if snap else 0.0,
                        futures_price=snap.futures_price or 0.0 if snap else 0.0,
                        trend_status="BEARISH" if (snap and snap.trend_bearish) else "NEUTRAL",
                        stop_loss=round(active_sl, 2),
                        target=round(active_target, 2),
                        gross_pnl=round(gross_pnl, 2),
                        charges=charges,
                        slippage=slippage_cost,
                        net_pnl=net_pnl,
                        exit_reason=exit_reason,
                    )
                    trades.append(trade_log)

                    if verbose:
                        print(f"[{date_str} {time_str}] SHORT EXIT: {exit_reason} | Net P&L: Rs. {net_pnl:+,.2f} | Equity: Rs. {current_equity:,.2f}")

                    in_position = False
                    active_setup_snapshot = None

            # ------------------------------------------------------------------
            # 3. EVALUATE STRATEGY AT CANDLE CLOSE FOR NEW ENTRY
            # ------------------------------------------------------------------
            if not in_position and not pending_entry:
                # Do not evaluate new entries past session cutoff
                if time_str < cfg.session_end:
                    data_provider.set_current_index(i)
                    snapshot = data_provider.get_market_snapshot()
                    result = self.strategy.evaluate(
                        snapshot=snapshot,
                        has_active_position=in_position,
                        bypass_risk_engine=False,
                    )

                    if result.signal == SignalType.SHORT:
                        # Queue entry for NEXT candle open
                        pending_entry = True
                        pending_setup = result
                        rejection_candle_high = candle.high
                        if verbose:
                            print(f"\n[{date_str} {time_str}] SHORT SIGNAL GENERATED!")
                            print(result.format_debug_output())

        # Compile comprehensive performance report
        report = self._compile_report(trades, equity_curve)
        return report, "SUCCESS"

    def _compile_report(
        self,
        trades: List[TradeLog],
        equity_curve: List[EquityPoint],
    ) -> BacktestReport:
        """Computes statistical metrics per prompt Section 26."""
        total_trades = len(trades)
        if total_trades == 0:
            return BacktestReport(
                total_trades=0,
                trade_logs=[],
                equity_curve=equity_curve,
            )

        winning_trades = [t for t in trades if t.net_pnl > 0]
        losing_trades = [t for t in trades if t.net_pnl <= 0]

        win_count = len(winning_trades)
        loss_count = len(losing_trades)
        win_rate = round((win_count / total_trades) * 100.0, 2)

        gross_profit = sum(t.gross_pnl for t in winning_trades)
        gross_loss = abs(sum(t.gross_pnl for t in losing_trades))
        net_pnl = sum(t.net_pnl for t in trades)

        total_charges = sum(t.charges for t in trades)
        total_slippage = sum(t.slippage for t in trades)

        avg_trade = round(net_pnl / total_trades, 2)
        avg_winner = round(sum(t.net_pnl for t in winning_trades) / max(1, win_count), 2) if win_count else 0.0
        avg_loser = round(sum(t.net_pnl for t in losing_trades) / max(1, loss_count), 2) if loss_count else 0.0

        profit_factor = round(gross_profit / max(1.0, gross_loss), 2) if gross_loss > 0 else (99.0 if gross_profit > 0 else 0.0)

        # Max Drawdown calculation
        peak = self.initial_capital
        max_dd = 0.0
        max_dd_pct = 0.0
        for pt in equity_curve:
            if pt.equity > peak:
                peak = pt.equity
            dd = peak - pt.equity
            dd_pct = (dd / peak) * 100.0 if peak > 0 else 0.0
            if dd > max_dd:
                max_dd = dd
            if dd_pct > max_dd_pct:
                max_dd_pct = dd_pct

        largest_winner = max((t.net_pnl for t in trades), default=0.0)
        largest_loser = min((t.net_pnl for t in trades), default=0.0)

        # Holding duration
        holding_times = []
        for t in trades:
            try:
                t_in = datetime.strptime(t.entry_time, "%Y-%m-%d %H:%M:%S")
                t_out = datetime.strptime(t.exit_time, "%Y-%m-%d %H:%M:%S")
                holding_times.append((t_out - t_in).total_seconds() / 60.0)
            except Exception:
                holding_times.append(15.0)

        avg_holding_time = round(sum(holding_times) / max(1, len(holding_times)), 1)

        unique_days = len(set(t.date for t in trades))
        trades_per_day = round(total_trades / max(1, unique_days), 2)

        return BacktestReport(
            total_trades=total_trades,
            winning_trades=win_count,
            losing_trades=loss_count,
            win_rate=win_rate,
            gross_profit=round(gross_profit, 2),
            gross_loss=round(gross_loss, 2),
            net_pnl=round(net_pnl, 2),
            average_trade=avg_trade,
            average_winner=avg_winner,
            average_loser=avg_loser,
            profit_factor=profit_factor,
            maximum_drawdown=round(max_dd, 2),
            maximum_drawdown_pct=round(max_dd_pct, 2),
            largest_winner=round(largest_winner, 2),
            largest_loser=round(largest_loser, 2),
            average_holding_time_minutes=avg_holding_time,
            trades_per_day=trades_per_day,
            total_charges=round(total_charges, 2),
            total_slippage=round(total_slippage, 2),
            trade_logs=trades,
            equity_curve=equity_curve,
        )
