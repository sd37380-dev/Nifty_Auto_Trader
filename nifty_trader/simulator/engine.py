"""
Real-Feel NIFTY Option Paper Trade Simulation Engine.

Simulates NIFTY ATM Call and Put options with real market dynamics:
- Execution directly on real historical option contracts (OHLC, Volume, OI)
- Configurable realistic slippage (bid-ask spread penalty)
- Trailing Stop-Loss, Profit Targets, and 15:15 IST EOD Auto-Square-Off
- Comprehensive Indian F&O Regulatory Charges (STT, GST, SEBI, Stamp Duty, Brokerage)
- Both Fast Backtest Mode and Candle-by-Candle Live Playback Mode
"""

from datetime import datetime, timezone
import logging
from pathlib import Path
import random
import sqlite3
import time
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
import pandas as pd
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from nifty_trader.simulator.charges import IndianFOChargesCalculator
from nifty_trader.simulator.contracts import (
    ExitReason,
    OptionPosition,
    SignalType,
    SimulationSummary,
    TradeResult,
    TradeSignal,
)
from nifty_trader.simulator.rules import BaseStrategyRule, EMAPivotBounceRule

logger = logging.getLogger(__name__)
console = Console()


def compute_supertrend(df: pd.DataFrame, period: int = 10, multiplier: float = 3.0) -> Tuple[pd.Series, pd.Series]:
    """Computes Supertrend indicator values and direction (+1 bull, -1 bear)."""
    hl2 = (df['spot_high'] + df['spot_low']) / 2.0
    tr1 = df['spot_high'] - df['spot_low']
    tr2 = (df['spot_high'] - df['spot_close'].shift(1)).abs()
    tr3 = (df['spot_low'] - df['spot_close'].shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(period).mean()

    basic_upper = hl2 + (multiplier * atr)
    basic_lower = hl2 - (multiplier * atr)

    upper_band = basic_upper.copy()
    lower_band = basic_lower.copy()
    trend = pd.Series(1, index=df.index)

    for i in range(1, len(df)):
        if df['spot_close'].iloc[i-1] > upper_band.iloc[i-1]:
            upper_band.iloc[i] = basic_upper.iloc[i]
        else:
            upper_band.iloc[i] = min(basic_upper.iloc[i], upper_band.iloc[i-1])

        if df['spot_close'].iloc[i-1] < lower_band.iloc[i-1]:
            lower_band.iloc[i] = basic_lower.iloc[i]
        else:
            lower_band.iloc[i] = max(basic_lower.iloc[i], lower_band.iloc[i-1])

        if df['spot_close'].iloc[i] > upper_band.iloc[i-1]:
            trend.iloc[i] = 1
        elif df['spot_close'].iloc[i] < lower_band.iloc[i-1]:
            trend.iloc[i] = -1
        else:
            trend.iloc[i] = trend.iloc[i-1]

    st_values = pd.Series(
        np.where(trend == 1, lower_band, upper_band), index=df.index
    )
    return st_values, trend


def compute_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Computes Relative Strength Index (RSI)."""
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50.0)


class NiftyOptionSimulator:
    """
    High-fidelity paper trade simulator for NIFTY options.
    """

    def __init__(
        self,
        db_path: Optional[str] = None,
        lot_size: int = 65,
        default_lots: int = 1,
        slippage_pts: float = 0.5,
        initial_capital: float = 100000.0,
    ):
        if db_path:
            self.db_path = Path(db_path).resolve()
        else:
            pkg_cand = Path(__file__).resolve().parent.parent.parent / "data" / "hermes_research" / "market_data.db"
            local_cand = Path("data/hermes_research/market_data.db").resolve()
            if pkg_cand.exists() and pkg_cand.stat().st_size > 1000000:
                self.db_path = pkg_cand
            elif local_cand.exists() and local_cand.stat().st_size > 1000000:
                self.db_path = local_cand
            elif pkg_cand.exists():
                self.db_path = pkg_cand
            else:
                self.db_path = local_cand
        self.lot_size = lot_size
        self.default_lots = default_lots
        self.slippage_pts = slippage_pts
        self.initial_capital = initial_capital
        self.active_position: Optional[OptionPosition] = None
        self.closed_trades: List[TradeResult] = []

    def load_dataset(self, timeframe: str = "15M", days_back: Optional[int] = None) -> pd.DataFrame:
        """Loads and precomputes spot, option contracts, and technical indicators."""
        if not self.db_path.exists():
            raise FileNotFoundError(f"Market database not found at {self.db_path}")

        conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        try:
            # 1. Spot data
            spot_df = pd.read_sql_query(
                f"SELECT timestamp, open as spot_open, high as spot_high, low as spot_low, close as spot_close, volume as spot_vol FROM normalized_bars WHERE symbol='NIFTY' AND timeframe='{timeframe}' ORDER BY timestamp ASC",
                conn
            )
            # 2. ATM CE options
            ce_df = pd.read_sql_query(
                f"SELECT timestamp, open as ce_open, high as ce_high, low as ce_low, close as ce_close, volume as ce_vol, open_interest as ce_oi FROM normalized_bars WHERE symbol='NIFTY_ATM_CE' AND timeframe='{timeframe}' ORDER BY timestamp ASC",
                conn
            )
            # 3. ATM PE options
            pe_df = pd.read_sql_query(
                f"SELECT timestamp, open as pe_open, high as pe_high, low as pe_low, close as pe_close, volume as pe_vol, open_interest as pe_oi FROM normalized_bars WHERE symbol='NIFTY_ATM_PE' AND timeframe='{timeframe}' ORDER BY timestamp ASC",
                conn
            )
        finally:
            conn.close()

        spot_df = spot_df.drop_duplicates(subset=['timestamp'])
        ce_df = ce_df.drop_duplicates(subset=['timestamp'])
        pe_df = pe_df.drop_duplicates(subset=['timestamp'])

        m = pd.merge(spot_df, ce_df, on='timestamp', how='inner')
        m = pd.merge(m, pe_df, on='timestamp', how='inner')

        m['dt'] = pd.to_datetime(m['timestamp'], format='ISO8601')
        m = m.set_index('dt')
        m = m.sort_index()

        # IST conversion
        m['ist'] = m.index + pd.Timedelta(hours=5, minutes=30)
        m['date'] = m['ist'].dt.date
        m['time_str'] = m['ist'].dt.strftime('%H:%M')

        # Filter market hours 09:15 to 15:30 IST
        m = m[(m['time_str'] >= '09:15') & (m['time_str'] <= '15:30')].copy()

        # Compute Technical Indicators
        m['ema_9'] = m['spot_close'].ewm(span=9, adjust=False).mean()
        m['ema_14'] = m['spot_close'].ewm(span=14, adjust=False).mean()
        m['ema_21'] = m['spot_close'].ewm(span=21, adjust=False).mean()
        m['ema_50'] = m['spot_close'].ewm(span=50, adjust=False).mean()
        m['ema_200'] = m['spot_close'].ewm(span=200, adjust=False).mean()
        m['rsi'] = compute_rsi(m['spot_close'], 14)
        m['supertrend'], m['supertrend_dir'] = compute_supertrend(m, 10, 3.0)

        # Intraday VWAP
        m['typical_price'] = (m['spot_high'] + m['spot_low'] + m['spot_close']) / 3.0
        m['pv'] = m['typical_price'] * m['spot_vol']
        m['vwap'] = m.groupby('date')['pv'].cumsum() / m.groupby('date')['spot_vol'].cumsum().replace(0, 1)

        # Daily CPR & Pivot points
        daily = m.groupby('date').agg(
            day_h=('spot_high', 'max'),
            day_l=('spot_low', 'min'),
            day_c=('spot_close', 'last')
        )
        daily_prev = daily.shift(1)
        pivot = (daily_prev['day_h'] + daily_prev['day_l'] + daily_prev['day_c']) / 3.0
        r1 = (2.0 * pivot) - daily_prev['day_l']
        s1 = (2.0 * pivot) - daily_prev['day_h']
        bc = (daily_prev['day_h'] + daily_prev['day_l']) / 2.0
        tc = (2.0 * pivot) - bc
        cpr_top = np.maximum(tc, bc)
        cpr_bot = np.minimum(tc, bc)

        pivots_df = pd.DataFrame({
            'pivot': pivot, 'r1': r1, 's1': s1, 'cpr_top': cpr_top, 'cpr_bot': cpr_bot
        }, index=daily.index)

        m = m.join(pivots_df, on='date')

        # Filter by days_back if requested
        if days_back:
            unique_dates = sorted(m['date'].unique())
            if len(unique_dates) > days_back:
                start_d = unique_dates[-days_back]
                m = m[m['date'] >= start_d].copy()

        return m.dropna(subset=['ema_14'])

    def _execute_entry(
        self,
        signal: TradeSignal,
        candle: pd.Series,
        lots: int,
        rule_name: str,
    ) -> OptionPosition:
        """Executes a realistic market buy order for Call or Put with slippage."""
        opt_type = "CE" if signal.signal_type == SignalType.BUY_CE else "PE"
        spot_close = candle["spot_close"]
        atm_strike = signal.strike or int(round(spot_close / 50.0) * 50)

        # Obtain base premium from real option contract bar open
        if opt_type == "CE":
            base_premium = float(candle.get("ce_open", 100.0))
        else:
            base_premium = float(candle.get("pe_open", 100.0))

        # Add realistic market-order entry slippage (+0.5 to +1.0 pt)
        executed_premium = round(base_premium + self.slippage_pts, 2)
        qty = lots * self.lot_size

        # Support Stop Loss as points value or percentage of premium
        if getattr(signal, "sl_mode", "POINTS") == "PERCENT":
            sl_pts = executed_premium * (signal.sl_points / 100.0)
        else:
            sl_pts = signal.sl_points

        # Support Target / Exit as points value or percentage of premium
        if getattr(signal, "target_mode", "POINTS") == "PERCENT":
            target_pts = executed_premium * (signal.target_points / 100.0)
        else:
            target_pts = signal.target_points

        sl_price = max(1.0, round(executed_premium - sl_pts, 2))
        target_price = round(executed_premium + target_pts, 2)

        pos = OptionPosition(
            trade_id=f"sim_{int(time.time() * 1000) % 1000000}",
            symbol="NIFTY",
            option_type=opt_type,
            strike=atm_strike,
            qty=qty,
            lots=lots,
            entry_time=f"{candle['date']} {candle['time_str']}",
            entry_spot=round(spot_close, 1),
            entry_premium=executed_premium,
            current_premium=executed_premium,
            sl_price=sl_price,
            target_price=target_price,
            highest_premium=executed_premium,
            trailing_sl=signal.trailing_sl,
            trail_step=signal.trail_points,
            sl_mode=getattr(signal, "sl_mode", "POINTS"),
            target_mode=getattr(signal, "target_mode", "POINTS"),
            mtm_pnl=0.0,
            status="OPEN",
        )
        return pos

    def _execute_exit(
        self,
        pos: OptionPosition,
        candle: pd.Series,
        raw_exit_premium: float,
        reason: ExitReason,
        rule_name: str,
    ) -> TradeResult:
        """Executes a realistic market sell order with slippage and full charges."""
        # Subtract exit slippage (-0.5 to -1.0 pt penalty)
        exit_premium = max(0.5, round(raw_exit_premium - self.slippage_pts, 2))
        exit_spot = round(candle["spot_close"], 1)
        exit_time = f"{candle['date']} {candle['time_str']}"

        gross_pnl = round((exit_premium - pos.entry_premium) * pos.qty, 2)

        # Calculate exact statutory deductions and brokerage
        charges = IndianFOChargesCalculator.calculate(
            buy_price=pos.entry_premium,
            sell_price=exit_premium,
            qty=pos.qty,
        )

        net_pnl = round(gross_pnl - charges.total_charges, 2)
        pnl_pct = round(((exit_premium - pos.entry_premium) / pos.entry_premium) * 100.0, 2)

        # Calculate holding duration
        try:
            t_in = datetime.strptime(pos.entry_time, "%Y-%m-%d %H:%M")
            t_out = datetime.strptime(exit_time, "%Y-%m-%d %H:%M")
            dur = max(15, int((t_out - t_in).total_seconds() / 60))
        except Exception:
            dur = 15

        res = TradeResult(
            trade_id=pos.trade_id,
            symbol=pos.symbol,
            option_type=pos.option_type,
            strike=pos.strike,
            lots=pos.lots,
            qty=pos.qty,
            entry_time=pos.entry_time,
            exit_time=exit_time,
            entry_spot=pos.entry_spot,
            exit_spot=exit_spot,
            entry_premium=pos.entry_premium,
            exit_premium=exit_premium,
            exit_reason=reason,
            gross_pnl=gross_pnl,
            brokerage=charges.brokerage,
            taxes=round(charges.total_charges - charges.brokerage, 2),
            total_charges=charges.total_charges,
            net_pnl=net_pnl,
            pnl_pct=pnl_pct,
            duration_minutes=dur,
            rule_name=rule_name,
        )
        return res

    def run_simulation(
        self,
        rule: BaseStrategyRule,
        timeframe: str = "15M",
        days_back: Optional[int] = 30,
        playback_mode: bool = False,
        playback_speed: float = 0.05,
    ) -> SimulationSummary:
        """
        Runs the simulation loop over historical or playback data.
        """
        df = self.load_dataset(timeframe=timeframe, days_back=days_back)
        self.active_position = None
        self.closed_trades = []

        console.print(f"\n[bold green]🚀 Launching NIFTY Option Simulator[/bold green]")
        console.print(f"📊 Strategy Rule   : [cyan]{rule.name}[/cyan] ({rule.description})")
        console.print(f"⏱️ Timeframe       : [magenta]{timeframe}[/magenta] | Dataset: {len(df)} candles across {df['date'].nunique()} trading days")
        console.print(f"💼 Lot Size        : [yellow]{self.lot_size} qty[/yellow] (1 Lot) | Capital: Rs. {self.initial_capital:,.2f}")
        console.print(f"⚡ Mode            : [{'bold yellow' if playback_mode else 'bold cyan'}]{'Live Candle Playback' if playback_mode else 'Fast Backtest'}[/]\n")

        for idx, row in df.iterrows():
            time_str = row['time_str']
            date_str = str(row['date'])

            # Extract option high, low, close for current bar
            if self.active_position is not None:
                is_ce = (self.active_position.option_type == "CE")
                opt_low = float(row['ce_low'] if is_ce else row['pe_low'])
                opt_high = float(row['ce_high'] if is_ce else row['pe_high'])
                opt_close = float(row['ce_close'] if is_ce else row['pe_close'])

                # Update MTM P&L
                self.active_position.current_premium = opt_close
                self.active_position.mtm_pnl = round(
                    (opt_close - self.active_position.entry_premium) * self.active_position.qty, 2
                )

                # Trailing SL update
                if self.active_position.trailing_sl and opt_high > self.active_position.highest_premium:
                    gain = opt_high - self.active_position.highest_premium
                    if gain >= self.active_position.trail_step:
                        self.active_position.highest_premium = opt_high
                        self.active_position.sl_price = max(
                            self.active_position.sl_price,
                            round(opt_high - self.active_position.trail_step, 2)
                        )

                # Check Exits:
                # 1. Stop Loss Hit
                if opt_low <= self.active_position.sl_price:
                    trade_res = self._execute_exit(
                        self.active_position, row, self.active_position.sl_price, ExitReason.STOP_LOSS, rule.name
                    )
                    self.closed_trades.append(trade_res)
                    self._log_trade_exit(trade_res)
                    self.active_position = None

                # 2. Target Hit
                elif opt_high >= self.active_position.target_price:
                    trade_res = self._execute_exit(
                        self.active_position, row, self.active_position.target_price, ExitReason.TARGET, rule.name
                    )
                    self.closed_trades.append(trade_res)
                    self._log_trade_exit(trade_res)
                    self.active_position = None

                # 3. EOD Auto Square-off at 15:15 IST
                elif time_str >= "15:15":
                    trade_res = self._execute_exit(
                        self.active_position, row, opt_close, ExitReason.EOD_SQUAREOFF, rule.name
                    )
                    self.closed_trades.append(trade_res)
                    self._log_trade_exit(trade_res)
                    self.active_position = None

            # If flat, evaluate rule for new trade setup
            if self.active_position is None:
                indicators = {
                    "ema_9": row["ema_9"],
                    "ema_14": row["ema_14"],
                    "ema_21": row["ema_21"],
                    "ema_50": row["ema_50"],
                    "ema_200": row["ema_200"],
                    "rsi": row["rsi"],
                    "vwap": row["vwap"],
                    "supertrend": row["supertrend"],
                    "supertrend_dir": row["supertrend_dir"],
                    "pivot": row["pivot"],
                    "r1": row["r1"],
                    "s1": row["s1"],
                    "cpr_top": row["cpr_top"],
                    "cpr_bot": row["cpr_bot"],
                }

                signal: TradeSignal = rule.on_candle(row, indicators, self.active_position)

                if signal.signal_type in [SignalType.BUY_CE, SignalType.BUY_PE]:
                    self.active_position = self._execute_entry(
                        signal, row, self.default_lots, rule.name
                    )
                    self._log_trade_entry(self.active_position, signal.reason)

            # Playback console ticker
            if playback_mode:
                self._render_playback_ticker(row)
                if playback_speed > 0:
                    time.sleep(playback_speed)

        # Build summary
        summary = self._compile_summary(self.closed_trades)
        self._print_institutional_report(summary, rule.name)
        return summary

    def _log_trade_entry(self, pos: OptionPosition, reason: str):
        col = "green" if pos.option_type == "CE" else "red"
        console.print(
            f"  [bold {col}]⚡ [ENTRY {pos.option_type}][/bold {col}] {pos.entry_time} | Strike: {pos.strike} {pos.option_type} | Buy: Rs. {pos.entry_premium:.2f} | SL: Rs. {pos.sl_price:.2f} | Target: Rs. {pos.target_price:.2f} | Reason: {reason}"
        )

    def _log_trade_exit(self, res: TradeResult):
        col = "green" if res.net_pnl > 0 else "red"
        symbol_icon = "🎉 WIN" if res.net_pnl > 0 else "🛑 LOSS"
        console.print(
            f"  [{col}]🏁 [EXIT {res.exit_reason.value}][/] {res.exit_time} | Exit: Rs. {res.exit_premium:.2f} | Net P&L: [{col}]Rs. {res.net_pnl:+,.2f} ({res.pnl_pct:+.1f}%)[/{col}] | Charges: Rs. {res.total_charges:.2f} | {symbol_icon}"
        )

    def _render_playback_ticker(self, candle: pd.Series):
        pos_str = f"FLAT"
        if self.active_position:
            pnl_col = "green" if self.active_position.mtm_pnl >= 0 else "red"
            pos_str = f"[{pnl_col}]{self.active_position.option_type} {self.active_position.strike} | MTM: Rs. {self.active_position.mtm_pnl:+,.2f}[/{pnl_col}]"
        # Dim timestamp line
        print(f"\r  🕒 {candle['date']} {candle['time_str']} | NIFTY Spot: {candle['spot_close']:.1f} | Active: {pos_str}     ", end="")

    def _compile_summary(self, trades: List[TradeResult]) -> SimulationSummary:
        if not trades:
            return SimulationSummary()

        wins = [t for t in trades if t.net_pnl > 0]
        losses = [t for t in trades if t.net_pnl < 0]
        evens = [t for t in trades if t.net_pnl == 0]

        gross_profit = sum(t.gross_pnl for t in wins)
        gross_loss = abs(sum(t.gross_pnl for t in losses))
        gross_pnl = sum(t.gross_pnl for t in trades)
        total_charges = sum(t.total_charges for t in trades)
        net_pnl = sum(t.net_pnl for t in trades)

        profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else 999.0
        win_rate = round((len(wins) / len(trades)) * 100.0, 1)

        # Calculate max drawdown
        equity_curve = []
        cum = 0.0
        peak = 0.0
        max_dd = 0.0
        for t in trades:
            cum += t.net_pnl
            if cum > peak:
                peak = cum
            dd = peak - cum
            if dd > max_dd:
                max_dd = dd
            equity_curve.append(cum)

        max_dd_pct = round((max_dd / self.initial_capital) * 100.0, 2)
        avg_holding = int(np.mean([t.duration_minutes for t in trades])) if trades else 0

        return SimulationSummary(
            total_trades=len(trades),
            winning_trades=len(wins),
            losing_trades=len(losses),
            breakeven_trades=len(evens),
            win_rate=win_rate,
            gross_profit=round(gross_profit, 2),
            gross_loss=round(gross_loss, 2),
            gross_pnl=round(gross_pnl, 2),
            total_charges=round(total_charges, 2),
            net_pnl=round(net_pnl, 2),
            profit_factor=profit_factor,
            avg_trade_pnl=round(net_pnl / len(trades), 2),
            max_profit_trade=max([t.net_pnl for t in trades], default=0.0),
            max_loss_trade=min([t.net_pnl for t in trades], default=0.0),
            max_drawdown_amount=round(max_dd, 2),
            max_drawdown_pct=max_dd_pct,
            avg_holding_minutes=avg_holding,
            trades=trades,
        )

    def _print_institutional_report(self, s: SimulationSummary, rule_name: str):
        table = Table(title=f"📊 [bold green]Paper Trading Performance Report — {rule_name}[/bold green]")
        table.add_column("Performance Metric", style="cyan", no_wrap=True)
        table.add_column("Value", style="bold magenta")

        table.add_row("Total Executed Trades", str(s.total_trades))
        table.add_row("Winning Trades / Losing Trades", f"[green]{s.winning_trades}[/green] / [red]{s.losing_trades}[/red]")
        wr_col = "green" if s.win_rate >= 50 else "yellow"
        table.add_row("Empirical Win Rate", f"[{wr_col}]{s.win_rate:.1f}%[/{wr_col}]")
        table.add_row("Profit Factor", f"{s.profit_factor:.2f}")
        table.add_row("Gross Profit (Options)", f"Rs. {s.gross_profit:+,.2f}")
        table.add_row("Gross Loss (Options)", f"Rs. -{s.gross_loss:,.2f}")
        table.add_row("Gross P&L", f"Rs. {s.gross_pnl:+,.2f}")
        table.add_row("Total Regulatory Taxes & Brokerage", f"[yellow]Rs. {s.total_charges:,.2f}[/yellow]")

        net_col = "bold green" if s.net_pnl > 0 else "bold red"
        table.add_row("REAL NET P&L (After All Charges)", f"[{net_col}]Rs. {s.net_pnl:+,.2f}[/{net_col}]")
        roi = (s.net_pnl / self.initial_capital) * 100.0
        table.add_row("Return on Capital (Rs. 1,00,000)", f"[{net_col}]{roi:+.2f}%[/{net_col}]")
        table.add_row("Average Trade P&L", f"Rs. {s.avg_trade_pnl:+,.2f}")
        table.add_row("Max Single Trade Win", f"[green]Rs. {s.max_profit_trade:+,.2f}[/green]")
        table.add_row("Max Single Trade Loss", f"[red]Rs. {s.max_loss_trade:+,.2f}[/red]")
        table.add_row("Maximum Peak-to-Trough Drawdown", f"[red]Rs. {s.max_drawdown_amount:,.2f} ({s.max_drawdown_pct:.1f}%)[/red]")
        table.add_row("Average Trade Duration", f"{s.avg_holding_minutes} minutes")

        console.print("\n")
        console.print(table)
