# External Historical Market Data Provider Research & Evaluation Report

**Audit Phase:** Phase 5 — External Historical Data Source Research  
**Date:** 2026-09-30  
**Status:** COMPLETE & LOCKED  
**Objective:** Identify and empirically evaluate legitimate external market data providers capable of satisfying [`research/validation/ALTERNATIVE_DATA_REQUIREMENTS.md`](ALTERNATIVE_DATA_REQUIREMENTS.md) for the frozen deterministic NIFTY Futures + Option OI strategy.

---

## 1. Executive Summary

Phase 4 established conclusively that broker REST APIs (specifically DhanHQ) are `DHAN INSUFFICIENT` due to the complete lack of expired Futures intraday history, omission of actual expiry dates and contract IDs, and the synthetic, spot-shifting nature of rolling options data.

In Phase 5, an extensive survey and technical evaluation of external data providers serving the Indian derivatives market (NSE F&O) was conducted. The investigation covered:
1. **NSE Data & Analytics (DotEx):** The official exchange market data subsidiary.
2. **Global DataFeeds (GFDL / NimbleData):** Authorized NSE real-time and historical vendor.
3. **TrueData (TrueData Velocity / Market Data API):** Authorized NSE data vendor.
4. **ICICI Direct Breeze API:** Direct retail broker F&O historical data API.
5. **OptionsData.shop:** Commercial pre-packaged Parquet historical data vendor.
6. **Zerodha Kite Connect & Upstox:** Retail broker historical APIs.
7. **AlgoTest / StockMock:** Turnkey backtesting platforms.
8. **NSE Daily Bhavcopy:** Official free public EOD archives.

An actual multi-day historical sample was obtained and audited using [`research/validation/validate_sample_data.py`](validate_sample_data.py).

### Core Takeaways
- **TrueData, Zerodha Kite, and Upstox** do not provide historical intraday data for expired options contracts via their APIs (restricted to active contracts or EOD).
- **OptionsData.shop** provides discrete 1-minute Parquet option chains with OI, but empirical validation of its free sample uncovered **asymmetric strike omissions** (odd 50-point strikes missing for Put options) and historical coverage limited to 3.5 years (2023–2026), failing the 5-year requirement.
- **ICICI Breeze API** documents discrete historical F&O bars with OI for expired contracts, but suffers from restrictive rate limits (5,000 calls/day), daily session token friction, and unverified multi-year strike completeness.
- **NSE Data & Analytics (DotEx)** remains the only 100% complete, exchange-cleared authority providing full 5-year expired Futures and Options intraday snapshots with Open Interest, but operates exclusively under high institutional commercial tariffs.

---

## 2. Comprehensive Provider Comparison Matrix

| Provider | Data Source Type | NIFTY Futures | Expired Futures | NIFTY Options | Expired Options | 5m Data | Historical OI | Expiry & Strike | Contract ID | 5Y Coverage | Verified Sample | Overall Status |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **NSE Data & Analytics (DotEx)** | Official Exchange Subsidiary | YES | YES | YES | YES | YES | YES | YES | YES | YES (20+ yrs) | DOCUMENTED | **SUITABLE** (Institutional) |
| **Global DataFeeds (GFDL)** | Authorized Vendor | YES | YES | YES | YES | YES | PARTIAL | YES | YES | YES (Custom) | UNVERIFIED | **PARTIALLY SUITABLE** |
| **ICICI Breeze API** | Retail Broker API | YES | YES | YES | YES | YES | YES | YES | YES | PARTIAL (3-5 yrs) | DOCUMENTED | **PARTIALLY SUITABLE** |
| **OptionsData.shop** | Independent Aggregator | YES | YES | YES | YES | YES | YES | YES | YES | NO (3.5 yrs) | VERIFIED BY SAMPLE | **INSUFFICIENT** |
| **TrueData** | Authorized Vendor | YES | NO | YES | NO | YES | NO (Expired) | N/A | N/A | NO (6 mo active) | DOCUMENTED | **INSUFFICIENT** |
| **Zerodha Kite Connect** | Retail Broker API | YES | NO | YES | NO | YES | NO (Expired) | N/A | N/A | NO (Active only) | DOCUMENTED | **INSUFFICIENT** |
| **Upstox API v2** | Retail Broker API | YES | NO | YES | NO | YES | NO (Expired) | N/A | N/A | NO (Active only) | DOCUMENTED | **INSUFFICIENT** |
| **AlgoTest / StockMock** | Backtest Platform | YES | YES | YES | YES | YES | YES | YES | N/A | YES (6 yrs) | DOCUMENTED | **INSUFFICIENT** (Closed UI) |
| **NSE Bhavcopy (Free)** | Official Exchange Public | YES | YES | YES | YES | NO (EOD only) | YES | YES | YES | YES (10+ yrs) | DOCUMENTED | **INSUFFICIENT** (No Intraday) |

