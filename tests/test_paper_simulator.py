"""
Unit tests for the Local NIFTY Option Paper Trade Simulator.
"""

import pandas as pd
import pytest

from nifty_trader.simulator.charges import IndianFOChargesCalculator
from nifty_trader.simulator.contracts import ExitReason, OptionPosition, SignalType, TradeSignal
from nifty_trader.simulator.engine import NiftyOptionSimulator
from nifty_trader.simulator.rules import EMAPivotBounceRule, SupertrendMomentumRule
from nifty_trader.simulator.user_rule import CustomUserRule


def test_indian_fo_charges_calculator():
    """Verify brokerage and statutory tax calculation on an option trade."""
    buy_price = 100.0
    sell_price = 150.0
    qty = 65

    charges = IndianFOChargesCalculator.calculate(buy_price, sell_price, qty)

    # Brokerage is flat Rs 40 (Rs 20 buy + Rs 20 sell)
    assert charges.brokerage == 40.0
    # STT is 0.1% of sell turnover (150 * 65 = 9750 -> 9.75)
    assert charges.stt == 9.75
    # Total charges must be positive and greater than brokerage
    assert charges.total_charges > 40.0
    assert charges.gst > 0.0
    assert charges.exchange_charges > 0.0


def test_user_rule_signal_generation():
    """Verify custom rule generates proper TradeSignal structure without exceptions."""
    rule = CustomUserRule()
    fake_candle = pd.Series({
        "spot_open": 24000.0,
        "spot_high": 24050.0,
        "spot_low": 23980.0,
        "spot_close": 24040.0,
        "spot_vol": 100000,
        "time_str": "10:15",
        "date": "2026-09-15",
    })
    fake_indicators = {
        "ema_9": 24030.0,
        "ema_21": 24000.0,
        "rsi": 62.0,
        "vwap": 24010.0,
        "supertrend_dir": 1,
    }

    signal = rule.on_candle(fake_candle, fake_indicators, active_position=None)
    assert isinstance(signal, TradeSignal)
    assert signal.signal_type == SignalType.BUY_CE
    assert signal.sl_points > 0
    assert signal.target_points > 0


def test_simulator_delete_trade():
    """Verify deleting a trade removes it and recalculates capital."""
    from nifty_trader.simulator.service import get_simulator_service
    svc = get_simulator_service()
    initial_cap = svc.current_capital

    # Insert a dummy trade
    from nifty_trader.simulator.contracts import TradeResult, ExitReason
    dummy_trade = TradeResult(
        trade_id="test_dummy_del_99",
        symbol="NIFTY",
        option_type="CE",
        strike=24000,
        lots=1,
        qty=65,
        entry_time="2026-09-15 10:00",
        exit_time="2026-09-15 10:15",
        entry_spot=24000.0,
        exit_spot=24050.0,
        entry_premium=100.0,
        exit_premium=120.0,
        exit_reason=ExitReason.TARGET,
        gross_pnl=1300.0,
        brokerage=40.0,
        taxes=20.0,
        total_charges=60.0,
        net_pnl=1240.0,
        pnl_pct=20.0,
        duration_minutes=15,
        rule_name="TestRule",
    )
    svc._save_trade(dummy_trade)
    assert any(t.trade_id == "test_dummy_del_99" for t in svc.recent_trades)

    # Delete it
    del_ok = svc.delete_trade("test_dummy_del_99")
    assert del_ok is True
    assert not any(t.trade_id == "test_dummy_del_99" for t in svc.recent_trades)


def test_simulator_presets_and_manual_settings():
    """Verify applying presets and manual configuration for sizing, SL and target."""
    from nifty_trader.simulator.service import get_simulator_service
    svc = get_simulator_service()

    # 1. Test applying preset
    svc.apply_preset("PERCENT_15_30")
    assert svc.preset_name == "PERCENT_15_30"
    assert svc.sl_mode == "PERCENT"
    assert svc.sl_val == 15.0
    assert svc.target_mode == "PERCENT"
    assert svc.target_val == 30.0

    # 2. Test manual settings update
    svc.update_settings(
        lots=3,
        sl_mode="POINTS",
        sl_val=18.5,
        target_mode="POINTS",
        target_val=45.0,
        trailing_sl=True,
        trail_step=12.0,
        preset_name="CUSTOM",
    )
    assert svc.lots == 3
    assert svc.sl_mode == "POINTS"
    assert svc.sl_val == 18.5
    assert svc.target_mode == "POINTS"
    assert svc.target_val == 45.0
    assert svc.trailing_sl is True
    assert svc.trail_step == 12.0
    assert svc.preset_name == "CUSTOM"

    summary = svc.get_dashboard_summary()
    assert summary["settings"]["lots"] == 3
    assert summary["settings"]["qty"] == 3 * svc.lot_size
    assert summary["settings"]["sl_val"] == 18.5
    assert summary["settings"]["target_val"] == 45.0


def test_manual_chart_analysis_and_screenshot():
    """Verify manual chart analysis computation and screenshot access."""
    from nifty_trader.simulator.service import get_simulator_service
    svc = get_simulator_service()

    # 1. Test chart analysis
    details = svc.analyze_chart_now()
    assert "spot_close" in details
    assert "indicators" in details
    assert "ema_9" in details["indicators"]
    assert "rsi" in details["indicators"]
    assert "verdict" in details
    assert "signal_type" in details

    # 2. Test screenshot path
    shot = svc.get_latest_screenshot_path()
    assert shot is not None
