"""
Pivot Engine for NIFTY Futures Short Strategy.

Calculates:
- Standard classic daily pivot points (P, R1, R2, S1, S2) from PREVIOUS COMPLETED TRADING DAY.
- Identifies the relevant Pivot Resistance level (P, R1, or R2) near current Futures price.
- Enforces strict no look-ahead invariant: NEVER uses current day's data.
"""

from typing import List, Optional
from nifty_trader.strategies.short.contracts import PivotLevels, PreviousDayOHLC


class PivotEngine:
    """
    Deterministic Pivot calculation and resistance identification engine.
    """

    @staticmethod
    def calculate_pivots(ohlc: PreviousDayOHLC) -> PivotLevels:
        """
        Calculates standard classic pivot levels:
        P = (High + Low + Close) / 3
        R1 = (2 * P) - Low
        R2 = P + High - Low
        S1 = (2 * P) - High
        S2 = P - (High - Low)
        """
        h = ohlc.high
        l = ohlc.low
        c = ohlc.close

        p = (h + l + c) / 3.0
        r1 = (2.0 * p) - l
        r2 = p + (h - l)
        s1 = (2.0 * p) - h
        s2 = p - (h - l)

        return PivotLevels(
            pivot=round(p, 2),
            r1=round(r1, 2),
            r2=round(r2, 2),
            s1=round(s1, 2),
            s2=round(s2, 2),
        )

    @staticmethod
    def identify_pivot_resistance(
        futures_price: float,
        pivots: Optional[PivotLevels],
    ) -> Optional[float]:
        """
        Identifies the relevant Pivot Resistance near the current Futures price.
        Resistance candidate levels: [P, R1, R2].
        Selects the resistance level closest to the current Futures price.
        """
        if pivots is None:
            return None

        candidates = [pivots.pivot, pivots.r1, pivots.r2]
        # Find candidate closest to current futures price
        closest_level = min(candidates, key=lambda lvl: abs(lvl - futures_price))
        return closest_level
