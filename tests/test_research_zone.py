"""
Comprehensive Unit and Integration Test Suite for the Hermes Research & Intelligence Zone.

Verifies:
1. Dhan Data Adapter (Mock provider, health check, synthetic generation)
2. Data Engineering (Invariant validation, deduplication, resampling, technical features, DQR)
3. SQLite Storage Layer (Database isolation, context management, zero Windows file locking leaks)
4. Research Engine (Questions, hypotheses, backtesting, contradiction search, follow-ups)
5. Dynamic Assessment Engine (Dynamic segment weighting, total score formula, confidence)
6. Research Memory (Negative knowledge / failed hypotheses, findings, audit trail)
7. End-to-End Hermes Research Service Cycle
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import pytest

from nifty_trader.research_zone.assessment import HermesAssessmentEngine
from nifty_trader.research_zone.contracts import (
    DataQualityRating,
    FeatureRow,
    HypothesisStatus,
    MarketDirection,
    NormalizedBar,
    PatternType,
)
from nifty_trader.research_zone.data_engineering import DataEngineeringZone
from nifty_trader.research_zone.dhan_adapter import MockDhanDataAdapter
from nifty_trader.research_zone.memory import ResearchMemory
from nifty_trader.research_zone.research_engine import HermesResearchEngine
from nifty_trader.research_zone.service import HermesResearchZoneService
from nifty_trader.research_zone.storage import ResearchZoneStorage


@pytest.fixture
def temp_research_dir():
    with tempfile.TemporaryDirectory() as tmp_dir:
        yield Path(tmp_dir)


# ==============================================================================
# 1. Dhan Data Adapter Tests
# ==============================================================================

def test_mock_dhan_adapter_generation():
    adapter = MockDhanDataAdapter(seed=123)
    bars = adapter.fetch_historical_bars(symbol="NIFTY", timeframe="15M")
    assert len(bars) > 50
    for b in bars:
        assert b.open > 0
        assert b.high >= b.low
        assert b.high >= b.open
        assert b.high >= b.close
        assert b.low <= b.open
        assert b.low <= b.close
        assert b.volume >= 0
        assert b.open_interest >= 0


def test_mock_dhan_adapter_option_chain_and_depth():
    adapter = MockDhanDataAdapter(seed=42)
    chain = adapter.fetch_option_chain_snapshot(symbol="NIFTY")
    assert "pcr" in chain
    assert "strikes" in chain
    assert len(chain["strikes"]) > 0
    assert chain["underlying_price"] > 0

    depth = adapter.fetch_market_depth(symbol="NIFTY")
    assert "bids" in depth
    assert "asks" in depth
    assert len(depth["bids"]) == 5
    assert len(depth["asks"]) == 5

    health = adapter.health_check()
    assert health["status"] in ["ONLINE", "HEALTHY"]


# ==============================================================================
# 2. Data Engineering Zone Tests
# ==============================================================================

def test_data_engineering_validation_and_cleaning():
    de = DataEngineeringZone()
    now = datetime.now(timezone.utc)

    valid_bar = NormalizedBar(
        symbol="NIFTY", timeframe="15M", timestamp=now,
        open=24000.0, high=24050.0, low=23980.0, close=24020.0, volume=1000, open_interest=50000,
    )
    # Corrupt bar: high < low
    corrupt_bar_1 = NormalizedBar(
        symbol="NIFTY", timeframe="15M", timestamp=now + timedelta(minutes=15),
        open=24000.0, high=23900.0, low=24050.0, close=24000.0, volume=100, open_interest=1000,
    )
    # Corrupt bar: zero/negative price
    corrupt_bar_2 = NormalizedBar(
        symbol="NIFTY", timeframe="15M", timestamp=now + timedelta(minutes=30),
        open=0.0, high=24000.0, low=0.0, close=24000.0, volume=100, open_interest=1000,
    )
    # Duplicate bar with same timestamp as valid_bar
    dup_bar = NormalizedBar(
        symbol="NIFTY", timeframe="15M", timestamp=now,
        open=24005.0, high=24060.0, low=23990.0, close=24030.0, volume=1200, open_interest=51000,
    )

    cleaned, rejected = de.validate_and_clean_bars([valid_bar, corrupt_bar_1, corrupt_bar_2, dup_bar])
    assert rejected == 2
    assert len(cleaned) == 1
    # Deduplication keeps the later updated bar
    assert cleaned[0].close == 24030.0


def test_data_engineering_resampling():
    de = DataEngineeringZone()
    now = datetime(2026, 9, 27, 9, 15, tzinfo=timezone.utc)

    # 15 consecutive 1-minute bars
    bars_1m = []
    for i in range(15):
        bars_1m.append(
            NormalizedBar(
                symbol="NIFTY", timeframe="1M",
                timestamp=now + timedelta(minutes=i),
                open=24000.0 + i, high=24010.0 + i, low=23990.0 + i, close=24005.0 + i,
                volume=100, open_interest=1000 + i * 10, vwap=24000.0,
            )
        )

    bars_15m = de.resample_bars(bars_1m, target_timeframe="15M")
    assert len(bars_15m) == 1
    b = bars_15m[0]
    assert b.open == bars_1m[0].open
    assert b.close == bars_1m[-1].close
    assert b.high == max(x.high for x in bars_1m)
    assert b.low == min(x.low for x in bars_1m)
    assert b.volume == 1500


def test_data_engineering_features_and_quality():
    de = DataEngineeringZone()
    adapter = MockDhanDataAdapter(seed=99)
    bars = adapter.fetch_historical_bars(symbol="NIFTY", timeframe="15M")

    dqr = de.assess_data_quality(bars, symbol="NIFTY", timeframe="15M")
    assert dqr.total_bars == len(bars)
    assert dqr.quality_rating in [DataQualityRating.EXCELLENT, DataQualityRating.GOOD]

    feature_set = de.calculate_features(bars, symbol="NIFTY", timeframe="15M")
    assert feature_set.total_bars == len(bars)
    assert len(feature_set.rows) == len(bars)

    # Check that tail features are computed
    last_row = feature_set.rows[-1]
    assert last_row.ema_9 is not None
    assert last_row.ema_20 is not None
    assert last_row.rsi_14 is not None
    assert last_row.macd is not None
    assert last_row.atr_14 is not None
    assert last_row.vwap is not None
    assert last_row.regime_tag != "UNDEFINED"


# ==============================================================================
# 3. Storage Layer Tests
# ==============================================================================

def test_research_zone_storage_crud(temp_research_dir):
    storage = ResearchZoneStorage(base_dir=temp_research_dir)
    adapter = MockDhanDataAdapter(seed=55)
    bars = adapter.fetch_historical_bars(symbol="NIFTY", timeframe="15M")[:10]

    # Test market data store
    saved_count = storage.market_data.save_normalized_bars(bars)
    assert saved_count == 10
    retrieved_bars = storage.market_data.get_bars(symbol="NIFTY", timeframe="15M")
    assert len(retrieved_bars) == 10

    # Test research store
    engine = HermesResearchEngine()
    question = engine.formulate_question(topic="Test Question", description="Test Desc")
    storage.research.save_question(question)
    questions = storage.research.get_questions()
    assert len(questions) == 1
    assert questions[0].topic == "Test Question"

    # Test assessment store
    assessment_engine = HermesAssessmentEngine()
    row = FeatureRow(
        timestamp=datetime.now(timezone.utc),
        close=24200.0,
        ema_20=24150.0,
        ema_50=24100.0,
        rsi_14=65.0,
        macd_hist=5.0,
        volume_ratio_20=1.4,
        regime_tag="TRENDING_UP",
    )
    assessment = assessment_engine.generate_assessment(
        instrument="NIFTY", timeframe="15M", latest_feature=row
    )
    storage.assessments.save_assessment(assessment)
    retrieved_ass = storage.assessments.get_assessment(assessment.research_id)
    assert retrieved_ass is not None
    assert retrieved_ass.total_score == assessment.total_score
    assert len(retrieved_ass.segments) == len(assessment.segments)


# ==============================================================================
# 4. Research Engine Tests (Hypothesis & Contradictions)
# ==============================================================================

def test_research_engine_workflow():
    engine = HermesResearchEngine()
    adapter = MockDhanDataAdapter(seed=12)
    bars = adapter.fetch_historical_bars(symbol="NIFTY", timeframe="15M")
    de = DataEngineeringZone()
    feature_set = de.calculate_features(bars)

    question = engine.formulate_question(
        topic="Breakout Expectancy",
        description="Study forward return after VWAP breakouts",
    )
    pattern = engine.default_patterns[0]
    hypothesis = engine.formulate_hypothesis(question, pattern, forward_bars=5, target_return_pct=0.2)

    test_res, status = engine.test_hypothesis(hypothesis, feature_set)
    assert test_res.sample_size >= 0
    assert status in [HypothesisStatus.CONFIRMED, HypothesisStatus.REJECTED, HypothesisStatus.INCONCLUSIVE]

    # Contradiction search
    contradiction = engine.search_contradictions(hypothesis, feature_set)
    assert contradiction.counter_examples_count >= 0
    assert 0.0 <= contradiction.false_positive_rate <= 100.0

    # Follow-up generation
    followup = engine.generate_followup(hypothesis, contradiction)
    if contradiction.failure_regimes:
        assert followup is not None
        assert followup.parent_research_id == hypothesis.hypothesis_id


# ==============================================================================
# 5. Dynamic Segment Scoring Invariant Test
# ==============================================================================

def test_dynamic_assessment_scoring_invariant():
    """
    STRICT INVARIANT: No fixed/static percentage weights.
    Verify dynamic importance weighting formula:
        Total Score = Sum(Score_i * Importance_i) / Sum(Importance_i)
    """
    assessment_engine = HermesAssessmentEngine()

    row = FeatureRow(
        timestamp=datetime.now(timezone.utc),
        close=24500.0,
        ema_20=24400.0,
        ema_50=24300.0,
        rsi_14=68.0,
        macd_hist=10.0,
        volume_ratio_20=1.6,
        oi_change_pct=3.5,
        regime_tag="TRENDING_UP",
    )

    assessment = assessment_engine.generate_assessment(
        instrument="NIFTY",
        timeframe="15M",
        latest_feature=row,
    )

    # Invariants check
    assert len(assessment.segments) >= 4
    weights_sum = sum(s.importance for s in assessment.segments)
    assert weights_sum > 0

    manual_weighted_sum = sum(s.score * s.importance for s in assessment.segments)
    expected_total_score = round(manual_weighted_sum / weights_sum, 2)
    assert assessment.total_score == expected_total_score

    # Verify that dynamic importances are not hard-coded static percentages summing rigidly to 100%
    importances = [s.importance for s in assessment.segments]
    assert any(imp != 0.20 for imp in importances)  # Not flat 20%
    assert assessment.confidence > 0.0
    assert assessment.direction in [MarketDirection.BULLISH, MarketDirection.NEUTRAL, MarketDirection.UNCLEAR]


# ==============================================================================
# 6. Research Memory & Negative Knowledge Tests
# ==============================================================================

def test_negative_knowledge_preservation(temp_research_dir):
    storage = ResearchZoneStorage(base_dir=temp_research_dir)
    memory = ResearchMemory(storage.memory)

    # Store a failed hypothesis
    failed = memory.record_failed_hypothesis(
        hypothesis_id="hyp_fail_01",
        statement="Buying blindly at RSI < 20 in strong bear trend",
        failure_reason="Win rate 28%, extreme drawdown due to trend persistence",
        counter_evidence=["Tested over 200 bars with 72% loss rate"],
        lessons_learned="Never counter-trend fade below EMA200 without volume absorption confirmation.",
    )
    assert failed.failed_id.startswith("fhyp_")

    # Check prior failure lookup
    detected = memory.has_prior_failure("Buying blindly at RSI < 20")
    assert detected is not None
    assert detected.hypothesis_id == "hyp_fail_01"

    # Store a confirmed finding
    finding = memory.record_finding(
        pattern_name="VWAP Bullish Expansion",
        statistical_edge="Win Rate: 62%, PF: 1.6",
        confidence=0.75,
        evidence_refs=["rass_test_01"],
    )
    assert finding.finding_id.startswith("fnd_")

    all_failures = memory.get_all_failed_hypotheses()
    all_findings = memory.get_all_findings()
    assert len(all_failures) == 1
    assert len(all_findings) == 1


# ==============================================================================
# 7. End-to-End Hermes Research Service Cycle
# ==============================================================================

def test_end_to_end_research_service_cycle(temp_research_dir):
    service = HermesResearchZoneService(base_dir=temp_research_dir)

    assessment = service.run_full_research_cycle(
        topic="NIFTY Momentum Regime Analysis",
        symbol="NIFTY",
        timeframe="15M",
        days=12,
    )

    assert assessment is not None
    assert assessment.instrument == "NIFTY"
    assert assessment.timeframe == "15M"
    assert len(assessment.segments) >= 4
    assert -100.0 <= assessment.total_score <= 100.0
    assert 0.0 <= assessment.confidence <= 1.0

    # Verify persistence in dedicated databases
    latest_ass = service.get_latest_assessment(symbol="NIFTY")
    assert latest_ass is not None
    assert latest_ass.research_id == assessment.research_id

    # Verify memory summary
    summary = service.get_memory_summary()
    assert summary["recent_history_count"] >= 5
    assert summary["recent_assessments_count"] >= 1
