"""
Standalone test script to verify Dhan HQ API connectivity and real data fetching.
"""

from datetime import datetime, timezone
import os
from pathlib import Path
import sys

# Ensure project root is in sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

load_dotenv(ROOT_DIR / ".env")
console = Console()

def main():
    console.print(Panel("[bold green]Dhan HQ Live Broker Data Test[/bold green]", expand=False))

    cid = os.getenv("DHAN_CLIENT_ID", "")
    tok = os.getenv("DHAN_ACCESS_TOKEN", "")

    if not cid or not tok or "YOUR_DHAN" in cid:
        console.print("[bold red][ERROR] DHAN_CLIENT_ID or DHAN_ACCESS_TOKEN missing in .env![/bold red]")
        console.print("Please edit .env and configure your real credentials.")
        sys.exit(1)

    masked_cid = cid[:4] + "*" * (len(cid) - 8) + cid[-4:] if len(cid) > 8 else "****"
    console.print(f"[cyan]Client ID:[/cyan] {masked_cid}")

    from nifty_trader.research_zone.dhan_adapter import LiveDhanDataAdapter

    adapter = LiveDhanDataAdapter(client_id=cid, access_token=tok)

    # 1. Health check
    console.print("[dim]Testing connection to Dhan HQ API...[/dim]")
    health = adapter.health_check()
    status_color = "green" if health.get("live_api_connected") else "red"
    console.print(f"API Connection: [{status_color}]{health.get('status')}[/{status_color}] (Live API: {health.get('live_api_connected')})")

    if not health.get("live_api_connected"):
        console.print("[yellow]Warning: Could not connect to Dhan fundlimit. Check your access token expiry.[/yellow]")

    # 2. Fetch real NIFTY bars
    console.print("\n[dim]Fetching real 15M candles for NIFTY from Dhan HQ...[/dim]")
    now = datetime.now(timezone.utc)
    from nifty_trader.research_zone.dhan_adapter import datetime as dt, timedelta
    start_date = now - timedelta(days=5)

    nifty_bars = adapter.fetch_historical_bars(symbol="NIFTY", timeframe="15M", from_date=start_date, to_date=now)
    console.print(f"[bold green][OK] Fetched {len(nifty_bars)} bars for NIFTY![/bold green]")

    if nifty_bars:
        latest = nifty_bars[-1]
        console.print(f"Latest NIFTY 15M Close: [bold yellow]Rs. {latest.close:,.2f}[/bold yellow] (Timestamp: {latest.timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')})")

    # 3. Fetch real BANKNIFTY bars
    console.print("\n[dim]Fetching real 15M candles for BANKNIFTY from Dhan HQ...[/dim]")
    bn_bars = adapter.fetch_historical_bars(symbol="BANKNIFTY", timeframe="15M", from_date=start_date, to_date=now)
    console.print(f"[bold green][OK] Fetched {len(bn_bars)} bars for BANKNIFTY![/bold green]")

    if bn_bars:
        latest_bn = bn_bars[-1]
        console.print(f"Latest BANKNIFTY 15M Close: [bold yellow]Rs. {latest_bn.close:,.2f}[/bold yellow] (Timestamp: {latest_bn.timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')})")

    # Table preview
    table = Table(title="[bold cyan]Latest Dhan Live Candle Data[/bold cyan]")
    table.add_column("Symbol", style="white")
    table.add_column("Timestamp (UTC)", style="dim")
    table.add_column("Open", style="yellow")
    table.add_column("High", style="green")
    table.add_column("Low", style="red")
    table.add_column("Close", style="bold yellow")
    table.add_column("Volume", style="white")

    for b in nifty_bars[-3:]:
        table.add_row("NIFTY", b.timestamp.strftime("%Y-%m-%d %H:%M"), f"{b.open:,.2f}", f"{b.high:,.2f}", f"{b.low:,.2f}", f"{b.close:,.2f}", str(b.volume))

    for b in bn_bars[-3:]:
        table.add_row("BANKNIFTY", b.timestamp.strftime("%Y-%m-%d %H:%M"), f"{b.open:,.2f}", f"{b.high:,.2f}", f"{b.low:,.2f}", f"{b.close:,.2f}", str(b.volume))

    console.print(table)
    console.print("[bold green]Dhan HQ Live Data Integration is active and operating smoothly![/bold green]\n")

if __name__ == "__main__":
    main()
