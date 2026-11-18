# HERMES DATA ENGINEERING ARCHITECTURE

**Document:** `docs/research/DATA_ENGINEERING_ARCHITECTURE.md`  
**Zone:** Data Engineering Layer (`nifty_trader/research_zone/data_engineering.py`)  
**Status:** Implemented & Verified  

---

## 1. Overview & Pipeline

The **Data Engineering Zone** transforms raw broker payloads into clean, normalized, multi-timeframe, and indicator-enriched datasets ready for autonomous quantitative research.

```text
Dhan Raw Payload (Minute bars / Intraday ticks / Option chain / Market depth)
      │
      ▼
Mathematical Invariant Validation (OHLC bounds, non-zero prices, volume integrity)
      │
      ▼
Cleaning & Deduplication (Preserves latest bar per timestamp)
      │
      ▼
Multi-Timeframe Generation (Resampling 1M → 5M, 15M, 1H, 1D)
      │
      ▼
Quantitative Feature Preparation (EMAs, RSI, MACD, ATR, VWAP Bands, Volume & OI)
      │
      ▼
Data Quality Assessment & Reporting (DQR Rating: EXCELLENT, GOOD, DEGRADED, CRITICAL)
```

---

## 2. Mathematical OHLC Invariants

Every candlestick must strictly satisfy:
$$\text{Low} \le \text{Open} \le \text{High}$$
$$\text{Low} \le \text{Close} \le \text{High}$$
$$\text{Open} > 0, \quad \text{High} > 0, \quad \text{Low} > 0, \quad \text{Close} > 0$$
$$\text{Volume} \ge 0, \quad \text{Open Interest} \ge 0$$

Any corrupted, inverted, or zero-price bar is rejected and logged in the telemetry counters.

---

## 3. Resampling Engine

The resampling module aggregates $1\text{M}$ bars into higher timeframes ($5\text{M}, 15\text{M}, 1\text{H}, 1\text{D}$):
* $\text{Open} = \text{Open}_{\text{first}}$
* $\text{High} = \max(\text{High}_i)$
* $\text{Low} = \min(\text{Low}_i)$
* $\text{Close} = \text{Close}_{\text{last}}$
* $\text{Volume} = \sum \text{Volume}_i$
* $\text{Open Interest} = \text{Open Interest}_{\text{last}}$
* $\text{VWAP} = \frac{\sum (\text{Typical Price}_i \times \text{Volume}_i)}{\sum \text{Volume}_i}$

---

## 4. Quantitative Feature Set (`FeatureRow`)

Computed indicators for empirical research:
1. **Exponential Moving Averages:** EMA 9, EMA 20, EMA 50, EMA 200
2. **Relative Strength Index (RSI):** 14-period RSI using exponential smoothing
3. **MACD:** Fast 12, Slow 26, Signal 9 with MACD Histogram
4. **Average True Range (ATR):** 14-period volatility metric
5. **Intraday VWAP & Bands:** Volume-weighted average price with $\pm 1.5$ standard deviation upper/lower bands
6. **Volume Ratio:** Current volume divided by 20-period Simple Moving Average of volume
7. **Open Interest Change %:** Net percentage change in contracts relative to prior bar
8. **Regime Tag:** Automatic classification into `TRENDING_UP`, `TRENDING_DOWN`, `RANGE_BOUND`, `HIGH_VOLATILITY`, `LOW_VOLATILITY`, or `UNDEFINED`.

---

## 5. Data Quality Report (`DataQualityReport`)

Evaluates dataset integrity:
* `completeness_percentage`: Ratio of received bars to expected continuous trading bars.
* `gap_events`: Documented time skips exceeding expected timeframe interval.
* `quality_rating`:
  * `EXCELLENT` ($\ge 98\%$ completeness, 0 invalid candles)
  * `GOOD` ($\ge 90\%$ completeness, $\le 2$ gaps)
  * `DEGRADED` ($75\% - 90\%$ completeness)
  * `CRITICAL` ($< 75\%$ completeness or severe corruptions)
