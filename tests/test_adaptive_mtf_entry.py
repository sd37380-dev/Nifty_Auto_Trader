"""Tests for 1H primary bias + adaptive 5M/15M entry timeframe selection."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from nifty_trader.contracts.models import CandleObservation, NumericalObservation
from nifty_trader.simulator.service import SimulatorBackgroundService

IST = timezone(timedelta(hours=5, minutes=30))


def _candle(tf: str, o: float, h: float, l: float, c: float, mins_offset: int = 0) -> CandleObservation:
    ts = datetime(2026, 11, 26, 10, 0, tzinfo=IST) + timedelta(minutes=mins_offset)
    return CandleObservation(
        instrument="NIFTY",
        timeframe=tf,
        timestamp=ts.astimezone(timezone.utc),
        open=o,
        high=h,
        low=l,
        close=c,
        volume=10000,
    )


def _new_sim(tmp_path: Path) -> SimulatorBackgroundService:
    svc = object.__new__(SimulatorBackgroundService)
    svc.root_dir = tmp_path
    svc.data_dir = tmp_path / "data"
    svc.data_dir.mkdir(parents=True, exist_ok=True)
    svc.db_path = svc.data_dir / "sim.db"
    svc.lot_size = 65
    svc.lots = 1
    svc.active_bias_1h = "NEUTRAL"
    svc.active_entry_timeframe = "15M"
    return svc


def test_1h_bullish_bias_selects_5m_on_strong_momentum(tmp_path: Path):
    svc = _new_sim(tmp_path)
    num = NumericalObservation(
        candles_1h=[
            _candle("1H", 25500, 25550, 25490, 25540, 0),
            _candle("1H", 25540, 25610, 25530, 25600, 60),
        ],
        candles_15m=[_candle("15M", 25570, 25605, 25565, 25600, 60)],
        candles_5m=[
            _candle("5M", 25570, 25580, 25565, 25575, 45),
            _candle("5M", 25575, 25585, 25570, 25580, 50),
            _candle("5M", 25580, 25588, 25575, 25582, 55),
            _candle("5M", 25582, 25620, 25580, 25615, 60),
        ],
    )
    obs = SimpleNamespace(numerical=num)

    bias_1h = svc._determine_1h_bias(obs)
    entry_tf, reason = svc._select_adaptive_entry_timeframe(obs, bias_1h=bias_1h)

    assert bias_1h == "BULLISH"
    assert entry_tf == "5M"
    assert "5M" in reason


def test_1h_bearish_bias_falls_back_to_15m_when_5m_is_choppy(tmp_path: Path):
    svc = _new_sim(tmp_path)
    num = NumericalObservation(
        candles_1h=[
            _candle("1H", 25700, 25710, 25620, 25630, 0),
            _candle("1H", 25630, 25640, 25550, 25560, 60),
        ],
        candles_15m=[_candle("15M", 25580, 25590, 25555, 25560, 60)],
        candles_5m=[
            _candle("5M", 25565, 25585, 25555, 25570, 45),
            _candle("5M", 25570, 25590, 25560, 25575, 50),
            _candle("5M", 25575, 25585, 25565, 25572, 55),
            _candle("5M", 25568, 25574, 25564, 25570, 60),  # green small chop against bearish 1H
        ],
    )
    obs = SimpleNamespace(numerical=num)

    bias_1h = svc._determine_1h_bias(obs)
    entry_tf, _ = svc._select_adaptive_entry_timeframe(obs, bias_1h=bias_1h)

    assert bias_1h == "BEARISH"
    assert entry_tf == "15M"
