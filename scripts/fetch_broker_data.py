"""
Fetch Broker Data CLI Script.
Connects directly to Dhan HQ API, downloads real historical market data (intraday & daily)
for NIFTY & BANKNIFTY, computes technical indicators, and saves everything cleanly into
data/hermes_research/market_data.db.
"""

import sys
from pathlib import Path

# Add project root to sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

import argparse
import logging
from datetime import datetime, timedelta, timezone
from typing import List
import httpx
from dotenv import load_dotenv
import os

from nifty_trader.research_zone.contracts import NormalizedBar
from nifty_trader.research_zone.data_engineering import DataEngineeringZone
from nifty_trader.research_zone.storage import MarketDataStore

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("broker_fetcher")


def fetch_dhan_intraday_chunk(
    client_id: str,
    access_token: str,
    sec_id: str,
    interval: str,
    from_dt: datetime,
    to_dt: datetime,
) -> List[NormalizedBar]:
    """Fetches a single chunk of intraday bars from Dhan."""
    url = "https://api.dhan.co/v2/charts/intraday"
    headers = {
        "client-id": client_id,
        "access-token": access_token,
        "Content-Type": "application/json",
    }
    payload = {
        "securityId": sec_id,
        "exchangeSegment": "IDX_I",
        "instrument": "INDEX",
        "interval": interval,
        "fromDate": from_dt.strftime("%Y-%m-%d %H:%M:%S"),
        "toDate": to_dt.strftime("%Y-%m-%d %H:%M:%S"),
    }
    try:
        resp = httpx.post(url, headers=headers, json=payload, timeout=15.0)
        if resp.status_code == 200:
            data = resp.json()
            if "open" in data and len(data["open"]) > 0:
                bars = []
                for o, h, l, c, v, t in zip(
                    data["open"],
                    data["high"],
                    data["low"],
                    data["close"],
                    data.get("volume", [0] * len(data["open"])),
                    data.get("timestamp", [0] * len(data["open"])),
                ):
                    bar_dt = datetime.fromtimestamp(t, tz=timezone.utc)
                    bars.append(
                        NormalizedBar(
                            symbol="NIFTY" if sec_id == "13" else "BANKNIFTY",
                            timeframe=f"{interval}M",
                            timestamp=bar_dt,
                            open=round(float(o), 2),
                            high=round(float(h), 2),
                            low=round(float(l), 2),
                            close=round(float(c), 2),
                            volume=int(v),
                            open_interest=0,
                        )
                    )
                return bars
        else:
            logger.warning(f"Dhan returned HTTP {resp.status_code}: {resp.text[:120]}")
    except Exception as e:
        logger.error(f"Error fetching chunk: {e}")
    return []


def fetch_dhan_rolling_option_chunk(
    client_id: str,
    access_token: str,
    sec_id: str,
    option_type: str,
    interval: str,
    from_dt: datetime,
    to_dt: datetime,
) -> List[NormalizedBar]:
    """Fetches rolling options historical bars (ATM) from Dhan."""
    url = "https://api.dhan.co/v2/charts/rollingoption"
    headers = {
        "client-id": client_id,
        "access-token": access_token,
        "Content-Type": "application/json",
    }
    payload = {
        "exchangeSegment": "NSE_FNO",
        "interval": interval,
        "securityId": sec_id,
        "instrument": "OPTIDX",
        "expiryFlag": "MONTH",
        "expiryCode": 1,
        "strike": "ATM",
        "drvOptionType": option_type.upper(),
        "requiredData": ["open", "high", "low", "close", "volume", "oi", "spot"],
        "fromDate": from_dt.strftime("%Y-%m-%d"),
        "toDate": to_dt.strftime("%Y-%m-%d"),
    }
    try:
        resp = httpx.post(url, headers=headers, json=payload, timeout=15.0)
        if resp.status_code == 200:
            data = resp.json().get("data", {})
            key = "ce" if option_type.upper() == "CALL" else "pe"
            opt_data = data.get(key)
            if opt_data and "open" in opt_data and len(opt_data["open"]) > 0:
                bars = []
                for o, h, l, c, v, oi, t in zip(
                    opt_data["open"],
                    opt_data["high"],
                    opt_data["low"],
                    opt_data["close"],
                    opt_data.get("volume", [0] * len(opt_data["open"])),
                    opt_data.get("oi", [0] * len(opt_data["open"])),
                    opt_data.get("timestamp", [0] * len(opt_data["open"])),
                ):
                    bar_dt = datetime.fromtimestamp(t, tz=timezone.utc)
                    sym_label = f"NIFTY_ATM_{key.upper()}"
                    bars.append(
                        NormalizedBar(
                            symbol=sym_label,
                            timeframe=f"{interval}M",
                            timestamp=bar_dt,
                            open=round(float(o), 2),
                            high=round(float(h), 2),
                            low=round(float(l), 2),
                            close=round(float(c), 2),
                            volume=int(v),
                            open_interest=int(oi),
                        )
                    )
                return bars
    except Exception as e:
        logger.error(f"Error fetching rolling options: {e}")
    return []


