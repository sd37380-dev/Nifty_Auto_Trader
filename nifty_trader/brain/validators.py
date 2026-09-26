"""
Brain Output Validators & Hallucination Defense.

Validates ModelRouter outputs against canonical schemas, enforces
non-execution invariants, checks confidence boundaries, and ensures evidence integrity.
"""

import logging
import re
from typing import Any, Dict, List, Optional, Set

from nifty_trader.brain.contracts import (
    BrainReasoningOutput,
    CandidateDirection,
    SetupState,
)

logger = logging.getLogger(__name__)


class ValidationError(Exception):
    """Raised when brain reasoning output violates domain invariants."""
    pass


class BrainOutputValidator:
    """
    Validates and sanitizes reasoning output from LLMs before it enters system state.
    """

    PROHIBITED_DIRECTIVES = [
        re.compile(r"\b(buy|sell)\s+(now|immediately|market|limit)\b", re.IGNORECASE),
        re.compile(r"\b(place\s+order|execute\s+trade|send\s+order)\b", re.IGNORECASE),
        re.compile(r"\b(position\s+size\s*[:=]\s*\d+|lot\s+size\s*[:=]\s*\d+)\b", re.IGNORECASE),
        re.compile(r"\b(hard\s+stop\s*[:=]|target\s*[:=]\s*2\d{4})\b", re.IGNORECASE),
    ]

    def validate_and_sanitize(
        self,
        output: BrainReasoningOutput,
        valid_evidence_ids: Optional[Set[str]] = None,
    ) -> BrainReasoningOutput:
        """
        Enforces domain invariants on the generated BrainReasoningOutput.
        """
        # 1. Prohibited execution directives defense
        text_corpus = f"{output.auditable_summary}\n{output.state_rationale}\n{output.one_hour_interpretation}\n{output.fifteen_minute_interpretation}"
        if output.candidate_thesis:
            text_corpus += f"\n{output.candidate_thesis.thesis}\n{output.candidate_thesis.market_context}"

        for pattern in self.PROHIBITED_DIRECTIVES:
            match = pattern.search(text_corpus)
            if match:
                logger.warning(
                    "Safety Boundary Violation: Prohibited execution directive '%s' detected in brain output. Demoting state to WAIT.",
                    match.group(0),
                )
                output.current_state = SetupState.WAIT
                output.state_rationale = (
                    f"SAFETY DEMOTION: Prohibited directive sequence '{match.group(0)}' was neutralized. "
                    "Package 4 is strictly an observation interpretation engine."
                )
                output.candidate_thesis = None
                break

        # 2. Confidence bounding check
        if output.confidence.value < 0.0 or output.confidence.value > 1.0:
            logger.warning("Confidence %f out of bounds [0.0, 1.0]. Clamping.", output.confidence.value)
            output.confidence.value = max(0.0, min(1.0, output.confidence.value))

        # 3. Candidate thesis invariants
        if output.current_state in [SetupState.WAIT, SetupState.NO_TRADE, SetupState.WATCH]:
            # If state is WAIT/NO_TRADE/WATCH, candidate_thesis should not be an active trade
            if output.candidate_thesis and output.candidate_thesis.direction != CandidateDirection.NEUTRAL:
                logger.info("Neutralizing candidate thesis for non-actionable state '%s'.", output.current_state.value)
                output.candidate_thesis.direction = CandidateDirection.NEUTRAL

        return output
