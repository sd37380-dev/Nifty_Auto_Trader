"""
Trading Brain & Market Reasoning Engine (Package 4).

Orchestrates multi-source cognitive interpretation, scenario formulation,
testable hypothesis generation, non-executable trade candidate drafting,
and safety validation over canonical market observations conforming to
the Package 4 Canonical Trading Brain Domain Model.
"""

from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Literal, Optional, Set
import uuid

from nifty_trader.brain.context import BrainContextCompiler
from nifty_trader.brain.contracts import (
    DEFAULT_PROMPT_VERSION,
    PACKAGE4_SCHEMA_VERSION,
    BrainFailure,
    BrainInput,
    BrainOutput,
    BrainResult,
    BrainState,
    Confidence,
    Direction,
    MarketContext,
    MarketHypothesis,
    MarketRegime,
    ObservationReference,
    ObservationRequest,
    ReasoningState,
    ReasoningSummary,
    Scenario,
    Severity,
    StructureType,
    TimeframeAssessment,
    TradeCandidate,
    Uncertainty,
    UncertaintyType,
)
from nifty_trader.brain.prompts import (
    DEFAULT_PROMPT_VERSION,
    SYSTEM_REASONING_POLICY,
    build_reasoning_prompt,
)
from nifty_trader.brain.storage import BrainStorage
from nifty_trader.brain.validators import BrainOutputValidator
from nifty_trader.contracts.models import CanonicalObservationStatus, UnifiedMarketObservation
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
        prompt_version: str = DEFAULT_PROMPT_VERSION,
    ):
        self.router = router or ModelRouter()
        self.storage = storage or BrainStorage()
        self.compiler = context_compiler or BrainContextCompiler()
        self.validator = validator or BrainOutputValidator()
        self.prompt_version = prompt_version

    async def analyze(
        self,
        brain_input: BrainInput,
        image_bytes: Optional[bytes] = None,
        image_mime_type: str = "image/png",
    ) -> BrainResult:
        """
        Executes a cognitive reasoning cycle on the provided BrainInput.
        Guaranteed to return a valid BrainResult (success=True with BrainOutput,
        or success=False with BrainFailure) without crashing.
        """
        tier_cfg = self.router.get_tier_config(TaskTier.MARKET_ANALYSIS)
        model_provider = tier_cfg.get("provider", "gemini")
        model_name = tier_cfg.get("model", "gemini-2.5-flash")

        # 1. Compile structured observation context from observation
        context = self.compiler.compile(brain_input.observation)

        # 2. Build model-neutral reasoning prompt
        prompt = build_reasoning_prompt(context, prompt_version=self.prompt_version)

        # 3. Route to AI reasoning engine with fallback protection
        try:
            raw_output = await self.router.route_structured(
                task_tier=TaskTier.MARKET_ANALYSIS,
                prompt=prompt,
                response_model=BrainOutput,
                system_instruction=SYSTEM_REASONING_POLICY,
                image_bytes=image_bytes,
                image_mime_type=image_mime_type,
            )
            # Ensure identifiers and schema version match
            raw_output.brain_request_id = brain_input.brain_request_id
            raw_output.observation_id = brain_input.observation.observation_id
            raw_output.schema_version = PACKAGE4_SCHEMA_VERSION

            # 4. Extract valid evidence IDs & source freshness for audit traceability
            valid_evidence_ids = {ev.evidence_id for ev in brain_input.observation.evidence}
            source_freshness = {
                src_id: (stat.status == CanonicalObservationStatus.SUCCESS)
                for src_id, stat in brain_input.observation.source_status.items()
            }

            # 5. Validate invariants & neutralize prohibited directives
            validated_output = self.validator.validate_and_sanitize(
                output=raw_output,
                valid_evidence_ids=valid_evidence_ids,
                source_freshness_flags=source_freshness,
            )

            # 6. Persist reasoning audit trail
            try:
                self.storage.save_output(
                    output=validated_output,
                    model_provider=model_provider,
                    model_name=model_name,
                    task=brain_input.task,
                    prompt_version=self.prompt_version,
                )
            except Exception as store_err:
                logger.error("Failed to persist brain output: %s", store_err)

            return BrainResult(success=True, output=validated_output, failure=None)

        except Exception as e:
            logger.error("TradingBrainEngine cognitive failure: %s. Constructing BrainFailure.", e, exc_info=True)
            failure_code = "PROVIDER_UNAVAILABLE" if "exhausted" in str(e).lower() else "MODEL_ERROR"
            failure = BrainFailure(
                schema_version=PACKAGE4_SCHEMA_VERSION,
                brain_request_id=brain_input.brain_request_id,
                observation_id=brain_input.observation.observation_id,
                code=failure_code,
                message=str(e),
                retryable=True,
                provider=model_provider,
                model=model_name,
                created_at=datetime.now(timezone.utc),
            )
            return BrainResult(success=False, output=None, failure=failure)

    async def reason(
        self,
        observation: UnifiedMarketObservation,
        image_bytes: Optional[bytes] = None,
        image_mime_type: str = "image/png",
        task: Literal["MARKET_ANALYSIS", "SETUP_CONFIRMATION"] = "MARKET_ANALYSIS",
        requested_focus: Optional[List[str]] = None,
    ) -> BrainResult:
        """
        High-level entry point accepting UnifiedMarketObservation.
        Constructs canonical BrainInput and executes cognitive reasoning.
        """
        prev_state = self.storage.get_latest_state()
        brain_input = BrainInput(
            schema_version=PACKAGE4_SCHEMA_VERSION,
            brain_request_id=f"breq_{uuid.uuid4().hex[:10]}",
            observation=observation,
            task=task,
            manual_instruction_context=observation.manual_instruction_context,
            previous_brain_state=prev_state,
            requested_focus=requested_focus or [],
            timestamp=datetime.now(timezone.utc),
        )
        return await self.analyze(brain_input=brain_input, image_bytes=image_bytes, image_mime_type=image_mime_type)

    def get_latest_output(self) -> Optional[BrainOutput]:
        """Returns the most recent reasoning run."""
        return self.storage.get_latest_output()

    def get_latest_state(self) -> Optional[BrainState]:
        """Returns the most recent BrainState."""
        return self.storage.get_latest_state()

    def get_history(self, limit: int = 20, state: Optional[ReasoningState] = None) -> List[BrainOutput]:
        """Lists recent reasoning history."""
        return self.storage.list_outputs(limit=limit, state=state)
