"""
Dual Autonomous Hermes Modes Orchestrator.

Coordinates Mode A (EXISTING_SYSTEM) and Mode B (HERMES_RESEARCH) concurrently:
- Independent lifecycle execution
- Complete fault isolation (failure in one mode NEVER terminates the other)
- Non-interfering browser / model router queuing
- Multi-mode status reporting and graceful shutdown
"""

import asyncio
from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional

from nifty_trader.autonomous.mode_a_trader import ExistingSystemTrader
from nifty_trader.core.modes import TradingMode
from nifty_trader.core.trade_store import TradeAuditStore
from nifty_trader.research_zone.trader import HermesResearchTrader

logger = logging.getLogger(__name__)


class DualAutonomousOrchestrator:
    """
    Master orchestrator running Mode A and Mode B concurrently with complete failure isolation.
    """

    def __init__(
        self,
        mode_a_trader: Optional[ExistingSystemTrader] = None,
        mode_b_trader: Optional[HermesResearchTrader] = None,
        audit_store: Optional[TradeAuditStore] = None,
    ):
        self.mode_a_trader = mode_a_trader
        self.mode_b_trader = mode_b_trader
        self.audit_store = audit_store or TradeAuditStore()

        self._active_mode: str = "dual"
        self._is_running: bool = False
        self._stop_event = asyncio.Event()

        self._task_a: Optional[asyncio.Task] = None
        self._task_b: Optional[asyncio.Task] = None

    @property
    def is_running(self) -> bool:
        return self._is_running

    async def _safe_run_mode_a(self, symbol: str) -> None:
        """Runs Mode A with continuous failure isolation."""
        if not self.mode_a_trader:
            logger.warning("[ORCHESTRATOR] Mode A trader not configured; skipping.")
            return

        logger.info("[ORCHESTRATOR] Mode A (EXISTING_SYSTEM) runner active.")
        while not self._stop_event.is_set():
            try:
                await self.mode_a_trader.run_loop(symbol=symbol)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.critical(
                    "[FAULT ISOLATION] Uncaught exception in Mode A (EXISTING_SYSTEM): %s. Mode B remains unaffected.",
                    e,
                    exc_info=True,
                )
                await asyncio.sleep(5.0)

    async def _safe_run_mode_b(self, symbol: str) -> None:
        """Runs Mode B with continuous failure isolation."""
        if not self.mode_b_trader:
            logger.warning("[ORCHESTRATOR] Mode B trader not configured; skipping.")
            return

        logger.info("[ORCHESTRATOR] Mode B (HERMES_RESEARCH) runner active.")
        while not self._stop_event.is_set():
            try:
                await self.mode_b_trader.run_loop(symbol=symbol)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.critical(
                    "[FAULT ISOLATION] Uncaught exception in Mode B (HERMES_RESEARCH): %s. Mode A remains unaffected.",
                    e,
                    exc_info=True,
                )
                await asyncio.sleep(5.0)

    async def start(
        self,
        mode: str = "dual",
        symbol: str = "NIFTY",
    ) -> None:
        """
        Starts autonomous trading for the requested mode:
        - "dual": Runs both Mode A and Mode B concurrently.
        - "existing": Runs Mode A only.
        - "research": Runs Mode B only.
        """
        clean_mode = str(mode).strip().lower()
        if clean_mode not in ["dual", "existing", "research"]:
            raise ValueError(f"Invalid mode '{mode}'. Supported modes: dual, existing, research.")

        self._active_mode = clean_mode
        self._is_running = True
        self._stop_event.clear()

        logger.info("[ORCHESTRATOR] Launching Autonomous Trading in [%s] mode for %s...", clean_mode.upper(), symbol)

        tasks = []
        if clean_mode in ["dual", "existing"]:
            self._task_a = asyncio.create_task(self._safe_run_mode_a(symbol), name="mode_a_runner")
            tasks.append(self._task_a)

        if clean_mode in ["dual", "research"]:
            self._task_b = asyncio.create_task(self._safe_run_mode_b(symbol), name="mode_b_runner")
            tasks.append(self._task_b)

        try:
            await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            self._is_running = False

    def stop(self) -> None:
        """Signals both modes to stop immediately and cancels background tasks."""
        logger.info("[ORCHESTRATOR] Stop signal received. Shutting down all autonomous modes safely...")
        self._stop_event.set()

        if self.mode_a_trader:
            self.mode_a_trader.stop()
        if self.mode_b_trader:
            self.mode_b_trader.stop()

        if self._task_a and not self._task_a.done():
            self._task_a.cancel()
        if self._task_b and not self._task_b.done():
            self._task_b.cancel()

        self._is_running = False

    def get_status(self) -> Dict[str, Any]:
        """Provides real-time telemetry on both autonomous modes."""
        mode_a_trades = self.audit_store.get_trades_by_mode(TradingMode.EXISTING_SYSTEM)
        mode_b_trades = self.audit_store.get_trades_by_mode(TradingMode.HERMES_RESEARCH)

        return {
            "orchestrator_running": self._is_running,
            "active_mode": self._active_mode,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "mode_a_existing_system": {
                "active": self._task_a is not None and not self._task_a.done(),
                "trades_count": len(mode_a_trades),
                "open_trades": len([t for t in mode_a_trades if t.execution_status == "OPEN"]),
                "realized_pnl": sum(t.pnl for t in mode_a_trades if t.execution_status == "CLOSED"),
            },
            "mode_b_hermes_research": {
                "active": self._task_b is not None and not self._task_b.done(),
                "trades_count": len(mode_b_trades),
                "open_trades": len([t for t in mode_b_trades if t.execution_status == "OPEN"]),
                "realized_pnl": sum(t.pnl for t in mode_b_trades if t.execution_status == "CLOSED"),
            },
        }
