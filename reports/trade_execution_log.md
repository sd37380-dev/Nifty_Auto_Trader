# Autonomous Paper Trade Execution Log — 2026-11-25

**Mode:** Paper Simulator Only (Live Broker DISABLED)  
**Risk Guards:** 1 Lot Max (65 NIFTY / 30 BANKNIFTY) | Min 1:3 R:R | Max ₹2,000 Daily Loss | 09:25–15:15 IST  
**Policy:** Auto-execute on confirmed 15M + Option Chain confluence; log every entry, SL trail, and exit.

---

## Pre-Auto Signals Observed
- **10:30 IST** | `BUY CE` Signal (`25800 CE` @ `₹246.10` / `25750 CE` @ `₹273.60`, Spot `25,805.30`) — *Not executed (prior approval-only mode). Reached Spot `25,850.05` (`25800 CE` `₹272.85`) by 10:47 IST.*

---

## Executed Trades

> **Screenshots Directory:** [`reports/trade_screenshots/`](file:///d:/AI_Trading/reports/trade_screenshots/)

### Trade #1 — `oc_882403` (CLOSED — TARGET HIT)
- **Entry Timestamp:** `2026-11-25 11:04:42 IST` *(DB/UI showed `05:34:42 UTC`)*
- **Exit Timestamp:** `2026-11-25 11:05:00 IST` *(DB/UI showed `05:35 UTC`)*
- **Screenshots:** [Modal](file:///d:/AI_Trading/reports/trade_screenshots/step_156_shot_1_trade_modal_25900ce_60tgt.png) | [Active](file:///d:/AI_Trading/reports/trade_screenshots/step_158_shot_1_simulator_active_position_card.png) | [TARGET Exit](file:///d:/AI_Trading/reports/trade_screenshots/step_168_shot_1_sim_1115_trade_log.png)
- **Mode:** Paper Simulator (`Live Broker: DISABLED`)
- **Contract:** `NIFTY 50 25900 CE` (01-DEC-2026) — **BUY 1 Lot (65 Qty)**
- **Margin Used:** `₹17,569.50`
- **Entry Premium:** `₹270.30` (Spot at entry: `₹25,908.10`)
- **Exit Premium:** `₹329.80` (**Exit Reason:** `TARGET`)
- **Stop Loss / Target:** `₹250.30` / `₹330.30` (`1:3 R:R`)
- **Trade P&L:** Gross `+₹3,867.50` | Taxes & Brokerage `₹92.46` | **Net P&L: `+₹3,775.04 (+22.0%)`**
- **Updated Simulator Capital:** `₹1,02,377.95` (Cumulative Net P&L: `+₹2,377.95`)
- **Confluence / Reason:**
  - `10:45–11:00` 15M candle closed bullish at `25,878.55` (+46.15 pts), breaking `25,850`.
  - BANKNIFTY broke `64,000` (`64,022.30`), GIFT NIFTY `26,033.50`.
  - Option Chain PCR surged `1.07 → 1.11`, `25800 CE` unwound `-15.3L/15m`, `25850 CE` unwound `-11.5L/15m`, and `25900 PE` added `+18.1L/15m`.
  - Contributors breadth `21 Green / 4 Red` (`BN: +1,619.2 pts | N50: +446.3 pts`).
- **Status:** `CLOSED (TARGET)`

### Trade #2 — `oc_436201` (CLOSED — TARGET HIT)
- **Entry Timestamp:** `2026-11-25 11:47:16 IST` *(DB/UI showed `06:17:16 UTC`)*
- **Exit Timestamp:** `2026-11-25 11:51:00 IST` *(DB/UI showed `06:21 UTC`)*
- **Screenshots:** [Modal](file:///d:/AI_Trading/reports/trade_screenshots/step_188_shot_1_trade_modal_25900ce_1145.png) | [Active](file:///d:/AI_Trading/reports/trade_screenshots/step_188_shot_2_sim_1145_position.png) | [TARGET Exit](file:///d:/AI_Trading/reports/trade_screenshots/step_196_shot_1_sim_1200_trade_status.png)
- **Mode:** Paper Simulator (`Live Broker: DISABLED`)
- **Contract:** `NIFTY 50 25900 CE` (01-DEC-2026) — **BUY 1 Lot (65 Qty)**
- **Margin Used:** `₹19,279.00`
- **Entry Premium:** `₹296.60` (Spot at entry: `₹25,944.85–25,948.65`)
- **Exit Premium:** `₹356.10` (**Exit Reason:** `TARGET`)
- **Stop Loss / Target:** `₹276.60` / `₹356.60` (`1:3 R:R`)
- **Trade P&L:** Gross `+₹3,867.50` | Taxes & Brokerage `₹96.25` | **Net P&L: `+₹3,771.25 (+20.1%)`**
- **Updated Simulator Capital:** `₹1,06,149.20` (Cumulative Net P&L: `+₹6,149.20`)
- **Confluence / Reason:**
  - `11:30–11:45` NIFTY dipped to `25,898.90` and reversed strongly to close at `25,949.50` (+35.50 pts).
  - BANKNIFTY broke above `64,040` and closed at `64,083.15` (+133.30 pts).
  - Option Chain PCR `1.14`; `25900 CE` unwound `-8.2L/15m`, `25950 CE` unwound `-4.6L/15m`, while `25950 PE` (`+9.8L/15m`) and `26000 PE` (`+9.5L/15m`) saw strong Put writing.
  - Contributors `21 Green / 4 Red` (`BN: +1,763.4 pts | N50: +493.8 pts`).
- **Status:** `CLOSED (TARGET)`

### Trade #3 — `oc_145671` (CLOSED — TRAILING SL PROFIT)
- **Entry Timestamp:** `2026-11-25 12:49:05 IST` *(DB/UI showed `07:19:05 UTC`)*
- **Exit Timestamp:** `2026-11-25 12:56:00 IST` *(DB/UI showed `07:26 UTC`)*
- **Screenshots:** [Modal](file:///d:/AI_Trading/reports/trade_screenshots/step_234_shot_1_trade_modal_25800pe_1245.png) | [Active](file:///d:/AI_Trading/reports/trade_screenshots/step_237_shot_1_sim_1245_position.png) | [Trailing SL Exit](file:///d:/AI_Trading/reports/trade_screenshots/step_243.png)
- **Mode:** Paper Simulator (`Live Broker: DISABLED`)
- **Contract:** `NIFTY 50 25800 PE` (01-DEC-2026) — **BUY 1 Lot (65 Qty)**
- **Margin Used:** `₹15,580.50`
- **Entry Premium:** `₹239.70` (Spot at entry: `₹25,775.65`)
- **Exit Premium:** `₹273.27` (**Exit Reason:** `TRAILING SL` — 15-pt Auto-Trail locked `+33.57 pts`)
- **Initial SL / Target:** `₹219.70` / `₹299.70` (`1:3 R:R`)
- **Trade P&L:** Gross `+₹2,182.05` | Taxes & Brokerage `₹85.34` | **Net P&L: `+₹2,096.71 (+14.0%)`**
- **Updated Simulator Capital:** `₹1,08,245.91` (Cumulative Net P&L: `+₹8,245.91` | Today's Net: `+₹9,643.00`, 3W/0L)
- **Confluence / Reason:**
  - `12:30–12:45` NIFTY broke down `-110.75 pts` (`O: 25,883.10 -> C: 25,772.35`), slicing cleanly below `25,800`.
  - BANKNIFTY dropped `-239.85 pts` (`C: 63,678.10`, live `63,616.55`).
  - Option Chain PCR plunged `1.14 → 1.02`, Max Pain dropped `25,800 → 25,750`.
  - Heavy Put unwinding (`25800 PE -10.6L/15m`, `25850 PE -7.2L/15m`, `25900 PE -16.0L/15m`) + Call writing (`25800 CE +5.0L/15m`).
- **Status:** `CLOSED (TRAILING SL +₹2,096.71)`

---

## Daily Summary (2026-11-25)
- **NIFTY Trades:** `3 / 3` (Daily Risk Engine Cap Reached) — **3 Wins / 0 Losses (100%)**
- **Today's Net P&L:** **`+₹9,643.00`** (`oc_882403` `+₹3,775.04` + `oc_436201` `+₹3,771.25` + `oc_145671` `+₹2,096.71`)
- **Simulator Capital:** **`₹1,08,245.91`**

