# HERMES DEEP PRICE-ACTION RESEARCH
## TOPIC 9 — TIME-OF-DAY PRICE BEHAVIOUR

**Document ID:** `HERMES-PA-RES-009`  
**Dataset:** NIFTY 50 Spot 5-Minute Continuous OHLC (Table: `normalized_bars`)  
**Data Range:** February 2019 – February 2024 (5 Years)  
**Total Analyzed Bars:** 92,605 5-Minute Bars (1,232 Full Trading Sessions)  
**Event Dataset:** `research/price_action/TIME_OF_DAY_EVENTS.csv` (9,856 Window Records)  
**Research Engine:** `research/price_action/time_of_day_research_engine.py`  
**Date:** September 2026  
**Status:** Empirical Discovery Completed

---

> ### ⚠️ Regulatory & Methodological Notice
> This study evaluates historical **NIFTY 50 Spot index data**, not NIFTY Futures. Spot index continuous bars represent pure institutional and retail market clearing without settlement pricing adjustments, quarterly roll anomalies, or carrying cost discrepancies. The findings quantify underlying structural index auction dynamics across time of day. Discovered behaviors must be independently validated against calibrated NIFTY Futures data prior to real-world capital deployment. All calculations are strictly causal and look-ahead free at decision timestamps.

---

## 1. Executive Summary

This study maps the intraday evolutionary lifecycle of the NIFTY 50 index across **eight distinct time windows** spanning the 09:15 to 15:30 trading session. By analyzing 92,605 bars across 1,232 complete trading sessions, we establish how price behavior transitions between **Expansion, Breakout, Compression, Mean Reversion, and Liquidation**.

### Key Empirical Findings:

1. **The Opening Volatility Engine (09:15–09:30):**  
   The opening 15 minutes exhibits the highest volatility ($\sigma = 22.03$) and widest absolute range (**81.40 points / 2.97 ATR**). Directional persistence from this window is strong: **63.64% of sessions close in the same net direction as the 09:15–09:30 candle**. Furthermore, opening range size is strongly predictive of total session range ($r = +0.525$): wide opening ranges produce average session ranges of **298.19 points**, whereas narrow opens result in only **159.53 points**.
2. **The 09:30–10:00 Breakout Trap:**  
   In 09:30–10:00, **87.01% of sessions break the opening 15-minute high or low**. However, **48.41% of these initial breakouts immediately fail** and close back inside the opening range. In 47.16% of sessions, this window completely reverses the direction of the opening drive.
3. **Midday Decay (11:00–14:00):**  
   Between 11:00 and 14:00, price action undergoes structural decay. Volatility sigma drops by **49.5%** (from 22.03 to 11.11), and the Kaufman Efficiency Ratio plummets from 0.246 down to **0.145**. Midday is characterized by rotational chop: median hourly range contracts to 52.50 points, and breakout occurrence drops from 87% to ~50%.
4. **The Afternoon Volatility Surge (14:00–15:00):**  
   Volatility re-accelerates after 14:00, with average hourly range expanding to **73.09 points** and volatility sigma increasing to 12.44 (+8.5% over midday). However, afternoon direction is decoupled from the morning trend: it continues morning direction **51.70%** of the time and reverses it **48.30%** of the time (pure coin toss).
5. **The Final 25-Minute Institutional Drive (15:00–15:25):**  
   The closing period is structurally distinct. Efficiency Ratio surges to **0.235** (highest since the open), with Maximum Favorable Excursion (**44.98 pts**) dramatically exceeding Adverse Excursion (**11.06 pts**). Large block trades and day-trader square-offs create one-way directional velocity.
6. **Closing Move vs Overnight Gap Disconnect:**  
   The direction of the final 25-minute move has **zero predictive power over next day's opening gap direction (49.96% accuracy)**. However, an asymmetric drift exists: following a bullish close, the average gap is **+16.01 points**, while following a bearish close it remains positive at **+8.52 points** due to structural index upward drift.

---

## 2. Window-by-Window Statistical Map

The trading day is partitioned into 8 objective intervals. All metrics are aggregated across 1,232 sessions:

### Table 2.1: Statistical Profile Across 8 Intraday Windows

