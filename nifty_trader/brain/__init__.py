"""
Package 4: Trading Brain & Market Reasoning Engine.

Cognitive interpretation layer between canonical perception and downstream modules.
Provides multi-source market regime analysis, multi-scenario evaluation,
testable hypotheses, bounded candidate trade theses, and auditable summaries.
"""

from nifty_trader.brain.context import BrainContextCompiler
from nifty_trader.brain.contracts import (
    BoundedConfidence,
    BrainReasoningOutput,
    CandidateDirection,
    MarketHypothesis,
    MarketRegime,
    ObservationRequest,
    Scenario,
    SetupState,
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
    "BoundedConfidence",
    "BrainReasoningOutput",
    "BrainOutputValidator",
    "BrainStorage",
    "CandidateDirection",
    "MarketHypothesis",
    "MarketRegime",
    "ObservationRequest",
    "Scenario",
    "SetupState",
    "SYSTEM_REASONING_POLICY",
    "TradingBrainEngine",
    "TradeCandidate",
    "Uncertainty",
    "UncertaintyType",
    "ValidationError",
    "build_reasoning_prompt",
]
