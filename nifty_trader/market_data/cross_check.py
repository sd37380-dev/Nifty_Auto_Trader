"""
Cross-Check Verification: Browser Visual Perception vs Numerical Market Data.

Validates price alignment between what the browser visual perception layer observed
and what the numerical data provider reported, detecting significant discrepancies.
"""

import logging
import re
from typing import Any, Dict, Optional
from pydantic import BaseModel

from nifty_trader.browser.models import BrowserObservation
from nifty_trader.market_data.models import Candle

logger = logging.getLogger(__name__)


class CrossCheckResult(BaseModel):
    is_aligned: bool
    browser_price: Optional[float]
    numerical_price: Optional[float]
    discrepancy_points: Optional[float]
    discrepancy_pct: Optional[float]
    tolerance_pct: float
    status: str  # MATCH, MISMATCH, INSUFFICIENT_DATA
    details: str


class MarketCrossChecker:
    """
    Deterministic cross-validator comparing visual webpage price data against numerical feeds.
    """

    # Matches Indian NIFTY price formats: e.g. 23,140.50 or 23140.50
    PRICE_PATTERN = re.compile(r"\b(2\d{1},\d{3}(?:\.\d{1,2})?|2\d{4}(?:\.\d{1,2})?)\b")

    def __init__(self, tolerance_pct: float = 0.5):
        """
        :param tolerance_pct: Acceptable percentage difference between sources (default 0.5%).
        """
        self.tolerance_pct = tolerance_pct

    def extract_price_from_browser_observation(self, obs: BrowserObservation) -> Optional[float]:
        """
        Parses candidate NIFTY index prices from webpage visible text and title.
        """
        text_corpus = f"{obs.page_title}\n{obs.visible_text}"
        matches = self.PRICE_PATTERN.findall(text_corpus)
        if not matches:
            return None

        # Clean commas and parse to float
        prices = []
        for m in matches:
            try:
                val = float(m.replace(",", ""))
                # Sanity range for NIFTY (15,000 to 35,000)
                if 15000 <= val <= 35000:
                    prices.append(val)
            except ValueError:
                continue

        # Return the most frequently appearing or first reasonable candidate
        return prices[0] if prices else None

    def cross_check(
        self,
        browser_obs: Optional[BrowserObservation],
        numerical_candle: Optional[Candle],
    ) -> CrossCheckResult:
        """
        Performs the cross-validation comparison.
        """
        if not browser_obs or not numerical_candle:
            return CrossCheckResult(
                is_aligned=True,
                browser_price=None,
                numerical_price=numerical_candle.close if numerical_candle else None,
                discrepancy_points=None,
                discrepancy_pct=None,
                tolerance_pct=self.tolerance_pct,
                status="INSUFFICIENT_DATA",
                details="Missing browser observation or numerical candle for cross-check.",
            )

        b_price = self.extract_price_from_browser_observation(browser_obs)
        n_price = numerical_candle.close

        if b_price is None:
            return CrossCheckResult(
                is_aligned=True,
                browser_price=None,
                numerical_price=n_price,
                discrepancy_points=None,
                discrepancy_pct=None,
                tolerance_pct=self.tolerance_pct,
                status="INSUFFICIENT_DATA",
                details="Could not extract candidate NIFTY price from browser observation text.",
            )

        delta = abs(b_price - n_price)
        pct = (delta / n_price) * 100.0
        aligned = pct <= self.tolerance_pct

        status = "MATCH" if aligned else "MISMATCH"
        details = (
            f"Browser price ({b_price:.2f}) vs Numerical close ({n_price:.2f}): "
            f"diff = {delta:.2f} pts ({pct:.2f}%). "
            + ("Within tolerance." if aligned else f"EXCEEDS tolerance ({self.tolerance_pct}%).")
        )

        if not aligned:
            logger.warning("[DATA_MISMATCH] %s", details)

        return CrossCheckResult(
            is_aligned=aligned,
            browser_price=b_price,
            numerical_price=n_price,
            discrepancy_points=round(delta, 2),
            discrepancy_pct=round(pct, 3),
            tolerance_pct=self.tolerance_pct,
            status=status,
            details=details,
        )
