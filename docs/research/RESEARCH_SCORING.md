# HERMES INDEPENDENT DYNAMIC RESEARCH SCORING

**Document:** `docs/research/RESEARCH_SCORING.md`  
**Engine:** `nifty_trader/research_zone/assessment.py`  
**Core Invariant:** Strictly NO fixed or static percentage weights  

---

## 1. The Dynamic Importance Principle

In quantitative research, static indicator weights (such as `Trend=25%, Momentum=20%, Volume=20%, OI=20%, Volatility=15%`) are mathematically flawed because market regimes constantly shift:
* **Strong Trending Regimes:** Trend stack alignment and momentum expansion dominate; mean-reversion oscillators produce false counter-signals.
* **Range-Bound / Consolidating Regimes:** Mean-reversion and support/resistance reactions matter far more than trend-following EMAs.
* **Option Expiry Days:** Open Interest concentrations, Max Pain, and Call/Put writing walls dominate technical chart patterns.
* **High Volatility Breakouts:** Contradiction checks and risk falsification penalties must be heavily weighted to prevent bull/bear traps.

Accordingly, Hermes evaluates context-driven segments dynamically and assigns situational **importance weights** ($\text{importance}_i \in [0.0, 1.0]$):

$$\text{Total Score} = \frac{\sum_{i=1}^n \left(\text{Segment Score}_i \times \text{Segment Importance}_i\right)}{\sum_{i=1}^n \text{Segment Importance}_i}$$

---

## 2. Standard Evaluation Segments

Hermes constructs and evaluates segments based on current empirical evidence:

1. **Trend & Market Structure:**
   * Examines EMA stacks (EMA 20 vs EMA 50), price positioning, higher highs / lower lows.
   * Score range: $[-100.0, +100.0]$.
   * Importance: Dynamically boosted in trending regimes ($0.85$), dampened in consolidating regimes ($0.40$).
2. **Momentum & Volume Expansion:**
   * Evaluates RSI (14), MACD histogram, and Volume 20-SMA expansion ratio.
   * Score range: $[-100.0, +100.0]$.
   * Importance: Scaled up ($0.80$) when volume expands $> 1.2\times$ average.
3. **Order Flow & Open Interest:**
   * Analyzes OI change %, PCR (Put-Call Ratio), Call/Put writing pressure.
   * Score range: $[-100.0, +100.0]$.
   * Importance: Elevated ($0.85$) during aggressive long/short OI accumulation.
4. **Contradiction & Falsification Check:**
   * Evaluates empirical counter-examples, failure regimes, and false positive rates discovered during backtesting.
   * Score range: $[-100.0, +100.0]$. High false positive rates ($> 50\%$) impose heavy skepticism penalties.
   * Importance: High ($0.75 - 0.90$) to protect against overfitted signals.
5. **Empirical Hypothesis Validation:**
   * Direct backtest win rate and profit factor score.
   * Importance: Scaled by sample size ($0.85$ if sample size $\ge 20$, $0.45$ otherwise).

---

## 3. Direction & Confidence Derivation

### Total Score Bounds:
* Total Score $\in [-100.0, +100.0]$:
  * $+100.0$: Extremely Bullish
  * $0.0$: Perfectly Neutral
  * $-100.0$: Extremely Bearish

### Market Direction:
* **`BULLISH`**: Total Score $\ge +25.0$ AND Confidence $\ge 0.55$.
* **`BEARISH`**: Total Score $\le -25.0$ AND Confidence $\ge 0.55$.
* **`UNCLEAR`**: Confidence $< 0.50$ (signals conflict or high contradiction failure rate).
* **`NEUTRAL`**: Total Score between $-25.0$ and $+25.0$.

### Confidence Calculation:
* Baseline confidence derived from segment consensus and sample size: $0.40 + (0.50 \times \text{Agreement Ratio})$.
* Contradiction penalty: If contradiction false positive rate exceeds $45\%$, confidence is penalized by $-0.20$ (floor at $0.25$).
