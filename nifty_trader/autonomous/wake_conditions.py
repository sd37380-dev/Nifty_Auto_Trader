"""
Package 5: Wake Conditions and Evaluator.

Defines factory helpers for constructing explicit wake conditions
(Candle boundaries, Price changes, Source refresh, Time delays, Session events)
and evaluates them against market perception updates and clock ticks.
"""

from datetime import datetime, timedelta, timezone
import logging
from typing import Any, Dict, List, Optional, Tuple
import uuid

from nifty_trader.autonomous.contracts import (
    WakeCondition,
    WakeConditionType,
)
from nifty_trader.contracts.models import (
    CanonicalObservationStatus,
    UnifiedMarketObservation,
)
from nifty_trader.market_data.clock import CandleClock
from nifty_trader.market_data.models import Timeframe
from nifty_trader.market_data.session import MarketSessionManager, MarketSessionStatus

logger = logging.getLogger(__name__)


class WakeConditionFactory:
    """
    Constructs standardized, traceable WakeCondition objects.
    """

    @staticmethod
    def create_candle_close_condition(
        timeframe: str = "15M",
        as_of: Optional[datetime] = None,
        reason: str = "Waiting for candle boundary completion",
    ) -> WakeCondition:
        """
        Creates a CANDLE_COMPLETION wake condition for 15M or 1H timeframe.
        """
        ref_time = as_of or datetime.now(timezone.utc)
        tf_enum = Timeframe.H1 if timeframe.upper() == "1H" else Timeframe.M15
        next_close = CandleClock.get_next_close_time(tf_enum, as_of=ref_time)

        return WakeCondition(
            condition_id=f"wake_candle_{uuid.uuid4().hex[:6]}",
            type=WakeConditionType.CANDLE_COMPLETION,
            timeframe=timeframe.upper(),
            scheduled_at=next_close,
            reason=f"{reason} ({timeframe.upper()} close at {next_close.strftime('%H:%M:%S UTC')})",
            metadata={"timeframe": timeframe.upper(), "target_close_utc": next_close.isoformat()},
        )

    @staticmethod
    def create_time_delay_condition(
        seconds: float,
        as_of: Optional[datetime] = None,
        reason: str = "Time delay pacing",
        condition_type: WakeConditionType = WakeConditionType.TIME,
    ) -> WakeCondition:
        """Creates a time-based wake condition expiring after `seconds`."""
        ref_time = as_of or datetime.now(timezone.utc)
        wake_time = ref_time + timedelta(seconds=max(1.0, seconds))

        return WakeCondition(
            condition_id=f"wake_time_{uuid.uuid4().hex[:6]}",
            type=condition_type,
            scheduled_at=wake_time,
            reason=f"{reason} (in {seconds:.1f}s)",
            metadata={"delay_seconds": seconds},
        )

    @staticmethod
    def create_price_change_condition(
        threshold_relative: float = 0.001,  # 0.1% price movement
        reference_price: Optional[float] = None,
        reason: str = "Waiting for significant price movement",
    ) -> WakeCondition:
        """Creates a PRICE_CHANGE wake condition."""
        return WakeCondition(
            condition_id=f"wake_price_{uuid.uuid4().hex[:6]}",
            type=WakeConditionType.PRICE_CHANGE,
            threshold=threshold_relative,
            scheduled_at=datetime.now(timezone.utc),
            reason=f"{reason} (threshold: {threshold_relative*100:.2f}%, ref: {reference_price or 'current'})",
            metadata={"threshold": threshold_relative, "reference_price": reference_price},
        )

    @staticmethod
    def create_source_refresh_condition(
        source: str,
        delay_seconds: float = 30.0,
        as_of: Optional[datetime] = None,
        reason: str = "Waiting for source refresh",
    ) -> WakeCondition:
        """Creates a SOURCE_REFRESH wake condition."""
        ref_time = as_of or datetime.now(timezone.utc)
        wake_time = ref_time + timedelta(seconds=delay_seconds)

        return WakeCondition(
            condition_id=f"wake_src_{uuid.uuid4().hex[:6]}",
            type=WakeConditionType.SOURCE_REFRESH,
            source=source,
            scheduled_at=wake_time,
            reason=f"{reason} (Source '{source}' in {delay_seconds:.0f}s)",
            metadata={"source": source, "delay_seconds": delay_seconds},
        )

    @staticmethod
    def create_manual_instruction_condition(
        reason: str = "Waiting for operator steering instruction",
    ) -> WakeCondition:
        """Creates a MANUAL_INSTRUCTION wake condition."""
        return WakeCondition(
            condition_id=f"wake_inst_{uuid.uuid4().hex[:6]}",
            type=WakeConditionType.MANUAL_INSTRUCTION,
            scheduled_at=datetime.now(timezone.utc),
            reason=reason,
        )

    @staticmethod
    def create_session_event_condition(
        target_time: datetime,
        reason: str = "Waiting for market session event",
    ) -> WakeCondition:
        """Creates a SESSION_EVENT wake condition."""
        return WakeCondition(
            condition_id=f"wake_sess_{uuid.uuid4().hex[:6]}",
            type=WakeConditionType.SESSION_EVENT,
            scheduled_at=target_time,
            reason=reason,
            metadata={"target_time_utc": target_time.isoformat()},
        )


