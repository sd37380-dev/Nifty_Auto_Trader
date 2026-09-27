"""
Stage 6: Hermes Context Builder.

Synthesizes Hermes's operational knowledge, perception data, previous reasoning state,
manual instructions, and memory into the canonical Package 4 BrainInput contract.
"""

from copy import deepcopy
from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional
import uuid

from nifty_trader.brain.contracts import (
    PACKAGE4_SCHEMA_VERSION,
    BrainInput,
    BrainState,
)
from nifty_trader.brain.context.context_memory import ContextMemoryStore
from nifty_trader.brain.context.context_selector import (
    ContextPriority,
    ContextSelector,
    PrioritizedContextItem,
)
from nifty_trader.brain.context.context_validator import ContextSecurityValidator
from nifty_trader.contracts.models import (
    CrossSourceValidationStatus,
    ManualInstructionContext,
    UnifiedMarketObservation,
)

logger = logging.getLogger(__name__)


class HermesContextBuilder:
    """
    Transforms Hermes world state into canonical BrainInput for AI Brain reasoning.
    """

    def __init__(
        self,
        security_validator: Optional[ContextSecurityValidator] = None,
        context_selector: Optional[ContextSelector] = None,
        memory_store: Optional[ContextMemoryStore] = None,
    ):
        self.security_validator = security_validator or ContextSecurityValidator()
        self.selector = context_selector or ContextSelector()
        self.memory_store = memory_store

    def build_brain_input(
        self,
        observation: UnifiedMarketObservation,
        previous_brain_state: Optional[BrainState] = None,
        manual_instructions: Optional[List[ManualInstructionContext]] = None,
        requested_focus: Optional[List[str]] = None,
        task: str = "MARKET_ANALYSIS",
    ) -> BrainInput:
        """
        Builds a canonical, secure, bounded BrainInput.
        """
        # 1. Deepcopy observation to protect original perception state
        sanitized_obs = deepcopy(observation)

        # 2. Sanitize and quarantine untrusted external browser data
        if sanitized_obs.visual.tradingview and sanitized_obs.visual.tradingview.visible_text:
            sanitized_obs.visual.tradingview.visible_text = (
                self.security_validator.sanitize_untrusted_text(
                    sanitized_obs.visual.tradingview.visible_text,
                    source="TradingView_Browser_Observation",
                    max_length=2000,
                )
            )

        if sanitized_obs.visual.sensibull and sanitized_obs.visual.sensibull.visible_text:
            sanitized_obs.visual.sensibull.visible_text = (
                self.security_validator.sanitize_untrusted_text(
                    sanitized_obs.visual.sensibull.visible_text,
                    source="Sensibull_Browser_Observation",
                    max_length=2000,
                )
            )

        # 3. Filter and validate manual operator instructions
        valid_instructions: List[ManualInstructionContext] = []
        raw_instructions = manual_instructions or sanitized_obs.manual_instruction_context or []
        for inst in raw_instructions:
            is_valid, err = self.security_validator.validate_instruction_source(
                inst.text,
                created_by=inst.created_by,
            )
            if is_valid:
                valid_instructions.append(inst)
            else:
                logger.warning("Dropped untrusted instruction: %s", err)

        # 4. Extract relevant memory context if store available
        memory_context_str: Optional[str] = None
        if self.memory_store:
            query_hint = ""
            if previous_brain_state and previous_brain_state.market_context:
                query_hint = previous_brain_state.market_context.summary
            memories = self.memory_store.query_relevant(
                query_text=query_hint,
                limit=3,
            )
            if memories:
                memory_context_str = self.memory_store.format_for_context(memories)

        # 5. Check cross-source consistency
        has_conflict = any(
            csv.status == CrossSourceValidationStatus.SIGNIFICANT_DIFFERENCE
            for csv in sanitized_obs.cross_source_validation
        )
        if has_conflict:
            logger.info("Context builder noted cross-source discrepancies in observation %s", sanitized_obs.observation_id)

        # 6. Construct canonical BrainInput
        brain_input = BrainInput(
            schema_version=PACKAGE4_SCHEMA_VERSION,
            brain_request_id=f"breq_{uuid.uuid4().hex[:10]}",
            observation=sanitized_obs,
            task=task,
            manual_instruction_context=valid_instructions,
            previous_brain_state=previous_brain_state,
            requested_focus=requested_focus or [],
            memory_context=memory_context_str,
            timestamp=datetime.now(timezone.utc),
        )

        return brain_input
