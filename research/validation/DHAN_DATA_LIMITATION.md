# DhanHQ API Historical Data Limitations Report

**Audit Phase:** Phase 4 — Investigation of Dhan Expired Contract Data Capability  
**Date:** 2026-09-30  
**Classification:** `DHAN INSUFFICIENT`  
**Verdict:** The strategy backtest remains **STRICTLY BLOCKED**. DhanHQ cannot supply the required historical data.

---

## 1. Executive Summary

A comprehensive investigation of official DhanHQ documentation and empirical API probing of DhanHQ endpoints was conducted to evaluate whether Dhan's **Expired Options Data** and **Historical Data** APIs can satisfy the data requirements of the frozen NIFTY Futures + Option OI strategy.

The findings establish conclusively that **DhanHQ is INSUFFICIENT** to support an authentic, lookahead-free, and mathematically valid backtest. 

Specifically:
1. **Zero Expired Futures Data:** Dhan does not archive or provide intraday historical OHLCV data for expired NIFTY Futures contracts. The `/charts/intraday` endpoint exclusively services currently active contracts (returning 0 bars for expired contracts).
2. **Synthetic Rolling Options Only:** Dhan's expired options API (`/charts/rollingoption`) does not provide discrete, expiry-identified option contracts. Instead, it serves synthetic, spot-relative rolling slices that switch underlying option strikes mid-session as the spot index moves.
3. **Missing Contract Identity & Expiry:** Responses from `/charts/rollingoption` omit the contract Security ID, trading symbol, actual expiry date, and Change in OI (`change_oi`).
4. **Spot vs. Futures Decoupling:** The strategy strictly anchors ATM strikes to historical NIFTY Futures prices (nearest 50). Dhan's rolling API is hardcoded to Spot Index price buckets and cannot accept Futures-anchored strike ladders.

---

## 2. Detailed Technical Audit of Dhan Endpoints

### 2.1 Expired Options API (`POST /charts/rollingoption`)

| Dimension | Specification | Audit Finding |
|---|---|---|
| **Endpoint** | `POST https://api.dhan.co/v2/charts/rollingoption` | Official expired options data endpoint. |
| **Authentication** | `client-id`, `access-token` headers | Verified; token requires active daily/session renewal. |
| **Required Parameters** | `exchangeSegment`, `interval`, `securityId`, `instrument`, `expiryFlag`, `expiryCode`, `strike`, `drvOptionType`, `requiredData`, `fromDate`, `toDate` | All parameters are mandatory. `securityId` must be the underlying scrip ID (`13` for NIFTY), not an option contract ID. |
| **Historical Range** | Up to 5 years (documented); max 30 days per single request | Data exists in 2022, 2024, and 2026 probes. |
| **Intervals** | `1`, `5`, `15`, `25`, `60` minutes | 5-minute interval supported. |
| **Supported Fields** | `open`, `high`, `low`, `close`, `volume`, `oi`, `strike`, `spot`, `iv`, `timestamp` | All return arrays corresponding to 5-minute candles. |
| **Missing Fields** | `expiry`, `security_id`, `trading_symbol`, `change_oi`, `underlying` | **CRITICALLY ABSENT**. Response schema: `{"data": {"ce": {...}, "pe": null}}`. |
| **Strike Mechanism** | Spot-relative rolling selector (`ATM`, `ATM+1` to `ATM+10`, `ATM-1` to `ATM-10`) | **Synthetic composite**. As spot price moves across 50-point boundaries, the resolved strike changes mid-session. |

#### Empirical Proof of Strike Shifting & False OI Deltas
In the 2024-07-10 CALL ATM probe (`option_call_atm_2024-07-10.json`):
- Across 75 five-minute bars in a single trading day, the resolved strike shifted **14 times** across 6 distinct strike prices: `24150.0`, `24200.0`, `24250.0`, `24300.0`, `24350.0`, `24400.0`.
- At bar index 8, the strike was `24400` with OI = `953,775`. At bar index 9, spot moved and the strike shifted to `24350` with OI = `106,025`.
- Computing Change in OI ($\Delta OI$) across adjacent candles produces an artificial drop of **$-847,750$ contracts**, which is completely spurious because two entirely different contracts were compared. Maximum artificial jump observed: **$1,240,000$ contracts**.

### 2.2 Historical Intraday Data API (`POST /charts/intraday`)

