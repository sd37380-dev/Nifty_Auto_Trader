# Autonomous Trading System Protocol & Global Model Directive

This document defines the strict, non-negotiable operational protocol for this workspace (`d:\AI_Trading`).
**Every Antigravity model (Gemini, Claude, GPT, Flash, Pro, etc.) operating in this workspace must adhere to this protocol without deviation.**

---

## ⚡ The Primary Keyword Trigger: `!trade`

Whenever the user sends the command `!trade` (or says "start trading", "start", "trade", "execute"):

1. **Zero Explanations Needed**: Do NOT ask the user for confirmation, strategy parameters, indicator settings, strike criteria, or risk rules. Everything is pre-configured and locked.
2. **Immediate Execution**:
   - **Step 1: Verify / Launch Dashboard Server**:
     Ensure the dashboard server on port 8080 is running. If not running, start it in the background as a daemon:
     ```powershell
     d:\AI_Trading\nifty-autonomous-trader\venv\Scripts\python.exe d:\AI_Trading\nifty-autonomous-trader\start_server.py
     ```
   - **Step 2: Launch Autonomous Price Action Trader**:
     Start the autonomous trading engine in the background:
     ```powershell
     d:\AI_Trading\nifty-autonomous-trader\venv\Scripts\python.exe d:\AI_Trading\nifty-autonomous-trader\scripts\autonomous_price_action_trader.py --mode live
     ```
3. **User Status Confirmation**:
   Respond immediately to the user with a concise status card confirming:
   - Dashboard: Live at `http://127.0.0.1:8080`
   - Engine: Active in Live Scanning Mode
   - Decision Engine: 3-Pillar Institutional Architecture Active
   - Setups Active: Setup A (Trend Continuation 1:3 R:R) & Setup B (Wall Reversal Fade 1:7 R:R)
   - Contract Selection: STRICTLY 1 Lot ITM (In-The-Money) on Next Weekly Expiry
   - Capital Protection: ₹2,000 Daily Loss Cap, 15-pt Trailing SL
   - Reporting: Live archival into `reports/<YYYY-MM-DD>/` with rich analytical breakdowns, reasons, statuses, candlestick charts, and strategic conclusions.

---

## 🏛 The 3-Pillar Institutional Trading Architecture

Every trade signal must satisfy all 3 Pillars before order placement:

### Pillar 1: Direction (Who is in control?)
- **1H / 15M Higher-Timeframe Trend**:
  - Price structure relative to EMA 9 and EMA 20.
  - RULE: Never buy Calls in a 1H downtrend; never buy Puts in a 1H uptrend.
- **Option Chain PCR (Put-Call Ratio)**:
  - Bullish: PCR ≥ 1.05 (Heavy Put writing provides a rising floor).
  - Bearish: PCR ≤ 0.90 (Heavy Call writing provides a descending ceiling).
- **Heavyweight Breadth & Contributors**:
  - Top Index Drivers (RELIANCE, HDFC Bank, ICICI Bank) must align with the trade direction.
  - Advance/Decline market breadth must support the move.
- **Sister Index Correlation**:
  - NIFTY 50 and BANKNIFTY price action must not diverge in opposition.

### Pillar 2: Location (Wholesale Value)
- **Pivots & CPR**:
  - Entering at high-probability value zones: Central Pivot (PP), CPR (Central Pivot Range), or S1/R1.
  - RULE: Avoid buying into Max OI Resistance Walls / Support Floors.
- **Volume Profile (POC)**:
  - Longs take place above session Point of Control (POC); Shorts take place below session POC.

### Pillar 3: Trigger & Execution (Timing & Risk)
- **5-Minute Confirmation Candle**:
  - Completed 5M candle closing in the direction of the trade with volume surge (≥ 1.0x - 1.2x of 20-period SMA).
- **Mandatory Contract Moneyness: Always In-The-Money (ITM)**:
  - **Calls (CE)**: Exactly 1 strike below ATM (`Strike < Spot`, Delta ~0.60 to 0.70). High intrinsic value, lower theta decay, fast delta response.
  - **Puts (PE)**: Exactly 1 strike above ATM (`Strike > Spot`, Delta ~ -0.60 to -0.70).
  - NEVER trade Out-Of-The-Money (OTM) or At-The-Money (ATM) lottery tickets.
