"""
Package 5: Autonomous Event Scheduler.

Orchestrates asynchronous sleep and event-driven wake triggers without busy polling.
Supports deterministic clock injection for automated unit testing and real-time execution.
"""

import asyncio
from datetime import datetime, timezone
import logging
from typing import Optional

from nifty_trader.autonomous.contracts import WakeConditionType

logger = logging.getLogger(__name__)


class IClock:
    """Protocol for time reference."""
    def now(self) -> datetime:
        raise NotImplementedError


class RealClock(IClock):
    """Standard system wall clock in UTC."""
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class FakeClock(IClock):
    """Deterministic simulated clock for tests."""
    def __init__(self, initial_time: Optional[datetime] = None):
        self._current_time = initial_time or datetime(2026, 9, 27, 9, 15, 0, tzinfo=timezone.utc)

    def now(self) -> datetime:
        return self._current_time

    def advance(self, seconds: float) -> None:
        from datetime import timedelta
        self._current_time += timedelta(seconds=seconds)

    def set_time(self, dt: datetime) -> None:
        self._current_time = dt


class AutonomousScheduler:
    """
    Event-driven scheduler that pauses the autonomous engine until a scheduled wake
    timestamp arrives or an event (e.g. manual wake, user stop, new instruction) fires.
    """

    def __init__(self, clock: Optional[IClock] = None):
        self.clock = clock or RealClock()
        self._wake_event = asyncio.Event()
        self._stop_event = asyncio.Event()
        self._pause_event = asyncio.Event()

    def request_wake(self, reason: str = "MANUAL_COMMAND") -> None:
        """Triggers an immediate wake of any waiting cycle."""
        logger.info("[SCHEDULER] Immediate wake requested: %s", reason)
        self._wake_event.set()

    def request_stop(self) -> None:
        """Signals the scheduler to abort waiting and stop."""
        logger.info("[SCHEDULER] Stop requested.")
        self._stop_event.set()
        self._wake_event.set()

    def request_pause(self) -> None:
        """Signals the scheduler to pause."""
        logger.info("[SCHEDULER] Pause requested.")
        self._pause_event.set()
        self._wake_event.set()

    def reset_events(self) -> None:
        """Resets synchronization events."""
        self._wake_event.clear()
        self._stop_event.clear()
        self._pause_event.clear()

    async def wait_until(
        self,
        wake_at: datetime,
        max_wait_seconds: Optional[float] = None,
    ) -> WakeConditionType:
        """
        Suspends execution until wake_at is reached or an asynchronous event occurs.
        In FakeClock mode (tests), returns immediately if current_time >= wake_at.
        """
        now = self.clock.now()

        # Immediate return if wake time is in the past
        if now >= wake_at:
            return WakeConditionType.TIME

        wait_seconds = (wake_at - now).total_seconds()
        if max_wait_seconds is not None:
            wait_seconds = min(wait_seconds, max_wait_seconds)

        # For FakeClock in unit tests, don't sleep real time
        if isinstance(self.clock, FakeClock):
            if self._stop_event.is_set():
                return WakeConditionType.USER_COMMAND
            if self._wake_event.is_set():
                self._wake_event.clear()
                return WakeConditionType.USER_COMMAND
            return WakeConditionType.CANDLE_COMPLETION

        # Real async sleep with event-driven interruption
        try:
            await asyncio.wait_for(self._wake_event.wait(), timeout=max(0.1, wait_seconds))
            # If we reached here, an event was set
            if self._stop_event.is_set():
                return WakeConditionType.USER_COMMAND
            if self._pause_event.is_set():
                return WakeConditionType.SESSION_EVENT
            self._wake_event.clear()
            return WakeConditionType.USER_COMMAND
        except asyncio.TimeoutError:
            # Normal timeout: scheduled wake time has arrived
            return WakeConditionType.CANDLE_COMPLETION
