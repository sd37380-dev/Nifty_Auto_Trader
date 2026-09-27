"""
Package 5: Wait Policy.

Translates Package 4 cognitive reasoning results (WAIT, WATCH, NO_TRADE,
DEVELOPING, CANDIDATE) and operational failures into structured, deterministic
WaitDecision contracts with explicit wake conditions.

STRICT INVARIANT: WAIT is an action, not an error.
"""

from datetime import datetime, timedelta, timezone
import logging
from typing import List, Optional
import uuid

from nifty_trader.autonomous.contracts import (
    AutonomousLimits,
    WaitDecision,
    WaitReason,
    WakeCondition,
    WakeConditionType,
)
from nifty_trader.autonomous.wake_conditions import WakeConditionFactory
from nifty_trader.brain.contracts import (
    BrainFailure,
    BrainOutput,
    ReasoningState,
)
from nifty_trader.market_data.clock import CandleClock
from nifty_trader.market_data.models import Timeframe

logger = logging.getLogger(__name__)


class WaitPolicy:
    """
    Translates cognitive reasoning states and system telemetry into structured wait decisions.
    """

    def __init__(self, limits: Optional[AutonomousLimits] = None):
        self.limits = limits or AutonomousLimits()

    def formulate_decision(
        self,
        brain_output: Optional[BrainOutput] = None,
        failure: Optional[BrainFailure] = None,
        consecutive_failures: int = 0,
        current_time: Optional[datetime] = None,
        reference_price: Optional[float] = None,
    ) -> WaitDecision:
        """
        Formulates a comprehensive WaitDecision.
        """
        now = current_time or datetime.now(timezone.utc)

        # 1. Handle Model/Perception Failure with Bounded Retry Backoff
        if failure is not None or brain_output is None:
            backoff_secs = min(
                self.limits.max_wait_seconds,
                self.limits.min_wait_seconds * (2 ** min(consecutive_failures, 4)),
            )
            wake_time = now + timedelta(seconds=backoff_secs)
            fail_reason = failure.code if failure else "BRAIN_FAILURE"
            wait_reason = (
                WaitReason.BRAIN_UNAVAILABLE
                if failure and failure.code == "PROVIDER_UNAVAILABLE"
                else WaitReason.RETRY_BACKOFF
            )

            wake_cond = WakeCondition(
                condition_id=f"wake_fail_{uuid.uuid4().hex[:6]}",
                type=WakeConditionType.ERROR_RECOVERY,
                scheduled_at=wake_time,
                reason=f"Failure backoff ({fail_reason}) attempt {consecutive_failures + 1}",
                metadata={"consecutive_failures": consecutive_failures, "backoff_seconds": backoff_secs},
            )

            return WaitDecision(
                should_wait=True,
                reason=wait_reason,
                wake_conditions=[wake_cond],
                earliest_wake_at=wake_time,
                latest_wake_at=wake_time,
                observation_requests=[],
                explanation=f"Autonomous engine waiting {backoff_secs:.1f}s following {fail_reason}. Attempt {consecutive_failures + 1}.",
            )

        # 2. Handle CANDIDATE State (Terminal for current autonomous cycle)
        if brain_output.reasoning_state == ReasoningState.CANDIDATE:
            return WaitDecision(
                should_wait=False,
                reason=WaitReason.TIME_DELAY,
                wake_conditions=[],
                earliest_wake_at=now,
                latest_wake_at=now,
                observation_requests=[],
                explanation="Coherent Trade Candidate generated. Autonomous reasoning cycle halted for downstream evaluation.",
            )

        # 3. Handle Cognitive Wait / Watch / No Trade / Developing States
        conditions: List[WakeCondition] = []
        state = brain_output.reasoning_state

        # Check for explicit observation requests (e.g. stale Sensibull)
        has_obs_requests = bool(brain_output.observation_requests)
        obs_req_condition = None
        if has_obs_requests:
            for req in brain_output.observation_requests:
                delay = 5.0 if req.priority == "CRITICAL" else self.limits.default_cooldown_seconds
                obs_req_condition = WakeConditionFactory.create_source_refresh_condition(
                    source=req.source,
                    delay_seconds=delay,
                    as_of=now,
                    reason=f"Brain requested refresh for {req.source}: {req.reason}",
                )
                conditions.append(obs_req_condition)

        # Candle boundary wake condition (15M standard)
        candle_cond = WakeConditionFactory.create_candle_close_condition(
            timeframe="15M",
            as_of=now,
            reason="Waiting for next 15M candle completion",
        )
        conditions.append(candle_cond)

        # Significant price change wake condition (0.10%)
        price_cond = WakeConditionFactory.create_price_change_condition(
            threshold_relative=0.001,
            reference_price=reference_price,
            reason="Significant price move detected",
        )
        conditions.append(price_cond)

        # Manual steering instruction wake condition
        manual_cond = WakeConditionFactory.create_manual_instruction_condition(
            reason="Operator steering instruction submitted",
        )
        conditions.append(manual_cond)

        # Determine Primary WaitReason
        if has_obs_requests:
            wait_reason = WaitReason.OBSERVATION_REQUEST
        elif state == ReasoningState.WAIT:
            wait_reason = WaitReason.NEXT_CANDLE
        elif state == ReasoningState.WATCH:
            wait_reason = WaitReason.STRUCTURAL_CHANGE
        elif state == ReasoningState.DEVELOPING:
            wait_reason = WaitReason.STRUCTURAL_CHANGE
        elif state == ReasoningState.NO_TRADE:
            wait_reason = WaitReason.NEXT_CANDLE
        else:
            wait_reason = WaitReason.TIME_DELAY

        # Compute earliest and latest wake timestamps
        scheduled_times = [c.scheduled_at for c in conditions if c.type in (WakeConditionType.TIME, WakeConditionType.CANDLE_COMPLETION, WakeConditionType.SOURCE_REFRESH)]
        if not scheduled_times:
            scheduled_times = [now + timedelta(seconds=self.limits.min_wait_seconds)]

        earliest = min(scheduled_times)
        latest = max(scheduled_times)

        # Bound by min and max wait limits
        min_allowed = now + timedelta(seconds=self.limits.min_wait_seconds)
        max_allowed = now + timedelta(seconds=self.limits.max_wait_seconds)

        earliest_bounded = max(earliest, min_allowed)
        latest_bounded = min(latest, max_allowed)
        if latest_bounded < earliest_bounded:
            latest_bounded = earliest_bounded

        summary_note = brain_output.reasoning_summary.context if brain_output.reasoning_summary else state.value
        explanation = (
            f"State '{state.value}': {wait_reason.value}. "
            f"Next scheduled wake at {earliest_bounded.strftime('%H:%M:%S UTC')}. "
            f"Conditions active: {len(conditions)}. Context: {summary_note[:80]}"
        )

        return WaitDecision(
            should_wait=True,
            reason=wait_reason,
            wake_conditions=conditions,
            earliest_wake_at=earliest_bounded,
            latest_wake_at=latest_bounded,
            observation_requests=brain_output.observation_requests,
            explanation=explanation,
        )

    def formulate_pre_market_decision(
        self,
        market_open_time: datetime,
        current_time: Optional[datetime] = None,
    ) -> WaitDecision:
        """
        Formulates a wait decision when the market is in pre-market or closed.
        """
        now = current_time or datetime.now(timezone.utc)
        wake_time = max(now + timedelta(seconds=self.limits.min_wait_seconds), market_open_time)

        cond = WakeConditionFactory.create_session_event_condition(
            target_time=wake_time,
            reason="Waiting for regular market opening (09:15 IST)",
        )

        return WaitDecision(
            should_wait=True,
            reason=WaitReason.MARKET_OPEN,
            wake_conditions=[cond],
            earliest_wake_at=wake_time,
            latest_wake_at=wake_time,
            observation_requests=[],
            explanation=f"Pre-market wait until regular trading session opens at {wake_time.strftime('%H:%M:%S UTC')} (09:15 IST).",
        )
