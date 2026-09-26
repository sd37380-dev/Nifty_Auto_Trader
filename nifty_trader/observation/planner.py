"""
Observation Planner.

Coordinates multi-source market observation planning across TradingView,
Sensibull, and Numerical feeds. Integrates automated cycle requirements
and operator steering directives while enforcing observation-only boundaries.
"""

from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, Field

from nifty_trader.instruction.models import AgentInstruction
from nifty_trader.observation.sources.base import IMarketObservationSource

logger = logging.getLogger(__name__)


class ObservationPlan(BaseModel):
    """Execution blueprint for a single market perception cycle."""
    plan_id: str = Field(default_factory=lambda: f"plan_{uuid.uuid4().hex[:8]}")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    required_sources: List[str] = Field(default_factory=list)
    is_sensibull_requested: bool = False
    is_tradingview_requested: bool = False
    is_numerical_requested: bool = True
    triggers: List[str] = Field(default_factory=list)
    safety_notes: List[str] = Field(default_factory=list)


class ObservationPlanner:
    """
    Decides which observation sources must be interrogated during a perception cycle.
    Supports automatic scheduled observation and manual operator instruction overrides.
    """

    SENSIBULL_DIRECTIVES = [
        "sensibull",
        "option chain",
        "options chain",
        "pcr",
        "put call ratio",
        "max pain",
        "implied volatility",
        "open interest",
    ]

    TRADINGVIEW_DIRECTIVES = [
        "tradingview",
        "chart",
        "candlestick",
        "technical view",
    ]

    PROHIBITED_DIRECTIVES = [
        "buy",
        "sell",
        "long",
        "short",
        "place order",
        "execute",
        "trade now",
    ]

    def __init__(
        self,
        tradingview_enabled: bool = True,
        sensibull_enabled: bool = True,
        numerical_enabled: bool = True,
        automatic_observation: bool = True,
    ):
        self.tradingview_enabled = tradingview_enabled
        self.sensibull_enabled = sensibull_enabled
        self.numerical_enabled = numerical_enabled
        self.automatic_observation = automatic_observation
        self._sources: Dict[str, IMarketObservationSource] = {}

    def register_source(self, source: IMarketObservationSource) -> None:
        """Registers a pluggable observation source."""
        self._sources[source.source_id] = source

    def get_source(self, source_id: str) -> Optional[IMarketObservationSource]:
        return self._sources.get(source_id)

    def plan_observation(
        self,
        instructions: Optional[List[AgentInstruction]] = None,
        source_overrides: Optional[List[str]] = None,
    ) -> ObservationPlan:
        """
        Synthesizes configuration, CLI overrides, and operator steering into an ObservationPlan.
        Enforces strict observation-only boundary.
        """
        triggers: List[str] = []
        safety_notes: List[str] = []

        # 1. Check for CLI explicit overrides
        if source_overrides:
            selected = [s.strip().lower() for s in source_overrides if s.strip()]
            triggers.append(f"CLI_OVERRIDE: Explicit sources requested: {', '.join(selected)}")
            return ObservationPlan(
                required_sources=selected,
                is_sensibull_requested="sensibull" in selected,
                is_tradingview_requested="tradingview" in selected,
                is_numerical_requested="numerical" in selected,
                triggers=triggers,
            )

        # 2. Base automatic schedule
        required = []
        if self.numerical_enabled:
            required.append("numerical")
            triggers.append("CONFIG: Numerical feed active by default.")
        if self.tradingview_enabled:
            required.append("tradingview")
            triggers.append("CONFIG: TradingView visual active by default.")
        if self.sensibull_enabled:
            required.append("sensibull")
            triggers.append("CONFIG: Sensibull option-chain active by default.")

        # 3. Analyze Operator Instructions
        if instructions:
            for inst in instructions:
                text_lower = inst.text.lower()

                # Check for trading directive intrusion
                for word in self.PROHIBITED_DIRECTIVES:
                    if f" {word} " in f" {text_lower} ":
                        safety_notes.append(
                            f"Safety Boundary Notice: Directive word '{word}' detected in instruction '{inst.text}'. "
                            "Trade execution is strictly disabled; instruction treated as observation context only."
                        )
                        break

                # Check for Sensibull directives
                if any(kw in text_lower for kw in self.SENSIBULL_DIRECTIVES):
                    if "sensibull" not in required:
                        required.append("sensibull")
                    triggers.append(f"INSTRUCTION: Operator instruction triggered Sensibull observation: '{inst.text}'")

                # Check for TradingView directives
                if any(kw in text_lower for kw in self.TRADINGVIEW_DIRECTIVES):
                    if "tradingview" not in required:
                        required.append("tradingview")
                    triggers.append(f"INSTRUCTION: Operator instruction triggered TradingView observation: '{inst.text}'")

        return ObservationPlan(
            required_sources=required,
            is_sensibull_requested="sensibull" in required,
            is_tradingview_requested="tradingview" in required,
            is_numerical_requested="numerical" in required,
            triggers=triggers,
            safety_notes=safety_notes,
        )