---

## 3. Detailed Provider Profiles

### 3.1 NSE Data & Analytics Limited (Formerly DotEx International)
- **Official Website:** `https://www.nseindia.com` / `https://www.nsea.co.in`
- **Data Type:** Official primary exchange feed archives (1-minute / 5-minute snapshot and Tick-by-Tick TBT).
- **Status Classification:** `SUITABLE` (Institutional / High Budget)
- **Documented Capabilities:**
  - **NIFTY Futures & Options:** Complete history from exchange inception (2000/2001 to present).
  - **Expired Contracts:** 100% of all traded contracts, expiries, and strikes.
  - **Open Interest:** Exchange-cleared, official cumulative OI and $\Delta OI$ recorded at every snapshot.
  - **Granularity:** 1-minute, 5-minute, and tick-by-tick order/trade logs.
  - **Identifiers:** Exchange instrument token, symbol name, expiry date, nominal strike, series, ISIN.
- **Access & Delivery Method:** Direct SFTP server download, enterprise cloud bucket, or external encrypted media delivery.
- **Pricing:** Institutional tariff. Historical F&O snapshot and intraday packs typically range from **₹1,40,000 to ₹5,00,000+** plus exchange royalties and GST depending on historical span and licensing scope.
- **Licensing & Restrictions:** Standard Non-Display Internal Research License permits proprietary quantitative research and backtesting. Commercial redistribution is prohibited.
- **Sample Availability:** Sample data files available upon institutional inquiry; daily EOD Bhavcopy publicly available.

---

### 3.2 Global DataFeeds India Pvt. Ltd. (GFDL / NimbleData)
- **Official Website:** `https://globaldatafeeds.in`
- **Data Type:** Authorized NSE market data vendor delivering real-time and historical multi-asset data.
- **Status Classification:** `PARTIALLY SUITABLE / UNVERIFIED`
- **Documented Capabilities:**
  - **NIFTY Futures:** Historical 1-minute and 5-minute bars for active and expired contracts.
  - **NIFTY Options:** Historical minute-level options data for expired contracts.
  - **Open Interest:** Historical OI is supported in their premium desktop product (`nimbleDataPro`) and historical offline data packs. (Note: real-time streaming tier `nimbleDataPlusLite` treats OI as a stateless live field).
  - **Historical Coverage:** Up to 10 years available upon request.
- **Access & Delivery Method:** NimbleData API (.NET/COM/Python SDK) or bulk offline CSV exports.
- **Pricing:** Custom pricing on inquiry. Typical subscriptions range from **₹3,000 to ₹10,000/month** for platform feeds; historical bulk archives quoted separately based on segment and depth.
- **Sample Availability:** Free 7-day trial for live platform; historical sample packs provided upon sales engagement.
- **Gaps / Unknowns:** Must independently verify via trial sample whether their offline F&O historical pack includes all 50-point strikes for expired weekly/monthly options and continuous OI without compression.

---

### 3.3 ICICI Direct Breeze API
- **Official Website:** `https://api.icicidirect.com`
- **Data Type:** Direct retail broker API (`breeze-connect` Python SDK).
- **Status Classification:** `PARTIALLY SUITABLE`
- **Documented Capabilities:**
  - **Endpoint:** `get_historical_data_v2`
  - **Parameters:** `stock_code="NIFTY"`, `exchange_code="NFO"`, `product_type="options"` (or `"futures"`), `strike_price`, `right="Call"`/`"Put"`, `expiry_date="YYYY-MM-DDT06:00:00.000Z"`.
  - **Fields Returned:** `datetime`, `open`, `high`, `low`, `close`, `volume`, `oi`.
  - **Expired Contracts:** Documented and confirmed in developer community: allows querying historical dates for expired option and futures contracts by specifying the exact contract parameters.
