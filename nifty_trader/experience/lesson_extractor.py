"""
Lesson Extractor: Derives Grounded, Evidence-Linked Takeaways from Trade Lifecycle.

STRICT INVARIANT:
- Every lesson MUST cite explicit supporting evidence references.
- Lessons are purely descriptive historical experiences, NEVER imperative trading rules.
- Prohibits commands such as "ALWAYS", "NEVER TRADE", "MUST BUY", "MUST SELL".
"""

import logging
import re
from typing import List, Optional

from nifty_trader.experience.contracts import (
    EpistemicStatus,
    ExecutionAnalysis,
    Lesson,
    LessonType,
    OutcomeAnalysis,
    ReasoningAnalysis,
    ReasoningOutcomeCategory,
    TradeOutcome,
    TradeTimeline,
)

logger = logging.getLogger(__name__)

# Patterns that indicate an attempt to formulate an imperative trading rule
PROHIBITED_RULE_PATTERNS = [
    r"\bnever\s+trade\b",
    r"\balways\s+buy\b",
    r"\balways\s+sell\b",
    r"\bmust\s+buy\b",
    r"\bmust\s+sell\b",
    r"\bif\s+.*then\s+never\b",
    r"\bif\s+.*then\s+always\b",
    r"\bstop\s+trading\s+forever\b",
]


class LessonExtractor:
    """
    Extracts structured, evidence-backed lessons from decoupled trade analyses.
    """

    def extract_lessons(
        self,
        timeline: TradeTimeline,
        reasoning: ReasoningAnalysis,
        execution: ExecutionAnalysis,
        outcome: OutcomeAnalysis,
    ) -> List[Lesson]:
        """
        Extracts candidate lessons grounded in verified evidence.
        """
        lessons: List[Lesson] = []

        # 1. Reasoning & Thesis Evolution Lesson
        if reasoning.original_thesis:
            r_refs = reasoning.evidence_refs.copy()
            if reasoning.reasoning_outcome == ReasoningOutcomeCategory.THESIS_INVALIDATED:
                statement = (
                    f"The original thesis ('{reasoning.original_thesis}') was invalidated during trade evolution "
                    f"as market structure shifted, prompting an autonomous square-off."
                )
            elif reasoning.reasoning_outcome == ReasoningOutcomeCategory.THESIS_CONFIRMED:
                statement = (
                    f"The original thesis ('{reasoning.original_thesis}') was confirmed by structural continuation."
                )
            elif reasoning.reasoning_outcome == ReasoningOutcomeCategory.THESIS_PARTIALLY_CONFIRMED:
                statement = (
                    f"The original thesis ('{reasoning.original_thesis}') achieved partial continuation before "
                    f"momentum stalled across subsequent 15M candles."
                )
            else:
                statement = (
                    f"The thesis ('{reasoning.original_thesis}') remained unresolved at time of exit."
                )

            if self._is_valid_lesson_statement(statement):
                lessons.append(Lesson(
                    lesson_type=LessonType.REASONING_LESSON,
                    statement=statement,
                    epistemic_status=EpistemicStatus.INFERRED,
                    evidence_refs=r_refs,
                    confidence=0.85,
                    is_validated=bool(r_refs),
                ))

        # 2. Execution & Slippage Lesson
        if execution.entry_slippage != 0.0 or execution.order_duration_seconds > 0.0:
            exec_refs = [timeline.trade_id]
            slip_text = f"slippage of Rs. {execution.entry_slippage:+.2f}" if execution.entry_slippage != 0.0 else "zero slippage"
            dur_text = f"within {execution.order_duration_seconds:.1f}s"
            statement = (
                f"Virtual paper execution was confirmed {dur_text} with {slip_text} "
                f"in environment '{execution.sensibull_environment}'."
            )
            if self._is_valid_lesson_statement(statement):
                lessons.append(Lesson(
                    lesson_type=LessonType.EXECUTION_LESSON,
                    statement=statement,
                    epistemic_status=EpistemicStatus.OBSERVED,
                    evidence_refs=exec_refs,
                    confidence=0.95,
                    is_validated=True,
                ))

        # 3. Position Management / Waiting Lesson
        if reasoning.reassessment_count > 0:
            mgmt_refs = [e.event_id for e in timeline.events if "MONITOR" in e.event_type]
            statement = (
                f"Position was actively monitored across {reasoning.reassessment_count} cognitive reassessment pass(es) "
                f"over a total duration of {outcome.holding_duration_minutes:.1f} minutes."
            )
            if self._is_valid_lesson_statement(statement):
                lessons.append(Lesson(
                    lesson_type=LessonType.POSITION_MANAGEMENT_LESSON,
                    statement=statement,
                    epistemic_status=EpistemicStatus.OBSERVED,
                    evidence_refs=mgmt_refs,
                    confidence=0.9,
                    is_validated=bool(mgmt_refs),
                ))

        # 4. Source Conflict Lesson (if observed)
        if reasoning.source_conflicts:
            conflict_refs = [timeline.trade_id]
            statement = (
                f"Source divergence was documented during holding: {'; '.join(reasoning.source_conflicts)}. "
                "Preserved as an important contextual divergence rather than forced harmonization."
            )
            if self._is_valid_lesson_statement(statement):
                lessons.append(Lesson(
                    lesson_type=LessonType.SOURCE_CONFLICT_LESSON,
                    statement=statement,
                    epistemic_status=EpistemicStatus.OBSERVED,
                    evidence_refs=conflict_refs,
                    confidence=0.9,
                    is_validated=True,
                ))

        # 5. Outcome & Excursion Lesson
        if outcome.is_verified_pnl:
            out_refs = [timeline.trade_id]
            statement = (
                f"Trade concluded with outcome {outcome.outcome.value} (Realized P&L: Rs. {outcome.realized_pnl:+,.2f}, "
                f"MFE: Rs. {outcome.max_favorable_excursion_pnl:+,.2f}, MAE: Rs. {outcome.max_adverse_excursion_pnl:+,.2f}). "
                "Outcome is recorded as economic fact without invalidating the procedural rigor of the reasoning."
            )
            if self._is_valid_lesson_statement(statement):
                lessons.append(Lesson(
                    lesson_type=LessonType.OBSERVATION_LESSON,
                    statement=statement,
                    epistemic_status=EpistemicStatus.OBSERVED,
                    evidence_refs=out_refs,
                    confidence=1.0,
                    is_validated=True,
                ))

        return lessons

    def _is_valid_lesson_statement(self, statement: str) -> bool:
        """Enforces that no impermissible rule commands exist in the lesson text."""
        statement_lower = statement.lower()
        for pat in PROHIBITED_RULE_PATTERNS:
            if re.search(pat, statement_lower):
                logger.warning("Rejected lesson containing prohibited rule pattern '%s': %s", pat, statement)
                return False
        return True