| Time Window | Interval Name | Mean Range (pts) | Median Range (pts) | Mean Body (pts) | Upper Wick (pts) | Lower Wick (pts) | Volatility ($\sigma$) | Efficiency (KER) | Breakout Prob (%) | Breakout Fail (%) | Predominant Regime |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **09:15–09:30** | Opening Drive | **81.40** | **71.25** | **42.48** | 17.76 | 21.16 | **22.03** | **0.246** | — | — | **Expansion / Drive** |
| **09:30–10:00** | Initial Auction | 70.08 | 62.00 | 35.84 | 15.88 | 18.35 | 16.09 | 0.217 | **87.01%** | **48.41%** | **Breakout / Fakeout** |
| **10:00–11:00** | Morning Trend | 76.60 | 65.75 | 37.80 | 18.01 | 20.79 | 13.17 | 0.146 | **77.11%** | 49.26% | **Breakout / Trend** |
| **11:00–12:00** | Midday Chop 1 | 64.93 | 54.45 | 32.80 | 15.41 | 16.72 | **11.11** | 0.150 | 56.09% | 49.06% | **Range / Compression** |
| **12:00–13:00** | Lunch Lull | 65.16 | **52.50** | 32.36 | 15.66 | 17.14 | 11.37 | 0.148 | 51.30% | 46.04% | **Range / Compression** |
| **13:00–14:00** | European Open | 67.07 | 56.00 | 32.59 | 16.26 | 18.22 | 11.47 | 0.139 | 50.08% | 48.62% | **Rotational Chop** |
| **14:00–15:00** | Afternoon Surge| 73.09 | 62.08 | 35.51 | 17.66 | 19.92 | 12.44 | 0.139 | 50.32% | 49.35% | **Expansion / Breakout**|
| **15:00–15:25** | Closing Auction| 56.05 | 47.80 | 29.98 | 12.33 | 13.74 | 12.79 | **0.235** | 37.09% | 45.30% | **Directional Drive** |

---

## 3. Excursion Profile: MFE vs MAE Across Windows

Measuring Maximum Favorable Excursion (MFE) and Maximum Adverse Excursion (MAE) from the window open exposes where risk-reward asymmetry lives:

### Table 3.1: Intraday Excursion & Asymmetry Profile

| Time Window | Mean MFE (pts) | Mean MAE (pts) | MFE / MAE Ratio | Structural Risk Profile |
| :--- | :--- | :--- | :--- | :--- |
| **09:15–09:30** | **62.17 pts** | 19.23 pts | **3.23 : 1** | Explosive one-sided thrust; tight trailing risk |
| **09:30–10:00** | 52.56 pts | 17.51 pts | **3.00 : 1** | Strong expansion once breakout establishes |
| **10:00–11:00** | 57.96 pts | 18.64 pts | 3.11 : 1 | Sustained morning trend expansion |
| **11:00–12:00** | 49.63 pts | 15.30 pts | 3.24 : 1 | Moderate excursions, narrow absolute boundaries |
| **12:00–13:00** | 50.10 pts | 15.07 pts | 3.32 : 1 | Smallest absolute boundary; low momentum |
| **13:00–14:00** | 50.82 pts | 16.25 pts | 3.13 : 1 | Gradual volatility build-up |
| **14:00–15:00** | 54.70 pts | 18.39 pts | 2.97 : 1 | Increased adverse pushback from mean reversion |
| **15:00–15:25** | **44.98 pts** | **11.06 pts** | **4.07 : 1** | **Highest directional purity; minimal counter-pull** |

---

## 4. Deep Research Insights by Session Phase

### 4.1 Morning Dynamics (09:15–11:00)

1. **Does opening volatility contain directional information?**  
   **Yes.** The correlation between the 09:15–09:30 range and the total session range is **+0.525**. When the opening 15-minute range is in the top decile, NIFTY expands aggressively, producing an average session range of **298.19 points**. When the opening 15-minute range is compressed, the full session range contracts to **159.53 points**.
2. **Does the first move frequently reverse?**  
   In 09:30–10:00, price reverses the net direction of the 09:15–09:30 drive **47.16% of the time**. It is essentially an even split: half the time 09:30 continues the open, half the time it pulls back to retest or sweep the open.
3. **How long does opening momentum persist?**  
   Opening directional efficiency persists strongly for **45 minutes** (until ~10:00 AM). Between 10:00 and 11:00, the Efficiency Ratio drops from 0.246 to 0.146, signaling the onset of rotational consolidation.
4. **Does opening direction predict the session close?**  
   **Yes, with 63.64% accuracy.** If the 09:15–09:30 bar closes green, the session has a 63.6% probability of closing higher than the open.

---

### 4.2 Midday Dynamics (11:00–14:00)

1. **Is midday genuinely mean reverting?**  
   **Yes.** Midday efficiency plummets to **0.145** (down 41% from the open). The market generates substantial total path length (continuous 5-minute ticks) but minimal net price displacement. Price repeatedly mean reverts around the 12-bar swing midpoint and session VWAP.
2. **Is it merely lower volatility?**  
   It is **both**. Volatility sigma falls by **49.5%** (from 22.03 to 11.11), while the median hourly range shrinks to 52.50 points.
3. **Are breakouts less reliable?**  
   **Yes.** The probability of breaking prior session extremes drops from 87.01% in the morning to **50.08%–56.09% at midday**. Furthermore, nearly half (46%–49%) of these midday breakout attempts fail to hold.
4. **Does midday compression predict afternoon expansion?**  
   **Yes.** On sessions where midday range compresses severely, subsequent afternoon expansion averages **129.14 points** across the final 90 minutes.

---

### 4.3 Afternoon Dynamics (14:00–15:00)

1. **Does volatility increase after 14:00?**  
   **Yes.** Average hourly range increases from 67.07 pts (13:00–14:00) to **73.09 pts (14:00–15:00)**, and volatility sigma rises from 11.47 to 12.44 (+8.5%).
