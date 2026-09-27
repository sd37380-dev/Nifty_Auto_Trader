"""
Package 5: Autonomous Observation & Waiting Engine.

Autonomous temporal-control layer for NIFTY Autonomous Trader.
"""

from nifty_trader.autonomous.change_detector import ChangeDetectionConfig, MeaningfulChangeDetector
from nifty_trader.autonomous.contracts import (
    AutonomousCycle,
    AutonomousLimits,
    AutonomousSession,
    AutonomousState,
    CycleResult,
    ObservationPriority,
    ScheduledObservationPlan,
    SourceFreshnessStatus,
    WaitDecision,
    WaitReason,
    WakeCondition,
    WakeConditionType,
)
from nifty_trader.autonomous.deduplication import RequestDeduplicator
from nifty_trader.autonomous.engine import AutonomousObservationEngine
from nifty_trader.autonomous.freshness import SourceFreshnessChecker
from nifty_trader.autonomous.observation_planner import AutonomousObservationPlanner
from nifty_trader.autonomous.persistence import AutonomousStorage
from nifty_trader.autonomous.retry import BoundedRetryPolicy
from nifty_trader.autonomous.scheduler import AutonomousScheduler, FakeClock, IClock, RealClock
from nifty_trader.autonomous.session import AutonomousSessionController
from nifty_trader.autonomous.state_machine import AutonomousStateMachine, StateTransitionRecord
from nifty_trader.autonomous.wait_policy import WaitPolicy
from nifty_trader.autonomous.wake_conditions import WakeConditionEvaluator, WakeConditionFactory

__all__ = [
    "AutonomousObservationEngine",
    "AutonomousState",
    "WaitReason",
    "WakeCondition",
    "WakeConditionType",
    "WakeConditionFactory",
    "WakeConditionEvaluator",
    "WaitDecision",
    "ScheduledObservationPlan",
    "AutonomousCycle",
    "CycleResult",
    "AutonomousSession",
    "AutonomousLimits",
    "AutonomousStateMachine",
    "StateTransitionRecord",
    "WaitPolicy",
    "AutonomousObservationPlanner",
    "RequestDeduplicator",
    "SourceFreshnessChecker",
    "MeaningfulChangeDetector",
    "ChangeDetectionConfig",
    "BoundedRetryPolicy",
    "AutonomousSessionController",
    "AutonomousStorage",
    "AutonomousScheduler",
    "IClock",
    "RealClock",
    "FakeClock",
]
