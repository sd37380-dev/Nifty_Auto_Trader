"""
Package 5: Autonomous State Machine.

Maintains the strict lifecycle state of the autonomous observation engine,
validates transitions according to the state transition graph, and maintains
an auditable transition history.
"""

from datetime import datetime, timezone
import logging
from typing import Callable, Dict, List, Optional, Set
import uuid
from pydantic import BaseModel, Field

from nifty_trader.autonomous.contracts import AutonomousState

logger = logging.getLogger(__name__)


class StateTransitionRecord(BaseModel):
    """Immutable audit record for an autonomous state transition."""
    transition_id: str = Field(default_factory=lambda: f"trans_{uuid.uuid4().hex[:8]}")
    from_state: AutonomousState
    to_state: AutonomousState
    reason: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    session_id: Optional[str] = None
    cycle_id: Optional[str] = None


class AutonomousStateMachine:
    """
    State machine enforcing valid state transitions for the autonomous trading engine.
    """

    # Directed transition graph
    VALID_TRANSITIONS: Dict[AutonomousState, Set[AutonomousState]] = {
        AutonomousState.IDLE: {
            AutonomousState.STARTING,
            AutonomousState.OBSERVING,
            AutonomousState.STOPPED,
        },
        AutonomousState.STARTING: {
            AutonomousState.OBSERVING,
            AutonomousState.WAITING,
            AutonomousState.SESSION_PAUSED,
            AutonomousState.SESSION_ENDED,
            AutonomousState.ERROR,
            AutonomousState.STOPPED,
        },
        AutonomousState.OBSERVING: {
            AutonomousState.ANALYZING,
            AutonomousState.WAITING,
            AutonomousState.SESSION_PAUSED,
            AutonomousState.SESSION_ENDED,
            AutonomousState.ERROR,
            AutonomousState.STOPPED,
        },
        AutonomousState.ANALYZING: {
            AutonomousState.WAITING,
            AutonomousState.WATCHING,
            AutonomousState.REOBSERVE_REQUESTED,
            AutonomousState.CANDIDATE_READY,
            AutonomousState.NO_TRADE,
            AutonomousState.ERROR,
            AutonomousState.STOPPED,
        },
        AutonomousState.WAITING: {
            AutonomousState.OBSERVING,
            AutonomousState.SESSION_PAUSED,
            AutonomousState.SESSION_ENDED,
            AutonomousState.ERROR,
            AutonomousState.STOPPED,
        },
        AutonomousState.WATCHING: {
            AutonomousState.OBSERVING,
            AutonomousState.WAITING,
            AutonomousState.SESSION_PAUSED,
            AutonomousState.SESSION_ENDED,
            AutonomousState.ERROR,
            AutonomousState.STOPPED,
        },
        AutonomousState.REOBSERVE_REQUESTED: {
            AutonomousState.OBSERVING,
            AutonomousState.WAITING,
            AutonomousState.ERROR,
            AutonomousState.STOPPED,
        },
        AutonomousState.CANDIDATE_READY: {
            AutonomousState.STOPPED,
            AutonomousState.IDLE,
        },
        AutonomousState.NO_TRADE: {
            AutonomousState.WAITING,
            AutonomousState.OBSERVING,
            AutonomousState.SESSION_ENDED,
            AutonomousState.STOPPED,
        },
        AutonomousState.SESSION_PAUSED: {
            AutonomousState.STARTING,
            AutonomousState.WAITING,
            AutonomousState.OBSERVING,
            AutonomousState.SESSION_ENDED,
            AutonomousState.STOPPED,
        },
        AutonomousState.SESSION_ENDED: {
            AutonomousState.IDLE,
            AutonomousState.STARTING,
            AutonomousState.STOPPED,
        },
        AutonomousState.ERROR: {
            AutonomousState.WAITING,
            AutonomousState.OBSERVING,
            AutonomousState.IDLE,
            AutonomousState.STOPPED,
        },
        AutonomousState.STOPPED: {
            AutonomousState.IDLE,
            AutonomousState.STARTING,
        },
    }

    def __init__(self, initial_state: AutonomousState = AutonomousState.IDLE):
        self._current_state = initial_state
        self._history: List[StateTransitionRecord] = []
        self._listeners: List[Callable[[StateTransitionRecord], None]] = []

    @property
    def current_state(self) -> AutonomousState:
        return self._current_state

    def can_transition_to(self, target_state: AutonomousState) -> bool:
        """Checks if a transition from current_state to target_state is permitted."""
        allowed = self.VALID_TRANSITIONS.get(self._current_state, set())
        return target_state in allowed

    def transition_to(
        self,
        target_state: AutonomousState,
        reason: str,
        session_id: Optional[str] = None,
        cycle_id: Optional[str] = None,
    ) -> StateTransitionRecord:
        """
        Executes a validated state transition. Raises ValueError if illegal.
        """
        if target_state == self._current_state:
            # Self-transitions allowed for continuous status updates
            record = StateTransitionRecord(
                from_state=self._current_state,
                to_state=target_state,
                reason=f"SELF_UPDATE: {reason}",
                session_id=session_id,
                cycle_id=cycle_id,
            )
            self._history.append(record)
            return record

        if not self.can_transition_to(target_state):
            err_msg = (
                f"Illegal autonomous state transition: Cannot transition from "
                f"'{self._current_state.value}' to '{target_state.value}'. Reason given: '{reason}'"
            )
            logger.error(err_msg)
            raise ValueError(err_msg)

        prev = self._current_state
        self._current_state = target_state

        record = StateTransitionRecord(
            from_state=prev,
            to_state=target_state,
            reason=reason,
            session_id=session_id,
            cycle_id=cycle_id,
        )
        self._history.append(record)
        logger.info(
            "[STATE] %s -> %s | Reason: %s",
            prev.value,
            target_state.value,
            reason,
        )

        for listener in self._listeners:
            try:
                listener(record)
            except Exception as e:
                logger.error("Error in state transition listener: %s", e)

        return record

    def add_listener(self, listener: Callable[[StateTransitionRecord], None]) -> None:
        """Adds a listener callback invoked upon each valid state transition."""
        self._listeners.append(listener)

    def get_history(self, limit: int = 50) -> List[StateTransitionRecord]:
        """Returns recent state transition history."""
        return self._history[-limit:]
