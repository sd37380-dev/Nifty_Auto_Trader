"""
Reasoning Analyzer: Evaluates Decision Quality Independent of Market Outcome.

STRICT INVARIANT:
- Never equate PROFIT = GOOD REASONING or LOSS = BAD REASONING.
- Evaluates whether actions were justified by evidence available at that moment.
- Preserves original thesis and hypotheses without post-hoc rewriting.
"""

import logging
from typing import Any, Dict, List, Optional

from nifty_trader.brain.contracts import BrainOutput, TradeCandidate
from nifty_trader.experience.contracts import (
    EvidenceQuality,
    ReasoningAnalysis,
    ReasoningOutcomeCategory,
)
from nifty_trader.monitoring.contracts import PositionMonitoringRecord
from nifty_trader.paper.contracts import PaperPosition, PaperTradeOrder

logger = logging.getLogger(__name__)


class ReasoningAnalyzer:
    """
    Evaluates the cognitive quality, hypothesis consistency, and thesis evolution
    of a trade across its lifecycle.
    """

    def analyze_reasoning(
        self,
        order: Optional[PaperTradeOrder] = None,
        position: Optional[PaperPosition] = None,
        monitoring_records: Optional[List[PositionMonitoringRecord]] = None,
        candidate: Optional[TradeCandidate] = None,
        brain_outputs: Optional[List[BrainOutput]] = None,
    ) -> ReasoningAnalysis:
        """
        Conducts decoupled reasoning analysis on the completed trade.
        """
        # 1. Extract Original Thesis & Hypotheses
        original_thesis = None
        original_hypothesis = None
        original_direction = None
        confirmation_conditions: List[str] = []
        invalidation_conditions: List[str] = []
        uncertainties: List[str] = []
        initial_confidence = 0.5
        evidence_refs: List[str] = []

        if candidate:
            original_thesis = candidate.thesis
            original_direction = candidate.direction.value
            confirmation_conditions = candidate.confirmation_conditions.copy()
            invalidation_conditions = candidate.invalidation_conditions.copy()
            uncertainties = [u.description for u in candidate.uncertainties]
            initial_confidence = candidate.reasoning_confidence.value
            evidence_refs = [ref.observation_id for ref in candidate.supporting_evidence]
        elif order and order.status_reason:
            original_thesis = order.status_reason
            original_direction = order.action.value
            evidence_refs.append(order.order_id)
        elif position:
            original_thesis = f"Position {position.symbol} {position.strike} {position.option_type.value}"
            original_direction = position.action.value
            evidence_refs.append(position.position_id)

        # 2. Analyze Reassessments and Thesis Evolution
        reassessment_count = 0
        thesis_invalidated_by_brain = False
        thesis_confirmed_by_brain = False
        source_conflicts: List[str] = []

        if monitoring_records:
            reassessment_count = len([r for r in monitoring_records if r.brain_position_action is not None])
            for rec in monitoring_records:
                evidence_refs.append(rec.monitoring_id)
                if rec.brain_request_id:
                    evidence_refs.append(rec.brain_request_id)

                summary = (rec.brain_summary or "").lower()
                if "invalidat" in summary or "breach" in summary or "broke lower" in summary or "broke higher" in summary:
                    thesis_invalidated_by_brain = True
                elif "confirmed" in summary or "target reached" in summary or "momentum sustained" in summary:
                    thesis_confirmed_by_brain = True

                if rec.discrepancy_detected:
                    source_conflicts.append(f"Discrepancy at monitoring turn {rec.monitoring_id}: {rec.discrepancy_detected}")

        # 3. Determine Reasoning Outcome Category
        if thesis_invalidated_by_brain:
            reasoning_outcome = ReasoningOutcomeCategory.THESIS_INVALIDATED
            thesis_eval = "Original thesis was invalidated by subsequent price action/structure as correctly identified by the Brain."
        elif thesis_confirmed_by_brain:
            reasoning_outcome = ReasoningOutcomeCategory.THESIS_CONFIRMED
            thesis_eval = "Original thesis played out according to hypothesis."
        elif reassessment_count > 0:
            reasoning_outcome = ReasoningOutcomeCategory.THESIS_PARTIALLY_CONFIRMED
            thesis_eval = "Trade evolved with partial hypothesis development before closure."
        elif original_thesis:
            reasoning_outcome = ReasoningOutcomeCategory.THESIS_REMAINED_UNRESOLVED
            thesis_eval = "Trade was closed before conclusive structural confirmation or invalidation occurred."
        else:
            reasoning_outcome = ReasoningOutcomeCategory.INSUFFICIENT_EVIDENCE
            thesis_eval = "Insufficient recorded reasoning context to evaluate thesis evolution."

        # 4. Determine Evidence Quality
        evidence_quality = EvidenceQuality.COMPLETE
        if not original_thesis:
            evidence_quality = EvidenceQuality.PARTIAL
        if source_conflicts:
            evidence_quality = EvidenceQuality.CONFLICTED

        return ReasoningAnalysis(
            original_hypothesis=original_hypothesis,
            original_thesis=original_thesis,
            original_direction=original_direction,
            confirmation_conditions=confirmation_conditions,
            invalidation_conditions=invalidation_conditions,
            uncertainties=uncertainties,
            initial_confidence=initial_confidence,
            reasoning_outcome=reasoning_outcome,
            thesis_evaluation=thesis_eval,
            reassessment_count=reassessment_count,
            source_conflicts=source_conflicts,
            evidence_quality=evidence_quality,
            evidence_refs=list(dict.fromkeys(evidence_refs)),  # deduplicate preserving order
        )
