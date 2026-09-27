"""
Brain Context Compiler.

Synthesizes the canonical UnifiedMarketObservation into a structured,
evidence-traceable context for the ModelRouter and Trading Brain reasoning prompts.
"""

from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional

from nifty_trader.contracts.models import (
    CanonicalObservationStatus,
    CrossSourceValidationStatus,
    UnifiedMarketObservation,
)

logger = logging.getLogger(__name__)


class BrainContextCompiler:
    """
    Compiles UnifiedMarketObservation into organized contextual sections for AI reasoning.
    """

    def compile(
        self,
        obs: UnifiedMarketObservation,
        previous_brain_state: Optional[Any] = None,
        requested_focus: Optional[List[str]] = None,
        memory_context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Extracts and formats observation components.
        """
        # 1. Numerical 1H & 15M Context
        c1h = obs.numerical.candles_1h
        c15m = obs.numerical.candles_15m

        h1_recent = c1h[-5:] if c1h else []
        m15_recent = c15m[-10:] if c15m else []

        h1_text = (
            f"Total 1H Candles: {len(c1h)}\n"
            + "\n".join(
                f"  * {c.timestamp_ist.strftime('%Y-%m-%d %H:%M')}: Open={c.open:.2f}, High={c.high:.2f}, Low={c.low:.2f}, Close={c.close:.2f}, Volume={c.volume or 0}"
                for c in h1_recent
            )
            if h1_recent
            else "No 1H candles available."
        )

        m15_text = (
            f"Total 15M Candles: {len(c15m)}\n"
            + "\n".join(
                f"  * {c.timestamp_ist.strftime('%Y-%m-%d %H:%M')}: Open={c.open:.2f}, High={c.high:.2f}, Low={c.low:.2f}, Close={c.close:.2f}, Volume={c.volume or 0}"
                for c in m15_recent
            )
            if m15_recent
            else "No 15M candles available."
        )

        # 2. Visual Context (TradingView)
        tv = obs.visual.tradingview
        tv_text = "TradingView Visual: Not interrogated in this observation cycle."
        if tv:
            tv_text = (
                f"TradingView Status: {tv.status.value}\n"
                f"Observed Price: {tv.visible_price or 'N/A'}\n"
                f"Chart Context: {tv.visible_chart_context}\n"
                f"Visible Text Excerpt: {tv.visible_text[:300] if tv.visible_text else 'None'}\n"
                f"Screenshot Reference: {tv.screenshot or 'None'}\n"
                f"Evidence IDs: {', '.join(tv.evidence_ids) if tv.evidence_ids else 'None'}"
            )

        # 3. Derivatives Context (Sensibull)
        sensi = obs.visual.sensibull
        sensi_text = "Sensibull Derivatives: Not interrogated in this observation cycle."
        if sensi:
            strikes_str = ", ".join(f"{s:.0f}" for s in sensi.visible_strikes[:8]) if sensi.visible_strikes else "None"
            sensi_text = (
                f"Sensibull Status: {sensi.status.value}\n"
                f"Spot Reference: {sensi.spot_reference or 'N/A'}\n"
                f"Put-Call Ratio (PCR): {sensi.pcr if sensi.pcr is not None else 'NULL (Unobserved)'}\n"
                f"Max Pain Strike: {sensi.max_pain or 'N/A'}\n"
                f"ATM Implied Volatility: {sensi.implied_volatility.get('atm_iv') or 'N/A'}%\n"
                f"Visible Strikes: {strikes_str}\n"
                f"Important Levels: {sensi.important_visible_levels}\n"
                f"Evidence IDs: {', '.join(sensi.evidence_ids) if sensi.evidence_ids else 'None'}"
            )

        # 4. Cross-Source Validation
        cross_lines = []
        for csv in obs.cross_source_validation:
            status_tag = f"[{csv.status.value}]"
            cross_lines.append(
                f"  * {status_tag} {csv.source_a} vs {csv.source_b} on {csv.field}: diff={csv.absolute_difference} ({csv.relative_difference}%)"
            )
        cross_text = "\n".join(cross_lines) if cross_lines else "No cross-source discrepancies identified."

        # 5. Source Status & Freshness
        src_lines = []
        for sid, st in obs.source_status.items():
            src_lines.append(f"  * {sid}: Status={st.status.value}, Completeness={st.completeness:.2f}")
        sources_text = "\n".join(src_lines)

        # 6. Active Operator Instructions
        inst_lines = []
        for inst in obs.manual_instruction_context:
            inst_lines.append(f"  * [{inst.priority}] {inst.text} (Status: {inst.status})")
        instructions_text = "\n".join(inst_lines) if inst_lines else "No active human operator instructions."

        # 7. Verifiable Evidence IDs Catalog
        ev_lines = []
        for ev in obs.evidence:
            ev_lines.append(f"  * {ev.evidence_id}: [{ev.evidence_type.value}] from {ev.source_id} - {ev.excerpt or ev.reference or 'Evidence artifact'}")
        evidence_text = "\n".join(ev_lines) if ev_lines else "No evidence artifacts attached."

        # 8. Previous Brain State Continuity
        prev_state_text = None
        if previous_brain_state:
            hypos = []
            for h in getattr(previous_brain_state, "hypotheses", []):
                h_dir = h.direction.value if hasattr(h.direction, "value") else str(h.direction)
                h_conf = h.confidence.value if hasattr(h.confidence, "value") else str(h.confidence)
                hypos.append(f"  * [{h.hypothesis_id}] ({h_dir}, {h_conf}): {h.statement}")
            hypos_str = "\n".join(hypos) if hypos else "None recorded."

            scens = []
            for s in getattr(previous_brain_state, "scenarios", []):
                s_dir = s.direction.value if hasattr(s.direction, "value") else str(s.direction)
                s_conf = s.confidence.value if hasattr(s.confidence, "value") else str(s.confidence)
                scens.append(f"  * [{s.scenario_id}] ({s_dir}, {s_conf}): {s.description}")
            scens_str = "\n".join(scens) if scens else "None recorded."

            regime_val = previous_brain_state.market_context.regime.value if hasattr(previous_brain_state.market_context.regime, "value") else str(previous_brain_state.market_context.regime)
            reasoning_val = previous_brain_state.reasoning_state.value if hasattr(previous_brain_state.reasoning_state, "value") else str(previous_brain_state.reasoning_state)

            prev_state_text = (
                f"Previous State ID: {previous_brain_state.state_id}\n"
                f"Previous Reasoning State: {reasoning_val}\n"
                f"Previous Market Regime: {regime_val} ({previous_brain_state.market_context.summary})\n"
                f"Active Hypotheses from Prior Cycle:\n{hypos_str}\n"
                f"Developing Scenarios from Prior Cycle:\n{scens_str}"
            )

        # 9. Requested Observation Focus
        focus_text = None
        if requested_focus:
            focus_text = "\n".join(f"  * {f}" for f in requested_focus)

        return {
            "observation_id": obs.observation_id,
            "instrument": obs.instrument,
            "session": obs.session,
            "observed_at_ist": obs.observed_at_ist.strftime("%Y-%m-%d %H:%M:%S IST"),
            "h1_context": h1_text,
            "m15_tactical": m15_text,
            "tradingview_visual": tv_text,
            "sensibull_derivatives": sensi_text,
            "cross_source_validation": cross_text,
            "source_status": sources_text,
            "operator_instructions": instructions_text,
            "evidence_catalog": evidence_text,
            "previous_brain_state": prev_state_text,
            "requested_focus": focus_text,
            "memory_context": memory_context,
            "warnings": [w.message for w in obs.warnings],
        }
