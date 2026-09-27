"""
Outcome Analyzer: Evaluates Verified Economic Results from Sensibull Ground Truth.

STRICT INVARIANT:
- Only confirmed CLOSED positions receive final outcome conclusions.
- Unknown/unverified outcomes remain explicitly UNKNOWN.
"""

import logging
from typing import List, Optional

from nifty_trader.experience.contracts import (
    EvidenceQuality,
    OutcomeAnalysis,
    TradeOutcome,
)
from nifty_trader.monitoring.contracts import PositionMonitoringRecord
from nifty_trader.paper.contracts import PaperPosition, PaperPositionStatus

logger = logging.getLogger(__name__)


class OutcomeAnalyzer:
    """
    Evaluates verified economic results, holding duration, and excursion telemetry.
    """

    def analyze_outcome(
        self,
        position: Optional[PaperPosition] = None,
        monitoring_records: Optional[List[PositionMonitoringRecord]] = None,
        exit_reason: Optional[str] = None,
    ) -> OutcomeAnalysis:
        """
        Analyzes economic outcome and excursion metrics.
        """
        if not position:
            return OutcomeAnalysis(
                outcome=TradeOutcome.UNKNOWN,
                realized_pnl=0.0,
                pnl_percentage=0.0,
                holding_duration_minutes=0.0,
                exit_reason="No position record provided",
                is_verified_pnl=False,
                data_quality=EvidenceQuality.INSUFFICIENT,
            )

        # Check if position is confirmed CLOSED
        is_closed = position.status in [PaperPositionStatus.CLOSED, PaperPositionStatus.EXTERNAL_CLOSED]
        realized_pnl = position.realized_pnl if is_closed else 0.0
        pnl_pct = position.pnl_percentage if is_closed else 0.0

        # Holding duration
        duration_mins = 0.0
        if position.first_detected_at:
            end_ts = position.closed_at or position.updated_at
            if end_ts:
                duration_mins = max(0.0, (end_ts - position.first_detected_at).total_seconds() / 60.0)

        # Compute MFE and MAE from monitoring history
        mfe = realized_pnl
        mae = realized_pnl
        if monitoring_records:
            pnls = [r.unrealized_pnl for r in monitoring_records]
            if pnls:
                mfe = max(max(pnls), realized_pnl)
                mae = min(min(pnls), realized_pnl)

        # Classify economic outcome
        if not is_closed:
            outcome = TradeOutcome.UNKNOWN
            data_quality = EvidenceQuality.PARTIAL
            final_reason = "Position still open or unverified closure."
        else:
            if realized_pnl > 0.0:
                outcome = TradeOutcome.PROFITABLE
            elif realized_pnl < 0.0:
                outcome = TradeOutcome.LOSS
            else:
                outcome = TradeOutcome.BREAKEVEN
            data_quality = EvidenceQuality.COMPLETE
            final_reason = exit_reason or "Normal position square-off"

        return OutcomeAnalysis(
            outcome=outcome,
            realized_pnl=round(realized_pnl, 2),
            pnl_percentage=round(pnl_pct, 2),
            max_favorable_excursion_pnl=round(mfe, 2),
            max_adverse_excursion_pnl=round(mae, 2),
            holding_duration_minutes=round(duration_mins, 1),
            exit_reason=final_reason,
            is_verified_pnl=is_closed,
            data_quality=data_quality,
        )
