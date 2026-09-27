# PACKAGE 5: AUTONOMOUS OBSERVATION & WAITING ENGINE — TEST REPORT

## 1. Test Suite Summary

- **Total Test Cases**: 143
- **Passing**: 143 (100%)
- **Failing**: 0
- **Execution Engine**: `pytest-9.1.1` on Python 3.13.11 Windows

### Test Breakdown by Module:

1. `tests/autonomous/test_state_machine.py` (7 tests):
   - Initial state validation (`IDLE`).
   - Standard autonomous cycle transitions (`IDLE -> STARTING -> OBSERVING -> ANALYZING -> WAITING -> OBSERVING`).
   - `CANDIDATE_READY` terminal transition halts autonomous loop.
   - `NO_TRADE` distinction (does not permanently kill session, transitions to `WAITING`).
   - Prohibited state transitions raise strict `ValueError`.
   - Self-transitions allowed for continuous status updates.
   - State transition listener notification callbacks.

2. `tests/autonomous/test_wait_policy_and_wake.py` (8 tests):
   - `WAIT` state with next 15M candle boundary calculation (UTC and IST).
   - `WATCH` state produces `STRUCTURAL_CHANGE` / `NEXT_CANDLE` wait decision.
   - `NO_TRADE` state wait decision without permanent session termination.
   - `CANDIDATE` state sets `should_wait = False` and halts.
   - `BrainFailure` produces bounded exponential backoff (5s, 10s, 20s...).
   - `WakeConditionEvaluator`: Time-based wake evaluation.
   - `WakeConditionEvaluator`: Price movement wake evaluation (0.10% threshold).
   - `WakeConditionEvaluator`: Manual instruction wake evaluation.

3. `tests/autonomous/test_observation_planner_and_dedup.py` (5 tests):
   - Deterministic SHA-256 request fingerprinting (case and ordering invariant).
   - Deduplication & source cooldown enforcement (60s Sensibull window).
   - Expired observation request filtering (`expires_at < current_time`).
   - Priority queue sorting (`CRITICAL` > `HIGH` > `NORMAL` > `LOW`).
   - Source aggregation for upcoming cycle (`determine_sources_for_cycle`).

4. `tests/autonomous/test_change_detector_and_freshness.py` (6 tests):
   - Initial observation establishing baseline.
   - Redundant observation suppression when market unchanged.
   - Meaningful change triggered by 15M candle completion.
   - Meaningful change triggered by price movement >= 0.10%.
   - Meaningful change triggered by Sensibull PCR shift >= 0.05.
   - Source freshness tiering (`FRESH`, `AGING`, `STALE`, `EXPIRED`, `FAILED`).

5. `tests/autonomous/test_session_controller.py` (4 tests):
   - Open market session (Friday 10:30 IST) permits active cycles.
   - Pre-market session (09:05 IST) triggers `SESSION_PAUSED` until 09:15 IST.
   - Post-market session (15:35 IST) triggers `SESSION_ENDED`.
   - Weekend / Holiday session triggers `SESSION_ENDED`.

6. `tests/autonomous/test_autonomous_engine.py` (5 tests):
   - Single cycle execution with mocked runtime and FakeClock.
   - Candidate trade thesis generation immediately transitions to `CANDIDATE_READY` and halts.
   - User `STOP` command has highest priority and halts loop immediately.
   - Pause and resume lifecycle transitions.
   - Model reasoning failure handling with safe retry backoff (zero fabricated output).

7. **Prior System Regression Tests** (108 tests):
   - 100% passing across ModelRouter, browser automation, session clock, manual instructions, market cache, Sensibull extraction, and Trading Brain contracts.

---

## 2. Live CLI Verification

### 1. Engine Operational Status
```bash
python -m nifty_trader.cli autonomous status
```
**Output:**
```text
Package 5 Autonomous Observation Engine — Operational Status
+------------------------------------+
| Parameter                | Value   |
|--------------------------+---------|
| Engine State             | IDLE    |
| Running Active           | False   |
| Market Session           | CLOSED  |
| Session ID               | None    |
| Current Brain State      | None    |
| Wait Reason              | None    |
| Next Scheduled Wake      | None    |
| Cycles Completed         | 0 / 100 |
| Model Calls Used         | 0 / 50  |
| Active Observation Plans | 0       |
| Consecutive Failures     | 0       |
+------------------------------------+
```

### 2. Single Cycle Execution (Market Session Aware)
```bash
python -m nifty_trader.cli autonomous start --once
```
**Result:**
- Evaluated session (Sunday = CLOSED).
- Concluded cycle with `SESSION_ENDED` cleanly.
- Preserved 0 model calls (zero redundant LLM queries outside exchange hours).

### 3. Historical Cycles Audit Trail
```bash
python -m nifty_trader.cli autonomous cycles
```
**Output:**
- Verified SQLite persistence in `data/autonomous/autonomous_engine.db`.
- Displayed cycle index, states, wait reason, and observation counts.
