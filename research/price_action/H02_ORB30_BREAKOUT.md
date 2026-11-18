# Strategy Candidate: H02 — ORB-30 Breakout Continuation

**Classification:** `ROBUST CANDIDATE (LONG) / PROMISING (OVERALL)`  
**Data Evaluated:** NIFTY 50 Spot Index (5-Minute Bars | 2021–2026)  
**Primary Edge:** 30-Minute Established Opening Range Expansion  

---

## 1. Strategy Summary & Mathematical Definition

```
[Initial 30-Minute Session (09:15 - 09:45 IST)]
  ├─ ORB30_High = Max(High of first 6 five-minute bars: 09:15 to 09:40)
  └─ ORB30_Low  = Min(Low of first 6 five-minute bars: 09:15 to 09:40)
                   │
                   ▼
[5M Intraday Candle i (Between 09:45 and 12:00 IST)]
  ├─ LONG SETUP:
  │    * Breakout Close: Close > ORB30_High and Prior Close <= ORB30_High
  │    * Solid Bullish Candle: Close > Open and Body Ratio >= 0.35
  │    * Stop Loss Base = Candle Low
  │
  └─ SHORT SETUP:
       * Breakdown Close: Close < ORB30_Low and Prior Close >= ORB30_Low
       * Solid Bearish Candle: Close < Open and Body Ratio >= 0.35
       * Stop Loss Base = Candle High
                   │
                   ▼
[Execution at Candle i+1 OPEN]
  * Entry Price = Next Candle OPEN
  * Stop Loss = Base SL Level +/- 5.0 Points Buffer
  * Target = Entry +/- (Risk * 2.0) [Fixed 2R Target]
  * Cutoff: No entries after 12:00 IST | Mandatory EOD Exit at 15:25 IST
```

---

## 2. 5-Year Empirical Performance (2021–2026)

| Metric | Both Directions | Long Only | Short Only |
|---|---|---|---|
| **Total Trades** | 1,520 | 768 | 752 |
| **Wins / Losses** | 564 / 956 | 289 / 479 | 275 / 477 |
| **Win Rate** | **37.11%** | **37.63%** | **36.57%** |
| **Gross Points** | **+3,671.40 pts** | **+2,197.05 pts** | **+1,474.30 pts** |
| **Slippage Points (1 pt/trade)** | 1,520.00 pts | 768.00 pts | 752.00 pts |
| **Net Points** | **+2,151.40 pts** | **+1,429.05 pts** | **+722.40 pts** |
| **Profit Factor (Net)** | **1.07** | **1.10** | **1.05** |
| **Profit Factor (Gross)**| **1.12** | **1.15** | **1.09** |
| **Expectancy per Trade**| **+1.42 pts** | **+1.86 pts** | **+0.96 pts** |
| **Max Drawdown (Points)**| 1,225.50 pts | 904.55 pts | 823.10 pts |
| **Trades per Trading Day**| 1.22 | 0.62 | 0.61 |
| **Max Consecutive Losses**| 14 | 12 | 11 |

---

## 3. Robustness Battery Findings

### A. Walk-Forward Stability (Chronological Split)
- **Training (2021–2023, In-Sample):** 692 trades | Win Rate 37.86% | Net +1,310.25 pts | **PF 1.11**
- **Validation (2024):** 311 trades | Win Rate 36.66% | Net +324.50 pts | **PF 1.04**
- **Out-of-Sample Test (2025–2026):** 517 trades | Win Rate 36.36% | Net +516.65 pts | **PF 1.05**
- *Conclusion:* Slightly lower trade frequency than ORB-15, but positive across all out-of-sample periods.

### B. Long vs Short Asymmetry
- **Long Only:** Delivers +1,429.05 net points (PF 1.10) with 37.63% win rate.
- **Short Only:** Delivers +722.40 net points (PF 1.05) with 36.57% win rate.
- *Insight:* Breakouts from a 30-minute range exhibit stronger follow-through on the long side during bull regimes.
