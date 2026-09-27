"""
Performance Analysis & Experience Memory Service.

Orchestrator for Stage 10:
ANALYZES completed paper trades, reconstructs timelines, performs decoupled reasoning,
execution, and outcome evaluations, extracts evidence-backed lessons, validates memory,
and stores structured experience for future cognitive context.

STRICT INVARIANT:
- Does NOT automatically change strategy, code, prompts, or safety policies.
"""

from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional, Tuple

from nifty_trader.brain.context.context_memory import ContextMemoryItem, ContextMemoryStore
from nifty_trader.experience.contracts import (
    EvidenceQuality,
    ExperienceRecord,
    ExperienceTag,
    Lesson,
    MemoryStatus,
    PerformanceSummary,
)
from nifty_trader.experience.execution_analysis import ExecutionAnalyzer
from nifty_trader.experience.lesson_extractor import LessonExtractor
from nifty_trader.experience.metrics import PerformanceMetricsCalculator
from nifty_trader.experience.outcome_analysis import OutcomeAnalyzer
from nifty_trader.experience.persistence import ExperienceStore
from nifty_trader.experience.reasoning_analysis import ReasoningAnalyzer
from nifty_trader.experience.retrieval import ExperienceRetriever
from nifty_trader.experience.timeline import TimelineBuilder
from nifty_trader.experience.validation import ExperienceValidator
from nifty_trader.monitoring.store import PositionMonitoringStore
from nifty_trader.paper.contracts import PaperPosition, PaperPositionStatus, PaperTradeOrder
from nifty_trader.paper.store import PaperTradeStore

logger = logging.getLogger(__name__)


