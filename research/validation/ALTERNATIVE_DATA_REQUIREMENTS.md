# Alternative Historical Data Requirements Specification

**Document Version:** 1.0  
**Date:** 2026-09-30  
**Project:** NIFTY Autonomous Trader — Deterministic Futures & Options Strategy Validation  
**Status:** Requirements Specification for External Data Acquisition  

---

## 1. Overview & Objective

Phase 4 of the historical data audit conclusively established that broker APIs (specifically DhanHQ) cannot supply expired NIFTY Futures contracts, explicit option contract expiries, or continuous strike-level Open Interest (OI) arrays anchored to Futures.

To validate the frozen deterministic trading strategy without lookahead bias or synthetic compromises, an authoritative external historical market dataset must be acquired. This document specifies the exact minimum and complete schemas, coverage periods, granularity, and verification criteria required.

---

## 2. Required Minimum Datasets

### 2.1 NIFTY Index Futures (`FUTIDX`)

The strategy executes directly on NIFTY Index Futures. A generic Spot Index series is unacceptable.

| Field Name | Type | Precision / Format | Description | Required / Optional |
|---|---|---|---|---|
| `timestamp` | UTC ISO-8601 or Unix Epoch | Seconds / Milliseconds | Exact candle boundary timestamp. Must document bar-open vs bar-close convention. | **REQUIRED** |
| `expiry` | Date (`YYYY-MM-DD`) | Date | Exact expiry date of the specific Futures contract (near, next, or far month). | **REQUIRED** |
| `open` | Float | 2 decimal places | Open price of the 5-minute bar. | **REQUIRED** |
| `high` | Float | 2 decimal places | High price of the 5-minute bar. | **REQUIRED** |
| `low` | Float | 2 decimal places | Low price of the 5-minute bar. | **REQUIRED** |
| `close` | Float | 2 decimal places | Close price of the 5-minute bar (evaluation price). | **REQUIRED** |
| `volume` | Integer | Whole contracts or shares | Cumulative volume traded within the 5-minute bar. | **REQUIRED** |
| `open_interest` | Integer | Whole contracts / shares | Open interest at the end of the 5-minute bar. | Strongly Recommended |
| `instrument_id` | String | Unique identifier | Exchange trading symbol or token (e.g., `NIFTY24JUL24FUT`). | Strongly Recommended |

#### Futures Coverage & Rollover Requirements
- **Historical Depth:** 5 continuous years (minimum 2021-09-30 to 2026-09-30).
- **Timeframe:** 5-minute completed bars.
- **Contract Continuity:** Individual contract files or an explicit rollover mapping that identifies:
  - Current active near-month contract.
  - Rollover execution date and time (e.g., final Thursday or Friday before expiry).
  - Unadjusted price series (do NOT apply backward/forward proportional smoothing that alters historical support/resistance levels or pivot calculations).

---

### 2.2 NIFTY Index Options (`OPTIDX`)

The strategy computes dynamic Open Interest support/resistance and $\Delta OI$ across the nearest 11 strikes around the Futures ATM strike ($ATM \pm 5$ strikes at 50-point intervals).

| Field Name | Type | Precision / Format | Description | Required / Optional |
|---|---|---|---|---|
| `timestamp` | UTC ISO-8601 or Unix Epoch | Seconds / Milliseconds | Timestamp of the option snapshot / bar (must align with Futures 5-minute candle). | **REQUIRED** |
| `expiry` | Date (`YYYY-MM-DD`) | Date | Actual expiration date of the option contract. | **REQUIRED** |
| `strike` | Float | Exact strike (e.g. `24500.0`) | Fixed nominal strike price. Must remain constant across a contract's lifecycle. | **REQUIRED** |
| `option_type` | String Enum | `"CE"` or `"PE"` (or `"CALL"` / `"PUT"`) | Option right classification. | **REQUIRED** |
| `open_interest` | Integer | Whole contracts / shares | Total outstanding open interest at timestamp $t$. | **REQUIRED** |
| `open` | Float | 2 decimal places | Bar open price. | **REQUIRED** |
| `high` | Float | 2 decimal places | Bar high price. | **REQUIRED** |
| `low` | Float | 2 decimal places | Bar low price. | **REQUIRED** |
| `close` / `ltp` | Float | 2 decimal places | Bar close or Last Traded Price (LTP). | **REQUIRED** |
| `volume` | Integer | Whole contracts / shares | Traded volume during the bar. | **REQUIRED** |
| `change_oi` | Integer | Signed integer | Net change in open interest since prior trading session close or prior bar. | Strongly Recommended |
| `instrument_id` | String | Unique token / symbol | Unique exchange token (e.g. `NIFTY2471124500CE`). | Strongly Recommended |

#### Options Coverage & Strike Breadth Requirements
- **Historical Depth:** 5 continuous years matching the Futures dataset.
- **Timeframe:** 5-minute snapshots synchronized with Futures candle close.
- **Strike Coverage:** At minimum, all strikes covering $ATM \pm 10$ strikes (spanning at least $\pm 500$ points from daily range) for active weekly and monthly contracts.
- **Contract Stability:** Each option series must be discrete to an exact strike and expiry. Synthetic rolling strikes (such as spot-relative shifting series) are strictly prohibited.

---

## 3. Data Integrity & Invariance Criteria

Any candidate historical dataset must pass the following verification tests before ingestion into the backtesting engine:

1. **Exact Causal Timestamping:**
   - Every option snapshot record must bear a timestamp $T_{\text{option}} \le T_{\text{futures}}$.
   - Replay must enforce exact equality: $\text{OptionSnapshot}(T) \equiv \text{FuturesBar}(T)$.
   - Zero tolerance for forward-filling, backward-filling, or inter-session carry of stale option snapshots.
2. **Deterministic Strike Continuity:**
   - For a given contract identifier $(\text{expiry}, \text{strike}, \text{type})$, the strike must remain completely invariant throughout the session.
   - $\Delta OI$ must be computed exclusively between successive timestamps of the *same* contract identifier:
     $$\Delta OI_{t} = OI_{t}(\text{contract}_k) - OI_{t-1}(\text{contract}_k)$$
3. **No Synthetic Price Smoothing:**
   - Raw contract prices must be retained so that technical indicators (EMA, ATR, Pivots) reflect actual historical order flow and price action.
4. **Exchange Calendar Alignment:**
   - Dataset must accurately reflect NSE trading sessions (09:15 to 15:30 IST) and account for exchange holidays, special Muhurat sessions, and historical expiry weekday shifts (e.g., Thursday vs. Wednesday expiries).

---

## 4. Vendor Neutrality & Ingestion Policy

In accordance with project audit rules:
- No specific commercial vendor or data redistributor is endorsed until sample verification, checksum validation, and schema conformance have been empirically proven on raw files.
- The trading system remains frozen in its current implementation. No backtesting runs or parameter optimizations will take place until the external dataset fulfilling this specification is delivered, validated, and normalized.
