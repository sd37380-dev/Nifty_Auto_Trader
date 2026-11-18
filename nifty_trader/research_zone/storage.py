"""
Dedicated SQLite Storage Managers for the Hermes Research & Intelligence Zone.

STRICT INVARIANTS:
1. Physical/Logical segregation in `data/hermes_research/` (or custom path / in-memory for testing).
2. Four dedicated databases:
   - market_data.db
   - research.db
   - assessments.db
   - research_memory.db
3. Safe context-managed connections ensuring proper closure (Windows [WinError 32] safe).
"""

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import sqlite3
from typing import Any, Dict, Generator, List, Optional

from nifty_trader.research_zone.contracts import (
    AssessmentSegment,
    ContradictionSearch,
    DhanRawPayload,
    FailedHypothesis,
    FeatureRow,
    FeatureSet,
    FollowUpResearch,
    HermesResearchAssessment,
    Hypothesis,
    HypothesisStatus,
    MarketDirection,
    NormalizedBar,
    PatternDefinition,
    PatternType,
    ResearchFinding,
    ResearchHistoryEntry,
    ResearchQuestion,
    TestResult,
)

logger = logging.getLogger(__name__)


@contextmanager
def get_db_connection(db_path: Path) -> Generator[sqlite3.Connection, None, None]:
    """
    Context manager that yields a sqlite3 connection and ensures
    it is committed and closed cleanly on Windows.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


class MarketDataStore:
    """Manages raw broker payloads, normalized OHLCV bars, and engineered feature sets."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._init_tables()

    def _init_tables(self) -> None:
        with get_db_connection(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS raw_payloads (
                    payload_id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    security_id TEXT,
                    exchange_segment TEXT NOT NULL,
                    payload_type TEXT NOT NULL,
                    raw_data TEXT NOT NULL,
                    received_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS normalized_bars (
                    bar_id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    open REAL NOT NULL,
                    high REAL NOT NULL,
                    low REAL NOT NULL,
                    close REAL NOT NULL,
                    volume INTEGER NOT NULL,
                    open_interest INTEGER NOT NULL,
                    vwap REAL NOT NULL,
                    trades_count INTEGER NOT NULL,
                    UNIQUE(symbol, timeframe, timestamp)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS feature_sets (
                    feature_set_id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    total_bars INTEGER NOT NULL,
                    rows_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)

    def save_raw_payload(self, payload: DhanRawPayload) -> None:
        with get_db_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO raw_payloads 
                (payload_id, symbol, security_id, exchange_segment, payload_type, raw_data, received_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload.payload_id,
                    payload.symbol,
                    payload.security_id,
                    payload.exchange_segment,
                    payload.payload_type,
                    json.dumps(payload.raw_data),
                    payload.received_at.isoformat(),
                ),
            )

    def save_normalized_bars(self, bars: List[NormalizedBar]) -> int:
        if not bars:
            return 0
        with get_db_connection(self.db_path) as conn:
            data = [
                (
                    b.bar_id,
                    b.symbol,
                    b.timeframe,
                    b.timestamp.isoformat(),
                    b.open,
                    b.high,
                    b.low,
                    b.close,
                    b.volume,
                    b.open_interest,
                    b.vwap,
                    b.trades_count,
                )
                for b in bars
            ]
            conn.executemany(
                """
                INSERT OR REPLACE INTO normalized_bars
                (bar_id, symbol, timeframe, timestamp, open, high, low, close, volume, open_interest, vwap, trades_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                data,
            )
        return len(bars)

    def get_bars(
        self,
        symbol: str,
        timeframe: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: Optional[int] = None,
    ) -> List[NormalizedBar]:
        query = "SELECT * FROM normalized_bars WHERE symbol = ? AND timeframe = ?"
        params: List[Any] = [symbol, timeframe]
        if start_time:
            query += " AND timestamp >= ?"
            params.append(start_time.isoformat())
        if end_time:
            query += " AND timestamp <= ?"
            params.append(end_time.isoformat())
        query += " ORDER BY timestamp ASC"
        if limit:
            query += f" LIMIT {int(limit)}"

        with get_db_connection(self.db_path) as conn:
            rows = conn.execute(query, params).fetchall()
            return [
                NormalizedBar(
                    bar_id=r["bar_id"],
                    symbol=r["symbol"],
                    timeframe=r["timeframe"],
                    timestamp=datetime.fromisoformat(r["timestamp"]),
                    open=r["open"],
                    high=r["high"],
                    low=r["low"],
                    close=r["close"],
                    volume=r["volume"],
                    open_interest=r["open_interest"],
                    vwap=r["vwap"],
                    trades_count=r["trades_count"],
                )
                for r in rows
            ]

    def save_feature_set(self, feature_set: FeatureSet) -> None:
        rows_data = [r.model_dump(mode="json") for r in feature_set.rows]
        with get_db_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO feature_sets
                (feature_set_id, symbol, timeframe, total_bars, rows_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    feature_set.feature_set_id,
                    feature_set.symbol,
                    feature_set.timeframe,
                    feature_set.total_bars,
                    json.dumps(rows_data),
                    feature_set.created_at.isoformat(),
                ),
            )

    def get_latest_feature_set(self, symbol: str, timeframe: str) -> Optional[FeatureSet]:
        with get_db_connection(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM feature_sets WHERE symbol = ? AND timeframe = ? ORDER BY created_at DESC LIMIT 1",
                (symbol, timeframe),
            ).fetchone()
            if not row:
                return None
            rows_data = json.loads(row["rows_json"])
            return FeatureSet(
                feature_set_id=row["feature_set_id"],
                symbol=row["symbol"],
                timeframe=row["timeframe"],
                total_bars=row["total_bars"],
                rows=[FeatureRow(**r) for r in rows_data],
                created_at=datetime.fromisoformat(row["created_at"]),
            )


class ResearchStore:
    """Manages research questions, patterns, hypotheses, tests, contradictions, and follow-ups."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._init_tables()

    def _init_tables(self) -> None:
        with get_db_connection(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS research_questions (
                    question_id TEXT PRIMARY KEY,
                    topic TEXT NOT NULL,
                    description TEXT NOT NULL,
                    target_symbol TEXT NOT NULL,
                    target_timeframe TEXT NOT NULL,
                    parameters TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS pattern_definitions (
                    pattern_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    pattern_type TEXT NOT NULL,
                    description TEXT NOT NULL,
                    conditions TEXT NOT NULL,
                    required_features TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS hypotheses (
                    hypothesis_id TEXT PRIMARY KEY,
                    question_id TEXT NOT NULL,
                    statement TEXT NOT NULL,
                    testable_condition TEXT NOT NULL,
                    null_hypothesis TEXT NOT NULL,
                    parameters TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS test_results (
                    test_id TEXT PRIMARY KEY,
                    hypothesis_id TEXT NOT NULL,
                    sample_size INTEGER NOT NULL,
                    win_rate REAL NOT NULL,
                    profit_factor REAL NOT NULL,
                    avg_return_pct REAL NOT NULL,
                    max_drawdown_pct REAL NOT NULL,
                    p_value REAL,
                    summary TEXT NOT NULL,
                    tested_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS contradiction_searches (
                    search_id TEXT PRIMARY KEY,
                    hypothesis_id TEXT NOT NULL,
                    counter_examples_count INTEGER NOT NULL,
                    failure_regimes TEXT NOT NULL,
                    false_positive_rate REAL NOT NULL,
                    findings TEXT NOT NULL,
                    conducted_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS followup_researches (
                    followup_id TEXT PRIMARY KEY,
                    parent_research_id TEXT NOT NULL,
                    new_question TEXT NOT NULL,
                    rationale TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)

    def save_question(self, q: ResearchQuestion) -> None:
        with get_db_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO research_questions
                (question_id, topic, description, target_symbol, target_timeframe, parameters, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    q.question_id,
                    q.topic,
                    q.description,
                    q.target_symbol,
                    q.target_timeframe,
                    json.dumps(q.parameters),
                    q.created_at.isoformat(),
                ),
            )

    def get_questions(self, limit: int = 50) -> List[ResearchQuestion]:
        with get_db_connection(self.db_path) as conn:
            rows = conn.execute("SELECT * FROM research_questions ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
            return [
                ResearchQuestion(
                    question_id=r["question_id"],
                    topic=r["topic"],
                    description=r["description"],
                    target_symbol=r["target_symbol"],
                    target_timeframe=r["target_timeframe"],
                    parameters=json.loads(r["parameters"]),
                    created_at=datetime.fromisoformat(r["created_at"]),
                )
                for r in rows
            ]

    def save_pattern(self, p: PatternDefinition) -> None:
        with get_db_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO pattern_definitions
                (pattern_id, name, pattern_type, description, conditions, required_features)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    p.pattern_id,
                    p.name,
                    p.pattern_type.value,
                    p.description,
                    json.dumps(p.conditions),
                    json.dumps(p.required_features),
                ),
            )

    def get_patterns(self) -> List[PatternDefinition]:
        with get_db_connection(self.db_path) as conn:
            rows = conn.execute("SELECT * FROM pattern_definitions").fetchall()
            return [
                PatternDefinition(
                    pattern_id=r["pattern_id"],
                    name=r["name"],
                    pattern_type=PatternType(r["pattern_type"]),
                    description=r["description"],
                    conditions=json.loads(r["conditions"]),
                    required_features=json.loads(r["required_features"]),
                )
                for r in rows
            ]

    def save_hypothesis(self, h: Hypothesis) -> None:
        with get_db_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO hypotheses
                (hypothesis_id, question_id, statement, testable_condition, null_hypothesis, parameters, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    h.hypothesis_id,
                    h.question_id,
                    h.statement,
                    h.testable_condition,
                    h.null_hypothesis,
                    json.dumps(h.parameters),
                    h.status.value,
                    h.created_at.isoformat(),
                ),
            )

    def update_hypothesis_status(self, hypothesis_id: str, status: HypothesisStatus) -> None:
        with get_db_connection(self.db_path) as conn:
            conn.execute(
                "UPDATE hypotheses SET status = ? WHERE hypothesis_id = ?",
                (status.value, hypothesis_id),
            )

    def save_test_result(self, res: TestResult) -> None:
        with get_db_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO test_results
                (test_id, hypothesis_id, sample_size, win_rate, profit_factor, avg_return_pct, max_drawdown_pct, p_value, summary, tested_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    res.test_id,
                    res.hypothesis_id,
                    res.sample_size,
                    res.win_rate,
                    res.profit_factor,
                    res.avg_return_pct,
                    res.max_drawdown_pct,
                    res.p_value,
                    res.summary,
                    res.tested_at.isoformat(),
                ),
            )

    def save_contradiction_search(self, cs: ContradictionSearch) -> None:
        with get_db_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO contradiction_searches
                (search_id, hypothesis_id, counter_examples_count, failure_regimes, false_positive_rate, findings, conducted_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    cs.search_id,
                    cs.hypothesis_id,
                    cs.counter_examples_count,
                    json.dumps(cs.failure_regimes),
                    cs.false_positive_rate,
                    cs.findings,
                    cs.conducted_at.isoformat(),
                ),
            )

    def save_followup_research(self, fu: FollowUpResearch) -> None:
        with get_db_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO followup_researches
                (followup_id, parent_research_id, new_question, rationale, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    fu.followup_id,
                    fu.parent_research_id,
                    fu.new_question,
                    fu.rationale,
                    fu.created_at.isoformat(),
                ),
            )


class AssessmentsStore:
    """Manages Hermes dynamic research assessments and their dynamically weighted segments."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._init_tables()

    def _init_tables(self) -> None:
        with get_db_connection(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS assessments (
                    research_id TEXT PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    instrument TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    total_score REAL NOT NULL,
                    confidence REAL NOT NULL,
                    direction TEXT NOT NULL,
                    trade_finding TEXT NOT NULL,
                    supporting_evidence TEXT NOT NULL,
                    contradictory_evidence TEXT NOT NULL,
                    uncertainty TEXT NOT NULL,
                    metadata TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS assessment_segments (
                    segment_id TEXT PRIMARY KEY,
                    research_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    score REAL NOT NULL,
                    importance REAL NOT NULL,
                    evidence TEXT NOT NULL,
                    reasoning_summary TEXT NOT NULL,
                    FOREIGN KEY(research_id) REFERENCES assessments(research_id)
                )
            """)

    def save_assessment(self, ass: HermesResearchAssessment) -> None:
        with get_db_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO assessments
                (research_id, timestamp, instrument, timeframe, total_score, confidence, direction,
                 trade_finding, supporting_evidence, contradictory_evidence, uncertainty, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ass.research_id,
                    ass.timestamp.isoformat(),
                    ass.instrument,
                    ass.timeframe,
                    ass.total_score,
                    ass.confidence,
                    ass.direction.value,
                    ass.trade_finding,
                    json.dumps(ass.supporting_evidence),
                    json.dumps(ass.contradictory_evidence),
                    json.dumps(ass.uncertainty),
                    json.dumps(ass.metadata),
                ),
            )
            for seg in ass.segments:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO assessment_segments
                    (segment_id, research_id, name, score, importance, evidence, reasoning_summary)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        seg.segment_id,
                        ass.research_id,
                        seg.name,
                        seg.score,
                        seg.importance,
                        json.dumps(seg.evidence),
                        seg.reasoning_summary,
                    ),
                )

    def get_assessment(self, research_id: str) -> Optional[HermesResearchAssessment]:
        with get_db_connection(self.db_path) as conn:
            row = conn.execute("SELECT * FROM assessments WHERE research_id = ?", (research_id,)).fetchone()
            if not row:
                return None
            seg_rows = conn.execute("SELECT * FROM assessment_segments WHERE research_id = ?", (research_id,)).fetchall()
            segments = [
                AssessmentSegment(
                    segment_id=s["segment_id"],
                    name=s["name"],
                    score=s["score"],
                    importance=s["importance"],
                    evidence=json.loads(s["evidence"]),
                    reasoning_summary=s["reasoning_summary"],
                )
                for s in seg_rows
            ]
            return HermesResearchAssessment(
                research_id=row["research_id"],
                timestamp=datetime.fromisoformat(row["timestamp"]),
                instrument=row["instrument"],
                timeframe=row["timeframe"],
                segments=segments,
                total_score=row["total_score"],
                confidence=row["confidence"],
                direction=MarketDirection(row["direction"]),
                trade_finding=row["trade_finding"],
                supporting_evidence=json.loads(row["supporting_evidence"]),
                contradictory_evidence=json.loads(row["contradictory_evidence"]),
                uncertainty=json.loads(row["uncertainty"]),
                metadata=json.loads(row["metadata"]),
            )

    def get_latest_assessment(self, instrument: str = "NIFTY") -> Optional[HermesResearchAssessment]:
        with get_db_connection(self.db_path) as conn:
            row = conn.execute(
                "SELECT research_id FROM assessments WHERE instrument = ? ORDER BY timestamp DESC LIMIT 1",
                (instrument,),
            ).fetchone()
            if not row:
                return None
            return self.get_assessment(row["research_id"])

    def list_assessments(self, limit: int = 20) -> List[HermesResearchAssessment]:
        with get_db_connection(self.db_path) as conn:
            rows = conn.execute("SELECT research_id FROM assessments ORDER BY timestamp DESC LIMIT ?", (limit,)).fetchall()
            results = []
            for r in rows:
                ass = self.get_assessment(r["research_id"])
                if ass:
                    results.append(ass)
            return results


