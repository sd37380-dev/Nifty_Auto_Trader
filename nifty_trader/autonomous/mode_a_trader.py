"""
Mode A (EXISTING_SYSTEM) Autonomous Trader.

Coordinates the existing Package 5 AutonomousObservationEngine and Package 4 Trading Brain:
Observation -> Understanding -> Candle/Context Analysis -> Brain Reasoning ->
TradeCandidate -> TradeIntent (EXISTING_SYSTEM) -> Deterministic Safety Guard ->
Sensibull Paper Execution -> TradeAuditStore persistence.

STRICT INVARIANTS:
1. Mode A represents the original architecture and operates independently of Mode B.
2. Mode identity EXISTING_SYSTEM is stamped on all intents, orders, positions, and events.
3. research_id is strictly None for Mode A.
4. Passes through the unmodified DeterministicSafetyGuard before execution.
"""

import asyncio
from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional
import uuid

from nifty_trader.autonomous.contracts import AutonomousState, CycleResult
from nifty_trader.autonomous.engine import AutonomousObservationEngine
from nifty_trader.brain.contracts import Direction, TradeCandidate
from nifty_trader.core.modes import (
    TradeEvent,
    TradeIntent,
    TradeLifecycleEventType,
    TradeRecord,
    TradingMode,
)
from nifty_trader.core.trade_store import TradeAuditStore
from nifty_trader.paper.contracts import (
    PaperAction,
    PaperOptionType,
    PaperOrderStatus,
    PaperPosition,
    PaperPositionStatus,
    PaperTradeOrder,
    PaperTradeOrderRequest,
)
from nifty_trader.paper.executor import SensibullPaperExecutor
from nifty_trader.paper.store import PaperTradeStore
from nifty_trader.safety.guard import DeterministicSafetyGuard

logger = logging.getLogger(__name__)


