# HERMES DATA RESEARCH ZONE — ARCHITECTURE SPECIFICATION

**Document:** `docs/research/RESEARCH_ARCHITECTURE.md`  
**Zone Status:** Completely Segregated / Isolated from Main Trading Architecture  
**Version:** 1.0.0  
**Target Asset:** NIFTY 50 (F&O / Equities)

---

## 1. Purpose & Core Invariant

The **Hermes Data Research Zone** is an isolated quantitative laboratory operating completely separate from the live and paper trading decision and execution architecture.

```text
                 FUTURE DHAN DATA
                       │
                       ▼
              ┌─────────────────┐
              │ DATA ENGINEERING│
              │      ZONE       │
              ├─────────────────┤
              │ Ingestion       │
              │ Validation      │
              │ Cleaning        │
              │ Normalization   │
              │ Timeframes      │
              │ Feature Prep    │
              │ Data Quality    │
              └────────┬────────┘
                       │
                       ▼
              ┌─────────────────┐
              │ HERMES RESEARCH │
              │     ENGINE      │
              ├─────────────────┤
              │ Research        │
              │ Analysis        │
              │ Pattern Search  │
              │ Hypotheses      │
              │ Testing         │
              │ Contradictions  │
              │ Follow-up       │
              └────────┬────────┘
                       │
                       ▼
              ┌─────────────────┐
              │ HERMES          │
              │ ASSESSMENT      │
              ├─────────────────┤
              │ Independent     │
              │ Segment Scores  │
              │ Total Score     │
              │ Confidence      │
              │ Direction       │
              │ Trade Finding   │
              └────────┬────────┘
                       │
                       ▼
              RESEARCH DATABASE
```

### Strict System Boundaries:
1. **Zero Trading Execution:** The Research Zone has NO connections to broker execution engines, order managers, or position monitoring loops.
2. **Physical Database Segregation:** All research persistence resides strictly inside `data/hermes_research/` (`market_data.db`, `research.db`, `assessments.db`, `research_memory.db`).
3. **No Live API Dependency:** The zone is built around an abstract `DhanDataAdapter` with an offline deterministic mock provider (`MockDhanDataAdapter`). No live API credentials are required.
4. **Hermes as Autonomous Researcher:** Hermes acts as data engineer, hypothesis generator, backtester, contradiction analyst, and trade researcher.

---

## 2. Hermes Cognitive Research Loop

Hermes drives the investigation process by iteratively answering empirical questions:

```text
Hermes
  ↓
"What data do I need?" (Defines target symbol, date range, resolution, features)
  ↓
Prepare Dataset (Data Engineering Zone cleans, normalizes, resamples, computes features)
  ↓
"What patterns exist?" (Scans structural setups, compressions, order flow buildup)
  ↓
"Does this pattern hold historically?" (Formulates falsifiable hypothesis and tests over historical bars)
  ↓
Test Hypothesis (Computes sample size, win rate, profit factor, max drawdown, p-value)
  ↓
"What contradicts my finding?" (Actively hunts counter-examples, failure regimes, false positive rates)
  ↓
Follow-Up Research (Spawns targeted boundary condition inquiries)
  ↓
"Does this represent an opportunity?" (Synthesizes independent assessment with dynamic segment weighting)
  ↓
Memory Update (Records confirmed findings and failed hypotheses as Negative Knowledge)
```

---

## 3. Negative Knowledge Preservation

Failed hypotheses are treated as **first-class empirical findings**. When a backtest or contradiction search disproves an edge:
* A `FailedHypothesis` record is saved to `research_memory.db`.
* Future inquiries query research memory to verify whether a thesis was previously disproven, avoiding redundant compute and false confidence.

---

## 4. Future Integration Boundary

When the Research Zone is eventually integrated into the trading system in a future phase, it will connect via a strictly defined `ResearchIntegrationInterface`. It will supply structured empirical findings rather than bypassing safety guards or trading state machines.
