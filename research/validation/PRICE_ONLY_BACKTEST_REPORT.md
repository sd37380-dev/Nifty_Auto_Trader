# Phase 7 — Price-Only Long/Short Data Validation Report

**Audit Phase:** Phase 7 — Price-Only Long/Short Data Validation  
**Date:** 2026-09-30  
**Status:** COMPLETE & BASELINE LOCKED  
**Objective:** Verify the identity, integrity, and cleanliness of the existing 5-year historical NIFTY price dataset, and determine whether it can support a reliable, reproducible, look-ahead-free Long/Short intraday strategy backtest.

---

> [!CAUTION]
> ### Critical Instrument Classification Notice
> **FUTURES IDENTITY UNVERIFIED — CONFIRMED NIFTY SPOT INDEX**  
> Empirical inspection of the underlying database records, exchange segments, scrip master mappings, and Open Interest fields confirms that the existing dataset represents the **NIFTY 50 Spot Index** (`NSE IDX_I`, Security ID `13`), **NOT** NIFTY Futures.  
> 
> Therefore, in accordance with Phase 7 instructions, the results of this report are strictly classified as **"NIFTY Price-Series Validation"** and **CANNOT be claimed as a NIFTY Futures strategy result**.

---

## 1. Dataset Verification & Identity Audit

Before running the backtest, an exhaustive forensic inspection of the existing market database was performed:

