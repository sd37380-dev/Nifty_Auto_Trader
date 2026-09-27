"""
Autonomous Position Monitor & Management Orchestrator.

Orchestrates the complete lifecycle:
OPEN POSITION -> OBSERVE -> BRAIN REASSESSMENT -> WAIT / CONTINUE / MODIFY / CLOSE -> POSITION CLOSED.
"""

from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional, Tuple

from nifty_trader.brain.contracts import (
    BrainInput,
    BrainOutput,
    BrainResult,
    PositionManagementAction,
    ReasoningState,
)
from nifty_trader.brain.engine import TradingBrainEngine
from nifty_trader.monitoring.context_builder import PositionMonitoringContextBuilder
from nifty_trader.monitoring.contracts import (
    MonitoringState,
    PositionEvent,
    PositionMonitoringRecord,
)
from nifty_trader.monitoring.store import PositionMonitoringStore
from nifty_trader.paper.contracts import (
    PaperPosition,
    PaperPositionStatus,
    SensibullEnvironmentType,
)
from nifty_trader.paper.service import SensibullPaperTradingService
from nifty_trader.paper.store import PaperTradeStore

logger = logging.getLogger(__name__)


class AutonomousPositionMonitor:
    """
    Autonomous operator managing open paper trades.
    Continuously provides the AI Brain with position-aware context, waits patiently for meaningful
    changes, verifies Sensibull ground truth, and carries out only authorized management actions.
    """

    def __init__(
        self,
        paper_service: SensibullPaperTradingService,
        brain_engine: TradingBrainEngine,
        paper_store: Optional[PaperTradeStore] = None,
        monitoring_store: Optional[PositionMonitoringStore] = None,
        context_builder: Optional[PositionMonitoringContextBuilder] = None,
        market_service: Optional[Any] = None,
        wait_policy: Optional[Any] = None,
    ):
        self.paper_service = paper_service
        self.brain = brain_engine
        self.paper_store = paper_store or paper_service.store
        self.monitoring_store = monitoring_store or PositionMonitoringStore()
        self.context_builder = context_builder or PositionMonitoringContextBuilder(self.paper_store)
        self.market_service = market_service
        self.wait_policy = wait_policy

        # In-memory last reassessed timestamp per position to prevent redundant model calls
        self._last_reassessed_at: Dict[str, datetime] = {}
        self._last_known_ltp: Dict[str, float] = {}

    async def monitor_once(
        self,
        force_reassessment: bool = False,
    ) -> List[PositionMonitoringRecord]:
        """
        Executes a single autonomous monitoring and reassessment pass across all open positions.
        """
        records: List[PositionMonitoringRecord] = []
        open_positions = self.paper_store.get_open_positions()

        if not open_positions:
            logger.info("No open paper positions to monitor.")
            return records

        # 1. Verify Remote Sensibull State and reconcile
        try:
            summary, discrepancies = await self.paper_service.sync_and_reconcile()
            if discrepancies:
                for disc in discrepancies:
                    self._emit_event(
                        "reconciliation-required",
                        disc.hermes_state.get("position_id") if disc.hermes_state else "UNKNOWN",
                        {"discrepancy": disc.discrepancy_type, "action": disc.resolution_action},
                    )
        except Exception as sync_err:
            logger.warning("Sensibull remote sync encountered issue: %s", sync_err)

        # Refresh local open positions after reconciliation
        open_positions = self.paper_store.get_open_positions()
        if not open_positions:
            logger.info("All positions closed after reconciliation.")
            return records

        # 2. Gather Fresh Market Perception
        observation = None
        if self.market_service:
            try:
                if hasattr(self.market_service, "get_unified_market_observation"):
                    observation = await self.market_service.get_unified_market_observation(
                        symbol="NIFTY",
                        include_browser=True,
                        include_sensibull=True,
                    )
                elif hasattr(self.market_service, "get_unified_observation"):
                    observation = await self.market_service.get_unified_observation("NIFTY")
            except Exception as obs_err:
                logger.warning("Market observation collection encountered error: %s", obs_err)

        # Fallback observation if market_service is mock or unavailable
        if observation is None:
            from nifty_trader.contracts.builder import UnifiedObservationBuilder
            builder = UnifiedObservationBuilder()
            observation = builder.build(symbol="NIFTY")

        # 3. Process Each Open Position
        for pos in open_positions:
            record = await self._monitor_position(
                position=pos,
                observation=observation,
                force_reassessment=force_reassessment,
            )
            records.append(record)

        return records

    async def _monitor_position(
        self,
        position: PaperPosition,
        observation: Any,
        force_reassessment: bool = False,
    ) -> PositionMonitoringRecord:
        """Monitors and reassesses a single position."""
        pos_id = position.position_id
        now = datetime.now(timezone.utc)
        duration_mins = max(0.0, (now - position.first_detected_at).total_seconds() / 60.0)

        record = PositionMonitoringRecord(
            position_id=pos_id,
            symbol=position.symbol,
            strike=position.strike,
            option_type=position.option_type.value,
            lots=position.lots,
            quantity=position.quantity,
            entry_price=position.avg_price,
            current_price=position.current_ltp,
            unrealized_pnl=position.unrealized_pnl,
            pnl_percentage=position.pnl_percentage,
            holding_duration_minutes=round(duration_mins, 1),
            monitoring_state=MonitoringState.MONITORING,
            market_observation_id=getattr(observation, "observation_id", None),
        )

        # Check if meaningful change occurred
        should_reassess = force_reassessment
        if not should_reassess:
            last_reassessed = self._last_reassessed_at.get(pos_id)
            if last_reassessed is None:
                should_reassess = True
            else:
                last_price = self._last_known_ltp.get(pos_id, position.current_ltp)
                price_move_pct = abs(position.current_ltp - last_price) / last_price if last_price > 0 else 0.0
                # Meaningful move >= 1.0% on option premium or 15 mins passed
                time_elapsed_secs = (now - last_reassessed).total_seconds()
                if price_move_pct >= 0.01 or time_elapsed_secs >= 900.0:
                    should_reassess = True

        if not should_reassess:
            # Patiently continue monitoring / waiting without calling AI Brain
            record.monitoring_state = MonitoringState.WAITING
            record.wake_reason = "No meaningful change in price structure or P&L."
            self.monitoring_store.save_record(record)
            self._emit_event("monitoring-waiting", pos_id, {"reason": record.wake_reason})
            return record

        # Build position-aware BrainInput
        brain_input = self.context_builder.build_context(
            position=position,
            observation=observation,
        )

        record.monitoring_state = MonitoringState.REASSESSING
        self._emit_event("brain-reassessment-requested", pos_id, {"ltp": position.current_ltp, "pnl": position.unrealized_pnl})

        # Query Trading Brain for cognitive reassessment
        brain_result: BrainResult = await self.brain.analyze(brain_input)
        record.brain_request_id = brain_result.output.brain_request_id if brain_result.output else None

        if not brain_result.success or not brain_result.output:
            record.monitoring_state = MonitoringState.MONITORING
            record.error = brain_result.failure.message if brain_result.failure else "Brain reasoning failed."
            self.monitoring_store.save_record(record)
            self._emit_event("monitoring-error", pos_id, {"error": record.error})
            return record

        output: BrainOutput = brain_result.output
        record.brain_reasoning_state = output.reasoning_state
        record.brain_summary = output.reasoning_summary.interpretation if output.reasoning_summary else None

        # Determine Position Action
        action = output.position_action
        if action is None:
            # Fallback derivation from reasoning state
            if output.reasoning_state == ReasoningState.WAIT:
                action = PositionManagementAction.WAIT
            elif output.reasoning_state in [ReasoningState.WATCH, ReasoningState.DEVELOPING]:
                action = PositionManagementAction.WATCH
            else:
                action = PositionManagementAction.CONTINUE

        record.brain_position_action = action
        self._last_reassessed_at[pos_id] = now
        self._last_known_ltp[pos_id] = position.current_ltp

        # Execute Position Management Action
        if action == PositionManagementAction.CLOSE:
            record.monitoring_state = MonitoringState.CLOSE_REQUESTED
            self._emit_event("position-close-requested", pos_id, {"reason": record.brain_summary})

            # Execute square-off via Stage 8
            success, closed_pos = await self.paper_service.close_position(
                position_id=pos_id,
                reason=record.brain_summary or "Brain exit signal",
            )
            if success and closed_pos:
                record.monitoring_state = MonitoringState.CLOSED
                record.action_executed = "CLOSE_POSITION"
                record.action_result = f"Successfully squared off. Realized P&L: Rs. {closed_pos.realized_pnl:+,.2f}"
                self._emit_event("position-closed", pos_id, {"realized_pnl": closed_pos.realized_pnl})
            else:
                record.monitoring_state = MonitoringState.RECONCILIATION_REQUIRED
                record.action_result = "Square-off execution could not be verified."
                self._emit_event("monitoring-error", pos_id, {"error": "Square-off failed to verify"})

        elif action == PositionManagementAction.WAIT:
            record.monitoring_state = MonitoringState.WAITING
            record.wake_reason = "Brain requested WAIT for candle completion or confirmation."
            self._emit_event("monitoring-waiting", pos_id, {"reason": record.wake_reason})

        elif action == PositionManagementAction.WATCH:
            record.monitoring_state = MonitoringState.MONITORING
            record.wake_reason = "Brain actively watching key structural level."
            self._emit_event("position-observed", pos_id, {"action": "WATCH"})

        elif action == PositionManagementAction.CONTINUE:
            record.monitoring_state = MonitoringState.MONITORING
            self._emit_event("position-observed", pos_id, {"action": "CONTINUE"})

        self.monitoring_store.save_record(record)
        return record

    async def reconcile_positions(self) -> Tuple[Any, List[Any]]:
        """Verifies local positions against remote Sensibull ground truth and resolves discrepancies."""
        summary, discrepancies = await self.paper_service.sync_and_reconcile()
        for disc in discrepancies:
            self._emit_event(
                "reconciliation-resolved",
                disc.hermes_state.get("position_id") if disc.hermes_state else "UNKNOWN",
                {"discrepancy": disc.discrepancy_type, "action": disc.resolution_action},
            )
        return summary, discrepancies

    def _emit_event(self, event_type: str, position_id: str, details: Dict[str, Any]) -> None:
        """Emits and logs an auditable event."""
        event = PositionEvent(
            event_type=event_type,
            position_id=position_id,
            details=details,
        )
        self.monitoring_store.save_event(event)
        logger.info("Stage 9 Event [%s] on position %s: %s", event_type, position_id, details)
