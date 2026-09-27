"""
Comprehensive Test Suite for Stage 10: Performance Analysis & Experience Memory.

Validates:
1. Canonical contracts, enums, schema versioning, and structural models.
2. Chronological timeline reconstruction from multi-source evidence and gap detection.
3. Decoupled evaluation:
   - Profitable trade with invalidated reasoning (Lucky profit).
   - Losing trade with confirmed/valid reasoning (Disciplined loss).
4. Execution analysis: slippage calculation, order latency, idempotency, visual validation.
5. Outcome analysis: verified CLOSED vs. unverified/partial trades, MFE, MAE.
6. Lesson extraction: evidence linkage and non-rule formatting.
7. Anti-rule guard: rejection of imperative trading rules (NEVER TRADE, ALWAYS BUY, etc.).
8. Security validation: rejection of credentials/tokens in memory records.
9. SQLite persistence: experience records, lessons, event logs, and query filtering.
10. Experience retrieval: tag/structure matching and non-rule Brain context formatting.
11. Descriptive performance metrics calculation without composite strategy scores.
12. Full PerformanceAnalysisService workflow and NiftyTraderRuntime integration.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest

from nifty_trader.brain.context.context_memory import ContextMemoryStore
from nifty_trader.brain.contracts import (
    Confidence,
    Direction,
    ObservationReference,
    PositionManagementAction,
    Severity,
    TradeCandidate,
    Uncertainty,
    UncertaintyType,
)
from nifty_trader.core.runtime import NiftyTraderRuntime
from nifty_trader.experience.contracts import (
    EXPERIENCE_SCHEMA_VERSION,
    EpistemicStatus,
    EvidenceQuality,
    ExecutionAnalysis,
    ExecutionOutcomeCategory,
    ExperienceRecord,
    ExperienceTag,
    Lesson,
    LessonType,
    MemoryStatus,
    OutcomeAnalysis,
    PerformanceSummary,
    ReasoningAnalysis,
    ReasoningOutcomeCategory,
    TimelineEvent,
    TradeOutcome,
    TradeTimeline,
)
from nifty_trader.experience.execution_analysis import ExecutionAnalyzer
from nifty_trader.experience.lesson_extractor import LessonExtractor, PROHIBITED_RULE_PATTERNS
from nifty_trader.experience.metrics import PerformanceMetricsCalculator
from nifty_trader.experience.outcome_analysis import OutcomeAnalyzer
from nifty_trader.experience.persistence import ExperienceStore
from nifty_trader.experience.reasoning_analysis import ReasoningAnalyzer
from nifty_trader.experience.retrieval import ExperienceRetriever
from nifty_trader.experience.service import PerformanceAnalysisService
from nifty_trader.experience.timeline import TimelineBuilder
from nifty_trader.experience.validation import ExperienceValidator
from nifty_trader.monitoring.contracts import MonitoringState, PositionEvent, PositionMonitoringRecord
from nifty_trader.monitoring.store import PositionMonitoringStore
from nifty_trader.paper.contracts import (
    PaperAction,
    PaperOptionType,
    PaperOrderStatus,
    PaperPosition,
    PaperPositionStatus,
    PaperTradeOrder,
    ReconciliationDiscrepancy,
    SensibullEnvironmentType,
)
from nifty_trader.paper.store import PaperTradeStore


# ==============================================================================
# 1. Contract & Schema Versioning Tests
# ==============================================================================

def test_schema_version_and_enums():
    """Verify Stage 10 schema version and standard taxonomy enums."""
    assert EXPERIENCE_SCHEMA_VERSION == "1.0"
    assert TradeOutcome.PROFITABLE.value == "PROFITABLE"
    assert TradeOutcome.LOSS.value == "LOSS"
    assert ReasoningOutcomeCategory.THESIS_CONFIRMED.value == "THESIS_CONFIRMED"
    assert ReasoningOutcomeCategory.THESIS_INVALIDATED.value == "THESIS_INVALIDATED"
    assert ExecutionOutcomeCategory.EXECUTION_CONFIRMED.value == "EXECUTION_CONFIRMED"
    assert EvidenceQuality.COMPLETE.value == "COMPLETE"
    assert EpistemicStatus.OBSERVED.value == "OBSERVED"
    assert EpistemicStatus.INFERRED.value == "INFERRED"
    assert MemoryStatus.ACTIVE.value == "ACTIVE"
    assert LessonType.REASONING_LESSON.value == "REASONING_LESSON"
    assert ExperienceTag.MARKET_STRUCTURE.value == "MARKET_STRUCTURE"


def test_timeline_event_and_trade_timeline_models():
    """Verify TimelineEvent and TradeTimeline creation and fields."""
    now = datetime.now(timezone.utc)
    evt = TimelineEvent(
        timestamp=now,
        source="BRAIN",
        event_type="SETUP_FORMED",
        description="Bullish hammer confirmed at support",
        details={"strike": 25300.0},
        evidence_refs=["umo_101"],
    )
    assert evt.event_id.startswith("tevt_")
    assert evt.source == "BRAIN"
    assert evt.evidence_refs == ["umo_101"]

    timeline = TradeTimeline(
        trade_id="trade_123",
        events=[evt],
        start_time=now,
        end_time=now + timedelta(minutes=45),
        duration_minutes=45.0,
        has_gaps=False,
    )
    assert timeline.trade_id == "trade_123"
    assert len(timeline.events) == 1
    assert timeline.duration_minutes == 45.0


# ==============================================================================
# 2. Timeline Reconstruction Tests
# ==============================================================================

def test_timeline_reconstruction_and_gap_detection():
    """Verify chronological timeline reconstruction and normal vs excessive gap detection."""
    t0 = datetime(2026, 9, 27, 9, 30, tzinfo=timezone.utc)
    t1 = t0 + timedelta(seconds=15)
    t2 = t0 + timedelta(minutes=15)
    t3 = t0 + timedelta(minutes=90)  # >60 min gap from t2

    order = PaperTradeOrder(
        order_id="ord_test_01",
        request_id="req_test_01",
        symbol="NIFTY",
        expiry="2026-10-01",
        strike=25300.0,
        option_type=PaperOptionType.CE,
        action=PaperAction.BUY,
        lots=1,
        quantity=25,
        submitted_at=t0,
        verified_at=t1,
        status=PaperOrderStatus.FILLED,
        entry_price=121.5,
        idempotency_key="idemp_01",
    )

    pos = PaperPosition(
        position_id="pos_test_01",
        symbol="NIFTY",
        expiry="2026-10-01",
        strike=25300.0,
        option_type=PaperOptionType.CE,
        lots=1,
        quantity=25,
        avg_price=121.5,
        current_ltp=135.0,
        first_detected_at=t1,
        closed_at=t3,
        status=PaperPositionStatus.CLOSED,
        realized_pnl=337.5,
        pnl_percentage=11.1,
    )

    mon_record = PositionMonitoringRecord(
        position_id="pos_test_01",
        timestamp=t2,
        symbol="NIFTY",
        strike=25300.0,
        option_type="CE",
        lots=1,
        quantity=25,
        entry_price=121.5,
        current_price=128.0,
        unrealized_pnl=162.5,
        pnl_percentage=5.3,
        monitoring_state=MonitoringState.MONITORING,
        brain_position_action=PositionManagementAction.WAIT,
        brain_summary="Position moving favorably toward target.",
    )

    builder = TimelineBuilder()
    timeline = builder.build_timeline(
        order=order,
        position=pos,
        monitoring_records=[mon_record],
        max_normal_gap_minutes=60.0,
    )

    assert timeline.trade_id == "ord_test_01"
    assert len(timeline.events) >= 3
    # Check chronological ordering
    timestamps = [e.timestamp for e in timeline.events]
    assert timestamps == sorted(timestamps)

    # Check gap detection: interval from t2 (9:45) to t3 (11:00) is 75 mins > 60 mins
    assert timeline.has_gaps is True
    assert any("Gap of 75.0 mins" in g for g in timeline.gap_descriptions)


# ==============================================================================
# 3. Decoupled Reasoning Analysis Tests (Strict Invariant)
# ==============================================================================

def test_decoupled_reasoning_lucky_profit():
    """
    Test DECOUPLED EVALUATION:
    A profitable trade (P&L > 0) where the original reasoning was invalidated.
    Must NOT mark reasoning as good just because P&L was positive.
    """
    analyzer = ReasoningAnalyzer()

    candidate = TradeCandidate(
        thesis="Breakout above resistance 25,400 with high volume continuation",
        direction=Direction.LONG,
        market_context="Bullish momentum on 1H",
        confirmation_conditions=["Break above 25400", "Volume > 1.5x average"],
        invalidation_conditions=["Fall below 25350", "Bearish divergence on 15M"],
        uncertainties=[Uncertainty(type=UncertaintyType.OTHER, severity=Severity.MEDIUM, description="RBI policy announcement")],
        supporting_evidence=[ObservationReference(observation_id="umo_breakout_01", description="15M breakout candle")],
        reasoning_confidence=Confidence(value=0.7, basis=["Breakout structure"]),
    )

    pos = PaperPosition(
        position_id="pos_lucky",
        symbol="NIFTY",
        expiry="2026-10-01",
        strike=25400.0,
        option_type=PaperOptionType.CE,
        lots=1,
        quantity=25,
        avg_price=100.0,
        current_ltp=110.0,
        status=PaperPositionStatus.CLOSED,
        realized_pnl=250.0,  # PROFITABLE
        pnl_percentage=10.0,
    )

    mon_record = PositionMonitoringRecord(
        position_id="pos_lucky",
        timestamp=datetime.now(timezone.utc),
        symbol="NIFTY",
        strike=25400.0,
        option_type="CE",
        lots=1,
        quantity=25,
        entry_price=100.0,
        current_price=95.0,
        unrealized_pnl=-125.0,
        pnl_percentage=-5.0,
        monitoring_state=MonitoringState.MONITORING,
        brain_position_action=PositionManagementAction.WATCH,
        brain_summary="Price dropped below invalidation level 25350; thesis invalidated but holding momentarily.",
    )

    analysis = analyzer.analyze_reasoning(
        order=None,
        position=pos,
        monitoring_records=[mon_record],
        candidate=candidate,
    )

    assert analysis.original_thesis == candidate.thesis
    assert analysis.original_direction == "LONG"
    assert "Fall below 25350" in analysis.invalidation_conditions
    assert analysis.reasoning_outcome == ReasoningOutcomeCategory.THESIS_INVALIDATED
    assert "invalidated" in analysis.thesis_evaluation.lower()


def test_decoupled_reasoning_disciplined_loss():
    """
    Test DECOUPLED EVALUATION:
    A losing trade (P&L < 0) where reasoning and setup criteria were confirmed.
    Must NOT mark reasoning as bad just because of an adverse loss / stop out.
    """
    analyzer = ReasoningAnalyzer()

    candidate = TradeCandidate(
        thesis="Pullback to 20 EMA in strong 1H bull trend",
        direction=Direction.LONG,
        market_context="Strong trend continuation",
        confirmation_conditions=["Hold above 25300", "Bullish rejection wick"],
        invalidation_conditions=["15M close below 25280"],
        supporting_evidence=[ObservationReference(observation_id="umo_pullback_01", description="EMA bounce")],
        reasoning_confidence=Confidence(value=0.85, basis=["Trend following"]),
    )

    pos = PaperPosition(
        position_id="pos_loss",
        symbol="NIFTY",
        expiry="2026-10-01",
        strike=25300.0,
        option_type=PaperOptionType.CE,
        lots=1,
        quantity=25,
        avg_price=120.0,
        current_ltp=105.0,
        status=PaperPositionStatus.CLOSED,
        realized_pnl=-375.0,  # LOSS
        pnl_percentage=-12.5,
    )

    mon_record = PositionMonitoringRecord(
        position_id="pos_loss",
        timestamp=datetime.now(timezone.utc),
        symbol="NIFTY",
        strike=25300.0,
        option_type="CE",
        lots=1,
        quantity=25,
        entry_price=120.0,
        current_price=124.0,
        unrealized_pnl=100.0,
        pnl_percentage=3.3,
        monitoring_state=MonitoringState.MONITORING,
        brain_position_action=PositionManagementAction.CONTINUE,
        brain_summary="Setup confirmed as expected; holding position according to plan.",
    )

    analysis = analyzer.analyze_reasoning(
        order=None,
        position=pos,
        monitoring_records=[mon_record],
        candidate=candidate,
    )

    assert analysis.reasoning_outcome == ReasoningOutcomeCategory.THESIS_CONFIRMED
    assert "thesis played out" in analysis.thesis_evaluation.lower()


# ==============================================================================
# 4. Execution Analysis Tests
# ==============================================================================

def test_execution_analysis_slippage_and_latency():
    """Verify execution analyzer computes slippage, latency, visual verification, and platform status."""
    t0 = datetime(2026, 9, 27, 10, 0, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 9, 27, 10, 0, 2, 500000, tzinfo=timezone.utc)  # 2.5s duration

    order = PaperTradeOrder(
        order_id="ord_exec_01",
        request_id="req_exec_01",
        symbol="NIFTY",
        expiry="2026-10-01",
        strike=25350.0,
        option_type=PaperOptionType.PE,
        action=PaperAction.BUY,
        lots=2,
        quantity=50,
        submitted_at=t0,
        verified_at=t1,
        status=PaperOrderStatus.FILLED,
        entry_price=81.2,  # 1.2 slippage over 80.0 requested
        idempotency_key="idemp_exec_01",
        post_execution_screenshot="screenshots/exec_01.png",
    )

    pos = PaperPosition(
        position_id="pos_exec_01",
        symbol="NIFTY",
        expiry="2026-10-01",
        strike=25350.0,
        option_type=PaperOptionType.PE,
        lots=2,
        quantity=50,
        avg_price=81.2,
        current_ltp=90.0,
        exit_price=90.0,
        status=PaperPositionStatus.CLOSED,
    )

    discrepancy = ReconciliationDiscrepancy(
        discrepancy_type="PRICE_DIFF",
        local_value="80.0",
        remote_value="81.2",
        resolution_action="ADJUSTED_LOCAL",
    )

    analyzer = ExecutionAnalyzer()
    analysis = analyzer.analyze_execution(
        order=order,
        position=pos,
        discrepancies=[discrepancy],
        requested_entry_price=80.0,
    )

    assert analysis.execution_outcome == ExecutionOutcomeCategory.EXECUTION_CONFIRMED
    assert analysis.entry_requested_price == 80.0
    assert analysis.entry_executed_price == 81.2
    assert analysis.entry_slippage == 1.2
    assert analysis.order_duration_seconds == 2.5
    assert analysis.idempotency_verified is True
    assert analysis.visual_confirmation is True
    assert analysis.sensibull_environment == "VIRTUAL_TRADE"
    assert len(analysis.reconciliation_discrepancies) == 1


# ==============================================================================
# 5. Outcome Analysis Tests
# ==============================================================================

def test_outcome_analysis_closed_vs_open_position():
    """Verify outcome analyzer distinguishes verified closed positions from open/unverified trades."""
    analyzer = OutcomeAnalyzer()

    # 1. Verified CLOSED trade
    t_start = datetime(2026, 9, 27, 9, 30, tzinfo=timezone.utc)
    t_end = t_start + timedelta(minutes=40)

    closed_pos = PaperPosition(
        position_id="pos_cl_01",
        symbol="NIFTY",
        expiry="2026-10-01",
        strike=25400.0,
        option_type=PaperOptionType.CE,
        lots=1,
        quantity=25,
        avg_price=100.0,
        current_ltp=120.0,
        first_detected_at=t_start,
        closed_at=t_end,
        status=PaperPositionStatus.CLOSED,
        realized_pnl=500.0,
        pnl_percentage=20.0,
    )

    mon1 = PositionMonitoringRecord(
        position_id="pos_cl_01",
        timestamp=t_start + timedelta(minutes=15),
        symbol="NIFTY",
        strike=25400.0,
        option_type="CE",
        lots=1,
        quantity=25,
        entry_price=100.0,
        current_price=112.0,
        unrealized_pnl=300.0,
        pnl_percentage=12.0,
    )
    mon2 = PositionMonitoringRecord(
        position_id="pos_cl_01",
        timestamp=t_start + timedelta(minutes=25),
        symbol="NIFTY",
        strike=25400.0,
        option_type="CE",
        lots=1,
        quantity=25,
        entry_price=100.0,
        current_price=96.0,
        unrealized_pnl=-100.0,
        pnl_percentage=-4.0,
    )

    closed_res = analyzer.analyze_outcome(
        position=closed_pos,
        monitoring_records=[mon1, mon2],
        exit_reason="Target achieved",
    )

    assert closed_res.outcome == TradeOutcome.PROFITABLE
    assert closed_res.realized_pnl == 500.0
    assert closed_res.pnl_percentage == 20.0
    assert closed_res.is_verified_pnl is True
    assert closed_res.holding_duration_minutes == 40.0
    assert closed_res.max_favorable_excursion_pnl == 500.0  # Max of (300, -100, 500)
    assert closed_res.max_adverse_excursion_pnl == -100.0   # Min of (300, -100, 500)
    assert closed_res.data_quality == EvidenceQuality.COMPLETE

    # 2. Open / Unverified trade
    open_pos = PaperPosition(
        position_id="pos_op_01",
        symbol="NIFTY",
        expiry="2026-10-01",
        strike=25400.0,
        option_type=PaperOptionType.CE,
        lots=1,
        quantity=25,
        avg_price=100.0,
        current_ltp=100.0,
        first_detected_at=t_start,
        status=PaperPositionStatus.OPEN,
        realized_pnl=0.0,
    )

    open_res = analyzer.analyze_outcome(position=open_pos)
    assert open_res.outcome == TradeOutcome.UNKNOWN
    assert open_res.is_verified_pnl is False
    assert open_res.data_quality == EvidenceQuality.PARTIAL


# ==============================================================================
# 6. Lesson Extraction & Anti-Rule Invariant Tests
# ==============================================================================

def test_lesson_extraction_evidence_linked_non_rules():
    """Verify LessonExtractor extracts evidence-backed, descriptive lessons without imperative rules."""
    extractor = LessonExtractor()

    timeline = TradeTimeline(
        trade_id="trade_lsn_01",
        events=[
            TimelineEvent(
                timestamp=datetime.now(timezone.utc),
                source="SENSIBULL_PAPER",
                event_type="ORDER_FILLED",
                description="Filled order at 105.0",
                evidence_refs=["ord_ref_01"],
            )
        ],
    )

    reasoning = ReasoningAnalysis(
        original_thesis="Momentum continuation above resistance",
        reasoning_outcome=ReasoningOutcomeCategory.THESIS_CONFIRMED,
        thesis_evaluation="Thesis confirmed across monitoring turns",
        evidence_refs=["umo_ref_01"],
    )

    execution = ExecutionAnalysis(
        execution_outcome=ExecutionOutcomeCategory.EXECUTION_CONFIRMED,
        entry_slippage=1.5,
        visual_confirmation=True,
    )

    outcome = OutcomeAnalysis(
        outcome=TradeOutcome.PROFITABLE,
        realized_pnl=450.0,
        pnl_percentage=15.0,
        is_verified_pnl=True,
    )

    lessons = extractor.extract_lessons(timeline, reasoning, execution, outcome)
    assert len(lessons) >= 1

    for lsn in lessons:
        assert len(lsn.evidence_refs) > 0, "Every lesson must have evidence references"
        assert lsn.epistemic_status in [EpistemicStatus.OBSERVED, EpistemicStatus.INFERRED]
        # Verify no prohibited rule patterns
        for pat in PROHIBITED_RULE_PATTERNS:
            assert not any(word in lsn.statement.lower() for word in ["never trade", "always buy", "must sell"]), \
                f"Lesson contains prohibited rule: {lsn.statement}"


# ==============================================================================
# 7. Anti-Rule Guard & Security Validation Pipeline Tests
# ==============================================================================

def test_validator_rejects_imperative_trading_rules():
    """Verify ExperienceValidator rejects lessons containing imperative strategy rules."""
    validator = ExperienceValidator()

    bad_lesson = Lesson(
        lesson_type=LessonType.REASONING_LESSON,
        statement="When price breaks resistance on low volume, NEVER TRADE options under any condition.",
        evidence_refs=["umo_101"],
    )

    good_lesson = Lesson(
        lesson_type=LessonType.EXECUTION_LESSON,
        statement="Observed 1.5 pt slippage on market orders during market open volatility.",
        evidence_refs=["ord_101"],
    )

    timeline = TradeTimeline(trade_id="tr_rule_test")
    record = ExperienceRecord(
        trade_id="tr_rule_test",
        symbol="NIFTY",
        strike=25300.0,
        option_type="CE",
        market_context="Testing anti-rule guard",
        original_thesis="Sample thesis",
        timeline=timeline,
        reasoning_analysis=ReasoningAnalysis(thesis_evaluation="Thesis eval"),
        execution_analysis=ExecutionAnalysis(),
        outcome_analysis=OutcomeAnalysis(outcome=TradeOutcome.PROFITABLE, is_verified_pnl=True),
        lessons=[bad_lesson, good_lesson],
        summary="Summary test",
    )

    is_valid, validated_record, errors = validator.validate(record)

    # Bad lesson must be filtered out
    assert len(validated_record.lessons) == 1
    assert validated_record.lessons[0].statement == good_lesson.statement
    assert any("prohibited imperative rule pattern" in err for err in errors)


def test_validator_rejects_credentials_and_secrets():
    """Verify ExperienceValidator detects and rejects sensitive credentials or secrets."""
    validator = ExperienceValidator()

    timeline = TradeTimeline(trade_id="tr_sec_test")
    record = ExperienceRecord(
        trade_id="tr_sec_test",
        symbol="NIFTY",
        strike=25300.0,
        option_type="CE",
        market_context="Context with bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.token string",
        original_thesis="Sample thesis",
        timeline=timeline,
        reasoning_analysis=ReasoningAnalysis(thesis_evaluation="Thesis eval"),
        execution_analysis=ExecutionAnalysis(),
        outcome_analysis=OutcomeAnalysis(outcome=TradeOutcome.PROFITABLE, is_verified_pnl=True),
        lessons=[
            Lesson(
                lesson_type=LessonType.OBSERVATION_LESSON,
                statement="Verified observation step.",
                evidence_refs=["umo_01"],
            )
        ],
        summary="Summary test",
    )

    is_valid, validated_record, errors = validator.validate(record)
    assert is_valid is False
    assert validated_record.memory_status == MemoryStatus.REJECTED
    assert any("Security violation" in err for err in errors)


# ==============================================================================
# 8. SQLite Persistence Tests
# ==============================================================================

def test_sqlite_persistence_crud_and_events(tmp_path):
    """Verify ExperienceStore saves, retrieves, and filters experience records and events."""
    db_path = tmp_path / "test_experience.db"
    store = ExperienceStore(db_path=db_path)

    timeline = TradeTimeline(trade_id="tr_db_01")
    record = ExperienceRecord(
        trade_id="tr_db_01",
        position_id="pos_db_01",
        symbol="NIFTY",
        strike=25300.0,
        option_type="CE",
        market_context="Uptrend pullback",
        original_thesis="Test DB persistence",
        timeline=timeline,
        reasoning_analysis=ReasoningAnalysis(
            reasoning_outcome=ReasoningOutcomeCategory.THESIS_CONFIRMED,
            thesis_evaluation="Evaluated",
        ),
        execution_analysis=ExecutionAnalysis(
            execution_outcome=ExecutionOutcomeCategory.EXECUTION_CONFIRMED,
        ),
        outcome_analysis=OutcomeAnalysis(
            outcome=TradeOutcome.PROFITABLE,
            realized_pnl=750.0,
            is_verified_pnl=True,
        ),
        lessons=[
            Lesson(
                lesson_type=LessonType.POSITION_MANAGEMENT_LESSON,
                statement="Trailing stop preserved unrealized gains.",
                evidence_refs=["mon_db_01"],
                is_validated=True,
            )
        ],
        tags=[ExperienceTag.TREND.value, ExperienceTag.POSITION_MANAGEMENT.value],
        memory_status=MemoryStatus.ACTIVE,
        summary="DB test summary",
    )

    # 1. Save and Retrieve Experience Record
    store.save_experience(record)

    fetched = store.get_experience(record.experience_id)
    assert fetched is not None
    assert fetched.trade_id == "tr_db_01"
    assert fetched.strike == 25300.0
    assert fetched.outcome_analysis.realized_pnl == 750.0
    assert len(fetched.lessons) == 1
    assert fetched.lessons[0].statement == "Trailing stop preserved unrealized gains."

    # 2. Lookup by trade_id
    by_trade = store.get_experience_by_trade("tr_db_01")
    assert by_trade is not None
    assert by_trade.experience_id == record.experience_id

    # 3. List with Tag Filter
    trend_records = store.list_experiences(tag=ExperienceTag.TREND.value)
    assert len(trend_records) == 1
    range_records = store.list_experiences(tag=ExperienceTag.RANGE.value)
    assert len(range_records) == 0

    # 4. Save and List Events
    store.save_event(
        event_type="trade-analyzed",
        experience_id=record.experience_id,
        trade_id="tr_db_01",
        details={"status": "SUCCESS"},
    )
    events = store.list_events(experience_id=record.experience_id)
    assert len(events) == 1
    assert events[0]["event_type"] == "trade-analyzed"


# ==============================================================================
# 9. Retrieval & AI Brain Context Formatting Tests
# ==============================================================================

def test_retriever_and_brain_context_formatting(tmp_path):
    """Verify ExperienceRetriever retrieves relevant memories and formats non-rule context for Brain."""
    db_path = tmp_path / "test_retrieval.db"
    store = ExperienceStore(db_path=db_path)

    # Insert 2 active records
    r1 = ExperienceRecord(
        trade_id="tr_ret_01",
        symbol="NIFTY",
        strike=25400.0,
        option_type="CE",
        market_context="Morning breakout",
        original_thesis="Breakout above previous day high",
        timeline=TradeTimeline(trade_id="tr_ret_01"),
        reasoning_analysis=ReasoningAnalysis(
            reasoning_outcome=ReasoningOutcomeCategory.THESIS_CONFIRMED,
            thesis_evaluation="Confirmed",
        ),
        execution_analysis=ExecutionAnalysis(),
        outcome_analysis=OutcomeAnalysis(
            outcome=TradeOutcome.PROFITABLE,
            realized_pnl=600.0,
            is_verified_pnl=True,
        ),
        lessons=[
            Lesson(
                lesson_type=LessonType.REASONING_LESSON,
                statement="Breakout accompanied by 15M volume expansion exhibited sustained follow-through.",
                evidence_refs=["umo_01"],
                is_validated=True,
            )
        ],
        tags=[ExperienceTag.BREAKOUT.value, ExperienceTag.TREND.value],
        memory_status=MemoryStatus.ACTIVE,
        summary="Breakout success summary",
    )
    store.save_experience(r1)

    retriever = ExperienceRetriever(store)
    relevant = retriever.find_relevant_experiences(symbol="NIFTY", tags=[ExperienceTag.BREAKOUT.value])
    assert len(relevant) == 1
    assert relevant[0].trade_id == "tr_ret_01"

    # Format for Brain
    context_str = retriever.format_for_brain_context(relevant)
    assert "HISTORICAL EXPERIENCE MEMORY" in context_str
    assert "NIFTY 25400 CE" in context_str
    assert "PROFITABLE" in context_str
    assert "Breakout accompanied by 15M volume expansion" in context_str
    # Verify strict non-rule guidance is rendered
    assert "NEVER be treated as hard-coded trading rules" in context_str


# ==============================================================================
# 10. Performance Metrics Calculator Tests
# ==============================================================================

def test_performance_metrics_calculator():
    """Verify descriptive statistics calculation without composite scores."""
    calc = PerformanceMetricsCalculator()

    # Create 3 records: 2 profitable, 1 loss
    def make_record(trade_id: str, pnl: float, duration: float, reassessments: int) -> ExperienceRecord:
        outcome = TradeOutcome.PROFITABLE if pnl > 0 else (TradeOutcome.LOSS if pnl < 0 else TradeOutcome.BREAKEVEN)
        return ExperienceRecord(
            trade_id=trade_id,
            symbol="NIFTY",
            strike=25300.0,
            option_type="CE",
            market_context="Context",
            original_thesis="Thesis",
            timeline=TradeTimeline(trade_id=trade_id, duration_minutes=duration),
            reasoning_analysis=ReasoningAnalysis(
                reassessment_count=reassessments,
                thesis_evaluation="Eval",
            ),
            execution_analysis=ExecutionAnalysis(),
            outcome_analysis=OutcomeAnalysis(
                outcome=outcome,
                realized_pnl=pnl,
                holding_duration_minutes=duration,
                is_verified_pnl=True,
            ),
            summary="Summary",
        )

    records = [
        make_record("t1", 1000.0, 30.0, 2),
        make_record("t2", 500.0, 20.0, 1),
        make_record("t3", -500.0, 40.0, 3),
    ]

    summary = calc.compute_summary(records)

    assert summary.total_completed_trades == 3
    assert summary.verified_trades_count == 3
    assert summary.profitable_trades == 2
    assert summary.loss_trades == 1
    assert round(summary.win_rate_pct, 1) == 66.7
    assert summary.total_realized_pnl == 1000.0
    assert summary.avg_pnl == pytest.approx(333.33, rel=1e-2)
    assert summary.largest_gain == 1000.0
    assert summary.largest_loss == -500.0
    assert summary.profit_factor == 3.0  # 1500 / 500
    assert summary.avg_duration_minutes == 30.0
    assert summary.total_reassessments == 6
    assert summary.avg_reassessments_per_trade == 2.0


# ==============================================================================
# 11. End-to-End Service & Runtime Integration Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_end_to_end_service_and_context_memory_sync(tmp_path):
    """Verify PerformanceAnalysisService completes the full pipeline and syncs with ContextMemoryStore."""
    paper_store = PaperTradeStore(db_path=tmp_path / "paper.db")
    monitoring_store = PositionMonitoringStore(db_path=tmp_path / "mon.db")
    exp_store = ExperienceStore(db_path=tmp_path / "exp.db")
    context_mem = ContextMemoryStore(storage_path=tmp_path / "context_memory.json")

    service = PerformanceAnalysisService(
        paper_store=paper_store,
        monitoring_store=monitoring_store,
        experience_store=exp_store,
        context_memory_store=context_mem,
    )

    # Setup recorded closed position in paper store
    t0 = datetime.now(timezone.utc) - timedelta(minutes=45)
    t1 = datetime.now(timezone.utc)

    pos = PaperPosition(
        position_id="pos_e2e_01",
        symbol="NIFTY",
        expiry="2026-10-01",
        strike=25350.0,
        option_type=PaperOptionType.CE,
        lots=1,
        quantity=25,
        avg_price=110.0,
        current_ltp=125.0,
        exit_price=125.0,
        first_detected_at=t0,
        closed_at=t1,
        status=PaperPositionStatus.CLOSED,
        realized_pnl=375.0,
        pnl_percentage=13.6,
    )
    paper_store.save_position(pos)

    order = PaperTradeOrder(
        order_id="ord_e2e_01",
        request_id="req_e2e_01",
        symbol="NIFTY",
        expiry="2026-10-01",
        strike=25350.0,
        option_type=PaperOptionType.CE,
        action=PaperAction.BUY,
        lots=1,
        quantity=25,
        submitted_at=t0,
        verified_at=t0 + timedelta(seconds=2),
        status=PaperOrderStatus.FILLED,
        entry_price=110.0,
        idempotency_key="idemp_e2e_01",
        status_reason="Breakout continuation thesis confirmed",
    )
    paper_store.save_order(order)

    # Execute analysis
    success, record, errors = service.analyze_trade("pos_e2e_01")
    assert success is True
    assert record is not None
    assert record.outcome_analysis.outcome == TradeOutcome.PROFITABLE
    assert record.outcome_analysis.realized_pnl == 375.0
    assert record.memory_status == MemoryStatus.ACTIVE

    # Verify ContextMemoryStore was synced
    active_memories = context_mem.query_relevant(limit=10)
    assert len(active_memories) >= 1
    assert any("25350" in m.observed_characteristics for m in active_memories)

    # Test idempotency (re-analyzing without force returns existing)
    ok2, rec2, notes2 = service.analyze_trade("pos_e2e_01", force=False)
    assert ok2 is True
    assert rec2.experience_id == record.experience_id
    assert "Already analyzed" in notes2[0]


@pytest.mark.asyncio
async def test_runtime_experience_status_reporting():
    """Verify NiftyTraderRuntime initializes experience components and reports status."""
    runtime = NiftyTraderRuntime()
    assert hasattr(runtime, "experience_store")
    assert hasattr(runtime, "experience_service")

    status = await runtime.get_status()
    assert "experience" in status
    assert "total_experiences" in status["experience"]
    assert isinstance(status["experience"]["total_experiences"], int)
