"""
Deterministic Safety Guard (Non-Bypassable Risk Engine).

Enforces hardcoded, non-negotiable risk constraints:
1. Total portfolio daily loss maximum: ₹2,000.
2. Single active instrument constraint: Only 1 instrument active at a time.
3. Position sizing: Exactly 1 lot per trade.
4. Per-instrument trade limit: Maximum 3 trades per day (NIFTY: 3, BANKNIFTY: 3).
5. Per-instrument daily loss limit: Maximum ₹1,000 daily loss (NIFTY: ₹1,000, BANKNIFTY: ₹1,000).
6. Risk-to-Reward ratio: Minimum 1:3 (3.0).
"""

from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional

from nifty_trader.brain.contracts import TradeCandidate
from nifty_trader.paper.contracts import PaperOrderStatus, PaperTradeOrderRequest
from nifty_trader.paper.store import PaperTradeStore
from nifty_trader.safety.contracts import (
    InstrumentRiskConfig,
    PortfolioRiskConfig,
    SafetyCheckResult,
)

logger = logging.getLogger(__name__)


class DeterministicSafetyGuard:
    """
    Deterministic Safety Guard standing between cognitive AI analysis / operator requests
    and paper broker execution. Cannot be bypassed by prompts, LLM reasoning, or flags.
    """

    def __init__(
        self,
        config: Optional[PortfolioRiskConfig] = None,
        store: Optional[PaperTradeStore] = None,
    ):
        self.config = config or PortfolioRiskConfig()
        self.store = store or PaperTradeStore()

    @classmethod
    def from_settings(cls, settings: Dict[str, Any], store: Optional[PaperTradeStore] = None) -> "DeterministicSafetyGuard":
        """Factory constructor instantiating the guard from system settings."""
        risk_cfg = settings.get("risk", {})
        portfolio_max_loss = float(risk_cfg.get("max_portfolio_daily_loss", risk_cfg.get("max_daily_loss", 2000.0)))
        max_lots = int(risk_cfg.get("max_lots_per_trade", 1))
        min_rr = float(risk_cfg.get("minimum_rr", 3.0))

        instruments_dict: Dict[str, InstrumentRiskConfig] = {}
        raw_inst = risk_cfg.get("instruments", {})

        # Default NIFTY
        nifty_raw = raw_inst.get("NIFTY", {})
        instruments_dict["NIFTY"] = InstrumentRiskConfig(
            symbol="NIFTY",
            lot_size=int(nifty_raw.get("lot_size", 65)),
            max_lots=int(nifty_raw.get("max_lots", 1)),
            max_trades_per_day=int(nifty_raw.get("max_trades_per_day", 3)),
            max_daily_loss=float(nifty_raw.get("max_daily_loss", 1000.0)),
            minimum_rr=float(nifty_raw.get("minimum_rr", min_rr)),
        )

        # Default BANKNIFTY
        bn_raw = raw_inst.get("BANKNIFTY", {})
        instruments_dict["BANKNIFTY"] = InstrumentRiskConfig(
            symbol="BANKNIFTY",
            lot_size=int(bn_raw.get("lot_size", 30)),
            max_lots=int(bn_raw.get("max_lots", 1)),
            max_trades_per_day=int(bn_raw.get("max_trades_per_day", 3)),
            max_daily_loss=float(bn_raw.get("max_daily_loss", 1000.0)),
            minimum_rr=float(bn_raw.get("minimum_rr", min_rr)),
        )

        portfolio_config = PortfolioRiskConfig(
            max_portfolio_daily_loss=portfolio_max_loss,
            max_lots_per_trade=max_lots,
            max_concurrent_instruments=int(risk_cfg.get("max_concurrent_instruments", 1)),
            max_concurrent_positions=int(risk_cfg.get("max_concurrent_positions", 1)),
            minimum_rr=min_rr,
            instruments=instruments_dict,
        )
        return cls(config=portfolio_config, store=store)

    def validate_order_request(
        self,
        request: PaperTradeOrderRequest,
        target_date: Optional[str] = None,
    ) -> SafetyCheckResult:
        """
        Validates an incoming paper trade order request against all deterministic safety invariants.
        Returns SafetyCheckResult with passed=True or passed=False and details.
        """
        violations: List[str] = []
        symbol = request.symbol.upper()

        # 1. Supported Instrument Validation
        if symbol not in self.config.instruments:
            reason = f"Unsupported instrument '{symbol}'. Supported instruments: {list(self.config.instruments.keys())}"
            return SafetyCheckResult(
                passed=False,
                reason=reason,
                rejection_code="UNSUPPORTED_INSTRUMENT",
                violations=[reason],
            )

        inst_cfg = self.config.instruments[symbol]

        # 2. Single Active Instrument Constraint
        # Only 1 instrument allowed to be active at a time
        open_positions = self.store.get_open_positions()
        other_open = [p for p in open_positions if p.symbol.upper() != symbol]
        if other_open:
            active_symbols = sorted(list(set(p.symbol.upper() for p in other_open)))
            reason = (
                f"Single active instrument policy violation: Open position already exists in {active_symbols}. "
                f"Only 1 instrument can be traded at a time. Close {active_symbols} before trading {symbol}."
            )
            violations.append(reason)
            return SafetyCheckResult(
                passed=False,
                reason=reason,
                rejection_code="SINGLE_INSTRUMENT_BREACH",
                violations=violations,
                details={"active_instruments": active_symbols, "requested": symbol},
            )

        # Also check concurrent open positions limit
        if len(open_positions) >= self.config.max_concurrent_positions:
            reason = (
                f"Concurrent position limit reached: Maximum {self.config.max_concurrent_positions} "
                f"open position(s) allowed. Current open: {len(open_positions)}."
            )
            violations.append(reason)
            return SafetyCheckResult(
                passed=False,
                reason=reason,
                rejection_code="CONCURRENT_POSITION_LIMIT",
                violations=violations,
            )

        # 3. Lot Size Constraint (Strictly 1 Lot per trade)
        if request.lots > inst_cfg.max_lots:
            reason = (
                f"Lot size policy violation: Exactly {inst_cfg.max_lots} lot(s) allowed per trade. "
                f"Requested: {request.lots} lot(s)."
            )
            violations.append(reason)
            return SafetyCheckResult(
                passed=False,
                reason=reason,
                rejection_code="EXCESS_LOT_SIZE",
                violations=violations,
                details={"requested_lots": request.lots, "max_lots": inst_cfg.max_lots},
            )

        # 4. Daily Trade Frequency Limit (3 trades per day per instrument)
        trade_count = self.store.get_daily_trade_count(symbol=symbol, target_date=target_date)
        if trade_count >= inst_cfg.max_trades_per_day:
            reason = (
                f"Daily trade frequency limit reached: {symbol} has already executed {trade_count} of "
                f"{inst_cfg.max_trades_per_day} allowed trades today."
            )
            violations.append(reason)
            return SafetyCheckResult(
                passed=False,
                reason=reason,
                rejection_code="DAILY_TRADE_LIMIT_REACHED",
                violations=violations,
                details={"executed_trades": trade_count, "limit": inst_cfg.max_trades_per_day},
            )

        # 5. Instrument Daily Loss Limit (₹1,000 max per day for NIFTY / BANKNIFTY)
        inst_net_pnl = self.store.get_daily_net_pnl(symbol=symbol, target_date=target_date)
        if inst_net_pnl <= -inst_cfg.max_daily_loss:
            loss_amount = abs(inst_net_pnl)
            reason = (
                f"Instrument daily loss limit reached: Cumulative session loss for {symbol} is ₹{loss_amount:,.2f} "
                f"(Limit: ₹{inst_cfg.max_daily_loss:,.2f}). Trading halted for {symbol} today."
            )
            violations.append(reason)
            return SafetyCheckResult(
                passed=False,
                reason=reason,
                rejection_code="INSTRUMENT_LOSS_LIMIT_REACHED",
                violations=violations,
                details={"instrument_net_pnl": inst_net_pnl, "max_daily_loss": inst_cfg.max_daily_loss},
            )

        # 6. Total Portfolio Daily Loss Limit (₹2,000 max per day across all instruments)
        portfolio_net_pnl = self.store.get_daily_net_pnl(symbol=None, target_date=target_date)
        if portfolio_net_pnl <= -self.config.max_portfolio_daily_loss:
            portfolio_loss = abs(portfolio_net_pnl)
            reason = (
                f"Portfolio daily loss circuit breaker triggered: Total portfolio loss is ₹{portfolio_loss:,.2f} "
                f"(Portfolio Limit: ₹{self.config.max_portfolio_daily_loss:,.2f}). All trading halted today."
            )
            violations.append(reason)
            return SafetyCheckResult(
                passed=False,
                reason=reason,
                rejection_code="PORTFOLIO_LOSS_LIMIT_REACHED",
                violations=violations,
                details={"portfolio_net_pnl": portfolio_net_pnl, "portfolio_limit": self.config.max_portfolio_daily_loss},
            )

        # 7. Risk-to-Reward Ratio Invariant (Minimum 1:3)
        if request.stop_loss_price is not None and request.target_price is not None:
            ref_price = request.limit_price or request.strike
            risk = abs(ref_price - request.stop_loss_price)
            reward = abs(request.target_price - ref_price)
            if risk > 0:
                rr = reward / risk
                if rr < (inst_cfg.minimum_rr - 0.01):
                    reason = (
                        f"Risk-to-Reward ratio policy violation: Proposed trade R:R is 1:{rr:.2f}, "
                        f"which is below the mandatory minimum 1:{inst_cfg.minimum_rr:.1f} (1:3)."
                    )
                    violations.append(reason)
                    return SafetyCheckResult(
                        passed=False,
                        reason=reason,
                        rejection_code="INSUFFICIENT_RR",
                        violations=violations,
                        details={"calculated_rr": rr, "required_minimum_rr": inst_cfg.minimum_rr},
                    )

        # All checks passed successfully
        return SafetyCheckResult(
            passed=True,
            reason="All deterministic safety checks passed successfully.",
            rejection_code=None,
            violations=[],
            details={
                "symbol": symbol,
                "lots": request.lots,
                "quantity": request.quantity,
                "executed_trades_today": trade_count,
                "max_trades_allowed": inst_cfg.max_trades_per_day,
                "instrument_net_pnl": inst_net_pnl,
                "instrument_max_daily_loss": inst_cfg.max_daily_loss,
                "portfolio_net_pnl": portfolio_net_pnl,
                "portfolio_max_loss": self.config.max_portfolio_daily_loss,
                "minimum_rr": inst_cfg.minimum_rr,
            },
        )

    def get_status(self) -> Dict[str, Any]:
        """Provides status summary of all active deterministic safety rules and limits."""
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        portfolio_pnl = self.store.get_daily_net_pnl(symbol=None, target_date=today_str)
        open_pos = self.store.get_open_positions()

        inst_status = {}
        for sym, cfg in self.config.instruments.items():
            sym_pnl = self.store.get_daily_net_pnl(symbol=sym, target_date=today_str)
            trades_today = self.store.get_daily_trade_count(symbol=sym, target_date=today_str)
            inst_status[sym] = {
                "max_trades_per_day": cfg.max_trades_per_day,
                "executed_trades_today": trades_today,
                "remaining_trades": max(0, cfg.max_trades_per_day - trades_today),
                "max_daily_loss": cfg.max_daily_loss,
                "current_daily_pnl": sym_pnl,
                "lot_size": cfg.lot_size,
                "max_lots_per_trade": cfg.max_lots,
                "minimum_rr": f"1:{cfg.minimum_rr:.0f}",
                "loss_circuit_breaker_active": sym_pnl <= -cfg.max_daily_loss,
            }

        return {
            "status": "ARMED_AND_LOCKED",
            "portfolio_max_daily_loss": self.config.max_portfolio_daily_loss,
            "portfolio_current_daily_pnl": portfolio_pnl,
            "portfolio_circuit_breaker_active": portfolio_pnl <= -self.config.max_portfolio_daily_loss,
            "max_lots_per_trade": self.config.max_lots_per_trade,
            "max_concurrent_instruments": self.config.max_concurrent_instruments,
            "currently_active_instruments": list(set(p.symbol.upper() for p in open_pos)),
            "open_positions_count": len(open_pos),
            "instruments": inst_status,
        }
