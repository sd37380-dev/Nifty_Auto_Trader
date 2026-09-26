# SENSIBULL OBSERVATION EXTENSION ARCHITECTURE (PACKAGE 3.1)

## 1. Overview & Architectural Principles

Package 3.1 introduces a pluggable, multi-source observation architecture for the **NIFTY Autonomous Trader**. It extends the system's perceptual scope beyond numerical price feeds and visual charts to include **derivatives market sentiment** via **Sensibull**.

### Non-Negotiable Invariants:
1. **Perception Only**: Strategy-agnostic observation. Zero buy/sell recommendations, zero position sizing, zero stop-loss or profit target calculation.
2. **Pluggable Source Architecture**: Neither TradingView nor Sensibull are hard-coded into each other. Each implements the uniform `IMarketObservationSource` interface.
3. **Source Independence**: The system reports what each source observes independently. No source "confirms" or overwrites another source.
4. **Security & Boundary Enforcement**:
   - Zero CAPTCHA / anti-bot bypass.
   - Zero credential theft / bypass. If authentication is required, `status = AUTHENTICATION_REQUIRED` is flagged.
   - All external webpage text is treated as untrusted data. Prompt injections are sanitized and neutralized.
5. **Deterministic Missing Representation**: Unobserved fields remain `None` / `NOT_AVAILABLE`. Never coerce missing values (e.g. PCR or IV) to `0.0`.

---

## 2. Multi-Source Perception Hierarchy

```text
                                HUMAN OPERATOR
                                      │
                                      ▼
                             Manual Instructions
                                      │
                                      ▼
                             Observation Planner
                                      │
                ┌─────────────────────┼─────────────────────┐
                │                     │                     │
                ▼                     ▼                     ▼
      TradingView Source       Sensibull Source      Numerical Data Source
        (BrowserAgent)          (BrowserAgent)         (MarketDataProvider)
                │                     │                     │
                └─────────────────────┼─────────────────────┘
                                      │
                                      ▼
                        Multi-Source Cross-Check
                                      │
                                      ▼
                          Unified MarketObservation
                                      │
                                      ▼
                         PACKAGE 4 TRADING BRAIN
```

---

## 3. Component Breakdown

### 3.1 `IMarketObservationSource` (`nifty_trader.observation.sources.base`)
Abstract contract defining:
- `source_id: str`: Unique provider key (`sensibull`, `tradingview`, `numerical`).
- `source_type: ObservationSourceType`: `NUMERICAL`, `CHART_VISUAL`, `DERIVATIVES_OPTION_CHAIN`.
- `capabilities: List[str]`: Advertised inspection abilities (`pcr`, `max_pain`, `atm_iv`, `candlesticks`).
- `is_available() -> bool`: Liveness check.
- `observe(symbol: str, **kwargs) -> SourceObservationResult`: Uniform asynchronous observation trigger.

### 3.2 `SensibullObservationSource` (`nifty_trader.observation.sources.sensibull`)
Implements the Sensibull observation workflow:
1. Verifies browser agent readiness.
2. Navigates to `https://web.sensibull.com/option-chain?tradingsymbol=NIFTY` with bounded retries.
3. Sanitizes untrusted visible text to neutralize prompt injection sequences.
4. Inspects for authentication barriers (`Login with Broker`, `Zerodha`, `Upstox`, etc.). If present without option chain data, sets `AUTHENTICATION_REQUIRED`.
5. Extracts NIFTY Spot, Put-Call Ratio (PCR), Max Pain Strike, ATM Implied Volatility (IV), and prominent visible strikes.
6. Links screenshot reference into observation record.
7. Produces structured `SensibullObservation`.

### 3.3 `TradingViewObservationSource` (`nifty_trader.observation.sources.tradingview`)
Wraps the existing `BrowserAgent.inspect_tradingview_nifty()` to expose TradingView visual observations through the uniform source contract.

### 3.4 `NumericalMarketDataSource` (`nifty_trader.observation.sources.numerical`)
Wraps `MarketDataProvider` and SQLite `MarketDataCache` to provide authoritative OHLCV candles through the uniform source contract.

### 3.5 `ObservationPlanner` (`nifty_trader.observation.planner`)
Plans which sources must be inspected during an observation cycle:
- Interrogates configuration flags (`tradingview.enabled`, `sensibull.enabled`, `numerical.enabled`).
- Analyzes active human operator steering directives (e.g. `"Check Sensibull option chain"`).
- Sanitizes trading directives (e.g. `"Buy NIFTY because PCR is bullish"` -> logs safety notice and treats purely as observation context).

### 3.6 `MultiSourceCrossChecker` (`nifty_trader.observation.cross_check`)
Compares displayed spot references from Sensibull and TradingView against authoritative numerical candle closes:
- **`MATCH`**: Discrepancy $\le 0.5\%$.
- **`MINOR_DIFFERENCE`**: $0.5\% < \text{Discrepancy} \le 1.5\%$.
- **`SIGNIFICANT_DIFFERENCE`**: $\text{Discrepancy} > 1.5\%$.
- **`INSUFFICIENT_DATA`**: One or more sources missing spot references.

---

## 4. Partial Observation & Fault Tolerance

If Sensibull encounters an error, timeout, or requires broker authentication:
1. Sensibull status is recorded as `AUTHENTICATION_REQUIRED`, `NOT_LOADED`, or `ERROR`.
2. The overall market observation cycle **does NOT crash or fail**.
3. Authoritative numerical data (1H/15M) and TradingView visual observations proceed normally.
4. Downstream reasoning layers (Package 4 Brain) receive the partial state with explicit flags indicating the absence of derivatives data.