class WakeConditionEvaluator:
    """
    Evaluates whether any active wake conditions are satisfied.
    """

    @classmethod
    def evaluate(
        cls,
        condition: WakeCondition,
        current_time: datetime,
        latest_observation: Optional[UnifiedMarketObservation] = None,
        reference_price: Optional[float] = None,
        new_instructions_count: int = 0,
        session_status: Optional[MarketSessionStatus] = None,
    ) -> Tuple[bool, str]:
        """
        Evaluates a single condition.
        Returns: (is_satisfied: bool, explanation: str)
        """
        # 1. Expiration check
        if condition.expires_at and current_time > condition.expires_at:
            return False, f"Condition expired at {condition.expires_at.isoformat()}"

        # 2. Time-based & Candle completion check
        if condition.type in (
            WakeConditionType.TIME,
            WakeConditionType.CANDLE_COMPLETION,
            WakeConditionType.ERROR_RECOVERY,
            WakeConditionType.SOURCE_REFRESH,
            WakeConditionType.SESSION_EVENT,
        ):
            if current_time >= condition.scheduled_at:
                return True, f"Scheduled timestamp reached: {condition.scheduled_at.isoformat()} (current: {current_time.isoformat()})"

        # 3. Price change check
        if condition.type == WakeConditionType.PRICE_CHANGE and latest_observation:
            latest_price = None
            if latest_observation.numerical.latest_15m:
                latest_price = latest_observation.numerical.latest_15m.close
            elif latest_observation.visual.tradingview and latest_observation.visual.tradingview.visible_price:
                latest_price = latest_observation.visual.tradingview.visible_price

            ref_p = condition.metadata.get("reference_price") or reference_price
            if latest_price and ref_p and ref_p > 0:
                rel_change = abs(latest_price - ref_p) / ref_p
                threshold = condition.threshold or 0.001
                if rel_change >= threshold:
                    return True, f"Price moved {rel_change*100:.3f}% (threshold: {threshold*100:.3f}%) from {ref_p:.2f} to {latest_price:.2f}"

        # 4. Manual instruction check
        if condition.type == WakeConditionType.MANUAL_INSTRUCTION:
            if new_instructions_count > 0:
                return True, f"{new_instructions_count} new operator instruction(s) arrived"

        # 5. User command check (explicit wake)
        if condition.type == WakeConditionType.USER_COMMAND:
            return True, "Explicit user command received"

        return False, "Condition pending"

    @classmethod
    def find_satisfied_conditions(
        cls,
        conditions: List[WakeCondition],
        current_time: datetime,
        latest_observation: Optional[UnifiedMarketObservation] = None,
        reference_price: Optional[float] = None,
        new_instructions_count: int = 0,
        session_status: Optional[MarketSessionStatus] = None,
    ) -> List[Tuple[WakeCondition, str]]:
        """
        Evaluates a list of conditions and returns all satisfied conditions with explanations.
        """
        satisfied = []
        for cond in conditions:
            is_met, explanation = cls.evaluate(
                condition=cond,
                current_time=current_time,
                latest_observation=latest_observation,
                reference_price=reference_price,
                new_instructions_count=new_instructions_count,
                session_status=session_status,
            )
            if is_met:
                cond.satisfied = True
                satisfied.append((cond, explanation))
        return satisfied
