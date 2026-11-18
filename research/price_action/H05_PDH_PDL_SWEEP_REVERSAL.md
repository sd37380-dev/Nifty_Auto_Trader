# Strategy Candidate: H05 — PDH / PDL Liquidity Sweep & Reversal

**Classification:** `ROBUST CANDIDATE`  
**Data Evaluated:** NIFTY 50 Spot Index (5-Minute Bars | 2021–2026)  
**Primary Edge:** False Breakout Trap at Previous Day Extremes  

---

## 1. Strategy Summary & Mathematical Definition

```
[Previous Day Finalized at Session Close (15:30 IST)]
  ├─ PDH = Max(High of Day D-1)
  └─ PDL = Min(Low of Day D-1)
                   │
                   ▼
[5M Intraday Candle i (Between 09:15 and 15:00 IST)]
  ├─ SHORT SETUP (High Sweep Trap):
  │    * Candle High pierces above PDH: High > PDH
  │    * Candle fails to hold breakout: Close < PDH
  │    * Significant upper rejection wick: Upper Wick / Candle Range >= 0.35
  │    * Stop Loss Base = Candle High
  │
  └─ LONG SETUP (Low Sweep Trap):
       * Candle Low pierces below PDL: Low < PDL
       * Candle fails to hold breakdown: Close > PDL
       * Significant lower rejection wick: Lower Wick / Candle Range >= 0.35
       * Stop Loss Base = Candle Low
                   │
                   ▼
[Execution at Candle i+1 OPEN]
  * Entry Price = Next Candle OPEN
  * Stop Loss = Base SL Level +/- 5.0 Points Buffer
  * Target = Entry +/- (Risk * 2.0) [Fixed 2R Target]
  * Position Limit: 1 Active Trade at a time
  * Cutoff: No entries after 15:00 IST | Mandatory EOD Exit at 15:25 IST
```

---

## 2. 5-Year Empirical Performance (2021–2026)

Evaluated on 92,605 5-minute bars across 1,242 trading days:

| Metric | Both Directions | Long Only | Short Only |
|---|---|---|---|
| **Total Trades** | 847 | 437 | 412 |
| **Wins / Losses** | 323 / 524 | 159 / 278 | 165 / 247 |
| **Win Rate** | **38.13%** | 36.38% | **40.05%** |
| **Gross Points** | **+2,547.75 pts** | +822.80 pts | **+1,764.20 pts** |
| **Slippage Points (1 pt/trade)** | 847.00 pts | 437.00 pts | 412.00 pts |
| **Net Points** | **+1,700.75 pts** | +385.80 pts | **+1,352.20 pts** |
| **Profit Factor (Net)** | **1.13** | 1.05 | **1.24** |
| **Profit Factor (Gross)**| **1.21** | 1.11 | **1.33** |
| **Expectancy per Trade**| **+2.01 pts** | +0.88 pts | **+3.28 pts** |
| **Max Drawdown (Points)**| 818.55 pts | 785.45 pts | **487.60 pts** |
| **Trades per Trading Day**| 0.68 | 0.35 | 0.33 |
| **Max Consecutive Losses**| 12 | 14 | 11 |

---

## 3. Robustness Battery Findings

### A. Walk-Forward Stability (Chronological Split)
- **Training (2021–2023, In-Sample):** 336 trades | Win Rate 38.39% | Net +651.00 pts | **PF 1.14**
- **Validation (2024):** 215 trades | Win Rate 37.67% | Net +453.20 pts | **PF 1.13**
- **Out-of-Sample Test (2025–2026):** 296 trades | Win Rate 38.18% | Net +596.55 pts | **PF 1.12**
- *Conclusion:* Demonstrates strong stability across independent regimes with virtually constant profit factor.

### B. Target R:R Sensitivity
- **1.0R Target:** 923 trades | WR 52.55% | Net +91.85 pts | PF 1.01
- **1.5R Target:** 879 trades | WR 44.14% | Net +955.07 pts | PF 1.08
- **2.0R Target (Baseline):** 847 trades | WR 38.13% | Net +1,700.75 pts | **PF 1.13**
- **2.5R Target:** 829 trades | WR 33.05% | Net +1,085.55 pts | PF 1.08
- **3.0R Target:** 807 trades | WR 29.74% | Net +724.95 pts | PF 1.05
- *Conclusion:* Stable performance across 1.5R–2.5R targets without parameter fragility.

### C. Stop Loss Buffer Sensitivity
- **3.0 Points:** Net +1,633.80 pts | PF 1.13 | Max DD 929.70 pts
- **5.0 Points (Baseline):** Net +1,700.75 pts | PF 1.13 | Max DD 818.55 pts
- **8.0 Points:** Net +1,960.40 pts | PF 1.15 | Max DD 849.40 pts
- **12.0 Points:** Net +1,225.65 pts | PF 1.08 | Max DD 1,021.40 pts
- *Conclusion:* Positive across all buffers from 3 to 12 points.

---

## 4. Retail Friction Analysis

- **Gross P&L (Points):** +2,547.75 pts (₹1,27,387.50 gross on 1 lot)
- **Statutory Turnover Taxes:** ₹2,80,987.63
- **Slippage Cost (1.0 pt round-trip):** ₹42,350.00
- **Net Trading Account P&L:** **-₹1,95,950.13**
- *Critical Insight:* While the price edge generates over 1,700 net index points, retail turnover taxes and exchange charges across 847 trades consume ₹3.23 Lakhs. To trade this live, position sizing must be scaled to larger point targets or executed via non-linear options strategies.

---

## 5. What Must Be Validated on NIFTY Futures

1. **Spot vs Futures Basis:** When Spot pierces PDH, does the Futures contract also sweep or trade at a significant premium/discount?
2. **Rollover Weeks:** Does the edge hold during monthly expiry roll cycles?
3. **Execution Slippage:** Actual limit vs market order slippage on active futures contracts during sudden rejection spikes.
