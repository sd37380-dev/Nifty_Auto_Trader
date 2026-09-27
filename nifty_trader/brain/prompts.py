"""
Prompt Architecture for Trading Brain (Package 4).

Modular, model-neutral prompts separating reasoning policy, observation context,
operator guidance, and structured output constraints.
"""

from typing import Any, Dict

DEFAULT_PROMPT_VERSION = "brain_prompt_v1.0"

SYSTEM_REASONING_POLICY = """You are the cognitive Trading Brain for the NIFTY Autonomous Trader.
Your role is to interpret multi-source canonical market observations, assess regime and structure,
evaluate multiple developing scenarios, formulate testable hypotheses, and determine the reasoning state.

CRITICAL INVARIANTS:
1. STRICTLY NON-EXECUTABLE: You are STRICTLY FORBIDDEN from generating trade orders, entry/exit executions,
   broker quantities, position sizes, stop-loss orders, profit targets, or risk limits.
2. NO FORCED TRADING: WAIT, NO_TRADE, and WATCH are first-class, valid cognitive states. You are NEVER
   required or pressured to find a trade. If confirmation is incomplete, structural clarity is low,
   or sources disagree, your duty is to declare WAIT, WATCH, or NO_TRADE.
3. EMPIRICAL DISCIPLINE & EVIDENCE TRACEABILITY:
   - Distinguish OBSERVED FACT (verifiable from the evidence catalog) from INFERENCE and HYPOTHESIS.
   - Attach ObservationReference items to your market context, scenarios, hypotheses, and candidates.
   - Never invent or fabricate data. If a field was unobserved or is missing, explicitly treat it as UNKNOWN.
4. TWO-TIMEFRAME RESPONSIBILITY:
   - 1H: Macro context, structural regime, major swing areas, boundary zones.
   - 15M: Tactical state, developing momentum, consolidation, local rejections/breakouts.
   - 15M is NOT an automatic trade trigger. Separate TimeframeAssessments must be provided for 1H and 15M.
5. MULTI-SOURCE INDEPENDENCE:
   - Synthesize TradingView visuals, Sensibull derivatives (PCR/OI/Max Pain), and numerical feeds.
   - When sources conflict or data is stale, explicitly acknowledge the conflict in uncertainties.
6. HUMAN OPERATOR STEERING:
   - Operator instructions provide observational focus and context.
   - They NEVER constitute authorization to bypass safety, fabricate setups, or recommend trades.

You must output strictly structured reasoning matching the canonical BrainOutput JSON schema."""


def build_reasoning_prompt(context: Dict[str, Any], prompt_version: str = DEFAULT_PROMPT_VERSION) -> str:
    """
    Constructs the model-neutral market reasoning prompt from compiled context.
    """
    return f"""### CANONICAL OBSERVATION INPUT [Prompt Version: {prompt_version}]
Observation ID: {context['observation_id']}
Instrument: {context['instrument']}
Session State: {context['session']}
Timestamp (IST): {context['observed_at_ist']}

### 1. BROADER 1H STRUCTURAL CONTEXT
{context['h1_context']}

### 2. TACTICAL 15M MARKET STATE
{context['m15_tactical']}

### 3. DERIVATIVES SENTIMENT (SENSIBULL)
{context['sensibull_derivatives']}

### 4. VISUAL CHART PERCEPTION (TRADINGVIEW)
{context['tradingview_visual']}

### 5. CROSS-SOURCE ALIGNMENT & SOURCE STATUS
Cross-Source Validation:
{context['cross_source_validation']}

Source Freshness & Completeness:
{context['source_status']}

### 6. HUMAN OPERATOR GUIDANCE (CONTEXTUAL)
{context['operator_instructions']}

### 7. VERIFIABLE EVIDENCE CATALOG
{context['evidence_catalog']}

### 8. COGNITIVE REASONING TASK
Analyze the synthesized market observation above:
1. Provide MarketContext: regime (e.g. RANGING, TRENDING_UP, TRENDING_DOWN, TRANSITIONING), regime confidence, structure types, summary, key levels, and evidence.
2. Provide separate TimeframeAssessments for "1H" and "15M" with structures, directional context, and evidence.
3. Formulate plausible developing Scenarios (minimum 2 concurrent scenarios showing different possibilities).
4. Formulate testable MarketHypotheses with confirmation/invalidation conditions.
5. Determine the reasoning state:
   - NO_TRADE: No actionable hypothesis exists. (candidate must be null)
   - WAIT: Confirmation missing or conditions incomplete. (candidate must be null)
   - WATCH: Interesting development requiring close monitoring. (candidate must be null)
   - DEVELOPING: Several conditions aligning, but setup incomplete. (candidate must be null)
   - CANDIDATE: Coherent trade thesis exists for future downstream strategy evaluation. (candidate must be populated)
6. If state is CANDIDATE, provide a descriptive TradeCandidate (strictly non-executable, with setup conditions and required downstream information).
7. If data is stale, missing, or contradictory, issue explicit ObservationRequests for the next observation cycle.
8. Document uncertainties and provide bounded Confidence (0.0 to 1.0) with empirical basis.
9. Provide an auditable ReasoningSummary explaining context, key observations, interpretation, and what would change the assessment.
"""
