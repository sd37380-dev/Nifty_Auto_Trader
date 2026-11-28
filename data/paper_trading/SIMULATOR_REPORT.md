# NIFTY Option Paper Trade Simulator — Audit Report

* **Last Observation Time:** Awaiting first 15M TradingView chart cycle
* **Current Chart Verdict:** `IDLE (Listening to Autonomous 15M cycle)`
* **Total 15M Cycles Analyzed:** 0
* **Active Strategy Rule:** `My_Custom_Strategy`
* **Active Risk Preset:** `CUSTOM`
* **Trade Order Size:** `3 Lot (195 Qty)`
* **Stop Loss Setting:** `18.5 pts`
* **Profit Target / Exit Level:** `45.0 pts`
* **Trailing Stop-Loss:** `Enabled (12.0 pts step)`
* **Initial Capital:** Rs. 100,000.00
* **Current Simulated Capital:** Rs. 133,483.30
* **Realized Net P&L:** Rs. +33,483.30

## 1. Performance Summary

| Performance Metric | Recorded Value |
| :--- | :--- |
| **Total Executed Trades** | 7 |
| **Winning Trades / Losing Trades** | 6 / 1 |
| **Empirical Win Rate** | 85.7% |
| **Gross P&L (Option Premiums)** | Rs. +34,084.70 |
| **Total Statutory Taxes & Brokerage** | Rs. 601.40 |
| **REAL NET P&L (After All Charges)** | **Rs. +33,483.30** |
| **Return on Capital** | +33.48% |

## 2. Executed Trade Audit Log

| Trade ID | Option Contract | Entry Time | Exit Time | Buy Price | Exit Price | Exit Reason | Gross P&L | Charges | Net P&L | ROI % |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `oc_602117` | NIFTY 25700 PE | 2026-11-27 07:13:22 UTC | 2026-11-27 09:15 | Rs. 162.65 | Rs. 177.63 | `STOP_LOSS` | Rs. +973.70 | Rs. 72.27 | **Rs. +901.43** | +9.2% |
| `oc_272060` | NIFTY 25900 CE | 2026-11-26 05:17:52 UTC | 2026-11-26 05:21 | Rs. 234.10 | Rs. 293.60 | `TARGET` | Rs. +3,867.50 | Rs. 87.21 | **Rs. +3,780.29** | +25.4% |
| `oc_145671` | NIFTY 25800 PE | 2026-11-25 07:19:05 UTC | 2026-11-25 07:26 | Rs. 239.70 | Rs. 273.27 | `STOP_LOSS` | Rs. +2,182.05 | Rs. 85.34 | **Rs. +2,096.71** | +14.0% |
| `oc_436201` | NIFTY 25900 CE | 2026-11-25 06:17:16 UTC | 2026-11-25 06:21 | Rs. 296.60 | Rs. 356.10 | `TARGET` | Rs. +3,867.50 | Rs. 96.25 | **Rs. +3,771.25** | +20.1% |
| `oc_882403` | NIFTY 25900 CE | 2026-11-25 05:34:42 UTC | 2026-11-25 05:35 | Rs. 270.30 | Rs. 329.80 | `TARGET` | Rs. +3,867.50 | Rs. 92.46 | **Rs. +3,775.04** | +22.0% |
| `oc_689058` | NIFTY 25400 CE | 2026-11-23 16:51:29 UTC | 2026-09-29 15:15 | Rs. 135.00 | Rs. 114.50 | `STOP_LOSS` | Rs. -1,332.50 | Rs. 64.59 | **Rs. -1,397.09** | -15.2% |
| `oc_957023` | NIFTY 25650 PE | 2026-11-27 09:15:57 UTC | 2026-09-25 10:30 | Rs. 159.75 | Rs. 477.58 | `STOP_LOSS` | Rs. +20,658.95 | Rs. 103.28 | **Rs. +20,555.67** | +198.9% |
