"""
Package 5: Autonomous Observation & Waiting Engine.

The central temporal-control orchestrator for NIFTY Autonomous Trader.
Manages the bounded autonomous loop:
  OBSERVE -> UNDERSTAND -> WAIT -> OBSERVE AGAIN -> ... -> CANDIDATE / NO_TRADE / SESSION_END

STRICT INVARIANTS:
1. Temporal control and observation timing only.
2. Zero trade signal generation, zero order placement, zero broker dependencies.
3. Candidate output stops at CANDIDATE_READY (never executes).
4. WAIT is an action, not an error.
5. User STOP has highest runtime priority.
"""

import asyncio
from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional
import uuid

from nifty_trader.autonomous.change_detector import MeaningfulChangeDetector
from nifty_trader.autonomous.contracts import (
    AutonomousCycle,
    AutonomousLimits,
    AutonomousSession,
    AutonomousState,
    CycleResult,
    ObservationPriority,
    Package4OutputContractValidator,
    ScheduledObservationPlan,
    WaitDecision,
    WaitReason,
    WakeConditionType,
)
from nifty_trader.autonomous.deduplication import RequestDeduplicator
from nifty_trader.autonomous.freshness import SourceFreshnessChecker
from nifty_trader.autonomous.observation_planner import AutonomousObservationPlanner
from nifty_trader.autonomous.persistence import AutonomousStorage
from nifty_trader.autonomous.retry import BoundedRetryPolicy
from nifty_trader.autonomous.scheduler import AutonomousScheduler, IClock, RealClock
from nifty_trader.autonomous.session import AutonomousSessionController
from nifty_trader.autonomous.state_machine import AutonomousStateMachine
from nifty_trader.autonomous.wait_policy import WaitPolicy
from nifty_trader.brain.contracts import (
    BrainFailure,
    BrainOutput,
    BrainResult,
    ReasoningState,
)
from nifty_trader.contracts.models import (
    CanonicalObservationStatus,
    UnifiedMarketObservation,
)
from nifty_trader.market_data.session import MarketSessionStatus

logger = logging.getLogger(__name__)


