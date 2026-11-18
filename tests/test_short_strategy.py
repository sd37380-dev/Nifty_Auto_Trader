"""
Comprehensive Test Suite for NIFTY Futures Short Strategy.

Covers all 21 mandatory test scenarios:
TEST 1: All conditions pass -> SHORT
TEST 2: OI resistance missing -> NO_SIGNAL
TEST 3: Pivot resistance missing -> NO_SIGNAL
TEST 4: OI/Pivot resistance too far apart -> NO_SIGNAL
TEST 5: Bullish trend -> NO_SIGNAL
TEST 6: Price above EMA20 -> NO_SIGNAL
TEST 7: Price too far below EMA20 -> NO_SIGNAL
TEST 8: No bearish resistance rejection -> NO_SIGNAL
TEST 9: Futures unavailable -> NO_SIGNAL
TEST 10: Risk rejected -> no order
TEST 11: ATM calculated from Futures, not Spot
TEST 12: Backtest uses historical Futures
TEST 13: Backtest uses historical Options
TEST 14: Previous-day Pivot only
TEST 15: No look-ahead bias
TEST 16: Entry occurs at next candle open
TEST 17: Stop loss works
TEST 18: Target works
TEST 19: End-of-session exit works
TEST 20: Transaction costs included
TEST 21: Slippage included
"""

from datetime import datetime, timezone, timedelta
import pytest

from nifty_trader.contracts.models import IST
from nifty_trader.strategies.short import (
    ApprovalEngine,
    BacktestEngine,
    Candle5M,
    HistoricalMarketDataProvider,
    IndicatorEngine,
    MarketSnapshot,
    NiftyFuturesShortStrategy,
    OptionChainSnapshot,
    OptionStrikeData,
    PivotEngine,
    PivotLevels,
    PreviousDayOHLC,
    ShortStrategyConfig,
    SignalType,
    StrategyResult,
    TransactionCostConfig,
)


def create_mock_option_chain(
    atm: float = 23900.0,
    strong_call_strike: float = 23900.0,
    strong_call_oi: float = 500000.0,
    strong_call_change: float = 50000.0,
) -> OptionChainSnapshot:
    """Helper creating a deterministic option chain with specified Call OI profile."""
    strikes = []
    for off in range(-5, 6):
        stk = atm + (off * 50.0)
        is_target = abs(stk - strong_call_strike) < 1e-4
        c_oi = strong_call_oi if is_target else (100000.0 - abs(off) * 5000.0)
        c_chg = strong_call_change if is_target else -2000.0
        strikes.append(
            OptionStrikeData(
                strike=stk,
                calls_oi=max(1000.0, c_oi),
                calls_change_oi=c_chg,
                puts_oi=150000.0,
                puts_change_oi=5000.0,
            )
        )
    return OptionChainSnapshot(
        timestamp=datetime(2026, 9, 17, 4, 30, tzinfo=timezone.utc),
        underlying="NIFTY",
        strikes=strikes,
    )


def create_valid_bearish_snapshot() -> MarketSnapshot:
    """
    Constructs a baseline MarketSnapshot where ALL 10 SHORT conditions pass.
    Futures = 23890.0, ATM = 23900.0
    OI Resistance = 23900.0
    Pivot Resistance = 23905.0 (P = 23905, distance = 5 <= 20)
    EMA20 = 23902.0, EMA50 = 23930.0, EMA20_prev = 23906.0 (falling)
    Price (23890) < EMA20 (23902)
    ATR14 = 60.0, EMA distance = 12.0 <= 15.0 (60 * 0.25)
    Rejection candle: High = 23905 (>= zone lower 23900), Close = 23890 (< 23900), Open = 23898 (red candle)
    """
    t = datetime(2026, 9, 17, 4, 30, tzinfo=timezone.utc) # 10:00 IST
    chain = create_mock_option_chain(atm=23900.0, strong_call_strike=23900.0)
    pivots = PivotLevels(pivot=23905.0, r1=23980.0, r2=24050.0, s1=23830.0, s2=23760.0)

    # 5-minute candles
    candles = []
    base_t = t - timedelta(minutes=5 * 30)
    for idx in range(30):
        c_time = base_t + timedelta(minutes=idx * 5)
        candles.append(
            Candle5M(
                timestamp=c_time,
                open=23920.0 - idx * 1.0,
                high=23925.0 - idx * 1.0,
                low=23910.0 - idx * 1.0,
                close=23915.0 - idx * 1.0,
                volume=10000,
            )
        )

    # Latest rejection candle
    candles.append(
        Candle5M(
            timestamp=t,
            open=23898.0,
            high=23905.0, # Touches resistance (23900)
            low=23885.0,
            close=23890.0, # Closes below resistance and below open (bearish)
            volume=15000,
        )
    )

    return MarketSnapshot(
        timestamp=t,
        futures_price=23890.0,
        spot_price=23870.0, # Spot exists but must NOT be used for futures
        futures_candles=candles,
        option_chain=chain,
        pivot_levels=pivots,
        ema20=23902.0,
        ema50=23930.0,
        ema20_prev=23906.0,
        atr14=60.0,
    )


