"""
Trading Brain & Market Reasoning Engine (Package 4).

Orchestrates multi-source cognitive interpretation, scenario formulation,
testable hypothesis generation, non-executable trade candidate drafting,
and safety validation over canonical market observations.
"""

from datetime import datetime, timezone
import logging
from typing import Any, Dict, Optional, Set
import uuid

from nifty_trader.brain.context import BrainContextCompiler
from nifty_trader.brain.contracts import (
    BoundedConfidence,
    BrainReasoningOutput,
    MarketRegime,
    ObservationRequest,
    SetupState,
    Uncertainty,
    UncertaintyType,
)
from nifty_trader.brain.prompts import SYSTEM_REASONING_POLICY, build_reasoning_prompt
from nifty_trader.brain.storage import BrainStorage
from nifty_trader.brain.validators import BrainOutputValidator
from nifty_trader.contracts.models import UnifiedMarketObservation
from nifty_trader.router.base import TaskTier
from nifty_trader.router.router import ModelRouter

logger = logging.getLogger(__name__)


class TradingBrainEngine:
    """
    Cognitive reasoning core of the NIFTY Autonomous Trader.
    """

    def __init__(
        self,
        router: Optional[ModelRouter] = None,
        storage: Optional[BrainStorage] = None,
        context_compiler: Optional[BrainContextCompiler] = None,
        validator: Optional[BrainOutputValidator] = None,
    ):
        self.router = router or ModelRouter()
        self.storage = storage or BrainStorage()
        self.compiler = context_compiler or BrainContextCompiler()
        self.validator = validator or BrainOutputValidator()

    async def reason(
        self,
        observation: UnifiedMarketObservation,
        image_bytes: Optional[bytes] = None,
        image_mime_type: str = "image/png",
    ) -> BrainReasoningOutput:
        """
        Executes a cognitive reasoning cycle on the provided canonical market observation.
        Guaranteed to return a valid BrainReasoningOutput without crashing on LLM/provider failures.
        """
        tier_cfg = self.router.get_tier_config(TaskTier.MARKET_ANALYSIS)
        model_provider = tier_cfg.get("provider", "gemini")
        model_name = tier_cfg.get("model", "gemini-2.5-flash")

        # 1. Compile structured observation context
        context = self.compiler.compile(observation)

        # 2. Build model-neutral reasoning prompt
        prompt = build_reasoning_prompt(context)

        # 3. Route to AI reasoning engine with fallback protection
        try:
            raw_output = await self.router.route_structured(
                task_tier=TaskTier.MARKET_ANALYSIS,
                prompt=prompt,
                response_model=BrainReasoningOutput,
                system_instruction=SYSTEM_REASONING_POLICY,
                image_bytes=image_bytes,
                image_mime_type=image_mime_type,
            )
            # Ensure observation_id matches input
            raw_output.observation_id = observation.observation_id
            raw_output.instrument = observation.instrument

            # 4. Extract valid evidence IDs for audit traceability
            valid_evidence_ids = {ev.evidence_id for ev in observation.evidence}

            # 5. Validate invariants & neutralize prohibited directives
            validated_output = self.validator.validate_and_sanitize(raw_output, valid_evidence_ids)

        except Exception as e:
            logger.error("TradingBrainEngine cognitive reasoning failure: %s. Engaging safe WAIT fallback.", e, exc_info=True)
            validated_output = self._create_safe_fallback(
                observation=observation,
                error_message=str(e),
            )

        # 6. Persist reasoning audit trail
        try:
            self.storage.save_run(
                output=validated_output,
                model_provider=model_provider,
                model_name=model_name,
            )
        except Exception as store_err:
            logger.error("Failed to persist brain reasoning run: %s", store_err)

        return validated_output

    def _create_safe_fallback(
        self,
        observation: UnifiedMarketObservation,
        error_message: str,
    ) -> BrainReasoningOutput:
        """
        Constructs an explicit, auditable WAIT state when AI models or network fail.
        Guarantees zero order execution and zero pipeline crashes.
        """
        return BrainReasoningOutput(
            schema_version="1.0",
            brain_run_id=f"brain_fb_{uuid.uuid4().hex[:8]}",
            observation_id=observation.observation_id,
            timestamp=datetime.now(timezone.utc),
            instrument=observation.instrument,
            regime=MarketRegime.UNCLEAR,
            regime_confidence=0.0,
            regime_evidence=["Cognitive engine fallback engaged due to provider failure."],
            one_hour_interpretation="Cognitive analysis unavailable due to operational provider error.",
            fifteen_minute_interpretation="Cognitive analysis unavailable due to operational provider error.",
            multi_source_synthesis="Cross-source synthesis deferred. Provider returned an error.",
            source_disagreement_assessment=None,
            scenarios=[],
            hypotheses=[],
            current_state=SetupState.WAIT,
            state_rationale=f"COGNITIVE_FAILOVER: Provider error encountered ({error_message}). Safety state WAIT engaged.",
            next_observation_needed="Perform new observation cycle once cognitive provider connectivity is restored.",
            candidate_thesis=None,
            observation_requests=[
                ObservationRequest(
                    source="system",
                    reason="Cognitive provider recovery",
                    requested_information="Verify provider status and re-run analysis",
                    priority="HIGH",
                )
            ],
            confidence=BoundedConfidence(
                value=0.0,
                basis=["Automatic failover default with zero confidence."],
            ),
            uncertainties=[
                Uncertainty(
                    type=UncertaintyType.AMBIGUOUS_STRUCTURE,
                    description=f"Model execution failure: {error_message}",
                    affected_conclusion="All interpretations and state determinations",
                    severity="HIGH",
                )
            ],
            auditable_summary=(
                f"SAFETY ENGAGED: Cognitive reasoning for observation '{observation.observation_id}' "
                f"could not be processed by AI model ({error_message}). Defaulted to state WAIT. "
                "No trade candidates formed."
            ),
        )

    def get_latest_reasoning(self) -> Optional[BrainReasoningOutput]:
        """Returns the most recent reasoning run."""
        return self.storage.get_latest()

    def get_reasoning_by_id(self, brain_run_id: str) -> Optional[BrainReasoningOutput]:
        """Returns a specific reasoning run."""
        return self.storage.get_run(brain_run_id)

    def get_history(self, limit: int = 20, state: Optional[SetupState] = None):
        """Lists recent reasoning history."""
        return self.storage.list_runs(limit=limit, state=state)