| Field | Value Found in Repository | Technical Interpretation |
|---|---|---|
| **Database File** | [`data/hermes_research/market_data.db`](file:///d:/AI_Trading/nifty-autonomous-trader/data/hermes_research/market_data.db) | Dedicated Windows-safe SQLite research storage. |
| **Table Name** | `normalized_bars` | Primary normalized OHLCV+OI bar repository. |
| **Symbol** | `NIFTY` | Underlying symbol tag. |
| **Exchange / Segment** | `NSE` (`IDX_I`) | Dhan Index segment identifier. |
| **Instrument Type** | `INDEX` | Spot Index (Not derivative contract). |
| **Instrument ID (Security ID)** | `13` | Mapped in Dhan Scrip Master to `Nifty 50` Index. |
| **OHLC Fields** | `open`, `high`, `low`, `close` (`REAL`) | 5-decimal floating point price levels. |
| **Volume Field** | `volume` (`INTEGER`) | Total index market turnover / aggregate volume. |
| **Open Interest Field** | `open_interest` (`INTEGER`) | **0 across all 92,739 bars** (Indices do not have OI). |
| **Stored Timezone** | `UTC` (`+00:00`) | Standard UTC ISO-8601 timestamps. |
| **Evaluation Timezone** | `Asia/Kolkata` (`+05:30`) | Local Indian Standard Time (IST). |
| **5M Total Rows** | **92,739** | Full 5-year 5-minute bar sequence. |
| **5M Earliest Bar (IST)** | `2021-09-30 17:00:00+05:30` | Initial session load. |
| **5M Latest Bar (IST)** | `2026-09-29 19:10:00+05:30` | End of historical series. |
| **15M Total Clean Rows** | **31,529** | Multi-year 15-minute bar sequence (excluding 6,719 test telemetry rows). |
| **15M Earliest Bar (IST)**| `2021-09-30 14:00:00+05:30` | Initial session load. |
| **15M Latest Bar (IST)**  | `2026-09-29 19:00:00+05:30` | End of historical series. |

---

## 2. Data Quality Audit Findings

A full scan for anomalies across all 92,739 5-minute bars was executed:

1. **Duplicate Timestamps:** **0 duplicates detected**. The 5-minute timestamp sequence is strictly unique.
2. **Invalid OHLC Bars:** **2 bars detected** with corrupted envelopes where `Open > High`:
   - `2022-03-25T03:45:00+00:00`: Open `17289.00`, High `17287.10`, Low `17209.65`, Close `17215.10` (High is 1.90 pts below Open).
   - `2022-03-30T03:45:00+00:00`: Open `17468.15`, High `17459.20`, Low `17401.25`, Close `17404.70` (High is 8.95 pts below Open).
   *Handling:* These 2 bars were documented and flagged. No silent data mutation was performed.
3. **Zero Volume Bars:** **76,898 / 92,739 bars (82.92%)** contain `volume = 0`. This is expected behavior for an index spot feed where exchange feeds frequently omit live volume ticks.
4. **Open Interest (OI):** **0 across 100% of bars**. Confirms conclusively that the feed is not a futures contract.
5. **Weekend Sessions:** 484 bars occurred on weekend dates (e.g. annual Diwali Muhurat trading sessions and special disaster recovery mock trading days scheduled by NSE).
6. **After-Hours Bars:** 60 bars in the 5M dataset occurred outside standard 09:15–15:30 IST market hours (e.g. flat post-closing price records on 2021-09-30). Filtered cleanly by session bounds.

---

## 3. Strategy Logic & Zero Look-Ahead Implementation

The strategy logic was coded in [`nifty_trader/strategies/price_validation_strategy.py`](../../nifty_trader/strategies/price_validation_strategy.py) using fixed, unoptimized baseline parameters:

```
[15M Candle Finalized at or before T]
  ├─ LONG BIAS : Close > EMA20 > EMA50 AND EMA20(t) > EMA20(t-1)
  └─ SHORT BIAS: Close < EMA20 < EMA50 AND EMA20(t) < EMA20(t-1)
                   │
                   ▼
[5M Signal Candle at Close T (between 09:15 and 15:00 IST)]
  ├─ LONG SETUP : Low <= EMA20, Close >= EMA20, 0 <= (Close - EMA20) <= ATR14 * 0.25
  │               Bullish Rejection: Close > Open, Close > EMA20, Low <= EMA20
  │               SL = Candle Low - 5 pts
  │               Signal Logged at Close T
  │
  └─ SHORT SETUP: High >= EMA20, Close <= EMA20, 0 <= (EMA20 - Close) <= ATR14 * 0.25
                  Bearish Rejection: Close < Open, Close < EMA20, High >= EMA20
                  SL = Candle High + 5 pts
                  Signal Logged at Close T
                   │
                   ▼
[Next Candle Open (T + 1)]
  ├─ Entry Price = Next Candle OPEN
  ├─ Target = Entry + 2 * (Entry - SL) [LONG]  or  Entry - 2 * (SL - Entry) [SHORT]  (2R Target)
  ├─ Position Limit: Maximum 1 active position at any time
  └─ Session Exit: 15:25 IST Candle Close (15:30 EOD mandatory square-off)
```

### Look-Ahead Elimination Verification
- At 5M candle close timestamp $T$, the strategy queries only 15M candles whose close timestamp satisfies $T_{15M\_Close} \le T$.
- Entry execution occurs strictly at next candle `Open` ($T+1$). Future bar highs, lows, or closes are never accessed during entry or sizing.

---

## 4. Transaction Cost & Regulatory Friction Model

Costs were computed using current NSE derivative schedules with 1 standard lot (50 units):
- **Brokerage:** Flat ₹20 per executed order (₹40 round-trip).
- **Exchange Charges:** 0.00173% of turnover.
- **STT (Securities Transaction Tax):** 0.02% on sell turnover.
- **SEBI Turnover Charges:** ₹10 per crore (0.0001%).
- **Stamp Duty:** 0.002% on buy turnover.
- **GST:** 18% on (Brokerage + Exchange + SEBI).
- **Slippage:** Configured at 0.5 index points per side (1.0 index point round-trip = ₹50/trade).

---

## 5. Master Backtest Performance Comparison

```
+--------------------------------+--------------------+--------------------+--------------------+
| Metric                         | Test A: LONG ONLY  | Test B: SHORT ONLY | Test C: LONG+SHORT |
+--------------------------------+--------------------+--------------------+--------------------+
| Total Trades                   | 781                | 603                | 1,384              |
| Long Trades                    | 781                | 0                  | 781                |
| Short Trades                   | 0                  | 603                | 603                |
| Wins / Losses                  | 255 / 526          | 224 / 379          | 479 / 905          |
| Win Rate                       | 32.65%             | 37.15%             | 34.61%             |
| Gross Points                   | -855.10 pts        | +1,014.20 pts      | +159.10 pts        |
| Slippage Points                | 781.00 pts         | 603.00 pts         | 1,384.00 pts       |
| Net Points                     | -1,636.10 pts      | +411.20 pts        | -1,224.90 pts      |
| Gross P&L (INR)                | -₹42,755.00        | +₹50,710.00        | +₹7,955.00         |
| Statutory Taxes & Charges      | ₹2,58,151.25       | ₹1,99,313.04       | ₹4,57,464.29       |
| Slippage Cost (INR)            | ₹39,050.00         | ₹30,150.00         | ₹69,200.00         |
| Net P&L (INR)                  | -₹3,39,956.25      | -₹1,78,753.04      | -₹5,18,709.29      |
| Profit Factor (Net)            | 0.84               | 1.05               | 0.93               |
| Expectancy (Net Points)        | -2.09 pts          | +0.68 pts          | -0.89 pts          |
| Maximum Drawdown (Points)      | 1,736.60 pts       | 801.60 pts         | 1,679.65 pts       |
| Maximum Drawdown (INR)         | ₹86,830.00         | ₹40,080.00         | ₹83,982.50         |
| Average Trade (Net Points)     | -2.09 pts          | +0.68 pts          | -0.89 pts          |
| Average Winner                 | +34.18 pts         | +37.95 pts         | +35.94 pts         |
| Average Loser                  | -19.68 pts         | -21.34 pts         | -20.38 pts         |
| Average Holding Time           | 38.2 mins          | 31.7 mins          | 35.4 mins          |
| Trades per Trading Day         | 0.63               | 0.48               | 1.11               |
| Maximum Consecutive Losses     | 18                 | 11                 | 14                 |
| Maximum Consecutive Wins       | 6                  | 6                  | 9                  |
+--------------------------------+--------------------+--------------------+--------------------+
```

---

## 6. Year-by-Year Performance Breakdown

### 6.1 Test A: Long Only
| Year | Trades | Win Rate % | Gross Points | Net Points | Net P&L (INR) | Profit Factor | Max Drawdown (pts) |
|---|---|---|---|---|---|---|---|
| **2021** | 33 | 21.21% | -759.05 | -792.05 | -₹48,904.33 | 0.21 | 858.45 |
| **2022** | 144 | 32.64% | +44.80 | -99.20 | -₹44,860.67 | 0.95 | 739.80 |
| **2023** | 176 | 34.66% | +157.60 | -18.40 | -₹53,427.88 | 0.99 | 268.40 |
| **2024** | 176 | 32.39% | -110.60 | -286.60 | -₹77,252.53 | 0.87 | 491.15 |
| **2025** | 144 | 35.42% | -73.05 | -217.05 | -₹64,523.60 | 0.88 | 487.85 |
| **2026** | 108 | 29.63% | -114.80 | -222.80 | -₹50,987.24 | 0.85 | 586.55 |
| **TOTAL** | **781** | **32.65%** | **-855.10** | **-1,636.10** | **-₹3,39,956.25** | **0.84** | **1,736.60** |

---

### 6.2 Test B: Short Only
| Year | Trades | Win Rate % | Gross Points | Net Points | Net P&L (INR) | Profit Factor | Max Drawdown (pts) |
|---|---|---|---|---|---|---|---|
| **2021** | 32 | 31.25% | -142.30 | -174.30 | -₹17,680.67 | 0.68 | 176.15 |
| **2022** | 111 | 38.74% | +469.75 | +358.75 | -₹12,425.73 | 1.24 | 176.75 |
| **2023** | 94 | 38.30% | +219.65 | +125.65 | -₹20,949.49 | 1.12 | 232.75 |
| **2024** | 115 | 31.30% | -370.55 | -485.55 | -₹64,981.76 | 0.75 | 775.70 |
| **2025** | 140 | 38.57% | +286.05 | +146.05 | -₹44,200.99 | 1.08 | 242.00 |
| **2026** | 111 | 40.54% | +551.60 | +440.60 | -₹18,514.40 | 1.35 | 366.70 |
| **TOTAL** | **603** | **37.15%** | **+1,014.20** | **+411.20** | **-₹1,78,753.04** | **1.05** | **801.60** |

---

### 6.3 Test C: Long + Short Combined
| Year | Trades | Win Rate % | Gross Points | Net Points | Net P&L (INR) | Profit Factor | Max Drawdown (pts) |
|---|---|---|---|---|---|---|---|
| **2021** | 65 | 26.15% | -901.35 | -966.35 | -₹66,585.00 | 0.37 | 1,012.75 |
| **2022** | 255 | 35.29% | +514.55 | +259.55 | -₹57,286.40 | 1.07 | 759.90 |
| **2023** | 270 | 35.93% | +377.25 | +107.25 | -₹74,377.37 | 1.04 | 324.25 |
| **2024** | 291 | 31.96% | -481.15 | -772.15 | -₹1,42,234.29 | 0.81 | 994.15 |
| **2025** | 284 | 36.97% | +213.00 | -71.00 | -₹1,08,724.59 | 0.98 | 533.35 |
| **2026** | 219 | 35.16% | +436.80 | +217.80 | -₹69,501.64 | 1.08 | 865.40 |
| **TOTAL** | **1,384** | **34.61%** | **+159.10** | **-1,224.90** | **-₹5,18,709.29** | **0.93** | **1,679.65** |

---

## 7. Optional Breakout Confirmation Evaluation

As specified in the prompt, the optional breakout filter (`Close > prev 5m High` for Long; `Close < prev 5m Low` for Short) was evaluated as a separate baseline comparator without optimization:

| Metric | Baseline (Without Confirmation) | With Breakout Confirmation | Delta |
|---|---|---|---|
| **Total Trades** | 1,384 | 573 | -58.6% (Filters over half of entries) |
| **Win Rate** | 34.61% | 36.30% | +1.69% |
| **Net Points** | -1,224.90 pts | -241.05 pts | +983.85 pts improvement |
| **Profit Factor** | 0.93 | 0.97 | +0.04 |
| **Net P&L (INR)**| -₹5,18,709.29 | -₹2,30,865.12 | +₹2,87,844.17 reduction in friction |

*Observation:* Adding breakout confirmation removes 811 whipsaw entries and sharply reduces transaction cost drag, but net expectancy remains slightly negative under fixed baseline parameters.

---

## 8. Quantitative Insights & Key Takeaways

1. **Short-Side Asymmetry:**
   - The short side displayed a consistent gross positive edge (**+1,014.20 gross points across 603 trades**, profitable in 4 out of 6 years on points), whereas the long side lost **-855.10 gross points**.
   - Pullback entries in an uptrend frequently suffered from chop and shallow fakeouts during sideways sessions, whereas breakdowns following bearish rejections achieved target with higher velocity (31.7 min avg holding vs 38.2 min).

2. **The Impact of Retail Friction:**
   - While Short Only generated **+411.20 net points** after slippage, the actual trading account P&L was **-₹1,78,753.04** because government taxes (STT), exchange charges, SEBI turnover fees, GST, and broker commissions totaled **₹1,99,313.04**.
   - In intraday trading, a 2R strategy with a ~35–37% win rate requires a higher average point gain per trade to overcome fixed statutory per-turnover taxes.

3. **Data Usability Verdict:**
   - **The 5-minute dataset is structurally clean, chronologically sound, and fully capable of driving an automated, deterministic backtesting pipeline.**
   - Timestamps, bar intervals, and multi-timeframe alignment functioned with 100% mathematical reproducibility.
   - However, because it represents **Spot Index prices**, actual execution in live markets must be mapped to derivative instruments (Futures or Options), which exhibit basis spreads, rollover gaps, and theta decay.

---

## 9. Baseline Locked — Next Steps

- **No Parameters Optimized:** No curve fitting, parameter sweeps, or machine learning filters were applied.
- **Artifacts Generated:**
  - Trade logs exported: [`research/validation/trades_long_and_short.csv`](trades_long_and_short.csv)
  - Detailed metrics JSON: [`research/validation/price_validation_results.json`](price_validation_results.json)
- **Phase 7 Concluded:** Anticipating user review before proceeding to any strategy exploration or instrument mapping.
