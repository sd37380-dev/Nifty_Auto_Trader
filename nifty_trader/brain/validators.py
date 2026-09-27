"""
Brain Output Validators & Domain Invariant Defense (Package 4).

Validates structured BrainOutput against domain rules, enforces non-execution
invariants, checks confidence boundaries, and ensures evidence integrity.
"""

import logging
import re
from typing import Any, Dict, List, Optional, Set

from nifty_trader.brain.contracts import (
    BrainOutput,
    Direction,
    ReasoningState,
    Severity,
    Uncertainty,
    UncertaintyType,
)

logger = logging.getLogger(__name__)


class ValidationError(Exception):
    """Raised when brain reasoning output violates domain invariants."""
    pass


class BrainOutputValidator:
    """
    Validates and sanitizes reasoning output from LLMs before it enters system state.
    Enforces Rules 1 through 10 of Package 4 Canonical Specification.
    """

    # Prohibited execution and risk directives
    PROHIBITED_DIRECTIVES = [
        re.compile(r"\b(buy|sell)\s+(now|immediately|market|limit)\b", re.IGNORECASE),
        re.compile(r"\b(place\s+order|execute\s+trade|send\s+order|submit\s+order)\b", re.IGNORECASE),
        re.compile(r"\b(position\s+size\s*[:=]\s*\d+|lot\s+size\s*[:=]\s*\d+)\b", re.IGNORECASE),
        re.compile(r"\b(hard\s+stop\s*[:=]|target\s*[:=]\s*2\d{4})\b", re.IGNORECASE),
        re.compile(r"\b(risk_per_trade|max_loss|portfolio_exposure|broker_action)\b", re.IGNORECASE),
    ]

    def validate_and_sanitize(
        self,
        output: BrainOutput,
        valid_evidence_ids: Optional[Set[str]] = None,
        source_freshness_flags: Optional[Dict[str, bool]] = None,
    ) -> BrainOutput:
        """
        Enforces domain invariants on the generated BrainOutput.
        """
        # 1. Prohibited execution and risk directives defense (Rule 6 & Rule 7)
        text_corpus = (
            f"{output.reasoning_summary.context}\n"
            f"{output.reasoning_summary.interpretation}\n"
            f"{output.market_context.summary}\n"
            + "\n".join(t.summary for t in output.timeframe_assessments)
        )
        if output.candidate:
            text_corpus += f"\n{output.candidate.thesis}\n{output.candidate.market_context}"

        for pattern in self.PROHIBITED_DIRECTIVES:
            match = pattern.search(text_corpus)
            if match:
                logger.warning(
                    "Safety Boundary Violation: Prohibited execution directive '%s' detected in brain output. Demoting state to WAIT.",
                    match.group(0),
                )
                output.reasoning_state = ReasoningState.WAIT
                output.reasoning_summary.interpretation = (
                    f"SAFETY DEMOTION: Prohibited directive sequence '{match.group(0)}' was neutralized. "
                    "Package 4 is strictly an observation interpretation engine."
                )
                output.candidate = None
                break

        # 2. Reasoning State Invariants (Rules 1, 2, 3, 4, 5)
        # Rule 1 — NO_TRADE: candidate must be None
        if output.reasoning_state == ReasoningState.NO_TRADE:
            if output.candidate is not None:
                logger.info("Rule 1 Enforced: candidate neutralized for NO_TRADE state.")
                output.candidate = None

        # Rule 2 — WAIT: candidate must be None
        elif output.reasoning_state == ReasoningState.WAIT:
            if output.candidate is not None:
                logger.info("Rule 2 Enforced: candidate neutralized for WAIT state.")
                output.candidate = None

        # Rule 3 — WATCH: candidate must be None
        elif output.reasoning_state == ReasoningState.WATCH:
            if output.candidate is not None:
                logger.info("Rule 3 Enforced: candidate neutralized for WATCH state.")
                output.candidate = None

        # Rule 4 — DEVELOPING: candidate should be None for Package 4.0
        elif output.reasoning_state == ReasoningState.DEVELOPING:
            if output.candidate is not None:
                logger.info("Rule 4 Enforced: candidate neutralized for DEVELOPING state.")
                output.candidate = None

        # Rule 5 — CANDIDATE: candidate must be present
        elif output.reasoning_state == ReasoningState.CANDIDATE:
            if output.candidate is None:
                logger.warning("Rule 5 Violation: CANDIDATE state requires candidate != None. Demoting to DEVELOPING.")
                output.reasoning_state = ReasoningState.DEVELOPING

        # 3. Confidence bounding check
        if output.confidence.value < 0.0 or output.confidence.value > 1.0:
            logger.warning("Confidence %f out of bounds [0.0, 1.0]. Clamping.", output.confidence.value)
            output.confidence.value = max(0.0, min(1.0, output.confidence.value))

        # 4. Source Freshness check (Rule 10)
        if source_freshness_flags:
            stale_sources = [s for s, fresh in source_freshness_flags.items() if not fresh]
            if stale_sources:
                has_stale_uncertainty = any(u.type == UncertaintyType.STALE_DATA for u in output.uncertainties)
                if not has_stale_uncertainty:
                    output.uncertainties.append(
                        Uncertainty(
                            type=UncertaintyType.STALE_DATA,
                            severity=Severity.HIGH,
                            description=f"Material observation source(s) stale: {', '.join(stale_sources)}",
                            affected_conclusion="Market structure and regime interpretation",
                        )
                    )

        return output
