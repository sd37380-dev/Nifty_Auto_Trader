"""
Nifty Autonomous Trader Runtime.

Core orchestration runtime initializing ModelRouter, BrowserAgent,
state machine, and cognitive analysis pipeline.
"""

import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional
import yaml
from pydantic import BaseModel, Field

from nifty_trader.browser.browser_agent import BrowserAgent
from nifty_trader.browser.hermes_adapter import HermesBrowserAdapter
from nifty_trader.browser.models import BrowserObservation
from nifty_trader.browser.screenshot import ScreenshotManager
from nifty_trader.autonomous.contracts import AutonomousLimits
from nifty_trader.autonomous.engine import AutonomousObservationEngine
from nifty_trader.autonomous.persistence import AutonomousStorage
from nifty_trader.brain.contracts import BrainOutput, BrainResult
from nifty_trader.brain.engine import TradingBrainEngine
from nifty_trader.contracts.models import UnifiedMarketObservation
from nifty_trader.core.state import MarketObservationOutput, TradingState
from nifty_trader.features.manifest import ReleaseManifestManager
from nifty_trader.features.registry import FeatureRegistry
from nifty_trader.hermes.adapter import HermesIntegrationAdapter
from nifty_trader.hermes.compatibility import HermesCompatibilityChecker
from nifty_trader.hermes.updater import HermesUpdateInspector
from nifty_trader.hermes.version import HermesVersionManager
from nifty_trader.router.base import TaskTier
from nifty_trader.router.router import ModelRouter
from nifty_trader.instruction.manager import InstructionManager
from nifty_trader.instruction.models import AgentInstruction, InstructionPriority, InstructionStatus
from nifty_trader.market_data.cache import MarketDataCache
from nifty_trader.market_data.clock import CandleClock
from nifty_trader.market_data.cross_check import MarketCrossChecker
from nifty_trader.market_data.events import EventBus
from nifty_trader.market_data.models import Timeframe
from nifty_trader.market_data.observation import MarketObservation, MarketPerceptionOutput
from nifty_trader.market_data.providers.mock import MockMarketDataProvider
from nifty_trader.market_data.providers.yahoo import YahooFinanceProvider
from nifty_trader.market_data.session import MarketSessionManager
from nifty_trader.observation.cross_check import MultiSourceCrossChecker
from nifty_trader.observation.models import (
    MultiSourceComparisonResult,
    ObservationSourceType,
    SensibullObservation,
    SensibullStatus,
    SourceObservationResult,
)
from nifty_trader.observation.planner import ObservationPlan, ObservationPlanner
from nifty_trader.observation.sources.numerical import NumericalMarketDataSource
from nifty_trader.observation.sources.sensibull import SensibullObservationSource
from nifty_trader.observation.sources.tradingview import TradingViewObservationSource

logger = logging.getLogger("nifty_trader.runtime")


class VisualPerceptionOutput(BaseModel):
    """
    Schema for purely neutral visual perception verification.
    STRICTLY PROHIBITS trading conclusions (no BUY, SELL, target, stop loss).
    """
    page_description: str = Field(description="Objective factual description of the visible webpage or chart.")
    detected_timeframe: str = Field(description="Visible timeframe on chart or 'N/A' if not a chart.")
    visible_components: list[str] = Field(default_factory=list, description="List of recognized UI components (e.g. candlestick series, volume bars, header).")
    symbol_identified: str = Field(description="Ticker or title identified on page.")