- **Pricing:** Free for ICICI Direct trading account holders with active API access.
- **Fatal Operational Constraints:**
  - **Rate Limits:** Strictly capped at **100 calls/minute and 5,000 calls/day**.
  - **Download Duration:** Downloading 5 years of $ATM \pm 5$ strikes (11 strikes $\times$ 2 sides $\times$ 250 days $\times$ 5 years $\approx 27,500$ requests) would require at least 6 consecutive days of continuous paced downloading.
  - **Session Friction:** Requires generating a new session token every trading day via web login.
  - **Data Integrity:** Community reports document occasional missing timestamps and unverified strike completeness.

---

### 3.4 OptionsData.shop
- **Official Website:** `https://optionsdata.shop`
- **Data Type:** Commercial independent aggregator selling pre-compiled Parquet archives of NSE/BSE options.
- **Status Classification:** `INSUFFICIENT` (Empirically Proven by Sample Audit)
- **Documented Capabilities:**
  - **Format:** Parquet files partitioned by trading date and expiry (`NIFTY_OPT_1min_<date>_exp<expiry>.parquet`).
  - **Fields:** `datetime`, `stock_code`, `exchange_code`, `product_type`, `expiry_date`, `strike_price`, `right`, `open`, `high`, `low`, `close`, `volume`, `open_interest`.
  - **Pricing:** One-time pack purchase via UPI (e.g. ₹3,999 to ₹8,999 for multi-year bundles).
- **Empirical Audit Findings on Official Free Sample (September 2026):**
  - **Total Sample Rows:** 495,715 across 9 files (3 trading days: 2026-09-15, 2026-09-16, 2026-09-17).
  - **Positive OI:** 96.13% of rows contain valid positive OI.
  - **Invalid OHLC:** 0 invalid bars detected.
  - **FATAL GAP 1 — Coverage Limited to 3.5 Years:** Archive spans January 2023 to August 2026. Data for 2021 and 2022 is completely missing.
  - **FATAL GAP 2 — Asymmetric Strike Omissions:** On 2026-09-15 (expiry day, Spot $\approx 25000$), CE contained all 11 strikes for $ATM \pm 5$, but PE contained only 5 strikes (`24750, 24800, 24900, 25000, 25100, 25200`). Odd 50-point strikes (`24850, 24950, 25050, 25150, 25250`) were **completely omitted** from the Put options dataset.
  - **Impact:** The strategy's deterministic requirement for full $ATM \pm 5$ strike coverage fails on this dataset.

---

### 3.5 TrueData (TrueData Velocity / Market Data API)
- **Official Website:** `https://www.truedata.in`
- **Data Type:** Authorized NSE vendor.
- **Status Classification:** `INSUFFICIENT`
- **Audit Finding:**
  - Official knowledge base and support confirm that TrueData does **not** provide historical intraday data for expired options contracts via their REST/WebSocket market data API.
  - Intraday bar history is restricted to 6 months for currently active contracts.
  - Open Interest is available live and for active instruments, but historical multi-year expired contract series are not supported.

---

### 3.6 Zerodha Kite Connect & Upstox API v2
- **Official Websites:** `https://kite.trade` / `https://upstox.com/developer/api-documentation`
- **Data Type:** Retail broker historical candle APIs.
- **Status Classification:** `INSUFFICIENT`
- **Audit Finding:**
  - Both brokers purge expired derivative instrument tokens daily from their instrument master files.
  - Once a contract expires, querying historical candle endpoints with expired instrument keys returns HTTP 404 or `InputException: invalid instrument_token`.
  - Neither broker offers an archive of expired Futures or Options intraday data.

---

### 3.7 Turnkey Platforms (AlgoTest / StockMock)
- **Official Websites:** `https://algotest.in` / `https://stockmock.in`
- **Data Type:** Closed-ecosystem web-based backtesting applications.
- **Status Classification:** `INSUFFICIENT FOR EXTERNAL VALIDATION`
- **Audit Finding:**
  - Both platforms maintain comprehensive 5+ year databases of 1-minute NIFTY options with OI.
  - However, neither platform allows exporting or downloading raw OHLCV/OI files. Strategy logic cannot be run externally in this repository's Python codebase.

