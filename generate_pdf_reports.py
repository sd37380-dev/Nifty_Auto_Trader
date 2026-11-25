"""
Generates individual Trade Report PDFs and 15-Minute Market Bulletin PDFs
with annotated 15M candlestick charts (entry/exit spot, strike price, IST times).
"""

import json
import os
import subprocess
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as patches

IST = timezone(timedelta(hours=5, minutes=30))
EDGE_EXE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

ROOT_DIR = Path(r"d:\AI_Trading")
TRADE_PDF_DIR = ROOT_DIR / "reports" / "trade_pdfs"
BULLETIN_PDF_DIR = ROOT_DIR / "reports" / "15m_market_pdfs"
TMP_DIR = ROOT_DIR / "reports" / "_tmp_charts"

TRADE_PDF_DIR.mkdir(parents=True, exist_ok=True)
BULLETIN_PDF_DIR.mkdir(parents=True, exist_ok=True)
TMP_DIR.mkdir(parents=True, exist_ok=True)


def fetch_15m_candles(symbol: str = "NIFTY", base_url: str = "http://127.0.0.1:8080") -> list[dict]:
    url = f"{base_url}/api/chart/candles?symbol={symbol}&interval=15m"
    with urllib.request.urlopen(url, timeout=10) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    candles = data.get("candles", data) if isinstance(data, dict) else data
    return candles


def ts_to_ist(unix_ts: int) -> datetime:
    # TradingView / chart API timestamps in this app may already be shifted or UTC;
    # inspect hour: if hour in [3..10] -> UTC, convert to IST (+5:30).
    dt_utc = datetime.fromtimestamp(unix_ts, tz=timezone.utc)
    if 3 <= dt_utc.hour <= 10:
        return dt_utc.astimezone(IST)
    return dt_utc.replace(tzinfo=IST)


def filter_today_candles(candles: list[dict], date_str: str = "2026-11-25", max_time_ist: str | None = None) -> list[dict]:
    out = []
    for c in candles:
        dt = ts_to_ist(int(c["time"]))
        if dt.strftime("%Y-%m-%d") == date_str:
            hhmm = dt.strftime("%H:%M")
            if max_time_ist and hhmm > max_time_ist:
                continue
            item = dict(c)
            item["ist_dt"] = dt
            item["label"] = hhmm
            out.append(item)
    return out


