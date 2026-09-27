"""
Stage 6: Hermes-Brain Collaborative Trading Orchestrator.

Implements the collaborative partnership where:
- Hermes = Autonomous Agent / Orchestrator / Operator
- Brain = AI Reasoning Intelligence
- Tools = Eyes / Information / Hands
- Memory = Historical Experience (Contextual Evidence)
- Safety = Non-Overridable Boundary

STRICT INVARIANTS:
1. No traditional Strategy Engine (no hardcoded EMA/VWAP/RSI/Supertrend decision engines).
2. No live broker execution or position sizing in this stage (yields TradeCandidate only).
3. The Brain never directly touches browser APIs; Hermes fulfills ObservationRequests via tools.
4. WAIT is a first-class operational state through Package 5.
"""

from datetime import datetime, timezone
import logging
import time
from typing import Any, Dict, List, Optional
import uuid

from nifty_trader.autonomous.contracts import AutonomousLimits, WaitDecision
from nifty_trader.autonomous.wait_policy import WaitPolicy
from nifty_trader.brain.context.context_builder import HermesContextBuilder
from nifty_trader.brain.contracts import (
    BrainFailure,
    BrainInput,
    BrainOutput,
    BrainResult,
    BrainState,
    ObservationRequest,
    ReasoningState,
    TradeCandidate,
)
from nifty_trader.brain.engine import TradingBrainEngine
from nifty_trader.brain.storage import BrainStorage
from nifty_trader.contracts.models import (
    ManualInstructionContext,
    UnifiedMarketObservation,
)
from nifty_trader.hermes.contracts import (
    CollaborationAuditStore,
    CollaborationCycle,
    CollaborationTurn,
)
from nifty_trader.hermes.tool_bridge import HermesToolBridge

logger = logging.getLogger(__name__)


