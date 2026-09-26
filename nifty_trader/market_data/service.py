"""
Market Observation Service.

Coordinates numerical market data feeds, SQLite cache synchronization,
candle clocks, browser visual perception cross-checking, and event generation.
"""

from datetime import datetime, timedelta, timezone
import logging
from typing import Any, Dict, List, Optional

from nifty_trader.browser.browser_agent import BrowserAgent
from nifty_trader.browser.models import BrowserObservation
from nifty_trader.instruction.manager import InstructionManager
from nifty_trader.market_data.base import MarketDataProvider
from nifty_trader.market_data.cache import MarketDataCache
from nifty_trader.market_data.clock import CandleClock
from nifty_trader.market_data.cross_check import MarketCrossChecker
from nifty_trader.market_data.events import EventBus
from nifty_trader.market_data.models import (
    Candle,
    DataQuality,
    MarketSessionStatus,
    ObservationEventType,
    Timeframe,
)
from nifty_trader.market_data.observation import (
    AgentObservationContext,
    MarketObservation,
)
from nifty_trader.market_data.session import MarketSessionManager

logger = logging.getLogger(__name__)


class MarketObservationService:
    """
    Central service producing deterministic multi-timeframe market observations.
    """

    def __init__(
        self,
        provider: MarketDataProvider,
        cache: Optional[MarketDataCache] = None,
        event_bus: Optional[EventBus] = None,
        cross_checker: Optional[MarketCrossChecker] = None,
        instruction_manager: Optional[InstructionManager] = None,
        browser_agent: Optional[BrowserAgent] = None,
        session_manager: Optional[MarketSessionManager] = None,
        clock: Optional[CandleClock] = None,
    ):
        self.provider = provider
        self.cache = cache or MarketDataCache()
        self.event_bus = event_bus or EventBus()
        self.cross_checker = cross_checker or MarketCrossChecker(tolerance_pct=0.5)
        self.instruction_mgr = instruction_manager or InstructionManager()
        self.browser_agent = browser_agent
        self.session_manager = session_manager or MarketSessionManager()
        self.clock = clock or CandleClock()

        self._last_observation: Optional[MarketObservation] = None
        self._last_15m_ts: Optional[datetime] = None
        self._last_1h_ts: Optional[datetime] = None
        self._last_session_status: Optional[MarketSessionStatus] = None
        self._last_instruction_ids: Optional[set] = None

    async def sync_data(self, symbol: str = "NIFTY") -> Dict[str, int]:
        """Convenience alias for sync_market_data."""
        return await self.sync_market_data(symbol=symbol)

    async def observe_market(
        self,
        symbol: str = "NIFTY",
        timeframe: Optional[Timeframe] = None,
        perform_cross_check: bool = False,
    ) -> MarketObservation:
        """Convenience alias for get_market_observation."""
        return await self.get_market_observation(symbol=symbol, include_browser=perform_cross_check)

    async def sync_market_data(self, symbol: str = "NIFTY") -> Dict[str, int]:
        """
        Incrementally synchronizes 1H and 15M candles from the provider to the local cache.
        Returns a dict of counts added per timeframe.
        """
        results = {}
        for tf in [Timeframe.H1, Timeframe.M15]:
            latest_cached_ts = self.cache.get_latest_timestamp(symbol=symbol, timeframe=tf)

            if latest_cached_ts is None:
                # Initial historical fetch
                logger.info("Performing initial sync for %s %s...", symbol, tf.value)
                candles = await self.provider.get_recent_candles(symbol=symbol, timeframe=tf, count=100)
            else:
                # Incremental sync from latest cached timestamp
                logger.debug("Performing incremental sync for %s %s from %s...", symbol, tf.value, latest_cached_ts)
                candles = await self.provider.get_historical_candles(
                    symbol=symbol,
                    timeframe=tf,
                    start_time=latest_cached_ts,
                )

            stored = self.cache.store_candles(candles)
            results[tf.value] = stored

            # Check if new completed candle arrived
            if candles:
                closed_candles = [c for c in candles if c.is_closed]
                if closed_candles:
                    newest = closed_candles[-1]
                    last_seen = self._last_1h_ts if tf == Timeframe.H1 else self._last_15m_ts
                    if last_seen is None or newest.timestamp > last_seen:
                        if tf == Timeframe.H1:
                            self._last_1h_ts = newest.timestamp
                        else:
                            self._last_15m_ts = newest.timestamp

                        await self.event_bus.emit(
                            event_type=ObservationEventType.CANDLE_CLOSED,
                            symbol=symbol,
                            timeframe=tf,
                            data={"candle": newest.model_dump(mode="json")},
                            message=f"New completed {tf.value} candle at {newest.timestamp.isoformat()} (Close: {newest.close})",
                        )

        return results

    async def get_market_observation(
        self,
        symbol: str = "NIFTY",
        include_browser: bool = False,
    ) -> MarketObservation:
        """
        Gathers cached numerical candles, checks exchange session state,
        retrieves visual browser observation if requested, and runs cross-check.
        """
        session_status = await self.provider.get_market_status()

        # Emit session change event if applicable
        if self._last_session_status is not None and self._last_session_status != session_status:
            ev_type = ObservationEventType.MARKET_OPENED if session_status == MarketSessionStatus.OPEN else ObservationEventType.MARKET_CLOSED
            await self.event_bus.emit(
                event_type=ev_type,
                symbol=symbol,
                message=f"Market session shifted from {self._last_session_status.value} to {session_status.value}",
            )
        self._last_session_status = session_status

        # Retrieve cached completed candles
        h1_candles = self.cache.get_candles(symbol=symbol, timeframe=Timeframe.H1, limit=30, only_closed=True)
        m15_candles = self.cache.get_candles(symbol=symbol, timeframe=Timeframe.M15, limit=50, only_closed=True)

        # Assess data quality
        quality = DataQuality.VALID
        if not h1_candles or not m15_candles:
            quality = DataQuality.PARTIAL if (h1_candles or m15_candles) else DataQuality.UNAVAILABLE
        else:
            latest_candle = m15_candles[-1]
            now_utc = datetime.now(timezone.utc)
            # If during regular market hours and latest 15M candle is older than 45 mins -> stale
            if session_status == MarketSessionStatus.OPEN and (now_utc - latest_candle.timestamp) > timedelta(minutes=45):
                quality = DataQuality.STALE

        # Visual observation (if browser agent is attached and requested)
        browser_obs: Optional[BrowserObservation] = None
        if include_browser and self.browser_agent:
            try:
                browser_obs = await self.browser_agent.inspect_tradingview_nifty()
            except Exception as e:
                logger.warning("Could not obtain TradingView observation: %s", e)

        # Cross-check visual vs numerical close
        numerical_ref = m15_candles[-1] if m15_candles else (h1_candles[-1] if h1_candles else None)
        cross_res = self.cross_checker.cross_check(browser_obs=browser_obs, numerical_candle=numerical_ref)

        if not cross_res.is_aligned and cross_res.status == "MISMATCH":
            quality = DataQuality.INVALID
            await self.event_bus.emit(
                event_type=ObservationEventType.DATA_MISMATCH,
                symbol=symbol,
                data=cross_res.model_dump(),
                message=cross_res.details,
            )

        observation = MarketObservation(
            symbol=symbol,
            market_status=session_status,
            one_hour_candles=h1_candles,
            fifteen_minute_candles=m15_candles,
            browser_observation=browser_obs,
            data_quality=quality,
            source_status={
                "provider": self.provider.__class__.__name__,
                "cached_1h_count": len(h1_candles),
                "cached_15m_count": len(m15_candles),
                "cache_total": self.cache.get_candle_count(symbol, Timeframe.H1) + self.cache.get_candle_count(symbol, Timeframe.M15),
            },
            cross_check=cross_res,
        )

        return observation

    def compile_observation_context(
        self,
        observation: MarketObservation,
        force_change: bool = False,
    ) -> AgentObservationContext:
        """
        Assembles MarketObservation, active operator instructions, and event history
        into an AgentObservationContext, detecting if meaningful change occurred.
        """
        active_instructions = self.instruction_mgr.get_active_instructions()
        recent_events = self.event_bus.get_history(limit=10)

        changes: List[str] = []
        if force_change:
            changes.append("MANUAL_TRIGGER: Operator requested observation analysis.")

        if self._last_observation is None:
            changes.append("INITIAL_OBSERVATION: System baseline established.")
        else:
            prev = self._last_observation
            # Check 15M candle change
            if prev.latest_15m and observation.latest_15m:
                if observation.latest_15m.timestamp > prev.latest_15m.timestamp:
                    changes.append(f"NEW_15M_CANDLE: Close at {observation.latest_15m.close}")

            # Check 1H candle change
            if prev.latest_1h and observation.latest_1h:
                if observation.latest_1h.timestamp > prev.latest_1h.timestamp:
                    changes.append(f"NEW_1H_CANDLE: Close at {observation.latest_1h.close}")

            # Check session change
            if prev.market_status != observation.market_status:
                changes.append(f"SESSION_CHANGE: {prev.market_status.value} -> {observation.market_status.value}")

            # Check data quality change
            if prev.data_quality != observation.data_quality:
                changes.append(f"DATA_QUALITY_CHANGE: {prev.data_quality.value} -> {observation.data_quality.value}")

        # Check active instructions changes
        current_inst_ids = {i.instruction_id for i in active_instructions}
        if self._last_instruction_ids is not None:
            new_ids = current_inst_ids - self._last_instruction_ids
            if new_ids:
                changes.append(f"NEW_INSTRUCTIONS: {len(new_ids)} new operator directive(s) added.")
        elif current_inst_ids:
            changes.append(f"OPERATOR_INSTRUCTIONS: {len(current_inst_ids)} active directive(s).")
        self._last_instruction_ids = current_inst_ids

        has_change = len(changes) > 0 or force_change
        self._last_observation = observation

        return AgentObservationContext(
            latest_market_observation=observation,
            manual_instructions=active_instructions,
            recent_events=recent_events,
            has_meaningful_change=has_change,
            change_reasons=changes,
        )

    async def get_agent_observation_context(
        self,
        symbol: str = "NIFTY",
        include_browser: bool = False,
        force_change: bool = False,
    ) -> AgentObservationContext:
        """Collects observation and compiles agent observation context."""
        obs = await self.get_market_observation(symbol=symbol, include_browser=include_browser)
        return self.compile_observation_context(obs, force_change=force_change)