def plot_15m_candle_chart(
    candles: list[dict],
    out_png: Path,
    title: str,
    strike: float | None = None,
    entry_spot: float | None = None,
    entry_time_hhmm: str | None = None,
    exit_spot: float | None = None,
    exit_time_hhmm: str | None = None,
) -> None:
    if not candles:
        return

    fig, (ax, ax_vol) = plt.subplots(
        2, 1, figsize=(11, 5.4), gridspec_kw={"height_ratios": [3.5, 1]}, sharex=True
    )
    fig.patch.set_facecolor("#0f172a")
    ax.set_facecolor("#0f172a")
    ax_vol.set_facecolor("#0f172a")

    xs = list(range(len(candles)))
    labels = [c["label"] for c in candles]

    entry_idx = None
    exit_idx = None
    for i, c in enumerate(candles):
        o, h, l, cl = float(c["open"]), float(c["high"]), float(c["low"]), float(c["close"])
        vol = float(c.get("volume", 0))
        color = "#22c55e" if cl >= o else "#ef4444"
        ax.plot([i, i], [l, h], color=color, linewidth=1.3, zorder=2)
        body_low = min(o, cl)
        body_h = max(abs(cl - o), 1.5)
        rect = patches.Rectangle((i - 0.32, body_low), 0.64, body_h, facecolor=color, edgecolor=color, zorder=3)
        ax.add_patch(rect)
        ax_vol.bar(i, vol, width=0.6, color=color, alpha=0.65)

        if entry_time_hhmm and c["label"] <= entry_time_hhmm:
            entry_idx = i
        if exit_time_hhmm and c["label"] <= exit_time_hhmm:
            exit_idx = i

    if strike is not None:
        ax.axhline(strike, color="#f59e0b", linestyle=":", linewidth=1.6, zorder=4)
        ax.text(0.1, strike, f" STRIKE: {int(strike)}", color="#fbbf24", fontsize=8.5, fontweight="bold",
                va="bottom", bbox=dict(boxstyle="round,pad=0.2", facecolor="#1e293b", edgecolor="#f59e0b", alpha=0.9))

    if entry_spot is not None:
        ax.axhline(entry_spot, color="#38bdf8", linestyle="--", linewidth=1.4, zorder=4)
        ex = entry_idx if entry_idx is not None else 0
        ax.scatter([ex], [entry_spot], color="#38bdf8", s=90, zorder=6, edgecolors="white", linewidths=1.2)
        ax.annotate(
            f"ENTRY {entry_spot:,.1f}\n({entry_time_hhmm} IST)",
            xy=(ex, entry_spot), xytext=(max(0, ex - 1.5), entry_spot + 25),
            color="#e0f2fe", fontsize=8, fontweight="bold",
            bbox=dict(boxstyle="round,pad=0.25", facecolor="#0369a1", edgecolor="#38bdf8"),
            arrowprops=dict(arrowstyle="->", color="#38bdf8", lw=1.3),
            zorder=7,
        )

    if exit_spot is not None:
        ax.axhline(exit_spot, color="#c084fc", linestyle="--", linewidth=1.4, zorder=4)
        xx = exit_idx if exit_idx is not None else len(candles) - 1
        ax.scatter([xx], [exit_spot], color="#c084fc", s=90, zorder=6, edgecolors="white", linewidths=1.2)
        ax.annotate(
            f"EXIT {exit_spot:,.1f}\n({exit_time_hhmm} IST)",
            xy=(xx, exit_spot), xytext=(min(len(candles) - 1, xx + 0.5), exit_spot - 30),
            color="#f3e8ff", fontsize=8, fontweight="bold",
            bbox=dict(boxstyle="round,pad=0.25", facecolor="#6b21a8", edgecolor="#c084fc"),
            arrowprops=dict(arrowstyle="->", color="#c084fc", lw=1.3),
            zorder=7,
        )

    ax.set_title(title, color="#f8fafc", fontsize=11, fontweight="bold", pad=10)
    ax.grid(True, color="#1e293b", linestyle="-", linewidth=0.7)
    ax_vol.grid(True, color="#1e293b", linestyle="-", linewidth=0.7)
    ax.tick_params(colors="#94a3b8", labelsize=8)
    ax_vol.tick_params(colors="#94a3b8", labelsize=8)
    ax_vol.set_xticks(xs)
    ax_vol.set_xticklabels(labels, rotation=45, ha="right", fontsize=7.5)
    ax.set_ylabel("Spot Price (₹)", color="#cbd5e1", fontsize=8.5)
    ax_vol.set_ylabel("Vol", color="#cbd5e1", fontsize=8)
    for spine in list(ax.spines.values()) + list(ax_vol.spines.values()):
        spine.set_color("#334155")

    plt.tight_layout()
    plt.savefig(out_png, dpi=180, facecolor="#0f172a")
    plt.close(fig)


