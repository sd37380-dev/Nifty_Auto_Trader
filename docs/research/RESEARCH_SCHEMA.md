# HERMES RESEARCH DATA & CONTRACT SCHEMAS

**Document:** `docs/research/RESEARCH_SCHEMA.md`  
**Package:** `nifty_trader/research_zone/contracts.py` & `storage.py`  
**Schema Version:** `1.0`  

---

## 1. Domain Models & Pydantic Contracts

### 1.1 Data Engineering Contracts
* **`DhanRawPayload`**: Raw payload delivery from Dhan Broker APIs or WebSockets (`payload_id`, `symbol`, `exchange_segment`, `payload_type`, `raw_data`, `received_at`).
* **`NormalizedBar`**: Standardized OHLCV+OI bar across timeframes (`bar_id`, `symbol`, `timeframe`, `timestamp`, `open`, `high`, `low`, `close`, `volume`, `open_interest`, `vwap`, `trades_count`).
* **`DataQualityReport`**: Telemetry validating continuity and completeness (`report_id`, `symbol`, `timeframe`, `total_bars`, `missing_bars_count`, `completeness_percentage`, `quality_rating`).
* **`FeatureRow`**: Computed indicators per bar (`timestamp`, `close`, `ema_9`, `ema_20`, `ema_50`, `ema_200`, `rsi_14`, `macd`, `macd_signal`, `macd_hist`, `atr_14`, `vwap`, `vwap_std_upper`, `vwap_std_lower`, `volume_ratio_20`, `oi_change_pct`, `regime_tag`).
* **`FeatureSet`**: Time-series collection of FeatureRows (`feature_set_id`, `symbol`, `timeframe`, `rows`, `total_bars`, `created_at`).

### 1.2 Cognitive Research Engine Contracts
* **`ResearchQuestion`**: Structured empirical question (`question_id`, `topic`, `description`, `target_symbol`, `target_timeframe`, `parameters`, `created_at`).
* **`PatternDefinition`**: Setup condition specification (`pattern_id`, `name`, `pattern_type`, `description`, `conditions`, `required_features`).
* **`Hypothesis`**: Falsifiable testable proposition (`hypothesis_id`, `question_id`, `statement`, `testable_condition`, `null_hypothesis`, `parameters`, `status`, `created_at`).
* **`TestResult`**: Quantitative backtesting metrics (`test_id`, `hypothesis_id`, `sample_size`, `win_rate`, `profit_factor`, `avg_return_pct`, `max_drawdown_pct`, `p_value`, `summary`, `tested_at`).
* **`ContradictionSearch`**: Counter-evidence investigation (`search_id`, `hypothesis_id`, `counter_examples_count`, `failure_regimes`, `false_positive_rate`, `findings`, `conducted_at`).
* **`FollowUpResearch`**: Refined boundary inquiry (`followup_id`, `parent_research_id`, `new_question`, `rationale`, `created_at`).

### 1.3 Assessment & Memory Contracts
* **`AssessmentSegment`**: Independent analysis category (`segment_id`, `name`, `score`, `importance`, `evidence`, `reasoning_summary`).
* **`HermesResearchAssessment`**: Master assessment (`research_id`, `timestamp`, `instrument`, `timeframe`, `segments`, `total_score`, `confidence`, `direction`, `trade_finding`, `supporting_evidence`, `contradictory_evidence`, `uncertainty`, `metadata`).
* **`ResearchFinding`**: Verified empirical pattern edge (`finding_id`, `pattern_name`, `statistical_edge`, `confidence`, `evidence_refs`, `created_at`).
* **`FailedHypothesis`**: Preserved negative knowledge (`failed_id`, `hypothesis_id`, `statement`, `failure_reason`, `counter_evidence`, `lessons_learned`, `recorded_at`).
* **`ResearchHistoryEntry`**: Audit progression record (`entry_id`, `research_id`, `stage`, `summary`, `details`, `timestamp`).

---

## 2. Dedicated SQLite Database Layout (`data/hermes_research/`)

```text
data/hermes_research/
├── market_data.db
│   ├── raw_payloads (payload_id, symbol, exchange_segment, payload_type, raw_data, received_at)
│   ├── normalized_bars (bar_id, symbol, timeframe, timestamp, open, high, low, close, volume, open_interest, vwap)
│   └── feature_sets (feature_set_id, symbol, timeframe, total_bars, rows_json, created_at)
│
├── research.db
│   ├── research_questions (question_id, topic, description, target_symbol, target_timeframe, parameters)
│   ├── pattern_definitions (pattern_id, name, pattern_type, description, conditions, required_features)
│   ├── hypotheses (hypothesis_id, question_id, statement, testable_condition, null_hypothesis, status)
│   ├── test_results (test_id, hypothesis_id, sample_size, win_rate, profit_factor, p_value, summary)
│   ├── contradiction_searches (search_id, hypothesis_id, counter_examples_count, failure_regimes, false_positive_rate)
│   └── followup_researches (followup_id, parent_research_id, new_question, rationale)
│
├── assessments.db
│   ├── assessments (research_id, timestamp, instrument, timeframe, total_score, confidence, direction, trade_finding)
│   └── assessment_segments (segment_id, research_id, name, score, importance, evidence, reasoning_summary)
│
└── research_memory.db
    ├── research_findings (finding_id, pattern_name, statistical_edge, confidence, evidence_refs)
    ├── failed_hypotheses (failed_id, hypothesis_id, statement, failure_reason, counter_evidence, lessons_learned)
    └── research_history (entry_id, research_id, stage, summary, details, timestamp)
```