class NiftyTraderRuntime:
    """
    Independent runtime for NIFTY Autonomous Trader.
    """

    def __init__(
        self,
        config_dir: Optional[Path] = None,
        env_file: Optional[Path] = None,
    ):
        self.root_dir = Path(__file__).resolve().parent.parent.parent
        self.config_dir = config_dir or (self.root_dir / "config")
        self.state = TradingState.STARTUP

        # Load environment variables
        self._load_environment(env_file)

        # Load settings
        self.settings = self._load_yaml(self.config_dir / "settings.yaml")

        # Initialize Model Router
        models_config_path = self.config_dir / "models.yaml"
        self.router = ModelRouter(config_path=models_config_path)

        # Initialize Browser Subsystem
        browser_cfg = self.settings.get("browser", {})
        shots_dir = self.root_dir / browser_cfg.get("screenshots", {}).get("directory", "data/browser/screenshots")
        retention = browser_cfg.get("screenshots", {}).get("retention_days", 7)
        screenshot_mgr = ScreenshotManager(storage_dir=shots_dir, retention_days=retention)

        adapter = HermesBrowserAdapter(
            chrome_path=browser_cfg.get("chrome_path", r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
            user_data_dir=self.root_dir / "data" / "browser" / "chrome_profile",
            remote_port=browser_cfg.get("remote_port", 9225),
            headless=browser_cfg.get("headless", True),
            navigation_timeout_seconds=browser_cfg.get("navigation_timeout_seconds", 30.0),
            element_timeout_seconds=browser_cfg.get("element_timeout_seconds", 10.0),
            screenshot_manager=screenshot_mgr,
        )

        extraction_cfg = browser_cfg.get("extraction", {})
        self.browser = BrowserAgent(
            provider=adapter,
            max_action_retries=browser_cfg.get("max_action_retries", 2),
            restart_on_disconnect=browser_cfg.get("restart_on_disconnect", True),
            max_visible_text_chars=extraction_cfg.get("max_visible_text_chars", 12000),
            max_dom_elements=extraction_cfg.get("max_dom_elements", 200),
        )

        # Initialize Hermes Integration & Version Management
        self.hermes_version = HermesVersionManager(self.config_dir / "hermes-version.yaml")
        self.hermes_adapter = HermesIntegrationAdapter(self.hermes_version)
        self.hermes_checker = HermesCompatibilityChecker(self.hermes_version, self.hermes_adapter)
        self.hermes_updater = HermesUpdateInspector(self.hermes_version)

        # Initialize Feature Extension Registry & Release Manifest
        self.features = FeatureRegistry(self.config_dir / "features.yaml")
        self.manifest = ReleaseManifestManager(self.config_dir / "release-manifest.yaml")

        # Initialize Instruction Subsystem (Operator Steering)
        agent_dir = self.root_dir / "data" / "agent"
        agent_dir.mkdir(parents=True, exist_ok=True)
        instructions_db = agent_dir / "instructions.db"
        self.instruction_manager = InstructionManager(db_path=instructions_db)

        # Initialize Market Data Subsystem
        market_dir = self.root_dir / "data" / "market"
        market_dir.mkdir(parents=True, exist_ok=True)
        market_cfg = self.settings.get("market_data", {})
        provider_name = market_cfg.get("provider", "yahoo").lower()
        symbol = market_cfg.get("symbol", "^NSEI")

        if provider_name == "yahoo":
            provider = YahooFinanceProvider(timeout_seconds=market_cfg.get("timeout_seconds", 10.0))
        else:
            provider = MockMarketDataProvider()

        cache_path = self.root_dir / market_cfg.get("cache_db_path", "data/market/market_cache.db")
        cache = MarketDataCache(db_path=cache_path)
        session_mgr = MarketSessionManager()
        clock = CandleClock()
        event_bus = EventBus()
        cross_checker = MarketCrossChecker(tolerance_pct=market_cfg.get("cross_check_tolerance_pct", 0.5))

        # Initialize Package 3.1 Observation Sources & Planner
        obs_cfg = self.settings.get("market_observation", {})
        sources_cfg = obs_cfg.get("sources", {})
        sensi_cfg = sources_cfg.get("sensibull", {})
        tv_cfg = sources_cfg.get("tradingview", {})
        cross_cfg = obs_cfg.get("cross_check", {})

        self.sensibull_source = SensibullObservationSource(
            browser_agent=self.browser,
            target_url=sensi_cfg.get("url"),
            max_retries=sensi_cfg.get("max_retries", 2),
            timeout_seconds=sensi_cfg.get("timeout_seconds", 30.0),
            enabled=sensi_cfg.get("enabled", True),
        )
        self.tradingview_source = TradingViewObservationSource(
            browser_agent=self.browser,
            enabled=tv_cfg.get("enabled", True),
        )
        self.numerical_source = NumericalMarketDataSource(
            provider=provider,
            cache=cache,
            enabled=sources_cfg.get("numerical", {}).get("enabled", True),
        )

        self.planner = ObservationPlanner(
            tradingview_enabled=tv_cfg.get("enabled", True),
            sensibull_enabled=sensi_cfg.get("enabled", True),
            numerical_enabled=sources_cfg.get("numerical", {}).get("enabled", True),
            automatic_observation=obs_cfg.get("planner", {}).get("automatic_observation", True),
        )
        self.planner.register_source(self.numerical_source)
        self.planner.register_source(self.tradingview_source)
        self.planner.register_source(self.sensibull_source)

        self.multi_cross_checker = MultiSourceCrossChecker(
            match_tolerance_pct=cross_cfg.get("match_tolerance_pct", 0.5),
            minor_tolerance_pct=cross_cfg.get("minor_tolerance_pct", 1.5),
        )

        from nifty_trader.market_data.service import MarketObservationService
        self.market_service = MarketObservationService(
            provider=provider,
            cache=cache,
            session_manager=session_mgr,
            clock=clock,
            event_bus=event_bus,
            cross_checker=cross_checker,
            browser_agent=self.browser,
            instruction_manager=self.instruction_manager,
            planner=self.planner,
            sensibull_source=self.sensibull_source,
            multi_cross_checker=self.multi_cross_checker,
        )

        # Initialize Package 4 Trading Brain Engine
        brain_dir = self.root_dir / "data" / "brain"
        brain_dir.mkdir(parents=True, exist_ok=True)
        from nifty_trader.brain.storage import BrainStorage
        brain_storage = BrainStorage(db_path=brain_dir / "reasoning_history.db")
        self.brain = TradingBrainEngine(
            router=self.router,
            storage=brain_storage,
        )

        # Initialize Package 5 Autonomous Observation & Waiting Engine
        auto_dir = self.root_dir / "data" / "autonomous"
        auto_dir.mkdir(parents=True, exist_ok=True)
        auto_cfg = self.settings.get("autonomous", {})
        auto_limits = AutonomousLimits(
            max_cycles=auto_cfg.get("max_cycles", 100),
            max_observation_requests=auto_cfg.get("max_observation_requests", 20),
            max_model_calls=auto_cfg.get("max_model_calls", 50),
            max_consecutive_failures=auto_cfg.get("max_consecutive_failures", 5),
            max_session_duration_minutes=auto_cfg.get("max_session_duration_minutes", 390),
            min_wait_seconds=auto_cfg.get("waiting", {}).get("minimum_seconds", 5.0),
            max_wait_seconds=auto_cfg.get("waiting", {}).get("maximum_seconds", 3600.0),
            default_cooldown_seconds=auto_cfg.get("cooldown", {}).get("default_seconds", 30.0),
            sensibull_cooldown_seconds=auto_cfg.get("cooldown", {}).get("sensibull_seconds", 60.0),
            tradingview_cooldown_seconds=auto_cfg.get("cooldown", {}).get("tradingview_seconds", 30.0),
        )
        auto_storage = AutonomousStorage(db_path=auto_dir / "autonomous_engine.db")
        self.autonomous = AutonomousObservationEngine(
            runtime=self,
            limits=auto_limits,
            storage=auto_storage,
        )

        # Initialize Stage 6 Hermes-Brain Collaborative Trading Orchestrator
        collab_dir = self.root_dir / "data" / "collaboration"
        collab_dir.mkdir(parents=True, exist_ok=True)
        from nifty_trader.brain.context.context_memory import ContextMemoryStore
        from nifty_trader.brain.context.context_builder import HermesContextBuilder
        from nifty_trader.hermes.tool_bridge import HermesToolBridge
        from nifty_trader.hermes.collaboration import HermesBrainOrchestrator
        from nifty_trader.hermes.contracts import CollaborationAuditStore

        # Initialize Stage 8 Sensibull Paper-Trading Service
        paper_dir = self.root_dir / "data" / "paper_trading"
        paper_dir.mkdir(parents=True, exist_ok=True)
        from nifty_trader.paper.service import SensibullPaperTradingService
        from nifty_trader.paper.store import PaperTradeStore
        self.paper_store = PaperTradeStore(db_path=paper_dir / "paper_trades.db")
        self.paper_service = SensibullPaperTradingService(
            browser_agent=self.browser,
            store=self.paper_store,
        )

        self.memory_store = ContextMemoryStore(storage_path=collab_dir / "context_memory.json")
        self.tool_bridge = HermesToolBridge(
            market_service=self.market_service,
            browser_agent=self.browser,
            instruction_manager=self.instruction_manager,
            memory_store=self.memory_store,
            paper_service=self.paper_service,
        )
        self.context_builder = HermesContextBuilder(
            memory_store=self.memory_store,
        )
        self.collaborator = HermesBrainOrchestrator(
            brain_engine=self.brain,
            tool_bridge=self.tool_bridge,
            context_builder=self.context_builder,
            brain_storage=brain_storage,
            wait_policy=self.autonomous.wait_policy,
            audit_store=CollaborationAuditStore(storage_dir=collab_dir),
        )

        # Initialize Stage 9 Autonomous Position Monitor & Lifecycle Manager
        monitoring_dir = self.root_dir / "data" / "monitoring"
        monitoring_dir.mkdir(parents=True, exist_ok=True)
        from nifty_trader.monitoring.store import PositionMonitoringStore
        from nifty_trader.monitoring.orchestrator import AutonomousPositionMonitor
        self.monitoring_store = PositionMonitoringStore(db_path=monitoring_dir / "position_monitoring.db")
        self.position_monitor = AutonomousPositionMonitor(
            paper_service=self.paper_service,
            brain_engine=self.brain,
            paper_store=self.paper_store,
            monitoring_store=self.monitoring_store,
            market_service=self.market_service,
            wait_policy=self.autonomous.wait_policy,
        )

        # Initialize Stage 10 Performance Analysis & Experience Memory
        exp_dir = self.root_dir / "data" / "experience"
        exp_dir.mkdir(parents=True, exist_ok=True)
        from nifty_trader.experience.persistence import ExperienceStore
        from nifty_trader.experience.service import PerformanceAnalysisService
        self.experience_store = ExperienceStore(db_path=exp_dir / "experience.db")
        self.experience_service = PerformanceAnalysisService(
            paper_store=self.paper_store,
            monitoring_store=self.monitoring_store,
            experience_store=self.experience_store,
            context_memory_store=self.memory_store,
        )

        logger.info("NiftyTraderRuntime initialized in state: %s", self.state.value)

    def _load_environment(self, env_file: Optional[Path]) -> None:
        from dotenv import load_dotenv

        candidate = env_file or (self.root_dir / ".env")
        if candidate.exists():
            load_dotenv(candidate)
            return

        ref_env = Path("C:/Users/Administrator/AppData/Local/hermes/.env")
        if ref_env.exists():
            load_dotenv(ref_env)

    def _load_yaml(self, path: Path) -> Dict[str, Any]:
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        return {}

    async def get_status(self) -> Dict[str, Any]:
        """Returns runtime status, AI provider health, and browser session state."""
        provider_health = await self.router.health_check_all()
        try:
            browser_state = await self.browser.provider.get_page_state()
        except Exception:
            browser_state = {"status": "STOPPED", "url": "none"}

        hermes_integrity = self.hermes_version.verify_baseline_integrity()
        cache_stats = self.market_service.cache.get_stats()
        session_status = self.market_service.session_manager.get_session_status()

        return {
            "app": self.settings.get("app", {}).get("name", "NIFTY Autonomous Trader"),
            "version": self.settings.get("app", {}).get("version", "0.1.0"),
            "mode": self.settings.get("app", {}).get("mode", "RESEARCH"),
            "state": self.state.value,
            "hermes": {
                "commit": hermes_integrity.get("current_commit", "UNKNOWN"),
                "baseline": hermes_integrity.get("baseline_commit", "UNKNOWN"),
                "status": hermes_integrity.get("status", "UNKNOWN"),
            },
            "features_summary": self.features.get_status_summary(),
            "providers": provider_health,
            "browser": browser_state,
            "market_data": {
                "provider": self.market_service.provider.name,
                "session": session_status.value,
                "cache_1h_count": cache_stats.get(Timeframe.H1, 0),
                "cache_15m_count": cache_stats.get(Timeframe.M15, 0),
            },
            "instructions": {
                "active_count": len(self.instruction_manager.get_active_instructions()),
                "total_count": len(self.instruction_manager.list_instructions()),
            },
            "autonomous": self.autonomous.get_status(),
            "monitoring": {
                "open_monitored_positions": len(self.paper_store.get_open_positions()),
                "total_records": len(self.monitoring_store.list_records(limit=1000)),
            },
            "experience": {
                "total_experiences": len(self.experience_store.list_experiences(limit=1000)),
            },
            "risk_policies": self.settings.get("risk", {}),
        }

    async def test_brain(self, custom_scenario: Optional[str] = None) -> MarketObservationOutput:
        """Sends a test market scenario through ModelRouter to Gemini."""
        scenario = custom_scenario or (
            "NIFTY 50 is trading at 25,350. On the 1H timeframe, price is in an established "
            "bullish uptrend making higher highs above the 50 EMA. On the 15M timeframe, "
            "price has pulled back into the 20 EMA (25,340) on declining volume and formed a "
            "rejection hammer candle. No high-impact macroeconomic events are scheduled."
        )

        system_instruction = (
            "You are the reasoning brain for an autonomous NIFTY trading agent. "
            "Analyze market structure with institutional discipline. "
            "You are ALWAYS allowed to recommend 'WAIT' or 'NO_TRADE'. "
            "Never fabricate certainty. Strictly adhere to the requested JSON schema."
        )

        prompt = f"Analyze the following market condition and determine the appropriate action:\n\n{scenario}"

        return await self.router.route_structured(
            task_tier=TaskTier.MARKET_ANALYSIS,
            prompt=prompt,
            response_model=MarketObservationOutput,
            system_instruction=system_instruction,
        )

    async def verify_multimodal_perception(self, obs: BrowserObservation) -> VisualPerceptionOutput:
        """
        Sends the browser screenshot and page metadata to ModelRouter for neutral visual verification.
        Strictly prohibits trading decisions.
        """
        image_bytes = None
        if obs.screenshot_path and Path(obs.screenshot_path).exists():
            with open(obs.screenshot_path, "rb") as f:
                image_bytes = f.read()

        system_instruction = (
            "You are an objective computer vision perception observer. "
            "Describe the visible visual components, text, and layout of the supplied webpage screenshot. "
            "DO NOT produce trading advice, buy/sell recommendations, entry prices, or price predictions. "
            "Your output must be strictly factual, neutral, and descriptive matching the requested JSON schema."
        )

        prompt = (
            f"Page Title: {obs.page_title}\n"
            f"URL: {obs.url}\n"
            f"Source Type: {obs.source_type.value}\n\n"
            f"Describe what visual information, charts, or UI controls are visible on this page."
        )

        return await self.router.route_structured(
            task_tier=TaskTier.FAST_OBSERVE,
            prompt=prompt,
            response_model=VisualPerceptionOutput,
            system_instruction=system_instruction,
            image_bytes=image_bytes,
            image_mime_type="image/png",
        )

    async def start(self) -> None:
        """Starts the autonomous trading runtime."""
        logger.info("Starting NIFTY Autonomous Trader...")
        self.state = TradingState.STARTUP

        # Verify brain health
        health = await self.router.health_check_all()
        logger.info("Provider health check: %s", health)

        # Transition to initial observation state
        self.state = TradingState.OBSERVE_1H
        logger.info("Runtime transitioned to state: %s", self.state.value)

    async def sync_market_data(self) -> Dict[str, Any]:
        """Runs incremental synchronization for 1H and 15M candles."""
        return await self.market_service.sync_data()

    async def get_market_observation(
        self,
        timeframe: Optional[Timeframe] = None,
        cross_check: bool = True,
        include_sensibull: bool = False,
        sources: Optional[list[str]] = None,
    ) -> MarketObservation:
        """Collects market observation across sources (numerical, TradingView, Sensibull)."""
        return await self.market_service.observe_market(
            timeframe=timeframe,
            perform_cross_check=cross_check,
            include_sensibull=include_sensibull,
            sources=sources,
        )

    async def test_sensibull_observation(self) -> SourceObservationResult:
        """Executes a test observation on Sensibull option chain via browser."""
        if not self.sensibull_source:
            raise RuntimeError("Sensibull observation source is not configured.")
        return await self.sensibull_source.observe()

    async def analyze_market_perception(
        self,
        observation: MarketObservation,
        image_bytes: Optional[bytes] = None,
    ) -> MarketPerceptionOutput:
        """
        Sends the synthesized MarketObservation (1H context, 15M tactical state,
        Sensibull derivatives data, cross-check status, and active instructions)
        to Gemini for objective perception analysis.

        STRICT SAFETY ENFORCEMENT:
        Prohibits trading advice, order placement, or position recommendations.
        """
        system_instruction = (
            "You are an objective market perception engine for NIFTY Autonomous Trader. "
            "Your role is strictly to observe, understand, and describe market state, structural levels, "
            "regime classification, derivatives option chain context, and active operator instructions. "
            "CRITICAL INVARIANT: You are STRICTLY FORBIDDEN from generating trade recommendations, "
            "buy/sell orders, price targets, entry/exit points, or position-sizing commands. "
            "You only provide disciplined situational awareness adhering strictly to the requested schema."
        )

        active_instr = self.instruction_manager.format_instructions_for_prompt()
        sensi_info = observation.sensibull_summary
        if observation.sensibull_observation and observation.sensibull_observation.pcr is not None:
            sensi_info += f" ({observation.pcr_summary})"

        prompt = (
            f"Symbol: {observation.symbol}\n"
            f"Timestamp (IST): {observation.timestamp_ist.strftime('%Y-%m-%d %H:%M:%S IST')}\n"
            f"Session Status: {observation.market_status.value}\n"
            f"Data Quality: {observation.data_quality.value}\n"
            f"1H Structural Context:\n{observation.h1_summary}\n\n"
            f"15M Tactical State:\n{observation.m15_summary}\n\n"
            f"Sensibull Option Chain Context:\n{sensi_info}\n\n"
            f"Cross-Check Match: {observation.cross_check_match} (discrepancy: {observation.cross_check_discrepancy_pct}%)\n"
            f"Active Instructions:\n{active_instr}\n\n"
            f"Analyze the market condition objectively and populate the perception output schema."
        )

        return await self.router.route_structured(
            task_tier=TaskTier.MARKET_ANALYSIS,
            prompt=prompt,
            response_model=MarketPerceptionOutput,
            system_instruction=system_instruction,
            image_bytes=image_bytes,
            image_mime_type="image/png" if image_bytes else None,
        )

    async def get_unified_market_observation(
        self,
        symbol: str = "NIFTY",
        cross_check: bool = True,
        include_sensibull: bool = False,
        sources: Optional[list[str]] = None,
    ):
        """Assembles canonical UnifiedMarketObservation contract for Package 4 consumption."""
        return await self.market_service.get_unified_market_observation(
            symbol=symbol,
            include_browser=cross_check,
            include_sensibull=include_sensibull,
            sources=sources,
        )

    async def analyze_unified_observation(
        self,
        unified_obs,
        image_bytes: Optional[bytes] = None,
    ) -> MarketPerceptionOutput:
        """
        Sends the canonical UnifiedMarketObservation to Gemini for objective perception analysis.
        Package 4 boundary: receives only the canonical contract.
        """
        system_instruction = (
            "You are an objective market perception engine for NIFTY Autonomous Trader. "
            "You analyze canonical multi-source market observations (numerical candles, "
            "TradingView visuals, Sensibull option chain metrics, and operator instructions). "
            "CRITICAL INVARIANT: You are STRICTLY FORBIDDEN from generating trade recommendations, "
            "buy/sell orders, price targets, entry/exit points, or position-sizing commands. "
            "You only provide disciplined situational awareness adhering strictly to the requested schema."
        )

        c1h = unified_obs.numerical.latest_1h
        c15m = unified_obs.numerical.latest_15m
        h1_str = f"Close: {c1h.close:.2f} (O:{c1h.open:.2f}, H:{c1h.high:.2f}, L:{c1h.low:.2f}) at {c1h.timestamp_ist.strftime('%Y-%m-%d %H:%M IST')}" if c1h else "N/A"
        m15_str = f"Close: {c15m.close:.2f} (O:{c15m.open:.2f}, H:{c15m.high:.2f}, L:{c15m.low:.2f}) at {c15m.timestamp_ist.strftime('%Y-%m-%d %H:%M IST')}" if c15m else "N/A"

        active_instr = "\n".join(f"[{i.priority}] {i.text}" for i in unified_obs.manual_instruction_context) or "None"

        sensi_info = "Not observed"
        if unified_obs.visual.sensibull:
            s = unified_obs.visual.sensibull
            pcr_val = f"{s.pcr:.2f}" if s.pcr is not None else "N/A"
            mp_val = f"{s.max_pain:.0f}" if s.max_pain is not None else "N/A"
            sensi_info = f"Status={s.status.value}, PCR={pcr_val}, Max Pain={mp_val}"

        prompt = (
            f"Schema Version: {unified_obs.schema_version}\n"
            f"Observation ID: {unified_obs.observation_id}\n"
            f"Symbol: {unified_obs.instrument}\n"
            f"Observed At (IST): {unified_obs.observed_at_ist.strftime('%Y-%m-%d %H:%M:%S IST')}\n"
            f"Session Status: {unified_obs.session}\n"
            f"1H Structural Context:\n{h1_str}\n\n"
            f"15M Tactical State:\n{m15_str}\n\n"
            f"Sensibull Option Chain Context:\n{sensi_info}\n\n"
            f"Active Instructions:\n{active_instr}\n\n"
            f"Analyze the market condition objectively and populate the perception output schema."
        )

        return await self.router.route_structured(
            task_tier=TaskTier.MARKET_ANALYSIS,
            prompt=prompt,
            response_model=MarketPerceptionOutput,
            system_instruction=system_instruction,
            image_bytes=image_bytes,
            image_mime_type="image/png" if image_bytes else None,
        )

    def submit_instruction(
        self,
        text: str,
        priority: InstructionPriority = InstructionPriority.NORMAL,
        expires_in_hours: Optional[float] = 4.0,
        created_by: str = "human_operator",
    ) -> AgentInstruction:
        """Submits an instruction into the manual agent steering system."""
        return self.instruction_manager.submit_instruction(
            text=text,
            priority=priority,
            expires_in_hours=expires_in_hours,
            created_by=created_by,
        )

    def list_instructions(
        self,
        status: Optional[InstructionStatus] = None,
    ) -> list[AgentInstruction]:
        """Lists stored agent instructions filtered by status."""
        return self.instruction_manager.list_instructions(status=status)

    async def reason_market(
        self,
        unified_obs: Optional[UnifiedMarketObservation] = None,
        image_bytes: Optional[bytes] = None,
    ) -> BrainResult:
        """
        Executes Package 4 Trading Brain cognitive reasoning on canonical UnifiedMarketObservation.
        If unified_obs is not provided, gathers a fresh observation first.
        """
        if unified_obs is None:
            unified_obs = await self.get_unified_market_observation()
        return await self.brain.reason(observation=unified_obs, image_bytes=image_bytes)

    async def run_collaboration(
        self,
        session_id: Optional[str] = None,
        symbol: str = "NIFTY",
        max_turns: int = 3,
        force_initial_observation: Optional[UnifiedMarketObservation] = None,
    ):
        """
        Executes Stage 6 Hermes-Brain collaborative trading orchestration cycle.
        """
        import uuid
        session = session_id or f"sess_{uuid.uuid4().hex[:8]}"
        return await self.collaborator.run_collaboration_cycle(
            session_id=session,
            symbol=symbol,
            max_turns=max_turns,
            force_initial_observation=force_initial_observation,
        )


