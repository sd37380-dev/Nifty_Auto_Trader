"""
Hermes Research Engine: Pattern Discovery, Hypothesis Testing, and Contradiction Search.

Implements the iterative empirical inquiry loop:
1. Question Formulation ("What data do I need?")
2. Pattern Discovery ("What patterns exist?")
3. Hypothesis Backtesting ("Does this pattern hold historically?")
4. Contradiction Search ("What contradicts my finding?")
5. Follow-up Formulation ("Research again with boundary conditions")
"""

from datetime import datetime, timezone
import logging
import math
from typing import Any, Dict, List, Optional, Tuple
import uuid

from nifty_trader.research_zone.contracts import (
    ContradictionSearch,
    FeatureRow,
    FeatureSet,
    FollowUpResearch,
    Hypothesis,
    HypothesisStatus,
    PatternDefinition,
    PatternType,
    ResearchQuestion,
    TestResult,
)

logger = logging.getLogger(__name__)


class HermesResearchEngine:
    """
    Autonomous empirical researcher executing systematic market pattern discovery,
    statistical hypothesis validation, and aggressive contradiction searching.
    """

    def __init__(self):
        self.default_patterns = self._init_default_patterns()

    def _init_default_patterns(self) -> List[PatternDefinition]:
        return [
            PatternDefinition(
                pattern_id="pat_bullish_vwap_breakout",
                name="VWAP Bullish Expansion",
                pattern_type=PatternType.BREAKOUT,
                description="Price closes above upper VWAP standard deviation band with rising volume and positive MACD histogram.",
                conditions=[
                    "close > vwap_std_upper",
                    "volume_ratio_20 > 1.2",
                    "macd_hist > 0",
                ],
                required_features=["close", "vwap_std_upper", "volume_ratio_20", "macd_hist"],
            ),
            PatternDefinition(
                pattern_id="pat_bearish_vwap_breakdown",
                name="VWAP Bearish Breakdown",
                pattern_type=PatternType.BREAKOUT,
                description="Price breaks below lower VWAP band with elevated volume and negative MACD histogram.",
                conditions=[
                    "close < vwap_std_lower",
                    "volume_ratio_20 > 1.2",
                    "macd_hist < 0",
                ],
                required_features=["close", "vwap_std_lower", "volume_ratio_20", "macd_hist"],
            ),
            PatternDefinition(
                pattern_id="pat_rsi_oversold_reversal",
                name="RSI Mean Reversion",
                pattern_type=PatternType.MEAN_REVERSION,
                description="RSI falls below 30 then crosses back above 30 in low/normal volatility regimes.",
                conditions=[
                    "rsi_14 < 30",
                ],
                required_features=["rsi_14"],
            ),
            PatternDefinition(
                pattern_id="pat_volatility_compression",
                name="ATR Volatility Compression Squeeze",
                pattern_type=PatternType.VOLATILITY_COMPRESSION,
                description="ATR drops significantly below historical norms indicating potential explosive expansion.",
                conditions=[
                    "atr_14_low",
                ],
                required_features=["atr_14"],
            ),
            PatternDefinition(
                pattern_id="pat_oi_long_buildup",
                name="OI Long Buildup Expansion",
                pattern_type=PatternType.OI_ACCUMULATION,
                description="Price rising concurrently with open interest expansion (> 2% OI change).",
                conditions=[
                    "oi_change_pct > 2.0",
                    "close > ema_20",
                ],
                required_features=["oi_change_pct", "close", "ema_20"],
            ),
        ]

    def formulate_question(
        self,
        topic: str,
        description: str,
        target_symbol: str = "NIFTY",
        target_timeframe: str = "15M",
        parameters: Optional[Dict[str, Any]] = None,
    ) -> ResearchQuestion:
        """Formulates a structured inquiry for Hermes to investigate."""
        return ResearchQuestion(
            question_id=f"rq_{uuid.uuid4().hex[:8]}",
            topic=topic,
            description=description,
            target_symbol=target_symbol,
            target_timeframe=target_timeframe,
            parameters=parameters or {},
            created_at=datetime.now(timezone.utc),
        )

    def formulate_hypothesis(
        self,
        question: ResearchQuestion,
        pattern: PatternDefinition,
        forward_bars: int = 5,
        target_return_pct: float = 0.5,
    ) -> Hypothesis:
        """Derives a falsifiable statistical hypothesis from a question and candidate pattern."""
        statement = (
            f"When pattern '{pattern.name}' occurs on {question.target_symbol} {question.target_timeframe}, "
            f"price advances by at least {target_return_pct}% over the subsequent {forward_bars} bars with >55% win rate."
        )
        testable_condition = f"Pattern: {pattern.pattern_id}; forward_bars: {forward_bars}; target_pct: {target_return_pct}"
        null_hypothesis = (
            f"Future forward return following '{pattern.name}' is indistinguishable from random noise (win rate <= 50%)."
        )
        return Hypothesis(
            hypothesis_id=f"hyp_{uuid.uuid4().hex[:8]}",
            question_id=question.question_id,
            statement=statement,
            testable_condition=testable_condition,
            null_hypothesis=null_hypothesis,
            parameters={
                "pattern_id": pattern.pattern_id,
                "forward_bars": forward_bars,
                "target_return_pct": target_return_pct,
            },
            status=HypothesisStatus.TESTING,
            created_at=datetime.now(timezone.utc),
        )

    def test_hypothesis(
        self,
        hypothesis: Hypothesis,
        feature_set: FeatureSet,
    ) -> Tuple[TestResult, HypothesisStatus]:
        """
        Empirically tests the hypothesis against a calculated FeatureSet.
        Computes sample size, win rate, profit factor, average return, and max drawdown.
        """
        rows = feature_set.rows
        if len(rows) < 30:
            result = TestResult(
                test_id=f"test_{uuid.uuid4().hex[:8]}",
                hypothesis_id=hypothesis.hypothesis_id,
                sample_size=len(rows),
                win_rate=0.0,
                profit_factor=0.0,
                avg_return_pct=0.0,
                max_drawdown_pct=0.0,
                p_value=1.0,
                summary=f"Insufficient sample size ({len(rows)} bars < 30 required).",
                tested_at=datetime.now(timezone.utc),
            )
            return result, HypothesisStatus.INCONCLUSIVE

        params = hypothesis.parameters
        forward_bars = params.get("forward_bars", 5)
        target_pct = params.get("target_return_pct", 0.5)
        pattern_id = params.get("pattern_id", "")

        # Identify signal indices based on pattern
        signal_indices: List[int] = []
        for i in range(len(rows) - forward_bars):
            r = rows[i]
            if self._matches_pattern_condition(r, pattern_id):
                signal_indices.append(i)

        if len(signal_indices) < 5:
            result = TestResult(
                test_id=f"test_{uuid.uuid4().hex[:8]}",
                hypothesis_id=hypothesis.hypothesis_id,
                sample_size=len(signal_indices),
                win_rate=0.0,
                profit_factor=0.0,
                avg_return_pct=0.0,
                max_drawdown_pct=0.0,
                p_value=1.0,
                summary=f"Extremely low signal occurrences ({len(signal_indices)} occurrences). Inconclusive.",
                tested_at=datetime.now(timezone.utc),
            )
            return result, HypothesisStatus.INCONCLUSIVE

        # Compute forward returns
        returns: List[float] = []
        wins: List[float] = []
        losses: List[float] = []

        for idx in signal_indices:
            entry_price = rows[idx].close
            exit_price = rows[idx + forward_bars].close
            ret_pct = ((exit_price - entry_price) / entry_price) * 100.0
            returns.append(ret_pct)
            if ret_pct >= target_pct:
                wins.append(ret_pct)
            else:
                losses.append(abs(ret_pct) if ret_pct < 0 else 0.01)

        win_rate = (len(wins) / len(returns)) * 100.0
        avg_ret = sum(returns) / len(returns) if returns else 0.0

        total_gain = sum(wins) if wins else 0.0
        total_loss = sum(losses) if losses else 0.01
        profit_factor = round(total_gain / max(total_loss, 0.001), 2)

        # Drawdown calculation
        cumulative = 0.0
        peak = 0.0
        max_dd = 0.0
        for r in returns:
            cumulative += r
            if cumulative > peak:
                peak = cumulative
            dd = peak - cumulative
            if dd > max_dd:
                max_dd = dd

        # Approximate p-value based on binomial distribution assumption (z-score)
        n = len(returns)
        p_hat = len(wins) / n
        p_0 = 0.5
        se = math.sqrt((p_0 * (1 - p_0)) / n) if n > 0 else 1.0
        z = (p_hat - p_0) / se if se > 0 else 0.0
        # Normal approximation two-tailed p-value
        p_value = round(math.erfc(abs(z) / math.sqrt(2)), 4) if z != 0 else 1.0

        summary = (
            f"Tested {len(returns)} occurrences: Win Rate = {win_rate:.1f}%, "
            f"Avg Return = {avg_ret:.2f}%, Profit Factor = {profit_factor}, Max DD = {max_dd:.2f}%, p-value = {p_value}"
        )

        status = HypothesisStatus.CONFIRMED if (win_rate >= 55.0 and profit_factor >= 1.25 and p_value < 0.05) else HypothesisStatus.REJECTED

        test_result = TestResult(
            test_id=f"test_{uuid.uuid4().hex[:8]}",
            hypothesis_id=hypothesis.hypothesis_id,
            sample_size=len(returns),
            win_rate=round(win_rate, 2),
            profit_factor=profit_factor,
            avg_return_pct=round(avg_ret, 2),
            max_drawdown_pct=round(max_dd, 2),
            p_value=p_value,
            summary=summary,
            tested_at=datetime.now(timezone.utc),
        )

        return test_result, status

    def search_contradictions(
        self,
        hypothesis: Hypothesis,
        feature_set: FeatureSet,
    ) -> ContradictionSearch:
        """
        Actively seeks counter-evidence, failure regimes, and false positives for a hypothesis.
        """
        rows = feature_set.rows
        forward_bars = hypothesis.parameters.get("forward_bars", 5)
        target_pct = hypothesis.parameters.get("target_return_pct", 0.5)
        pattern_id = hypothesis.parameters.get("pattern_id", "")

        failures: List[Tuple[FeatureRow, float]] = []
        failure_regimes_set = set()
        total_signals = 0

        for i in range(len(rows) - forward_bars):
            r = rows[i]
            if self._matches_pattern_condition(r, pattern_id):
                total_signals += 1
                entry_price = r.close
                exit_price = rows[i + forward_bars].close
                ret_pct = ((exit_price - entry_price) / entry_price) * 100.0

                if ret_pct < target_pct:
                    failures.append((r, ret_pct))
                    failure_regimes_set.add(r.regime_tag)

        counter_count = len(failures)
        fp_rate = (counter_count / max(total_signals, 1)) * 100.0

        findings = (
            f"Found {counter_count} counter-examples out of {total_signals} signals ({fp_rate:.1f}% failure rate). "
            f"Frequent failure regimes: {', '.join(failure_regimes_set) or 'None'}."
        )

        return ContradictionSearch(
            search_id=f"cntr_{uuid.uuid4().hex[:8]}",
            hypothesis_id=hypothesis.hypothesis_id,
            counter_examples_count=counter_count,
            failure_regimes=sorted(list(failure_regimes_set)),
            false_positive_rate=round(fp_rate, 2),
            findings=findings,
            conducted_at=datetime.now(timezone.utc),
        )

    def generate_followup(
        self,
        hypothesis: Hypothesis,
        contradiction: ContradictionSearch,
    ) -> Optional[FollowUpResearch]:
        """
        Spawns a follow-up inquiry based on identified failure regimes.
        """
        if not contradiction.failure_regimes:
            return None

        worst_regime = contradiction.failure_regimes[0]
        new_q = (
            f"Investigate if adding a filter against '{worst_regime}' regime eliminates "
            f"false positives for hypothesis '{hypothesis.statement}'."
        )
        rationale = (
            f"Contradiction search revealed {contradiction.counter_examples_count} counter-examples "
            f"with heavy concentration in '{worst_regime}' regime."
        )

        return FollowUpResearch(
            followup_id=f"fup_{uuid.uuid4().hex[:8]}",
            parent_research_id=hypothesis.hypothesis_id,
            new_question=new_q,
            rationale=rationale,
            created_at=datetime.now(timezone.utc),
        )

    def _matches_pattern_condition(self, r: FeatureRow, pattern_id: str) -> bool:
        """Evaluates whether a FeatureRow triggers a specific pattern condition."""
        if pattern_id == "pat_bullish_vwap_breakout":
            if r.vwap_std_upper and r.volume_ratio_20 and r.macd_hist is not None:
                return (r.close > r.vwap_std_upper) and (r.volume_ratio_20 > 1.1) and (r.macd_hist > 0)
        elif pattern_id == "pat_bearish_vwap_breakdown":
            if r.vwap_std_lower and r.volume_ratio_20 and r.macd_hist is not None:
                return (r.close < r.vwap_std_lower) and (r.volume_ratio_20 > 1.1) and (r.macd_hist < 0)
        elif pattern_id == "pat_rsi_oversold_reversal":
            if r.rsi_14 is not None:
                return r.rsi_14 < 32.0
        elif pattern_id == "pat_oi_long_buildup":
            if r.oi_change_pct is not None and r.ema_20 is not None:
                return (r.oi_change_pct > 1.5) and (r.close > r.ema_20)
        elif pattern_id == "pat_volatility_compression":
            if r.atr_14 is not None and r.close > 0:
                atr_ratio = (r.atr_14 / r.close) * 100.0
                return atr_ratio < 0.25

        # Fallback heuristic: close > ema_20 and positive volume
        if r.ema_20 is not None and r.volume_ratio_20 is not None:
            return r.close > r.ema_20 and r.volume_ratio_20 > 1.0
        return False
