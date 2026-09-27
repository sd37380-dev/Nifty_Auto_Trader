"""
Descriptive Performance & Operational Metrics Calculator.

STRICT INVARIANTS:
1. Calculates descriptive statistics strictly from verified completed trades.
2. Unverified or incomplete trades are segregated and not falsified.
3. No overall composite strategy scores or Brain scores.
"""

from datetime import datetime, timezone
import logging
import statistics
from typing import List

from nifty_trader.experience.contracts import (
    ExperienceRecord,
    PerformanceSummary,
    TradeOutcome,
)

logger = logging.getLogger(__name__)


class PerformanceMetricsCalculator:
    """
    Computes statistical and operational summaries from historical experience records.
    """

    def compute_summary(self, experiences: List[ExperienceRecord]) -> PerformanceSummary:
        """
        Aggregates verified economic, cognitive, and operational performance metrics.
        """
        if not experiences:
            return PerformanceSummary()

        total_trades = len(experiences)
        verified_exps = [e for e in experiences if e.outcome_analysis.is_verified_pnl]
        unverified_count = total_trades - len(verified_exps)

        pnls = [e.outcome_analysis.realized_pnl for e in verified_exps]
        durations = [e.outcome_analysis.holding_duration_minutes for e in verified_exps]

        profitable = len([p for p in pnls if p > 0])
        losses = len([p for p in pnls if p < 0])
        breakevens = len([p for p in pnls if p == 0])

        win_rate = (profitable / len(pnls) * 100.0) if pnls else 0.0
        total_pnl = sum(pnls)
        avg_pnl = statistics.mean(pnls) if pnls else 0.0
        median_pnl = statistics.median(pnls) if pnls else 0.0
        largest_gain = max(pnls) if pnls else 0.0
        largest_loss = min(pnls) if pnls else 0.0

        # Maximum Drawdown calculation from cumulative P&L series
        max_drawdown = 0.0
        peak = 0.0
        cumulative = 0.0
        for p in pnls:
            cumulative += p
            if cumulative > peak:
                peak = cumulative
            dd = peak - cumulative
            if dd > max_drawdown:
                max_drawdown = dd

        # Profit Factor
        gross_profit = sum(p for p in pnls if p > 0)
        gross_loss = abs(sum(p for p in pnls if p < 0))
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (gross_profit if gross_profit > 0 else 0.0)

        avg_duration = statistics.mean(durations) if durations else 0.0

        # Operational & Cognitive Metrics
        total_reassessments = sum(e.reasoning_analysis.reassessment_count for e in experiences)
        avg_reassessments = (total_reassessments / total_trades) if total_trades else 0.0
        wait_freq = sum(1 for e in experiences for evt in e.timeline.events if "WAIT" in evt.event_type)
        source_conflicts = sum(len(e.reasoning_analysis.source_conflicts) for e in experiences)
        reconcil_events = sum(len(e.execution_analysis.reconciliation_discrepancies) for e in experiences)
        exec_failures = sum(1 for e in experiences if e.execution_analysis.execution_outcome.value == "EXECUTION_FAILED")

        return PerformanceSummary(
            total_completed_trades=total_trades,
            verified_trades_count=len(verified_exps),
            unverified_trades_count=unverified_count,
            profitable_trades=profitable,
            loss_trades=losses,
            breakeven_trades=breakevens,
            win_rate_pct=round(win_rate, 2),
            total_realized_pnl=round(total_pnl, 2),
            avg_pnl=round(avg_pnl, 2),
            median_pnl=round(median_pnl, 2),
            largest_gain=round(largest_gain, 2),
            largest_loss=round(largest_loss, 2),
            max_drawdown=round(max_drawdown, 2),
            profit_factor=round(profit_factor, 2),
            avg_duration_minutes=round(avg_duration, 1),
            total_reassessments=total_reassessments,
            avg_reassessments_per_trade=round(avg_reassessments, 1),
            wait_frequency=wait_freq,
            source_conflicts_encountered=source_conflicts,
            brain_failures_encountered=0,
            execution_failures_encountered=exec_failures,
            reconciliation_events_encountered=reconcil_events,
            generated_at=datetime.now(timezone.utc),
        )
