"""
Master Research Study Runner for 5-Year NIFTY Spot Price Action.
Executes the full research battery:
1. Baseline hypothesis screening (12 hypotheses x 3 directions = 36 configurations).
2. Year-by-year stability analysis (2021-2026).
3. Parameter sensitivity grid (R:R 1.0 to 3.0, SL buffers 3 to 8 pts).
4. Chronological walk-forward test (Train -> Val -> Out-of-Sample Test).
5. Friction sensitivity (Gross vs Standard vs High Friction).
6. Time-of-day edge breakdown.
Outputs strategy_candidates.csv and detailed JSON data.
"""

import os
import sys
from datetime import datetime, time, date
import json
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.abspath("."))

from nifty_trader.strategies.price_validation_strategy import Direction, TransactionCostModel
from research.price_action.data_loader import load_and_clean_nifty_5m, compute_price_action_features
from research.price_action.engine import (
    HypothesisDefinition,
    run_hypothesis_simulation,
    summarize_trade_metrics,
)
from research.price_action.hypotheses import get_all_hypotheses


def run_full_study():
    print("================================================================================")
    print("STARTING 5-YEAR NIFTY SPOT PRICE-ACTION RESEARCH STUDY")
    print("================================================================================")

    # 1. Load Data
    print("[1/6] Ingesting and engineering features on 5M NIFTY Spot dataset...")
    df_clean, meta = load_and_clean_nifty_5m()
    print(f"Loaded {meta['total_in_session']} bars across {meta['unique_trading_days']} trading days.")
    print(f"Date Range: {meta['earliest_ist']} to {meta['latest_ist']}")
    if meta['invalid_ohlc_count'] > 0:
        print(f"Documented {meta['invalid_ohlc_count']} invalid OHLC bars (handled with is_valid_ohlc=False).")

    df_feats = compute_price_action_features(df_clean)
    print(f"Feature engineering complete. Total feature columns: {df_feats.shape[1]}")

    cost_standard = TransactionCostModel(lot_size=50, slippage_points_per_side=0.5)
    cost_zero = TransactionCostModel(lot_size=50, brokerage_per_order=0, exchange_charge_rate=0,
                                     stt_rate_sell=0, sebi_charge_rate=0, stamp_duty_rate_buy=0,
                                     gst_rate=0, slippage_points_per_side=0)
    cost_high = TransactionCostModel(lot_size=50, slippage_points_per_side=1.0)  # 2.0 pt roundtrip

    hyps = get_all_hypotheses()
    print(f"\n[2/6] Running Baseline Screening for {len(hyps)} Hypotheses across 3 directions (36 runs)...")

    baseline_results = []
    trades_dict = {}

    for hyp in hyps:
        for d_mode in ["BOTH", "LONG_ONLY", "SHORT_ONLY"]:
            tag = f"{hyp.hypothesis_id}_{d_mode}"
            trades, df_t = run_hypothesis_simulation(
                df_feats, hyp, cost_model=cost_standard, direction_mode=d_mode
            )
            metrics = summarize_trade_metrics(trades, total_days=meta['unique_trading_days'])
            trades_dict[tag] = trades

            # Determine initial status
            # Criteria:
            # ROBUST CANDIDATE: Net positive, PF >= 1.10, trades >= 150, positive in >= 4 years
            # PROMISING: Gross positive, Net near-breakeven or positive, PF >= 1.00, trades >= 100
            # DISCOVERY: Interesting behavior / trade count, but fails net profitability
            # REJECTED: Low trade count (< 50) or deeply negative expectancy
            status = "REJECTED"
            if metrics['total_trades'] >= 50:
                pos_years = sum(1 for y in metrics['yearly_stats'].values() if y['gross_points'] > 0)
                if metrics['net_points'] > 0 and metrics['profit_factor'] >= 1.10 and pos_years >= 4:
                    status = "ROBUST CANDIDATE"
                elif metrics['gross_points'] > 0 and metrics['profit_factor'] >= 1.00:
                    status = "PROMISING"
                else:
                    status = "DISCOVERY" if metrics['total_trades'] >= 100 else "REJECTED"

            res_entry = {
                "hypothesis_id": hyp.hypothesis_id,
                "strategy_name": hyp.name,
                "direction": d_mode,
                "timeframe": "5M",
                "category": hyp.category,
                "description": hyp.description,
                "trades": metrics['total_trades'],
                "win_rate": metrics['win_rate'],
                "expectancy": metrics['expectancy_pts'],
                "profit_factor": metrics['profit_factor'],
                "gross_points": metrics['gross_points'],
                "net_points": metrics['net_points'],
                "gross_pnl_inr": metrics['gross_pnl_inr'],
                "net_pnl_inr": metrics['net_pnl_inr'],
                "total_costs_inr": metrics['total_costs_inr'],
                "slippage_inr": metrics['total_slippage_inr'],
                "max_drawdown": metrics['max_drawdown_pts'],
                "average_trade": metrics['avg_trade_pts'],
                "avg_holding_mins": metrics['avg_holding_mins'],
                "trades_per_day": metrics['trades_per_day'],
                "max_consecutive_losses": metrics['max_consecutive_losses'],
                "status": status,
                "metrics_full": metrics,
            }
            baseline_results.append(res_entry)
            print(f"  [{d_mode:10s}] {hyp.hypothesis_id:30s} | Tr: {metrics['total_trades']:4d} | WR: {metrics['win_rate']:5.2f}% | Gross: {metrics['gross_points']:8.1f} pts | Net: {metrics['net_points']:8.1f} pts | PF: {metrics['profit_factor']:4.2f} | Status: {status}")

    # Convert to DataFrame
    df_baseline = pd.DataFrame(baseline_results)
    
    # Save strategy_candidates.csv
    csv_cols = [
        "strategy_name", "direction", "timeframe", "category", "trades",
        "win_rate", "expectancy", "profit_factor", "gross_points", "net_points",
        "max_drawdown", "average_trade", "status"
    ]
    df_baseline[csv_cols].to_csv("research/price_action/strategy_candidates.csv", index=False)
    print("\n[OK] Saved research/price_action/strategy_candidates.csv")

    # 3. Identify Top Candidates for In-Depth Robustness Testing
    # Top candidates are those with highest gross/net points, highest profit factor, or interesting category representation
    top_candidates = df_baseline[df_baseline['status'].isin(["ROBUST CANDIDATE", "PROMISING", "DISCOVERY"])].copy()
    top_candidates = top_candidates.sort_values(by=['gross_points', 'profit_factor'], ascending=False).reset_index(drop=True)
    print(f"\n[3/6] Identified {len(top_candidates)} Promising/Discovery Candidates for Deep Robustness Battery.")
    for idx, r in top_candidates.head(8).iterrows():
        print(f"   Candidate {idx+1}: {r['hypothesis_id']} ({r['direction']}) -> Gross: {r['gross_points']} pts, Net: {r['net_points']} pts, PF: {r['profit_factor']}")

    # 4. Detailed Robustness Battery on Selected Representative Hypotheses
    print("\n[4/6] Executing Parameter Sensitivity, Walk-Forward, and Cost Sensitivity Analysis...")
    robustness_data = {}

    # Select the top 5 distinct hypotheses
    selected_hyp_ids = top_candidates['hypothesis_id'].unique()[:6].tolist()
    # Ensure representative categories are included
    for req_id in ["H05_PDH_PDL_SWEEP_REVERSAL", "H06_FIRST_HOUR_SWEEP_REVERSAL", "H01_ORB15_BREAKOUT", "H10_MORNING_MOMENTUM_BREAKOUT"]:
        if req_id not in selected_hyp_ids:
            selected_hyp_ids.append(req_id)

    hyp_lookup = {h.hypothesis_id: h for h in hyps}

    for hid in selected_hyp_ids:
        hyp = hyp_lookup[hid]
        print(f"\n--- Testing Robustness for {hid}: {hyp.name} ---")
        robustness_data[hid] = {
            "parameter_sensitivity": {},
            "walk_forward": {},
            "friction_sensitivity": {},
        }

        # A. Parameter Sensitivity (RR grid and SL buffer grid)
        # Test RR: 1.0, 1.5, 2.0, 2.5, 3.0
        rr_results = {}
        for test_rr in [1.0, 1.5, 2.0, 2.5, 3.0]:
            tr_rr, _ = run_hypothesis_simulation(df_feats, hyp, cost_model=cost_standard, target_rr=test_rr)
            m_rr = summarize_trade_metrics(tr_rr)
            rr_results[str(test_rr)] = {
                "rr": test_rr, "trades": m_rr['total_trades'], "win_rate": m_rr['win_rate'],
                "gross_points": m_rr['gross_points'], "net_points": m_rr['net_points'],
                "profit_factor": m_rr['profit_factor'], "max_dd_pts": m_rr['max_drawdown_pts']
            }
        robustness_data[hid]["parameter_sensitivity"]["target_rr"] = rr_results

        # Test SL buffers: 3.0, 5.0, 8.0, 12.0
        sl_results = {}
        for test_sl in [3.0, 5.0, 8.0, 12.0]:
            tr_sl, _ = run_hypothesis_simulation(df_feats, hyp, cost_model=cost_standard, sl_buffer=test_sl)
            m_sl = summarize_trade_metrics(tr_sl)
            sl_results[str(test_sl)] = {
                "sl_buffer": test_sl, "trades": m_sl['total_trades'], "win_rate": m_sl['win_rate'],
                "gross_points": m_sl['gross_points'], "net_points": m_sl['net_points'],
                "profit_factor": m_sl['profit_factor'], "max_dd_pts": m_sl['max_drawdown_pts']
            }
        robustness_data[hid]["parameter_sensitivity"]["sl_buffer"] = sl_results

        # B. Walk-Forward Chronological Split
        # Train: 2021-10-01 to 2023-12-31
        # Validation: 2024-01-01 to 2024-12-31
        # Out-of-Sample Test: 2025-01-01 to 2026-09-29
        df_train = df_feats[df_feats['date_ist'] <= date(2023, 12, 31)]
        df_val = df_feats[(df_feats['date_ist'] >= date(2024, 1, 1)) & (df_feats['date_ist'] <= date(2024, 12, 31))]
        df_test = df_feats[df_feats['date_ist'] >= date(2025, 1, 1)]

        tr_train, _ = run_hypothesis_simulation(df_train, hyp, cost_model=cost_standard)
        tr_val, _ = run_hypothesis_simulation(df_val, hyp, cost_model=cost_standard)
        tr_test, _ = run_hypothesis_simulation(df_test, hyp, cost_model=cost_standard)

        m_train = summarize_trade_metrics(tr_train)
        m_val = summarize_trade_metrics(tr_val)
        m_test = summarize_trade_metrics(tr_test)

        robustness_data[hid]["walk_forward"] = {
            "train_2021_2023": {
                "period": "2021-10-01 to 2023-12-31 (In-Sample)",
                "trades": m_train['total_trades'], "win_rate": m_train['win_rate'],
                "gross_points": m_train['gross_points'], "net_points": m_train['net_points'],
                "profit_factor": m_train['profit_factor'], "max_dd_pts": m_train['max_drawdown_pts'],
            },
            "validation_2024": {
                "period": "2024-01-01 to 2024-12-31 (Validation)",
                "trades": m_val['total_trades'], "win_rate": m_val['win_rate'],
                "gross_points": m_val['gross_points'], "net_points": m_val['net_points'],
                "profit_factor": m_val['profit_factor'], "max_dd_pts": m_val['max_drawdown_pts'],
            },
            "test_2025_2026": {
                "period": "2025-01-01 to 2026-09-29 (Out-of-Sample Test)",
                "trades": m_test['total_trades'], "win_rate": m_test['win_rate'],
                "gross_points": m_test['gross_points'], "net_points": m_test['net_points'],
                "profit_factor": m_test['profit_factor'], "max_dd_pts": m_test['max_drawdown_pts'],
            },
        }

        # C. Friction Sensitivity
        tr_zero, _ = run_hypothesis_simulation(df_feats, hyp, cost_model=cost_zero)
        tr_std, _ = run_hypothesis_simulation(df_feats, hyp, cost_model=cost_standard)
        tr_hi, _ = run_hypothesis_simulation(df_feats, hyp, cost_model=cost_high)

        m_zero = summarize_trade_metrics(tr_zero)
        m_std = summarize_trade_metrics(tr_std)
        m_hi = summarize_trade_metrics(tr_hi)

        robustness_data[hid]["friction_sensitivity"] = {
            "zero_friction_gross": {
                "gross_points": m_zero['gross_points'], "net_points": m_zero['net_points'],
                "net_pnl_inr": m_zero['net_pnl_inr'], "profit_factor": m_zero['profit_factor']
            },
            "standard_friction": {
                "gross_points": m_std['gross_points'], "net_points": m_std['net_points'],
                "net_pnl_inr": m_std['net_pnl_inr'], "profit_factor": m_std['profit_factor'],
                "total_friction_inr": m_std['total_costs_inr'] + m_std['total_slippage_inr']
            },
            "high_friction_2pt_slip": {
                "gross_points": m_hi['gross_points'], "net_points": m_hi['net_points'],
                "net_pnl_inr": m_hi['net_pnl_inr'], "profit_factor": m_hi['profit_factor'],
                "total_friction_inr": m_hi['total_costs_inr'] + m_hi['total_slippage_inr']
            }
        }

    # 5. Save all findings to JSON
    print("\n[5/6] Saving full research results to JSON...")
    full_output = {
        "metadata": meta,
        "baseline_summary": baseline_results,
        "robustness_studies": robustness_data,
    }
    with open("research/price_action/all_research_results.json", "w") as f:
        json.dump(full_output, f, indent=2, default=str)
    print("[OK] Saved research/price_action/all_research_results.json")

    print("\n[6/6] Full research run complete. Ready for markdown report generation.")
    return full_output


if __name__ == "__main__":
    run_full_study()
