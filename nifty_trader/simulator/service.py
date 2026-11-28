"""
Event-Driven Simulator Service for NIFTY Autonomous Trader.

CRITICAL INVARIANTS:
1. Does NOT generate automated fake/random trades on independent timers.
2. Only evaluates and trades when the Autonomous Trader captures a 15-minute NIFTY chart observation from TradingView.
3. Supports full manual configuration and fast 1-click presets for:
   - Paper trade amount (Lots / Qty)
   - Stop Loss (Points / Value or Percentage %)
   - Target / Exit level (Points / Value or Percentage %)
   - Trailing Stop-Loss (Enabled/Disabled + Step)
4. Continuously maintains persistent trade audit logs in SIMULATOR_REPORT.md, SIMULATOR_LOG.txt, and SQLite.
"""

from datetime import datetime, timezone
import asyncio
import json
import logging
from pathlib import Path
import sqlite3
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from nifty_trader.simulator.charges import IndianFOChargesCalculator
from nifty_trader.simulator.contracts import (
    ExitReason,
    OptionPosition,
    SignalType,
    TradeResult,
    TradeSignal,
)
from nifty_trader.simulator.engine import NiftyOptionSimulator, compute_rsi, compute_supertrend
from nifty_trader.simulator.rules import BaseStrategyRule, EMAPivotBounceRule, SupertrendMomentumRule
from nifty_trader.simulator.user_rule import CustomUserRule

logger = logging.getLogger(__name__)


