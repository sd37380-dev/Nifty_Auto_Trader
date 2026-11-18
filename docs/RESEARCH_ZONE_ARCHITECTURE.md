# HERMES RESEARCH & INTELLIGENCE ZONE — ARCHITECTURE SPECIFICATION

**Zone Status:** ISOLATED RESEARCH & INTELLIGENCE ZONE (STANDALONE)  
**Schema Version:** 1.0  
**Primary Engine:** Hermes Autonomous Research & Analytics Engine  
**Broker Integration Status:** Mock/Synthetic Data Adapter (Dhan-Ready, zero API dependencies required)  
**Database Segregation:** `data/hermes_research/` (strictly segregated from live/paper trading storage)

---

## 1. Executive Purpose & Scope

The **Hermes Research & Intelligence Zone** is an autonomous market exploration, empirical research, hypothesis generation, backtesting, contradiction search, and dynamic scoring environment.

It operates as an independent research sandbox:
- **No live trading dependencies**: Does not require real Dhan API keys or active broker sessions.
- **Dhan-Ready Interface**: Built on a clean `DhanDataAdapter` contract. When real Dhan credentials or WebSocket feeds become available later, the adapter is plugged in without redesigning any research, analysis, or memory code.
- **Physical & Logical Segregation**: Has dedicated SQLite stores located strictly in `data/hermes_research/` completely isolated from `data/paper_trading/`, `data/monitoring/`, and `data/experience/`.
- **Zero Fixed Scoring Weights**: Hermes calculates dynamic segment importances based on specific market regime and research context, never hard-coded static percentages.

---

## 2. End-to-End Zone Architecture

```text
                        Dhan Broker Data
                                │
                        [Future Input]
                                │
                                ▼
                    ┌──────────────────────┐
                    │   DATA ENGINEERING   │
                    │         ZONE         │
                    │                      │
                    │ Ingestion            │
                    │ Validation           │
                    │ Cleaning             │
                    │ Normalization        │
                    │ Timeframe Generation │
                    │ Feature Preparation  │
                    │ Data Quality         │
                    └──────────┬───────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │   HERMES RESEARCH    │
                    │       ENGINE         │
                    │                      │
                    │ Historical Research  │
                    │ Pattern Discovery    │
                    │ Market Analysis      │
                    │ Hypothesis Generation│
                    │ Hypothesis Testing   │
                    │ Trade Research       │
                    │ Contradiction Search │
                    │ Follow-up Research   │
                    └──────────┬───────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │  HERMES ASSESSMENT   │
                    │                      │
                    │ Independent scoring  │
                    │                      │
                    │ Segment 1            │
                    │ Segment 2            │
                    │ Segment 3            │
                    │ ...                  │
                    │                      │
                    │ Total Score          │
                    │ Confidence           │
                    │ Direction            │
                    │ Trade Finding        │
                    └──────────┬───────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │   RESEARCH MEMORY    │
                    │      DATABASE        │
                    │                      │
                    │ Raw Dhan Data        │
                    │ Research datasets    │
                    │ Research questions   │
                    │ Experiments          │
                    │ Findings             │
                    │ Failed hypotheses    │
                    │ Trade findings       │
                    │ Scores               │
                    │ Evidence             │
                    │ Research history     │
                    └──────────────────────┘
```

---

## 3. Core Operating Principle: Hermes as Autonomous Data Engineer + Researcher + Analyst

Hermes does not simply query a database. Hermes orchestrates the cognitive research loop:

```text
Hermes
  ↓
"What data do I need?" (Defines symbols, date range, resolution, features)
  ↓
Prepare dataset (Data Engineering zone ingests, validates, normalizes, resamples, computes features)
  ↓
"What patterns exist?" (Scans structural levels, order flow proxies, volatility compressions)
  ↓
Research (Forms qualitative observations into empirical candidate patterns)
  ↓
"Does this pattern hold historically?" (Formulates falsifiable hypothesis and tests across historical bars)
  ↓
Test (Evaluates win rate, sample size, expectancy, drawdown)
  ↓
"What contradicts my finding?" (Actively hunts for counter-examples, failed breakouts, regime breakdowns)
  ↓
Research again (Adjusts scope, documents boundary conditions)
  ↓
"Does this represent a trade opportunity?" (Derives trading thesis with supporting/opposing evidence)
  ↓
Independent assessment (Evaluates context-specific segments)
  ↓
Segment Scores & Dynamic Importances
  ↓
Total Score & Confidence
```

---

## 4. Independent Dynamic Scoring Engine

Static, rigid weights (such as `Trend=25%, Momentum=20%, Volume=20%, OI=20%, Volatility=15%`) are **strictly prohibited**. 

Market contexts change:
- In a runaway momentum trend, trend continuity and volume expansion matter far more than oscillating indicators.
- During monthly option expiry, Open Interest buildup, Max Pain, and gamma pinning matter far more than historical chart patterns.
- During range-bound consolidation, support/resistance reaction and mean reversion matter far more than trend-following indicators.

Hermes dynamically evaluates segments and assigns context-driven `importance` (weight) values:

$$\text{Total Score} = \frac{\sum_{i=1}^n \left(\text{Segment Score}_i \times \text{Segment Importance}_i\right)}{\sum_{i=1}^n \text{Segment Importance}_i}$$

### Canonical Assessment Model (`HermesResearchAssessment`):
- `research_id`: Unique identifier
- `timestamp`: UTC timestamp of assessment
- `instrument`: e.g. "NIFTY"
- `timeframe`: e.g. "15M", "1H"
- `segments`: List of `AssessmentSegment`
  - `name`: Segment category (e.g. "Structural Regime", "Order Flow & OI", "Momentum", "Contradiction Check")
  - `score`: Value in range $[-100.0, +100.0]$
  - `importance`: Dynamic importance in range $[0.0, 1.0]$
  - `evidence`: Specific verifiable evidence references
  - `reasoning_summary`: Concise justification for score and assigned importance
- `total_score`: Dynamically aggregated score $[-100.0, +100.0]$
- `confidence`: Confidence rating $[0.0, 1.0]$
- `direction`: `BULLISH`, `BEARISH`, `NEUTRAL`, or `UNCLEAR`
- `trade_finding`: Actionable research takeaway
- `supporting_evidence`: Traceable supporting evidence items
- `contradictory_evidence`: Explicit counter-evidence documented by contradiction search
- `uncertainty`: Documented unknowns and data limitations

---

## 5. Dedicated Research Database Layout

The research database files reside strictly in `data/hermes_research/`:

```text
data/
│
├── existing/
│   └── ... existing trading databases
│
└── hermes_research/
    ├── market_data.db        (Raw payloads, normalized 1M/5M/15M/1H bars, engineered feature sets)
    ├── research.db           (Research questions, pattern specs, hypothesis test executions)
    ├── assessments.db        (Hermes dynamic assessments, segments, scores, findings)
    └── research_memory.db    (Pattern catalog, findings, failed hypotheses, research history)
```

Each store uses atomic SQLite connection context managers ensuring safe execution and avoiding Windows lock issues.