2. **Does afternoon movement continue morning direction?**  
   Afternoon direction continues the morning trend **51.70% of the time**.
3. **How often does afternoon movement reverse the morning trend?**  
   Afternoon movement reverses the morning trend **48.30% of the time**. The afternoon session behaves as an independent auction: relying on morning trend inertia after 14:00 carries near coin-flip expectancy without specific structural triggers.

---

### 4.4 Closing Period Dynamics (15:00–15:25)

1. **Is the final 25-minute period structurally different?**  
   **Decisively yes.** The Efficiency Ratio jumps to **0.235**, which is 69% higher than the preceding hour (0.139). MFE/MAE ratio reaches an extreme **4.07 : 1**, reflecting one-way institutional block clearing and short-covering/long-liquidation.
2. **How large are final-session moves?**  
   The average range in this single 25-minute window is **56.05 points (2.74 ATR)**, which is nearly as large as an entire midday 60-minute window (64.9 pts).
3. **Does the direction of the final move predict next day's opening gap?**  
   **No.** Final-window direction matches the next day's gap direction only **49.96% of the time** (pure noise). However, the absolute gap magnitude displays a positive secular bias: following a green closing drive, the next day's gap averages **+16.01 points**; following a red closing drive, the gap still averages **+8.52 points**.

---

## 5. Session Day-Type Classification & Early Identification

Across 1,232 trading sessions, price action falls into four objective structural day types:

### Table 5.1: Day-Type Distribution & Characteristics

| Day Type | Objective Mathematical Definition | Frequency (Sessions) | Percentage Share | Typical Price Character |
| :--- | :--- | :--- | :--- | :--- |
| **Trend Day** | $\text{Session Efficiency} \ge 0.65$ ($\|\text{Close} - \text{Open}\| / \text{Range} \ge 0.65$) | 383 | **31.09%** | Persistent one-way drift; minimal retracements |
| **Expansion Day**| $\text{Session Range} \ge 1.5 \times \text{ATR}$ with moderate efficiency | 378 | **30.68%** | High volatility; wide multi-directional swings |
| **Range Day** | $\text{Session Efficiency} \le 0.30$ ($\|\text{Close} - \text{Open}\| / \text{Range} \le 0.30$) | 342 | **27.76%** | Choppy oscillation; closes near session open |
| **Reversal Day** | Extreme wick $\ge 0.45 \times \text{Range}$ (morning high/low fully rejected) | 129 | **10.47%** | Strong false breakout followed by full-session reversal |

### Early Day-Type Identification by 10:00 AM:
* **Trend Day Early Trigger:** When the first 45 minutes (09:15–10:00) produce an accumulated range $\ge 2.0$ ATR and both 15-minute segments close in the same direction, the precision of predicting a full Trend Day is **38.04%** (compared to the baseline prior probability of 31.09%).
* **Range Day Early Trigger:** Early range-day identification by 10:00 AM is notoriously noisy; true range days require monitoring through 11:30 AM before compression confirms the absence of institutional participation.

---

## 6. Synthesis: How the Statistical Character of NIFTY Changes Throughout the Day

| Intraday Phase | Clock Time | Dominant Physics | Primary Edge | Deadly Mistake to Avoid |
| :--- | :--- | :--- | :--- | :--- |
| **Phase 1: Discovery** | 09:15 – 09:30 | Maximum Volatility & Range Expansion | Trade with opening 15M momentum; set directional bias (63.6% persist) | Fading the first 5 minutes without extreme wick exhaustion |
| **Phase 2: Trapping** | 09:30 – 10:00 | Breakout Attempts with High Failure (48.4%) | Fade initial breakout fakeouts; wait for structural retests | Chasing market orders on the breakout of the 09:15–09:30 range |
| **Phase 3: Morning Run**| 10:00 – 11:00 | European Pre-Open Extension | Ride verified morning trend continuations | Over-trading counter-trend scalps |
| **Phase 4: Dead Zone** | 11:00 – 14:00 | Volatility Collapse (-49.5%) & Rotational Chop | Mean-reversion scalping to VWAP; non-directional option selling | Chasing breakout signals (50% fail rate, low MFE) |
| **Phase 5: Afternoon** | 14:00 – 15:00 | Volatility Re-expansion (+8.5%) | Trade fresh afternoon structure breaks; expect independent direction | Assuming afternoon will blindly continue morning trend (48.3% reverse) |
| **Phase 6: Liquidation**| 15:00 – 15:25 | High Efficiency (0.235) Directional Block Clearing | Momentum scalping in direction of 15:00 thrust (MFE/MAE 4.07:1) | Holding counter-trend intraday positions into the close |

---

## 7. Research Artifacts & Traceability

* **Analysis Script:** `research/price_action/time_of_day_research_engine.py`
* **Metrics Data:** `research/price_action/time_of_day_metrics.json`
* **Event Log:** `research/price_action/TIME_OF_DAY_EVENTS.csv` (9,856 rows)
* **Compiled PDF Report:** `research_reports_pdf/HERMES_TIME_OF_DAY_BEHAVIOUR_*.pdf`