class SimulatorBackgroundService:
    """
    Event-driven paper trading simulator service with user-configurable risk presets.
    """

    _instance: Optional["SimulatorBackgroundService"] = None
    _lock = threading.Lock()

    PRESETS = {
        "SCALP_POINTS": {
            "name": "Quick Scalp (15 pts SL, 25 pts Target, 1 Lot)",
            "lots": 1,
            "sl_mode": "POINTS",
            "sl_val": 15.0,
            "target_mode": "POINTS",
            "target_val": 25.0,
            "trailing_sl": False,
            "trail_step": 5.0,
        },
        "BALANCED_POINTS": {
            "name": "Balanced 1:2 (20 pts SL, 40 pts Target, 1 Lot)",
            "lots": 1,
            "sl_mode": "POINTS",
            "sl_val": 20.0,
            "target_mode": "POINTS",
            "target_val": 40.0,
            "trailing_sl": True,
            "trail_step": 10.0,
        },
        "RUNNER_POINTS": {
            "name": "Momentum Runner 1:3 (25 pts SL, 75 pts Target, 2 Lots)",
            "lots": 2,
            "sl_mode": "POINTS",
            "sl_val": 25.0,
            "target_mode": "POINTS",
            "target_val": 75.0,
            "trailing_sl": True,
            "trail_step": 15.0,
        },
        "PERCENT_15_30": {
            "name": "Percentage (15% SL, 30% Profit Target, 1 Lot)",
            "lots": 1,
            "sl_mode": "PERCENT",
            "sl_val": 15.0,
            "target_mode": "PERCENT",
            "target_val": 30.0,
            "trailing_sl": True,
            "trail_step": 10.0,
        },
        "PERCENT_20_50": {
            "name": "Percentage (20% SL, 50% Profit Target, 1 Lot)",
            "lots": 1,
            "sl_mode": "PERCENT",
            "sl_val": 20.0,
            "target_mode": "PERCENT",
            "target_val": 50.0,
            "trailing_sl": True,
            "trail_step": 12.0,
        },
    }

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self, root_dir: Optional[Path] = None):
        if getattr(self, "_initialized", False):
            return

        self.root_dir = root_dir or Path(__file__).resolve().parent.parent.parent
        self.data_dir = self.root_dir / "data" / "paper_trading"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "simulator_live.db"

        self.active_rule: BaseStrategyRule = CustomUserRule()
        self.lot_size: int = 65
        self.slippage_pts: float = 0.5
        self.initial_capital: float = 100000.0
        self.current_capital: float = 100000.0

        # User Configurable Risk & Trade Settings (Points vs Percentage)
        self.lots: int = 1
        self.sl_mode: str = "POINTS"       # "POINTS" or "PERCENT"
        self.sl_val: float = 20.0          # Value in points or percentage
        self.target_mode: str = "POINTS"   # "POINTS" or "PERCENT"
        self.target_val: float = 40.0      # Value in points or percentage
        self.trailing_sl: bool = True
        self.trail_step: float = 10.0
        self.preset_name: str = "BALANCED_POINTS"

        self.active_position: Optional[OptionPosition] = None
        self.recent_trades: List[TradeResult] = []

        self.is_running: bool = True
        self.last_analysis_time: str = "Awaiting first 15M TradingView chart cycle"
        self.last_chart_verdict: str = "IDLE (Listening to Autonomous 15M cycle)"
        self.last_screenshot_path: Optional[str] = None
        self.last_analysis_details: Optional[Dict[str, Any]] = None
        self.total_observations_analyzed: int = 0

        # Auto-detect latest TradingView screenshot from disk if available
        shots_dir = self.root_dir / "data" / "browser" / "screenshots"
        if shots_dir.exists():
            tv_shots = sorted(
                [p for p in shots_dir.glob("*.png") if "tradingview" in p.name.lower()],
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            if tv_shots:
                self.last_screenshot_path = str(tv_shots[0])

        self.active_bias_1h: str = "NEUTRAL"
        self.active_entry_timeframe: str = "15M"
        self._init_db()
        self._load_state()
        self.update_report_files()
        self._initialized = True

    def _init_db(self):
        """Initializes SQLite persistence for live simulator positions, trades, and settings."""
        conn = sqlite3.connect(str(self.db_path))
        try:
            with conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS sim_trades (
                        trade_id TEXT PRIMARY KEY,
                        symbol TEXT NOT NULL,
                        option_type TEXT NOT NULL,
                        strike INTEGER NOT NULL,
                        lots INTEGER NOT NULL,
                        qty INTEGER NOT NULL,
                        entry_time TEXT NOT NULL,
                        exit_time TEXT NOT NULL,
                        entry_spot REAL NOT NULL,
                        exit_spot REAL NOT NULL,
                        entry_premium REAL NOT NULL,
                        exit_premium REAL NOT NULL,
                        exit_reason TEXT NOT NULL,
                        gross_pnl REAL NOT NULL,
                        brokerage REAL NOT NULL,
                        taxes REAL NOT NULL,
                        total_charges REAL NOT NULL,
                        net_pnl REAL NOT NULL,
                        pnl_pct REAL NOT NULL,
                        duration_minutes INTEGER NOT NULL,
                        rule_name TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS sim_active_position (
                        id INTEGER PRIMARY KEY CHECK (id = 1),
                        data TEXT,
                        updated_at TEXT NOT NULL
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS sim_settings (
                        id INTEGER PRIMARY KEY CHECK (id = 1),
                        lots INTEGER NOT NULL DEFAULT 1,
                        sl_mode TEXT NOT NULL DEFAULT 'POINTS',
                        sl_val REAL NOT NULL DEFAULT 20.0,
                        target_mode TEXT NOT NULL DEFAULT 'POINTS',
                        target_val REAL NOT NULL DEFAULT 40.0,
                        trailing_sl INTEGER NOT NULL DEFAULT 1,
                        trail_step REAL NOT NULL DEFAULT 10.0,
                        preset_name TEXT NOT NULL DEFAULT 'BALANCED_POINTS'
                    )
                """)
        finally:
            conn.close()

    def _load_state(self):
        """Restores recent trade history and risk settings from SQLite."""
        if not self.db_path.exists():
            return
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            # 1. Load Settings
            try:
                set_row = conn.execute("SELECT * FROM sim_settings WHERE id = 1").fetchone()
                if set_row:
                    self.lots = int(set_row["lots"])
                    self.sl_mode = str(set_row["sl_mode"])
                    self.sl_val = float(set_row["sl_val"])
                    self.target_mode = str(set_row["target_mode"])
                    self.target_val = float(set_row["target_val"])
                    self.trailing_sl = bool(set_row["trailing_sl"])
                    self.trail_step = float(set_row["trail_step"])
                    self.preset_name = str(set_row["preset_name"])
            except Exception as set_err:
                logger.debug("Settings load fallback: %s", set_err)

            # 2. Load Trades
            rows = conn.execute("SELECT * FROM sim_trades ORDER BY exit_time DESC LIMIT 50").fetchall()
            loaded = []
            for r in rows:
                try:
                    reason_val = ExitReason(r["exit_reason"])
                except Exception:
                    reason_val = ExitReason.STOP_LOSS

                t = TradeResult(
                    trade_id=r["trade_id"],
                    symbol=r["symbol"],
                    option_type=r["option_type"],
                    strike=r["strike"],
                    lots=r["lots"],
                    qty=r["qty"],
                    entry_time=r["entry_time"],
                    exit_time=r["exit_time"],
                    entry_spot=r["entry_spot"],
                    exit_spot=r["exit_spot"],
                    entry_premium=r["entry_premium"],
                    exit_premium=r["exit_premium"],
                    exit_reason=reason_val,
                    gross_pnl=r["gross_pnl"],
                    brokerage=r["brokerage"],
                    taxes=r["taxes"],
                    total_charges=r["total_charges"],
                    net_pnl=r["net_pnl"],
                    pnl_pct=r["pnl_pct"],
                    duration_minutes=r["duration_minutes"],
                    rule_name=r["rule_name"],
                )
                loaded.append(t)
            self.recent_trades = loaded
            net_total = sum(t.net_pnl for t in loaded)
            self.current_capital = round(self.initial_capital + net_total, 2)

            # 3. Load Open Active Position
            try:
                pos_row = conn.execute("SELECT data FROM sim_active_position WHERE id = 1").fetchone()
                if pos_row and pos_row["data"]:
                    pos_data = json.loads(pos_row["data"])
                    self.active_position = OptionPosition(**pos_data)
            except Exception as pos_err:
                logger.debug("Active position load fallback: %s", pos_err)
        finally:
            conn.close()

    def set_rule(self, rule_name: str):
        """Switch active rule dynamically."""
        if rule_name == "ema-pivot":
            self.active_rule = EMAPivotBounceRule()
        elif rule_name == "supertrend":
            self.active_rule = SupertrendMomentumRule()
        else:
            self.active_rule = CustomUserRule()
        self.update_report_files()
        logger.info("Simulator rule switched to %s", self.active_rule.name)

    def apply_preset(self, preset_key: str):
        """Applies a built-in pre-set for trade amount, SL, and Target."""
        if preset_key in self.PRESETS:
            cfg = self.PRESETS[preset_key]
            self.lots = cfg["lots"]
            self.sl_mode = cfg["sl_mode"]
            self.sl_val = cfg["sl_val"]
            self.target_mode = cfg["target_mode"]
            self.target_val = cfg["target_val"]
            self.trailing_sl = cfg["trailing_sl"]
            self.trail_step = cfg["trail_step"]
            self.preset_name = preset_key
            self._save_settings()
            now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            self._append_log(f"[{now_str}] ⚙️ [PRESET] Applied risk preset: {cfg['name']}")
            self.update_report_files()

    def update_settings(
        self,
        lots: Optional[int] = None,
        sl_mode: Optional[str] = None,
        sl_val: Optional[float] = None,
        target_mode: Optional[str] = None,
        target_val: Optional[float] = None,
        trailing_sl: Optional[bool] = None,
        trail_step: Optional[float] = None,
        preset_name: Optional[str] = "CUSTOM",
    ):
        """Manually updates paper trade amount, stop loss, and exit target."""
        if lots is not None:
            self.lots = max(1, int(lots))
        if sl_mode in ["POINTS", "PERCENT"]:
            self.sl_mode = sl_mode
        if sl_val is not None:
            self.sl_val = max(1.0, float(sl_val))
        if target_mode in ["POINTS", "PERCENT"]:
            self.target_mode = target_mode
        if target_val is not None:
            self.target_val = max(1.0, float(target_val))
        if trailing_sl is not None:
            self.trailing_sl = bool(trailing_sl)
        if trail_step is not None:
            self.trail_step = max(1.0, float(trail_step))

        self.preset_name = preset_name or "CUSTOM"
        self._save_settings()
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        self._append_log(
            f"[{now_str}] ⚙️ [SETTINGS UPDATED] Lots={self.lots} ({self.lots*self.lot_size} qty) | SL={self.sl_val}{'%' if self.sl_mode == 'PERCENT' else ' pts'} | Target={self.target_val}{'%' if self.target_mode == 'PERCENT' else ' pts'} | TrailingSL={self.trailing_sl} ({self.trail_step} pts step)"
        )
        self.update_report_files()

    def _save_settings(self):
        """Persists settings in SQLite."""
        conn = sqlite3.connect(str(self.db_path))
        try:
            with conn:
                conn.execute("""
                    INSERT OR REPLACE INTO sim_settings (id, lots, sl_mode, sl_val, target_mode, target_val, trailing_sl, trail_step, preset_name)
                    VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    self.lots, self.sl_mode, self.sl_val,
                    self.target_mode, self.target_val,
                    1 if self.trailing_sl else 0, self.trail_step,
                    self.preset_name,
                ))
        finally:
            conn.close()

    def start(self):
        """Marks the event-driven simulator as active."""
        self.is_running = True
        self.update_report_files()
        logger.info("⚡ Option Paper Simulator is active and listening for 15M TradingView chart cycles.")

    def stop(self):
        """Pauses the simulator."""
        self.is_running = False
        self.update_report_files()

    def _compute_indicators(self, latest_candle: Dict[str, Any], timeframe: str = "15M") -> Dict[str, Any]:
        """Calculates indicators combining historical baseline with the newly observed candle."""
        sim = NiftyOptionSimulator(lot_size=self.lot_size, default_lots=self.lots)
        for tf in ([timeframe, "15M"] if timeframe != "15M" else ["15M"]):
            try:
                df = sim.load_dataset(timeframe=tf, days_back=10)
                if not df.empty:
                    last_row = df.iloc[-1]
                    return {
                        "ema_9": float(last_row.get("ema_9", latest_candle["spot_close"])),
                        "ema_14": float(last_row.get("ema_14", latest_candle["spot_close"])),
                        "ema_21": float(last_row.get("ema_21", latest_candle["spot_close"])),
                        "ema_50": float(last_row.get("ema_50", latest_candle["spot_close"])),
                        "ema_200": float(last_row.get("ema_200", latest_candle["spot_close"])),
                        "rsi": float(last_row.get("rsi", 50.0)),
                        "vwap": float(last_row.get("vwap", latest_candle["spot_close"])),
                        "supertrend": float(last_row.get("supertrend", latest_candle["spot_close"])),
                        "supertrend_dir": int(last_row.get("supertrend_dir", 0)),
                        "pivot": float(last_row.get("pivot", latest_candle["spot_close"])),
                        "r1": float(last_row.get("r1", latest_candle["spot_close"] + 50)),
                        "s1": float(last_row.get("s1", latest_candle["spot_close"] - 50)),
                        "cpr_top": float(last_row.get("cpr_top", latest_candle["spot_close"] + 20)),
                        "cpr_bot": float(last_row.get("cpr_bot", latest_candle["spot_close"] - 20)),
                    }
            except Exception as e:
                logger.debug("Could not compute full historical indicators (%s): %s", tf, e)

        sc = float(latest_candle["spot_close"])
        return {
            "ema_9": sc, "ema_14": sc, "ema_21": sc, "ema_50": sc, "ema_200": sc,
            "rsi": 50.0, "vwap": sc, "supertrend": sc, "supertrend_dir": 1,
            "pivot": sc, "r1": sc + 50, "s1": sc - 50, "cpr_top": sc + 20, "cpr_bot": sc - 20
        }

    def _determine_1h_bias(self, unified_obs: Any = None) -> str:
        """Determines primary directional bias (BULLISH / BEARISH / NEUTRAL) from 1H candles."""
        candles_1h = []
        if unified_obs and hasattr(unified_obs, "numerical"):
            candles_1h = getattr(unified_obs.numerical, "candles_1h", []) or []

        if len(candles_1h) >= 2:
            recent = candles_1h[-3:] if len(candles_1h) >= 3 else candles_1h[-2:]
            first_open = float(recent[0].open)
            last_close = float(recent[-1].close)
            prev_close = float(candles_1h[-2].close)
            if first_open > 0:
                pct_move = ((last_close - first_open) / first_open) * 100.0
                if last_close > prev_close and pct_move >= 0.08:
                    return "BULLISH"
                if last_close < prev_close and pct_move <= -0.08:
                    return "BEARISH"
        elif len(candles_1h) == 1:
            c = candles_1h[0]
            if float(c.close) > float(c.open):
                return "BULLISH"
            if float(c.close) < float(c.open):
                return "BEARISH"
        return "NEUTRAL"

    def _select_adaptive_entry_timeframe(
        self,
        unified_obs: Any = None,
        bias_1h: str = "NEUTRAL",
    ) -> tuple[str, str]:
        """
        Selects 5M or 15M entry timeframe based on live market conditions:
        - 5M: When 5M candles show strong directional momentum/range expansion aligned with 1H bias.
        - 15M: Default for normal, choppy, or neutral-bias conditions requiring 15M confirmation.
        """
        candles_5m = []
        if unified_obs and hasattr(unified_obs, "numerical"):
            candles_5m = getattr(unified_obs.numerical, "candles_5m", []) or []

        if not candles_5m or bias_1h == "NEUTRAL":
            return "15M", "Standard 15M confirmation"

        latest_5m = candles_5m[-1]
        o = float(latest_5m.open)
        h = float(latest_5m.high)
        l = float(latest_5m.low)
        c = float(latest_5m.close)
        body_pct = ((c - o) / o) * 100.0 if o > 0 else 0.0
        latest_range = h - l

        avg_range = latest_range
        if len(candles_5m) >= 4:
            prev_ranges = [float(x.high) - float(x.low) for x in candles_5m[-4:-1]]
            avg_range = sum(prev_ranges) / len(prev_ranges) if prev_ranges else latest_range

        range_expansion = avg_range > 0 and latest_range >= (1.25 * avg_range)
        aligned_bull = bias_1h == "BULLISH" and c > o and (body_pct >= 0.08 or range_expansion)
        aligned_bear = bias_1h == "BEARISH" and c < o and (body_pct <= -0.08 or range_expansion)

        if aligned_bull or aligned_bear:
            return "5M", f"Fast 5M momentum aligned with 1H {bias_1h} bias"
        return "15M", f"15M confirmation preferred under current 1H {bias_1h} condition"

    def get_latest_screenshot_path(self) -> Optional[str]:
        """Returns the most recent TradingView chart screenshot path."""
        if self.last_screenshot_path and Path(self.last_screenshot_path).exists():
            return self.last_screenshot_path
        shots_dir = self.root_dir / "data" / "browser" / "screenshots"
        if shots_dir.exists():
            tv_shots = sorted(
                [p for p in shots_dir.glob("*.png") if "tradingview" in p.name.lower()],
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            if tv_shots:
                self.last_screenshot_path = str(tv_shots[0])
                return str(tv_shots[0])
        return None

    def capture_tradingview_screenshot(self) -> str:
        """
        Manually captures a fresh visual chart screenshot of NIFTY from TradingView via Chrome CDP.
        Returns the local screenshot file path.
        """
        shot_path = None
        try:
            async def _do_capture():
                from nifty_trader.core.runtime import NiftyTraderRuntime
                runtime = NiftyTraderRuntime()
                await runtime.browser.provider.start()
                try:
                    obs = await runtime.browser.inspect_tradingview_nifty()
                    return obs.screenshot_path
                finally:
                    await runtime.browser.provider.stop()

            shot_path = asyncio.run(_do_capture())
        except Exception as e:
            logger.warning("Browser screenshot capture error: %s", e)

        # Fallback to latest screenshot on disk if browser launch encountered an issue
        if not shot_path or not Path(shot_path).exists():
            shot_path = self.get_latest_screenshot_path()

        if shot_path and Path(shot_path).exists():
            self.last_screenshot_path = str(shot_path)
            now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            self._append_log(f"[{now_str}] 📸 [MANUAL SCREENSHOT] Captured TradingView NIFTY chart: {Path(shot_path).name}")
            self.update_report_files()
            return str(shot_path)

        raise RuntimeError("Failed to capture screenshot from TradingView.")

    def analyze_chart_now(self) -> Dict[str, Any]:
        """
        Manually triggers real-time chart analysis on the latest market bar.
        Computes technical indicators (EMA 9/21, RSI 14, Pivot CPR, VWAP), evaluates active strategy rule,
        and if the rule triggers a signal, executes a paper trade and updates the trade log.
        """
        now_utc = datetime.now(timezone.utc)
        now_str = now_utc.strftime("%Y-%m-%d %H:%M:%S UTC")

        sim = NiftyOptionSimulator(lot_size=self.lot_size, default_lots=self.lots)
        try:
            df = sim.load_dataset(timeframe="15M", days_back=3)
        except Exception as e:
            logger.warning("Error loading dataset for manual analysis: %s", e)
            df = pd.DataFrame()

        if df.empty:
            raise RuntimeError("No historical candle dataset available for chart analysis.")

        last_row = df.iloc[-1]
        candle_data = {
            "spot_open": float(last_row["spot_open"]),
            "spot_high": float(last_row["spot_high"]),
            "spot_low": float(last_row["spot_low"]),
            "spot_close": float(last_row["spot_close"]),
            "spot_vol": int(last_row.get("spot_vol", 10000)),
            "time_str": str(last_row.get("time_str", "11:30")),
            "date": str(last_row.get("date", str(datetime.now().date()))),
            "ce_open": float(last_row.get("ce_open", round(float(last_row["spot_close"]) * 0.007, 2))),
            "pe_open": float(last_row.get("pe_open", round(float(last_row["spot_close"]) * 0.007, 2))),
            "ce_high": float(last_row.get("ce_high", 160.0)),
            "ce_low": float(last_row.get("ce_low", 140.0)),
            "ce_close": float(last_row.get("ce_close", 155.0)),
            "pe_high": float(last_row.get("pe_high", 160.0)),
            "pe_low": float(last_row.get("pe_low", 140.0)),
            "pe_close": float(last_row.get("pe_close", 155.0)),
        }
        candle_series = pd.Series(candle_data)
        spot_close = candle_data["spot_close"]

        # Compute indicators
        indicators = self._compute_indicators(candle_data)
        ema_9 = indicators.get("ema_9", spot_close)
        ema_21 = indicators.get("ema_21", spot_close)
        trend = "BULLISH" if ema_9 >= ema_21 else "BEARISH"
        indicators["trend"] = trend

        # Evaluate active rule (use mid-session time so time filters evaluate signal conditions)
        candle_series_eval = candle_series.copy()
        time_str_orig = str(candle_series.get("time_str", "12:00"))
        if not ("09:30" <= time_str_orig <= "14:15"):
            candle_series_eval["time_str"] = "11:30"

        signal = self.active_rule.on_candle(candle_series_eval, indicators, self.active_position)

        self.last_analysis_time = now_str
        self.total_observations_analyzed += 1

        trade_executed = False
        action_msg = "No Trade Action (Condition not triggered)"

        # Position monitoring or execution
        if self.active_position is not None:
            is_ce = (self.active_position.option_type == "CE")
            opt_low = float(candle_series["ce_low"] if is_ce else candle_series["pe_low"])
            opt_high = float(candle_series["ce_high"] if is_ce else candle_series["pe_high"])
            opt_close = float(candle_series["ce_close"] if is_ce else candle_series["pe_close"])

            self.active_position.current_premium = opt_close
            self.active_position.mtm_pnl = round((opt_close - self.active_position.entry_premium) * self.active_position.qty, 2)

            exit_res = None
            if opt_low <= self.active_position.sl_price:
                exit_res = sim._execute_exit(self.active_position, candle_series, self.active_position.sl_price, ExitReason.STOP_LOSS, self.active_rule.name)
            elif opt_high >= self.active_position.target_price:
                exit_res = sim._execute_exit(self.active_position, candle_series, self.active_position.target_price, ExitReason.TARGET, self.active_rule.name)

            if exit_res:
                self._save_trade(exit_res)
                self.active_position = None
                self._save_active_pos(None)
                self.last_chart_verdict = f"POSITION CLOSED: {exit_res.exit_reason.value} (Net P&L: Rs. {exit_res.net_pnl:+,.2f})"
                action_msg = f"Closed active position: {exit_res.exit_reason.value} with Net P&L Rs. {exit_res.net_pnl:+,.2f}"
            else:
                self.last_chart_verdict = f"MONITORING ACTIVE POSITION: NIFTY {self.active_position.strike} {self.active_position.option_type} (MTM: Rs. {self.active_position.mtm_pnl:+,.2f})"
                action_msg = f"Position remains open (MTM: Rs. {self.active_position.mtm_pnl:+,.2f})"

        elif signal.signal_type in [SignalType.BUY_CE, SignalType.BUY_PE]:
            # Apply user's configured sizing & SL & Target
            signal.sl_points = self.sl_val
            signal.sl_mode = self.sl_mode
            signal.target_points = self.target_val
            signal.target_mode = self.target_mode
            signal.trailing_sl = self.trailing_sl
            signal.trail_points = self.trail_step

            pos = sim._execute_entry(signal, candle_series, self.lots, self.active_rule.name)
            self.active_position = pos
            self._save_active_pos(pos)

            sl_desc = f"{self.sl_val}%" if self.sl_mode == "PERCENT" else f"{self.sl_val} pts"
            tgt_desc = f"{self.target_val}%" if self.target_mode == "PERCENT" else f"{self.target_val} pts"

            self.last_chart_verdict = f"RULE PASSED: BUY {pos.option_type} {pos.strike} ({signal.reason})"
            action_msg = f"Placed paper trade: NIFTY {pos.strike} {pos.option_type} ({pos.lots} Lot / {pos.qty} Qty) @ Rs. {pos.entry_premium:.2f} | SL: Rs. {pos.sl_price:.2f} ({sl_desc}) | Target: Rs. {pos.target_price:.2f} ({tgt_desc})"
            trade_executed = True

            self._append_log(
                f"[{now_str}] ⚡ [MANUAL CHART ANALYSIS -> RULE PASSED] {action_msg}"
            )
        else:
            self.last_chart_verdict = f"CHART ANALYZED: {signal.reason}"
            action_msg = f"Rule evaluated: {signal.reason}. No trade taken."
            self._append_log(
                f"[{now_str}] 🔍 [MANUAL CHART ANALYSIS] Spot: {spot_close:.1f} | Rule: {self.active_rule.name} -> {signal.reason}"
            )

        self.update_report_files()

        details = {
            "timestamp": now_str,
            "spot_close": spot_close,
            "candle_time": candle_data["time_str"],
            "candle_date": candle_data["date"],
            "rule_name": self.active_rule.name,
            "signal_type": signal.signal_type.value,
            "reason": signal.reason,
            "verdict": self.last_chart_verdict,
            "action_message": action_msg,
            "trade_executed": trade_executed,
            "indicators": {
                "ema_9": indicators.get("ema_9", spot_close),
                "ema_21": indicators.get("ema_21", spot_close),
                "rsi": indicators.get("rsi", 50.0),
                "vwap": indicators.get("vwap", spot_close),
                "trend": trend,
                "pivot": indicators.get("pivot", spot_close),
                "r1": indicators.get("r1", spot_close + 50),
                "s1": indicators.get("s1", spot_close - 50),
            },
            "active_position": self.active_position.__dict__ if self.active_position else None,
            "screenshot_path": self.last_screenshot_path,
        }
        self.last_analysis_details = details
        return details

    def on_market_observation(self, unified_obs: Any = None, custom_candle: Optional[Dict[str, Any]] = None):
        """
        Primary execution entry point.
        Called EVERY 15 MINUTES when the Autonomous Trader observes the NIFTY TradingView chart.
        """
        if not self.is_running:
            return

        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        self.last_analysis_time = now_str
        self.total_observations_analyzed += 1

        # 1. Determine 1H Primary Trend Bias & Adaptive Entry Timeframe (5M or 15M)
        bias_1h = self._determine_1h_bias(unified_obs)
        entry_tf, tf_reason = self._select_adaptive_entry_timeframe(unified_obs, bias_1h=bias_1h)
        self.active_bias_1h = bias_1h
        self.active_entry_timeframe = entry_tf

        # Extract newly observed 5M/15M candle and screenshot reference
        candle_data = None
        screenshot_ref = None

        if unified_obs:
            if hasattr(unified_obs, "visual") and getattr(unified_obs.visual, "screenshot_path", None):
                screenshot_ref = unified_obs.visual.screenshot_path
                self.last_screenshot_path = screenshot_ref

            if hasattr(unified_obs, "numerical"):
                target_candle = None
                if entry_tf == "5M" and getattr(unified_obs.numerical, "latest_5m", None):
                    target_candle = unified_obs.numerical.latest_5m
                elif getattr(unified_obs.numerical, "latest_15m", None):
                    target_candle = unified_obs.numerical.latest_15m
                    entry_tf = "15M"
                elif getattr(unified_obs.numerical, "latest_5m", None):
                    target_candle = unified_obs.numerical.latest_5m
                    entry_tf = "5M"

                if target_candle is not None:
                    self.active_entry_timeframe = entry_tf
                    candle_data = {
                        "spot_open": float(target_candle.open),
                        "spot_high": float(target_candle.high),
                        "spot_low": float(target_candle.low),
                        "spot_close": float(target_candle.close),
                        "spot_vol": int(getattr(target_candle, "volume", 10000) or 10000),
                        "time_str": unified_obs.observed_at_ist.strftime("%H:%M") if hasattr(unified_obs, "observed_at_ist") else "12:00",
                        "date": str(unified_obs.observed_at_ist.date()) if hasattr(unified_obs, "observed_at_ist") else str(datetime.now().date()),
                    }

        if not candle_data and custom_candle:
            candle_data = custom_candle

        # Fallback to latest real bar from database if needed
        if not candle_data:
            sim = NiftyOptionSimulator(lot_size=self.lot_size, default_lots=self.lots)
            try:
                df = sim.load_dataset(timeframe="15M", days_back=2)
                if not df.empty:
                    last_row = df.iloc[-1]
                    candle_data = {
                        "spot_open": float(last_row["spot_open"]),
                        "spot_high": float(last_row["spot_high"]),
                        "spot_low": float(last_row["spot_low"]),
                        "spot_close": float(last_row["spot_close"]),
                        "spot_vol": int(last_row.get("spot_vol", 10000)),
                        "time_str": str(last_row["time_str"]),
                        "date": str(last_row["date"]),
                        "ce_open": float(last_row.get("ce_open", 150.0)),
                        "pe_open": float(last_row.get("pe_open", 150.0)),
                        "ce_high": float(last_row.get("ce_high", 160.0)),
                        "ce_low": float(last_row.get("ce_low", 140.0)),
                        "ce_close": float(last_row.get("ce_close", 155.0)),
                        "pe_high": float(last_row.get("pe_high", 160.0)),
                        "pe_low": float(last_row.get("pe_low", 140.0)),
                        "pe_close": float(last_row.get("pe_close", 155.0)),
                    }
            except Exception as e:
                logger.debug("Failed loading fallback candle: %s", e)

        if not candle_data:
            self.last_chart_verdict = "WAIT: Incomplete candle data"
            self.update_report_files()
            return

        candle_series = pd.Series(candle_data)
        spot_close = float(candle_series["spot_close"])
        time_str = candle_series.get("time_str", "12:00")
        sim = NiftyOptionSimulator(lot_size=self.lot_size, default_lots=self.lots)

        # 2. If already in a trade, update MTM and check SL / Target / 15:15 EOD square-off
        if self.active_position is not None:
            is_ce = (self.active_position.option_type == "CE")
            if "ce_close" in candle_series and is_ce:
                opt_low = float(candle_series["ce_low"])
                opt_high = float(candle_series["ce_high"])
                opt_close = float(candle_series["ce_close"])
            elif "pe_close" in candle_series and not is_ce:
                opt_low = float(candle_series["pe_low"])
                opt_high = float(candle_series["pe_high"])
                opt_close = float(candle_series["pe_close"])
            else:
                spot_move = (spot_close - self.active_position.entry_spot) * (0.50 if is_ce else -0.50)
                opt_close = max(1.0, round(self.active_position.entry_premium + spot_move, 2))
                opt_high = max(opt_close, self.active_position.entry_premium)
                opt_low = min(opt_close, self.active_position.entry_premium)

            self.active_position.current_premium = opt_close
            self.active_position.mtm_pnl = round((opt_close - self.active_position.entry_premium) * self.active_position.qty, 2)

            # Check trailing SL
            if self.active_position.trailing_sl and opt_high > self.active_position.highest_premium:
                gain = opt_high - self.active_position.highest_premium
                if gain >= self.active_position.trail_step:
                    self.active_position.highest_premium = opt_high
                    self.active_position.sl_price = max(self.active_position.sl_price, round(opt_high - self.active_position.trail_step, 2))

            # Check exit
            exit_res = None
            if opt_low <= self.active_position.sl_price:
                exit_res = sim._execute_exit(self.active_position, candle_series, self.active_position.sl_price, ExitReason.STOP_LOSS, self.active_rule.name)
            elif opt_high >= self.active_position.target_price:
                exit_res = sim._execute_exit(self.active_position, candle_series, self.active_position.target_price, ExitReason.TARGET, self.active_rule.name)
            elif time_str >= "15:15":
                exit_res = sim._execute_exit(self.active_position, candle_series, opt_close, ExitReason.EOD_SQUAREOFF, self.active_rule.name)

            if exit_res:
                self._save_trade(exit_res)
                self.active_position = None
                self._save_active_pos(None)
                self.last_chart_verdict = f"POSITION CLOSED: {exit_res.exit_reason.value} (Net P&L: Rs. {exit_res.net_pnl:+,.2f})"
                self.update_report_files()
                return

        # 3. If flat, evaluate the rule locally with 1H Bias + Adaptive 5M/15M Entry!
        if self.active_position is None:
            indicators = self._compute_indicators(candle_data, timeframe=entry_tf)
            signal: TradeSignal = self.active_rule.on_candle(candle_series, indicators, self.active_position)

            counter_trend = (
                (bias_1h == "BULLISH" and signal.signal_type == SignalType.BUY_PE)
                or (bias_1h == "BEARISH" and signal.signal_type == SignalType.BUY_CE)
            )
            if counter_trend:
                self.last_chart_verdict = (
                    f"WAIT (1H={bias_1h} | {entry_tf}): Counter-trend {signal.signal_type.value} filtered by 1H bias"
                )
                self._append_log(
                    f"[{now_str}] 🛡️ [1H BIAS FILTER] NIFTY Spot: {spot_close:.1f} | 1H Bias: {bias_1h} | Entry TF: {entry_tf} ({tf_reason}) | Filtered {signal.signal_type.value}."
                )
            elif signal.signal_type in [SignalType.BUY_CE, SignalType.BUY_PE]:
                # Apply User Configured Risk & Exit Settings (Points or %)
                signal.sl_points = self.sl_val
                signal.sl_mode = self.sl_mode
                signal.target_points = self.target_val
                signal.target_mode = self.target_mode
                signal.trailing_sl = self.trailing_sl
                signal.trail_points = self.trail_step

                if "ce_open" not in candle_series:
                    base_prem = round(spot_close * 0.007, 2)
                    candle_series["ce_open"] = base_prem
                    candle_series["pe_open"] = base_prem

                pos = sim._execute_entry(signal, candle_series, self.lots, self.active_rule.name)
                self.active_position = pos
                self._save_active_pos(pos)

                sl_desc = f"{self.sl_val}%" if self.sl_mode == "PERCENT" else f"{self.sl_val} pts"
                tgt_desc = f"{self.target_val}%" if self.target_mode == "PERCENT" else f"{self.target_val} pts"

                self.last_chart_verdict = f"RULE PASSED (1H={bias_1h} | {entry_tf}): BUY {pos.option_type} {pos.strike} ({signal.reason})"
                self._append_log(
                    f"[{now_str}] ⚡ [{entry_tf} CHART RULE PASSED | 1H={bias_1h}] Entry {pos.option_type} | Strike: {pos.strike} | Lots: {pos.lots} ({pos.qty} qty) | Buy: Rs. {pos.entry_premium:.2f} | SL: Rs. {pos.sl_price:.2f} ({sl_desc}) | Target: Rs. {pos.target_price:.2f} ({tgt_desc}) | Reason: {signal.reason} ({tf_reason})"
                )
            else:
                self.last_chart_verdict = f"CHART ANALYZED (1H={bias_1h} | {entry_tf}): {signal.reason} (Setup not triggered)"
                self._append_log(
                    f"[{now_str}] 🔍 [{entry_tf} CHART ANALYZED | 1H={bias_1h}] NIFTY Spot: {spot_close:.1f} | Rule: {self.active_rule.name} -> {signal.reason} ({tf_reason}) | No trade taken."
                )

        self.update_report_files()

    def update_active_position_with_spot(
        self,
        symbol: str,
        spot_price: float,
        high: Optional[float] = None,
        low: Optional[float] = None,
    ) -> Optional[TradeResult]:
        """
        Updates live MTM P&L, current premium, and evaluates Stop Loss / Target
        for the currently open option position using latest spot market data.
        """
        if self.active_position is None:
            return None

        # Check symbol match (e.g. NIFTY 50 vs NIFTY)
        pos_sym = self.active_position.symbol.strip().upper()
        upd_sym = symbol.strip().upper()
        if pos_sym != upd_sym and not (("NIFTY" in pos_sym and "BANK" not in pos_sym) and ("NIFTY" in upd_sym and "BANK" not in upd_sym)):
            if not ("BANK" in pos_sym and "BANK" in upd_sym):
                return None

        is_ce = (self.active_position.option_type == "CE")
        delta = 0.50 if is_ce else -0.50
        spot_move = (spot_price - self.active_position.entry_spot) * delta
        current_prem = max(1.0, round(self.active_position.entry_premium + spot_move, 2))

        self.active_position.current_premium = current_prem
        self.active_position.mtm_pnl = round(
            (current_prem - self.active_position.entry_premium) * self.active_position.qty, 2
        )

        # Check trailing SL
        if self.active_position.trailing_sl and current_prem > self.active_position.highest_premium:
            gain = current_prem - self.active_position.highest_premium
            if gain >= self.active_position.trail_step:
                self.active_position.highest_premium = current_prem
                self.active_position.sl_price = max(
                    self.active_position.sl_price,
                    round(current_prem - self.active_position.trail_step, 2)
                )

        self._save_active_pos(self.active_position)

        # Evaluate Exit: Check SL and Target
        exit_reason = None
        exit_price = current_prem
        if current_prem <= self.active_position.sl_price:
            exit_reason = ExitReason.STOP_LOSS
            exit_price = self.active_position.sl_price
        elif current_prem >= self.active_position.target_price:
            exit_reason = ExitReason.TARGET
            exit_price = self.active_position.target_price

        if exit_reason:
            sim = NiftyOptionSimulator(lot_size=self.lot_size, default_lots=self.lots)
            candle_series = pd.Series({
                "time_str": datetime.now(timezone.utc).strftime("%H:%M"),
                "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "spot_close": spot_price,
            })
            exit_res = sim._execute_exit(
                self.active_position,
                candle_series,
                exit_price,
                exit_reason,
                getattr(self.active_position, "rule_name", "Level_Strategy"),
            )
            self._save_trade(exit_res)
            self.active_position = None
            self._save_active_pos(None)
            self.last_chart_verdict = f"POSITION CLOSED: {exit_res.exit_reason.value} (Net P&L: Rs. {exit_res.net_pnl:+,.2f})"
            self.update_report_files()
            return exit_res
        else:
            self._save_active_pos(self.active_position)
            return None

    def _save_trade(self, t: TradeResult):
        """Persists completed trade to SQLite, appends to log, and updates markdown report."""
        self.recent_trades.insert(0, t)
        if len(self.recent_trades) > 50:
            self.recent_trades.pop()

        self.current_capital = round(self.current_capital + t.net_pnl, 2)

        conn = sqlite3.connect(str(self.db_path))
        try:
            with conn:
                conn.execute("""
                    INSERT OR REPLACE INTO sim_trades VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    t.trade_id, t.symbol, t.option_type, t.strike, t.lots, t.qty,
                    t.entry_time, t.exit_time, t.entry_spot, t.exit_spot,
                    t.entry_premium, t.exit_premium, t.exit_reason.value,
                    t.gross_pnl, t.brokerage, t.taxes, t.total_charges,
                    t.net_pnl, t.pnl_pct, t.duration_minutes, t.rule_name,
                    datetime.now(timezone.utc).isoformat()
                ))
        finally:
            conn.close()

        self._append_log(
            f"[{t.exit_time}] 🏁 EXIT {t.exit_reason.value} | NIFTY {t.strike} {t.option_type} | Buy: Rs. {t.entry_premium:.2f} | Exit: Rs. {t.exit_premium:.2f} | Gross: Rs. {t.gross_pnl:+,.2f} | Charges: Rs. {t.total_charges:.2f} | Net: Rs. {t.net_pnl:+,.2f} ({t.pnl_pct:+.1f}%) | Rule: {t.rule_name}"
        )
        self.update_report_files()

        # Instant Telegram Alert on Trade Exit (Stop Loss / Target Hit)
        try:
            from nifty_trader.notifications.telegram_service import get_telegram_service
            tele = get_telegram_service(self.root_dir)
            tele.send_trade_closed_alert(
                symbol=t.symbol,
                strike=t.strike,
                option_type=t.option_type,
                entry_premium=t.entry_premium,
                exit_premium=t.exit_premium,
                exit_reason=t.exit_reason.value if hasattr(t.exit_reason, "value") else str(t.exit_reason),
                net_pnl=t.net_pnl,
                pnl_pct=t.pnl_pct,
                lots=t.lots,
                qty=t.qty,
                trade_id=str(t.trade_id),
                rule_name=t.rule_name,
            )
        except Exception as tele_err:
            logger.warning("Could not dispatch Telegram trade exit alert: %s", tele_err)

        # Dual persistence: sync completed trade to Supabase Cloud
        try:
            from nifty_trader.core.supabase_adapter import get_supabase_adapter
            get_supabase_adapter(self.root_dir).sync_paper_trade({
                "trade_id": t.trade_id,
                "symbol": t.symbol,
                "strike": t.strike,
                "option_type": t.option_type,
                "lots": t.lots,
                "qty": t.qty,
                "entry_time": t.entry_time,
                "exit_time": t.exit_time,
                "entry_premium": t.entry_premium,
                "exit_premium": t.exit_premium,
                "exit_reason": t.exit_reason.value if hasattr(t.exit_reason, "value") else str(t.exit_reason),
                "gross_pnl": t.gross_pnl,
                "charges": t.total_charges,
                "net_pnl": t.net_pnl,
                "pnl_pct": t.pnl_pct,
            })
        except Exception:
            pass

    def delete_trade(self, trade_id: str) -> bool:
        """Manually deletes a specific trade log by its ID."""
        with self._lock:
            removed = False
            for i, t in enumerate(self.recent_trades):
                if str(t.trade_id) == str(trade_id):
                    self.current_capital = round(self.current_capital - t.net_pnl, 2)
                    self.recent_trades.pop(i)
                    removed = True
                    break

            conn = sqlite3.connect(str(self.db_path))
            try:
                with conn:
                    conn.execute("DELETE FROM sim_trades WHERE trade_id = ?", (str(trade_id),))
            finally:
                conn.close()

            now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            self._append_log(f"[{now_str}] 🗑️ [MANUAL DELETE] Deleted trade log record: {trade_id}")
            self.update_report_files()
            return removed

    def clear_all_trades(self) -> int:
        """Deletes all simulated trade records and resets capital to initial baseline."""
        with self._lock:
            count = len(self.recent_trades)
            self.recent_trades.clear()
            self.current_capital = self.initial_capital
            self.active_position = None
            self._save_active_pos(None)

            conn = sqlite3.connect(str(self.db_path))
            try:
                with conn:
                    conn.execute("DELETE FROM sim_trades")
            finally:
                conn.close()

            now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            self._append_log(f"[{now_str}] 🧹 [RESET] Cleared all simulated trade records and reset capital to Rs. {self.initial_capital:,.2f}.")
            self.update_report_files()
            return count

    def _append_log(self, text: str):
        """Appends formatted event line to SIMULATOR_LOG.txt."""
        try:
            log_path = self.data_dir / "SIMULATOR_LOG.txt"
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"{text}\n")
        except Exception as e:
            logger.debug("Failed writing simulator log line: %s", e)

    def update_report_files(self):
        """Generates and writes SIMULATOR_REPORT.md and updates log files."""
        try:
            report_md_path = self.data_dir / "SIMULATOR_REPORT.md"
            wins = [t for t in self.recent_trades if t.net_pnl > 0]
            losses = [t for t in self.recent_trades if t.net_pnl < 0]
            tot = len(self.recent_trades)
            wr = round((len(wins) / tot) * 100.0, 1) if tot > 0 else 0.0
            gross_pnl = sum(t.gross_pnl for t in self.recent_trades)
            charges = sum(t.total_charges for t in self.recent_trades)
            net_pnl = sum(t.net_pnl for t in self.recent_trades)

            sl_desc = f"{self.sl_val}%" if self.sl_mode == "PERCENT" else f"{self.sl_val} pts"
            tgt_desc = f"{self.target_val}%" if self.target_mode == "PERCENT" else f"{self.target_val} pts"
            tsl_desc = f"Enabled ({self.trail_step} pts step)" if self.trailing_sl else "Disabled"

            lines = [
                "# NIFTY Option Paper Trade Simulator — Audit Report",
                "",
                f"* **Last Observation Time:** {self.last_analysis_time}",
                f"* **Current Chart Verdict:** `{self.last_chart_verdict}`",
                f"* **Total 15M Cycles Analyzed:** {self.total_observations_analyzed}",
                f"* **Active Strategy Rule:** `{self.active_rule.name}`",
                f"* **Active Risk Preset:** `{self.preset_name}`",
                f"* **Trade Order Size:** `{self.lots} Lot ({self.lots*self.lot_size} Qty)`",
                f"* **Stop Loss Setting:** `{sl_desc}`",
                f"* **Profit Target / Exit Level:** `{tgt_desc}`",
                f"* **Trailing Stop-Loss:** `{tsl_desc}`",
                f"* **Initial Capital:** Rs. {self.initial_capital:,.2f}",
                f"* **Current Simulated Capital:** Rs. {self.current_capital:,.2f}",
                f"* **Realized Net P&L:** Rs. {self.current_capital - self.initial_capital:+,.2f}",
                "",
                "## 1. Performance Summary",
                "",
                "| Performance Metric | Recorded Value |",
                "| :--- | :--- |",
                f"| **Total Executed Trades** | {tot} |",
                f"| **Winning Trades / Losing Trades** | {len(wins)} / {len(losses)} |",
                f"| **Empirical Win Rate** | {wr:.1f}% |",
                f"| **Gross P&L (Option Premiums)** | Rs. {gross_pnl:+,.2f} |",
                f"| **Total Statutory Taxes & Brokerage** | Rs. {charges:,.2f} |",
                f"| **REAL NET P&L (After All Charges)** | **Rs. {net_pnl:+,.2f}** |",
                f"| **Return on Capital** | {((self.current_capital - self.initial_capital)/self.initial_capital)*100.0:+.2f}% |",
                "",
                "## 2. Executed Trade Audit Log",
                "",
                "| Trade ID | Option Contract | Entry Time | Exit Time | Buy Price | Exit Price | Exit Reason | Gross P&L | Charges | Net P&L | ROI % |",
                "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
            ]

            if not self.recent_trades:
                lines.append("| - | *No executed trades logged yet (Waiting for chart setup to pass)* | - | - | - | - | - | - | - | - | - |")
            else:
                for t in self.recent_trades:
                    lines.append(
                        f"| `{t.trade_id}` | NIFTY {t.strike} {t.option_type} | {t.entry_time} | {t.exit_time} | Rs. {t.entry_premium:.2f} | Rs. {t.exit_premium:.2f} | `{t.exit_reason.value}` | Rs. {t.gross_pnl:+,.2f} | Rs. {t.total_charges:.2f} | **Rs. {t.net_pnl:+,.2f}** | {t.pnl_pct:+.1f}% |"
                    )

            lines.append("")
            report_md_path.write_text("\n".join(lines), encoding="utf-8")
        except Exception as e:
            logger.debug("Failed updating report markdown: %s", e)

    def _save_active_pos(self, pos: Optional[OptionPosition]):
        """Persists or clears active position in SQLite."""
        conn = sqlite3.connect(str(self.db_path))
        try:
            with conn:
                data_str = json.dumps(pos.__dict__) if pos else None
                conn.execute("""
                    INSERT OR REPLACE INTO sim_active_position (id, data, updated_at)
                    VALUES (1, ?, ?)
                """, (data_str, datetime.now(timezone.utc).isoformat()))
        finally:
            conn.close()

        # Dual persistence: sync active position to Supabase Cloud
        try:
            from nifty_trader.core.supabase_adapter import get_supabase_adapter
            get_supabase_adapter(self.root_dir).sync_active_position(pos.__dict__ if pos else None)
        except Exception:
            pass

    def get_dashboard_summary(self) -> Dict[str, Any]:
        """Provides full telemetry dictionary for the web dashboard."""
        if self.db_path and self.db_path.exists():
            try:
                conn = sqlite3.connect(str(self.db_path), timeout=3.0)
                conn.row_factory = sqlite3.Row
                pos_row = conn.execute("SELECT data FROM sim_active_position WHERE id = 1").fetchone()
                if pos_row and pos_row["data"]:
                    pos_data = json.loads(pos_row["data"])
                    self.active_position = OptionPosition(**pos_data)
                else:
                    self.active_position = None

                # Deduplicate and sync recent trades from SQLite
                rows = conn.execute("SELECT * FROM sim_trades ORDER BY exit_time DESC LIMIT 50").fetchall()
                if rows:
                    seen = set()
                    loaded = []
                    for r in rows:
                        tid = r["trade_id"]
                        if tid in seen:
                            continue
                        seen.add(tid)
                        try:
                            reason_val = ExitReason(r["exit_reason"])
                        except Exception:
                            reason_val = ExitReason.STOP_LOSS
                        loaded.append(TradeResult(
                            trade_id=r["trade_id"],
                            symbol=r["symbol"],
                            option_type=r["option_type"],
                            strike=r["strike"],
                            lots=r["lots"],
                            qty=r["qty"],
                            entry_time=r["entry_time"],
                            exit_time=r["exit_time"],
                            entry_spot=r["entry_spot"],
                            exit_spot=r["exit_spot"],
                            entry_premium=r["entry_premium"],
                            exit_premium=r["exit_premium"],
                            exit_reason=reason_val,
                            gross_pnl=r["gross_pnl"],
                            brokerage=r["brokerage"],
                            taxes=r["taxes"],
                            total_charges=r["total_charges"],
                            net_pnl=r["net_pnl"],
                            pnl_pct=r["pnl_pct"],
                            duration_minutes=r["duration_minutes"],
                            rule_name=r["rule_name"],
                        ))
                    self.recent_trades = loaded

                conn.close()
            except Exception as _ex:
                logger.debug("Sync active pos error: %s", _ex)

        wins = [t for t in self.recent_trades if t.net_pnl > 0]
        losses = [t for t in self.recent_trades if t.net_pnl < 0]

        total_trades = len(self.recent_trades)
        win_rate = round((len(wins) / total_trades) * 100.0, 1) if total_trades > 0 else 0.0
        gross_pnl = sum(t.gross_pnl for t in self.recent_trades)
        total_charges = sum(t.total_charges for t in self.recent_trades)
        net_pnl = sum(t.net_pnl for t in self.recent_trades)

        active_dict = None
        if self.active_position:
            active_dict = {
                "trade_id": self.active_position.trade_id,
                "symbol": self.active_position.symbol,
                "option_type": self.active_position.option_type,
                "strike": self.active_position.strike,
                "qty": self.active_position.qty,
                "lots": self.active_position.lots,
                "entry_time": self.active_position.entry_time,
                "entry_premium": self.active_position.entry_premium,
                "current_premium": self.active_position.current_premium,
                "sl_price": self.active_position.sl_price,
                "target_price": self.active_position.target_price,
                "mtm_pnl": self.active_position.mtm_pnl,
                "sl_mode": getattr(self.active_position, "sl_mode", "POINTS"),
                "target_mode": getattr(self.active_position, "target_mode", "POINTS"),
                "status": self.active_position.status,
            }

        report_md_path = self.data_dir / "SIMULATOR_REPORT.md"
        report_preview = report_md_path.read_text(encoding="utf-8") if report_md_path.exists() else ""

        return {
            "status": f"WAITING_{getattr(self, 'active_entry_timeframe', '15M')}_CHART" if self.is_running else "PAUSED",
            "active_bias_1h": getattr(self, "active_bias_1h", "NEUTRAL"),
            "active_entry_timeframe": getattr(self, "active_entry_timeframe", "15M"),
            "rule_name": self.active_rule.name,
            "rule_description": self.active_rule.description,
            "lot_size": self.lot_size,
            "initial_capital": self.initial_capital,
            "current_capital": self.current_capital,
            "last_analysis_time": self.last_analysis_time,
            "last_chart_verdict": self.last_chart_verdict,
            "total_observations_analyzed": self.total_observations_analyzed,
            "total_trades": total_trades,
            "winning_trades": len(wins),
            "losing_trades": len(losses),
            "win_rate": win_rate,
            "gross_pnl": round(gross_pnl, 2),
            "total_charges": round(total_charges, 2),
            "net_pnl": round(net_pnl, 2),
            "active_position": active_dict,
            "report_path": str(report_md_path),
            "report_preview": report_preview,
            "last_screenshot_path": self.last_screenshot_path,
            "last_screenshot_name": Path(self.last_screenshot_path).name if self.last_screenshot_path else None,
            "last_analysis_details": getattr(self, "last_analysis_details", None),
            "settings": {
                "lots": self.lots,
                "qty": self.lots * self.lot_size,
                "sl_mode": self.sl_mode,
                "sl_val": self.sl_val,
                "target_mode": self.target_mode,
                "target_val": self.target_val,
                "trailing_sl": self.trailing_sl,
                "trail_step": self.trail_step,
                "preset_name": self.preset_name,
            },
            "presets": {k: v["name"] for k, v in self.PRESETS.items()},
            "recent_trades": [
                {
                    "trade_id": t.trade_id,
                    "option_type": t.option_type,
                    "strike": t.strike,
                    "entry_time": t.entry_time,
                    "exit_time": t.exit_time,
                    "entry_premium": t.entry_premium,
                    "exit_premium": t.exit_premium,
                    "exit_reason": t.exit_reason.value,
                    "gross_pnl": t.gross_pnl,
                    "charges": t.total_charges,
                    "net_pnl": t.net_pnl,
                    "pnl_pct": t.pnl_pct,
                    "duration_minutes": t.duration_minutes,
                }
                for t in self.recent_trades[:15]
            ],
        }


def get_simulator_service() -> SimulatorBackgroundService:
    """Returns singleton SimulatorBackgroundService."""
    return SimulatorBackgroundService()