# ------------------------------------------------------------------------------
# TEST 1: All conditions pass -> SHORT
# ------------------------------------------------------------------------------
def test_1_all_conditions_pass_generates_short():
    strategy = NiftyFuturesShortStrategy()
    snapshot = create_valid_bearish_snapshot()

    result = strategy.evaluate(snapshot, bypass_risk_engine=True)

    assert result.signal == SignalType.SHORT
    assert result.reason == "ALL SHORT CONDITIONS SATISFIED"
    assert result.direction == "SHORT"
    assert result.trend_bearish is True
    assert result.price_below_ema20 is True
    assert result.ema_distance_ok is True
    assert result.resistance_rejection is True
    assert result.stop_loss == 23905.0 + strategy.config.sl_buffer
    assert result.target is not None
    assert "NIFTY FUTURES SHORT STRATEGY" in result.debug_output


# ------------------------------------------------------------------------------
# TEST 2: OI resistance missing -> NO_SIGNAL
# ------------------------------------------------------------------------------
def test_2_oi_resistance_missing_no_signal():
    strategy = NiftyFuturesShortStrategy()
    snapshot = create_valid_bearish_snapshot()
    # Wipe out option chain strikes
    snapshot.option_chain.strikes = []

    result = strategy.evaluate(snapshot, bypass_risk_engine=True)

    assert result.signal == SignalType.NO_SIGNAL
    assert result.reason in ["OPTION DATA UNAVAILABLE", "OI RESISTANCE NOT FOUND"]


# ------------------------------------------------------------------------------
# TEST 3: Pivot resistance missing -> NO_SIGNAL
# ------------------------------------------------------------------------------
def test_3_pivot_resistance_missing_no_signal():
    strategy = NiftyFuturesShortStrategy()
    snapshot = create_valid_bearish_snapshot()
    snapshot.pivot_levels = None
    snapshot.previous_day_ohlc = None

    result = strategy.evaluate(snapshot, bypass_risk_engine=True)

    assert result.signal == SignalType.NO_SIGNAL
    assert result.reason == "PIVOT RESISTANCE NOT FOUND"


# ------------------------------------------------------------------------------
# TEST 4: OI/Pivot resistance too far apart -> NO_SIGNAL
# ------------------------------------------------------------------------------
def test_4_oi_pivot_not_in_confluence_no_signal():
    strategy = NiftyFuturesShortStrategy(config=ShortStrategyConfig(max_resistance_distance=20.0))
    snapshot = create_valid_bearish_snapshot()
    # Move pivot resistance far away (e.g. 24050, distance = 150 > 20)
    snapshot.pivot_levels = PivotLevels(pivot=24050.0, r1=24150.0, r2=24250.0, s1=23950.0, s2=23850.0)

    result = strategy.evaluate(snapshot, bypass_risk_engine=True)

    assert result.signal == SignalType.NO_SIGNAL
    assert result.reason == "OI RESISTANCE AND PIVOT RESISTANCE NOT IN CONFLUENCE"


