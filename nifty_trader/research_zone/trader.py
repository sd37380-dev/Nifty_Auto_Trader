"""
Hermes Research Trader (Mode B Autonomous Trading Engine).

Executes the autonomous cycle for Mode B:
Dhan Data Ingestion -> Data Engineering -> Pattern Discovery ->
Hypothesis Testing -> Contradiction Search -> HermesResearchAssessment ->
TradeIntent (HERMES_RESEARCH) -> Deterministic Safety Guard ->
Sensibull Paper Execution -> ResearchMemory & TradeAuditStore persistence.

STRICT INVARIANTS:
1. Mode B is completely independent of Mode A.
2. Mode identity HERMES_RESEARCH and research_id are stamped on all intents, orders, positions, and events.
3. Passes through the unmodified DeterministicSafetyGuard before execution.
4. Operates strictly in paper trading (Sensibull Virtual Portfolio). No live Dhan trading.
"""

import asyncio
from datetime import datetime, timezone
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
import uuid

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
from nifty_trader.research_zone.contracts import (
    HermesResearchAssessment,
    HypothesisStatus,
    MarketDirection,
)
from nifty_trader.research_zone.dhan_adapter import DhanDataAdapter, MockDhanDataAdapter
from nifty_trader.research_zone.service import HermesResearchZoneService
from nifty_trader.safety.guard import DeterministicSafetyGuard

logger = logging.getLogger(__name__)


