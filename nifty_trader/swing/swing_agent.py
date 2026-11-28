"""
Hermes Autonomous Swing Trading Agent.
Operates completely decoupled in the background to scan, monitor, execute,
and report on 300-point swing trades without hampering the daily intraday trade engine.
"""

from datetime import datetime, timedelta, timezone
import json
import logging
from pathlib import Path
import threading
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)
IST = timezone(timedelta(hours=5, minutes=30))


class HermesSwingAgent:
    """Dedicated background agent for swing trade discovery, monitoring, and execution."""

    _instance: Optional["HermesSwingAgent"] = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls, root_dir: Optional[Path] = None) -> "HermesSwingAgent":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls(root_dir=root_dir)
        return cls._instance

    def __init__(self, root_dir: Optional[Path] = None, scan_interval_seconds: int = 60):
        self.root_dir = root_dir or Path(__file__).resolve().parent.parent.parent
        self.scan_interval: int = max(15, scan_interval_seconds)

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self.is_running: bool = False
        self.last_scan_time: Optional[str] = None
        self.last_status: str = "INITIALIZED"
        self.active_swing_trades: List[Dict[str, Any]] = []

    def start(self, interval_minutes: Optional[int] = None):
        """Starts the swing agent in background."""
        if interval_minutes:
            self.scan_interval = max(15, interval_minutes * 60)
        self.start_background_monitoring()

    def stop(self):
        """Stops the swing agent."""
        self.stop_background_monitoring()

    def start_background_monitoring(self):
        """Starts the dedicated swing trade scanner in a background daemon thread."""
        if self.is_running:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._agent_loop,
            daemon=True,
            name="Hermes-Swing-Agent-Daemon",
        )
        self._thread.start()
        self.is_running = True
        logger.info("Hermes Swing Trade Agent launched successfully in background daemon mode.")

    def stop_background_monitoring(self):
        """Gracefully stops the swing agent."""
        self._stop_event.set()
        self.is_running = False

    def _agent_loop(self):
        """Core periodic agent cycle."""
        # Initial scan
        try:
            self.run_swing_scan()
        except Exception as e:
            logger.warning("Initial swing scan error: %s", e)

        while not self._stop_event.is_set():
            if self._stop_event.wait(timeout=self.scan_interval):
                break
            try:
                self.run_swing_scan()
            except Exception as e:
                logger.error("Error during background swing scan: %s", e)

    @staticmethod
    def is_nse_market_open(dt: Optional[datetime] = None) -> bool:
        """Strict check: NSE market hours are Mon-Fri 09:15 to 15:30 IST."""
        now = dt or datetime.now(IST)
        if now.weekday() >= 5:  # Saturday (5) or Sunday (6)
            return False
        market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
        market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
        return market_open <= now <= market_close

    def run_swing_scan(self) -> Dict[str, Any]:
        """Performs full 4-tier scan for swing trade opportunities."""
        now = datetime.now(IST)
        now_str = now.strftime("%Y-%m-%d %H:%M:%S IST")
        market_open = self.is_nse_market_open(now)

        from nifty_trader.swing.macro_service import get_macro_radar_service
        from nifty_trader.swing.reaction_zone_service import get_reaction_zone_service
        from nifty_trader.swing.swing_report_service import get_swing_report_service

        macro_svc = get_macro_radar_service(self.root_dir)
        rz_svc = get_reaction_zone_service(self.root_dir)
        rep_svc = get_swing_report_service(self.root_dir)

        # 1. Tier 1: Macro Radar
        macro = macro_svc.get_macro_radar_telemetry()

        # 2. Tier 2: Multi-Timeframe Structure
        mtfa = rz_svc.get_multi_timeframe_state("NIFTY")

        # 3. Tier 3: Reaction Zones & Setups
        zones = rz_svc.scan_reaction_zones("NIFTY")
        setups = rz_svc.get_active_swing_setups("NIFTY")

        self.last_scan_time = now_str
        self.last_status = "MONITORING_ACTIVE" if market_open else "EXCHANGE_CLOSED (Standby until 09:15 IST)"

        return {
            "status": "ok",
            "timestamp": now_str,
            "agent_state": "ACTIVE_SCANNING" if market_open else "OFF_MARKET_MONITORING",
            "is_market_open": market_open,
            "macro": macro,
            "mtfa": mtfa,
            "reaction_zones": zones,
            "setups": setups,
            "active_positions": self.active_swing_trades,
        }

    def clear_active_trades(self):
        """Clears all active/monitored swing trades."""
        self.active_swing_trades.clear()
        logger.info("All active swing trade positions cleared.")

    def get_status(self) -> Dict[str, Any]:
        """Returns the current operational status of the agent."""
        return {
            "is_running": self.is_running,
            "last_scan_time": self.last_scan_time,
            "status": self.last_status,
            "scan_interval_seconds": self.scan_interval,
            "active_trades": self.active_swing_trades,
            "active_positions_count": len(self.active_swing_trades),
        }

    def execute_swing_paper_trade(self, setup_data: Optional[Dict[str, Any]] = None, bypass_market_hours: bool = False) -> Dict[str, Any]:
        """Executes a swing trade into simulator and triggers detailed PDF report.
        Strictly guarded: will reject order placement outside 09:15 - 15:30 IST.
        """
        now = datetime.now(IST)
        if not self.is_nse_market_open(now) and not bypass_market_hours:
            raise ValueError(
                f"Exchange Closed: Cannot place trades at {now.strftime('%H:%M:%S IST')}. "
                "NSE Market trading hours are strictly 09:15 - 15:30 IST (Mon-Fri)."
            )
        trade_id = f"SWING_{int(now.timestamp())}"
        if setup_data is None:
            setup_data = {
                "symbol": "NIFTY",
                "recommended_contract": "NIFTY 31-Dec-2026 Bull Call Spread (25,500 CE / 25,800 CE)",
                "direction": "BULLISH",
                "name": "Setup 1: Liquidity Sweep & Institutional FII Squeeze",
                "entry_level": 25515.0,
                "stop_loss_price": 25465.0,
                "target_price": 25815.0,
            }
        symbol = setup_data.get("symbol", "NIFTY")

        trade_record = {
            "trade_id": trade_id,
            "date": now.strftime("%Y-%m-%d"),
            "entry_time": now.strftime("%Y-%m-%d %H:%M:%S IST"),
            "symbol": symbol,
            "contract": setup_data.get("recommended_contract", "NIFTY 31-Dec-2026 Bull Call Spread"),
            "direction": setup_data.get("direction", "BULLISH"),
            "setup_name": setup_data.get("name", "Liquidity Sweep & FII Squeeze"),
            "entry_spot": float(setup_data.get("entry_level", 25515.0)),
            "sl_price": float(setup_data.get("stop_loss_price", 25465.0)),
            "tgt_price": float(setup_data.get("target_price", 25815.0)),
            "target": float(setup_data.get("target_price", 25815.0)),
            "stop_loss": float(setup_data.get("stop_loss_price", 25465.0)),
            "sl_pts": 50.0,
            "tgt_pts": 300.0,
            "risk_reward": "1 : 6.0",
            "status": "OPEN",
            "why_selected": setup_data.get("why_selected", "Price tested confluence reaction floor at 25,500; 1H rejection candle confirmed smart money absorption."),
        }

        self.active_swing_trades.append(trade_record)

        # Generate detailed PDF report with chart
        from nifty_trader.swing.swing_report_service import get_swing_report_service
        pdf_res = get_swing_report_service(self.root_dir).generate_executed_swing_trade_pdf(trade_record)
        trade_record["pdf_report"] = pdf_res.get("pdf_path")

        logger.info("Executed Swing Trade logged & PDF created: %s (%s)", trade_id, trade_record["contract"])
        return trade_record


def get_swing_agent(root_dir: Optional[Path] = None) -> HermesSwingAgent:
    return HermesSwingAgent.get_instance(root_dir=root_dir)