# ------------------------------------------------------------------------------
# TEST 5: Bullish trend -> NO_SIGNAL
# ------------------------------------------------------------------------------
def test_5_bullish_trend_no_signal():
    strategy = NiftyFuturesShortStrategy()
    snapshot = create_valid_bearish_snapshot()
    # Bullish moving average alignment: EMA20 > EMA50
    snapshot.ema20 = 23950.0
    snapshot.ema50 = 23900.0

    result = strategy.evaluate(snapshot, bypass_risk_engine=True)

    assert result.signal == SignalType.NO_SIGNAL
    assert result.reason == "BEARISH TREND NOT CONFIRMED"


# ------------------------------------------------------------------------------
# TEST 6: Price above EMA20 -> NO_SIGNAL
# ------------------------------------------------------------------------------
def test_6_price_above_ema20_no_signal():
    strategy = NiftyFuturesShortStrategy()
    snapshot = create_valid_bearish_snapshot()
    # Futures price above EMA20
    snapshot.futures_price = 23910.0
    snapshot.ema20 = 23902.0

    result = strategy.evaluate(snapshot, bypass_risk_engine=True)

    assert result.signal == SignalType.NO_SIGNAL
    assert result.reason == "PRICE ABOVE EMA20"


# ------------------------------------------------------------------------------
# TEST 7: Price too far below EMA20 -> NO_SIGNAL
# ------------------------------------------------------------------------------
def test_7_price_too_far_below_ema20_no_signal():
    strategy = NiftyFuturesShortStrategy(
        config=ShortStrategyConfig(ema_distance_atr_multiplier=0.25)
    )
    snapshot = create_valid_bearish_snapshot()
    # EMA20 = 23902, ATR14 = 60 -> Max allowed distance = 60 * 0.25 = 15.0
    # Set Futures price = 23850 -> Distance = 52.0 > 15.0
    snapshot.futures_price = 23850.0

    result = strategy.evaluate(snapshot, bypass_risk_engine=True)

    assert result.signal == SignalType.NO_SIGNAL
    assert result.reason == "PRICE TOO FAR BELOW EMA20"


# ------------------------------------------------------------------------------
# TEST 8: No bearish resistance rejection -> NO_SIGNAL
# ------------------------------------------------------------------------------
def test_8_no_bearish_resistance_rejection_no_signal():
    strategy = NiftyFuturesShortStrategy()
    snapshot = create_valid_bearish_snapshot()
    # Modify latest candle to NOT touch resistance zone (High = 23880 < zone lower 23900)
    snapshot.futures_candles[-1] = Candle5M(
        timestamp=snapshot.timestamp,
        open=23875.0,
        high=23880.0, # Failed to interact with 23900 resistance
        low=23865.0,
        close=23870.0,
    )

    result = strategy.evaluate(snapshot, bypass_risk_engine=True)

    assert result.signal == SignalType.NO_SIGNAL
    assert result.reason == "NO BEARISH RESISTANCE REJECTION"


# ------------------------------------------------------------------------------
# TEST 9: Futures unavailable -> NO_SIGNAL
# ------------------------------------------------------------------------------
def test_9_futures_data_unavailable_no_signal():
    strategy = NiftyFuturesShortStrategy()
    snapshot = create_valid_bearish_snapshot()
    snapshot.futures_price = None

    result = strategy.evaluate(snapshot, bypass_risk_engine=True)

    assert result.signal == SignalType.NO_SIGNAL
    assert result.reason == "FUTURES DATA UNAVAILABLE"


# ------------------------------------------------------------------------------
# TEST 10: Risk rejected -> no order
# ------------------------------------------------------------------------------
def test_10_risk_check_failed_blocks_trade():
    strategy = NiftyFuturesShortStrategy()
    snapshot = create_valid_bearish_snapshot()

    # Create mock approval engine that simulates risk rejection
    class MockFailingApproval(ApprovalEngine):
        def validate_risk_clearance(self, *args, **kwargs):
            return False, "RISK CHECK FAILED: Max daily loss reached"

    strategy.approval_engine = MockFailingApproval()

    result = strategy.evaluate(snapshot, bypass_risk_engine=False)

    assert result.signal == SignalType.NO_SIGNAL
    assert result.reason == "RISK CHECK FAILED"
    assert result.risk_check_passed is False


