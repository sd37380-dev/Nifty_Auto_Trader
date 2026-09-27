"""
Experience Retrieval & Context Memory Bridge for the AI Trading Brain.

STRICT INVARIANTS:
1. Context memory is evidence/context, NEVER an instruction or trading rule.
2. Contradictory experiences are preserved independently without artificial suppression.
3. Every memory injection is explicitly tagged with non-rule disclaimers.
4. Distinguishes current observations from historical memory.
"""

import logging
from typing import List, Optional

from nifty_trader.experience.contracts import (
    ExperienceRecord,
    MemoryStatus,
    ReasoningOutcomeCategory,
)
from nifty_trader.experience.persistence import ExperienceStore

logger = logging.getLogger(__name__)


class ExperienceRetriever:
    """
    Retrieves and formats relevant historical experiences for Hermes and AI Brain context.
    """

    def __init__(self, store: ExperienceStore):
        self.store = store

    def find_relevant_experiences(
        self,
        symbol: str = "NIFTY",
        timeframe: Optional[str] = None,
        market_structure: Optional[str] = None,
        tags: Optional[List[str]] = None,
        limit: int = 3,
    ) -> List[ExperienceRecord]:
        """
        Retrieves top relevant active experiences matching market conditions.
        Preserves conflicting/contradictory experiences independently.
        """
        # Fetch active experiences
        candidates = self.store.list_experiences(limit=100, status=MemoryStatus.ACTIVE)

        if not candidates:
            # Fallback to validated if active is empty
            candidates = self.store.list_experiences(limit=100, status=MemoryStatus.VALIDATED)

        scored: List[tuple[float, ExperienceRecord]] = []
        target_tags = set(t.upper() for t in (tags or []))
        if market_structure:
            target_tags.add(market_structure.upper())

        for exp in candidates:
            if exp.symbol != symbol:
                continue

            score = 1.0
            exp_tags = set(t.upper() for t in exp.tags)

            # Match tags
            if target_tags:
                matched_tags = target_tags.intersection(exp_tags)
                score += len(matched_tags) * 2.0

            # Match timeframe
            if timeframe and timeframe.upper() in [t.upper() for t in exp.tags]:
                score += 1.5

            # Recent experience boost
            recency_days = (exp.created_at.date() - exp.created_at.date()).days
            score += max(0.0, 1.0 - (recency_days / 30.0))

            scored.append((score, exp))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [item[1] for item in scored[:limit]]

    def format_for_brain_context(self, experiences: List[ExperienceRecord]) -> str:
        """
        Formats retrieved experiences with explicit non-rule warning banners.
        """
        if not experiences:
            return "No historical experience records matching current setup."

        header = (
            "### HISTORICAL EXPERIENCE MEMORY (NON-DETERMINISTIC CONTEXT - EVIDENCE ONLY, NOT RULES)\n"
            "> [!NOTE] The following verified past paper-trade experiences are provided as descriptive historical pattern context. "
            "They must NEVER be treated as hard-coded trading rules, triggers, or orders. You remain free to reason independently.\n\n"
        )

        entries = []
        for i, exp in enumerate(experiences, start=1):
            lessons_text = "\n".join(f"      - {l.statement} [Evidence: {', '.join(l.evidence_refs)}]" for l in exp.lessons) if exp.lessons else "      - None recorded."
            entries.append(
                f"{i}. [Experience ID: {exp.experience_id}] (Trade: {exp.trade_id}, Sample Size: {exp.similar_experience_count})\n"
                f"   * Instrument: {exp.symbol} {exp.strike:.0f} {exp.option_type}\n"
                f"   * Original Thesis: {exp.original_thesis}\n"
                f"   * Reasoning Outcome: {exp.reasoning_analysis.reasoning_outcome.value} ({exp.reasoning_analysis.thesis_evaluation})\n"
                f"   * Economic Outcome: {exp.outcome_analysis.outcome.value} (Realized P&L: Rs. {exp.outcome_analysis.realized_pnl:+,.2f}, Return: {exp.outcome_analysis.pnl_percentage:+.2f}%)\n"
                f"   * Duration: {exp.outcome_analysis.holding_duration_minutes:.1f} mins\n"
                f"   * Tags: {', '.join(exp.tags) if exp.tags else 'None'}\n"
                f"   * Validated Lessons:\n{lessons_text}"
            )

        return header + "\n\n".join(entries)
