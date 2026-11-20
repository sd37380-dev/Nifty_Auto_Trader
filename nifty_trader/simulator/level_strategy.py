"""
Custom Level-Based Trading Strategy Manager for NIFTY Autonomous Trader.

Features:
1. User can set custom key price levels (Spot price).
2. Supports Trigger Conditions:
   - TOUCH: Triggers when spot price touches or comes within threshold of level.
   - CROSS_ABOVE: Triggers when spot price crosses above the level (Bullish breakout).
   - CROSS_BELOW: Triggers when spot price crosses below the level (Bearish breakdown).
3. Executes Call (CE) or Put (PE) trades in the paper trade simulator.
4. Allows setting manual Stop Loss and Target levels as:
   - SPOT_LEVEL: Exit if Spot price hits user's designated price level.
   - POINTS: Exit if Option premium moves by X points.
   - PERCENT: Exit if Option premium moves by X percent.
5. Persists all triggers, states, and execution histories in SQLite (data/paper_trading/level_triggers.db).
"""

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import sqlite3
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class LevelTrigger:
    trigger_id: str
    instrument: str             # "NIFTY 50" or "BANKNIFTY"
    trigger_price: float        # Key Spot level to watch
    condition: str              # "TOUCH", "CROSS_ABOVE", "CROSS_BELOW"
    option_type: str            # "CE" or "PE"
    strike_mode: str            # "ATM" or specific strike string
    lots: int
    sl_type: str                # "SPOT_LEVEL", "POINTS", "PERCENT"
    sl_val: float               # Value corresponding to sl_type
    target_type: str            # "SPOT_LEVEL", "POINTS", "PERCENT"
    target_val: float           # Value corresponding to target_type
    trailing_sl: bool
    trail_step: float
    status: str                 # "ARMED", "TRIGGERED", "CANCELLED"
    created_at: str
    triggered_at: Optional[str] = None
    executed_trade_id: Optional[str] = None
    notes: Optional[str] = None


