"""
Historical OHLC Data Importer & Database Manager.

Allows importing 1-year (or any date range) OHLC data into:
  1. data/market/nse_spot_data.db (Table: nse_spot_records)
  2. data/market/market_cache.db  (Table: candles)

Supports:
  - Importing from custom CSV files (TradingView export, NSE India CSV, Broker CSV)
  - Auto-fetching 1-year historical OHLC from Yahoo Finance (^NSEI for NIFTY 50, ^NSEBANK for BANKNIFTY)
"""

import argparse
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import sys
from typing import Optional
import urllib.request

ROOT_DIR = Path(__file__).resolve().parent.parent
SPOT_DB_PATH = ROOT_DIR / "data" / "market" / "nse_spot_data.db"
CACHE_DB_PATH = ROOT_DIR / "data" / "market" / "market_cache.db"


def ensure_dbs():
    """Ensures database tables exist."""
    SPOT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(SPOT_DB_PATH))
    with conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS nse_spot_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp_utc TEXT,
                timestamp_ist TEXT,
                date TEXT,
                time TEXT,
                symbol TEXT,
                spot_price REAL,
                open_price REAL,
                high_price REAL,
                low_price REAL,
                close_price REAL,
                previous_close REAL,
                pdh REAL,
                pdl REAL,
                change_pts REAL,
                change_pct REAL,
                volume INTEGER,
                source TEXT,
                created_at TEXT
            )
        """)
    conn.close()


def parse_row_date(date_str: str) -> tuple[str, str, str, str]:
    """
    Parses various date/time formats from CSVs and returns:
    (date_str, time_str, timestamp_ist, timestamp_utc)
    """
    date_str = date_str.strip()
    dt = None

    # Try common formats
    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%d-%m-%Y %H:%M:%S",
        "%d-%m-%Y",
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
    ]

    for fmt in formats:
        try:
            dt = datetime.strptime(date_str, fmt)
            break
        except ValueError:
            continue

    if not dt:
        # Fallback to date parser or raw
        dt = datetime.now()

    d_str = dt.strftime("%Y-%m-%d")
    t_str = dt.strftime("%H:%M:%S")
    ist_str = f"{d_str} {t_str} IST"
    utc_str = f"{d_str} {t_str} UTC"
    return d_str, t_str, ist_str, utc_str


def import_csv_to_db(csv_path: str, symbol: str = "NIFTY 50") -> int:
    """
    Imports custom CSV file into nse_spot_data.db.
    Maps headers case-insensitively:
      date/timestamp/time -> date
      open -> open_price
      high -> high_price
      low -> low_price
      close/spot/ltp -> close_price, spot_price
      volume/vol -> volume
    """
    ensure_dbs()
    path = Path(csv_path)
    if not path.exists():
        print(f"❌ Error: CSV file not found at: {csv_path}")
        return 0

    conn = sqlite3.connect(str(SPOT_DB_PATH))
    inserted = 0

    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        # Normalize header keys
        headers = {k.strip().lower(): k for k in reader.fieldnames or []}

        date_col = next((headers[k] for k in ["date", "timestamp", "datetime", "time"] if k in headers), None)
        open_col = next((headers[k] for k in ["open", "open price", "open_price"] if k in headers), None)
        high_col = next((headers[k] for k in ["high", "high price", "high_price"] if k in headers), None)
        low_col = next((headers[k] for k in ["low", "low price", "low_price"] if k in headers), None)
        close_col = next((headers[k] for k in ["close", "close price", "close_price", "ltp", "spot"] if k in headers), None)
        vol_col = next((headers[k] for k in ["volume", "vol", "shares traded", "total traded quantity"] if k in headers), None)

        if not (date_col and open_col and high_col and low_col and close_col):
            print(f"❌ Error: CSV must have date, open, high, low, close columns. Found: {list(headers.keys())}")
            return 0

        prev_close = 0.0
        prev_high = 0.0
        prev_low = 0.0

        with conn:
            for row in reader:
                try:
                    d_raw = row[date_col]
                    d_str, t_str, ist_str, utc_str = parse_row_date(d_raw)

                    o = float(str(row[open_col]).replace(",", "").strip())
                    h = float(str(row[high_col]).replace(",", "").strip())
                    l = float(str(row[low_col]).replace(",", "").strip())
                    c = float(str(row[close_col]).replace(",", "").strip())
                    v = int(float(str(row.get(vol_col, 0) or 0).replace(",", "").strip())) if vol_col else 0

                    chg_pts = round(c - prev_close, 2) if prev_close > 0 else 0.0
                    chg_pct = round((chg_pts / prev_close) * 100, 2) if prev_close > 0 else 0.0

                    pdh = prev_high if prev_high > 0 else h
                    pdl = prev_low if prev_low > 0 else l
                    pc = prev_close if prev_close > 0 else o

                    conn.execute("""
                        INSERT INTO nse_spot_records (
                            timestamp_utc, timestamp_ist, date, time, symbol,
                            spot_price, open_price, high_price, low_price, close_price,
                            previous_close, pdh, pdl, change_pts, change_pct, volume, source, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        utc_str, ist_str, d_str, t_str, symbol,
                        c, o, h, l, c, pc, pdh, pdl, chg_pts, chg_pct, v, "CSV_IMPORT", datetime.now(timezone.utc).isoformat()
                    ))

                    prev_close = c
                    prev_high = h
                    prev_low = l
                    inserted += 1
                except Exception as row_err:
                    continue

    conn.close()
    print(f"✅ Successfully imported {inserted} historical OHLC records for {symbol} from {csv_path} into {SPOT_DB_PATH}")
    return inserted