def main():
    parser = argparse.ArgumentParser(description="Fetch historical data from Dhan HQ into local database.")
    parser.add_argument("--symbol", choices=["NIFTY", "BANKNIFTY"], default="NIFTY", help="Symbol to fetch (default: NIFTY)")
    parser.add_argument("--interval", choices=["1", "5", "15", "60"], default="15", help="Candle interval in minutes (default: 15)")
    parser.add_argument("--days", type=int, default=60, help="Number of historical days to fetch (e.g. 30, 60, 180, 365)")
    parser.add_argument("--include-options", action="store_true", help="Also fetch rolling ATM Call and Put option data")
    args = parser.parse_args()

    client_id = os.getenv("DHAN_CLIENT_ID")
    access_token = os.getenv("DHAN_ACCESS_TOKEN")

    if not client_id or not access_token:
        print("[ERROR] DHAN_CLIENT_ID or DHAN_ACCESS_TOKEN missing from .env file!")
        sys.exit(1)

    sec_id = "13" if args.symbol == "NIFTY" else "25"
    db_store = MarketDataStore(root_dir / "data" / "hermes_research" / "market_data.db")
    de_zone = DataEngineeringZone()

    print("=" * 65)
    print(f"       DHAN BROKER DATA FETCHER (DhanHQ -> SQLite)        ")
    print("=" * 65)
    print(f"Target Symbol    : {args.symbol} (SecurityId: {sec_id})")
    print(f"Timeframe        : {args.interval} Minute Candles")
    print(f"History Range    : Last {args.days} days")
    print(f"Include Options  : {'YES (ATM CE & PE)' if args.include_options else 'NO'}")
    print(f"Target Database  : data/hermes_research/market_data.db")
    print("-" * 65)

    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=args.days)

    # Chunk in 60-day windows
    chunk_size_days = 60
    current_start = start_date
    all_bars: List[NormalizedBar] = []

    print("[*] Fetching index candlestick data in 60-day chunks...")
    while current_start < end_date:
        current_end = min(current_start + timedelta(days=chunk_size_days), end_date)
        chunk_bars = fetch_dhan_intraday_chunk(
            client_id, access_token, sec_id, args.interval, current_start, current_end
        )
        if chunk_bars:
            print(f"  -> [{current_start.strftime('%Y-%m-%d')} to {current_end.strftime('%Y-%m-%d')}] Received {len(chunk_bars)} bars")
            all_bars.extend(chunk_bars)
        else:
            print(f"  -> [{current_start.strftime('%Y-%m-%d')} to {current_end.strftime('%Y-%m-%d')}] No data / holiday window")
        current_start = current_end + timedelta(seconds=1)

    print(f"[SUCCESS] Total index bars retrieved: {len(all_bars)}")

    if all_bars:
        # Save to database
        saved_count = db_store.save_normalized_bars(all_bars)
        print(f"[+] Saved {saved_count} new unique bars to table 'normalized_bars'.")

        # Compute Technical Features
        print("[*] Running DataEngineeringZone feature computation...")
        feature_set = de_zone.prepare_feature_set(all_bars, symbol=args.symbol, timeframe=f"{args.interval}M")
        db_store.save_feature_set(feature_set)
        print(f"[+] Feature set computed and stored with ID: {feature_set.feature_set_id} ({feature_set.total_bars} bars with 15 indicators)")

    # Optional: Options data
    if args.include_options:
        print("\n[*] Fetching rolling ATM Call & Put option data (30-day chunks)...")
        opt_start = end_date - timedelta(days=min(args.days, 90))  # Rolling options recent window
        opt_chunk_days = 30
        opt_curr = opt_start
        all_opt_bars: List[NormalizedBar] = []

        while opt_curr < end_date:
            opt_end = min(opt_curr + timedelta(days=opt_chunk_days), end_date)
            # Call
            ce_bars = fetch_dhan_rolling_option_chunk(client_id, access_token, sec_id, "CALL", args.interval, opt_curr, opt_end)
            # Put
            pe_bars = fetch_dhan_rolling_option_chunk(client_id, access_token, sec_id, "PUT", args.interval, opt_curr, opt_end)

            if ce_bars:
                print(f"  -> ATM CE [{opt_curr.strftime('%Y-%m-%d')} to {opt_end.strftime('%Y-%m-%d')}]: {len(ce_bars)} bars")
                all_opt_bars.extend(ce_bars)
            if pe_bars:
                print(f"  -> ATM PE [{opt_curr.strftime('%Y-%m-%d')} to {opt_end.strftime('%Y-%m-%d')}]: {len(pe_bars)} bars")
                all_opt_bars.extend(pe_bars)

            opt_curr = opt_end + timedelta(days=1)

        if all_opt_bars:
            saved_opt = db_store.save_normalized_bars(all_opt_bars)
            print(f"[+] Saved {saved_opt} unique option bars (CE & PE) to 'normalized_bars'.")

    print("\n" + "=" * 65)
    print("      DATA FETCH & FEATURE COMPUTATION COMPLETED!       ")
    print("=" * 65)


if __name__ == "__main__":
    main()