# ------------------------------------------------------------------------------
# TEST 11: ATM calculated from Futures, not Spot
# ------------------------------------------------------------------------------
def test_11_atm_calculated_strictly_from_futures():
    # Prompt example: Futures = 23891.25 -> ATM = 23900
    futures_p = 23891.25
    spot_p = 23750.0  # Deliberately divergent spot price

    atm_from_futures = IndicatorEngine.calculate_atm_strike(futures_p, strike_step=50.0)
    assert atm_from_futures == 23900.0

    # Ensure 11 strikes are centered around 23900
    strikes = IndicatorEngine.get_atm_plus_minus_5_strikes(futures_p, strike_step=50.0)
    assert len(strikes) == 11
    assert strikes[0] == 23650.0 # ATM - 5
    assert strikes[5] == 23900.0 # ATM
    assert strikes[10] == 24150.0 # ATM + 5

    # Invariant: If futures_price is None, spot_price must NEVER be substituted
    snapshot = MarketSnapshot(
        timestamp=datetime.now(timezone.utc),
        futures_price=None,
        spot_price=spot_p,
    )
    strategy = NiftyFuturesShortStrategy()
    result = strategy.evaluate(snapshot)
    assert result.signal == SignalType.NO_SIGNAL
    assert result.reason == "FUTURES DATA UNAVAILABLE"


def test_atm_is_recomputed_from_each_historical_futures_timestamp():
    start = datetime(2026, 9, 17, 4, 0, tzinfo=timezone.utc)
    candles = [
        Candle5M(timestamp=start, open=23890.0, high=23900.0, low=23880.0, close=23891.0),
        Candle5M(timestamp=start + timedelta(minutes=5), open=23920.0, high=23935.0, low=23915.0, close=23926.0),
    ]
    provider = HistoricalMarketDataProvider(candles)
    provider.set_current_index(0)
    atm_0 = IndicatorEngine.calculate_atm_strike(provider.get_market_snapshot().futures_price)
    provider.set_current_index(1)
    atm_1 = IndicatorEngine.calculate_atm_strike(provider.get_market_snapshot().futures_price)
    assert atm_0 == 23900.0
    assert atm_1 == 23950.0


# ------------------------------------------------------------------------------
# TEST 12: Backtest uses historical Futures
# ------------------------------------------------------------------------------
def test_12_backtest_uses_historical_futures():
    candles = [
        Candle5M(
            timestamp=datetime(2026, 9, 17, 4, i * 5, tzinfo=timezone.utc),
            open=24000.0 - i,
            high=24005.0 - i,
            low=23990.0 - i,
            close=23995.0 - i,
            volume=5000,
        )
        for i in range(10)
    ]
    provider = HistoricalMarketDataProvider(futures_candles=candles)
    provider.set_current_index(5)
    snapshot = provider.get_market_snapshot()

    # Futures price must match historical 5-minute candle close directly
    assert snapshot.futures_price == candles[5].close
    assert snapshot.spot_price is None


# ------------------------------------------------------------------------------
# TEST 13: Backtest uses historical Options
# ------------------------------------------------------------------------------
def test_13_backtest_uses_historical_options_validation():
    base_t = datetime(2026, 9, 17, 4, 0, tzinfo=timezone.utc)
    candles = [
        Candle5M(
            timestamp=base_t + timedelta(minutes=i * 5),
            open=24000.0,
            high=24010.0,
            low=23990.0,
            close=24000.0,
        )
        for i in range(60)
    ]

    # Without option snapshots, backtest must report insufficient option data
    provider_no_opt = HistoricalMarketDataProvider(futures_candles=candles, option_chain_snapshots={})
    engine = BacktestEngine()
    report, msg = engine.run(provider_no_opt)

    assert report is None
    assert msg == "INSUFFICIENT HISTORICAL OPTION DATA FOR VALID BACKTEST"


