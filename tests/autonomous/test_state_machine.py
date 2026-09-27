"""
Unit tests for Package 5 Autonomous State Machine.
"""

import pytest

from nifty_trader.autonomous.contracts import AutonomousState
from nifty_trader.autonomous.state_machine import AutonomousStateMachine, StateTransitionRecord


def test_initial_state():
    sm = AutonomousStateMachine()
    assert sm.current_state == AutonomousState.IDLE


def test_standard_autonomous_cycle_transitions():
    sm = AutonomousStateMachine(AutonomousState.IDLE)

    # IDLE -> STARTING
    sm.transition_to(AutonomousState.STARTING, reason="Start session")
    assert sm.current_state == AutonomousState.STARTING

    # STARTING -> OBSERVING
    sm.transition_to(AutonomousState.OBSERVING, reason="Gather market data")
    assert sm.current_state == AutonomousState.OBSERVING

    # OBSERVING -> ANALYZING
    sm.transition_to(AutonomousState.ANALYZING, reason="Trading Brain reasoning")
    assert sm.current_state == AutonomousState.ANALYZING

    # ANALYZING -> WAITING
    sm.transition_to(AutonomousState.WAITING, reason="Wait for 15M confirmation")
    assert sm.current_state == AutonomousState.WAITING

    # WAITING -> OBSERVING (Re-observe after wake)
    sm.transition_to(AutonomousState.OBSERVING, reason="Wake event: Candle closed")
    assert sm.current_state == AutonomousState.OBSERVING


def test_candidate_ready_halts_autonomous_loop():
    sm = AutonomousStateMachine(AutonomousState.ANALYZING)
    sm.transition_to(AutonomousState.CANDIDATE_READY, reason="Trade thesis ready")
    assert sm.current_state == AutonomousState.CANDIDATE_READY

    # CANDIDATE_READY cannot directly observe again; can only stop or reset to IDLE
    assert not sm.can_transition_to(AutonomousState.OBSERVING)
    assert sm.can_transition_to(AutonomousState.STOPPED)

    sm.transition_to(AutonomousState.STOPPED, reason="Cycle concluded")
    assert sm.current_state == AutonomousState.STOPPED


def test_no_trade_distinction():
    sm = AutonomousStateMachine(AutonomousState.ANALYZING)
    sm.transition_to(AutonomousState.NO_TRADE, reason="No setup currently")
    assert sm.current_state == AutonomousState.NO_TRADE

    # NO_TRADE does not kill session; it can wait for next meaningful event
    assert sm.can_transition_to(AutonomousState.WAITING)
    sm.transition_to(AutonomousState.WAITING, reason="Wait for next candle")
    assert sm.current_state == AutonomousState.WAITING


def test_prohibited_transitions_raise_value_error():
    sm = AutonomousStateMachine(AutonomousState.IDLE)
    # Direct jump from IDLE to ANALYZING is forbidden
    with pytest.raises(ValueError, match="Illegal autonomous state transition"):
        sm.transition_to(AutonomousState.ANALYZING, reason="Invalid jump")

    sm.transition_to(AutonomousState.STARTING, reason="Valid start")
    # Direct jump from STARTING to CANDIDATE_READY is forbidden
    with pytest.raises(ValueError, match="Illegal autonomous state transition"):
        sm.transition_to(AutonomousState.CANDIDATE_READY, reason="Invalid candidate")


def test_self_transitions_allowed():
    sm = AutonomousStateMachine(AutonomousState.WAITING)
    rec = sm.transition_to(AutonomousState.WAITING, reason="Still waiting")
    assert sm.current_state == AutonomousState.WAITING
    assert "SELF_UPDATE" in rec.reason


def test_state_transition_listener():
    sm = AutonomousStateMachine(AutonomousState.IDLE)
    events = []

    def listener(record: StateTransitionRecord):
        events.append(record)

    sm.add_listener(listener)
    sm.transition_to(AutonomousState.STARTING, reason="Start")
    sm.transition_to(AutonomousState.OBSERVING, reason="Observe")

    assert len(events) == 2
    assert events[0].from_state == AutonomousState.IDLE
    assert events[0].to_state == AutonomousState.STARTING
    assert events[1].to_state == AutonomousState.OBSERVING