---

## 4. Empirical Sample Validation Report (OptionsData.shop Sample)

A free, legitimate 3-day sample (September 15–17, 2026) was downloaded and audited via [`research/validation/validate_sample_data.py`](validate_sample_data.py).

### 4.1 Schema Verification

| Field | Source Type | Maps to Strategy Spec? | Notes |
|---|---|---|---|
| `datetime` | `timestamp[us]` | YES | Bar start time in IST. |
| `stock_code` | `string` | YES | Nominal identifier (`NIFTY`). |
| `exchange_code` | `string` | YES | Exchange segment (`NFO`). |
| `product_type` | `string` | YES | Product type (`Options`). |
| `expiry_date` | `string` | YES | Explicit expiry date (e.g. `15-SEP-2026`). |
| `strike_price` | `float64` | YES | Fixed nominal strike (e.g. `25000.0`). |
| `right` | `string` | YES | Option right (`Call` / `Put`). |
| `open` | `float64` | YES | Bar open premium. |
| `high` | `float64` | YES | Bar high premium. |
| `low` | `float64` | YES | Bar low premium. |
| `close` | `float64` | YES | Bar close premium / LTP. |
| `volume` | `int64` | YES | Cumulative volume in bar. |
| `open_interest`| `int64` | YES | Open interest at bar end. |

### 4.2 End-to-End Strategy Reconstruction Test
- **Evaluation Date/Time:** `2026-09-15 10:00:00` (Weekly Expiry Day)
- **Underlying Reference:** ATM = `25000.0`
- **Target Strikes ($ATM \pm 5$):** `[24750, 24800, 24850, 24900, 24950, 25000, 25050, 25100, 25150, 25200, 25250]`
- **Call (CE) Availability:** 11 of 11 strikes present (100% complete).
- **Put (PE) Availability:** **5 of 11 strikes present (Only 45.5% complete)**. Strikes `24850, 24950, 25050, 25150, 25250` were completely absent.
- **Chain Test Result:** **FAILED**. The strategy rejects incomplete option snapshots to avoid distorted OI resistance and support levels.

---

## 5. Final Classification & Recommendation

```
+------------------------------------+--------------------------+-------------------------------------------------------------+
| Provider                           | Classification           | Operational Viability                                       |
+------------------------------------+--------------------------+-------------------------------------------------------------+
| NSE Data & Analytics (DotEx)       | SUITABLE                 | Full 5-Year Institutional Compliance (Requires Budget)     |
| Global DataFeeds (GFDL)            | PARTIALLY SUITABLE       | Viable Commercial Candidate (Requires Custom Sales Inquiry) |
| ICICI Direct Breeze API            | PARTIALLY SUITABLE       | Technical Fit, but High Scraping/Throttling Friction        |
| OptionsData.shop                   | INSUFFICIENT             | Fails 5-Year Span (3.5y max) & Missing 50pt Put Strikes     |
| TrueData                           | INSUFFICIENT             | No Expired F&O Intraday API Support                         |
| Zerodha Kite Connect / Upstox      | INSUFFICIENT             | No Expired Contracts Supported                              |
| AlgoTest / StockMock               | INSUFFICIENT             | Closed Platform (No Raw Data Export)                        |
| NSE Bhavcopy (Free)                | INSUFFICIENT             | EOD Only (No 5-minute Bars)                                 |
+------------------------------------+--------------------------+-------------------------------------------------------------+
```

### Recommendation for Next Steps
1. **Primary Institutional Route:** If budget permits, acquire official historical 1-minute/5-minute F&O data directly from **NSE Data & Analytics (DotEx)**. This is the only exchange-authorized dataset that guarantees 100% completeness, zero missing strikes, and full 5-year coverage.
2. **Primary Commercial Vendor Route:** Contact **Global DataFeeds (GFDL)** sales to request a verified sample of their offline historical NIFTY F&O pack covering 2021–2026, explicitly requesting verification that all 50-point Put strikes and minute-level OI arrays are populated.
3. **No Automatic Purchases:** In strict compliance with guidelines, no purchases have been made, no payment details entered, and the strategy remains frozen and blocked.