class ExistingSystemTrader:
    """
    Autonomous trading agent executing Mode A (EXISTING_SYSTEM).
    Bridges the perception and reasoning loop into validated paper execution.
    """

    def __init__(
        self,
        engine: AutonomousObservationEngine,
        safety_guard: Optional[DeterministicSafetyGuard] = None,
        audit_store: Optional[TradeAuditStore] = None,
        paper_store: Optional[PaperTradeStore] = None,
        paper_executor: Optional[SensibullPaperExecutor] = None,
        poll_interval_seconds: float = 60.0,
    ):
        self.engine = engine
        self.paper_store = paper_store or PaperTradeStore()
        self.audit_store = audit_store or TradeAuditStore()
        self.safety_guard = safety_guard or DeterministicSafetyGuard(store=self.paper_store)
        self.paper_executor = paper_executor
        self.poll_interval_seconds = poll_interval_seconds

        self._stop_event = asyncio.Event()
        self._is_running = False

    def formulate_trade_intent(
        self,
        candidate: TradeCandidate,
        ref_price: float = 22650.0,
        symbol: str = "NIFTY",
    ) -> TradeIntent:
        """
        Transforms a TradeCandidate from Package 4 BrainOutput into a concrete TradeIntent.
        """
        strike_step = 100.0 if "BANKNIFTY" in symbol.upper() else 50.0
        atm_strike = round(ref_price / strike_step) * strike_step

        is_bullish = candidate.direction == Direction.LONG or str(candidate.direction).upper() in ["LONG", "BULLISH"]
        option_type = "CE" if is_bullish else "PE"

        invalidation_text = "; ".join(candidate.invalidation_conditions) if candidate.invalidation_conditions else "Thesis invalidated by opposing structure"
        evidence_list = [ref.description for ref in candidate.supporting_evidence] if candidate.supporting_evidence else []

        conf_val = candidate.reasoning_confidence.value
        score = round(conf_val * 100.0, 2) if is_bullish else round(-conf_val * 100.0, 2)

        return TradeIntent(
            mode=TradingMode.EXISTING_SYSTEM,
            instrument=symbol,
            direction="BUY",
            setup=candidate.market_context or "PRICE_ACTION_STRUCTURE",
            entry_thesis=candidate.thesis,
            invalidation=invalidation_text,
            evidence_refs=evidence_list,
            assessment_id=candidate.candidate_id,
            research_id=None,  # Strictly None for Mode A
            score=score,
            confidence=conf_val,
            expiry="CURRENT_WEEK",
            strike=atm_strike,
            option_type=option_type,
            lots=1,
            limit_price=100.0,
            stop_loss_price=70.0,
            target_price=190.0,  # 1:3 R:R
            metadata={
                "candidate_id": candidate.candidate_id,
                "direction": candidate.direction.value,
                "confidence_basis": candidate.reasoning_confidence.basis,
            },
        )

    async def execute_cycle(self, symbol: str = "NIFTY") -> Optional[TradeIntent]:
        """
        Executes one observation cycle in Mode A.
        If a trade candidate is reached, validates it with Safety Guard and executes paper trade.
        """
        logger.info("[MODE A] Executing observation & reasoning cycle for %s...", symbol)
        try:
            # 1. Execute engine cycle
            cycle_result: CycleResult = await self.engine.execute_single_cycle()

            if not cycle_result.success:
                logger.warning("[MODE A] Observation cycle returned non-success: %s", cycle_result.failure)
                return None

            # 2. Check if a CANDIDATE was produced
            if cycle_result.state != AutonomousState.CANDIDATE_READY:
                logger.info("[MODE A] Cycle completed with state %s. No candidate to execute.", cycle_result.state.value)
                return None

            brain_output = cycle_result.brain_output
            if not brain_output or not brain_output.candidate:
                logger.info("[MODE A] State is CANDIDATE_READY but candidate object is missing.")
                return None

            candidate = brain_output.candidate

            # 3. Log assessment event
            self.audit_store.log_event(TradeEvent(
                mode=TradingMode.EXISTING_SYSTEM,
                event_type=TradeLifecycleEventType.ASSESSMENT_CREATED,
                assessment_id=candidate.candidate_id,
                research_id=None,
                details={"thesis": candidate.thesis, "direction": candidate.direction.value, "confidence": candidate.reasoning_confidence.value},
            ))

            # 4. Formulate TradeIntent
            ref_price = 22650.0
            if self.engine._previous_observation and self.engine._previous_observation.numerical.latest_15m:
                ref_price = self.engine._previous_observation.numerical.latest_15m.close

            intent = self.formulate_trade_intent(candidate, ref_price=ref_price, symbol=symbol)

            self.audit_store.log_event(TradeEvent(
                mode=TradingMode.EXISTING_SYSTEM,
                event_type=TradeLifecycleEventType.INTENT_FORMULATED,
                assessment_id=intent.assessment_id,
                research_id=None,
                trade_intent_id=intent.trade_intent_id,
                details={"direction": intent.direction, "option_type": intent.option_type, "strike": intent.strike},
            ))

            # 5. Position Collision Detection across modes
            open_positions = self.paper_store.get_open_positions()
            allowed, collision_reason = self.audit_store.handle_position_collision(intent, open_positions)
            if not allowed:
                logger.warning("[MODE A] Position collision detected and blocked: %s", collision_reason)
                blocked_record = TradeRecord(
                    decision_source=TradingMode.EXISTING_SYSTEM,
                    trade_intent_id=intent.trade_intent_id,
                    assessment_id=intent.assessment_id,
                    research_id=None,
                    instrument=intent.instrument,
                    direction=intent.direction,
                    strike=intent.strike,
                    option_type=intent.option_type,
                    entry=intent.limit_price,
                    stop_loss=intent.stop_loss_price,
                    target=intent.target_price,
                    score=intent.score,
                    confidence=intent.confidence,
                    thesis=intent.entry_thesis,
                    safety_decision="BLOCKED",
                    safety_block_reason=collision_reason,
                    execution_status="REJECTED",
                    pnl=0.0,
                    outcome="COLLISION_PREVENTED",
                )
                self.audit_store.save_trade(blocked_record)
                return intent

            # 6. Deterministic Safety Guard Validation
            order_req = intent.to_order_request()
            safety_result = self.safety_guard.validate_order_request(order_req)

            if not safety_result.passed:
                logger.warning(
                    "[MODE A] Safety Guard REJECTED TradeIntent [%s]: %s (Code: %s)",
                    intent.trade_intent_id,
                    safety_result.reason,
                    safety_result.rejection_code,
                )
                self.audit_store.log_event(TradeEvent(
                    mode=TradingMode.EXISTING_SYSTEM,
                    event_type=TradeLifecycleEventType.SAFETY_BLOCKED,
                    assessment_id=intent.assessment_id,
                    research_id=None,
                    trade_intent_id=intent.trade_intent_id,
                    details={"reason": safety_result.reason, "code": safety_result.rejection_code},
                ))
                blocked_record = TradeRecord(
                    decision_source=TradingMode.EXISTING_SYSTEM,
                    trade_intent_id=intent.trade_intent_id,
                    assessment_id=intent.assessment_id,
                    research_id=None,
                    instrument=intent.instrument,
                    direction=intent.direction,
                    strike=intent.strike,
                    option_type=intent.option_type,
                    entry=intent.limit_price,
                    stop_loss=intent.stop_loss_price,
                    target=intent.target_price,
                    score=intent.score,
                    confidence=intent.confidence,
                    thesis=intent.entry_thesis,
                    safety_decision="BLOCKED",
                    safety_block_reason=safety_result.reason,
                    execution_status="REJECTED",
                    pnl=0.0,
                    outcome="SAFETY_REJECTED",
                )
                self.audit_store.save_trade(blocked_record)
                return intent

            # Safety Guard PASSED
            self.audit_store.log_event(TradeEvent(
                mode=TradingMode.EXISTING_SYSTEM,
                event_type=TradeLifecycleEventType.SAFETY_VALIDATED,
                assessment_id=intent.assessment_id,
                research_id=None,
                trade_intent_id=intent.trade_intent_id,
                details={"risk_approved": True},
            ))

            # 7. Paper Execution via Sensibull
            self.audit_store.log_event(TradeEvent(
                mode=TradingMode.EXISTING_SYSTEM,
                event_type=TradeLifecycleEventType.EXECUTION_ATTEMPTED,
                assessment_id=intent.assessment_id,
                research_id=None,
                trade_intent_id=intent.trade_intent_id,
                details={"platform": "Sensibull Virtual Portfolio"},
            ))

            if self.paper_executor:
                order = await self.paper_executor.execute_paper_order(order_req)
            else:
                # Direct store execution fallback
                order = PaperTradeOrder(
                    request_id=order_req.request_id,
                    idempotency_key=order_req.idempotency_key,
                    symbol=order_req.symbol,
                    expiry=order_req.expiry,
                    strike=order_req.strike,
                    option_type=order_req.option_type,
                    action=order_req.action,
                    lots=order_req.lots,
                    quantity=order_req.quantity,
                    entry_price=order_req.limit_price or 100.0,
                    mode=TradingMode.EXISTING_SYSTEM.value,
                    trade_intent_id=intent.trade_intent_id,
                    assessment_id=intent.assessment_id,
                    research_id=None,
                    status=PaperOrderStatus.OPEN,
                    status_reason="Paper trade executed via Existing System Trader.",
                    verified_at=datetime.now(timezone.utc),
                )
                self.paper_store.save_order(order)
                pos = PaperPosition(
                    symbol=order_req.symbol,
                    expiry=order_req.expiry,
                    strike=order_req.strike,
                    option_type=order_req.option_type,
                    action=order_req.action,
                    lots=order_req.lots,
                    quantity=order_req.quantity,
                    avg_price=order.entry_price or 100.0,
                    current_ltp=order.entry_price or 100.0,
                    mode=TradingMode.EXISTING_SYSTEM.value,
                    trade_intent_id=intent.trade_intent_id,
                    assessment_id=intent.assessment_id,
                    research_id=None,
                    status=PaperPositionStatus.OPEN,
                )
                self.paper_store.save_position(pos)

            # Record TradeRecord in Audit Store
            trade_record = TradeRecord(
                decision_source=TradingMode.EXISTING_SYSTEM,
                trade_intent_id=intent.trade_intent_id,
                assessment_id=intent.assessment_id,
                research_id=None,
                instrument=intent.instrument,
                direction=intent.direction,
                strike=intent.strike,
                option_type=intent.option_type,
                entry=order.entry_price or intent.limit_price,
                stop_loss=intent.stop_loss_price,
                target=intent.target_price,
                score=intent.score,
                confidence=intent.confidence,
                thesis=intent.entry_thesis,
                safety_decision="APPROVED",
                execution_status="OPEN" if order.status == PaperOrderStatus.OPEN else order.status.value,
                entry_time=order.verified_at or datetime.now(timezone.utc),
                pnl=0.0,
                outcome="ACTIVE",
            )
            self.audit_store.save_trade(trade_record)

            self.audit_store.log_event(TradeEvent(
                mode=TradingMode.EXISTING_SYSTEM,
                event_type=TradeLifecycleEventType.ORDER_SUBMITTED,
                assessment_id=intent.assessment_id,
                research_id=None,
                trade_intent_id=intent.trade_intent_id,
                trade_id=trade_record.trade_id,
                details={"order_id": order.order_id, "status": order.status.value},
            ))

            logger.info(
                "[MODE A] Trade executed successfully: %s %s strike %.1f at ₹%.2f (Trade ID: %s)",
                intent.instrument,
                intent.option_type,
                intent.strike or 0.0,
                order.entry_price or 0.0,
                trade_record.trade_id,
            )
            return intent

        except Exception as e:
            logger.error("[MODE A] Error in observation/trading cycle: %s", e, exc_info=True)
            self.audit_store.log_event(TradeEvent(
                mode=TradingMode.EXISTING_SYSTEM,
                event_type=TradeLifecycleEventType.EXECUTION_FAILED,
                details={"error": str(e)},
            ))
            return None

    async def run_loop(self, symbol: str = "NIFTY") -> None:
        """
        Continuous observation and trading loop for Mode A.
        Runs until stopped via stop().
        """
        self._is_running = True
        self._stop_event.clear()
        logger.info("[MODE A] Existing System Trader loop started for %s.", symbol)

        # Auto-activate Local Option Paper Simulator
        try:
            from nifty_trader.simulator.service import get_simulator_service
            get_simulator_service().start()
            logger.info("[SIMULATOR] Auto-activated local paper simulator service alongside Mode A.")
        except Exception as sim_e:
            logger.debug("Simulator auto-start: %s", sim_e)

        while not self._stop_event.is_set():
            try:
                await self.execute_cycle(symbol=symbol)
            except Exception as e:
                logger.error("[MODE A] Error in autonomous loop iteration: %s", e, exc_info=True)

            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self.poll_interval_seconds)
            except asyncio.TimeoutError:
                pass

        self._is_running = False
        logger.info("[MODE A] Existing System Trader loop stopped.")

    def stop(self) -> None:
        """Signals the autonomous loop to terminate gracefully."""
        self._stop_event.set()
        self._is_running = False
