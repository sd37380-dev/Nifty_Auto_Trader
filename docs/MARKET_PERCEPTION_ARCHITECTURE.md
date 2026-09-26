# Market Perception Architecture

## 1. Architectural Philosophy

Human discretionary traders do not stare at raw ticks in isolation. They observe markets hierarchically:
1. **Macro Regime (1H):** What is the overarching structural environment? Are we in an expansion, range compression, or trending channel?
2. **Tactical Behavior (15M):** Where is price relative to recent value? Are pullbacks orderly? Are rejection wicks forming at key inflection levels?
3. **Visual Confirmation:** What does the TradingView chart look like? Is the numerical data aligned with what the screen shows?
4. **Operator Guidance:** What specific mandates, risk warnings, or key levels has the human trader highlighted?

Market Perception in Package 3 formalizes this multi-sensory process into a deterministic perception engine that feeds the cognitive reasoning model without allowing premature trade execution.

```text
                  ┌────────────────────────────────────────────────┐
                  │            MarketObservationService            │
                  └───────┬────────────────────────┬───────────────┘
                          │                        │
         ┌────────────────┴──────┐          ┌──────┴───────────────┐
         │  Numerical Feeds      │          │  Visual Perception   │
         │  (YahooFinance / Mock)│          │  (Chrome CDP / TV)   │
         └────────┬──────────────┘          └──────┬───────────────┘
                  │                                │
                  ▼                                ▼
         ┌────────────────┐                 ┌──────────────┐
         │ 1H/15M SQLite  │                 │ Screenshot & │
         │ Local Cache    │                 │ DOM Parser   │
         └────────┬───────┘                 └──────┬───────┘
                  │                                │
                  └───────────────┬────────────────┘
                                  ▼
                     ┌────────────────────────┐
                     │   MarketCrossChecker   │
                     │  (Price Tolerance <0.5%)│
                     └────────────┬───────────┘
                                  │
                                  ▼
                     ┌────────────────────────┐
                     │   InstructionManager   │
                     │ (Operator Mandates)    │
                     └────────────┬───────────┘
                                  │
                                  ▼
                     ┌────────────────────────┐
                     │   MarketObservation    │
                     │  (Perceptual Bundle)   │
                     └────────────┬───────────┘
                                  │
                                  ▼
                     ┌────────────────────────┐
                     │  Gemini Brain Router   │
                     │(MarketPerceptionOutput)│
                     └────────────────────────┘
```

---

## 2. Ingestion & Quality Control

### A. Strict Candle Model Invariants
All ingested data must satisfy mathematical candle integrity:
* $Low \le Open \le High$
* $Low \le Close \le High$
* $Low > 0$, $High > 0$, $Open > 0$, $Close > 0$
* Timestamp is timezone-aware UTC internally, with automatic Asia/Kolkata (`IST`) projection.

### B. Completed vs. Forming Candles
* `is_closed = True`: Candle interval is finished and static. Cached permanently in SQLite.
* `is_closed = False`: Live forming candle. Overwritten on delta synchronization; never used for finalized regime classification.

### C. Data Quality Tiers
* `VALID`: Both 1H and 15M candles present, fresh (< 45 min during market hours), cross-check aligned.
* `PARTIAL`: One timeframe populated or minor gaps detected.
* `STALE`: Market is `OPEN` but latest candle timestamp is lagging.
* `UNAVAILABLE`: Feed outage or zero cached data.

---

## 3. Cognitive Observation Synthesis

When observations are submitted to the cognitive reasoning layer (`Gemini 2.5/3.5`), the system instruction enforces institutional discipline:
1. **Descriptive Only:** Describe regime, structure, levels, and anomalies.
2. **Prohibited Outputs:** NEVER generate BUY, SELL, target, stop loss, or execution commands.
3. **Pydantic Validation:** Model outputs conform strictly to `MarketPerceptionOutput`.
