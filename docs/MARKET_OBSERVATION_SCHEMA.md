# Market Observation & Perception Schemas

## 1. Overview

Package 3 defines two rigorous, strictly non-trading Pydantic schemas:
1. `MarketObservation`: Consolidated numerical, visual, and operational telemetry.
2. `MarketPerceptionOutput`: Factual cognitive perception structured response from Gemini.

---

## 2. Ingestion Model: `MarketObservation`

```python
class MarketObservation(BaseModel):
    observation_id: str
    timestamp: datetime
    symbol: str = "NIFTY"
    market_status: MarketSessionStatus
    one_hour_candles: List[Candle]
    fifteen_minute_candles: List[Candle]
    browser_observation: Optional[BrowserObservation]
    data_quality: DataQuality
    source_status: Dict[str, Any]
    cross_check: Optional[CrossCheckResult]

    # Computed Properties
    @property
    def latest_1h(self) -> Optional[Candle]: ...
    @property
    def latest_15m(self) -> Optional[Candle]: ...
    @property
    def timestamp_ist(self) -> datetime: ...
    @property
    def h1_summary(self) -> str: ...
    @property
    def m15_summary(self) -> str: ...
    @property
    def cross_check_match(self) -> bool: ...
    @property
    def cross_check_discrepancy_pct(self) -> float: ...
```

---

## 3. Cognitive Output Schema: `MarketPerceptionOutput`

```python
class MarketPerceptionOutput(BaseModel):
    """
    Strictly non-trading schema returned by Gemini for market perception.
    EXCLUDES trading execution directives.
    """
    market_regime_description: str = Field(
        description="Factual assessment of the overarching higher-timeframe market regime."
    )
    one_hour_structure_description: str = Field(
        description="Objective structural observation on the 1H timeframe."
    )
    fifteen_minute_structure_description: str = Field(
        description="Tactical price behavior on the 15M timeframe."
    )
    notable_levels: List[float] = Field(
        default_factory=list,
        description="Prominent visible numerical price levels, swing highs, swing lows, or round-number inflection zones.",
    )
    recent_changes: List[str] = Field(
        default_factory=list,
        description="Deterministic changes observed between recent candle periods or events.",
    )
    uncertainties: List[str] = Field(
        default_factory=list,
        description="Unknowns, data ambiguities, conflicting signals, or missing information.",
    )
    data_quality_assessment: str = Field(
        description="Evaluation of source data integrity, alignment between visual and numerical data, and data freshness.",
    )
    observation_summary: str = Field(
        description="Concise neutral executive summary of current market conditions."
    )
```

---

## 4. Non-Trading Schema Invariants

* **Omission of Trade Signals:** No `BUY`, `SELL`, `action`, `entry_price`, `stop_loss`, or `target` fields exist in this schema.
* **Pure Situational Awareness:** The reasoning model is strictly confined to reporting objective facts about structural market context.
