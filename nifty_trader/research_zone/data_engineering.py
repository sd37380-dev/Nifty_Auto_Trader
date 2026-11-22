"""
Data Engineering Zone for the Hermes Research & Intelligence Zone.

Implements:
1. Ingestion of raw broker data
2. Mathematical invariant validation
3. Data cleaning and deduplication
4. Normalization and UTC timestamp handling
5. Multi-timeframe generation (resampling from 1M to 5M, 15M, 1H, 1D)
6. Feature preparation (EMAs, RSI, MACD, ATR, VWAP bands, OI change, Regime tags)
7. Data quality analysis and reporting
"""

from datetime import datetime, timedelta, timezone
import logging
import math
from typing import Dict, List, Optional, Tuple

from nifty_trader.research_zone.contracts import (
    DataQualityRating,
    DataQualityReport,
    FeatureRow,
    FeatureSet,
    NormalizedBar,
)

logger = logging.getLogger(__name__)


class DataEngineeringZone:
    """
    Dedicated quantitative pipeline for validating, cleaning, resampling,
    and feature-enriching broker market data.
    """

    def validate_and_clean_bars(self, bars: List[NormalizedBar]) -> Tuple[List[NormalizedBar], int]:
        """
        Validates OHLC invariants and removes corrupted, duplicate, or zero-price bars.
        Returns: (cleaned_bars, rejected_count)
        """
        cleaned: List[NormalizedBar] = []
        seen_timestamps = set()
        rejected = 0

        # Sort chronologically first
        sorted_bars = sorted(bars, key=lambda b: b.timestamp)

        for b in sorted_bars:
            # Mathematical OHLC Invariants
            if b.open <= 0 or b.high <= 0 or b.low <= 0 or b.close <= 0:
                rejected += 1
                continue
            if b.high < b.low or b.high < b.open or b.high < b.close:
                rejected += 1
                continue
            if b.low > b.open or b.low > b.close:
                rejected += 1
                continue
            if b.volume < 0 or b.open_interest < 0:
                rejected += 1
                continue

            # Deduplication: keep latest
            if b.timestamp in seen_timestamps:
                cleaned = [c for c in cleaned if c.timestamp != b.timestamp]
            
            seen_timestamps.add(b.timestamp)
            cleaned.append(b)

        return cleaned, rejected

    def assess_data_quality(
        self,
        bars: List[NormalizedBar],
        symbol: str,
        timeframe: str,
        expected_interval_minutes: int = 15,
    ) -> DataQualityReport:
        """
        Analyzes time-continuity and data integrity.
        """
        if not bars:
            return DataQualityReport(
                symbol=symbol,
                timeframe=timeframe,
                total_bars=0,
                missing_bars_count=0,
                invalid_candles_count=0,
                completeness_percentage=0.0,
                gap_events=["No bars provided"],
                quality_rating=DataQualityRating.CRITICAL,
            )

        sorted_bars = sorted(bars, key=lambda b: b.timestamp)
        gaps: List[str] = []
        missing_count = 0

        for i in range(len(sorted_bars) - 1):
            t_curr = sorted_bars[i].timestamp
            t_next = sorted_bars[i + 1].timestamp
            diff_mins = (t_next - t_curr).total_seconds() / 60.0

            # Normal gap threshold (allow for market close / overnight gaps > 360 mins)
            if expected_interval_minutes < diff_mins <= 360:
                expected_missing = int((diff_mins / expected_interval_minutes) - 1)
                missing_count += expected_missing
                gaps.append(
                    f"Gap of {diff_mins:.0f}m between {t_curr.isoformat()} and {t_next.isoformat()} (~{expected_missing} bars)"
                )

        total = len(sorted_bars)
        completeness = max(0.0, min(100.0, round((total / max(1, total + missing_count)) * 100.0, 2)))

        if completeness >= 98.0:
            rating = DataQualityRating.EXCELLENT
        elif completeness >= 90.0:
            rating = DataQualityRating.GOOD
        elif completeness >= 75.0:
            rating = DataQualityRating.DEGRADED
        else:
            rating = DataQualityRating.CRITICAL

        return DataQualityReport(
            symbol=symbol,
            timeframe=timeframe,
            total_bars=total,
            missing_bars_count=missing_count,
            invalid_candles_count=0,
            completeness_percentage=completeness,
            gap_events=gaps[:10],
            quality_rating=rating,
        )

    def resample_bars(
        self,
        minute_bars: List[NormalizedBar],
        target_timeframe: str = "15M",
    ) -> List[NormalizedBar]:
        """
        Resamples granular 1-minute bars into higher timeframe bars (5M, 15M, 1H, 1D).
        Properly calculates OHLC, cumulative volume, final OI, and VWAP.
        """
        if not minute_bars:
            return []

        tf_upper = target_timeframe.upper()
        if tf_upper in ["5M", "5MIN"]:
            group_minutes = 5
        elif tf_upper in ["15M", "15MIN"]:
            group_minutes = 15
        elif tf_upper in ["1H", "60M"]:
            group_minutes = 60
        elif tf_upper in ["1D", "D"]:
            group_minutes = 375
        else:
            return minute_bars

        sorted_bars = sorted(minute_bars, key=lambda b: b.timestamp)
        aggregated: List[NormalizedBar] = []
        current_bucket: List[NormalizedBar] = []
        bucket_start_time: Optional[datetime] = None

        for bar in sorted_bars:
            # Calculate bucket alignment
            minute_offset = bar.timestamp.minute % group_minutes
            bar_bucket_start = bar.timestamp - timedelta(minutes=minute_offset, seconds=bar.timestamp.second, microseconds=bar.timestamp.microsecond)

            if bucket_start_time is None:
                bucket_start_time = bar_bucket_start

            if bar_bucket_start != bucket_start_time and current_bucket:
                # Close current bucket
                agg_bar = self._aggregate_bucket(current_bucket, target_timeframe, bucket_start_time)
                aggregated.append(agg_bar)
                current_bucket = []
                bucket_start_time = bar_bucket_start

            current_bucket.append(bar)

        if current_bucket and bucket_start_time:
            aggregated.append(self._aggregate_bucket(current_bucket, target_timeframe, bucket_start_time))

        return aggregated

    def resample_to_volume_bars(
        self,
        bars: List[NormalizedBar],
        target_volume: int = 10000,
        slice_overflow: bool = True,
    ):
        """
        Resamples granular bars into constant-volume candlesticks (Volume Bars).
        Closes a candle when the cumulative volume hits target_volume.
        """
        from nifty_trader.features.volume_candles import VolumeBarAggregator
        aggregator = VolumeBarAggregator(default_target_volume=target_volume)
        return aggregator.aggregate_from_normalized_bars(
            bars=bars,
            target_volume=target_volume,
            slice_overflow=slice_overflow,
        )

    def _aggregate_bucket(
        self,
        bucket: List[NormalizedBar],
        timeframe: str,
        start_time: datetime,
    ) -> NormalizedBar:
        first = bucket[0]
        last = bucket[-1]
        open_p = first.open
        high_p = max(b.high for b in bucket)
        low_p = min(b.low for b in bucket)
        close_p = last.close
        total_vol = sum(b.volume for b in bucket)
        final_oi = last.open_interest

        # Compute volume-weighted average price
        pv_sum = sum(b.vwap * b.volume for b in bucket if b.volume > 0)
        vwap = round(pv_sum / max(1, total_vol), 2) if total_vol > 0 else round((open_p + high_p + low_p + close_p) / 4.0, 2)
        trades = sum(b.trades_count for b in bucket)

        return NormalizedBar(
            symbol=first.symbol,
            timeframe=timeframe,
            timestamp=start_time,
            open=round(open_p, 2),
            high=round(high_p, 2),
            low=round(low_p, 2),
            close=round(close_p, 2),
            volume=total_vol,
            open_interest=final_oi,
            vwap=vwap,
            trades_count=trades,
        )

    def calculate_features(
        self,
        bars: List[NormalizedBar],
        symbol: str = "NIFTY",
        timeframe: str = "15M",
    ) -> FeatureSet:
        """Alias for prepare_feature_set."""
        return self.prepare_feature_set(bars, symbol=symbol, timeframe=timeframe)

    def _make_fallback_feature_row(self, bar: Optional[NormalizedBar] = None) -> FeatureRow:
        """Constructs a basic FeatureRow when indicators cannot be computed."""
        now = datetime.now(timezone.utc)
        if not bar:
            return FeatureRow(timestamp=now, close=24000.0, regime_tag="UNDEFINED")
        return FeatureRow(
            timestamp=bar.timestamp,
            close=bar.close,
            vwap=bar.vwap,
            regime_tag="UNDEFINED",
        )

    def prepare_feature_set(
        self,
        bars: List[NormalizedBar],
        symbol: str = "NIFTY",
        timeframe: str = "15M",
    ) -> FeatureSet:
        """
        Computes multi-period indicators, moving averages, volatility bands,
        and market regime classifications.
        """
        if not bars:
            return FeatureSet(symbol=symbol, timeframe=timeframe, rows=[], total_bars=0)

        sorted_bars = sorted(bars, key=lambda b: b.timestamp)
        closes = [b.close for b in sorted_bars]
        volumes = [b.volume for b in sorted_bars]
        highs = [b.high for b in sorted_bars]
        lows = [b.low for b in sorted_bars]
        ois = [b.open_interest for b in sorted_bars]

        # 1. EMAs
        ema_9 = self._calculate_ema(closes, 9)
        ema_20 = self._calculate_ema(closes, 20)
        ema_50 = self._calculate_ema(closes, 50)
        ema_200 = self._calculate_ema(closes, 200)

        # 2. RSI (14)
        rsi_14 = self._calculate_rsi(closes, 14)

        # 3. MACD (12, 26, 9)
        macd_line, macd_signal, macd_hist = self._calculate_macd(closes, 12, 26, 9)

        # 4. ATR (14)
        atr_14 = self._calculate_atr(highs, lows, closes, 14)

        # 5. Volume 20 SMA ratio
        vol_sma_20 = self._calculate_sma(volumes, 20)

        # 6. VWAP and Bands
        vwap_vals, vwap_std = self._calculate_vwap_series(sorted_bars)

        rows: List[FeatureRow] = []
        for i in range(len(sorted_bars)):
            b = sorted_bars[i]
            c = closes[i]

            vol_ratio = round(b.volume / max(1.0, vol_sma_20[i]), 2) if vol_sma_20[i] else 1.0

            # OI change pct from previous bar
            oi_change = 0.0
            if i > 0 and ois[i - 1] > 0:
                oi_change = round(((ois[i] - ois[i - 1]) / ois[i - 1]) * 100.0, 2)

            # Determine regime tag
            regime = "UNDEFINED"
            e20 = ema_20[i]
            e50 = ema_50[i]
            r = rsi_14[i]
            if e20 and e50:
                if c > e20 > e50 and (r or 50) > 55:
                    regime = "STRONG_BULLISH_TREND"
                elif c < e20 < e50 and (r or 50) < 45:
                    regime = "STRONG_BEARISH_TREND"
                elif abs(c - e20) / e20 < 0.003:
                    regime = "CONSOLIDATION_MEAN_REVERSION"
                else:
                    regime = "RANGING"

            v_std = vwap_std[i] or (c * 0.005)
            v_val = vwap_vals[i] or b.vwap

            rows.append(FeatureRow(
                timestamp=b.timestamp,
                close=b.close,
                ema_9=round(ema_9[i], 2) if ema_9[i] else None,
                ema_20=round(ema_20[i], 2) if ema_20[i] else None,
                ema_50=round(ema_50[i], 2) if ema_50[i] else None,
                ema_200=round(ema_200[i], 2) if ema_200[i] else None,
                rsi_14=round(rsi_14[i], 1) if rsi_14[i] else None,
                macd=round(macd_line[i], 2) if macd_line[i] else None,
                macd_signal=round(macd_signal[i], 2) if macd_signal[i] else None,
                macd_hist=round(macd_hist[i], 2) if macd_hist[i] else None,
                atr_14=round(atr_14[i], 2) if atr_14[i] else None,
                vwap=round(v_val, 2),
                vwap_std_upper=round(v_val + (1.5 * v_std), 2),
                vwap_std_lower=round(v_val - (1.5 * v_std), 2),
                volume_ratio_20=vol_ratio,
                oi_change_pct=oi_change,
                regime_tag=regime,
            ))

        return FeatureSet(
            symbol=symbol,
            timeframe=timeframe,
            rows=rows,
            total_bars=len(rows),
        )

    # --------------------------------------------------------------------------
    # Mathematical Indicator Helpers
    # --------------------------------------------------------------------------

    def _calculate_sma(self, data: List[float], period: int) -> List[Optional[float]]:
        res: List[Optional[float]] = []
        for i in range(len(data)):
            if i < period - 1:
                res.append(None)
            else:
                window = data[i - period + 1 : i + 1]
                res.append(sum(window) / period)
        return res

    def _calculate_ema(self, data: List[float], period: int) -> List[Optional[float]]:
        res: List[Optional[float]] = []
        if len(data) < period:
            return [None] * len(data)

        multiplier = 2.0 / (period + 1)
        # Seed with initial SMA
        initial_sma = sum(data[:period]) / period
        for _ in range(period - 1):
            res.append(None)
        res.append(initial_sma)

        current_ema = initial_sma
        for val in data[period:]:
            current_ema = (val - current_ema) * multiplier + current_ema
            res.append(current_ema)
        return res

    def _calculate_rsi(self, data: List[float], period: int = 14) -> List[Optional[float]]:
        res: List[Optional[float]] = []
        if len(data) <= period:
            return [None] * len(data)

        gains = []
        losses = []
        for i in range(1, len(data)):
            diff = data[i] - data[i - 1]
            gains.append(max(0.0, diff))
            losses.append(max(0.0, -diff))

        res.append(None)  # first index has no diff
        for _ in range(period - 1):
            res.append(None)

        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period

        if avg_loss == 0:
            res.append(100.0)
        else:
            rs = avg_gain / avg_loss
            res.append(100.0 - (100.0 / (1.0 + rs)))

        for i in range(period, len(gains)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period
            if avg_loss == 0:
                res.append(100.0)
            else:
                rs = avg_gain / avg_loss
                res.append(100.0 - (100.0 / (1.0 + rs)))
        return res

    def _calculate_macd(
        self,
        data: List[float],
        fast_period: int = 12,
        slow_period: int = 26,
        signal_period: int = 9,
    ) -> Tuple[List[Optional[float]], List[Optional[float]], List[Optional[float]]]:
        fast_ema = self._calculate_ema(data, fast_period)
        slow_ema = self._calculate_ema(data, slow_period)

        macd_line: List[Optional[float]] = []
        valid_macd_vals: List[float] = []
        for f, s in zip(fast_ema, slow_ema):
            if f is not None and s is not None:
                diff = f - s
                macd_line.append(diff)
                valid_macd_vals.append(diff)
            else:
                macd_line.append(None)

        # Compute signal line over valid macd values
        signal_valid = self._calculate_ema(valid_macd_vals, signal_period)
        signal_line: List[Optional[float]] = []
        macd_hist: List[Optional[float]] = []

        val_idx = 0
        for m in macd_line:
            if m is None:
                signal_line.append(None)
                macd_hist.append(None)
            else:
                s = signal_valid[val_idx]
                signal_line.append(s)
                macd_hist.append((m - s) if s is not None else None)
                val_idx += 1

        return macd_line, signal_line, macd_hist

    def _calculate_atr(
        self,
        highs: List[float],
        lows: List[float],
        closes: List[float],
        period: int = 14,
    ) -> List[Optional[float]]:
        if len(closes) <= period:
            return [None] * len(closes)

        tr: List[float] = [highs[0] - lows[0]]
        for i in range(1, len(closes)):
            h = highs[i]
            l = lows[i]
            prev_c = closes[i - 1]
            true_range = max(h - l, abs(h - prev_c), abs(l - prev_c))
            tr.append(true_range)

        atr_series = self._calculate_sma(tr, period)
        return atr_series

    def _calculate_vwap_series(self, bars: List[NormalizedBar]) -> Tuple[List[float], List[float]]:
        vwap_vals: List[float] = []
        vwap_stds: List[float] = []
        cum_pv = 0.0
        cum_vol = 0.0
        prices_in_session: List[float] = []

        last_date = None
        for b in bars:
            curr_date = b.timestamp.date()
            if last_date != curr_date:
                # Reset intraday session
                cum_pv = 0.0
                cum_vol = 0.0
                prices_in_session = []
                last_date = curr_date

            typical_price = (b.high + b.low + b.close) / 3.0
            vol = max(1, b.volume)
            cum_pv += typical_price * vol
            cum_vol += vol
            prices_in_session.append(typical_price)

            current_vwap = cum_pv / cum_vol
            vwap_vals.append(current_vwap)

            # Session variance
            variance = sum((p - current_vwap) ** 2 for p in prices_in_session) / len(prices_in_session)
            vwap_stds.append(math.sqrt(variance))

        return vwap_vals, vwap_stds