class PerformanceAnalysisService:
    """
    Unified operational service for performance analysis, lesson extraction,
    and persistent experience memory.
    """

    def __init__(
        self,
        paper_store: PaperTradeStore,
        monitoring_store: Optional[PositionMonitoringStore] = None,
        experience_store: Optional[ExperienceStore] = None,
        context_memory_store: Optional[ContextMemoryStore] = None,
    ):
        self.paper_store = paper_store
        self.monitoring_store = monitoring_store or PositionMonitoringStore()
        self.experience_store = experience_store or ExperienceStore()
        self.context_memory_store = context_memory_store

        self.timeline_builder = TimelineBuilder()
        self.reasoning_analyzer = ReasoningAnalyzer()
        self.execution_analyzer = ExecutionAnalyzer()
        self.outcome_analyzer = OutcomeAnalyzer()
        self.lesson_extractor = LessonExtractor()
        self.validator = ExperienceValidator()
        self.retriever = ExperienceRetriever(self.experience_store)
        self.metrics_calculator = PerformanceMetricsCalculator()

    def analyze_trade(
        self,
        trade_id: str,
        force: bool = False,
    ) -> Tuple[bool, Optional[ExperienceRecord], List[str]]:
        """
        Executes the complete post-trade analysis pipeline for a given trade/position.
        Returns: (success, experience_record, errors_or_warnings)
        """
        # Check if already analyzed unless forced
        existing = self.experience_store.get_experience_by_trade(trade_id)
        if existing and not force:
            logger.info("Trade %s already analyzed as experience %s", trade_id, existing.experience_id)
            return True, existing, ["Already analyzed. Use force=True to re-analyze."]

        # 1. Gather recorded evidence
        order = self.paper_store.get_order(trade_id)
        pos = self.paper_store.get_position(trade_id)

        # Cross lookup if trade_id might be position_id or order_id
        if not pos and order:
            all_positions = self.paper_store.get_all_positions(limit=100)
            pos = next((p for p in all_positions if p.position_id == getattr(order, "position_id", None) or p.strike == order.strike), None)

        if not order and pos:
            recent_orders = self.paper_store.get_recent_orders(limit=50)
            order = next((o for o in recent_orders if getattr(o, "position_id", None) == pos.position_id or o.strike == pos.strike), None)

        if not order and not pos:
            return False, None, [f"No order or position found matching ID '{trade_id}'"]

        pos_id = pos.position_id if pos else None
        monitoring_records = self.monitoring_store.get_records_for_position(pos_id) if pos_id else []
        monitoring_events = self.monitoring_store.get_events_for_position(pos_id) if pos_id else []

        # 2. Reconstruct Chronological Timeline
        timeline = self.timeline_builder.build_timeline(
            order=order,
            position=pos,
            monitoring_records=monitoring_records,
            monitoring_events=monitoring_events,
        )

        # 3. Analyze Decoupled Dimensions
        reasoning = self.reasoning_analyzer.analyze_reasoning(
            order=order,
            position=pos,
            monitoring_records=monitoring_records,
        )

        execution = self.execution_analyzer.analyze_execution(
            order=order,
            position=pos,
        )

        outcome = self.outcome_analyzer.analyze_outcome(
            position=pos,
            monitoring_records=monitoring_records,
            exit_reason=pos.status.value if pos else None,
        )

        # 4. Extract Grounded Lessons
        lessons = self.lesson_extractor.extract_lessons(
            timeline=timeline,
            reasoning=reasoning,
            execution=execution,
            outcome=outcome,
        )

        # 5. Determine Tags
        tags = [ExperienceTag.POSITION_MANAGEMENT.value]
        if reasoning.source_conflicts:
            tags.append(ExperienceTag.SOURCE_CONFLICT.value)
        if "breakout" in (reasoning.original_thesis or "").lower():
            tags.append(ExperienceTag.BREAKOUT.value)
        elif "range" in (reasoning.original_thesis or "").lower():
            tags.append(ExperienceTag.RANGE.value)
        elif "trend" in (reasoning.original_thesis or "").lower():
            tags.append(ExperienceTag.TREND.value)
        else:
            tags.append(ExperienceTag.MARKET_STRUCTURE.value)

        symbol = pos.symbol if pos else (order.symbol if order else "NIFTY")
        strike = pos.strike if pos else (order.strike if order else 0.0)
        option_type = pos.option_type.value if pos else (order.option_type.value if order else "CE")

        summary = (
            f"Trade {trade_id} on {symbol} {strike:.0f} {option_type}: "
            f"Outcome={outcome.outcome.value} (Realized P&L Rs. {outcome.realized_pnl:+,.2f}), "
            f"Reasoning={reasoning.reasoning_outcome.value}, "
            f"Execution={execution.execution_outcome.value}."
        )

        # 6. Assemble ExperienceRecord
        record = ExperienceRecord(
            trade_id=trade_id,
            position_id=pos_id,
            symbol=symbol,
            strike=strike,
            option_type=option_type,
            market_context=f"Recorded trade on {symbol} {strike:.0f} {option_type}",
            original_thesis=reasoning.original_thesis or "Thesis not recorded",
            timeline=timeline,
            reasoning_analysis=reasoning,
            execution_analysis=execution,
            outcome_analysis=outcome,
            lessons=lessons,
            tags=tags,
            evidence_quality=outcome.data_quality,
            summary=summary,
        )

        # 7. Validate Record & Anti-Rule Guard
        is_valid, validated_record, errors = self.validator.validate(record)

        # 8. Persist Record & Emit Lifecycle Event
        self.experience_store.save_experience(validated_record)
        self.experience_store.save_event(
            event_type="trade-analysis-completed",
            experience_id=validated_record.experience_id,
            trade_id=trade_id,
            details={"status": validated_record.memory_status.value, "outcome": outcome.outcome.value, "pnl": outcome.realized_pnl},
        )

        # 9. Sync with ContextMemoryStore if valid and active
        if is_valid and validated_record.memory_status == MemoryStatus.ACTIVE and self.context_memory_store:
            primary_lesson = validated_record.lessons[0].statement if validated_record.lessons else "No explicit lesson."
            mem_item = ContextMemoryItem(
                setup_type=tags[1] if len(tags) > 1 else tags[0],
                timeframe="15M",
                observed_characteristics=f"NIFTY {strike:.0f} {option_type} entry thesis: {validated_record.original_thesis}",
                historical_outcome=f"{outcome.outcome.value} (Rs. {outcome.realized_pnl:+,.2f}, {outcome.pnl_percentage:+.2f}%)",
                lessons=primary_lesson,
                relevance_score=0.8,
                tags=tags,
            )
            self.context_memory_store.add_memory(mem_item)

        return is_valid, validated_record, errors

    def analyze_all_completed_trades(self) -> List[ExperienceRecord]:
        """Scans for all closed paper positions and executes analysis on each."""
        all_positions = self.paper_store.get_all_positions(limit=500)
        closed_positions = [
            p for p in all_positions
            if p.status in [PaperPositionStatus.CLOSED, PaperPositionStatus.EXTERNAL_CLOSED]
        ]

        analyzed: List[ExperienceRecord] = []
        for pos in closed_positions:
            ok, record, _ = self.analyze_trade(pos.position_id, force=False)
            if ok and record:
                analyzed.append(record)

        return analyzed

    def get_performance_summary(self) -> PerformanceSummary:
        """Returns aggregated statistical and operational performance metrics."""
        experiences = self.experience_store.list_experiences(limit=1000)
        return self.metrics_calculator.compute_summary(experiences)

    def find_relevant_experiences(
        self,
        symbol: str = "NIFTY",
        timeframe: Optional[str] = None,
        market_structure: Optional[str] = None,
        tags: Optional[List[str]] = None,
        limit: int = 3,
    ) -> List[ExperienceRecord]:
        """Finds prior relevant experiences matching criteria."""
        return self.retriever.find_relevant_experiences(
            symbol=symbol,
            timeframe=timeframe,
            market_structure=market_structure,
            tags=tags,
            limit=limit,
        )

    def format_for_brain_context(self, experiences: List[ExperienceRecord]) -> str:
        """Formats experiences for AI Brain contextual prompt injection."""
        return self.retriever.format_for_brain_context(experiences)
