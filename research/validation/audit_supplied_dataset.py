"""Read-only integrity audit for the supplied Hermes market-data SQLite file."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "data" / "hermes_research" / "market_data.db"
OUTPUT = ROOT / "research" / "validation" / "dataset_audit.json"


def main() -> None:
    digest = hashlib.sha256(DB.read_bytes()).hexdigest()
    conn = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    report: dict = {"file": str(DB.relative_to(ROOT)), "sha256": digest, "bytes": DB.stat().st_size, "tables": {}}
    for table in tables:
        report["tables"][table] = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
    if "normalized_bars" not in tables:
        raise RuntimeError("normalized_bars table is missing")
    report["normalized_bars_schema"] = [dict(r) for r in conn.execute("PRAGMA table_info(normalized_bars)")]
    groups = conn.execute("""
        SELECT symbol,timeframe,COUNT(*) rows,MIN(timestamp) first_ts,MAX(timestamp) last_ts,
               COUNT(DISTINCT timestamp) distinct_timestamps,
               SUM(CASE WHEN open_interest IS NULL THEN 1 ELSE 0 END) missing_oi,
               SUM(CASE WHEN open_interest = 0 THEN 1 ELSE 0 END) zero_oi,
               SUM(CASE WHEN volume IS NULL THEN 1 ELSE 0 END) missing_volume,
               SUM(CASE WHEN vwap IS NULL THEN 1 ELSE 0 END) missing_vwap,
               SUM(CASE WHEN open IS NULL OR high IS NULL OR low IS NULL OR close IS NULL THEN 1 ELSE 0 END) missing_ohlc,
               SUM(CASE WHEN high < low OR high < open OR high < close OR low > open OR low > close OR volume < 0 THEN 1 ELSE 0 END) invalid_ohlc
        FROM normalized_bars GROUP BY symbol,timeframe ORDER BY symbol,timeframe
    """).fetchall()
    report["groups"] = [dict(r) for r in groups]
    detail = {}
    for group in groups:
        symbol, timeframe = group["symbol"], group["timeframe"]
        rows = conn.execute("SELECT timestamp,open,high,low,close,volume,open_interest FROM normalized_bars WHERE symbol=? AND timeframe=? ORDER BY timestamp,bar_id", (symbol,timeframe)).fetchall()
        stamps = [r["timestamp"] for r in rows]
        dates = [s[:10] for s in stamps]
        parsed = []
        for stamp in stamps:
            try:
                parsed.append(datetime.fromisoformat(stamp.replace("Z", "+00:00")))
            except ValueError:
                pass
        gaps = Counter()
        if len(parsed) > 1:
            for a, b in zip(parsed, parsed[1:]):
                delta = (b - a).total_seconds() / 60
                if delta > 0:
                    gaps[str(int(delta))] += 1
        time_counts = Counter(s[11:16] for s in stamps if len(s) >= 16)
        duplicates = len(stamps) - len(set(stamps))
        # Dates are reported as observed dates only; calendar dates without a bar are not labelled trading holidays.
        detail[f"{symbol}|{timeframe}"] = {
            "trading_dates": len(set(dates)), "duplicate_timestamps": duplicates,
            "timestamp_gaps_minutes_counts": dict(sorted(gaps.items(), key=lambda kv: int(kv[0]))),
            "timestamp_examples_per_day": dict(time_counts.most_common(12)),
            "non_monotonic_rows": sum(b <= a for a,b in zip(parsed,parsed[1:])),
            "parsed_timestamps": len(parsed),
        }
    report["timestamp_details"] = detail
    report["options_tables_or_chain_data"] = [t for t in tables if any(k in t.lower() for k in ("option", "chain", "expiry", "strike"))]
    conn.close()
    OUTPUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