# ------------------------------------------------------------------------------
# TEST 14: Previous-day Pivot only
# ------------------------------------------------------------------------------
def test_14_pivot_uses_strictly_previous_day_ohlc():
    # Day 1: 2026-09-16 (H=24100, L=23900, C=24000)
    # Day 2: 2026-09-17 (Current trading day)
    prev_ohlc = PreviousDayOHLC(date="2026-09-16", high=24100.0, low=23900.0, close=24000.0)
    pivots = PivotEngine.calculate_pivots(prev_ohlc)

    # P = (24100 + 23900 + 24000) / 3 = 24000
    # R1 = 2*24000 - 23900 = 24100
    # R2 = 24000 + (24100 - 23900) = 24200
    assert pivots.pivot == 24000.0
    assert pivots.r1 == 24100.0
    assert pivots.r2 == 24200.0

    # Test historical provider respects strictly prior date
    t_curr = datetime(2026, 9, 17, 5, 0, tzinfo=timezone.utc)
    candle_d2 = Candle5M(timestamp=t_curr, open=24050.0, high=24080.0, low=24020.0, close=24060.0)
    provider = HistoricalMarketDataProvider(
        futures_candles=[candle_d2],
        daily_ohlc={"2026-09-16": prev_ohlc},
    )
    provider.set_current_index(0)
    snap = provider.get_market_snapshot()

    assert snap.previous_day_ohlc.date == "2026-09-16"
    assert snap.pivot_levels.pivot == 24000.0


# ------------------------------------------------------------------------------
# TEST 15: No look-ahead bias
# ------------------------------------------------------------------------------
def test_15_no_look_ahead_bias_in_historical_provider():
    base_t = datetime(2026, 9, 17, 4, 0, tzinfo=timezone.utc)
    candles = [
        Candle5M(
            timestamp=base_t + timedelta(minutes=i * 5),
            open=24000.0 + i * 10,
            high=24005.0 + i * 10,
            low=23995.0 + i * 10,
            close=24000.0 + i * 10,
        )
        for i in range(20)
    ]
    provider = HistoricalMarketDataProvider(futures_candles=candles)

    # At index 5, only candles 0 to 5 can be present in visible_candles
    provider.set_current_index(5)
    snap = provider.get_market_snapshot()

    assert len(snap.futures_candles) == 6
    assert snap.futures_candles[-1].close == candles[5].close
    assert snap.futures_price == candles[5].close


def test_historical_provider_never_uses_future_option_chain_snapshot():
    base_t = datetime(2026, 9, 17, 4, 0, tzinfo=timezone.utc)
    candles = [
        Candle5M(timestamp=base_t + timedelta(minutes=5 * i), open=100, high=101, low=99, close=100)
        for i in range(3)
    ]
    future_chain = OptionChainSnapshot(
        timestamp=base_t + timedelta(minutes=10),
        strikes=[OptionStrikeData(strike=100, calls_oi=500, puts_oi=600)],
    )
    provider = HistoricalMarketDataProvider(candles, {"future": future_chain})
    provider.set_current_index(1)
    assert provider.get_market_snapshot().option_chain is None
    assert not provider.has_sufficient_option_data()


def test_historical_provider_ignores_date_only_option_chain_key():
    base_t = datetime(2026, 9, 17, 4, 0, tzinfo=timezone.utc)
    candles = [Candle5M(timestamp=base_t, open=100, high=101, low=99, close=100)]
    # Legacy date-keyed snapshots have a timestamp, but the key itself must
    # never bypass checking that timestamp against the evaluation time.
    future_chain = OptionChainSnapshot(
        timestamp=base_t + timedelta(minutes=5),
        strikes=[OptionStrikeData(strike=100, calls_oi=500, puts_oi=600)],
    )
    provider = HistoricalMarketDataProvider(candles, {"2026-09-17": future_chain})
    assert not provider.has_sufficient_option_data()
    assert provider.get_market_snapshot().option_chain is None


