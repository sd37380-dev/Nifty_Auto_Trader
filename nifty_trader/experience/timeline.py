"""
Chronological Timeline Builder for Completed Trade Lifecycle Reconstruction.

Reconstructs an immutable, auditable timeline from recorded evidence across:
- Stage 8 Order and Position events
- Stage 9 Monitoring cycles and position lifecycle transitions
- Stage 4/6 Brain reasoning events
- Stage 3/3.1 Market observations

STRICT INVARIANT:
- Only real, recorded timestamps are used.
- Missing events are never fabricated.
"""

from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional

from nifty_trader.experience.contracts import TimelineEvent, TradeTimeline
from nifty_trader.monitoring.contracts import PositionEvent, PositionMonitoringRecord
from nifty_trader.paper.contracts import PaperPosition, PaperTradeOrder

logger = logging.getLogger(__name__)


class TimelineBuilder:
    """
    Assembles a chronological timeline of verified events for a specific trade.
    """

    def build_timeline(
        self,
        order: Optional[PaperTradeOrder] = None,
        position: Optional[PaperPosition] = None,
        monitoring_records: Optional[List[PositionMonitoringRecord]] = None,
        monitoring_events: Optional[List[PositionEvent]] = None,
        custom_events: Optional[List[TimelineEvent]] = None,
        max_normal_gap_minutes: float = 60.0,
    ) -> TradeTimeline:
        """
        Builds a chronological TradeTimeline from multi-source inputs.
        """
        events: List[TimelineEvent] = []
        trade_id = (
            (order.order_id if order else None)
            or (getattr(position, "trade_id", None) if position else None)
            or (position.position_id if position else "unknown_trade")
        )

        # 1. Order submission & fill events (Stage 8)
        if order:
            events.append(TimelineEvent(
                timestamp=order.submitted_at,
                source="SENSIBULL_PAPER",
                event_type="ORDER_SUBMITTED",
                description=f"Paper order submitted: {order.action.value} {order.lots} Lot(s) NIFTY {order.strike} {order.option_type.value}",
                details={"order_id": order.order_id, "entry_price": order.entry_price, "idempotency_key": order.idempotency_key},
                evidence_refs=[order.order_id],
            ))
            if order.verified_at:
                events.append(TimelineEvent(
                    timestamp=order.verified_at,
                    source="SENSIBULL_PAPER",
                    event_type="ORDER_VERIFIED",
                    description=f"Order fill verified: entry price Rs. {order.entry_price or 0.0:.2f} (Status: {order.status.value})",
                    details={"status": order.status.value, "entry_price": order.entry_price},
                    evidence_refs=[order.order_id],
                ))

        # 2. Position detection event (Stage 8)
        if position:
            events.append(TimelineEvent(
                timestamp=position.first_detected_at,
                source="SENSIBULL_PAPER",
                event_type="POSITION_DETECTED",
                description=f"Position recognized in virtual portfolio: {position.symbol} {position.strike} {position.option_type.value}",
                details={"position_id": position.position_id, "avg_price": position.avg_price, "lots": position.lots},
                evidence_refs=[position.position_id],
            ))

        # 3. Position monitoring records (Stage 9)
        if monitoring_records:
            for rec in monitoring_records:
                desc = f"Monitoring cycle: State={rec.monitoring_state.value}"
                if rec.brain_position_action:
                    desc += f", Brain Action={rec.brain_position_action.value}"
                if rec.brain_summary:
                    desc += f" ({rec.brain_summary[:60]}...)"
                elif rec.wake_reason:
                    desc += f" ({rec.wake_reason[:60]}...)"

                events.append(TimelineEvent(
                    timestamp=rec.timestamp,
                    source="POSITION_MONITOR",
                    event_type=f"MONITOR_{rec.monitoring_state.value}",
                    description=desc,
                    details={
                        "monitoring_id": rec.monitoring_id,
                        "current_price": rec.current_price,
                        "unrealized_pnl": rec.unrealized_pnl,
                        "action": rec.brain_position_action.value if rec.brain_position_action else None,
                    },
                    evidence_refs=[rec.monitoring_id] + ([rec.brain_request_id] if rec.brain_request_id else []),
                ))

        # 4. Position monitoring lifecycle events (Stage 9)
        if monitoring_events:
            for evt in monitoring_events:
                events.append(TimelineEvent(
                    timestamp=evt.timestamp,
                    source="POSITION_EVENT",
                    event_type=evt.event_type.upper().replace("-", "_"),
                    description=f"Lifecycle event: {evt.event_type}",
                    details=evt.details,
                    evidence_refs=[evt.event_id],
                ))

        # 5. Position closure event (Stage 8)
        if position and position.closed_at:
            events.append(TimelineEvent(
                timestamp=position.closed_at,
                source="SENSIBULL_PAPER",
                event_type="POSITION_CLOSED",
                description=f"Position closed. Realized P&L: Rs. {position.realized_pnl:+,.2f} (Exit Price: Rs. {position.exit_price or 0.0:.2f})",
                details={"exit_price": position.exit_price, "realized_pnl": position.realized_pnl},
                evidence_refs=[position.position_id],
            ))

        # 6. Include any custom events
        if custom_events:
            events.extend(custom_events)

        # Sort chronologically
        events.sort(key=lambda e: e.timestamp)

        # Compute duration and check for gaps
        start_time = events[0].timestamp if events else None
        end_time = events[-1].timestamp if events else None
        duration_minutes = 0.0
        if start_time and end_time:
            duration_minutes = max(0.0, (end_time - start_time).total_seconds() / 60.0)

        has_gaps = False
        gap_descriptions: List[str] = []
        for i in range(len(events) - 1):
            delta_mins = (events[i + 1].timestamp - events[i].timestamp).total_seconds() / 60.0
            if delta_mins > max_normal_gap_minutes:
                has_gaps = True
                gap_descriptions.append(
                    f"Gap of {delta_mins:.1f} mins between {events[i].event_type} and {events[i + 1].event_type}"
                )

        return TradeTimeline(
            trade_id=trade_id,
            events=events,
            start_time=start_time,
            end_time=end_time,
            duration_minutes=round(duration_minutes, 1),
            has_gaps=has_gaps,
            gap_descriptions=gap_descriptions,
        )
