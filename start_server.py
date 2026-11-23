import sys
from pathlib import Path

root = Path(__file__).resolve().parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

from nifty_trader.dashboard.server import run_dashboard_server

if __name__ == "__main__":
    run_dashboard_server(host="127.0.0.1", port=8080, open_browser=False, block=True)
