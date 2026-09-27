"""
High-Level Facade: Sensibull Paper Trading Service.

Provides complete paper trading lifecycle operations, position monitoring,
dual-state reconciliation, and telemetry feeds for Hermes.
"""

from datetime import datetime, timezone
import logging
from typing import List, Optional, Tuple
from nifty_trader.browser.browser_agent import BrowserAgent
from nifty_trader.paper.contracts import (
    PaperPortfolioSummary,
    PaperPosition,
    PaperPositionObservation,
    PaperPositionStatus,
    PaperTradeOrder,
    PaperTradeOrderRequest,
    ReconciliationDiscrepancy,
    SensibullEnvironmentType,
)
from nifty_trader.paper.environment import SensibullEnvironmentDetector
from nifty_trader.paper.executor import SensibullPaperExecutor
from nifty_trader.paper.navigator import SensibullPaperNavigator
from nifty_trader.paper.position_reader import SensibullPositionReader
from nifty_trader.paper.reconciler import SensibullStateReconciler
from nifty_trader.paper.store import PaperTradeStore

logger = logging.getLogger(__name__)


class SensibullPaperTradingService:
    """
    Unified service facade for Sensibull Virtual Portfolio paper trading.
    Connects Hermes to safe virtual execution, position tracking, and reconciliation.
    """

    def __init__(
        self,
        browser_agent: BrowserAgent,
        store: Optional[PaperTradeStore] = None,
        detector: Optional[SensibullEnvironmentDetector] = None,
        navigator: Optional[SensibullPaperNavigator] = None,
        position_reader: Optional[SensibullPositionReader] = None,
        executor: Optional[SensibullPaperExecutor] = None,
        reconciler: Optional[SensibullStateReconciler] = None,
    ):
        self.browser = browser_agent
        self.store = store or PaperTradeStore()
        self.detector = detector or SensibullEnvironmentDetector()
        self.navigator = navigator or SensibullPaperNavigator(browser_agent, self.detector)
        self.position_reader = position_reader or SensibullPositionReader()
        self.executor = executor or SensibullPaperExecutor(
            browser_agent, self.store, self.navigator, self.position_reader
        )
        self.reconciler = reconciler or SensibullStateReconciler(self.store)

    async def get_portfolio_status(self) -> PaperPortfolioSummary:
        """
        Navigates to Sensibull Virtual Portfolio, reads positions, and reconciles state.
        """
        obs, env_type, is_safe = await self.navigator.navigate_to_virtual_portfolio(capture_screen=True)

        summary = self.position_reader.parse_portfolio(
            visible_text=obs.visible_text,
            environment=env_type,
        )

        # Reconcile with local SQLite store if environment is safe
        if is_safe:
            reconciled_positions, _ = self.reconciler.reconcile(summary)
            summary.positions = reconciled_positions
            summary.total_positions = len(reconciled_positions)
            summary.open_positions_count = sum(1 for p in reconciled_positions if p.status == PaperPositionStatus.OPEN)

        return summary

    async def execute_trade(self, request: PaperTradeOrderRequest) -> PaperTradeOrder:
        """
        Executes a paper order after safety checks and idempotency verification.
        """
        return await self.executor.execute_paper_order(request)

    async def close_position(self, position_id: str, reason: str = "Operator square-off") -> Tuple[bool, Optional[PaperPosition]]:
        """
        Squares off a specific open paper position.
        """
        return await self.executor.close_paper_position(position_id, reason=reason)

    async def close_all_positions(self, reason: str = "Emergency square-off") -> List[PaperPosition]:
        """
        Squares off all currently open paper positions.
        """
        open_positions = self.store.get_open_positions()
        closed_positions = []
        for pos in open_positions:
            success, closed_pos = await self.close_position(pos.position_id, reason=reason)
            if success and closed_pos:
                closed_positions.append(closed_pos)
        return closed_positions

    async def sync_and_reconcile(self) -> Tuple[PaperPortfolioSummary, List[ReconciliationDiscrepancy]]:
        """
        Full synchronization and dual-state reconciliation cycle.
        """
        obs, env_type, is_safe = await self.navigator.navigate_to_virtual_portfolio(capture_screen=True)
        summary = self.position_reader.parse_portfolio(
            visible_text=obs.visible_text,
            environment=env_type,
        )

        discrepancies: List[ReconciliationDiscrepancy] = []
        if is_safe:
            reconciled, discrepancies = self.reconciler.reconcile(summary)
            summary.positions = reconciled

        return summary, discrepancies

    async def get_paper_observation(self) -> PaperPositionObservation:
        """
        Generates telemetry representation to feed into Hermes World State and AI Brain context.
        """
        open_positions = self.store.get_open_positions()
        unrealized = sum(p.unrealized_pnl for p in open_positions)
        realized = sum(p.realized_pnl for p in open_positions)
        net_lots = sum(p.lots for p in open_positions)

        return PaperPositionObservation(
            environment=SensibullEnvironmentType.VIRTUAL_TRADE,
            has_open_position=len(open_positions) > 0,
            open_positions=open_positions,
            unrealized_pnl=round(unrealized, 2),
            realized_pnl=round(realized, 2),
            net_exposure_lots=net_lots,
            observed_at=datetime.now(timezone.utc),
        )
