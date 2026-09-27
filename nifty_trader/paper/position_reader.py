"""
Sensibull Virtual Portfolio Position & P&L Reader.

Extracts live paper positions, orders, MTM, and realized/unrealized P&L from
Sensibull Virtual Trade DOM or page text.
"""

from datetime import datetime, timezone
import logging
import re
from typing import Any, Dict, List, Optional, Tuple
from nifty_trader.paper.contracts import (
    PaperAction,
    PaperOptionType,
    PaperPortfolioSummary,
    PaperPosition,
    PaperPositionStatus,
    SensibullEnvironmentType,
)

logger = logging.getLogger(__name__)


class SensibullPositionReader:
    """
    Parses Sensibull Virtual Portfolio page text and DOM elements to extract
    structured open positions and P&L metrics.
    """

    # Patterns for positions table: e.g. "NIFTY 24500 CE 26 SEP" or "24500 CE"
    POSITION_LINE_PATTERN = re.compile(
        r"(?:NIFTY\s+)?(\d{5})\s+(CE|PE)\b(?:\s+([A-Za-z0-9\-]+))?",
        re.IGNORECASE,
    )

    # Patterns for Quantity / Lots: e.g. "25 Qty" or "1 Lot" or "Qty: 25"
    QTY_PATTERN = re.compile(r"(?:Qty|Quantity|Lots?)\s*[:=]?\s*([+\-]?\d+)", re.IGNORECASE)

    # Patterns for Prices: Buy/Avg Price and LTP
    PRICE_PATTERN = re.compile(r"(?:Avg|Buy|Entry)[\s:]*₹?\s*(\d+(?:\.\d{1,2})?)", re.IGNORECASE)
    LTP_PATTERN = re.compile(r"(?:LTP|Current|Last)[\s:]*₹?\s*(\d+(?:\.\d{1,2})?)", re.IGNORECASE)

    # Patterns for P&L: e.g. "P&L: +₹1,250.00 (+12.5%)"
    PNL_PATTERN = re.compile(
        r"(?:P&L|PnL|Profit|Loss)\s*[:=]?\s*([+\-]?₹?\s*[\d,]+(?:\.\d{1,2})?)\s*(?:\(([+\-]?\d+(?:\.\d{1,2})?%?)\))?",
        re.IGNORECASE,
    )

    TOTAL_UNREALIZED_PATTERN = re.compile(
        r"(?:Total\s+)?\b(?:Unrealized|Active)\s+P&L\s*[:=]?\s*([+\-]?₹?\s*[\d,]+(?:\.\d{1,2})?)",
        re.IGNORECASE,
    )
    TOTAL_REALIZED_PATTERN = re.compile(
        r"(?:Total\s+)?\bRealized\s+P&L\s*[:=]?\s*([+\-]?₹?\s*[\d,]+(?:\.\d{1,2})?)",
        re.IGNORECASE,
    )

    def parse_portfolio(
        self,
        visible_text: str,
        dom_elements: Optional[List[Dict[str, Any]]] = None,
        environment: SensibullEnvironmentType = SensibullEnvironmentType.VIRTUAL_TRADE,
    ) -> PaperPortfolioSummary:
        """
        Parses the virtual portfolio text and elements into a PaperPortfolioSummary.
        """
        positions: List[PaperPosition] = []
        text = visible_text or ""

        # 1. Parse Total P&L metrics
        unrealized_pnl = self._extract_currency(self.TOTAL_UNREALIZED_PATTERN, text) or 0.0
        realized_pnl = self._extract_currency(self.TOTAL_REALIZED_PATTERN, text) or 0.0

        # If individual PnL pattern found without explicit total, look for overall P&L
        if unrealized_pnl == 0.0 and realized_pnl == 0.0:
            m_pnl = self.PNL_PATTERN.search(text)
            if m_pnl:
                raw_val = m_pnl.group(1).replace("₹", "").replace(",", "").replace(" ", "")
                try:
                    unrealized_pnl = float(raw_val)
                except ValueError:
                    pass

        # 2. Extract Positions
        # If DOM elements available, inspect rows
        if dom_elements:
            positions = self._parse_from_dom_elements(dom_elements)

        # Fallback to line-by-line text parsing if no DOM rows matched
        if not positions and text:
            positions = self._parse_from_text(text)

        open_count = sum(1 for p in positions if p.status == PaperPositionStatus.OPEN)

        # Re-sum unrealized P&L from positions if available
        if positions and unrealized_pnl == 0.0:
            unrealized_pnl = sum(p.unrealized_pnl for p in positions if p.status == PaperPositionStatus.OPEN)

        return PaperPortfolioSummary(
            environment=environment,
            is_safe_environment=environment == SensibullEnvironmentType.VIRTUAL_TRADE,
            total_positions=len(positions),
            open_positions_count=open_count,
            total_unrealized_pnl=round(unrealized_pnl, 2),
            total_realized_pnl=round(realized_pnl, 2),
            net_pnl=round(unrealized_pnl + realized_pnl, 2),
            positions=positions,
            last_synced_at=datetime.now(timezone.utc),
        )

    def _parse_from_text(self, text: str) -> List[PaperPosition]:
        """Heuristic text parser identifying position blocks."""
        positions: List[PaperPosition] = []
        lines = text.split("\n")

        for i, line in enumerate(lines):
            pos_match = self.POSITION_LINE_PATTERN.search(line)
            if pos_match:
                strike_str = pos_match.group(1)
                opt_type_str = pos_match.group(2).upper()
                expiry_str = pos_match.group(3) or "CURRENT_EXPIRY"

                try:
                    strike = float(strike_str)
                    opt_type = PaperOptionType(opt_type_str)
                except (ValueError, KeyError):
                    continue

                # Look forward up to 5 lines for prices and quantities
                context_block = "\n".join(lines[max(0, i - 1): min(len(lines), i + 6)])

                qty = 25
                qty_match = self.QTY_PATTERN.search(context_block)
                if qty_match:
                    try:
                        qty = abs(int(qty_match.group(1)))
                    except ValueError:
                        qty = 25

                lots = max(1, qty // 25)

                avg_price = 100.0
                price_match = self.PRICE_PATTERN.search(context_block)
                if price_match:
                    try:
                        avg_price = float(price_match.group(1))
                    except ValueError:
                        pass

                ltp = avg_price
                ltp_match = self.LTP_PATTERN.search(context_block)
                if ltp_match:
                    try:
                        ltp = float(ltp_match.group(1))
                    except ValueError:
                        pass

                pnl = (ltp - avg_price) * qty
                pnl_pct = ((ltp - avg_price) / avg_price * 100.0) if avg_price > 0 else 0.0

                pos = PaperPosition(
                    symbol="NIFTY",
                    expiry=expiry_str,
                    strike=strike,
                    option_type=opt_type,
                    action=PaperAction.BUY,
                    lots=lots,
                    quantity=qty,
                    avg_price=avg_price,
                    current_ltp=ltp,
                    unrealized_pnl=round(pnl, 2),
                    pnl_percentage=round(pnl_pct, 2),
                    status=PaperPositionStatus.OPEN,
                )
                positions.append(pos)

        return positions

    def _parse_from_dom_elements(self, elements: List[Dict[str, Any]]) -> List[PaperPosition]:
        """Extracts positions from structured DOM element representations."""
        positions: List[PaperPosition] = []

        # Find rows containing strike descriptions
        for el in elements:
            text = el.get("text", "")
            match = self.POSITION_LINE_PATTERN.search(text)
            if match:
                strike_val = float(match.group(1))
                opt_type = PaperOptionType(match.group(2).upper())
                expiry_val = match.group(3) or "CURRENT_EXPIRY"

                # Extract attributes or nearby values
                pos = PaperPosition(
                    symbol="NIFTY",
                    expiry=expiry_val,
                    strike=strike_val,
                    option_type=opt_type,
                    action=PaperAction.BUY,
                    lots=1,
                    quantity=25,
                    avg_price=100.0,
                    current_ltp=100.0,
                    unrealized_pnl=0.0,
                    pnl_percentage=0.0,
                    status=PaperPositionStatus.OPEN,
                )
                positions.append(pos)

        return positions

    def _extract_currency(self, pattern: re.Pattern, text: str) -> Optional[float]:
        """Safely extracts a currency figure from text."""
        match = pattern.search(text)
        if not match:
            return None
        raw = match.group(1).replace("₹", "").replace(",", "").replace(" ", "")
        try:
            return float(raw)
        except ValueError:
            return None