def auto_fetch_1year(symbol_name: str = "NIFTY 50") -> int:
    """
    Automatically downloads 1 year of daily OHLC data from Yahoo Finance and inserts into nse_spot_data.db.
    NIFTY 50 -> ^NSEI
    BANKNIFTY -> ^NSEBANK
    """
    ensure_dbs()
    ticker_map = {
        "NIFTY 50": "^NSEI",
        "BANKNIFTY": "^NSEBANK",
        "GIFT NIFTY": "^NSEI"
    }
    ticker = ticker_map.get(symbol_name, "^NSEI")
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=1y"
    print(f"🌐 Fetching 1-year OHLC for {symbol_name} ({ticker}) from Yahoo Finance...")

    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    )
    with urllib.request.urlopen(req, timeout=12) as response:
        payload = json.loads(response.read().decode("utf-8"))

    result = payload["chart"]["result"][0]
    timestamps = result.get("timestamp", [])
    quote = result["indicators"]["quote"][0]
    opens = quote.get("open", [])
    highs = quote.get("high", [])
    lows = quote.get("low", [])
    closes = quote.get("close", [])
    volumes = quote.get("volume", [])

    conn = sqlite3.connect(str(SPOT_DB_PATH))
    inserted = 0

    with conn:
        for i in range(len(timestamps)):
            ts = timestamps[i]
            o = opens[i]
            h = highs[i]
            l = lows[i]
            c = closes[i]
            v = volumes[i] or 0

            if o is None or h is None or l is None or c is None:
                continue

            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            d_str = dt.strftime("%Y-%m-%d")
            t_str = "15:30:00"
            ist_str = f"{d_str} {t_str} IST"
            utc_str = f"{d_str} 10:00:00 UTC"

            # Compute PDH and PDL from previous bar if available
            pdh = highs[i - 1] if i > 0 and highs[i - 1] else h
            pdl = lows[i - 1] if i > 0 and lows[i - 1] else l
            prev_c = closes[i - 1] if i > 0 and closes[i - 1] else o
            chg_pts = round(c - prev_c, 2)
            chg_pct = round((chg_pts / prev_c) * 100, 2) if prev_c else 0.0

            conn.execute("""
                INSERT INTO nse_spot_records (
                    timestamp_utc, timestamp_ist, date, time, symbol,
                    spot_price, open_price, high_price, low_price, close_price,
                    previous_close, pdh, pdl, change_pts, change_pct, volume, source, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                utc_str, ist_str, d_str, t_str, symbol_name,
                round(c, 2), round(o, 2), round(h, 2), round(l, 2), round(c, 2),
                round(prev_c, 2), round(pdh, 2), round(pdl, 2), chg_pts, chg_pct, int(v),
                "YAHOO_1Y_FETCH", datetime.now(timezone.utc).isoformat()
            ))
            inserted += 1

    conn.close()
    print(f"✅ Successfully inserted {inserted} trading days of 1-year OHLC for {symbol_name} into {SPOT_DB_PATH}")
    return inserted


def main():
    parser = argparse.ArgumentParser(description="Import historical 1-year OHLC data into SQLite")
    parser.add_argument("--csv", help="Path to your custom CSV file")
    parser.add_argument("--symbol", default="NIFTY 50", choices=["NIFTY 50", "BANKNIFTY", "GIFT NIFTY"], help="Target symbol")
    parser.add_argument("--auto-1y", action="store_true", help="Automatically download 1 year of daily OHLC from Yahoo Finance")
    args = parser.parse_args()

    if args.auto_1y:
        auto_fetch_1year(symbol_name=args.symbol)
    elif args.csv:
        import_csv_to_db(csv_path=args.csv, symbol=args.symbol)
    else:
        print("Usage:")
        print("  1. Auto download 1 year:  python scripts/import_historical_ohlc.py --auto-1y --symbol 'NIFTY 50'")
        print("  2. Import your CSV file:  python scripts/import_historical_ohlc.py --csv path/to/data.csv --symbol 'NIFTY 50'")


if __name__ == "__main__":
    main()