class HermesResearchTrader:
    """
    Autonomous trading agent executing Mode B (HERMES_RESEARCH).
    Transforms empirical research findings into actionable paper trades.
    """

    def __init__(
        self,
        service: Optional[HermesResearchZoneService] = None,
        safety_guard: Optional[DeterministicSafetyGuard] = None,
        audit_store: Optional[TradeAuditStore] = None,
        paper_store: Optional[PaperTradeStore] = None,
        paper_executor: Optional[SensibullPaperExecutor] = None,
        min_score_threshold: float = 20.0,
        min_confidence_threshold: float = 0.50,
        poll_interval_seconds: float = 60.0,
    ):
        self.paper_store = paper_store or PaperTradeStore()
        self.audit_store = audit_store or TradeAuditStore()
        self.safety_guard = safety_guard or DeterministicSafetyGuard(store=self.paper_store)
        self.service = service or HermesResearchZoneService()
        self.paper_executor = paper_executor
        self.min_score_threshold = min_score_threshold
        self.min_confidence_threshold = min_confidence_threshold
        self.poll_interval_seconds = poll_interval_seconds

        self._stop_event = asyncio.Event()
        self._is_running = False

    def formulate_trade_intent(
        self,
        assessment: HermesResearchAssessment,
        symbol: str = "NIFTY",
    ) -> Optional[TradeIntent]:
        """
        Formulates a TradeIntent from a valid HermesResearchAssessment.
        Returns None if assessment direction is NEUTRAL or below confidence threshold.
        """
        if assessment.direction == MarketDirection.NEUTRAL:
            logger.info("[MODE B] Assessment is NEUTRAL. No trade intent formulated.")
            return None

        if assessment.confidence < self.min_confidence_threshold:
            logger.info(
                "[MODE B] Assessment confidence %.2f below threshold %.2f. Skipping.",
                assessment.confidence,
                self.min_confidence_threshold,
            )
            return None

        if abs(assessment.total_score) < self.min_score_threshold:
            logger.info(
                "[MODE B] Assessment absolute score %.1f below threshold %.1f. Skipping.",
                abs(assessment.total_score),
                self.min_score_threshold,
            )
            return None

        # Determine option type and ATM strike
        # Reference spot price from metadata or defaults
        spot_price = float(assessment.metadata.get("spot_price", 22650.0))
        strike_step = 100.0 if "BANKNIFTY" in symbol.upper() else 50.0
        atm_strike = round(spot_price / strike_step) * strike_step

        option_type = "CE" if assessment.direction == MarketDirection.BULLISH else "PE"

        invalidation_text = "; ".join(assessment.contradictory_evidence) if assessment.contradictory_evidence else "Statistically rejected edge or opposing momentum."

        intent = TradeIntent(
            mode=TradingMode.HERMES_RESEARCH,
            instrument=symbol,
            direction="BUY",
            setup=f"RESEARCH_{assessment.direction.value}_{assessment.timeframe}",
            entry_thesis=assessment.trade_finding or f"Quantitative research edge ({assessment.total_score:.1f} score, {assessment.confidence:.2f} conf)",
            invalidation=invalidation_text,
            evidence_refs=assessment.supporting_evidence,
            assessment_id=assessment.research_id,
            research_id=assessment.metadata.get("question_id", assessment.research_id),
            score=assessment.total_score,
            confidence=assessment.confidence,
            expiry=assessment.metadata.get("expiry", "CURRENT_WEEK"),
            strike=atm_strike,
            option_type=option_type,
            lots=1,
            limit_price=100.0,
            stop_loss_price=70.0,
            target_price=190.0,  # 1:3 R:R ratio
            metadata={
                "research_assessment_id": assessment.research_id,
                "research_segments_count": len(assessment.segments),
                "total_score": assessment.total_score,
                "uncertainties": assessment.uncertainty,
            },
        )
        return intent

    async def execute_cycle(
        self,
        symbol: str = "NIFTY",
        timeframe: str = "15M",
        days: int = 15,
    ) -> Optional[TradeIntent]:
        """
        Executes one complete Mode B autonomous cycle:
        Research -> Assessment -> Intent -> Collision Check -> Safety Guard -> Sensibull Paper Execution.
        """
        logger.info("[MODE B] Starting Hermes Research autonomous cycle for %s (%s)...", symbol, timeframe)
        try:
            # 1. Run Research Cycle in isolated Research Zone
            assessment = self.service.run_full_research_cycle(
                topic=f"Autonomous {symbol} Quantitative Edge Discovery",
                symbol=symbol,
                timeframe=timeframe,
                days=days,
            )

            # Log assessment event
            self.audit_store.log_event(TradeEvent(
                mode=TradingMode.HERMES_RESEARCH,
                event_type=TradeLifecycleEventType.ASSESSMENT_CREATED,
                assessment_id=assessment.research_id,
                research_id=assessment.metadata.get("question_id", assessment.research_id),
                details={"score": assessment.total_score, "confidence": assessment.confidence, "direction": assessment.direction.value},
            ))

            # 2. Formulate Trade Intent
            intent = self.formulate_trade_intent(assessment, symbol=symbol)
            if not intent:
                return None

            self.audit_store.log_event(TradeEvent(
                mode=TradingMode.HERMES_RESEARCH,
                event_type=TradeLifecycleEventType.INTENT_FORMULATED,
                assessment_id=intent.assessment_id,
                research_id=intent.research_id,
                trade_intent_id=intent.trade_intent_id,
                details={"direction": intent.direction, "option_type": intent.option_type, "strike": intent.strike},
            ))

            # 3. Position Collision Detection across modes
            open_positions = self.paper_store.get_open_positions()
            allowed, collision_reason = self.audit_store.handle_position_collision(intent, open_positions)
            if not allowed:
                logger.warning("[MODE B] Position collision detected and blocked: %s", collision_reason)
                blocked_record = TradeRecord(
                    decision_source=TradingMode.HERMES_RESEARCH,
                    trade_intent_id=intent.trade_intent_id,
                    assessment_id=intent.assessment_id,
                    research_id=intent.research_id,
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

            # 4. Deterministic Safety Guard Validation
            order_req = intent.to_order_request()
            safety_result = self.safety_guard.validate_order_request(order_req)

            if not safety_result.passed:
                logger.warning(
                    "[MODE B] Safety Guard REJECTED TradeIntent [%s]: %s (Code: %s)",
                    intent.trade_intent_id,
                    safety_result.reason,
                    safety_result.rejection_code,
                )
                self.audit_store.log_event(TradeEvent(
                    mode=TradingMode.HERMES_RESEARCH,
                    event_type=TradeLifecycleEventType.SAFETY_BLOCKED,
                    assessment_id=intent.assessment_id,
                    research_id=intent.research_id,
                    trade_intent_id=intent.trade_intent_id,
                    details={"reason": safety_result.reason, "code": safety_result.rejection_code},
                ))
                blocked_record = TradeRecord(
                    decision_source=TradingMode.HERMES_RESEARCH,
                    trade_intent_id=intent.trade_intent_id,
                    assessment_id=intent.assessment_id,
                    research_id=intent.research_id,
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
                mode=TradingMode.HERMES_RESEARCH,
                event_type=TradeLifecycleEventType.SAFETY_VALIDATED,
                assessment_id=intent.assessment_id,
                research_id=intent.research_id,
                trade_intent_id=intent.trade_intent_id,
                details={"risk_approved": True},
            ))

            # 5. Paper Execution via Sensibull
            self.audit_store.log_event(TradeEvent(
                mode=TradingMode.HERMES_RESEARCH,
                event_type=TradeLifecycleEventType.EXECUTION_ATTEMPTED,
                assessment_id=intent.assessment_id,
                research_id=intent.research_id,
                trade_intent_id=intent.trade_intent_id,
                details={"platform": "Sensibull Virtual Portfolio"},
            ))

            if self.paper_executor:
                order = await self.paper_executor.execute_paper_order(order_req)
            else:
                # Direct store execution fallback for standalone/mock testing
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
                    mode=TradingMode.HERMES_RESEARCH.value,
                    trade_intent_id=intent.trade_intent_id,
                    assessment_id=intent.assessment_id,
                    research_id=intent.research_id,
                    status=PaperOrderStatus.OPEN,
                    status_reason="Paper trade executed via Hermes Research Trader.",
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
                    mode=TradingMode.HERMES_RESEARCH.value,
                    trade_intent_id=intent.trade_intent_id,
                    assessment_id=intent.assessment_id,
                    research_id=intent.research_id,
                    status=PaperPositionStatus.OPEN,
                )
                self.paper_store.save_position(pos)

            # Record TradeRecord in Audit Store
            trade_record = TradeRecord(
                decision_source=TradingMode.HERMES_RESEARCH,
                trade_intent_id=intent.trade_intent_id,
                assessment_id=intent.assessment_id,
                research_id=intent.research_id,
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
                mode=TradingMode.HERMES_RESEARCH,
                event_type=TradeLifecycleEventType.ORDER_SUBMITTED,
                assessment_id=intent.assessment_id,
                research_id=intent.research_id,
                trade_intent_id=intent.trade_intent_id,
                trade_id=trade_record.trade_id,
                details={"order_id": order.order_id, "status": order.status.value},
            ))

            logger.info(
                "[MODE B] Trade executed successfully: %s %s strike %.1f at ₹%.2f (Trade ID: %s)",
                intent.instrument,
                intent.option_type,
                intent.strike or 0.0,
                order.entry_price or 0.0,
                trade_record.trade_id,
            )
            return intent

        except Exception as e:
            logger.error("[MODE B] Research cycle encountered error: %s", e, exc_info=True)
            self.audit_store.log_event(TradeEvent(
                mode=TradingMode.HERMES_RESEARCH,
                event_type=TradeLifecycleEventType.EXECUTION_FAILED,
                details={"error": str(e)},
            ))
            return None

    async def run_loop(
        self,
        symbol: str = "NIFTY",
        timeframe: str = "15M",
    ) -> None:
        """
        Continuous autonomous research trading loop.
        Runs until stopped via stop().
        """
        self._is_running = True
        self._stop_event.clear()
        logger.info("[MODE B] Hermes Research Trader loop started for %s.", symbol)

        while not self._stop_event.is_set():
            try:
                await self.execute_cycle(symbol=symbol, timeframe=timeframe)
            except Exception as e:
                logger.error("[MODE B] Error in autonomous loop iteration: %s", e, exc_info=True)

            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self.poll_interval_seconds)
            except asyncio.TimeoutError:
                pass

        self._is_running = False
        logger.info("[MODE B] Hermes Research Trader loop stopped.")

    def stop(self) -> None:
        """Signals the autonomous loop to terminate gracefully."""
        self._stop_event.set()
        self._is_running = False
