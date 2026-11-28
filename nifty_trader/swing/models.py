"""
Data models and schemas for Hermes Swing Trading System (300-point 1:6 R:R Architecture).
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class GlobalIndexQuote:
    symbol: str
    name: str
    region: str  # US, ASIA, EUROPE, DOMESTIC
    price: float
    change_pct: float
    status: str  # BULLISH, BEARISH, NEUTRAL
    last_updated: str


@dataclass
class MacroRadarData:
    timestamp: str
    fii_futures_long_pct: float
    fii_futures_status: str  # TRAPPED_OVERSOLD, EUPHORIC_OVERBOUGHT, NEUTRAL
    fii_net_contracts: int
    fii_cash_net_cr: float
    dii_cash_net_cr: float
    crude_oil_price: float
    crude_oil_change_pct: float
    crude_status: str  # CALM, SURGING, BREAKDOWN
    gold_price: float
    gold_change_pct: float
    gold_status: str  # RISK_ON, RISK_OFF
    dxy_price: float
    dxy_change_pct: float
    dxy_status: str  # WEAK_BULLISH_EM, STRONG_BEARISH_EM
    us_10y_yield: float
    india_vix: float
    vix_status: str  # COMPRESSED, ELEVATED, PANIC_REVERSAL
    global_health_verdict: str  # GLOBAL_RISK_ON, GLOBAL_RISK_OFF, NEUTRAL
    global_indices: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class TimeframeState:
    timeframe: str  # W1, D1, 4H, 1H
    role: str  # COMPASS, ROADMAP, BATTLEGROUND, TRIGGER
    trend_bias: str  # BULLISH, BEARISH, NEUTRAL
    key_moving_averages: Dict[str, float]
    structure_summary: str
    permission_or_status: str


@dataclass
class ReactionZoneBox:
    zone_id: str
    symbol: str  # NIFTY, BANKNIFTY
    zone_type: str  # BULLISH_FLOOR, BEARISH_CEILING
    range_low: float
    range_high: float
    center_price: float
    distance_pts: float
    confluence_factors: List[str]
    institutional_anchors: Dict[str, Any]
    status: str  # ACTIVE_TESTING, NEARBY, DISTANT


@dataclass
class SwingSetup:
    setup_id: str
    symbol: str
    setup_name: str  # TREND_CONTINUATION, LIQUIDITY_SWEEP_SQUEEZE
    direction: str  # BULLISH, BEARISH
    reaction_zone: str
    entry_reference: float
    sl_points: float = 50.0
    tgt_points: float = 300.0
    risk_reward: str = "1:6.0"
    recommended_contract: str = ""
    monthly_expiry: str = ""
    status: str = "WATCHLIST"  # WATCHLIST, READY, TRIGGERED, ACTIVE, CLOSED
    reason: str = ""
    four_tiers_status: Dict[str, str] = field(default_factory=dict)
