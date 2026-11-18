"""
Unified Service Layer for the Hermes Research & Intelligence Zone.

Coordinates:
1. Dhan Data Adapter (Mock or future live broker)
2. Data Engineering Pipeline (Validation, Cleaning, Resampling, Feature Set)
3. Research Engine (Questions, Hypotheses, Testing, Contradictions, Follow-ups)
4. Assessment Engine (Dynamic Segment Weights & Total Score)
5. Research Memory & Isolated Databases
"""

from datetime import datetime, timedelta, timezone
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from nifty_trader.research_zone.assessment import HermesAssessmentEngine
from nifty_trader.research_zone.contracts import (
    DataQualityReport,
    FeatureSet,
    HermesResearchAssessment,
    HypothesisStatus,
    PatternDefinition,
    ResearchQuestion,
)
from nifty_trader.research_zone.data_engineering import DataEngineeringZone
from nifty_trader.research_zone.dhan_adapter import (
    DhanDataAdapter,
    MockDhanDataAdapter,
    create_dhan_adapter,
)
from nifty_trader.research_zone.memory import ResearchMemory
from nifty_trader.research_zone.research_engine import HermesResearchEngine
from nifty_trader.research_zone.storage import ResearchZoneStorage

logger = logging.getLogger(__name__)


class HermesResearchZoneService:
    """
    Master coordinator for the isolated Research & Intelligence Zone.
    Completely isolated from live/paper trading execution loops.
    """

    def __init__(
        self,
        base_dir: Optional[Path] = None,
        adapter: Optional[DhanDataAdapter] = None,
    ):
        self.storage = ResearchZoneStorage(base_dir=base_dir)
        self.adapter = adapter or create_dhan_adapter()
        self.data_engineering = DataEngineeringZone()
        self.research_engine = HermesResearchEngine()
        self.assessment_engine = HermesAssessmentEngine()
        self.memory = ResearchMemory(self.storage.memory)

    def run_full_research_cycle(
        self,
        topic: str = "NIFTY Momentum & Volatility Breakout Study",
        symbol: str = "NIFTY",
        timeframe: str = "15M",
        days: int = 15,
        pattern_id: Optional[str] = None,
    ) -> HermesResearchAssessment:
        """
        Executes the end-to-end cognitive research loop:
        Question -> Data Prep -> Pattern Discovery -> Hypothesis Test ->
        Contradiction Search -> Follow-up -> Dynamic Assessment -> Memory Update.
        """
        logger.info("Initiating autonomous research cycle: '%s' for %s %s", topic, symbol, timeframe)

        # ------------------------------------------------------------------
        # 1. Question Formulation ("What data do I need?")
        # ------------------------------------------------------------------
        question = self.research_engine.formulate_question(
            topic=topic,
            description=f"Empirical study of market structure and momentum patterns for {symbol} on {timeframe}.",
            target_symbol=symbol,
            target_timeframe=timeframe,
            parameters={"days": days},
        )
        self.storage.research.save_question(question)
        research_id = question.question_id

        self.memory.log_stage_progression(
            research_id=research_id,
            stage="QUESTION_FORMULATION",
            summary=f"Formulated research question: {question.topic}",
            details={"parameters": question.parameters},
        )

        # ------------------------------------------------------------------
        # 2. Dataset Preparation (Data Engineering Zone)
        # ------------------------------------------------------------------
        now = datetime.now(timezone.utc)
        from_date = now - timedelta(days=days)
        
        # 1. Load existing historical bars from local SQLite database (e.g. 5-year dataset)
        local_bars = self.storage.market_data.get_bars(
            symbol=symbol,
            timeframe=timeframe,
            start_time=from_date,
            end_time=now,
        )

        # 2. Fetch latest live market bars from broker adapter
        live_window_start = max(from_date, now - timedelta(days=3))
        live_bars = self.adapter.fetch_historical_bars(
            symbol=symbol,
            timeframe=timeframe,
            from_date=live_window_start,
            to_date=now,
        )

        # 3. Seamlessly merge local historical dataset with fresh live broker bars
        bars_dict = {b.timestamp.isoformat(): b for b in local_bars}
        for b in live_bars:
            bars_dict[b.timestamp.isoformat()] = b

        raw_bars = sorted(bars_dict.values(), key=lambda b: b.timestamp)
        if not raw_bars:
            raw_bars = self.adapter.fetch_historical_bars(
                symbol=symbol,
                timeframe=timeframe,
                from_date=from_date,
                to_date=now,
            )

        # Validate and clean
        cleaned_bars, rejected = self.data_engineering.validate_and_clean_bars(raw_bars)
        dqr = self.data_engineering.assess_data_quality(cleaned_bars, symbol=symbol, timeframe=timeframe)

        # Persist normalized bars
        self.storage.market_data.save_normalized_bars(cleaned_bars)

        # Compute feature set
        feature_set = self.data_engineering.calculate_features(cleaned_bars, symbol=symbol, timeframe=timeframe)
        self.storage.market_data.save_feature_set(feature_set)

        self.memory.log_stage_progression(
            research_id=research_id,
            stage="DATASET_PREPARATION",
            summary=f"Prepared {len(feature_set.rows)} feature rows with rating {dqr.quality_rating.value}.",
            details={"total_bars": len(cleaned_bars), "rejected": rejected, "quality": dqr.model_dump(mode="json")},
        )

        # ------------------------------------------------------------------
        # 3. Pattern Discovery ("What patterns exist?")
        # ------------------------------------------------------------------
        patterns = self.research_engine.default_patterns
        selected_pattern = patterns[0]
        if pattern_id:
            for p in patterns:
                if p.pattern_id == pattern_id:
                    selected_pattern = p
                    break

        self.storage.research.save_pattern(selected_pattern)

        # Check negative knowledge in research memory
        prior_failure = self.memory.has_prior_failure(selected_pattern.name)
        if prior_failure:
            logger.warning(
                "Prior empirical failure detected for %s: %s",
                selected_pattern.name,
                prior_failure.failure_reason,
            )

        # ------------------------------------------------------------------
        # 4. Hypothesis Testing ("Does this pattern hold historically?")
        # ------------------------------------------------------------------
        hypothesis = self.research_engine.formulate_hypothesis(
            question=question,
            pattern=selected_pattern,
            forward_bars=5,
            target_return_pct=0.35,
        )
        self.storage.research.save_hypothesis(hypothesis)

        test_result, status = self.research_engine.test_hypothesis(hypothesis, feature_set)
        self.storage.research.save_test_result(test_result)
        self.storage.research.update_hypothesis_status(hypothesis.hypothesis_id, status)

        self.memory.log_stage_progression(
            research_id=research_id,
            stage="HYPOTHESIS_TESTING",
            summary=f"Hypothesis {status.value}: Win Rate={test_result.win_rate}%, Profit Factor={test_result.profit_factor}",
            details={"test_result": test_result.model_dump(mode="json"), "status": status.value},
        )

        # If rejected, immediately record negative knowledge
        if status == HypothesisStatus.REJECTED:
            self.memory.record_failed_hypothesis(
                hypothesis_id=hypothesis.hypothesis_id,
                statement=hypothesis.statement,
                failure_reason=f"Failed edge validation: Win Rate={test_result.win_rate}%, Profit Factor={test_result.profit_factor}",
                counter_evidence=[test_result.summary],
                lessons_learned="Pattern failed to show statistical edge over random walk. Avoid unconditioned execution.",
            )

        # ------------------------------------------------------------------
        # 5. Contradiction Search ("What contradicts my finding?")
        # ------------------------------------------------------------------
        contradiction = self.research_engine.search_contradictions(hypothesis, feature_set)
        self.storage.research.save_contradiction_search(contradiction)

        self.memory.log_stage_progression(
            research_id=research_id,
            stage="CONTRADICTION_SEARCH",
            summary=f"Contradiction search found {contradiction.counter_examples_count} counter-examples ({contradiction.false_positive_rate}% failure rate).",
            details={"failure_regimes": contradiction.failure_regimes, "fp_rate": contradiction.false_positive_rate},
        )

        # Follow-up formulation
        followup = self.research_engine.generate_followup(hypothesis, contradiction)
        if followup:
            self.storage.research.save_followup_research(followup)

        # ------------------------------------------------------------------
        # 6. Independent Dynamic Assessment ("Does this represent an opportunity?")
        # ------------------------------------------------------------------
        latest_feature = feature_set.rows[-1] if feature_set.rows else self.data_engineering._make_fallback_feature_row(cleaned_bars[-1] if cleaned_bars else None)
        option_snapshot = self.adapter.fetch_option_chain_snapshot(symbol=symbol)

        assessment = self.assessment_engine.generate_assessment(
            instrument=symbol,
            timeframe=timeframe,
            latest_feature=latest_feature,
            hypothesis=hypothesis,
            test_result=test_result,
            contradiction=contradiction,
            option_chain_summary=option_snapshot,
        )
        # Store assessment in dedicated database
        self.storage.assessments.save_assessment(assessment)

        self.memory.log_stage_progression(
            research_id=research_id,
            stage="ASSESSMENT_COMPLETED",
            summary=f"Generated assessment: Direction={assessment.direction.value}, Total Score={assessment.total_score}, Confidence={assessment.confidence}",
            details={"assessment_id": assessment.research_id, "score": assessment.total_score},
        )

        # Record finding in memory if confidence is strong and edge confirmed
        if assessment.confidence >= 0.65 and status == HypothesisStatus.CONFIRMED:
            self.memory.record_finding(
                pattern_name=selected_pattern.name,
                statistical_edge=f"Win Rate: {test_result.win_rate}%, PF: {test_result.profit_factor}",
                confidence=assessment.confidence,
                evidence_refs=[assessment.research_id, test_result.test_id],
            )

        logger.info(
            "Research cycle completed: %s (Score: %s, Direction: %s, Confidence: %s)",
            research_id,
            assessment.total_score,
            assessment.direction.value,
            assessment.confidence,
        )
        return assessment

    def get_latest_assessment(self, symbol: str = "NIFTY") -> Optional[HermesResearchAssessment]:
        """Retrieves the most recent assessment from storage."""
        return self.storage.assessments.get_latest_assessment(instrument=symbol)

    def get_memory_summary(self) -> Dict[str, Any]:
        """Provides high-level research telemetry and memory status."""
        findings = self.memory.get_all_findings()
        failures = self.memory.get_all_failed_hypotheses()
        history = self.memory.get_research_history(limit=20)
        assessments = self.storage.assessments.list_assessments(limit=10)

        return {
            "total_findings": len(findings),
            "total_failed_hypotheses": len(failures),
            "recent_history_count": len(history),
            "recent_assessments_count": len(assessments),
            "latest_findings": [f.model_dump(mode="json") for f in findings[:5]],
            "latest_failures": [fh.model_dump(mode="json") for fh in failures[:5]],
        }
