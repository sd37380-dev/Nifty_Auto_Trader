# CANONICAL OBSERVATION CONTRACTS (VERSION 1.0)

## 1. Architectural Mission & The Single Pipeline

Before building **Package 4 (Gemini & Multi-Model Trading Brain)**, the perception architecture is locked behind a set of canonical, immutable, evidence-traceable contracts.

All observation sources—TradingView, Sensibull, Yahoo Finance, NSE, and Human Operator Steering—feed the future Trading Brain through a single canonical contract:

```text
TradingView ─────┐
Sensibull ───────┤
Numerical Data ──┤
Human Steering ──┤
                 ↓
          Observation Sources
                 ↓
          Canonical Contracts
                 ↓
      UnifiedMarketObservation (v1.0)
                 ↓
            PACKAGE 4
          Trading Brain
```

### The Non-Negotiable Boundary:
> **"Package 3 reports what was observed and where it came from (evidence traceable). Package 4 interprets what those observations mean."**

Package 3 and 3.1 **NEVER** output:
- `BUY`, `SELL`, `ENTRY`, `STOP`, `TARGET`
- "This is a bullish setup", "Therefore enter here"

Package 3 and 3.1 **ONLY** output factual, objective observations:
- "15M candles show a sequence of higher swing highs over the observed window."
- "Sensibull displayed elevated put open interest around strike 24,500."
- "TradingView visually shows price near the recent range high."

---

## 2. Core Canonical Contracts Reference

### 2.1 `ObservationSource`
Every perception source declares itself consistently:
```python
class ObservationSource(BaseModel):
    schema_version: str = "1.0"
    source_id: str                      # "tradingview", "sensibull", "yahoo_finance"
    source_type: SourceChannelType      # BROWSER, NUMERICAL, OTHER
    provider: str                       # e.g. "TradingView Inc.", "Sensibull"
    version: Optional[str]              # e.g. "1.0.0"
    capabilities: List[str]             # ["chart", "candlesticks", "pcr", "option_chain"]
```

### 2.2 `CanonicalObservationStatus`
Explicit representation of operational and perceptual states without faking values:
- `SUCCESS`: Interrogated and data fully captured.
- `PARTIAL`: Interrogated, but only a subset of expected components was readable.
- `NOT_AVAILABLE`: Source is disabled or prerequisites are uninstalled.
- `NOT_VISIBLE`: Elements were not rendered in visible DOM.
- `NOT_LOADED`: Navigation timed out or failed.
- `AUTHENTICATION_REQUIRED`: Blocked by broker/platform login. No bypass attempted.
- `STALE`: Data timestamp exceeds allowable session freshness.
- `PARSE_FAILED`: Unrecognized DOM or table layout.
- `SOURCE_ERROR`: Exception during execution.
- `TIMEOUT`: Network/CDP timeout.

### 2.3 `ObservationEvidence`
Enables Package 4 to distinguish **"The agent saw this"** from **"The model inferred this"**:
```python
class ObservationEvidence(BaseModel):
    schema_version: str = "1.0"
    evidence_id: str                    # e.g. "ev_a1b2c3d4e5"
    source_id: str                      # "sensibull", "tradingview", "operator"
    observed_at: datetime               # UTC timestamp
    evidence_type: EvidenceType         # SCREENSHOT, VISIBLE_TEXT, DOM, NUMERICAL_DATA, USER_INSTRUCTION
    reference: Optional[str]            # Local screenshot path or URL
    excerpt: Optional[str]              # Verbatim text snippet
    metadata: Dict[str, Any]
```

### 2.4 `CandleObservation` & `NumericalObservation`
- Strictly limited to **1H** (macro context) and **15M** (tactical state) timeframes.
- Stored in **UTC**, with `.timestamp_ist` property for presentation and reasoning prompts.
- Completed candles (`is_complete=True`) and forming candles (`is_complete=False`) are never confused.

### 2.5 `TradingViewObservation`
- Captures visual chart context, displayed index price, and screenshot evidence.
- `visible_chart_context` strictly records descriptive structural properties:
  - `trend_appearance`
  - `range_appearance`
  - `recent_swing_structure`
  - `visible_levels`
- Strictly prohibits trading directives.

### 2.6 `SensibullObservation` & `OptionChainObservation`
- Normalized option chain dataset with call/put legs per strike:
  - `call`: `{ltp, oi, oi_change, volume, iv}`
  - `put`: `{ltp, oi, oi_change, volume, iv}`
- **Preservation of Null**: Missing metrics (PCR, Max Pain, ATM IV, OI) remain `None` / `NOT_VISIBLE`. Missing values are **NEVER coerced to 0.0**.

### 2.7 `SourceStatus`
Telemetry informing Package 4 whether it is reasoning from complete or partial data:
- `source_id: str`
- `status: CanonicalObservationStatus`
- `latency_ms: Optional[float]`
- `data_age_seconds: Optional[float]`
- `completeness: float` ($0.0$ to $1.0$)
- `warnings: List[str]`

### 2.8 `CrossSourceValidation`
Compares price alignment across sources without deciding which source is "right":
- `status`: `MATCH` ($\le 0.5\%$), `MINOR_DIFFERENCE` ($0.5\% - 1.5\%$), `SIGNIFICANT_DIFFERENCE` ($> 1.5\%$), `UNCOMPARABLE`.
- Preserves source independence.

### 2.9 `ManualInstructionContext`
Operator steering directives enter the observation context as traceable instructions. They do NOT become automatic order commands.

### 2.10 `ObservationWarning`
Structured warning items with standardized codes (`STALE_SOURCE`, `MISSING_OPTION_CHAIN`, `AUTH_REQUIRED`, `CHART_NOT_LOADED`, `SOURCE_DISAGREEMENT`, `PARTIAL_OBSERVATION`) and severity levels.

---

## 3. The Sole Input Contract: `UnifiedMarketObservation`

Package 4 does NOT directly interrogate TradingView, Sensibull, or Yahoo Finance. It receives this singular, fully assembled, verified bundle:

```python
class UnifiedMarketObservation(BaseModel):
    schema_version: str = "1.0"
    observation_id: str
    observed_at: datetime
    instrument: str
    session: str

    numerical: NumericalObservation
    visual: VisualObservation

    source_status: Dict[str, SourceStatus]
    cross_source_validation: List[CrossSourceValidation]
    manual_instruction_context: List[ManualInstructionContext]
    evidence: List[ObservationEvidence]
    warnings: List[ObservationWarning]
```

---

## 4. Contract Governance & Versioning

All contracts declare:
```python
schema_version: "1.0"
```
Future evolutions will follow semantic versioning (`1.1`, `1.2`, `2.0`), allowing Package 4 to declare compatibility and adapt gracefully.
