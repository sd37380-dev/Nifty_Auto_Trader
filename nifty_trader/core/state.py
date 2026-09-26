"""
Trading State Machine and Structured Cognitive Schemas.
"""

from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


class TradingState(str, Enum):
    """
    Finite state machine operational states.
    """
    STARTUP = "STARTUP"
    PRE_MARKET = "PRE_MARKET"
    OBSERVE_1H = "OBSERVE_1H"
    OBSERVE_15M = "OBSERVE_15M"
    ANALYZE = "ANALYZE"
    WAIT = "WAIT"
    WATCH_SETUP = "WATCH_SETUP"
    RESEARCH = "RESEARCH"
    PAUSED = "PAUSED"
    MARKET_CLOSED = "MARKET_CLOSED"


class MarketAction(str, Enum):
    """
    Cognitive action recommended by the AI brain.
    NOTE: The AI is always free to output 'WAIT' or 'NO_TRADE'.
    """
    OBSERVE = "OBSERVE"
    WAIT = "WAIT"
    WATCH_SETUP = "WATCH_SETUP"
    ANALYZE = "ANALYZE"
    RESEARCH = "RESEARCH"
    TRADE_PLAN = "TRADE_PLAN"
    NO_TRADE = "NO_TRADE"


class MarketObservationOutput(BaseModel):
    """
    Structured reasoning output returned by the Model Router.
    Guarantees strict schema compliance from any cognitive provider.
    """
    market_context: str = Field(description="Summary of prevailing market regime and macro backdrop.")
    one_hour_bias: str = Field(description="1H directional bias: BULLISH | BEARISH | NEUTRAL | UNCLEAR")
    fifteen_minute_state: str = Field(description="15M price action: TRENDING | PULLBACK | RANGE | BREAKOUT | REVERSAL | UNCLEAR")
    setup_status: str = Field(description="Predefined setup formation: NONE | DEVELOPING | POTENTIAL | CONFIRMED")
    action: MarketAction = Field(description="Recommended next action: OBSERVE | WAIT | WATCH_SETUP | RESEARCH | NO_TRADE | TRADE_PLAN")
    important_levels: List[float] = Field(default_factory=list, description="Key support, resistance, or pivot price levels.")
    reasoning: List[str] = Field(default_factory=list, description="Step-by-step analytical reasoning.")
    uncertainties: List[str] = Field(default_factory=list, description="Identified risks, missing variables, or ambiguities.")
    next_observation: str = Field(description="Trigger or condition for the next required analysis.")
