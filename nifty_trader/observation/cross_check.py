"""
Multi-Source Cross-Check Engine.

Performs cross-validation across Sensibull, TradingView, and Authoritative Numerical Data.
Classifies spot discrepancies (MATCH, MINOR_DIFFERENCE, SIGNIFICANT_DIFFERENCE) without
silently overwriting any source.
"""

import logging
import re
from typing import Any, Dict, Optional

from nifty_trader.browser.models import BrowserObservation
from nifty_trader.market_data.models import Candle
from nifty_trader.observation.models import (
    MultiSourceComparisonResult,
    SensibullObservation,
)

logger = logging.getLogger(__name__)


class MultiSourceCrossChecker:
    """
    Validates price alignment across multiple observation sources against numerical feed close.
    """

    PRICE_PATTERN = re.compile(r"\b(2\d{1},\d{3}(?:\.\d{1,2})?|2\d{4}(?:\.\d{1,2})?)\b")

    def __init__(
        self,
        match_tolerance_pct: float = 0.5,
        minor_tolerance_pct: float = 1.5,
    ):
        self.match_tolerance_pct = match_tolerance_pct
        self.minor_tolerance_pct = minor_tolerance_pct

    def extract_tradingview_price(self, obs: Optional[BrowserObservation]) -> Optional[float]:
        """Extracts candidate NIFTY price from TradingView observation text and title."""
        if not obs:
            return None
        text = f"{obs.page_title}\n{obs.visible_text}"
        matches = self.PRICE_PATTERN.findall(text)
        for m in matches:
            try:
                val = float(m.replace(",", ""))
                if 15000 <= val <= 35000:
                    return val
            except ValueError:
                continue
        return None

    def compare_sources(
        self,
        numerical_candle: Optional[Candle] = None,
        sensibull_obs: Optional[SensibullObservation] = None,
        tradingview_obs: Optional[BrowserObservation] = None,
    ) -> MultiSourceComparisonResult:
        """
        Compares displayed spot prices against numerical close.
        Does NOT alter source values.
        """
        details = []
        n_close = numerical_candle.close if numerical_candle else None
        s_spot = sensibull_obs.spot_reference if (sensibull_obs and sensibull_obs.spot_reference) else None
        tv_price = self.extract_tradingview_price(tradingview_obs)

        # 1. Evaluate Sensibull vs Numerical
        s_diff = None
        s_pct = None
        s_status = "INSUFFICIENT_DATA"

        if n_close is not None and s_spot is not None:
            s_diff = round(abs(s_spot - n_close), 2)
            s_pct = round((s_diff / n_close) * 100.0, 3)

            if s_pct <= self.match_tolerance_pct:
                s_status = "MATCH"
                details.append(f"Sensibull spot ({s_spot:.2f}) matches Numerical close ({n_close:.2f}) within {self.match_tolerance_pct}% ({s_pct}%).")
            elif s_pct <= self.minor_tolerance_pct:
                s_status = "MINOR_DIFFERENCE"
                details.append(f"Sensibull spot ({s_spot:.2f}) has minor discrepancy vs Numerical close ({n_close:.2f}): {s_diff:.2f} pts ({s_pct}%).")
            else:
                s_status = "SIGNIFICANT_DIFFERENCE"
                details.append(f"[DISCREPANCY] Sensibull spot ({s_spot:.2f}) diverges significantly from Numerical close ({n_close:.2f}): {s_diff:.2f} pts ({s_pct}%).")
                logger.warning("[DATA_MISMATCH_SENSIBULL] %s", details[-1])
        else:
            details.append("Sensibull vs Numerical comparison: Insufficient data (one or both values missing).")

        # 2. Evaluate TradingView vs Numerical
        tv_diff = None
        tv_pct = None
        tv_status = "INSUFFICIENT_DATA"

        if n_close is not None and tv_price is not None:
            tv_diff = round(abs(tv_price - n_close), 2)
            tv_pct = round((tv_diff / n_close) * 100.0, 3)

            if tv_pct <= self.match_tolerance_pct:
                tv_status = "MATCH"
                details.append(f"TradingView price ({tv_price:.2f}) matches Numerical close ({n_close:.2f}) within {self.match_tolerance_pct}% ({tv_pct}%).")
            elif tv_pct <= self.minor_tolerance_pct:
                tv_status = "MINOR_DIFFERENCE"
                details.append(f"TradingView price ({tv_price:.2f}) has minor discrepancy vs Numerical close ({n_close:.2f}): {tv_diff:.2f} pts ({tv_pct}%).")
            else:
                tv_status = "SIGNIFICANT_DIFFERENCE"
                details.append(f"[DISCREPANCY] TradingView price ({tv_price:.2f}) diverges significantly from Numerical close ({n_close:.2f}): {tv_diff:.2f} pts ({tv_pct}%).")
                logger.warning("[DATA_MISMATCH_TRADINGVIEW] %s", details[-1])
        else:
            details.append("TradingView vs Numerical comparison: Insufficient data (one or both values missing).")

        return MultiSourceComparisonResult(
            sensibull_spot=s_spot,
            tradingview_spot=tv_price,
            numerical_close=n_close,
            sensibull_vs_numerical_diff=s_diff,
            sensibull_vs_numerical_pct=s_pct,
            sensibull_vs_numerical_status=s_status,
            tradingview_vs_numerical_diff=tv_diff,
            tradingview_vs_numerical_pct=tv_pct,
            tradingview_vs_numerical_status=tv_status,
            details=details,
        )
