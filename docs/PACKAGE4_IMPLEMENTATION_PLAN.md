# PACKAGE 4 — TRADING BRAIN & MARKET REASONING ENGINE IMPLEMENTATION PLAN

## 1. Executive Summary

Package 4 introduces the **cognitive reasoning and market interpretation layer** of the NIFTY Autonomous Trader. It sits squarely between the canonical observation layer (Package 3 / 3.1) and future downstream modules (Strategy, Risk, Approval, Paper Broker).

Package 4 answers the core question:
> **"Given what the system has observed, what does it mean, what scenarios are developing, what should be watched, and is there currently a meaningful trading hypothesis?"**

### Strict Invariants & Non-Negotiable Boundaries:
1. **No Order Execution & No Risk Sizing**: Package 4 produces *reasoning outputs and candidate theses only*. It does NOT decide position sizing, monetary stop-loss amounts, daily loss limits, broker orders, or paper trade execution.
2. **Canonical Contract Input Only**: Package 4 strictly consumes `UnifiedMarketObservation` (v1.0) assembled by the canonical contracts layer (`nifty_trader/contracts`). It does NOT make direct calls to TradingView, Sensibull, Yahoo Finance, or browser providers.
3. **ModelRouter Decoupling**: All AI calls route through `ModelRouter` (Package 1). Gemini is the default initial brain, but prompts and contracts are 100% model-neutral (OpenRouter, Claude, GPT compatible).
4. **No Forced Trading & First-Class States**: `WAIT`, `NO_TRADE`, and `WATCH` are valid, dignified cognitive states. The brain is explicitly rewarded for patience when confirmation is incomplete.
5. **Observed Fact vs. Inference vs. Hypothesis**: The system explicitly tags whether a conclusion stems from verifiable evidence (`evidence_id`), model inference, or speculative scenario.
6. **No Hidden Chain-of-Thought**: Produces structured, auditable reasoning records stored persistently in `data/brain/`.

---

## 2. Pipeline Architecture

```text
                  PACKAGE 3 / 3.1 & CANONICAL CONTRACTS
                        (What does the market look like?)
                                       │
                                       ▼
                       UnifiedMarketObservation (v1.0)
                                       │
                                       ▼
                         ┌───────────────────────────┐
                         │         PACKAGE 4         │
                         │       TRADING BRAIN       │
                         │                           │
                         │  * Multi-Source Synthesis │
                         │  * 1H & 15M Interpretation│
                         │  * Source Conflict Check  │
                         │  * Scenario Engine        │
                         │  * Hypothesis Formation   │
                         │  * Observation Requests   │
                         │  * Auditable Reasoning    │
                         └─────────────┬─────────────┘
                                       │
                    ┌──────────────────┼──────────────────┐
                    ▼                  ▼                  ▼
                 NO_TRADE            WAIT / WATCH       CANDIDATE
             (Nothing to do)      (Pending Confirm)         │
                                                            ▼
                                                   FUTURE STRATEGY ENGINE
                                                            │
                                                            ▼
                                                    FUTURE RISK ENGINE
                                                            │
                                                            ▼
                                                   FUTURE PAPER BROKER
```

---

## 3. Package Structure (`nifty_trader/brain/`)

1. **`contracts.py`**:
   - `MarketRegime`: `TRENDING_UP`, `TRENDING_DOWN`, `RANGING`, `TRANSITIONING`, `EXPANDING`, `CONTRACTING`, `UNCLEAR`
   - `SetupState`: `NO_TRADE`, `WAIT`, `WATCH`, `DEVELOPING`, `CANDIDATE`
   - `Scenario`: Multiple concurrent scenarios with supporting/contradicting evidence and invalidation conditions
   - `MarketHypothesis`: Plausible interpretations with confirmation and invalidation rules
   - `TradeCandidate`: Descriptive trade thesis (direction: `LONG`, `SHORT`, `NEUTRAL`, rationale, invalidation conditions, required downstream risk info). No broker orders.
   - `ObservationRequest`: Mechanism for requesting fresh observations (e.g. re-inspect Sensibull ATM strikes)
   - `BoundedConfidence`: Perceptual and reasoning confidence (0.0 - 1.0) with explicit basis
   - `Uncertainty`: Documented ambiguities (stale data, source conflicts, ambiguous structure)
   - `BrainReasoningOutput`: The canonical output contract of Package 4
2. **`context.py`**:
   - `BrainContextCompiler`: Formats `UnifiedMarketObservation` into structured context for the reasoning prompt, segregating 1H structural regime, 15M tactical state, Sensibull derivatives sentiment, TradingView visuals, cross-source validations, and operator instructions.
3. **`prompts.py`**:
   - Modular, model-neutral prompt architecture enforcing system reasoning policy, hallucination defense, and structured output adherence.
4. **`validators.py`**:
   - Validates model responses against strict Pydantic schemas, ensures evidence traceability, and filters out prohibited execution directives.
5. **`storage.py`**:
   - Persistent SQLite ledger (`data/brain/reasoning_history.db`) saving full reasoning runs, timestamps, model metadata, and outputs.
6. **`engine.py`**:
   - `TradingBrainEngine`: Orchestrates observation input, source conflict check, ModelRouter call (`TaskTier.MARKET_ANALYSIS`), fallback handling (`BRAIN_UNAVAILABLE` -> safe `WAIT`), and persistence.

---

## 4. Implementation Steps

1. Create `nifty_trader/brain/contracts.py`.
2. Create `nifty_trader/brain/context.py`.
3. Create `nifty_trader/brain/prompts.py`.
4. Create `nifty_trader/brain/validators.py`.
5. Create `nifty_trader/brain/storage.py`.
6. Create `nifty_trader/brain/engine.py`.
7. Create `nifty_trader/brain/__init__.py`.
8. Integrate `TradingBrainEngine` into `NiftyTraderRuntime` (`nifty_trader/core/runtime.py`).
9. Extend CLI in `nifty_trader/cli.py` (`brain-analyze`, `brain-history`).
10. Update `config/features.yaml` and `config/release-manifest.yaml`.
11. Write comprehensive test suite (`tests/test_brain_*.py`).
12. Verify live with Gemini reasoning.
13. Write documentation and lock Package 4.