class HermesBrainOrchestrator:
    """
    Central orchestrator coordinating Hermes agent tools, context compilation,
    cognitive AI Brain reasoning, and operational waiting.
    """

    def __init__(
        self,
        brain_engine: TradingBrainEngine,
        tool_bridge: HermesToolBridge,
        context_builder: Optional[HermesContextBuilder] = None,
        brain_storage: Optional[BrainStorage] = None,
        wait_policy: Optional[WaitPolicy] = None,
        audit_store: Optional[CollaborationAuditStore] = None,
        max_re_evaluation_turns: int = 3,
    ):
        self.brain = brain_engine
        self.tool_bridge = tool_bridge
        self.context_builder = context_builder or HermesContextBuilder()
        self.storage = brain_storage
        self.wait_policy = wait_policy or WaitPolicy()
        self.audit_store = audit_store or CollaborationAuditStore()
        self.max_turns = max_re_evaluation_turns

    async def run_collaboration_cycle(
        self,
        session_id: str,
        symbol: str = "NIFTY",
        max_turns: Optional[int] = None,
        force_initial_observation: Optional[UnifiedMarketObservation] = None,
        manual_instructions: Optional[List[ManualInstructionContext]] = None,
    ) -> CollaborationCycle:
        """
        Executes a collaborative reasoning cycle across Hermes and the Brain.
        """
        turn_limit = max_turns or self.max_turns
        cycle = CollaborationCycle(
            session_id=session_id,
            instrument=symbol,
            started_at=datetime.now(timezone.utc),
            model_used=getattr(self.brain, "model_name", "gemini"),
        )

        logger.info(
            "Starting Hermes-Brain Collaboration Cycle %s for session %s (Limit: %d turns)",
            cycle.cycle_id,
            session_id,
            turn_limit,
        )

        # 1. Fetch initial observation
        current_obs = force_initial_observation
        if not current_obs:
            try:
                current_obs = await self.tool_bridge.fetch_current_observation(symbol=symbol)
            except Exception as e:
                logger.error("Failed to acquire initial observation for collaboration cycle: %s", e)
                cycle.completed_at = datetime.now(timezone.utc)
                cycle.metadata["error"] = f"Initial observation failed: {str(e)}"
                self.audit_store.record_cycle(cycle)
                return cycle

        # 2. Retrieve previous cognitive state for continuity
        previous_brain_state: Optional[BrainState] = None
        if self.storage:
            try:
                previous_brain_state = self.storage.get_latest_state()
                if previous_brain_state:
                    logger.info(
                        "Resuming previous reasoning continuity from state %s (%s)",
                        previous_brain_state.state_id,
                        previous_brain_state.reasoning_state.value,
                    )
            except Exception as e:
                logger.warning("Could not retrieve latest brain state: %s", e)

        # 3. Retrieve active manual instructions if not provided explicitly
        active_instructions = manual_instructions
        if active_instructions is None:
            active_instructions = await self.tool_bridge.get_active_instructions()

        requested_focus: List[str] = []

        # 4. Collaboration Turns Loop
        for turn_idx in range(turn_limit):
            turn_start = time.perf_counter()
            action = "INITIAL_REASONING" if turn_idx == 0 else "RE_EVALUATION"

            # Build canonical, sanitized, bounded BrainInput
            brain_input = self.context_builder.build_brain_input(
                observation=current_obs,
                previous_brain_state=previous_brain_state,
                manual_instructions=active_instructions,
                requested_focus=requested_focus,
            )

            # Route to Brain Reasoning Intelligence
            result: BrainResult = await self.brain.reason(brain_input)
            duration_ms = (time.perf_counter() - turn_start) * 1000.0

            if not result.success:
                # Brain Failure occurred (network, validation, rate limit)
                # STRICT INVARIANT: Never invent fake reasoning or convert failure to fake trade
                failure: BrainFailure = result.failure
                logger.error(
                    "Brain reasoning failed on turn %d: [%s] %s",
                    turn_idx + 1,
                    failure.code,
                    failure.message,
                )
                turn = CollaborationTurn(
                    turn_index=turn_idx + 1,
                    brain_request_id=brain_input.brain_request_id,
                    action_taken=f"{action}_FAILED",
                    requested_items=[],
                    tools_invoked=[],
                    reasoning_state=None,
                    duration_ms=duration_ms,
                )
                cycle.turns.append(turn)
                cycle.metadata["brain_failure"] = {
                    "code": failure.code,
                    "message": failure.message,
                    "retryable": failure.retryable,
                }
                break

            output: BrainOutput = result.output
            reasoning_state = output.reasoning_state
            logger.info(
                "Brain evaluated turn %d: ReasoningState=%s (Confidence=%.2f)",
                turn_idx + 1,
                reasoning_state.value,
                output.confidence.value,
            )

            # Update cognitive state continuity
            if self.storage:
                try:
                    prov = getattr(self.brain, "model_provider", None)
                    mname = getattr(self.brain, "model_name", None)
                    self.storage.save_output(
                        output=output,
                        model_provider=prov if isinstance(prov, str) else "gemini",
                        model_name=mname if isinstance(mname, str) else "gemini-2.5-flash",
                        task="MARKET_ANALYSIS",
                    )
                    previous_brain_state = self.storage.get_latest_state()
                except Exception as e:
                    logger.warning("Failed to persist brain output state: %s", e)

            # Record turn telemetry
            turn = CollaborationTurn(
                turn_index=turn_idx + 1,
                brain_request_id=brain_input.brain_request_id,
                action_taken=action,
                requested_items=[getattr(req, "source", None) or getattr(req, "target", "") for req in output.observation_requests],
                tools_invoked=[],
                reasoning_state=reasoning_state,
                duration_ms=duration_ms,
            )

            # 5. Handle Reasoning State & Operational Decision
            if reasoning_state == ReasoningState.CANDIDATE:
                # Candidate formulated: STRICT BOUNDARY - Zero Broker Execution!
                cycle.candidate = output.candidate
                cycle.final_reasoning_state = ReasoningState.CANDIDATE
                cycle.turns.append(turn)
                logger.info(
                    "Collaboration cycle produced TradeCandidate [%s: %s]. Halting cycle for downstream safety.",
                    output.candidate.thesis,
                    output.candidate.direction.value,
                )
                break

            # Check if Brain requested additional observations and turns remain
            if output.observation_requests and (turn_idx + 1 < turn_limit):
                cycle.observation_requests_issued.extend(output.observation_requests)
                tools_executed_all = []
                for req in output.observation_requests:
                    current_obs, tools = await self.tool_bridge.fulfill_observation_request(
                        request=req,
                        current_observation=current_obs,
                    )
                    tools_executed_all.extend(tools)

                turn.tools_invoked = tools_executed_all
                cycle.turns.append(turn)

                # Set requested focus for the re-evaluation turn
                requested_focus = [
                    f"{getattr(req, 'source', None) or getattr(req, 'target', '')}: {req.reason}"
                    for req in output.observation_requests
                ]
                logger.info(
                    "Fulfill complete. Invoked tools %s. Proceeding to turn %d re-evaluation.",
                    tools_executed_all,
                    turn_idx + 2,
                )
                continue

            # Non-candidate states termination (WAIT, WATCH, DEVELOPING, NO_TRADE)
            cycle.final_reasoning_state = reasoning_state
            cycle.turns.append(turn)

            if reasoning_state == ReasoningState.WAIT:
                ref_px = None
                if current_obs.numerical and current_obs.numerical.candles_15m:
                    ref_px = current_obs.numerical.candles_15m[-1].close
                wait_decision = self.wait_policy.formulate_decision(
                    brain_output=output,
                    reference_price=ref_px,
                )
                cycle.wait_decision = wait_decision.model_dump()
                logger.info(
                    "Collaborative cycle entered WAIT: Reason=%s, EarliestWake=%s, Explanation='%s'",
                    wait_decision.reason.value,
                    wait_decision.earliest_wake_at.isoformat(),
                    wait_decision.explanation,
                )

            break

        cycle.completed_at = datetime.now(timezone.utc)
        self.audit_store.record_cycle(cycle)
        return cycle
