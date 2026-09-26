# PACKAGE 3.1 — SENSIBULL OBSERVATION EXTENSION IMPLEMENTATION PLAN

## 1. Executive Summary

Package 3.1 extends the market perception layer of the **NIFTY Autonomous Trader** to include **Sensibull** as a first-class, pluggable, browser-based market observation source alongside **TradingView** and the authoritative **Numerical Market Data Provider** (Yahoo Finance / Mock).

This extension provides the future Package 4 Trading Brain with rich derivatives market sentiment data (Option Chain, Put-Call Ratio [PCR], Open Interest [OI], Implied Volatility [IV], and Max Pain) without violating any architectural invariants.

### Strict Package Boundary & Invariants
- **Perception Extension Only**: Zero trading signals, zero buy/sell directives, zero entry/exit levels, zero stop-loss or profit targets, zero position sizing, zero risk approval, zero order execution.
- **Source Independence**: Sensibull, TradingView, and Numerical data remain logically independent. Sensibull does NOT "confirm" TradingView in Package 3.1; each source reports what it observes independently.
- **Untrusted External Data**: All webpage content is treated as untrusted external text. Prompt injections inside HTML or visible text are sanitized and never executed.
- **No Anti-Bot/CAPTCHA Bypass**: If Sensibull requires authentication, the system flags `AUTHENTICATION_REQUIRED` and continues partial observation.
- **Explicit Missing Representation**: Missing data is represented as `None` / `NOT_AVAILABLE`. Never convert missing PCR or IV into `0.0`.

---

## 2. Pluggable Source Architecture

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

### Source Contract: `IMarketObservationSource`
Each source implements:
- `source_id: str`
- `source_type: ObservationSourceType` (`NUMERICAL`, `CHART_VISUAL`, `DERIVATIVES_OPTION_CHAIN`)
- `is_available() -> bool`
- `capabilities: List[str]`
- `observe(...) -> SourceObservationResult`

---

## 3. Sensibull Observation Workflow

1. **Session Verification**: Ensure browser instance is active via `BrowserProvider`.
2. **Navigation**: Navigate to Sensibull NIFTY Option Chain (`https://web.sensibull.com/option-chain?tradingsymbol=NIFTY` or configured URL) with bounded retries.
3. **Authentication Check**: Detect login buttons, modal overlays, or user sign-in prompts. If authentication is required and not present, set `status = AUTHENTICATION_REQUIRED` and exit gracefully.
4. **Content Verification**: Verify that the NIFTY option chain container or summary cards are visible. If missing or layout changed, record `status = PARSE_FAILED` or `NOT_LOADED`.
5. **Data Extraction (Bounded & Safe)**:
   - NIFTY Spot Price (candidate float)
   - Expiry Date (selected expiry string)
   - Put-Call Ratio (PCR float, or `None`)
   - Max Pain Strike (float, or `None`)
   - ATM IV (float, or `None`)
   - Call OI & Put OI totals
   - Key visible strike details (strikes around ATM)
6. **Screenshot Association**: Capture screenshot to `data/browser/screenshots/sensibull/YYYY-MM-DD/sensibull_nifty_<ts>.png` and associate path with observation ID.
7. **Sanitization**: Filter untrusted text against prompt injection patterns.
8. **Telemetry & Timestamps**: Record `observed_at`, `status`, `warnings`, `errors`, and `confidence`.

---

## 4. Multi-Source Numerical Validation

Sensibull displayed spot price is compared with the authoritative numerical candle close:
- **`MATCH`**: Discrepancy $\le 0.5\%$
- **`MINOR_DIFFERENCE`**: $0.5\% < \text{Discrepancy} \le 1.5\%$
- **`SIGNIFICANT_DIFFERENCE`**: $\text{Discrepancy} > 1.5\%$
- **`INSUFFICIENT_DATA`**: One or both sources missing numerical spot data.

Discrepancies are logged and stored in the unified observation record without overwriting either source.

---

## 5. Observation Planner

`ObservationPlanner` dynamically decides which sources to execute:
- Configurable defaults: `tradingview.enabled`, `sensibull.enabled`, `numerical.enabled`.
- Automatic execution on standard observation cycles.
- Operator instruction steering: When an active instruction contains requests like `"check sensibull"`, `"observe option chain"`, or `"sensibull pcr"`, the planner automatically schedules Sensibull observation for the cycle.

---

## 6. Implementation Steps

1. **Models**: `nifty_trader/observation/models.py` (SensibullStatus, SensibullObservation, OptionChainData, CrossCheckStatus).
2. **Sources**:
   - `nifty_trader/observation/sources/base.py` (`IMarketObservationSource`)
   - `nifty_trader/observation/sources/sensibull.py` (`SensibullObservationSource`)
   - `nifty_trader/observation/sources/tradingview.py` (`TradingViewObservationSource`)
   - `nifty_trader/observation/sources/numerical.py` (`NumericalMarketDataSource`)
3. **Cross-Checker**: `nifty_trader/observation/cross_check.py` (Multi-source cross-check engine).
4. **Planner**: `nifty_trader/observation/planner.py` (`ObservationPlanner`).
5. **Unified Observation**: Extend `nifty_trader/market_data/observation.py` and `nifty_trader/market_data/service.py` to produce multi-source unified observations.
6. **Configuration**: Update `config/settings.yaml`, `config/features.yaml`, and `config/release-manifest.yaml`.
7. **Runtime & CLI**: Expose `sensibull-test` and `--sources` parameter on `market-observe`.
8. **Test Suite**: Add full unit and integration tests across all modules.
9. **Verification**: Run complete test suite and execute live test.
10. **Documentation & Lock**: Create architecture doc, schema doc, test report, update `PROJECT_STATUS.md`.
