"""
Stage 6: Hermes Tool Bridge.

Provides Hermes Orchestrator with safe, decoupled access to market observation tools,
browser extraction agents, instruction registries, and contextual memory.

STRICT INVARIANT:
The Brain NEVER invokes tools or browser APIs directly.
The Brain issues ObservationRequest, and Hermes uses ToolBridge to fulfill them.
"""

from copy import deepcopy
from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional, Tuple

from nifty_trader.brain.context.context_memory import ContextMemoryItem, ContextMemoryStore
from nifty_trader.brain.contracts import ObservationRequest
from nifty_trader.contracts.models import (
    CanonicalObservationStatus,
    ManualInstructionContext,
    UnifiedMarketObservation,
)

logger = logging.getLogger(__name__)


class HermesToolBridge:
    """
    Operational tool execution bridge for Hermes autonomous trading workflows.
    """

    def __init__(
        self,
        market_service: Optional[Any] = None,
        browser_agent: Optional[Any] = None,
        instruction_manager: Optional[Any] = None,
        memory_store: Optional[ContextMemoryStore] = None,
    ):
        self.market_service = market_service
        self.browser_agent = browser_agent
        self.instruction_manager = instruction_manager
        self.memory_store = memory_store or ContextMemoryStore()

    async def fetch_current_observation(
        self,
        symbol: str = "NIFTY",
        force_refresh: bool = False,
    ) -> UnifiedMarketObservation:
        """
        Retrieves the canonical UnifiedMarketObservation via MarketObservationService.
        """
        if self.market_service:
            if hasattr(self.market_service, "get_unified_market_observation"):
                return await self.market_service.get_unified_market_observation(
                    symbol=symbol,
                    include_browser=True,
                    include_sensibull=True,
                )
            if hasattr(self.market_service, "get_unified_observation"):
                return await self.market_service.get_unified_observation(symbol=symbol, force_refresh=force_refresh)
        raise RuntimeError("MarketObservationService is not configured on HermesToolBridge.")

    async def get_active_instructions(self) -> List[ManualInstructionContext]:
        """
        Retrieves active human operator instructions from the instruction manager.
        """
        if not self.instruction_manager:
            return []
        active = self.instruction_manager.get_active_instructions()
        return [
            ManualInstructionContext(
                instruction_id=inst.instruction_id,
                text=inst.text,
                priority=inst.priority,
                created_at=inst.created_at,
                created_by=inst.created_by,
                status=inst.status,
            )
            for inst in active
        ]

    async def fulfill_observation_request(
        self,
        request: ObservationRequest,
        current_observation: UnifiedMarketObservation,
    ) -> Tuple[UnifiedMarketObservation, List[str]]:
        """
        Translates a Brain ObservationRequest into operational tool executions,
        refreshing target observations and returning an updated UnifiedMarketObservation.
        """
        target_val = getattr(request, "source", None) or getattr(request, "target", "")
        logger.info(
            "Hermes ToolBridge fulfilling ObservationRequest [%s]: Target='%s', Reason='%s'",
            request.request_id,
            target_val,
            request.reason,
        )

        tools_invoked: List[str] = []
        updated_obs = deepcopy(current_observation)
        target_lower = target_val.lower()

        # 1. Option Chain / Sensibull Request
        if any(k in target_lower for k in ["sensibull", "derivative", "pcr", "option", "oi", "open interest", "strike"]):
            tools_invoked.append("browser_agent.sensibull_refresh")
            if self.market_service and getattr(self.market_service, "sensibull_source", None):
                try:
                    sensi_res = await self.market_service.sensibull_source.capture_observation("NIFTY")
                    updated_obs.visual.sensibull = sensi_res
                    logger.info("Refreshed Sensibull derivatives observation via tool bridge.")
                except Exception as e:
                    logger.warning("Failed to refresh Sensibull via tool bridge: %s", e)

        # 2. Visual Chart / TradingView Request
        elif any(k in target_lower for k in ["tradingview", "chart", "visual", "pattern", "support", "resistance", "breakout"]):
            tools_invoked.append("browser_agent.tradingview_refresh")
            if self.market_service and getattr(self.market_service, "planner", None):
                tv_source = self.market_service.planner.sources.get("tradingview")
                if tv_source:
                    try:
                        tv_res = await tv_source.capture_observation("NIFTY")
                        updated_obs.visual.tradingview = tv_res
                        logger.info("Refreshed TradingView visual observation via tool bridge.")
                    except Exception as e:
                        logger.warning("Failed to refresh TradingView via tool bridge: %s", e)

        # 3. Candle / Timeframe Numerical Request (15M, 1H)
        elif any(k in target_lower for k in ["15m", "1h", "candle", "numerical", "price", "volume"]):
            tools_invoked.append("market_data.numerical_refresh")
            if self.market_service:
                try:
                    if hasattr(self.market_service, "get_unified_market_observation"):
                        refreshed = await self.market_service.get_unified_market_observation(symbol="NIFTY")
                    else:
                        refreshed = await self.market_service.get_unified_observation(symbol="NIFTY", force_refresh=True)
                    updated_obs.numerical = refreshed.numerical
                    updated_obs.observed_at = refreshed.observed_at
                    logger.info("Refreshed numerical candle data via tool bridge.")
                except Exception as e:
                    logger.warning("Failed to refresh numerical data via tool bridge: %s", e)

        else:
            # Default generic refresh
            tools_invoked.append("market_service.generic_refresh")
            if self.market_service:
                try:
                    if hasattr(self.market_service, "get_unified_market_observation"):
                        updated_obs = await self.market_service.get_unified_market_observation(symbol="NIFTY")
                    else:
                        updated_obs = await self.market_service.get_unified_observation(symbol="NIFTY", force_refresh=True)
                except Exception as e:
                    logger.warning("Generic observation refresh failed: %s", e)

        # Run cross-source validation if available
        if self.market_service and getattr(self.market_service, "multi_cross_checker", None):
            try:
                cross_checks = self.market_service.multi_cross_checker.validate_all(
                    numerical=updated_obs.numerical,
                    tradingview=updated_obs.visual.tradingview,
                    sensibull=updated_obs.visual.sensibull,
                )
                updated_obs.cross_source_validation = cross_checks
            except Exception as e:
                logger.warning("Cross check re-evaluation failed: %s", e)

        return updated_obs, tools_invoked

    def query_memory(
        self,
        setup_type: Optional[str] = None,
        timeframe: Optional[str] = None,
        query_text: Optional[str] = None,
        limit: int = 3,
    ) -> List[ContextMemoryItem]:
        """Queries historical experience memories."""
        return self.memory_store.query_relevant(
            setup_type=setup_type,
            timeframe=timeframe,
            query_text=query_text,
            limit=limit,
        )