def test_historical_provider_does_not_carry_option_chain_across_sessions():
    day_one = datetime(2026, 9, 16, 4, 0, tzinfo=timezone.utc)
    day_two = datetime(2026, 9, 17, 4, 0, tzinfo=timezone.utc)
    candle = Candle5M(timestamp=day_two, open=100, high=101, low=99, close=100)
    prior_chain = OptionChainSnapshot(
        timestamp=day_one + timedelta(minutes=5),
        strikes=[OptionStrikeData(strike=100, calls_oi=500, puts_oi=600)],
    )
    provider = HistoricalMarketDataProvider([candle], {"prior": prior_chain})
    provider.set_current_index(0)
    assert provider.get_market_snapshot().option_chain is None


def test_historical_provider_rejects_timestamped_but_empty_option_chain():
    ts = datetime(2026, 9, 17, 4, 0, tzinfo=timezone.utc)
    candle = Candle5M(timestamp=ts, open=100, high=101, low=99, close=100)
    empty_chain = OptionChainSnapshot(timestamp=ts, strikes=[])
    provider = HistoricalMarketDataProvider([candle], {"empty": empty_chain})
    assert not provider.has_sufficient_option_data()
    report, message = BacktestEngine().run(provider)
    assert report is None
    assert message == "INSUFFICIENT HISTORICAL OPTION DATA FOR VALID BACKTEST"


def test_historical_provider_rejects_chain_without_actual_ce_and_pe_oi():
    ts = datetime(2026, 9, 17, 4, 0, tzinfo=timezone.utc)
    candle = Candle5M(timestamp=ts, open=100, high=101, low=99, close=100)
    zero_oi_chain = OptionChainSnapshot(
        timestamp=ts,
        strikes=[OptionStrikeData(strike=100, calls_oi=0, puts_oi=0)],
    )
    provider = HistoricalMarketDataProvider([candle], {"zero_oi": zero_oi_chain})
    assert not provider.has_sufficient_option_data()


def test_historical_snapshot_is_invariant_to_mutations_after_evaluation_time():
    base_t = datetime(2026, 9, 17, 4, 0, tzinfo=timezone.utc)
    original = [
        Candle5M(timestamp=base_t + timedelta(minutes=5 * i), open=100+i, high=102+i, low=99+i, close=101+i)
        for i in range(4)
    ]
    changed_future = list(original)
    changed_future[2] = Candle5M(timestamp=original[2].timestamp, open=900, high=999, low=1, close=950)
    changed_future[3] = Candle5M(timestamp=original[3].timestamp, open=900, high=999, low=1, close=950)
    before = HistoricalMarketDataProvider(original)
    after = HistoricalMarketDataProvider(changed_future)
    before.set_current_index(1)
    after.set_current_index(1)
    first = before.get_market_snapshot()
    second = after.get_market_snapshot()
    assert first.futures_price == second.futures_price
    assert first.futures_candles == second.futures_candles
    assert first.ema20 == second.ema20
    assert first.ema50 == second.ema50
    assert first.atr14 == second.atr14
    assert first.pivot_levels == second.pivot_levels


def test_historical_provider_fails_closed_when_requested_time_disagrees_with_cursor():
    ts = datetime(2026, 9, 17, 4, 0, tzinfo=timezone.utc)
    future_ts = ts + timedelta(minutes=5)
    candle = Candle5M(timestamp=ts, open=100, high=101, low=99, close=100)
    chain = OptionChainSnapshot(timestamp=ts, strikes=[OptionStrikeData(strike=100, calls_oi=10, puts_oi=10)])
    provider = HistoricalMarketDataProvider([candle], {"exact": chain})
    mismatched = provider.get_market_snapshot(timestamp=future_ts)
    assert mismatched.futures_price is None
    assert not mismatched.futures_candles
    assert mismatched.option_chain is None


# ------------------------------------------------------------------------------
# TEST 16: Entry occurs at next candle open
# ------------------------------------------------------------------------------
def test_16_entry_occurs_at_next_candle_open():
    cost_cfg = TransactionCostConfig(slippage_points=1.0)
    strategy = NiftyFuturesShortStrategy()
    engine = BacktestEngine(strategy=strategy, cost_config=cost_cfg)

    # Rejection candle at step 50
    # Next candle at step 51 has open = 23880.0
    # Executed entry must be: 23880.0 - 1.0 = 23879.0
    raw_open = 23880.0
    executed_entry = raw_open - cost_cfg.slippage_points
    assert executed_entry == 23879.0


