"""
Package 4: Canonical Trading Brain Domain Models & Exact Contracts.

Cognitive interpretation layer between canonical perception and downstream modules.
Provides multi-source market regime analysis, multi-scenario evaluation,
testable hypotheses, bounded candidate trade theses, and auditable summaries.
"""

from nifty_trader.brain.context import BrainContextCompiler
from nifty_trader.brain.contracts import (
    DEFAULT_PROMPT_VERSION,
    PACKAGE4_SCHEMA_VERSION,
    BrainFailure,
    BrainInput,
    BrainOutput,
    BrainRecord,
    BrainResult,
    BrainState,
    Confidence,
    Direction,
    EvidenceType,
    MarketContext,
    MarketHypothesis,
    MarketRegime,
    ObservationReference,
    ObservationRequest,
    ReasoningState,
    ReasoningSummary,
    Scenario,
    SetupCondition,
    Severity,
    StructureType,
    TimeframeAssessment,
    TradeCandidate,
    Uncertainty,
    UncertaintyType,
)
from nifty_trader.brain.engine import TradingBrainEngine
from nifty_trader.brain.prompts import SYSTEM_REASONING_POLICY, build_reasoning_prompt
from nifty_trader.brain.storage import BrainStorage
from nifty_trader.brain.validators import BrainOutputValidator, ValidationError

__all__ = [
    "BrainContextCompiler",
    "BrainFailure",
    "BrainInput",
    "BrainOutput",
    "BrainOutputValidator",
    "BrainRecord",
    "BrainResult",
    "BrainState",
    "BrainStorage",
    "Confidence",
    "DEFAULT_PROMPT_VERSION",
    "Direction",
    "EvidenceType",
    "MarketContext",
    "MarketHypothesis",
    "MarketRegime",
    "ObservationReference",
    "ObservationRequest",
    "PACKAGE4_SCHEMA_VERSION",
    "ReasoningState",
    "ReasoningSummary",
    "Scenario",
    "SetupCondition",
    "Severity",
    "StructureType",
    "SYSTEM_REASONING_POLICY",
    "TimeframeAssessment",
    "TradingBrainEngine",
    "TradeCandidate",
    "Uncertainty",
    "UncertaintyType",
    "ValidationError",
    "build_reasoning_prompt",
]
