"""
Package 5: Meaningful Market Change Detector.

Detects whether a newly gathered market observation possesses meaningful structural,
numerical, derivatives, or operator changes compared to the prior observation,
preventing redundant model calls while ensuring critical shifts trigger analysis.

STRICT INVARIANT: Change detection controls observation scheduling only.
Zero trading signals or bullish/bearish bias.
"""

from datetime import datetime, timezone
import logging
from typing import List, Optional, Tuple
from pydantic import BaseModel, Field

from nifty_trader.contracts.models import (
    CanonicalObservationStatus,
    UnifiedMarketObservation,
)

logger = logging.getLogger(__name__)


class ChangeDetectionConfig(BaseModel):
    """Configuration thresholds for meaningful change detection."""
    candle_completion: bool = True
    price_change_enabled: bool = True
    minimum_relative_price_change: float = 0.001  # 0.10% price delta threshold
    source_refresh_enabled: bool = True
    pcr_change_threshold: float = 0.05            # Meaningful option chain PCR shift
    structure_change_enabled: bool = True
    manual_instruction_enabled: bool = True


class MeaningfulChangeDetector:
    """
    Evaluates deltas between sequential market observations.
    """

    def __init__(self, config: Optional[ChangeDetectionConfig] = None):
        self.config = config or ChangeDetectionConfig()

    def detect_changes(
        self,
        current_obs: UnifiedMarketObservation,
        previous_obs: Optional[UnifiedMarketObservation],
        new_instruction_present: bool = False,
        explicit_wake_reason: Optional[str] = None,
    ) -> Tuple[bool, List[str]]:
        """
        Determines whether the current observation differs meaningfully from the previous observation.
        Returns: (is_meaningful: bool, reasons: List[str])
        """
        reasons: List[str] = []

        # 1. First observation is always meaningful
        if previous_obs is None:
            return True, ["INITIAL_OBSERVATION: Baseline market observation established."]

        # 2. Explicit Wake Reason (e.g. manual OBSERVE_NOW command)
        if explicit_wake_reason:
            reasons.append(f"EXPLICIT_WAKE: {explicit_wake_reason}")

        # 3. New Operator Instruction
        if self.config.manual_instruction_enabled and new_instruction_present:
            reasons.append("MANUAL_INSTRUCTION: New operator guidance received.")

        # 4. Session Phase Transition
        if current_obs.session != previous_obs.session:
            reasons.append(f"SESSION_EVENT: Market session changed from '{previous_obs.session}' to '{current_obs.session}'.")

        # 5. Candle Completion (15M or 1H)
        if self.config.candle_completion:
            c15_curr = current_obs.numerical.latest_15m
            c15_prev = previous_obs.numerical.latest_15m
            if c15_curr and c15_prev and c15_curr.timestamp > c15_prev.timestamp:
                reasons.append(f"NEW_CANDLE: 15M candle completed at {c15_curr.timestamp.strftime('%H:%M UTC')}.")

            c1h_curr = current_obs.numerical.latest_1h
            c1h_prev = previous_obs.numerical.latest_1h
            if c1h_curr and c1h_prev and c1h_curr.timestamp > c1h_prev.timestamp:
                reasons.append(f"NEW_CANDLE: 1H candle completed at {c1h_curr.timestamp.strftime('%H:%M UTC')}.")

        # 6. Price Movement
        if self.config.price_change_enabled:
            curr_price = None
            prev_price = None

            if current_obs.numerical.latest_15m:
                curr_price = current_obs.numerical.latest_15m.close
            elif current_obs.visual.tradingview and current_obs.visual.tradingview.visible_price:
                curr_price = current_obs.visual.tradingview.visible_price

            if previous_obs.numerical.latest_15m:
                prev_price = previous_obs.numerical.latest_15m.close
            elif previous_obs.visual.tradingview and previous_obs.visual.tradingview.visible_price:
                prev_price = previous_obs.visual.tradingview.visible_price

            if curr_price and prev_price and prev_price > 0:
                rel_delta = abs(curr_price - prev_price) / prev_price
                if rel_delta >= self.config.minimum_relative_price_change:
                    reasons.append(
                        f"PRICE_MOVEMENT: Price shifted {rel_delta*100:.2f}% "
                        f"(from {prev_price:.2f} to {curr_price:.2f}, threshold: {self.config.minimum_relative_price_change*100:.2f}%)."
                    )

        # 7. Derivatives / Option Chain Shift (Sensibull)
        if self.config.source_refresh_enabled:
            curr_sensi = current_obs.visual.sensibull
            prev_sensi = previous_obs.visual.sensibull

            # Source availability flip
            if curr_sensi and prev_sensi:
                if curr_sensi.status != prev_sensi.status:
                    reasons.append(f"SOURCE_REFRESH: Sensibull status changed from '{prev_sensi.status.value}' to '{curr_sensi.status.value}'.")
                elif curr_sensi.pcr is not None and prev_sensi.pcr is not None:
                    pcr_diff = abs(curr_sensi.pcr - prev_sensi.pcr)
                    if pcr_diff >= self.config.pcr_change_threshold:
                        reasons.append(f"SOURCE_REFRESH: Sensibull PCR shifted by {pcr_diff:.2f} (from {prev_sensi.pcr:.2f} to {curr_sensi.pcr:.2f}).")
                elif curr_sensi.max_pain != prev_sensi.max_pain:
                    reasons.append(f"SOURCE_REFRESH: Max Pain shifted from {prev_sensi.max_pain} to {curr_sensi.max_pain}.")
            elif (curr_sensi is None) != (prev_sensi is None):
                reasons.append("SOURCE_REFRESH: Sensibull observation newly acquired or detached.")

        # 8. Cross Source Validation Discrepancy Change
        curr_warnings = {w.code for w in current_obs.warnings}
        prev_warnings = {w.code for w in previous_obs.warnings}
        if curr_warnings != prev_warnings:
            diff = curr_warnings.symmetric_difference(prev_warnings)
            reasons.append(f"WARNING_CHANGE: Perception warnings changed ({', '.join(diff)}).")

        is_meaningful = len(reasons) > 0
        return is_meaningful, reasons
