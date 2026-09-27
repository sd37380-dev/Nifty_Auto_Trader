"""
Position Monitoring Context Builder.

Synthesizes active Sensibull position telemetry, original trade entry thesis,
and new multi-timeframe market observations into position-aware BrainInput.
"""

from datetime import datetime, timezone
import logging
from typing import Any, Optional

from nifty_trader.brain.contracts import (
    BrainInput,
    Direction,
    OpenPositionContext,
)
from nifty_trader.contracts.models import UnifiedMarketObservation
from nifty_trader.paper.contracts import PaperPosition
from nifty_trader.paper.store import PaperTradeStore

logger = logging.getLogger(__name__)


class PositionMonitoringContextBuilder:
    """
    Constructs rich, position-aware BrainInput preserving the original trade thesis
    alongside live position telemetry and multi-timeframe perception.
    """

    def __init__(self, paper_store: PaperTradeStore):
        self.paper_store = paper_store

    def build_context(
        self,
        position: PaperPosition,
        observation: UnifiedMarketObservation,
        previous_brain_state: Optional[Any] = None,
        requested_focus: Optional[list] = None,
    ) -> BrainInput:
        """
        Builds position-aware BrainInput for position reassessment.
        """
        now = datetime.now(timezone.utc)
        duration_mins = max(0.0, (now - position.first_detected_at).total_seconds() / 60.0)

        # Direction determination
        direction = Direction.LONG if position.action.value == "BUY" else Direction.SHORT

        # Locate original trade order for thesis context preservation
        opening_thesis = None
        opening_hypothesis = None
        opening_time = position.first_detected_at

        recent_orders = self.paper_store.get_recent_orders(limit=20)
        matched_order = next((o for o in recent_orders if o.strike == position.strike and o.option_type == position.option_type), None)
        if matched_order:
            opening_thesis = matched_order.status_reason
            opening_time = matched_order.submitted_at

        open_ctx = OpenPositionContext(
            position_id=position.position_id,
            symbol=position.symbol,
            direction=direction,
            strike=position.strike,
            option_type=position.option_type.value,
            quantity=position.quantity,
            lots=position.lots,
            entry_price=position.avg_price,
            current_price=position.current_ltp,
            unrealized_pnl=position.unrealized_pnl,
            pnl_percentage=position.pnl_percentage,
            holding_duration_minutes=round(duration_mins, 1),
            opening_candidate_thesis=opening_thesis,
            opening_hypothesis=opening_hypothesis,
            opening_timestamp=opening_time,
            status=position.status.value,
        )

        focus_items = requested_focus or [
            f"Active open position {position.symbol} {position.strike} {position.option_type.value}",
            "Reassess original entry thesis against current 15M structure",
            "Determine if position should CONTINUE, WAIT, WATCH, MODIFY, or CLOSE",
        ]

        return BrainInput(
            observation=observation,
            task="POSITION_REASSESSMENT",
            open_position_context=open_ctx,
            previous_brain_state=previous_brain_state,
            requested_focus=focus_items,
            timestamp=now,
        )
