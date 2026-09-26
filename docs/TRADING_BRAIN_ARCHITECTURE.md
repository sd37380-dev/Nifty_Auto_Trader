# PACKAGE 4: TRADING BRAIN & MARKET REASONING ENGINE ARCHITECTURE

## 1. PURPOSE & BOUNDARIES

Package 4 (`nifty_trader.brain`) is the cognitive reasoning and market interpretation layer between canonical perception (`UnifiedMarketObservation` v1.0) and future Strategy, Risk, Approval, and Paper Trading engines.

### STRICT INVARIANTS:
1. **Zero Order Execution**: Package 4 is strictly an observation interpretation engine. It cannot generate broker orders, execute trades, or determine position sizing.
2. **First-Class Inaction**: `WAIT`, `NO_TRADE`, and `WATCH` are valid, respected cognitive states. The system is never forced to find a trade.
3. **Decoupled Architecture**: Strictly consumes canonical `UnifiedMarketObservation` contracts. Zero direct browser, network, or third-party scraper queries.
4. **Empirical Discipline**: Explicitly distinguishes between **Observed Facts** (traceable to `evidence_id`), **Inferences**, and **Hypotheses**.
5. **Traceable Auditability**: All reasoning runs, regimes, scenarios, hypotheses, and candidate trade theses are persisted in SQLite (`data/brain/reasoning_history.db`).

---

## 2. COMPONENT ARCHITECTURE

```text
       CANONICAL OBSERVATION INPUT
       UnifiedMarketObservation (v1.0)
                     │
                     ▼
          BrainContextCompiler
  (Extracts 1H/15M, Visuals, Derivatives,
   Cross-Checks, Operator Guidance, Evidence)
                     │
                     ▼
             Prompt Architecture
       (SYSTEM_REASONING_POLICY +
        build_reasoning_prompt)
                     │
                     ▼
                ModelRouter
       (Tier: TaskTier.MARKET_ANALYSIS)
        Primary: Gemini-2.5-Flash
        Fallback: OpenRouter / Claude
                     │
                     ▼
             BrainOutputValidator
   (Neutralizes prohibited execution keywords,
    clamps bounded confidence, validates theses)
                     │
                     ▼
                BrainStorage
     (Persists into reasoning_history.db)
                     │
                     ▼
            BrainReasoningOutput
```

---

## 3. CORE CONTRACTS & DOMAIN MODELS

- **`MarketRegime`**: `TRENDING_UP`, `TRENDING_DOWN`, `RANGING`, `TRANSITIONING`, `EXPANDING`, `CONTRACTING`, `UNCLEAR`.
- **`SetupState`**:
  - `NO_TRADE`: No meaningful actionable hypothesis exists.
  - `WAIT`: Confirmation missing or conditions incomplete.
  - `WATCH`: Interesting development requiring close monitoring.
  - `DEVELOPING`: Several conditions aligning, but setup incomplete.
  - `CANDIDATE`: Coherent trade thesis exists for future downstream strategy evaluation.
- **`Scenario`**: Multi-scenario evaluation with `confirmation_conditions`, `invalidation_conditions`, and confidence metrics.
- **`MarketHypothesis`**: Testable hypotheses across 1H and 15M timeframes.
- **`TradeCandidate`**: Non-executable candidate thesis drafting `direction` (LONG/SHORT/NEUTRAL), `thesis`, `market_context`, `setup_conditions`, `confirmation_conditions`, `invalidation_conditions`, and `required_downstream_information`.
- **`BoundedConfidence`**: Value between 0.0 and 1.0 with explicit empirical basis.
- **`ObservationRequest`**: Dynamic feedback loop requesting refreshed or additional observations.

---

## 4. AUDIT & CLI INTEGRATION

- **`nifty-trader brain-analyze`**: Executes full observation gathering and Trading Brain reasoning cycle with formatted rich terminal tables and panels.
- **`nifty-trader brain-history`**: Queries persisted reasoning runs from SQLite history.
