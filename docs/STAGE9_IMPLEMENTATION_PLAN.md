# STAGE 9 — AUTONOMOUS TRADE MONITORING & POSITION MANAGEMENT IMPLEMENTATION PLAN

## 1. Executive Summary

Stage 9 implements the **Autonomous Trade Monitoring and Position Management Layer** for the NIFTY Autonomous Trader. It extends the Sensibull paper-trade execution engine (Stage 8) into a continuous, patient, position-aware monitoring loop:

```text
OPEN POSITION (Stage 8)
       ↓
OBSERVE (Package 3 / 3.1)
       ↓
HERMES CONTEXT BUILDER (Position + Market + Original Thesis)
       ↓
BRAIN REASSESSMENT (Package 4 / Gemini)
       ↓
┌──────────────────────────────────────────────┐
│ WAIT (Package 5: Schedule next 15M wake)      │
│ CONTINUE (Position remains open & valid)     │
│ WATCH (Active observation near levels)       │
│ MODIFY (Adjust trailing stop or targets)     │
│ CLOSE (Execute exit via Stage 8 Sensibull)   │
└──────────────────────┬───────────────────────┘
                       ↓
               Continue / Act
                       ↓
         Verify Sensibull Ground Truth
                       ↓
         Reassess / POSITION CLOSED
```

---

## 2. Core Non-Negotiable Invariants

1. **Zero New Strategy Engines**: No hard-coded exit rules (`IF profit > X CLOSE`, `IF loss > X CLOSE`, `IF RSI < X CLOSE`, etc.). Decisions are made through cognitive reasoning by Hermes + AI Brain.
2. **Zero Duplicate Engines**:
   - Reuses **Stage 8** for Sensibull paper-trade execution, square-off, and state verification.
   - Reuses **Package 5** for waiting, change detection, and wake-up control.
   - Reuses **Package 4** for Trading Brain contracts and reasoning.
   - Reuses **Package 3 / 3.1** for market perception (1H + 15M).
3. **Position-Aware Context**: The Brain explicitly knows: *"There is already an open position"*, and evaluates the original thesis against current evidence.
4. **Historical Thesis Preservation**: The original entry thesis, candidate ID, and opening hypothesis are preserved and never rewritten to match subsequent market outcomes.
5. **Sensibull Ground Truth Verification**: Every action is visually and DOM-verified against Sensibull's ground truth table. If unexpected position closures or new positions are found, Hermes enters `RECONCILIATION_REQUIRED`.
6. **Complete Audit Trail**: All monitoring cycles, observations, Brain reassessments, and decisions are persisted in SQLite (`data/monitoring/position_monitoring.db`).

---

## 3. Subsystem Architecture

```text
nifty_trader/monitoring/
├── __init__.py                  # Package exports
├── contracts.py                 # MonitoringState, PositionMonitoringRecord, PositionEvent
├── store.py                     # SQLite persistence (data/monitoring/position_monitoring.db)
├── context_builder.py           # Assembles OpenPositionContext + Thesis + Market Observation
└── orchestrator.py              # AutonomousPositionMonitor (manages monitoring loop)
```

---

## 4. Contract Extensions (`nifty_trader/brain/contracts.py`)

- **`OpenPositionContext`**:
  - `position_id`, `symbol`, `direction`, `strike`, `option_type`, `lots`, `quantity`, `entry_price`, `current_price`, `unrealized_pnl`, `pnl_percentage`, `holding_duration_minutes`, `opening_candidate_thesis`, `opening_hypothesis`, `opening_timestamp`.
- **`PositionManagementAction`**:
  - Enum: `CONTINUE`, `WAIT`, `WATCH`, `MODIFY`, `CLOSE`.
- **`BrainInput`**:
  - `task: Literal["MARKET_ANALYSIS", "SETUP_CONFIRMATION", "POSITION_REASSESSMENT"]`
  - `open_position_context: Optional[OpenPositionContext]`
- **`BrainOutput`**:
  - `position_action: Optional[PositionManagementAction]`

---

## 5. Verification & Test Suite

1. **Open Position Detection**: Correctly identifies open paper positions and preserves entry thesis.
2. **Position-Aware Brain Context**: Asserts BrainInput contains full position telemetry and historical thesis.
3. **Change Detection & Noise Rejection**: Suppresses redundant Brain calls when market and P&L have not meaningfully moved.
4. **Reassessment & Action Dispatching**:
   - `CONTINUE` keeps position open.
   - `WAIT` schedules wake with Package 5 wait policy.
   - `CLOSE` triggers Stage 8 square-off and verifies closed state.
5. **Reconciliation & Anomaly Handling**: Detects unexpected external closures or untracked positions.
6. **Failure & Interruption Handling**: Gracefully handles browser timeouts, unauthenticated sessions, and model failures without corrupting state.
