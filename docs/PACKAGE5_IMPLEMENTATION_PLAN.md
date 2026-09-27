# PACKAGE 5 — AUTONOMOUS OBSERVATION & WAITING ENGINE IMPLEMENTATION PLAN

## 1. Executive Summary

Package 5 introduces the **autonomous temporal-control and observation scheduling layer** of the NIFTY Autonomous Trader. It connects the Market Perception Engine (Package 3 / 3.1) and the Trading Brain (Package 4) into a bounded, patient, event-driven autonomous loop:

```text
Package 3 / 3.1 (Perception)
       ↓
Package 4 (Trading Brain)
       ↓
Package 5 (Autonomous Wait & Schedule)
       ↓
Package 3 / 3.1 (New Observation)
       ↓
Package 4 (Re-evaluation)
```

Package 5 answers the core question:
> **"When should I look again, what information should be refreshed, how long should I wait, and when should the current reasoning cycle terminate?"**

### Strict Invariants & Non-Negotiable Boundaries:
1. **WAIT is an Action, Not an Error**: The agent intentionally does nothing when confirmation is incomplete.
2. **Zero Trade Signals & Zero Execution**: Package 5 controls observation timing only. It never issues buy/sell signals, position sizing, stop loss, or broker orders.
3. **Candidate Stops the Reasoning Loop**: When Package 4 produces `CANDIDATE`, Package 5 immediately transitions to `CANDIDATE_READY`, halts the autonomous reasoning cycle, and hands the candidate off downstream.
4. **Authoritative Contracts Preserved**: Consumes `UnifiedMarketObservation`, `BrainInput`, `BrainOutput`, `BrainResult`, `BrainState`, `ObservationRequest`, and `ReasoningState` without duplication.
5. **No Direct LLM Calls**: Package 5 calls Package 4 Trading Brain (`analyze` / `reason`). Package 4 remains responsible for ModelRouter and prompt synthesis.
6. **User STOP Has Highest Priority**: An operator STOP command immediately cancels waiting, prevents new cycles, and sets state to `STOPPED`.
7. **Patience & Noise Rejection**: Package 5 ignores minor fluctuations and enforces minimum relative price change (0.10%) and candle boundaries to avoid runaway model queries.
8. **No Self-Modification & No Hidden CoT**: All state transitions, cycles, wait decisions, and observation plans are persisted in SQLite audit records.

---

## 2. Autonomous Loop Pipeline

```text
┌──────────────────────┐
│  START CYCLE         │
└──────────┬───────────┘
           ↓
┌──────────────────────┐
│ CHECK SESSION        │──► (PRE_MARKET -> SESSION_PAUSED until 09:15 IST)
└──────────┬───────────┘──► (POST_MARKET / CLOSED -> SESSION_ENDED)
           ↓ (OPEN)
┌──────────────────────┐
│ PLAN SOURCES         │──► Deduplicate, cooldown, priority sort
└──────────┬───────────┘
           ↓
┌──────────────────────┐
│ PACKAGE 3 / 3.1      │──► UnifiedMarketObservation
│ OBSERVATION          │
└──────────┬───────────┘
           ↓
┌──────────────────────┐
│ MEANINGFUL CHANGE?   │──► NO (and prior brain output exists) ──► CONTINUE WAITING (Skip LLM call)
└──────────┬───────────┘
           ↓ YES
┌──────────────────────┐
│ PACKAGE 4 BRAIN      │──► BrainResult (via ModelRouter)
└──────────┬───────────┘
           ↓
┌──────────────────────┐
│ EVALUATE BRAIN STATE │
└──────────┬───────────┘
      ┌────┴─────────────────────────────┐
      ▼                  ▼               ▼
    WAIT               WATCH         CANDIDATE
      │                  │               │
      └─────────┬────────┘               ▼
                ↓                 CANDIDATE_READY
           WaitPolicy                    │
                ↓                        ▼
         Schedule Wait            HALT AUTONOMOUS LOOP
                ↓                 (Handoff to Strategy)
            Wake Event
                ↓
           Observe Again
```

---

## 3. Package Structure (`nifty_trader/autonomous/`)

```text
nifty_trader/autonomous/
├── __init__.py               # Exports public engine and contracts
├── contracts.py              # AutonomousState, WaitReason, WakeCondition, WaitDecision, ScheduledObservationPlan
├── state_machine.py          # State transition graph enforcement and audit logging
├── wait_policy.py            # Translates BrainOutput/failures into structured WaitDecisions
├── wake_conditions.py        # Factory & evaluator for time, candle, price, instruction wake conditions
├── deduplication.py          # Request fingerprinting and source cooldown enforcement
├── freshness.py              # Source freshness tiering (FRESH, AGING, STALE, EXPIRED, FAILED)
├── observation_planner.py    # Autonomous observation request planning and priority queues
├── change_detector.py        # Meaningful market change detector (candles, price >= 0.1%, PCR shift)
├── retry.py                  # Bounded exponential backoff with jitter
├── session.py                # Integrates Package 3 MarketSessionManager for exchange hours
├── scheduler.py              # Event-driven scheduler with IClock / FakeClock / RealClock
├── persistence.py            # SQLite storage (data/autonomous/autonomous_engine.db)
└── engine.py                 # AutonomousObservationEngine coordinator
```

---

## 4. Key Contracts & Enums

- **AutonomousState**: `IDLE`, `STARTING`, `OBSERVING`, `ANALYZING`, `WAITING`, `WATCHING`, `REOBSERVE_REQUESTED`, `CANDIDATE_READY`, `NO_TRADE`, `SESSION_PAUSED`, `SESSION_ENDED`, `ERROR`, `STOPPED`.
- **WaitReason**: `NEXT_CANDLE`, `PRICE_CHANGE`, `STRUCTURAL_CHANGE`, `SOURCE_REFRESH`, `OBSERVATION_REQUEST`, `TIME_DELAY`, `SESSION_EVENT`, `MANUAL_INSTRUCTION`, `RETRY_BACKOFF`, `MARKET_OPEN`, `MARKET_RESUME`, `BRAIN_UNAVAILABLE`, `OBSERVATION_FAILED`, `UNKNOWN`.
- **WakeConditionType**: `TIME`, `CANDLE_COMPLETION`, `PRICE_CHANGE`, `STRUCTURE_CHANGE`, `SOURCE_REFRESH`, `OBSERVATION_REQUEST`, `MANUAL_INSTRUCTION`, `SESSION_EVENT`, `ERROR_RECOVERY`, `USER_COMMAND`.
- **ObservationPriority**: `CRITICAL`, `HIGH`, `NORMAL`, `LOW`.
- **SourceFreshnessStatus**: `FRESH`, `AGING`, `STALE`, `EXPIRED`, `FAILED`.

---

## 5. CLI Operational Interface

```bash
# Start autonomous observation engine (continuous loop)
python -m nifty_trader.cli autonomous start

# Execute a single bounded observation cycle and inspect result
python -m nifty_trader.cli autonomous start --once

# Inspect engine state, current brain state, wait reason, and next wake time
python -m nifty_trader.cli autonomous status

# Interrupt waiting and force an immediate observation cycle
python -m nifty_trader.cli autonomous observe-now

# Pause and resume autonomous loop
python -m nifty_trader.cli autonomous pause
python -m nifty_trader.cli autonomous resume

# Emergency stop (highest runtime priority)
python -m nifty_trader.cli autonomous stop

# View historical reasoning cycles from SQLite audit trail
python -m nifty_trader.cli autonomous cycles --limit 10
```
