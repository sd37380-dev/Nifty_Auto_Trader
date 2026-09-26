"""
Market Perception Event Bus.

Dispatches market perception events (CANDLE_CLOSED, MARKET_OPENED, DATA_UPDATED, DATA_MISMATCH)
to subscribers and maintains an audit log of recent market events.
"""

import asyncio
from datetime import datetime, timezone
import logging
from typing import Any, Callable, Dict, List, Optional
import uuid

from nifty_trader.market_data.models import (
    ObservationEvent,
    ObservationEventType,
    Timeframe,
)

logger = logging.getLogger(__name__)


class EventBus:
    """
    Asynchronous in-memory event dispatcher for market perception events.
    """

    def __init__(self, max_history: int = 100):
        self._subscribers: Dict[ObservationEventType, List[Callable[[ObservationEvent], Any]]] = {
            t: [] for t in ObservationEventType
        }
        self._history: List[ObservationEvent] = []
        self.max_history = max_history

    def subscribe(self, event_type: ObservationEventType, handler: Callable[[ObservationEvent], Any]) -> None:
        """Subscribes an async or sync callback to a specific event type."""
        self._subscribers[event_type].append(handler)

    async def emit(
        self,
        event_type: ObservationEventType,
        symbol: str = "NIFTY",
        timeframe: Optional[Timeframe] = None,
        data: Optional[Dict] = None,
        message: str = "",
    ) -> ObservationEvent:
        """Constructs and dispatches an ObservationEvent."""
        event = ObservationEvent(
            event_id=str(uuid.uuid4())[:8],
            event_type=event_type,
            timestamp=datetime.now(timezone.utc),
            symbol=symbol,
            timeframe=timeframe,
            data=data or {},
            message=message,
        )

        self._history.append(event)
        if len(self._history) > self.max_history:
            self._history.pop(0)

        logger.info("[EVENT] %s: %s (Timeframe: %s)", event.event_type.value, message, timeframe.value if timeframe else "N/A")

        # Notify subscribers
        for handler in self._subscribers.get(event_type, []):
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(event)
                else:
                    handler(event)
            except Exception as e:
                logger.error("Error in event subscriber handler for %s: %s", event_type.value, e)

        return event

    def get_history(self, limit: int = 50, event_type: Optional[ObservationEventType] = None) -> List[ObservationEvent]:
        """Returns recent events, optionally filtered by type."""
        if event_type:
            events = [e for e in self._history if e.event_type == event_type]
        else:
            events = self._history
        return events[-limit:]
