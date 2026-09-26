# SENSIBULL OBSERVATION & MULTI-SOURCE SCHEMAS (PACKAGE 3.1)

## 1. `SensibullStatus` Enumeration

Tracks operational states of the Sensibull perception source:

| Status Enum Value | Description |
| :--- | :--- |
| `OBSERVED` | Page loaded successfully and key derivatives metrics were extracted. |
| `NOT_VISIBLE` | Option chain elements were not found in the visible DOM. |
| `NOT_AVAILABLE` | Source is disabled in configuration or runtime prerequisites are missing. |
| `NOT_LOADED` | Browser navigation timed out or connection failed. |
| `AUTHENTICATION_REQUIRED` | Page is blocked by user broker sign-in barrier. No bypass attempted. |
| `PARSE_FAILED` | Page loaded, but DOM layout altered or unrecognized; metrics could not be parsed. |
| `STALE` | Observed data timestamp is outdated relative to market hours. |
| `ERROR` | Unhandled browser or communication exception during inspection. |

---

## 2. `SensibullObservation` Schema

```python
class SensibullObservation(BaseModel):
    observation_id: str                # Unique identifier e.g. "sensi_a1b2c3d4"
    timestamp: datetime                # Observation timestamp in UTC
    source: str = "sensibull"          # Source identifier
    status: SensibullStatus            # Explicit lifecycle status
    instrument: str = "NIFTY"          # Traded instrument
    underlying: str = "NIFTY 50"       # Underlying asset description
    expiry: Optional[str]              # Selected option expiry date string
    spot_reference: Optional[float]    # Displayed index spot price
    option_chain_available: bool       # Liveness indicator for option table
    visible_option_chain_data: dict    # Raw DOM or extracted table data
    
    # Derivatives Sentiment Metrics (None when unobserved, NEVER 0.0)
    pcr: Optional[float]               # Put-Call Ratio (e.g. 0.95)
    oi_information: dict               # Total Call OI, Total Put OI, max strike
    oi_change_information: dict        # Net OI shifts
    iv_information: dict               # ATM Implied Volatility e.g. {"atm_iv": 13.8}
    strike_information: List[OptionChainStrike] # List of strikes around ATM
    max_pain_information: Optional[float]       # Max Pain Strike price e.g. 24500.0
    important_levels: List[float]      # Key inflection levels e.g. [24500.0, 24530.0]
    
    screenshot_reference: Optional[str] # Local path to captured screenshot
    visible_text: Optional[str]        # Sanitized text excerpt (max 4,000 chars)
    warnings: List[str]                # Non-fatal alerts (e.g. auth banner, injection attempt)
    errors: List[str]                  # Critical failure notices
    confidence: float                  # Perceptual extraction confidence [0.0 - 1.0]
    freshness: ObservationFreshness    # FRESH, STALE, UNKNOWN
    metadata: dict                     # Diagnostic telemetry
```

---

## 3. `MultiSourceComparisonResult` Schema

```python
class MultiSourceComparisonResult(BaseModel):
    sensibull_spot: Optional[float]
    tradingview_spot: Optional[float]
    numerical_close: Optional[float]

    # Sensibull vs Numerical Feed
    sensibull_vs_numerical_diff: Optional[float]
    sensibull_vs_numerical_pct: Optional[float]
    sensibull_vs_numerical_status: str  # MATCH, MINOR_DIFFERENCE, SIGNIFICANT_DIFFERENCE, INSUFFICIENT_DATA

    # TradingView vs Numerical Feed
    tradingview_vs_numerical_diff: Optional[float]
    tradingview_vs_numerical_pct: Optional[float]
    tradingview_vs_numerical_status: str

    details: List[str]
```

---

## 4. `Unified MarketObservation` Integration

In Package 3.1, the canonical `MarketObservation` model incorporates both `sensibull_observation` and `multi_source_cross_check`:

```python
class MarketObservation(BaseModel):
    observation_id: str
    timestamp: datetime
    symbol: str = "NIFTY"
    market_status: MarketSessionStatus
    one_hour_candles: List[Candle]
    fifteen_minute_candles: List[Candle]
    browser_observation: Optional[BrowserObservation]       # TradingView visual observation
    sensibull_observation: Optional[SensibullObservation]   # Sensibull derivatives observation
    data_quality: DataQuality
    source_status: Dict[str, Any]
    cross_check: Optional[CrossCheckResult]                 # Single cross-check
    multi_source_cross_check: Optional[MultiSourceComparisonResult] # Multi-source validation
```
