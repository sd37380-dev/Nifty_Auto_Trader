# STAGE 10 — PERFORMANCE ANALYSIS & EXPERIENCE MEMORY
## Implementation Plan & Engineering Specification

---

# 1. Purpose

Implement **Stage 10: Performance Analysis & Experience Memory** for the NIFTY Autonomous Trader.

Following Stage 8 (Sensibull Paper Trading) and Stage 9 (Autonomous Trade Monitoring), Stage 10 provides post-trade performance analysis and persistent, structured experience memory.

The core principle is:
```text
ANALYZE → EXPLAIN → RECORD → REMEMBER
```
It is **NOT**:
```text
ANALYZE → MODIFY STRATEGY AUTOMATICALLY
```

Controlled behavioral and strategy self-improvement is strictly deferred to Stage 11. Stage 10 focuses on accumulating truthful, evidence-backed experience records.

---

# 2. Strict Architectural Invariants

1. **Decoupled Evaluation**:
   - Never equate `PROFIT = GOOD REASONING` or `LOSS = BAD REASONING`.
   - Separately analyze:
     - **Decision Quality** (Evidence freshness, source agreement, hypothesis clarity, structural alignment).
     - **Execution Quality** (Slippage, order confirmation, visual validation, environment safety, reconciliation).
     - **Market Outcome** (Verified numerical P&L, % return, duration, exit reason).
2. **Epistemic Traceability**:
   - Distinguish:
     - `OBSERVED` (Verifiable perceptual facts from TradingView, Sensibull, or numerical candles).
     - `INFERRED` (Analytical assessments by AI Brain).
     - `HYPOTHESIS` (Prospective market expectations).
     - `UNKNOWN` (Missing or unverifiable information).
3. **No Automatic Strategy Rules**:
   - Experience memory contains descriptive lessons, never imperative trading rules (`IF X THEN NEVER TRADE` is strictly prohibited).
4. **Historical Record Immutability**:
   - The original entry thesis, candidate, and hypotheses are preserved as recorded at trade inception without post-hoc rewriting.
5. **Completed Trade Gating**:
   - Only trades with status `CLOSED` are analyzed for final conclusions. Incomplete or active trades are marked `PARTIAL_ANALYSIS`.
6. **No Secret or Credential Leakage**:
   - Passwords, cookies, OTPs, or API secrets never enter experience memory.
7. **Thread-Safe Persistence**:
   - Stored in SQLite (`data/experience/experience.db`).

---

# 3. Component Architecture

```text
nifty_trader/experience/
├── __init__.py               # Public package exports
├── contracts.py              # ExperienceRecord, TimelineEvent, Lesson, PerformanceSummary
├── timeline.py               # Chronological timeline reconstruction from multi-source events
├── reasoning_analysis.py     # Independent analysis of cognitive decision quality
├── execution_analysis.py     # Independent analysis of platform execution & slippage
├── outcome_analysis.py       # Verified P&L and duration analysis
├── lesson_extractor.py       # Evidence-backed lesson generation
├── validation.py             # Memory validation pipeline & anti-rule guard
├── persistence.py            # SQLite store (data/experience/experience.db)
├── retrieval.py              # Semantic & tag-based relevance query for future Brain context
├── metrics.py                # Descriptive trading and operational performance metrics
└── service.py                # Unified PerformanceAnalysisService orchestrating pipeline
```

---

# 4. Lifecycle & Pipeline

```text
COMPLETED PAPER TRADE
          ↓
[Evidence Collector]
  - PaperTradeOrder (Stage 8)
  - PaperPosition (Stage 8)
  - PositionMonitoringRecord (Stage 9)
  - UnifiedMarketObservation (Stage 3/3.1)
  - BrainResult (Stage 4)
          ↓
[Timeline Builder]
  - Chronological reconstruction (Order -> Fills -> Monitoring -> Candle Closures -> Reassessment -> Square-off)
          ↓
[Multi-Dimensional Analyzer]
  ├── ReasoningAnalyzer (Thesis evaluation, source conflict, regime evolution)
  ├── ExecutionAnalyzer (Slippage, toast verification, reconciliation checks)
  └── OutcomeAnalyzer (Realized P&L, holding duration, exit reason)
          ↓
[Lesson Extractor]
  - Generates candidate lessons citing explicit evidence IDs
          ↓
[Experience Validator]
  - Validates evidence linkage, rejects unsupported assertions, enforces non-rule constraints
          ↓
[Experience Store]
  - Persists to data/experience/experience.db
          ↓
[Context Memory Bridge]
  - Surfaces top relevant experiences to Hermes / Brain as non-deterministic historical context
```

---

# 5. CLI Commands

1. `nifty-trader experience-analyze <trade_id> [--force]`:
   Runs the complete analysis pipeline on a completed trade.
2. `nifty-trader experience-show <experience_id|trade_id>`:
   Displays detailed breakdown (Timeline, Reasoning, Execution, Outcome, Lessons).
3. `nifty-trader experience-search [--tags <tags>] [--limit <n>]`:
   Searches persisted experience memory by tag or context.
4. `nifty-trader performance-summary`:
   Displays comprehensive descriptive trading and operational performance statistics.
5. `nifty-trader performance-trades`:
   Lists analyzed trades and their multi-dimensional outcomes.

---

# 6. Testing Strategy

1. **Contracts & Validation**:
   - Verify invariant rules: no imperative rules allowed in lessons, evidence references required.
2. **Timeline Reconstruction**:
   - Ensure strictly ascending chronological timestamps without invented events.
3. **Decoupled Quality Analysis**:
   - Test profitable trade with poor reasoning.
   - Test losing trade with valid reasoning.
   - Test execution failure handling.
4. **Data Quality & Gaps**:
   - Complete vs. partial trade handling.
   - Unverified P&L handling (`UNKNOWN`).
5. **Persistence & Retrieval**:
   - CRUD in SQLite `experience.db`.
   - Tag and context filtering (`find_relevant_experiences`).
   - Non-rule contextual formatting for Brain.
6. **Descriptive Metrics**:
   - Verified P&L math, drawdown, trade duration, operational reasoning metrics.
7. **Runtime & CLI Integration**:
   - Full integration into `NiftyTraderRuntime` and CLI commands.
