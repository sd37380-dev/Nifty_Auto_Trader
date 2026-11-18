# Strategy Candidate: H01 — ORB-15 Breakout Continuation

**Classification:** `ROBUST CANDIDATE (LONG) / PROMISING (OVERALL)`  
**Data Evaluated:** NIFTY 50 Spot Index (5-Minute Bars | 2021–2026)  
**Primary Edge:** Opening Momentum Expansion from 15-Minute Base  

---

## 1. Strategy Summary & Mathematical Definition

```
[Initial 15-Minute Session (09:15 - 09:30 IST)]
  ├─ ORB15_High = Max(High of first 3 five-minute bars: 09:15, 09:20, 09:25)
  └─ ORB15_Low  = Min(Low of first 3 five-minute bars: 09:15, 09:20, 09:25)
                   │
                   ▼
[5M Intraday Candle i (Between 09:30 and 11:30 IST)]
  ├─ LONG SETUP:
  │    * Breakout Close: Close > ORB15_High and Prior Close <= ORB15_High
  │    * Solid Bullish Candle: Close > Open and Body Ratio >= 0.35
  │    * Stop Loss Base = Candle Low
  │
  └─ SHORT SETUP:
       * Breakdown Close: Close < ORB15_Low and Prior Close >= ORB15_Low
       * Solid Bearish Candle: Close < Open and Body Ratio >= 0.35
       * Stop Loss Base = Candle High
                   │
                   ▼
[Execution at Candle i+1 OPEN]
  * Entry Price = Next Candle OPEN
  * Stop Loss = Base SL Level +/- 5.0 Points Buffer
  * Target = Entry +/- (Risk * 2.0) [Fixed 2R Target]
  * Cutoff: No entries after 11:30 IST | Mandatory EOD Exit at 15:25 IST
```

---

## 2. 5-Year Empirical Performance (2021–2026)

| Metric | Both Directions | Long Only | Short Only |
|---|---|---|---|
| **Total Trades** | 1,615 | 781 | 834 |
| **Wins / Losses** | 600 / 1,015 | 290 / 491 | 310 / 524 |
| **Win Rate** | **37.15%** | **37.13%** | **37.17%** |
| **Gross Points** | **+4,499.15 pts** | **+2,364.25 pts** | **+2,134.90 pts** |
| **Slippage Points (1 pt/trade)** | 1,615.00 pts | 781.00 pts | 834.00 pts |
| **Net Points** | **+2,884.15 pts** | **+1,583.25 pts** | **+1,300.90 pts** |
| **Profit Factor (Net)** | **1.09** | **1.10** | **1.07** |
| **Profit Factor (Gross)**| **1.14** | **1.16** | **1.12** |
| **Expectancy per Trade**| **+1.79 pts** | **+2.03 pts** | **+1.56 pts** |
| **Max Drawdown (Points)**| 1,309.05 pts | 895.10 pts | 924.30 pts |
| **Trades per Trading Day**| 1.30 | 0.63 | 0.67 |
| **Max Consecutive Losses**| 15 | 13 | 12 |

---

## 3. Robustness Battery Findings

### A. Walk-Forward Stability (Chronological Split)
- **Training (2021–2023, In-Sample):** 726 trades | Win Rate 38.29% | Net +1,642.15 pts | **PF 1.13**
- **Validation (2024):** 339 trades | Win Rate 35.40% | Net +248.75 pts | **PF 1.03**
- **Out-of-Sample Test (2025–2026):** 550 trades | Win Rate 36.73% | Net +993.25 pts | **PF 1.08**
- *Conclusion:* Sustains positive expectancy across all three eras.

### B. Target R:R Sensitivity
- **1.0R Target:** Net -560.80 pts | PF 0.98 (Fails at 1R due to spread/slippage)
- **1.5R Target:** Net +1,543.87 pts | PF 1.05
- **2.0R Target (Baseline):** Net +2,884.15 pts | **PF 1.09**
- **2.5R Target:** Net +4,409.87 pts | **PF 1.13**
- **3.0R Target:** Net +5,204.40 pts | **PF 1.14**
- *Conclusion:* Momentum breakouts benefit strongly from extended runner targets (2R to 3R) rather than quick profit taking.

---

## 4. Retail Friction & Futures Validation Requirements

- **Friction Drag:** While the strategy captures +2,884 net index points, transaction costs across 1,615 trades total ₹6.10 Lakhs.
- **Futures Validation:** Requires validating intraday basis movements during the 09:30–10:00 morning volatility rush.
