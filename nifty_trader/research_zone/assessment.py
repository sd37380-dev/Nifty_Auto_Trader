"""
Hermes Assessment & Dynamic Scoring Engine.

STRICT INVARIANT:
No fixed or static percentage weights (e.g., Trend=25%, Momentum=20%, Volume=20%, etc.).
Hermes dynamically evaluates context-driven segments and assigns situational importance:

    Total Score = Sum(Segment Score_i * Segment Importance_i) / Sum(Segment Importance_i)
"""

from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional
import uuid

from nifty_trader.research_zone.contracts import (
    AssessmentSegment,
    ContradictionSearch,
    FeatureRow,
    HermesResearchAssessment,
    Hypothesis,
    MarketDirection,
    TestResult,
)

logger = logging.getLogger(__name__)


class HermesAssessmentEngine:
    """
    Synthesizes empirical findings, feature metrics, and contradiction searches
    into an independent assessment with dynamic segment weighting.
    """

    def generate_assessment(
        self,
        instrument: str,
        timeframe: str,
        latest_feature: FeatureRow,
        hypothesis: Optional[Hypothesis] = None,
        test_result: Optional[TestResult] = None,
        contradiction: Optional[ContradictionSearch] = None,
        option_chain_summary: Optional[Dict[str, Any]] = None,
    ) -> HermesResearchAssessment:
        """
        Dynamically derives assessment segments, dynamic importance weights,
        total aggregated score, direction, and confidence.
        """
        segments: List[AssessmentSegment] = []
        regime = latest_feature.regime_tag

        # ------------------------------------------------------------------
        # 1. Segment: Trend & Market Structure
        # ------------------------------------------------------------------
        trend_score = 0.0
        trend_reasons = []
        if latest_feature.ema_20 and latest_feature.ema_50:
            if latest_feature.close > latest_feature.ema_20 > latest_feature.ema_50:
                trend_score = 65.0
                trend_reasons.append("Price above EMA20 and EMA50 (Bullish structural stack)")
            elif latest_feature.close < latest_feature.ema_20 < latest_feature.ema_50:
                trend_score = -65.0
                trend_reasons.append("Price below EMA20 and EMA50 (Bearish structural stack)")
            else:
                trend_score = 0.0
                trend_reasons.append("EMAs intertwined, no clean directional slope")

        # Dynamic importance for Trend: higher in trending regimes, lower in range/choppy
        trend_importance = 0.85 if "TRENDING" in regime else 0.40
        segments.append(
            AssessmentSegment(
                segment_id=f"seg_{uuid.uuid4().hex[:6]}",
                name="Trend & Market Structure",
                score=trend_score,
                importance=trend_importance,
                evidence=[f"Close={latest_feature.close}", f"Regime={regime}"],
                reasoning_summary="; ".join(trend_reasons) or "Neutral market structure",
            )
        )

        # ------------------------------------------------------------------
        # 2. Segment: Momentum & Volume Expansion
        # ------------------------------------------------------------------
        mom_score = 0.0
        mom_reasons = []
        if latest_feature.rsi_14 is not None:
            if latest_feature.rsi_14 > 60:
                mom_score += 35.0
                mom_reasons.append(f"RSI bullish expansion at {latest_feature.rsi_14:.1f}")
            elif latest_feature.rsi_14 < 40:
                mom_score -= 35.0
                mom_reasons.append(f"RSI bearish compression at {latest_feature.rsi_14:.1f}")
        if latest_feature.macd_hist is not None:
            if latest_feature.macd_hist > 0:
                mom_score += 25.0
                mom_reasons.append("Positive MACD histogram")
            else:
                mom_score -= 25.0
                mom_reasons.append("Negative MACD histogram")
        if latest_feature.volume_ratio_20 and latest_feature.volume_ratio_20 > 1.2:
            mom_reasons.append(f"Volume surge ({latest_feature.volume_ratio_20:.2f}x 20SMA)")

        # Dynamic importance: high when volume and volatility expand
        mom_importance = 0.80 if (latest_feature.volume_ratio_20 or 1.0) > 1.2 else 0.50
        segments.append(
            AssessmentSegment(
                segment_id=f"seg_{uuid.uuid4().hex[:6]}",
                name="Momentum & Volume Expansion",
                score=max(min(mom_score, 100.0), -100.0),
                importance=mom_importance,
                evidence=[f"RSI={latest_feature.rsi_14}", f"MACD_Hist={latest_feature.macd_hist}"],
                reasoning_summary="; ".join(mom_reasons) or "Neutral momentum",
            )
        )

        # ------------------------------------------------------------------
        # 3. Segment: Order Flow & Open Interest
        # ------------------------------------------------------------------
        oi_score = 0.0
        oi_reasons = []
        oi_importance = 0.50

        if latest_feature.oi_change_pct is not None:
            if latest_feature.oi_change_pct > 2.0 and latest_feature.close > (latest_feature.ema_20 or 0):
                oi_score = 70.0
                oi_reasons.append(f"Aggressive long buildup (+{latest_feature.oi_change_pct:.1f}% OI)")
                oi_importance = 0.85
            elif latest_feature.oi_change_pct > 2.0 and latest_feature.close < (latest_feature.ema_20 or float("inf")):
                oi_score = -70.0
                oi_reasons.append(f"Aggressive short buildup (+{latest_feature.oi_change_pct:.1f}% OI)")
                oi_importance = 0.85
            elif latest_feature.oi_change_pct < -2.0:
                oi_score = 15.0 if latest_feature.close > (latest_feature.ema_20 or 0) else -15.0
                oi_reasons.append(f"Short covering or long unwinding ({latest_feature.oi_change_pct:.1f}% OI)")
                oi_importance = 0.60

        if option_chain_summary:
            pcr = option_chain_summary.get("pcr", 1.0)
            if pcr > 1.3:
                oi_score += 15.0
                oi_reasons.append(f"High PCR ({pcr:.2f}) indicates strong put writing support")
            elif pcr < 0.7:
                oi_score -= 15.0
                oi_reasons.append(f"Low PCR ({pcr:.2f}) indicates heavy call writing overhead")

        segments.append(
            AssessmentSegment(
                segment_id=f"seg_{uuid.uuid4().hex[:6]}",
                name="Order Flow & Open Interest",
                score=max(min(oi_score, 100.0), -100.0),
                importance=oi_importance,
                evidence=[f"OI_change={latest_feature.oi_change_pct}%"],
                reasoning_summary="; ".join(oi_reasons) or "Neutral OI dynamics",
            )
        )

        # ------------------------------------------------------------------
        # 4. Segment: Contradiction & Falsification Check
        # ------------------------------------------------------------------
        contra_score = 0.0
        contra_reasons = []
        contra_importance = 0.60

        if contradiction:
            # High false positive rate dampens bullish/bearish conviction towards 0 or negative
            fp = contradiction.false_positive_rate
            if fp > 50.0:
                contra_score = -50.0  # Heavy skepticism penalty
                contra_importance = 0.90
                contra_reasons.append(f"Elevated failure rate in contradiction search: {fp:.1f}%")
            elif fp < 30.0:
                contra_score = 40.0   # Low contradiction reinforces thesis
                contra_importance = 0.75
                contra_reasons.append(f"Contradiction search found low failure rate ({fp:.1f}%)")
            else:
                contra_score = 0.0
                contra_importance = 0.60
                contra_reasons.append(f"Moderate contradiction failure rate ({fp:.1f}%)")
        else:
            contra_reasons.append("No active contradiction search conducted")

        segments.append(
            AssessmentSegment(
                segment_id=f"seg_{uuid.uuid4().hex[:6]}",
                name="Contradiction & Falsification Check",
                score=contra_score,
                importance=contra_importance,
                evidence=[contradiction.findings if contradiction else "None"],
                reasoning_summary="; ".join(contra_reasons),
            )
        )

        # ------------------------------------------------------------------
        # 5. Segment: Empirical Hypothesis Validation
        # ------------------------------------------------------------------
        if test_result:
            hypo_score = (test_result.win_rate - 50.0) * 2.0  # e.g., 60% win rate -> +20.0
            hypo_importance = 0.85 if test_result.sample_size >= 20 else 0.45
            segments.append(
                AssessmentSegment(
                    segment_id=f"seg_{uuid.uuid4().hex[:6]}",
                    name="Empirical Hypothesis Validation",
                    score=max(min(hypo_score, 100.0), -100.0),
                    importance=hypo_importance,
                    evidence=[f"Sample={test_result.sample_size}", f"WinRate={test_result.win_rate}%"],
                    reasoning_summary=test_result.summary,
                )
            )

        # ------------------------------------------------------------------
        # Dynamic Total Score Computation
        # Total Score = Sum(Score_i * Importance_i) / Sum(Importance_i)
        # ------------------------------------------------------------------
        total_importance = sum(s.importance for s in segments)
        if total_importance > 0:
            weighted_sum = sum(s.score * s.importance for s in segments)
            total_score = round(weighted_sum / total_importance, 2)
        else:
            total_score = 0.0

        # Confidence calculation
        # Baseline confidence from segment importance weights and agreement
        agreement_count = sum(1 for s in segments if (s.score > 10 and total_score > 10) or (s.score < -10 and total_score < -10))
        agreement_ratio = agreement_count / max(len(segments), 1)
        base_confidence = 0.4 + (0.5 * agreement_ratio)

        # Contradiction penalty
        if contradiction and contradiction.false_positive_rate > 45.0:
            base_confidence = max(base_confidence - 0.20, 0.25)

        confidence = round(max(min(base_confidence, 0.95), 0.1), 2)

        # Direction Assignment
        if total_score >= 25.0 and confidence >= 0.55:
            direction = MarketDirection.BULLISH
        elif total_score <= -25.0 and confidence >= 0.55:
            direction = MarketDirection.BEARISH
        elif confidence < 0.50:
            direction = MarketDirection.UNCLEAR
        else:
            direction = MarketDirection.NEUTRAL

        # Gather supporting / contradictory evidence
        supporting = []
        contradictory = []
        for s in segments:
            if (direction == MarketDirection.BULLISH and s.score > 20) or (direction == MarketDirection.BEARISH and s.score < -20):
                supporting.append(f"{s.name}: {s.reasoning_summary}")
            elif (direction == MarketDirection.BULLISH and s.score < -20) or (direction == MarketDirection.BEARISH and s.score > 20):
                contradictory.append(f"{s.name}: {s.reasoning_summary}")

        trade_finding = (
            f"Autonomous Research Assessment indicates {direction.value} outlook for {instrument} {timeframe} "
            f"(Total Score: {total_score}, Confidence: {confidence*100:.0f}%)."
        )

        return HermesResearchAssessment(
            research_id=f"rass_{uuid.uuid4().hex[:8]}",
            timestamp=datetime.now(timezone.utc),
            instrument=instrument,
            timeframe=timeframe,
            segments=segments,
            total_score=total_score,
            confidence=confidence,
            direction=direction,
            trade_finding=trade_finding,
            supporting_evidence=supporting,
            contradictory_evidence=contradictory,
            uncertainty=[
                "Mock Dhan adapter in offline mode",
                f"Market regime tagged as {regime}",
            ],
            metadata={
                "regime": regime,
                "latest_close": latest_feature.close,
                "total_segments_evaluated": len(segments),
            },
        )