class AutonomousObservationEngine:
    """
    Autonomous Observation & Waiting Engine.
    Coordinates observation cycles, waiting logic, patience policy, and market session boundaries.
    """

    def __init__(
        self,
        runtime: Any,  # NiftyTraderRuntime
        limits: Optional[AutonomousLimits] = None,
        clock: Optional[IClock] = None,
        storage: Optional[AutonomousStorage] = None,
    ):
        self.runtime = runtime
        self.limits = limits or AutonomousLimits()
        self.clock = clock or RealClock()
        self.storage = storage or AutonomousStorage()

        # Subsystems
        self.state_machine = AutonomousStateMachine(AutonomousState.IDLE)
        self.wait_policy = WaitPolicy(self.limits)
        self.deduplicator = RequestDeduplicator(self.limits)
        self.planner = AutonomousObservationPlanner(self.deduplicator, self.limits)
        self.freshness_checker = SourceFreshnessChecker()
        self.change_detector = MeaningfulChangeDetector()
        self.retry_policy = BoundedRetryPolicy(
            max_attempts=self.limits.max_consecutive_failures,
            initial_backoff_seconds=self.limits.min_wait_seconds,
            max_backoff_seconds=self.limits.max_wait_seconds,
        )
        self.session_controller = AutonomousSessionController(
            session_manager=runtime.market_service.session_manager,
            wait_policy=self.wait_policy,
        )
        self.scheduler = AutonomousScheduler(self.clock)

        # Active session state
        self._current_session: Optional[AutonomousSession] = None
        self._previous_observation: Optional[UnifiedMarketObservation] = None
        self._previous_brain_output: Optional[BrainOutput] = None
        self._latest_wait_decision: Optional[WaitDecision] = None
        self._explicit_wake_reason: Optional[str] = None
        self._is_running: bool = False
        self._loop_task: Optional[asyncio.Task] = None
        self._consecutive_failures: int = 0
        self._cycle_counter: int = 0

        # Wire state machine listener to SQLite persistence
        self.state_machine.add_listener(self._on_state_transition)

    @property
    def current_state(self) -> AutonomousState:
        return self.state_machine.current_state

    @property
    def is_running(self) -> bool:
        return self._is_running

    def _on_state_transition(self, record) -> None:
        try:
            self.storage.save_transition(record)
        except Exception as e:
            logger.error("Failed to persist state transition: %s", e)

    # =========================================================================
    # Lifecycle Controls (Start, Stop, Pause, Resume, Observe-Now)
    # =========================================================================

    async def start(
        self,
        symbol: str = "NIFTY",
        max_cycles: Optional[int] = None,
        run_once: bool = False,
    ) -> None:
        """
        Starts the autonomous observation engine.
        If run_once is True, executes a single bounded cycle and pauses/stops.
        """
        if self._is_running:
            logger.warning("Autonomous engine is already running.")
            return

        now = self.clock.now()
        session_id = f"asess_{uuid.uuid4().hex[:8]}"
        self._current_session = AutonomousSession(
            session_id=session_id,
            symbol=symbol,
            started_at=now,
            status=AutonomousState.STARTING,
        )
        self._cycle_counter = 0
        self._consecutive_failures = 0
        self._is_running = True
        self.scheduler.reset_events()

        if max_cycles is not None:
            self.limits.max_cycles = max_cycles

        self.state_machine.transition_to(
            AutonomousState.STARTING,
            reason="Autonomous session initialized by operator",
            session_id=session_id,
        )
        self.storage.save_session(self._current_session)

        if run_once:
            await self.run_single_cycle()
        else:
            self._loop_task = asyncio.create_task(self.run_loop())

    async def stop(self, reason: str = "Operator commanded STOP") -> None:
        """
        Highest Priority: Cancels waiting, aborts active reasoning, and stops engine.
        """
        logger.info("[STOP] Stopping autonomous engine. Reason: %s", reason)
        self._is_running = False
        self.scheduler.request_stop()

        if self._loop_task and not self._loop_task.done():
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass

        if self.state_machine.current_state != AutonomousState.STOPPED:
            self.state_machine.transition_to(
                AutonomousState.STOPPED,
                reason=reason,
                session_id=self._current_session.session_id if self._current_session else None,
            )

        if self._current_session:
            self._current_session.ended_at = self.clock.now()
            self._current_session.status = AutonomousState.STOPPED
            self.storage.save_session(self._current_session)

    async def pause(self, reason: str = "Operator commanded PAUSE") -> None:
        """Pauses autonomous observation cycles."""
        logger.info("[PAUSE] Pausing autonomous engine. Reason: %s", reason)
        self.scheduler.request_pause()
        if self.state_machine.can_transition_to(AutonomousState.SESSION_PAUSED):
            self.state_machine.transition_to(
                AutonomousState.SESSION_PAUSED,
                reason=reason,
                session_id=self._current_session.session_id if self._current_session else None,
            )

    async def resume(self, reason: str = "Operator commanded RESUME") -> None:
        """Resumes a paused autonomous engine."""
        logger.info("[RESUME] Resuming autonomous engine. Reason: %s", reason)
        if self.state_machine.can_transition_to(AutonomousState.WAITING):
            self.state_machine.transition_to(
                AutonomousState.WAITING,
                reason=reason,
                session_id=self._current_session.session_id if self._current_session else None,
            )
            self.scheduler.request_wake(reason="RESUME")

    async def observe_now(self, reason: str = "Operator commanded OBSERVE_NOW") -> None:
        """
        Immediately cancels current wait and schedules an immediate observation cycle.
        """
        logger.info("[OBSERVE_NOW] Immediate observation requested: %s", reason)
        self._explicit_wake_reason = reason
        self.scheduler.request_wake(reason=reason)

    # =========================================================================
    # Autonomous Reasoning Cycle Execution
    # =========================================================================

    async def run_single_cycle(self) -> CycleResult:
        """
        Executes one bounded cycle:
        CHECK SESSION -> OBSERVE -> MEANINGFUL CHANGE CHECK -> ANALYZE -> WAIT DECISION -> PERSIST
        """
        now = self.clock.now()
        self._cycle_counter += 1
        cycle_id = f"cycle_{uuid.uuid4().hex[:8]}"
        session_id = self._current_session.session_id if self._current_session else "standalone"
        prev_state = self.state_machine.current_state

        cycle_record = AutonomousCycle(
            cycle_id=cycle_id,
            session_id=session_id,
            cycle_index=self._cycle_counter,
            started_at=now,
            previous_state=prev_state,
            resulting_state=prev_state,
            wake_reason=self._explicit_wake_reason,
        )

        # 1. Check Safety Limits
        if self._cycle_counter > self.limits.max_cycles:
            logger.warning("Max cycles limit (%d) reached. Ending session.", self.limits.max_cycles)
            self.state_machine.transition_to(AutonomousState.SESSION_ENDED, reason="Max cycles reached", session_id=session_id, cycle_id=cycle_id)
            return CycleResult(success=True, state=AutonomousState.SESSION_ENDED, cycle_id=cycle_id, failure="MAX_CYCLES_REACHED", completed_at=now)

        if self._current_session and self._current_session.model_calls >= self.limits.max_model_calls:
            logger.warning("Max model calls limit (%d) reached. Ending session.", self.limits.max_model_calls)
            self.state_machine.transition_to(AutonomousState.SESSION_ENDED, reason="Max model calls reached", session_id=session_id, cycle_id=cycle_id)
            return CycleResult(success=True, state=AutonomousState.SESSION_ENDED, cycle_id=cycle_id, failure="MAX_MODEL_CALLS_REACHED", completed_at=now)

        if self._consecutive_failures >= self.limits.max_consecutive_failures:
            logger.error("Max consecutive failures (%d) reached. Entering ERROR state.", self.limits.max_consecutive_failures)
            self.state_machine.transition_to(AutonomousState.ERROR, reason="Max consecutive failures reached", session_id=session_id, cycle_id=cycle_id)
            return CycleResult(success=False, state=AutonomousState.ERROR, cycle_id=cycle_id, failure="MAX_FAILURES_EXCEEDED", completed_at=now)

        # 2. Check Market Session Boundaries
        sess_status, rec_state, wait_dec = self.session_controller.evaluate_session(now)
        if rec_state == AutonomousState.SESSION_PAUSED and wait_dec:
            logger.info("Market in PRE_MARKET session. Pausing until 09:15 IST.")
            self.state_machine.transition_to(AutonomousState.SESSION_PAUSED, reason=wait_dec.explanation, session_id=session_id, cycle_id=cycle_id)
            self._latest_wait_decision = wait_dec
            cycle_record.resulting_state = AutonomousState.SESSION_PAUSED
            cycle_record.wait_reason = wait_dec.reason
            cycle_record.completed_at = self.clock.now()
            self.storage.save_cycle(cycle_record)
            return CycleResult(success=True, state=AutonomousState.SESSION_PAUSED, cycle_id=cycle_id, next_wait=wait_dec, completed_at=now)
        elif rec_state == AutonomousState.SESSION_ENDED:
            logger.info("Market session is CLOSED/POST_MARKET. Concluding autonomous session.")
            self.state_machine.transition_to(AutonomousState.SESSION_ENDED, reason="Market closed", session_id=session_id, cycle_id=cycle_id)
            cycle_record.resulting_state = AutonomousState.SESSION_ENDED
            cycle_record.completed_at = self.clock.now()
            self.storage.save_cycle(cycle_record)
            return CycleResult(success=True, state=AutonomousState.SESSION_ENDED, cycle_id=cycle_id, completed_at=now)

        # 3. Enter OBSERVING State
        self.state_machine.transition_to(AutonomousState.OBSERVING, reason="Initiating market observation", session_id=session_id, cycle_id=cycle_id)

        # Determine Sources
        sources = self.planner.determine_sources_for_cycle(base_sources=["numerical"])
        unified_obs: Optional[UnifiedMarketObservation] = None

        try:
            include_sensi = "sensibull" in sources
            unified_obs = await self.runtime.get_unified_market_observation(
                cross_check=True,
                include_sensibull=include_sensi,
                sources=sources,
            )
            cycle_record.observation_id = unified_obs.observation_id
            cycle_record.observation_count += 1

            for s in sources:
                self.planner.mark_source_executed(s, timestamp=now)

        except Exception as obs_err:
            logger.error("Observation capture failure: %s", obs_err, exc_info=True)
            self._consecutive_failures += 1
            cycle_record.errors.append(str(obs_err))
            wait_dec = self.wait_policy.formulate_decision(
                failure=BrainFailure(
                    schema_version="1.0",
                    brain_request_id=f"breq_err_{uuid.uuid4().hex[:6]}",
                    observation_id="obs_failed",
                    code="PROVIDER_UNAVAILABLE",
                    message=f"Perception failure: {obs_err}",
                    retryable=True,
                    created_at=now,
                ),
                consecutive_failures=self._consecutive_failures,
                current_time=now,
            )
            self.state_machine.transition_to(AutonomousState.WAITING, reason="Waiting after observation failure", session_id=session_id, cycle_id=cycle_id)
            cycle_record.resulting_state = AutonomousState.WAITING
            cycle_record.completed_at = self.clock.now()
            self.storage.save_cycle(cycle_record)
            return CycleResult(success=False, state=AutonomousState.WAITING, cycle_id=cycle_id, next_wait=wait_dec, failure=str(obs_err), completed_at=self.clock.now())

        # 4. Meaningful Change Detection
        new_instructions = len(unified_obs.manual_instruction_context) > 0
        is_meaningful, change_reasons = self.change_detector.detect_changes(
            current_obs=unified_obs,
            previous_obs=self._previous_observation,
            new_instruction_present=new_instructions,
            explicit_wake_reason=self._explicit_wake_reason,
        )
        self._explicit_wake_reason = None  # Consume wake trigger

        # If not meaningful and previous reasoning exists, suppress redundant model call
        if not is_meaningful and self._previous_brain_output is not None:
            logger.info("No meaningful market change detected (%s). Suppressing redundant model call.", "; ".join(change_reasons) or "Unchanged")
            wait_dec = self.wait_policy.formulate_decision(
                brain_output=self._previous_brain_output,
                consecutive_failures=0,
                current_time=now,
            )
            self.state_machine.transition_to(AutonomousState.WAITING, reason="No meaningful change; continue waiting", session_id=session_id, cycle_id=cycle_id)
            cycle_record.resulting_state = AutonomousState.WAITING
            cycle_record.completed_at = self.clock.now()
            self.storage.save_cycle(cycle_record)
            return CycleResult(success=True, state=AutonomousState.WAITING, cycle_id=cycle_id, brain_output=self._previous_brain_output, next_wait=wait_dec, completed_at=self.clock.now())

        # 5. Enter ANALYZING State (Invoke Package 4 Trading Brain)
        self.state_machine.transition_to(AutonomousState.ANALYZING, reason=f"Meaningful change: {'; '.join(change_reasons)}", session_id=session_id, cycle_id=cycle_id)

        brain_result: Optional[BrainResult] = None
        try:
            brain_result = await self.runtime.reason_market(unified_obs=unified_obs)
            cycle_record.model_call_count += 1
            if self._current_session:
                self._current_session.model_calls += 1

        except Exception as brain_err:
            logger.error("Brain reasoning invocation error: %s", brain_err, exc_info=True)
            brain_result = BrainResult(
                success=False,
                output=None,
                failure=BrainFailure(
                    schema_version="1.0",
                    brain_request_id=f"breq_err_{uuid.uuid4().hex[:6]}",
                    observation_id=unified_obs.observation_id,
                    code="MODEL_ERROR",
                    message=str(brain_err),
                    retryable=True,
                    created_at=now,
                ),
            )

        # 6. Evaluate Brain Result & Formulate Next Step (Spec 52A)
        if not brain_result.success:
            self._consecutive_failures += 1
            cycle_record.errors.append(brain_result.failure.message)

            # Non-retryable failure triggers structured autonomous failure (ERROR state)
            if not brain_result.failure.retryable:
                logger.error("Non-retryable BrainFailure [%s]: %s. Entering ERROR state.", brain_result.failure.code, brain_result.failure.message)
                self.state_machine.transition_to(AutonomousState.ERROR, reason=f"Non-retryable brain failure: {brain_result.failure.code}", session_id=session_id, cycle_id=cycle_id)
                cycle_record.resulting_state = AutonomousState.ERROR
                cycle_record.completed_at = self.clock.now()
                self.storage.save_cycle(cycle_record)
                return CycleResult(success=False, state=AutonomousState.ERROR, cycle_id=cycle_id, failure=brain_result.failure.message, completed_at=self.clock.now())

            # Retryable failure triggers bounded backoff
            wait_dec = self.wait_policy.formulate_decision(
                failure=brain_result.failure,
                consecutive_failures=self._consecutive_failures,
                current_time=now,
            )
            self.state_machine.transition_to(AutonomousState.WAITING, reason=f"Wait following brain failure: {brain_result.failure.code}", session_id=session_id, cycle_id=cycle_id)
            cycle_record.resulting_state = AutonomousState.WAITING
            cycle_record.completed_at = self.clock.now()
            self.storage.save_cycle(cycle_record)
            return CycleResult(success=False, state=AutonomousState.WAITING, cycle_id=cycle_id, next_wait=wait_dec, failure=brain_result.failure.message, completed_at=self.clock.now())

        # Success path: Enforce Package 4 domain contract invariants (Spec 52A.9)
        brain_out = brain_result.output
        is_valid, validation_err = Package4OutputContractValidator.validate(brain_out)
        if not is_valid:
            logger.error("Package 4 BrainOutput contract violation: %s. Entering ERROR state.", validation_err)
            self._consecutive_failures += 1
            cycle_record.errors.append(validation_err)
            self.state_machine.transition_to(
                AutonomousState.ERROR,
                reason=f"Contract validation failure: {validation_err}",
                session_id=session_id,
                cycle_id=cycle_id,
            )
            cycle_record.resulting_state = AutonomousState.ERROR
            cycle_record.completed_at = self.clock.now()
            self.storage.save_cycle(cycle_record)
            return CycleResult(success=False, state=AutonomousState.ERROR, cycle_id=cycle_id, failure=validation_err, completed_at=self.clock.now())

        self._consecutive_failures = 0
        self._previous_brain_output = brain_out
        self._previous_observation = unified_obs
        cycle_record.brain_request_id = brain_out.brain_request_id

        # Plan any requested observations
        plans: List[ScheduledObservationPlan] = []
        if brain_out.observation_requests:
            plans = self.planner.plan_requests(brain_out.observation_requests, current_time=now)
            if self._current_session:
                self._current_session.observation_requests_count += len(plans)

        # Check for CANDIDATE (Terminal for this autonomous cycle)
        if brain_out.reasoning_state == ReasoningState.CANDIDATE:
            logger.info("[CANDIDATE_READY] Coherent trade candidate produced. Stopping autonomous reasoning loop.")
            self.state_machine.transition_to(AutonomousState.CANDIDATE_READY, reason="Candidate produced; loop halts", session_id=session_id, cycle_id=cycle_id)
            cycle_record.resulting_state = AutonomousState.CANDIDATE_READY
            cycle_record.completed_at = self.clock.now()
            self.storage.save_cycle(cycle_record)
            wait_dec = self.wait_policy.formulate_decision(brain_output=brain_out, current_time=now)
            self.storage.save_wait_decision(wait_dec, cycle_id=cycle_id)
            return CycleResult(success=True, state=AutonomousState.CANDIDATE_READY, cycle_id=cycle_id, brain_output=brain_out, next_wait=wait_dec, completed_at=self.clock.now())

        # Formulate Wait Decision
        ref_price = unified_obs.numerical.latest_15m.close if unified_obs.numerical.latest_15m else None
        wait_dec = self.wait_policy.formulate_decision(
            brain_output=brain_out,
            consecutive_failures=0,
            current_time=now,
            reference_price=ref_price,
        )
        self._latest_wait_decision = wait_dec
        self.storage.save_wait_decision(wait_dec, cycle_id=cycle_id)

        # Determine target state
        if brain_out.reasoning_state == ReasoningState.WATCH:
            target_state = AutonomousState.WATCHING
        elif brain_out.reasoning_state == ReasoningState.NO_TRADE:
            target_state = AutonomousState.NO_TRADE
        elif plans and any(p.priority == ObservationPriority.CRITICAL for p in plans):
            target_state = AutonomousState.REOBSERVE_REQUESTED
        else:
            target_state = AutonomousState.WAITING

        self.state_machine.transition_to(target_state, reason=wait_dec.explanation, session_id=session_id, cycle_id=cycle_id)
        cycle_record.resulting_state = target_state
        cycle_record.wait_reason = wait_dec.reason
        cycle_record.completed_at = self.clock.now()
        self.storage.save_cycle(cycle_record)

        if self._current_session:
            self._current_session.cycles_completed += 1
            self._current_session.status = target_state
            self.storage.save_session(self._current_session)

        return CycleResult(
            success=True,
            state=target_state,
            cycle_id=cycle_id,
            brain_output=brain_out,
            next_wait=wait_dec,
            observation_plans=plans,
            completed_at=self.clock.now(),
        )

    async def run_loop(self) -> None:
        """
        Continuous bounded loop running until terminal state or user stop.
        """
        logger.info("[LOOP] Autonomous loop initiated.")
        terminal_states = {
            AutonomousState.STOPPED,
            AutonomousState.SESSION_ENDED,
            AutonomousState.CANDIDATE_READY,
            AutonomousState.ERROR,
        }

        try:
            while self._is_running and self.state_machine.current_state not in terminal_states:
                cycle_result = await self.run_single_cycle()

                if cycle_result.state in terminal_states:
                    logger.info("[LOOP] Terminating autonomous loop in state: %s", cycle_result.state.value)
                    break

                if cycle_result.next_wait and cycle_result.next_wait.should_wait:
                    wake_time = cycle_result.next_wait.earliest_wake_at
                    logger.info("[WAIT] Suspending execution until next scheduled wake at %s", wake_time.strftime('%H:%M:%S UTC'))
                    wake_trigger = await self.scheduler.wait_until(wake_time)
                    logger.info("[WAKE] Waking engine via trigger: %s", wake_trigger.value)

                    if self.state_machine.current_state in (AutonomousState.STOPPED, AutonomousState.SESSION_PAUSED):
                        break

        except asyncio.CancelledError:
            logger.info("[LOOP] Autonomous loop cancelled.")
        except Exception as e:
            logger.error("[LOOP] Unhandled loop exception: %s", e, exc_info=True)
            if self.state_machine.can_transition_to(AutonomousState.ERROR):
                self.state_machine.transition_to(AutonomousState.ERROR, reason=f"Unhandled loop error: {e}")
        finally:
            self._is_running = False

    def get_status(self) -> Dict[str, Any]:
        """Returns structured status overview for CLI and diagnostics."""
        session_stat = self.session_controller.session_manager.get_session_status()
        latest_c = self.storage.list_cycles(limit=1)
        cycle_info = latest_c[0] if latest_c else None

        next_wake_str = "None"
        wait_reason_str = "None"
        if self._latest_wait_decision:
            next_wake_str = self._latest_wait_decision.earliest_wake_at.strftime('%Y-%m-%d %H:%M:%S UTC')
            wait_reason_str = self._latest_wait_decision.reason.value

        return {
            "status": self.state_machine.current_state.value,
            "is_running": self._is_running,
            "market_session": session_stat.value,
            "session_id": self._current_session.session_id if self._current_session else "None",
            "current_brain_state": self._previous_brain_output.reasoning_state.value if self._previous_brain_output else "None",
            "wait_reason": wait_reason_str,
            "next_wake": next_wake_str,
            "cycles_completed": self._cycle_counter,
            "max_cycles": self.limits.max_cycles,
            "model_calls": self._current_session.model_calls if self._current_session else 0,
            "max_model_calls": self.limits.max_model_calls,
            "active_observation_plans": len(self.planner.get_pending_plans()),
            "consecutive_failures": self._consecutive_failures,
        }
