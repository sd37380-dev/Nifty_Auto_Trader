"""
Approval Engine for NIFTY Futures Short Strategy.

Coordinates:
- Session boundary checks (e.g. cutoff at 15:00 IST)
- Single active position constraint
- Integration with DeterministicSafetyGuard (Risk Engine)
- Pre-execution signoff for broker / paper orders
"""

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from nifty_trader.core.modes import TradingMode
from nifty_trader.paper.contracts import PaperAction, PaperOptionType, PaperTradeOrderRequest
from nifty_trader.strategies.short.contracts import ShortStrategyConfig


class ApprovalEngine:
    """
    Deterministic Approval Engine enforcing operational and risk signoffs.
    """

    def __init__(
        self,
        safety_guard: Optional[Any] = None,
        config: Optional[ShortStrategyConfig] = None,
    ):
        self._safety_guard = safety_guard
        self.config = config or ShortStrategyConfig()

    @property
    def safety_guard(self) -> Any:
        if self._safety_guard is None:
            from nifty_trader.safety.guard import DeterministicSafetyGuard
            self._safety_guard = DeterministicSafetyGuard()
        return self._safety_guard

    @safety_guard.setter
    def safety_guard(self, val: Any) -> None:
        self._safety_guard = val

    def check_session_cutoff(self, timestamp: datetime) -> Tuple[bool, str]:
        """
        Validates if current candle/tick is within the allowed trading window (before session_end).
        Default cutoff is 15:00 IST.
        """
        # Convert to IST time string HH:MM
        from nifty_trader.contracts.models import IST
        ist_dt = timestamp.astimezone(IST) if timestamp.tzinfo else timestamp
        time_str = ist_dt.strftime("%H:%M")

        if time_str >= self.config.session_end:
            return False, "SESSION CUTOFF REACHED"

        return True, "OK"

    def validate_risk_clearance(
        self,
        entry_price: float,
        stop_loss: float,
        target: float,
        target_date: Optional[str] = None,
        has_active_position: bool = False,
    ) -> Tuple[bool, str]:
        """
        Runs full risk evaluation through the project's DeterministicSafetyGuard.
        Enforces:
        - 1-position constraint
        - 1-lot constraint
        - Daily trade limit (max 3 trades)
        - Daily loss circuit breakers (₹1,000 NIFTY / ₹2,000 Portfolio)
        - Mandatory minimum 1:2 or 1:3 R:R
        """
        if self.config.one_position_only and has_active_position:
            return False, "ACTIVE POSITION ALREADY OPEN"

        # Construct candidate paper order request for deterministic validation
        order_req = PaperTradeOrderRequest(
            symbol="NIFTY",
            expiry="CURRENT_WEEK",
            strike=round(entry_price / 50.0) * 50.0,
            option_type=PaperOptionType.PE, # Short bias proxy
            action=PaperAction.SELL,
            lots=1,
            limit_price=entry_price,
            stop_loss_price=stop_loss,
            target_price=target,
            mode=TradingMode.EXISTING_SYSTEM,
        )

        result = self.safety_guard.validate_order_request(order_req, target_date=target_date)
        if not result.passed:
            return False, f"RISK CHECK FAILED: {result.reason}"

        return True, "PASSED"