class ResearchMemoryStore:
    """Manages empirical findings, negative knowledge (failed hypotheses), and research history."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._init_tables()

    def _init_tables(self) -> None:
        with get_db_connection(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS research_findings (
                    finding_id TEXT PRIMARY KEY,
                    pattern_name TEXT NOT NULL,
                    statistical_edge TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    evidence_refs TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS failed_hypotheses (
                    failed_id TEXT PRIMARY KEY,
                    hypothesis_id TEXT NOT NULL,
                    statement TEXT NOT NULL,
                    failure_reason TEXT NOT NULL,
                    counter_evidence TEXT NOT NULL,
                    lessons_learned TEXT NOT NULL,
                    recorded_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS research_history (
                    entry_id TEXT PRIMARY KEY,
                    research_id TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    details TEXT NOT NULL,
                    timestamp TEXT NOT NULL
                )
            """)

    def save_finding(self, f: ResearchFinding) -> None:
        with get_db_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO research_findings
                (finding_id, pattern_name, statistical_edge, confidence, evidence_refs, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    f.finding_id,
                    f.pattern_name,
                    f.statistical_edge,
                    f.confidence,
                    json.dumps(f.evidence_refs),
                    f.created_at.isoformat(),
                ),
            )

    def get_findings(self, limit: int = 50) -> List[ResearchFinding]:
        with get_db_connection(self.db_path) as conn:
            rows = conn.execute("SELECT * FROM research_findings ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
            return [
                ResearchFinding(
                    finding_id=r["finding_id"],
                    pattern_name=r["pattern_name"],
                    statistical_edge=r["statistical_edge"],
                    confidence=r["confidence"],
                    evidence_refs=json.loads(r["evidence_refs"]),
                    created_at=datetime.fromisoformat(r["created_at"]),
                )
                for r in rows
            ]

    def save_failed_hypothesis(self, fh: FailedHypothesis) -> None:
        with get_db_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO failed_hypotheses
                (failed_id, hypothesis_id, statement, failure_reason, counter_evidence, lessons_learned, recorded_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    fh.failed_id,
                    fh.hypothesis_id,
                    fh.statement,
                    fh.failure_reason,
                    json.dumps(fh.counter_evidence),
                    fh.lessons_learned,
                    fh.recorded_at.isoformat(),
                ),
            )

    def get_failed_hypotheses(self, limit: int = 50) -> List[FailedHypothesis]:
        with get_db_connection(self.db_path) as conn:
            rows = conn.execute("SELECT * FROM failed_hypotheses ORDER BY recorded_at DESC LIMIT ?", (limit,)).fetchall()
            return [
                FailedHypothesis(
                    failed_id=r["failed_id"],
                    hypothesis_id=r["hypothesis_id"],
                    statement=r["statement"],
                    failure_reason=r["failure_reason"],
                    counter_evidence=json.loads(r["counter_evidence"]),
                    lessons_learned=r["lessons_learned"],
                    recorded_at=datetime.fromisoformat(r["recorded_at"]),
                )
                for r in rows
            ]

    def record_history_entry(self, entry: ResearchHistoryEntry) -> None:
        with get_db_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO research_history
                (entry_id, research_id, stage, summary, details, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    entry.entry_id,
                    entry.research_id,
                    entry.stage,
                    entry.summary,
                    json.dumps(entry.details),
                    entry.timestamp.isoformat(),
                ),
            )

    def get_history(self, research_id: Optional[str] = None, limit: int = 100) -> List[ResearchHistoryEntry]:
        query = "SELECT * FROM research_history"
        params: List[Any] = []
        if research_id:
            query += " WHERE research_id = ?"
            params.append(research_id)
        query += " ORDER BY timestamp ASC LIMIT ?"
        params.append(limit)

        with get_db_connection(self.db_path) as conn:
            rows = conn.execute(query, params).fetchall()
            return [
                ResearchHistoryEntry(
                    entry_id=r["entry_id"],
                    research_id=r["research_id"],
                    stage=r["stage"],
                    summary=r["summary"],
                    details=json.loads(r["details"]),
                    timestamp=datetime.fromisoformat(r["timestamp"]),
                )
                for r in rows
            ]


class ResearchZoneStorage:
    """
    Unified manager for all 4 isolated databases in the Hermes Research Zone.
    Defaults to `data/hermes_research/`.
    """

    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = base_dir or Path("data/hermes_research")
        self.market_data = MarketDataStore(self.base_dir / "market_data.db")
        self.research = ResearchStore(self.base_dir / "research.db")
        self.assessments = AssessmentsStore(self.base_dir / "assessments.db")
        self.memory = ResearchMemoryStore(self.base_dir / "research_memory.db")
