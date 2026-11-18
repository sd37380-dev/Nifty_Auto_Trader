"""
OI Analysis Engine for NIFTY Futures Short Strategy.

Calculates:
- Filters option chain to ATM ±5 strikes (11 strikes total) centered around current Futures price.
- Identifies primary Call OI resistance considering:
  1. Strong Call OI (calls_oi)
  2. Call OI increase (calls_change_oi > 0)
  3. Distance from current Futures price
- Produces:
  OI_RESISTANCE (strike level)
  OI_RESISTANCE_STRENGTH (strength score 0.0 - 100.0)
"""

from typing import List, Optional, Tuple
from nifty_trader.strategies.short.contracts import OptionChainSnapshot, OptionStrikeData


class OIResistanceEngine:
    """
    Deterministic Call OI resistance detection engine.
    """

    @staticmethod
    def identify_call_oi_resistance(
        futures_price: float,
        option_chain: Optional[OptionChainSnapshot],
        atm_strikes: List[float],
    ) -> Tuple[Optional[float], Optional[float]]:
        """
        Identifies Call OI resistance from ATM ±5 strikes.
        Returns: (OI_RESISTANCE, OI_RESISTANCE_STRENGTH)
        """
        if option_chain is None or not option_chain.strikes:
            return None, None

        atm_set = set(round(s, 2) for s in atm_strikes)
        eligible = [s for s in option_chain.strikes if round(s.strike, 2) in atm_set]

        # If strict matching finds no strikes, fallback to closest 11 strikes in chain
        if not eligible:
            sorted_by_dist = sorted(option_chain.strikes, key=lambda s: abs(s.strike - futures_price))
            eligible = sorted_by_dist[:11]

        if not eligible:
            return None, None

        max_call_oi = max((s.calls_oi for s in eligible), default=0.0)
        if max_call_oi <= 0:
            return None, None

        pos_changes = [s.calls_change_oi for s in eligible if s.calls_change_oi > 0]
        max_call_change = max(pos_changes) if pos_changes else 1.0

        best_strike: Optional[float] = None
        best_score = -1.0

        for s in eligible:
            # 1. Strong Call OI
            norm_oi = max(0.0, s.calls_oi) / max_call_oi
            # 2. Call OI Increase (preferred)
            norm_change = max(0.0, s.calls_change_oi) / max_call_change if max_call_change > 0 else 0.0
            # 3. Proximity to current Futures price
            distance = abs(s.strike - futures_price)
            proximity = 1.0 / (1.0 + (distance / 100.0))

            # Composite weight: 40% OI volume, 40% OI change, 20% distance relevance
            score = (norm_oi * 0.40) + (norm_change * 0.40) + (proximity * 0.20)

            # Extra weight if strike is at or above current futures price (acting as overhead resistance)
            if s.strike >= (futures_price - 10.0):
                score += 0.05

            if score > best_score:
                best_score = score
                best_strike = s.strike

        if best_strike is None:
            return None, None

        strength = round(best_score * 100.0, 2)
        return best_strike, strength