| Dimension | Specification | Audit Finding |
|---|---|---|
| **Endpoint** | `POST https://api.dhan.co/v2/charts/intraday` | Used for minute/5-minute candles. |
| **Documented Limitation** | *"This data available for all exchanges and segments for all active instruments."* | Official documentation explicitly restricts intraday history to **active instruments**. |
| **Behavior on Expired Contracts** | Querying active NIFTY FUTIDX security ID `68407` for 2022-01-12 | Returns HTTP 200 with **0 bars**: `{"open":[], "high":[], "low":[], "close":[], "volume":[], "timestamp":[], "open_interest":[]}`. |
| **Expired Futures Endpoint** | Trial queries to `/charts/rollingfuture`, `/charts/expiredfuture`, `/charts/historicalfutures` | Return **HTTP 404 Not Found**. Dhan has no expired futures endpoint. |

### 2.3 Instrument Master (`api-scrip-master-detailed.csv`)

| Dimension | Specification | Audit Finding |
|---|---|---|
| **Source** | `https://images.dhan.co/api-data/api-scrip-master-detailed.csv` | Downloaded and parsed (198,814 rows). |
| **Active NIFTY Futures** | Exactly 3 contracts present (near, next, far month: `2026-09-29`, `2026-10-27`, `2026-11-23`). | Contains tradable contracts only. |
| **Historical/Expired Contracts** | Expired contracts are purged daily upon expiry. | **Zero** expired contracts exist in the master. No historical instrument ID archive is provided. |

### 2.4 Option Chain API (`POST /v2/optionchain`)

| Dimension | Specification | Audit Finding |
|---|---|---|
| **Endpoint** | `POST /v2/optionchain` | Returns real-time option chain across all strikes for active expiries. |
| **Historical Snapshot Capability** | None. Documented rate limit: 1 request every 3 seconds. | Exclusively real-time; cannot provide historical timestamped snapshots. |

---

## 3. Exact Missing Fields & Structural Gaps

| Entity | Field Name | Required By Strategy | Status in Dhan | Impact on Strategy |
|---|---|---|---|---|
| **NIFTY Futures** | `security_id` (expired) | Yes (5-year contract coverage) | Missing | Cannot identify expired contracts |
| **NIFTY Futures** | 5m OHLCV / OI (expired) | Yes (underlying entry/exit instrument) | Missing (0 bars) | **Fatal blocker:** No execution price series |
| **NIFTY Options** | `expiry_date` | Yes (exact contract selection) | Missing | Cannot verify weekly vs. monthly expiry |
| **NIFTY Options** | `security_id` / Contract ID | Yes (contract uniqueness) | Missing | Cannot map to Dhan instrument master |
| **NIFTY Options** | `change_oi` | Yes (OI resistance filtering) | Missing | Cannot filter by positive OI buildup |
| **Strike Ladder** | Futures-anchored ATM | Yes (ATM = nearest 50 of Futures) | Missing | Dhan hardcodes ladder to Spot Index |

---

## 4. Why the Strategy Cannot Be Validated With Dhan Alone

The frozen strategy architecture requires a continuous, causal data pipeline:

$$\text{NIFTY Futures Price } (t) \longrightarrow \text{ATM Strike } (\text{nearest } 50) \longrightarrow \text{ATM } \pm 5 \text{ CE/PE Strikes } (E) \longrightarrow \text{OI \& } \Delta\text{OI } (t)$$

1. **Broken Root Link:** Without historical NIFTY Futures 5-minute bars, there is no traded asset to compute signals, entry prices, stops, or targets.
2. **Broken ATM Anchor:** Without Futures prices, the strategy cannot calculate the exact ATM strike (nearest 50).
3. **Broken Strike Selection:** Because Dhan's rolling options API shifts strikes dynamically based on Spot, one cannot hold a continuous series for a specific strike across a session.
4. **Spurious Delta OI:** Because rolling strikes jump across candles, taking differences of Dhan's rolling OI produces catastrophic artificial spikes of over 1,000,000 contracts, completely corrupting the 20-point OI confluence logic.
5. **No Expiry Disambiguation:** Without explicit expiry timestamps, it is impossible to distinguish between current monthly contracts, next-month contracts, or weekly expiries.

**Conclusion:** It is impossible to validate or backtest this strategy using DhanHQ APIs alone without introducing lookahead bias, synthetic instrument distortion, or fake data substitutes.