def html_to_pdf(html_path: Path, pdf_path: Path) -> None:
    uri = html_path.resolve().as_uri()
    cmd = [
        EDGE_EXE,
        "--headless",
        "--disable-gpu",
        "--no-pdf-header-footer",
        f"--print-to-pdf={str(pdf_path.resolve())}",
        uri,
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def generate_trade_pdf(trade: dict) -> Path:
    candles = filter_today_candles(fetch_15m_candles(trade.get("symbol", "NIFTY")), trade["date"])
    chart_png = TMP_DIR / f"chart_{trade['trade_id']}.png"
    plot_15m_candle_chart(
        candles=candles,
        out_png=chart_png,
        title=f"{trade['instrument']} 15M Candle Chart — {trade['contract']} ({trade['date']} IST)",
        strike=trade["strike"],
        entry_spot=trade["entry_spot"],
        entry_time_hhmm=trade["entry_ist_hhmm"],
        exit_spot=trade["exit_spot"],
        exit_time_hhmm=trade["exit_ist_hhmm"],
    )

    pnl_color = "#16a34a" if trade["net_pnl"] >= 0 else "#dc2626"
    reasons_html = "".join(f"<li>{r}</li>" for r in trade["reasons"])
    confidence_html = "".join(f"<li>{c}</li>" for c in trade["confidence_factors"])
    ss_html = ""
    if trade.get("screenshot_path") and Path(trade["screenshot_path"]).exists():
        ss_uri = Path(trade["screenshot_path"]).resolve().as_uri()
        ss_html = f"""
        <div class="section">
          <h3>Dashboard Execution Evidence</h3>
          <img src="{ss_uri}" style="width:100%; border:1px solid #cbd5e1; border-radius:6px;" />
        </div>
        """

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8" />
<style>
  @page {{ size: A4; margin: 12mm; }}
  body {{ font-family: 'Segoe UI', Arial, sans-serif; color: #0f172a; margin: 0; font-size: 11px; line-height: 1.45; }}
  .header {{ background: #0f172a; color: #f8fafc; padding: 14px 18px; border-radius: 8px; display: flex; justify-content: space-between; align-items: center; }}
  .header h1 {{ margin: 0; font-size: 17px; }}
  .header .sub {{ color: #94a3b8; font-size: 10.5px; margin-top: 3px; }}
  .pnl-box {{ background: {pnl_color}; color: white; padding: 8px 14px; border-radius: 6px; text-align: right; font-weight: bold; }}
  .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 12px; }}
  .card {{ border: 1px solid #cbd5e1; border-radius: 6px; padding: 10px 12px; background: #f8fafc; }}
  .card h3 {{ margin: 0 0 6px 0; font-size: 12px; color: #1e293b; border-bottom: 1px solid #e2e8f0; padding-bottom: 4px; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 6px; font-size: 10.5px; }}
  th, td {{ border: 1px solid #cbd5e1; padding: 5px 8px; text-align: left; }}
  th {{ background: #e2e8f0; color: #0f172a; }}
  .section {{ margin-top: 12px; border: 1px solid #cbd5e1; border-radius: 6px; padding: 10px 12px; }}
  .section h3 {{ margin: 0 0 6px 0; font-size: 12px; color: #0f172a; border-bottom: 1px solid #e2e8f0; padding-bottom: 4px; }}
  ul {{ margin: 4px 0 0 16px; padding: 0; }}
  li {{ margin-bottom: 3px; }}
</style>
</head>
<body>
  <div class="header">
    <div>
      <h1>TRADE INTELLIGENCE REPORT — {trade['contract']}</h1>
      <div class="sub">Trade ID: <b>{trade['trade_id']}</b> | Mode: <b>PAPER SIMULATOR</b> | Date: <b>{trade['date']} (IST)</b></div>
    </div>
    <div class="pnl-box">
      <div style="font-size:15px;">{trade['net_pnl_str']}</div>
      <div style="font-size:10px; opacity:0.9;">{trade['exit_reason']} ({trade['pnl_pct_str']})</div>
    </div>
  </div>

  <div class="grid">
    <div class="card">
      <h3>Entry &amp; Risk Parameters (IST)</h3>
      <table>
        <tr><th>Entry Time (IST)</th><td><b>{trade['entry_ist']}</b></td></tr>
        <tr><th>Entry Spot Price</th><td><b>₹{trade['entry_spot']:,.2f}</b></td></tr>
        <tr><th>Strike Price</th><td><b>{int(trade['strike'])} {trade['option_type']}</b></td></tr>
        <tr><th>Entry Option Premium</th><td><b>₹{trade['entry_premium']:,.2f}</b> ({trade['qty_label']})</td></tr>
        <tr><th>Stop Loss / Target</th><td>SL: ₹{trade['sl']:,.2f} | Target: ₹{trade['target']:,.2f} (1:3 R:R)</td></tr>
      </table>
    </div>
    <div class="card">
      <h3>Exit &amp; P&amp;L Breakdown (IST)</h3>
      <table>
        <tr><th>Exit Time (IST)</th><td><b>{trade['exit_ist']}</b></td></tr>
        <tr><th>Exit Spot Price</th><td><b>₹{trade['exit_spot']:,.2f}</b></td></tr>
        <tr><th>Exit Option Premium</th><td><b>₹{trade['exit_premium']:,.2f}</b></td></tr>
        <tr><th>Exit Reason</th><td><b>{trade['exit_reason']}</b></td></tr>
        <tr><th>Gross / Charges / Net</th><td>₹{trade['gross_pnl']:,.2f} / ₹{trade['charges']:,.2f} / <b style="color:{pnl_color};">{trade['net_pnl_str']}</b></td></tr>
      </table>
    </div>
  </div>

  <div class="section">
    <h3>1. Pre-Trade Market View</h3>
    <p style="margin:4px 0;">{trade['pre_trade_view']}</p>
  </div>

  <div class="grid">
    <div class="card">
      <h3>2. Why We Chose This Trade</h3>
      <ul>{reasons_html}</ul>
    </div>
    <div class="card">
      <h3>3. High-Confidence Drivers</h3>
      <ul>{confidence_html}</ul>
    </div>
  </div>

  <div class="section">
    <h3>4. Clear 15-Minute Candle Chart View (Entry, Exit &amp; Strike Levels)</h3>
    <img src="{chart_png.resolve().as_uri()}" style="width:100%; border-radius:6px;" />
  </div>

  {ss_html}
</body>
</html>"""

    html_path = TMP_DIR / f"{trade['trade_id']}.html"
    html_path.write_text(html, encoding="utf-8")

    safe_contract = trade["contract"].replace(" ", "_")
    safe_ts = trade["entry_ist"].replace(":", "-").replace(" ", "_")
    pdf_path = TRADE_PDF_DIR / f"Trade_{trade['trade_id']}_{safe_contract}_{safe_ts}.pdf"
    html_to_pdf(html_path, pdf_path)
    return pdf_path


def generate_15m_bulletin_pdf(bulletin: dict) -> Path:
    candles = filter_today_candles(
        fetch_15m_candles("NIFTY"), bulletin["date"], max_time_ist=bulletin["hhmm"]
    )
    chart_png = TMP_DIR / f"bulletin_{bulletin['hhmm'].replace(':', '')}.png"
    plot_15m_candle_chart(
        candles=candles,
        out_png=chart_png,
        title=f"NIFTY 50 Intraday 15M Chart up to {bulletin['date']} {bulletin['hhmm']} IST",
    )

    overview_html = "".join(f"<li>{item}</li>" for item in bulletin["overview_points"])
    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8" />
<style>
  @page {{ size: A4; margin: 12mm; }}
  body {{ font-family: 'Segoe UI', Arial, sans-serif; color: #0f172a; margin: 0; font-size: 11px; line-height: 1.45; }}
  .header {{ background: #0f172a; color: #f8fafc; padding: 14px 18px; border-radius: 8px; display: flex; justify-content: space-between; align-items: center; }}
  .header h1 {{ margin: 0; font-size: 16px; }}
  .header .sub {{ color: #94a3b8; font-size: 10.5px; margin-top: 3px; }}
  .badge {{ background: #1d4ed8; color: white; padding: 6px 12px; border-radius: 6px; font-weight: bold; font-size: 11px; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 10.5px; }}
  th, td {{ border: 1px solid #cbd5e1; padding: 6px 8px; text-align: left; }}
  th {{ background: #e2e8f0; color: #0f172a; }}
  .section {{ margin-top: 12px; border: 1px solid #cbd5e1; border-radius: 6px; padding: 10px 12px; background: #f8fafc; }}
  .section h3 {{ margin: 0 0 6px 0; font-size: 12px; color: #0f172a; border-bottom: 1px solid #e2e8f0; padding-bottom: 4px; }}
  ul {{ margin: 4px 0 0 16px; padding: 0; }}
  li {{ margin-bottom: 4px; }}
</style>
</head>
<body>
  <div class="header">
    <div>
      <h1>15-MINUTE MARKET STATUS SUMMARY BULLETIN</h1>
      <div class="sub">Timestamp: <b>{bulletin['date']} {bulletin['hhmm']} IST</b> | Mode: <b>PAPER SIMULATOR</b></div>
    </div>
    <div class="badge">{bulletin['decision_badge']}</div>
  </div>

  <table>
    <tr><th>NIFTY 50 Live</th><td><b>{bulletin['nifty_live']}</b></td><th>BANK NIFTY Live</th><td><b>{bulletin['banknifty_live']}</b></td></tr>
    <tr><th>15M Closed Candle (NIFTY)</th><td>{bulletin['nifty_candle']}</td><th>15M Closed Candle (BN)</th><td>{bulletin['banknifty_candle']}</td></tr>
    <tr><th>Contributors Breadth</th><td>{bulletin['breadth']}</td><th>GIFT NIFTY / VIX</th><td>{bulletin['gift_vix']}</td></tr>
    <tr><th>NIFTY Option Chain</th><td>{bulletin['nifty_oc']}</td><th>BANKNIFTY Option Chain</th><td>{bulletin['bn_oc']}</td></tr>
    <tr><th>Simulator Capital</th><td><b>{bulletin['sim_capital']}</b></td><th>Today's Net P&amp;L</th><td><b>{bulletin['today_pnl']}</b></td></tr>
  </table>

  <div class="section">
    <h3>15-Minute Market Overview &amp; Action Plan</h3>
    <ul>{overview_html}</ul>
  </div>

  <div class="section">
    <h3>Intraday 15-Minute Price Action Chart ({bulletin['hhmm']} IST)</h3>
    <img src="{chart_png.resolve().as_uri()}" style="width:100%; border-radius:6px;" />
  </div>
</body>
</html>"""

    html_path = TMP_DIR / f"bulletin_{bulletin['hhmm'].replace(':', '')}.html"
    html_path.write_text(html, encoding="utf-8")
    pdf_path = BULLETIN_PDF_DIR / f"Market_Bulletin_{bulletin['date']}_{bulletin['hhmm'].replace(':', '-')}_IST.pdf"
    html_to_pdf(html_path, pdf_path)
    return pdf_path


if __name__ == "__main__":
    trades = [
        {
            "trade_id": "oc_882403",
            "symbol": "NIFTY",
            "instrument": "NIFTY 50",
            "contract": "NIFTY 50 25900 CE",
            "date": "2026-11-25",
            "strike": 25900,
            "option_type": "CE",
            "qty_label": "1 Lot / 65 Qty",
            "entry_ist": "2026-11-25 11:04:42 IST",
            "entry_ist_hhmm": "11:00",
            "entry_spot": 25908.10,
            "entry_premium": 270.30,
            "sl": 250.30,
            "target": 330.30,
            "exit_ist": "2026-11-25 11:05:00 IST",
            "exit_ist_hhmm": "11:00",
            "exit_spot": 25924.50,
            "exit_premium": 329.80,
            "exit_reason": "TARGET",
            "gross_pnl": 3867.50,
            "charges": 92.46,
            "net_pnl": 3775.04,
            "net_pnl_str": "+₹3,775.04",
            "pnl_pct_str": "+22.0%",
            "pre_trade_view": "NIFTY gapped up above the 25,562 Central Pivot and cleared 25,805 at 10:30 IST. GIFT NIFTY (+2.11%) and BANKNIFTY breaking 64,000 signaled a strong short-covering continuation toward 25,950–26,000.",
            "reasons": [
                "10:45–11:00 15M candle closed strongly bullish at 25,878.55 (+46.15 pts), holding well above 25,850.",
                "BANKNIFTY broke above psychological 64,000 (64,022.30) simultaneously.",
                "Clean 1:3 R:R (20 pts SL / 60 pts Target) with 15-pt Auto-Trail SL."
            ],
            "confidence_factors": [
                "Option Chain PCR surged 1.07 -> 1.11 (Put OI 12.93 Cr > Call OI 11.60 Cr).",
                "Heavy Call short unwinding at 25800 CE (-15.3L/15m) and 25850 CE (-11.5L/15m).",
                "Massive Put writing at 25900 PE (+18.1L/15m) + Breadth 21 Green / 4 Red (BN +1,619 pts)."
            ],
            "screenshot_path": r"d:\AI_Trading\reports\trade_screenshots\step_168_shot_1_sim_1115_trade_log.png",
        },
        {
            "trade_id": "oc_436201",
            "symbol": "NIFTY",
            "instrument": "NIFTY 50",
            "contract": "NIFTY 50 25900 CE",
            "date": "2026-11-25",
            "strike": 25900,
            "option_type": "CE",
            "qty_label": "1 Lot / 65 Qty",
            "entry_ist": "2026-11-25 11:47:16 IST",
            "entry_ist_hhmm": "11:45",
            "entry_spot": 25944.85,
            "entry_premium": 296.60,
            "sl": 276.60,
            "target": 356.60,
            "exit_ist": "2026-11-25 11:51:00 IST",
            "exit_ist_hhmm": "11:45",
            "exit_spot": 25951.65,
            "exit_premium": 356.10,
            "exit_reason": "TARGET",
            "gross_pnl": 3867.50,
            "charges": 96.25,
            "net_pnl": 3771.25,
            "net_pnl_str": "+₹3,771.25",
            "pnl_pct_str": "+20.1%",
            "pre_trade_view": "After hitting 25,942.60 at 11:15, NIFTY consolidated cleanly above the 25,900 Put-writing floor. We stayed flat during 11:30 upper-wick chop and waited for a pullback-and-bounce confirmation.",
            "reasons": [
                "11:30–11:45 15M candle dipped into our 25,880–25,905 support zone (L: 25,898.90) and reversed to close at 25,949.50 (+35.50 pts).",
                "BANKNIFTY broke above 64,040 to close at 64,083.15 (+133.30 pts).",
                "Strict 1:3 R:R (20 pts SL / 60 pts Target) with Auto-Trail SL."
            ],
            "confidence_factors": [
                "Option Chain PCR remained bullish at 1.14 (PE OI 13.72 Cr > CE OI 12.04 Cr).",
                "25900 CE (-8.2L/15m) and 25950 CE (-4.6L/15m) unwound while 25950 PE (+9.8L/15m) and 26000 PE (+9.5L/15m) added OI.",
                "Contributors Breadth 21 Green / 4 Red (BN +1,763 pts | N50 +493.8 pts)."
            ],
            "screenshot_path": r"d:\AI_Trading\reports\trade_screenshots\step_196_shot_1_sim_1200_trade_status.png",
        },
        {
            "trade_id": "oc_145671",
            "symbol": "NIFTY",
            "instrument": "NIFTY 50",
            "contract": "NIFTY 50 25800 PE",
            "date": "2026-11-25",
            "strike": 25800,
            "option_type": "PE",
            "qty_label": "1 Lot / 65 Qty",
            "entry_ist": "2026-11-25 12:49:05 IST",
            "entry_ist_hhmm": "12:45",
            "entry_spot": 25775.65,
            "entry_premium": 239.70,
            "sl": 219.70,
            "target": 299.70,
            "exit_ist": "2026-11-25 12:56:00 IST",
            "exit_ist_hhmm": "12:45",
            "exit_spot": 25700.60,
            "exit_premium": 273.27,
            "exit_reason": "TRAILING SL (+33.57 pts)",
            "gross_pnl": 2182.05,
            "charges": 85.34,
            "net_pnl": 2096.71,
            "net_pnl_str": "+₹2,096.71",
            "pnl_pct_str": "+14.0%",
            "pre_trade_view": "After 12:00, Put writers trimmed 25900–26000 positions and NIFTY lost 25,885. We stayed flat at 12:15 & 12:30 until 25,800 Max Pain broke decisively on volume.",
            "reasons": [
                "12:30–12:45 15M candle plunged -110.75 pts (O: 25,883.10 -> C: 25,772.35, Vol: 80,453), slicing cleanly below 25,800.",
                "BANKNIFTY broke down -239.85 pts (C: 63,678.10) on heavy volume.",
                "15-pt Auto-Trail SL locked +33.57 pts profit automatically as spot fell to 25,700.60."
            ],
            "confidence_factors": [
                "Option Chain PCR dropped sharply 1.14 -> 1.02; Max Pain shifted down 25,800 -> 25,750.",
                "Heavy Put unwinding at 25800 PE (-10.6L/15m), 25850 PE (-7.2L/15m), 25900 PE (-16.0L/15m).",
                "Fresh Call writing added at 25800 CE (+5.0L/15m) + Breadth weakened to 18 Green / 7 Red."
            ],
            "screenshot_path": r"d:\AI_Trading\reports\trade_screenshots\step_243.png",
        },
    ]

    for t in trades:
        out = generate_trade_pdf(t)
        print("GENERATED TRADE PDF:", out)