class LevelStrategyManager:
    """
    Manages custom user-defined level triggers and executes paper trades upon level breach.
    """

    _instance: Optional["LevelStrategyManager"] = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls, root_dir: Optional[Path] = None) -> "LevelStrategyManager":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls(root_dir=root_dir)
        return cls._instance

    def __init__(self, root_dir: Optional[Path] = None):
        self.root_dir = root_dir or Path(__file__).resolve().parent.parent.parent
        self.data_dir = self.root_dir / "data" / "paper_trading"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "level_triggers.db"

        self.triggers: Dict[str, LevelTrigger] = {}
        self.last_spots: Dict[str, float] = {}  # Previous spot prices to detect crossovers
        self._init_db()
        self._load_triggers()

    def _init_db(self):
        """Initializes SQLite table for custom level triggers."""
        conn = sqlite3.connect(str(self.db_path))
        try:
            with conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS level_triggers (
                        trigger_id TEXT PRIMARY KEY,
                        instrument TEXT NOT NULL,
                        trigger_price REAL NOT NULL,
                        condition TEXT NOT NULL,
                        option_type TEXT NOT NULL,
                        strike_mode TEXT NOT NULL,
                        lots INTEGER NOT NULL,
                        sl_type TEXT NOT NULL,
                        sl_val REAL NOT NULL,
                        target_type TEXT NOT NULL,
                        target_val REAL NOT NULL,
                        trailing_sl INTEGER NOT NULL,
                        trail_step REAL NOT NULL,
                        status TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        triggered_at TEXT,
                        executed_trade_id TEXT,
                        notes TEXT
                    )
                """)
        finally:
            conn.close()

    def _load_triggers(self):
        """Loads all level triggers into memory."""
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("SELECT * FROM level_triggers ORDER BY created_at DESC")
            for r in cur.fetchall():
                trig = LevelTrigger(
                    trigger_id=r["trigger_id"],
                    instrument=r["instrument"],
                    trigger_price=float(r["trigger_price"]),
                    condition=r["condition"],
                    option_type=r["option_type"],
                    strike_mode=r["strike_mode"],
                    lots=int(r["lots"]),
                    sl_type=r["sl_type"],
                    sl_val=float(r["sl_val"]),
                    target_type=r["target_type"],
                    target_val=float(r["target_val"]),
                    trailing_sl=bool(r["trailing_sl"]),
                    trail_step=float(r["trail_step"]),
                    status=r["status"],
                    created_at=r["created_at"],
                    triggered_at=r["triggered_at"],
                    executed_trade_id=r["executed_trade_id"],
                    notes=r["notes"],
                )
                self.triggers[trig.trigger_id] = trig
        finally:
            conn.close()

    def add_trigger(
        self,
        instrument: str = "NIFTY 50",
        trigger_price: float = 25400.0,
        condition: str = "CROSS_ABOVE",
        option_type: str = "CE",
        strike_mode: str = "ATM",
        lots: int = 1,
        sl_type: str = "SPOT_LEVEL",
        sl_val: float = 25350.0,
        target_type: str = "SPOT_LEVEL",
        target_val: float = 25550.0,
        trailing_sl: bool = False,
        trail_step: float = 10.0,
        notes: str = "",
    ) -> LevelTrigger:
        """Adds and arms a new custom level trigger."""
        trigger_id = f"LVL_{int(time.time() * 1000) % 1000000}"
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        trig = LevelTrigger(
            trigger_id=trigger_id,
            instrument=instrument.strip().upper(),
            trigger_price=round(float(trigger_price), 2),
            condition=condition.strip().upper(),
            option_type=option_type.strip().upper(),
            strike_mode=strike_mode.strip().upper(),
            lots=max(1, int(lots)),
            sl_type=sl_type.strip().upper(),
            sl_val=round(float(sl_val), 2),
            target_type=target_type.strip().upper(),
            target_val=round(float(target_val), 2),
            trailing_sl=bool(trailing_sl),
            trail_step=round(float(trail_step), 2),
            status="ARMED",
            created_at=now_str,
            notes=notes.strip() or f"Level trigger at {trigger_price}",
        )

        conn = sqlite3.connect(str(self.db_path))
        try:
            with conn:
                conn.execute("""
                    INSERT INTO level_triggers (
                        trigger_id, instrument, trigger_price, condition, option_type,
                        strike_mode, lots, sl_type, sl_val, target_type, target_val,
                        trailing_sl, trail_step, status, created_at, triggered_at,
                        executed_trade_id, notes
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    trig.trigger_id, trig.instrument, trig.trigger_price, trig.condition,
                    trig.option_type, trig.strike_mode, trig.lots, trig.sl_type,
                    trig.sl_val, trig.target_type, trig.target_val, int(trig.trailing_sl),
                    trig.trail_step, trig.status, trig.created_at, trig.triggered_at,
                    trig.executed_trade_id, trig.notes
                ))
        finally:
            conn.close()

        self.triggers[trigger_id] = trig
        logger.info(
            "Armed custom level trigger %s: %s @ %.2f -> BUY %s (SL: %s=%.2f, Target: %s=%.2f)",
            trigger_id, trig.instrument, trig.trigger_price, trig.option_type,
            trig.sl_type, trig.sl_val, trig.target_type, trig.target_val
        )
        return trig

    def cancel_trigger(self, trigger_id: str) -> bool:
        """Cancels an armed trigger."""
        if trigger_id in self.triggers:
            trig = self.triggers[trigger_id]
            trig.status = "CANCELLED"
            conn = sqlite3.connect(str(self.db_path))
            try:
                with conn:
                    conn.execute("UPDATE level_triggers SET status='CANCELLED' WHERE trigger_id=?", (trigger_id,))
            finally:
                conn.close()
            return True
        return False

    def delete_trigger(self, trigger_id: str) -> bool:
        """Deletes a trigger from SQLite and memory."""
        if trigger_id in self.triggers:
            del self.triggers[trigger_id]
        conn = sqlite3.connect(str(self.db_path))
        try:
            with conn:
                conn.execute("DELETE FROM level_triggers WHERE trigger_id=?", (trigger_id,))
            return True
        finally:
            conn.close()

    def list_triggers(self, current_spots: Optional[Dict[str, float]] = None) -> List[Dict[str, Any]]:
        """Returns all triggers formatted for the dashboard with live distance metrics."""
        current_spots = current_spots or {}
        out = []
        for trig in sorted(self.triggers.values(), key=lambda t: t.created_at, reverse=True):
            d = asdict(trig)
            inst = trig.instrument
            cur_spot = current_spots.get(inst) or current_spots.get("NIFTY 50", 0.0)
            if cur_spot > 0:
                dist = round(cur_spot - trig.trigger_price, 2)
                d["current_spot"] = cur_spot
                d["distance_pts"] = dist
                if abs(dist) <= 3.0:
                    d["proximity_desc"] = f"AT LEVEL (diff: {dist:+.1f} pts)"
                elif dist > 0:
                    d["proximity_desc"] = f"{dist:.1f} pts above level"
                else:
                    d["proximity_desc"] = f"{abs(dist):.1f} pts below level"
            else:
                d["current_spot"] = 0.0
                d["distance_pts"] = 0.0
                d["proximity_desc"] = "Awaiting live spot"
            out.append(d)
        return out

    def evaluate_spot_update(
        self,
        symbol: str,
        spot_price: float,
        day_high: Optional[float] = None,
        day_low: Optional[float] = None,
        day_open: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """
        Evaluates all armed level triggers against the updated spot price.
        Executes trade automatically if condition (TOUCH, CROSS_ABOVE, CROSS_BELOW) is met.
        """
        executed_events: List[Dict[str, Any]] = []
        sym_norm = symbol.strip().upper()
        prev_spot = self.last_spots.get(sym_norm)
        self.last_spots[sym_norm] = spot_price

        # Check all ARMED triggers for this symbol
        for trig_id, trig in list(self.triggers.items()):
            if trig.status != "ARMED":
                continue
            if trig.instrument != sym_norm and not (sym_norm in ["NIFTY", "NIFTY 50"] and trig.instrument in ["NIFTY", "NIFTY 50"]):
                continue

            lvl = trig.trigger_price
            cond = trig.condition
            is_triggered = False
            trigger_reason = ""

            # Evaluation logic
            if cond == "TOUCH":
                # Price touches within 3 points tolerance or day high/low breached level
                if abs(spot_price - lvl) <= 3.0:
                    is_triggered = True
                    trigger_reason = f"Spot {spot_price:.2f} touched level {lvl:.2f}"
                elif day_high and day_low and (day_low <= lvl <= day_high):
                    is_triggered = True
                    trigger_reason = f"Day Range [{day_low:.1f} - {day_high:.1f}] touched level {lvl:.2f}"

            elif cond == "CROSS_ABOVE":
                # Crossed above level: previously below or equal, now strictly above
                if prev_spot is not None and prev_spot <= lvl and spot_price > lvl:
                    is_triggered = True
                    trigger_reason = f"Spot crossed above {lvl:.2f} (from {prev_spot:.2f} to {spot_price:.2f})"
                elif spot_price > lvl and (prev_spot is None or prev_spot <= lvl):
                    is_triggered = True
                    trigger_reason = f"Spot {spot_price:.2f} crossed above level {lvl:.2f}"

            elif cond == "CROSS_BELOW":
                # Crossed below level: previously above or equal, now strictly below
                if prev_spot is not None and prev_spot >= lvl and spot_price < lvl:
                    is_triggered = True
                    trigger_reason = f"Spot crossed below {lvl:.2f} (from {prev_spot:.2f} to {spot_price:.2f})"
                elif spot_price < lvl and (prev_spot is None or prev_spot >= lvl):
                    is_triggered = True
                    trigger_reason = f"Spot {spot_price:.2f} crossed below level {lvl:.2f}"

            if is_triggered:
                # 1. Dispatch Telegram Level Breakout Alert
                try:
                    from nifty_trader.notifications.telegram_service import get_telegram_service
                    get_telegram_service(self.root_dir).send_level_breakout_alert(
                        instrument=trig.instrument,
                        current_spot=spot_price,
                        level_price=lvl,
                        condition=cond,
                        trigger_reason=trigger_reason,
                        action_note=f"Trade criteria matched for {trig.option_type}. Auto-executing paper trade immediately in simulator.",
                    )
                except Exception as tele_err:
                    logger.debug("Telegram level alert skipped: %s", tele_err)

                # 2. Directly execute trade into simulator
                exec_info = self._execute_level_trade(trig, spot_price, trigger_reason)
                if exec_info:
                    executed_events.append(exec_info)

        return executed_events

    def _execute_level_trade(self, trig: LevelTrigger, spot_price: float, trigger_reason: str) -> Optional[Dict[str, Any]]:
        """Executes the paper trade in SimulatorBackgroundService."""
        try:
            from nifty_trader.simulator.service import get_simulator_service
            from nifty_trader.simulator.contracts import SignalType, TradeSignal
            import pandas as pd

            sim_service = get_simulator_service()
            now_dt = datetime.now(timezone.utc)
            now_str = now_dt.strftime("%Y-%m-%d %H:%M:%S UTC")

            # 1. Determine Strike
            step = 100 if "BANK" in trig.instrument else 50
            if trig.strike_mode == "ATM":
                strike = int(round(spot_price / step) * step)
            else:
                try:
                    strike = int(float(trig.strike_mode))
                except Exception:
                    strike = int(round(spot_price / step) * step)

            # 2. Estimate base option premium from spot
            pct_factor = 0.006 if "BANK" in trig.instrument else 0.0075
            base_prem = round(spot_price * pct_factor, 2)
            executed_premium = round(base_prem + 0.5, 2)  # realistic market slippage

            # 3. Calculate Stop Loss Price & Target Price
            # Support SPOT_LEVEL, POINTS, PERCENT
            if trig.sl_type == "SPOT_LEVEL":
                # Delta approximation: 1 spot pt ≈ 0.5 option pt
                spot_dist = abs(spot_price - trig.sl_val)
                opt_sl_pts = max(5.0, round(spot_dist * 0.5, 2))
                sl_price = max(1.0, round(executed_premium - opt_sl_pts, 2))
                sl_desc = f"Spot Level {trig.sl_val:.1f} (~{opt_sl_pts:.1f} pts)"
            elif trig.sl_type == "PERCENT":
                opt_sl_pts = round(executed_premium * (trig.sl_val / 100.0), 2)
                sl_price = max(1.0, round(executed_premium - opt_sl_pts, 2))
                sl_desc = f"{trig.sl_val}% ({opt_sl_pts:.1f} pts)"
            else:  # POINTS
                opt_sl_pts = trig.sl_val
                sl_price = max(1.0, round(executed_premium - opt_sl_pts, 2))
                sl_desc = f"{opt_sl_pts:.1f} pts"

            if trig.target_type == "SPOT_LEVEL":
                spot_dist = abs(trig.target_val - spot_price)
                opt_tgt_pts = max(10.0, round(spot_dist * 0.5, 2))
                target_price = round(executed_premium + opt_tgt_pts, 2)
                tgt_desc = f"Spot Level {trig.target_val:.1f} (~{opt_tgt_pts:.1f} pts)"
            elif trig.target_type == "PERCENT":
                opt_tgt_pts = round(executed_premium * (trig.target_val / 100.0), 2)
                target_price = round(executed_premium + opt_tgt_pts, 2)
                tgt_desc = f"{trig.target_val}% ({opt_tgt_pts:.1f} pts)"
            else:  # POINTS
                opt_tgt_pts = trig.target_val
                target_price = round(executed_premium + opt_tgt_pts, 2)
                tgt_desc = f"{opt_tgt_pts:.1f} pts"

            # 4. Construct Signal & Position
            sig_type = SignalType.BUY_CE if trig.option_type == "CE" else SignalType.BUY_PE
            lot_size = 30 if "BANK" in trig.instrument else 65
            qty = trig.lots * lot_size
            trade_id = f"lvl_{int(time.time() * 1000) % 1000000}"

            from nifty_trader.simulator.contracts import OptionPosition
            pos = OptionPosition(
                trade_id=trade_id,
                symbol=trig.instrument,
                option_type=trig.option_type,
                strike=strike,
                qty=qty,
                lots=trig.lots,
                entry_time=now_str,
                entry_spot=round(spot_price, 2),
                entry_premium=executed_premium,
                current_premium=executed_premium,
                sl_price=sl_price,
                target_price=target_price,
                highest_premium=executed_premium,
                trailing_sl=trig.trailing_sl,
                trail_step=trig.trail_step,
                sl_mode=trig.sl_type,
                target_mode=trig.target_type,
                mtm_pnl=0.0,
                status="OPEN",
            )

            # 5. Place into simulator
            sim_service.active_position = pos
            sim_service._save_active_pos(pos)

            # Update trigger record
            trig.status = "TRIGGERED"
            trig.triggered_at = now_str
            trig.executed_trade_id = trade_id

            conn = sqlite3.connect(str(self.db_path))
            try:
                with conn:
                    conn.execute("""
                        UPDATE level_triggers
                        SET status='TRIGGERED', triggered_at=?, executed_trade_id=?
                        WHERE trigger_id=?
                    """, (now_str, trade_id, trig.trigger_id))
            finally:
                conn.close()

            # Dual persistence: sync updated trigger state to Supabase Cloud
            try:
                from nifty_trader.core.supabase_adapter import get_supabase_adapter
                get_supabase_adapter(self.root_dir).sync_level_trigger(asdict(trig))
            except Exception:
                pass

            log_msg = (
                f"[{now_str}] 🎯 [CUSTOM LEVEL STRATEGY TRIGGERED] Trigger '{trig.trigger_id}' hit! "
                f"Reason: {trigger_reason} | Executed BUY {trig.instrument} {strike} {trig.option_type} "
                f"({trig.lots} Lot / {qty} Qty) @ ₹{executed_premium:.2f} | "
                f"SL: ₹{sl_price:.2f} ({sl_desc}) | Target: ₹{target_price:.2f} ({tgt_desc}) | "
                f"Note: {trig.notes}"
            )
            sim_service._append_log(log_msg)
            sim_service.last_chart_verdict = f"LEVEL TRIGGERED: BUY {trig.instrument} {strike} {trig.option_type} ({trigger_reason})"
            sim_service.update_report_files()

            logger.info("Custom level trigger executed: %s", log_msg)

            return {
                "trigger_id": trig.trigger_id,
                "trade_id": trade_id,
                "instrument": trig.instrument,
                "strike": strike,
                "option_type": trig.option_type,
                "entry_premium": executed_premium,
                "sl_price": sl_price,
                "target_price": target_price,
                "trigger_reason": trigger_reason,
                "timestamp": now_str,
            }

        except Exception as e:
            logger.error("Failed executing level trade for trigger %s: %s", trig.trigger_id, e)
            return None


def get_level_strategy_manager(root_dir: Optional[Path] = None) -> LevelStrategyManager:
    return LevelStrategyManager.get_instance(root_dir=root_dir)