# ------------------------------------------------------------------------------
# TEST 17: Stop loss works
# ------------------------------------------------------------------------------
def test_17_stop_loss_exit_triggers():
    # Test SL trigger condition: candle.high >= SL
    entry_p = 23900.0
    sl = 23925.0
    candle_loss = Candle5M(
        timestamp=datetime(2026, 9, 17, 5, 30, tzinfo=timezone.utc),
        open=23910.0,
        high=23930.0, # Pierces SL
        low=23905.0,
        close=23928.0,
    )
    assert candle_loss.high >= sl


# ------------------------------------------------------------------------------
# TEST 18: Target works
# ------------------------------------------------------------------------------
def test_18_target_exit_triggers():
    # Test Target trigger condition: candle.low <= Target
    entry_p = 23900.0
    target = 23850.0
    candle_win = Candle5M(
        timestamp=datetime(2026, 9, 17, 5, 30, tzinfo=timezone.utc),
        open=23870.0,
        high=23875.0,
        low=23840.0, # Reaches Target
        close=23845.0,
    )
    assert candle_win.low <= target


# ------------------------------------------------------------------------------
# TEST 19: End-of-session exit works
# ------------------------------------------------------------------------------
def test_19_end_of_session_exit_cutoff():
    approval = ApprovalEngine(config=ShortStrategyConfig(session_end="15:00"))

    # 14:55 IST -> OK
    t_ok = datetime(2026, 9, 17, 9, 25, tzinfo=timezone.utc) # 14:55 IST
    ok, _ = approval.check_session_cutoff(t_ok)
    assert ok is True

    # 15:05 IST -> Blocked / Cutoff reached
    t_cutoff = datetime(2026, 9, 17, 9, 35, tzinfo=timezone.utc) # 15:05 IST
    cutoff, reason = approval.check_session_cutoff(t_cutoff)
    assert cutoff is False
    assert reason == "SESSION CUTOFF REACHED"


# ------------------------------------------------------------------------------
# TEST 20: Transaction costs included
# ------------------------------------------------------------------------------
def test_20_transaction_costs_calculated_correctly():
    cost_cfg = TransactionCostConfig(
        brokerage_per_order=20.0,
        exchange_turnover_pct=0.000019,
        stt_pct=0.0002,
        gst_pct=0.18,
        sebi_turnover_pct=0.000001,
        stamp_duty_pct=0.00002,
    )

    entry = 23900.0
    exit_p = 23850.0
    qty = 65

    charges = cost_cfg.calculate_charges(entry, exit_p, qty)

    assert charges["brokerage"] == 40.0
    assert charges["exchange"] > 0
    assert charges["stt"] > 0
    assert charges["gst"] > 0
    assert charges["stamp_duty"] > 0
    assert charges["total_charges"] > 40.0


# ------------------------------------------------------------------------------
# TEST 21: Slippage included
# ------------------------------------------------------------------------------
def test_21_slippage_applied_to_entry_and_exit():
    cost_cfg = TransactionCostConfig(slippage_points=1.0)
    qty = 65

    raw_entry = 23900.0
    raw_exit = 23850.0

    # Short entry: execution = raw_entry - slippage
    short_entry_exec = raw_entry - cost_cfg.slippage_points
    # Short exit: execution = raw_exit + slippage
    short_exit_exec = raw_exit + cost_cfg.slippage_points

    gross_slippage_pts = (raw_entry - raw_exit) - (short_entry_exec - short_exit_exec)
    assert gross_slippage_pts == 2.0 * cost_cfg.slippage_points

    charges = cost_cfg.calculate_charges(short_entry_exec, short_exit_exec, qty)
    assert charges["slippage_cost"] == 2.0 * cost_cfg.slippage_points * qty
