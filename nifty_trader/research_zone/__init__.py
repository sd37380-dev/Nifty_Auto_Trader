"""
Hermes Research & Intelligence Zone.

A dedicated, isolated quantitative research environment designed for autonomous
pattern discovery, hypothesis backtesting, aggressive contradiction searching,
and dynamic segment importance scoring.

Completely segregated from live and paper trading execution loops.
Dhan-ready interface with zero live dependencies required.
"""

from nifty_trader.research_zone.assessment import HermesAssessmentEngine
from nifty_trader.research_zone.contracts import (
    RESEARCH_ZONE_SCHEMA_VERSION,
    AssessmentSegment,
    ContradictionSearch,
    DataQualityRating,
    DataQualityReport,
    DhanRawPayload,
    FailedHypothesis,
    FeatureRow,
    FeatureSet,
    FollowUpResearch,
    HermesResearchAssessment,
    Hypothesis,
    HypothesisStatus,
    MarketDirection,
    NormalizedBar,
    PatternDefinition,
    PatternType,
    ResearchFinding,
    ResearchHistoryEntry,
    ResearchQuestion,
    TestResult,
)
from nifty_trader.research_zone.data_engineering import DataEngineeringZone
from nifty_trader.research_zone.dhan_adapter import DhanDataAdapter, MockDhanDataAdapter
from nifty_trader.research_zone.memory import ResearchMemory
from nifty_trader.research_zone.research_engine import HermesResearchEngine
from nifty_trader.research_zone.service import HermesResearchZoneService
from nifty_trader.research_zone.storage import (
    AssessmentsStore,
    MarketDataStore,
    ResearchMemoryStore,
    ResearchStore,
    ResearchZoneStorage,
)

__all__ = [
    "RESEARCH_ZONE_SCHEMA_VERSION",
    "MarketDirection",
    "PatternType",
    "HypothesisStatus",
    "DataQualityRating",
    "DhanRawPayload",
    "NormalizedBar",
    "DataQualityReport",
    "FeatureRow",
    "FeatureSet",
    "ResearchQuestion",
    "PatternDefinition",
    "Hypothesis",
    "TestResult",
    "ContradictionSearch",
    "FollowUpResearch",
    "AssessmentSegment",
    "HermesResearchAssessment",
    "ResearchFinding",
    "FailedHypothesis",
    "ResearchHistoryEntry",
    "DhanDataAdapter",
    "MockDhanDataAdapter",
    "DataEngineeringZone",
    "HermesResearchEngine",
    "HermesAssessmentEngine",
    "ResearchZoneStorage",
    "MarketDataStore",
    "ResearchStore",
    "AssessmentsStore",
    "ResearchMemoryStore",
    "ResearchMemory",
    "HermesResearchZoneService",
]
