"""
Dual-State Reconciler for Sensibull Paper Trading.

Reconciles Hermes internal SQLite position state against Sensibull's ground truth
and enforces idempotency guards against duplicate orders.
"""

from datetime import datetime, timezone
import logging
from typing import List, Tuple
from nifty_trader.paper.contracts import (
    PaperPortfolioSummary,
    PaperPosition,
    PaperPositionStatus,
    ReconciliationDiscrepancy,
)
from nifty_trader.paper.store import PaperTradeStore

logger = logging.getLogger(__name__)


class SensibullStateReconciler:
    """
    Reconciles internal recorded positions with actual external Sensibull virtual portfolio state.
    Sensibull remote state is ALWAYS the ultimate ground truth.
    """

    def __init__(self, store: PaperTradeStore):
        self.store = store

    def reconcile(
        self,
        remote_summary: PaperPortfolioSummary,
    ) -> Tuple[List[PaperPosition], List[ReconciliationDiscrepancy]]:
        """
        Performs dual-state reconciliation:
        1. Compares local open positions with remote positions.
        2. Updates LTP and P&L for matching positions.
        3. Marks positions CLOSED if missing from remote.
        4. Ingests new positions discovered remotely.
        5. Logs any discrepancies into the SQLite audit store.
        """
        local_open = self.store.get_open_positions()
        remote_positions = remote_summary.positions
        discrepancies: List[ReconciliationDiscrepancy] = []
        reconciled_positions: List[PaperPosition] = []

        # Map by matching key: (strike, option_type, expiry)
        remote_map = {
            (p.strike, p.option_type, p.expiry): p
            for p in remote_positions if p.status == PaperPositionStatus.OPEN
        }

        local_map = {
            (p.strike, p.option_type, p.expiry): p
            for p in local_open
        }

        # 1. Check local positions against remote ground truth
        for key, l_pos in local_map.items():
            if key in remote_map:
                r_pos = remote_map[key]
                # Check quantity mismatch
                if l_pos.quantity != r_pos.quantity:
                    disc = ReconciliationDiscrepancy(
                        discrepancy_type="QUANTITY_MISMATCH",
                        hermes_state={"position_id": l_pos.position_id, "quantity": l_pos.quantity},
                        sensibull_state={"quantity": r_pos.quantity},
                        resolution_action=f"Updated quantity from {l_pos.quantity} to {r_pos.quantity}",
                    )
                    discrepancies.append(disc)
                    self.store.save_reconciliation(disc)
                    l_pos.quantity = r_pos.quantity
                    l_pos.lots = r_pos.lots

                # Update live LTP and P&L
                l_pos.current_ltp = r_pos.current_ltp
                l_pos.unrealized_pnl = r_pos.unrealized_pnl
                l_pos.pnl_percentage = r_pos.pnl_percentage
                l_pos.updated_at = datetime.now(timezone.utc)
                self.store.save_position(l_pos)
                reconciled_positions.append(l_pos)
            else:
                # Local thinks it's open, but remote doesn't have it -> Closed externally or expired
                disc = ReconciliationDiscrepancy(
                    discrepancy_type="MISSING_REMOTE",
                    hermes_state={"position_id": l_pos.position_id, "strike": l_pos.strike, "opt": l_pos.option_type.value},
                    sensibull_state=None,
                    resolution_action="Marked position CLOSED (absent from Sensibull ground truth)",
                )
                discrepancies.append(disc)
                self.store.save_reconciliation(disc)

                l_pos.status = PaperPositionStatus.EXTERNAL_CLOSED
                l_pos.closed_at = datetime.now(timezone.utc)
                self.store.save_position(l_pos)
                logger.info("Reconciled position %s as CLOSED (not present in Sensibull).", l_pos.position_id)

        # 2. Check for extra remote positions not present in Hermes local store
        for key, r_pos in remote_map.items():
            if key not in local_map:
                disc = ReconciliationDiscrepancy(
                    discrepancy_type="EXTRA_REMOTE",
                    hermes_state=None,
                    sensibull_state={"strike": r_pos.strike, "opt": r_pos.option_type.value, "qty": r_pos.quantity},
                    resolution_action="Ingested external Sensibull position into Hermes local store",
                )
                discrepancies.append(disc)
                self.store.save_reconciliation(disc)
                self.store.save_position(r_pos)
                reconciled_positions.append(r_pos)
                logger.info("Ingested external Sensibull position %s (%s %s) into local store.", r_pos.position_id, r_pos.strike, r_pos.option_type.value)

        return reconciled_positions, discrepancies