- **Mandatory Expiry: Always Next Weekly Expiry**:
  - Automatically queries live NSE Option Chain API and selects the next upcoming weekly expiry (e.g. `08-Dec-2026`).
  - Completely eliminates 0-DTE same-week expiry theta burn and rapid extrinsic evaporation.
- **Position Sizing**: Strictly **1 Lot** per trade. Never scale up beyond 1 Lot.

---

## 🎯 Two Active Setups

### Setup A: Trend Continuation (1:3 Risk-to-Reward)
- **Trigger**: Breakout or pullback continuation aligned with the 1H trend, holding above/below Central Pivot & POC.
- **Stop Loss**: 20 index points.
- **Target**: 60 index points (**1:3.0 R:R**).
- **Trailing Stop**: 15 index points trail step.

### Setup B: Wall Reversal / Fade the Wall (1:7 Risk-to-Reward)
- **Concept**: Institutional option writers heavily defend their highest Open Interest (OI) strikes. When spot reaches an extreme wall, institutions aggressively reject price.
- **Trigger**:
  - At **Max Call OI Wall**: Spot tests the wall + Call OI actively builds up + 5M rejection candle closes with ≥50% upper wick $\rightarrow$ **Buy 1 Lot ITM PE** targeting the session POC.
  - At **Max Put OI Floor**: Spot tests the floor + Put OI actively builds up + 5M rejection candle closes with ≥50% lower wick $\rightarrow$ **Buy 1 Lot ITM CE** targeting the session POC.
- **Stop Loss**: 15 index points (Tight SL just behind the institutional wall).
- **Target**: **105 index points (1:7.0 R:R)**.
- **Trailing Stop**: 15 index points trail step.

---

## 📊 Comprehensive Reporting Standards (5M, 15M & Trade Execution)

Every generated report must be comprehensive, detailed, and formatted as follows:
1. **Components Analyzed & Quantitative Metrics**:
   - 1H / 15M Higher-Timeframe Trend & EMAs
   - Option Chain PCR, Max Call OI Wall & Max Put OI Floor
   - Daily Pivots (PP, CPR, S1/R1, S2/R2, PDH, PDL)
   - Volume Profile Session Point of Control (POC, VAH, VAL)
   - Heavyweight Drivers & Advances/Declines Breadth
   - Inter-Market Sister Index (Nifty vs BankNifty, GIFT, VIX)
   - News Sentiment & Headline Catalyst Impact
   - Capital & Daily ₹2,000 Loss Headroom
2. **Explicit Status & In-Depth Reason**:
   - Every analyzed factor must display its Status (`PASS`, `BULLISH`, `BEARISH`, `DEFENDED`, `VALUE ZONE`) and the exact institutional reason why it matters.
3. **High-Resolution Intraday Candlestick Chart**:
   - Dark-navy theme chart with candlestick price action, spot level markers, strike reference lines, and volume sub-bars.
4. **Executive Summary & Tactical Conclusion**:
   - Detailed synthesis summarizing market diagnosis, active setup readiness (Setup A 1:3 vs Setup B 1:7), and the exact trading directive for the next interval.

---

## 🔔 Execution & Notification Invariants

Upon every trade entry and exit:
1. **Audible Host Chime**: Execute `winsound.Beep` chime sequence on the host Windows machine to alert the trader.
2. **Telegram Broadcast**: Instant alert featuring 3-Pillar summary checklist card, contract strike, ITM tag, next expiry, setup type, entry/exit price, and P&L.
3. **Date-Partitioned Archival**:
   All outputs must strictly be written to `d:\AI_Trading\reports/<YYYY-MM-DD>/`:
   - `5m_reports/` $\rightarrow$ 5-minute Market Status Bulletins (PDF).
   - `15m_reports/` $\rightarrow$ 15-minute Market Status Bulletins (PDF, HTML, MD).
   - `trade_reports/` $\rightarrow$ Trade Execution Intelligence Reports (PDF).
4. **Daily Capital Protection**:
   - Maximum daily loss ceiling strictly capped at **₹2,000**.
   - If daily P&L reaches -₹2,000, all trading is halted for the rest of the day.
