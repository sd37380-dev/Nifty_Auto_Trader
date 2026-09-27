"""
Execution Analyzer: Evaluates Platform Interaction Fidelity and Execution Quality.

Separates execution quality (slippage, latency, visual verification, environment safety)
from market outcome and strategy decisions.
"""

from datetime import datetime
import logging
from typing import List, Optional

from nifty_trader.experience.contracts import (
    ExecutionAnalysis,
    ExecutionOutcomeCategory,
)
from nifty_trader.paper.contracts import (
    PaperOrderStatus,
    PaperPosition,
    PaperTradeOrder,
    ReconciliationDiscrepancy,
    SensibullEnvironmentType,
)

logger = logging.getLogger(__name__)


class ExecutionAnalyzer:
    """
    Evaluates order execution fidelity, slippage, and operational integrity.
    """

    def analyze_execution(
        self,
        order: Optional[PaperTradeOrder] = None,
        position: Optional[PaperPosition] = None,
        discrepancies: Optional[List[ReconciliationDiscrepancy]] = None,
        requested_entry_price: Optional[float] = None,
    ) -> ExecutionAnalysis:
        """
        Conducts independent execution analysis.
        """
        entry_req = requested_entry_price or getattr(order, "limit_price", None) or (order.entry_price if order else None)
        entry_exec = (order.entry_price if order and order.entry_price is not None else None) or (position.avg_price if position else None)
        entry_slippage = (entry_exec - entry_req) if (entry_req and entry_exec) else 0.0

        exit_req = None
        exit_exec = position.exit_price if position else None
        exit_slippage = 0.0

        order_duration = 0.0
        if order and order.submitted_at and order.verified_at:
            order_duration = max(0.0, (order.verified_at - order.submitted_at).total_seconds())

        idemp_verified = bool(order and order.idempotency_key)
        visual_confirmed = bool(order and (order.post_execution_screenshot or order.verified_at))

        disc_strs = [f"{d.discrepancy_type}: {d.resolution_action}" for d in (discrepancies or [])]

        # Determine Execution Outcome Category
        if order and order.status in [PaperOrderStatus.FILLED, PaperOrderStatus.OPEN]:
            exec_outcome = ExecutionOutcomeCategory.EXECUTION_CONFIRMED
            notes = "Order filled and verified cleanly against Sensibull virtual portfolio."
        elif order and order.status == PaperOrderStatus.REJECTED:
            exec_outcome = ExecutionOutcomeCategory.EXECUTION_FAILED
            notes = f"Order rejected by broker/platform: {order.status_reason or 'No reason provided'}"
        elif order and order.status == PaperOrderStatus.FAILED:
            exec_outcome = ExecutionOutcomeCategory.EXECUTION_FAILED
            notes = f"Execution failed: {order.status_reason or 'Platform failure'}"
        elif position and position.status.value in ["OPEN", "CLOSED"]:
            exec_outcome = ExecutionOutcomeCategory.EXECUTION_CONFIRMED
            notes = "Position established and verified."
        else:
            exec_outcome = ExecutionOutcomeCategory.EXECUTION_UNKNOWN
            notes = "Insufficient execution evidence recorded."

        return ExecutionAnalysis(
            execution_outcome=exec_outcome,
            entry_requested_price=entry_req,
            entry_executed_price=entry_exec,
            entry_slippage=round(entry_slippage, 2),
            exit_requested_price=exit_req,
            exit_executed_price=exit_exec,
            exit_slippage=round(exit_slippage, 2),
            order_duration_seconds=round(order_duration, 1),
            idempotency_verified=idemp_verified,
            visual_confirmation=visual_confirmed,
            sensibull_environment=SensibullEnvironmentType.VIRTUAL_TRADE.value,
            reconciliation_discrepancies=disc_strs,
            notes=notes,
        )
