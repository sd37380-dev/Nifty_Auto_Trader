"""
15-Minute Live Trade Intelligence Report Generator.
Executable directly from CLI or invoked by automated scheduler.
"""

from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parent
NIFTY_PKG_DIR = ROOT_DIR / "nifty-autonomous-trader"
if str(NIFTY_PKG_DIR) not in sys.path:
    sys.path.insert(0, str(NIFTY_PKG_DIR))

from nifty_trader.market_data.report_service import get_report_service

if __name__ == "__main__":
    srv = get_report_service(NIFTY_PKG_DIR)
    out = srv.generate_report()
    print("\n=======================================================")
    print("✅ 15-MINUTE TRADE INTELLIGENCE REPORT GENERATED!")
    print(f"🕒 Generated at: {out.get('timestamp')}")
    print(f"📁 Target Dirs:   {out.get('dirs')}")
    print("=======================================================\n")
