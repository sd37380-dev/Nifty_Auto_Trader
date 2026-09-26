"""
Unified Market Observation Builder.

Transforms multi-source perception outputs (numerical candles, TradingView observations,
Sensibull option-chain data, and operator steering directives) into the immutable,
traceable canonical UnifiedMarketObservation contract.
"""

from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional
import uuid

from nifty_trader.browser.models import BrowserObservation
from nifty_trader.contracts.models import (
    CandleObservation,
    CanonicalObservationStatus,
    CrossSourceValidation,
    CrossSourceValidationStatus,
    EvidenceType,
    ManualInstructionContext,
    NumericalObservation,
    ObservationEvidence,
    ObservationSource,
    ObservationWarning,
    OptionChainObservation,
    OptionLegObservation,
    OptionStrikeObservation,
    SensibullObservation,
    SourceChannelType,
    SourceStatus,
    TradingViewObservation,
    UnifiedMarketObservation,
    VisualObservation,
    WarningSeverity,
)
from nifty_trader.instruction.models import AgentInstruction
from nifty_trader.market_data.models import Candle, MarketSessionStatus, Timeframe
from nifty_trader.observation.cross_check import MultiSourceCrossChecker
from nifty_trader.observation.models import (
    MultiSourceComparisonResult,
    SensibullObservation as RawSensibullObservation,
    SensibullStatus,
)

logger = logging.getLogger(__name__)


class UnifiedObservationBuilder:
    """
    Assembles, normalizes, and validates canonical UnifiedMarketObservation records.
    """

    def __init__(self, cross_checker: Optional[MultiSourceCrossChecker] = None):
        self.cross_checker = cross_checker or MultiSourceCrossChecker()

    def build(
        self,
        symbol: str = "NIFTY",
        session_status: MarketSessionStatus = MarketSessionStatus.OPEN,
        h1_candles: Optional[List[Candle]] = None,
        m15_candles: Optional[List[Candle]] = None,
        tradingview_obs: Optional[BrowserObservation] = None,
        sensibull_obs: Optional[RawSensibullObservation] = None,
        instructions: Optional[List[AgentInstruction]] = None,
        multi_cross_result: Optional[MultiSourceComparisonResult] = None,
        start_time_utc: Optional[datetime] = None,
    ) -> UnifiedMarketObservation:
        """
        Builds a canonical UnifiedMarketObservation.
        Ensures evidence traceability and explicit status representation.
        """
        now = datetime.now(timezone.utc)
        start_ts = start_time_utc or now
        evidence_list: List[ObservationEvidence] = []
        warnings_list: List[ObservationWarning] = []
        sources_status: Dict[str, SourceStatus] = {}

        # ----------------------------------------------------------------------
        # 1. Numerical Market Data Normalization
        # ----------------------------------------------------------------------
        norm_h1: List[CandleObservation] = []
        norm_m15: List[CandleObservation] = []

        if h1_candles:
            for c in h1_candles:
                norm_h1.append(
                    CandleObservation(
                        instrument=symbol,
                        timeframe="1H",
                        timestamp=c.timestamp,
                        open=c.open,
                        high=c.high,
                        low=c.low,
                        close=c.close,
                        volume=c.volume,
                        is_complete=c.is_closed,
                        source="numerical_feed",
                    )
                )

        if m15_candles:
            for c in m15_candles:
                norm_m15.append(
                    CandleObservation(
                        instrument=symbol,
                        timeframe="15M",
                        timestamp=c.timestamp,
                        open=c.open,
                        high=c.high,
                        low=c.low,
                        close=c.close,
                        volume=c.volume,
                        is_complete=c.is_closed,
                        source="numerical_feed",
                    )
                )

        num_status = CanonicalObservationStatus.SUCCESS
        if not norm_h1 and not norm_m15:
            num_status = CanonicalObservationStatus.NOT_AVAILABLE
        elif not norm_h1 or not norm_m15:
            num_status = CanonicalObservationStatus.PARTIAL

        # Evidence for numerical data
        if norm_m15 or norm_h1:
            latest_ref = norm_m15[-1] if norm_m15 else norm_h1[-1]
            num_ev = ObservationEvidence(
                source_id="numerical_feed",
                observed_at=now,
                evidence_type=EvidenceType.NUMERICAL_DATA,
                excerpt=f"Latest close: {latest_ref.close} at {latest_ref.timestamp.isoformat()}",
                metadata={"h1_count": len(norm_h1), "m15_count": len(norm_m15)},
            )
            evidence_list.append(num_ev)

        sources_status["numerical_feed"] = SourceStatus(
            source_id="numerical_feed",
            status=num_status,
            observed_at=now,
            completeness=1.0 if num_status == CanonicalObservationStatus.SUCCESS else (0.5 if num_status == CanonicalObservationStatus.PARTIAL else 0.0),
            data_age_seconds=0.0,
            warnings=[],
        )

        numerical_obs = NumericalObservation(
            instrument=symbol,
            candles_1h=norm_h1,
            candles_15m=norm_m15,
        )

        # ----------------------------------------------------------------------
        # 2. TradingView Visual Observation Normalization
        # ----------------------------------------------------------------------
        canonical_tv: Optional[TradingViewObservation] = None
        if tradingview_obs:
            tv_ev_ids = []
            if tradingview_obs.screenshot_path:
                shot_ev = ObservationEvidence(
                    source_id="tradingview",
                    observed_at=now,
                    evidence_type=EvidenceType.SCREENSHOT,
                    reference=tradingview_obs.screenshot_path,
                )
                evidence_list.append(shot_ev)
                tv_ev_ids.append(shot_ev.evidence_id)

            if tradingview_obs.visible_text:
                txt_ev = ObservationEvidence(
                    source_id="tradingview",
                    observed_at=now,
                    evidence_type=EvidenceType.VISIBLE_TEXT,
                    excerpt=tradingview_obs.visible_text[:300],
                )
                evidence_list.append(txt_ev)
                tv_ev_ids.append(txt_ev.evidence_id)

            # Extract displayed price
            tv_price = self.cross_checker.extract_tradingview_price(tradingview_obs)
            tv_status = CanonicalObservationStatus.SUCCESS if tv_price is not None else CanonicalObservationStatus.PARTIAL

            canonical_tv = TradingViewObservation(
                status=tv_status,
                observed_at=now,
                instrument=symbol,
                timeframe_views={"1H": {}, "15M": {}},
                visible_price=tv_price,
                visible_chart_context={
                    "page_title": tradingview_obs.page_title,
                    "element_count": len(tradingview_obs.important_elements),
                },
                visible_text=tradingview_obs.visible_text[:1000] if tradingview_obs.visible_text else None,
                screenshot=tradingview_obs.screenshot_path,
                page_url=tradingview_obs.url,
                evidence_ids=tv_ev_ids,
                warnings=tradingview_obs.warnings,
            )

            sources_status["tradingview"] = SourceStatus(
                source_id="tradingview",
                status=tv_status,
                observed_at=now,
                completeness=0.95 if tv_price else 0.5,
                warnings=tradingview_obs.warnings,
            )
        else:
            sources_status["tradingview"] = SourceStatus(
                source_id="tradingview",
                status=CanonicalObservationStatus.NOT_AVAILABLE,
                observed_at=now,
                completeness=0.0,
                warnings=["TradingView visual observation was not interrogated."],
            )

        # ----------------------------------------------------------------------
        # 3. Sensibull Derivatives Observation Normalization
        # ----------------------------------------------------------------------
        canonical_sensi: Optional[SensibullObservation] = None
        if sensibull_obs:
            sensi_ev_ids = []
            if sensibull_obs.screenshot_reference:
                s_shot_ev = ObservationEvidence(
                    source_id="sensibull",
                    observed_at=now,
                    evidence_type=EvidenceType.SCREENSHOT,
                    reference=sensibull_obs.screenshot_reference,
                )
                evidence_list.append(s_shot_ev)
                sensi_ev_ids.append(s_shot_ev.evidence_id)

            if sensibull_obs.visible_text:
                s_txt_ev = ObservationEvidence(
                    source_id="sensibull",
                    observed_at=now,
                    evidence_type=EvidenceType.VISIBLE_TEXT,
                    excerpt=sensibull_obs.visible_text[:300],
                )
                evidence_list.append(s_txt_ev)
                sensi_ev_ids.append(s_txt_ev.evidence_id)

            # Map raw Sensibull status to CanonicalObservationStatus
            status_map = {
                SensibullStatus.OBSERVED: CanonicalObservationStatus.SUCCESS,
                SensibullStatus.AUTHENTICATION_REQUIRED: CanonicalObservationStatus.AUTHENTICATION_REQUIRED,
                SensibullStatus.PARSE_FAILED: CanonicalObservationStatus.PARSE_FAILED,
                SensibullStatus.NOT_LOADED: CanonicalObservationStatus.NOT_LOADED,
                SensibullStatus.NOT_AVAILABLE: CanonicalObservationStatus.NOT_AVAILABLE,
                SensibullStatus.STALE: CanonicalObservationStatus.STALE,
                SensibullStatus.ERROR: CanonicalObservationStatus.SOURCE_ERROR,
            }
            c_status = status_map.get(sensibull_obs.status, CanonicalObservationStatus.SOURCE_ERROR)

            # Normalize option strikes
            norm_strikes = []
            for s in sensibull_obs.strike_information:
                norm_strikes.append(
                    OptionStrikeObservation(
                        strike=s.strike,
                        call=OptionLegObservation(
                            ltp=s.call_ltp,
                            oi=s.call_oi,
                            oi_change=s.call_oi_change,
                            iv=s.call_iv,
                        ),
                        put=OptionLegObservation(
                            ltp=s.put_ltp,
                            oi=s.put_oi,
                            oi_change=s.put_oi_change,
                            iv=s.put_iv,
                        ),
                    )
                )

            opt_chain = OptionChainObservation(
                underlying=symbol,
                expiry=sensibull_obs.expiry,
                observed_at=sensibull_obs.timestamp,
                spot=sensibull_obs.spot_reference,
                strikes=norm_strikes,
                source="sensibull",
            )

            canonical_sensi = SensibullObservation(
                status=c_status,
                observed_at=sensibull_obs.timestamp,
                underlying=symbol,
                expiry=sensibull_obs.expiry,
                spot_reference=sensibull_obs.spot_reference,
                option_chain=opt_chain,
                pcr=sensibull_obs.pcr,
                open_interest=sensibull_obs.oi_information,
                oi_change=sensibull_obs.oi_change_information,
                implied_volatility=sensibull_obs.iv_information,
                max_pain=sensibull_obs.max_pain_information,
                visible_strikes=[s.strike for s in sensibull_obs.strike_information],
                important_visible_levels=sensibull_obs.important_levels,
                screenshot=sensibull_obs.screenshot_reference,
                visible_text=sensibull_obs.visible_text,
                evidence_ids=sensi_ev_ids,
                warnings=sensibull_obs.warnings,
            )

            sources_status["sensibull"] = SourceStatus(
                source_id="sensibull",
                status=c_status,
                observed_at=sensibull_obs.timestamp,
                completeness=sensibull_obs.confidence,
                warnings=sensibull_obs.warnings,
            )

            if c_status == CanonicalObservationStatus.AUTHENTICATION_REQUIRED:
                warnings_list.append(
                    ObservationWarning(
                        code="AUTH_REQUIRED",
                        severity=WarningSeverity.WARNING,
                        source="sensibull",
                        message="Sensibull option chain requires broker login; derivatives data omitted without blocking overall observation.",
                        evidence_id=sensi_ev_ids[0] if sensi_ev_ids else None,
                    )
                )
        else:
            sources_status["sensibull"] = SourceStatus(
                source_id="sensibull",
                status=CanonicalObservationStatus.NOT_AVAILABLE,
                observed_at=now,
                completeness=0.0,
                warnings=["Sensibull derivatives observation was not interrogated."],
            )

        # ----------------------------------------------------------------------
        # 4. Cross-Source Validation Normalization
        # ----------------------------------------------------------------------
        validations: List[CrossSourceValidation] = []
        n_ref = norm_m15[-1] if norm_m15 else (norm_h1[-1] if norm_h1 else None)
        n_close = n_ref.close if n_ref else None

        # Compare Sensibull vs Numerical
        if canonical_sensi and canonical_sensi.spot_reference is not None and n_close is not None:
            diff = round(abs(canonical_sensi.spot_reference - n_close), 2)
            pct = round((diff / n_close) * 100.0, 3)
            stat = CrossSourceValidationStatus.MATCH if pct <= 0.5 else (CrossSourceValidationStatus.MINOR_DIFFERENCE if pct <= 1.5 else CrossSourceValidationStatus.SIGNIFICANT_DIFFERENCE)
            validations.append(
                CrossSourceValidation(
                    field="spot_price",
                    source_a="sensibull",
                    value_a=canonical_sensi.spot_reference,
                    source_b="numerical_feed",
                    value_b=n_close,
                    absolute_difference=diff,
                    relative_difference=pct,
                    tolerance=0.5,
                    status=stat,
                    details=f"Sensibull spot ({canonical_sensi.spot_reference}) vs Numerical close ({n_close}): diff={diff} pts ({pct}%).",
                )
            )
            if stat == CrossSourceValidationStatus.SIGNIFICANT_DIFFERENCE:
                warnings_list.append(
                    ObservationWarning(
                        code="SOURCE_DISAGREEMENT",
                        severity=WarningSeverity.WARNING,
                        source="cross_validator",
                        message=f"Sensibull spot differs by {pct}% from numerical feed, exceeding 0.5% tolerance.",
                    )
                )

        # Compare TradingView vs Numerical
        if canonical_tv and canonical_tv.visible_price is not None and n_close is not None:
            diff = round(abs(canonical_tv.visible_price - n_close), 2)
            pct = round((diff / n_close) * 100.0, 3)
            stat = CrossSourceValidationStatus.MATCH if pct <= 0.5 else (CrossSourceValidationStatus.MINOR_DIFFERENCE if pct <= 1.5 else CrossSourceValidationStatus.SIGNIFICANT_DIFFERENCE)
            validations.append(
                CrossSourceValidation(
                    field="spot_price",
                    source_a="tradingview",
                    value_a=canonical_tv.visible_price,
                    source_b="numerical_feed",
                    value_b=n_close,
                    absolute_difference=diff,
                    relative_difference=pct,
                    tolerance=0.5,
                    status=stat,
                    details=f"TradingView price ({canonical_tv.visible_price}) vs Numerical close ({n_close}): diff={diff} pts ({pct}%).",
                )
            )
            if stat == CrossSourceValidationStatus.SIGNIFICANT_DIFFERENCE:
                warnings_list.append(
                    ObservationWarning(
                        code="SOURCE_DISAGREEMENT",
                        severity=WarningSeverity.WARNING,
                        source="cross_validator",
                        message=f"TradingView price differs by {pct}% from numerical feed, exceeding 0.5% tolerance.",
                    )
                )

        # ----------------------------------------------------------------------
        # 5. Manual Operator Steering Instructions Normalization
        # ----------------------------------------------------------------------
        instruction_contexts: List[ManualInstructionContext] = []
        if instructions:
            for inst in instructions:
                inst_created = getattr(inst, "created_at", getattr(inst, "timestamp", now))
                inst_ctx = ManualInstructionContext(
                    instruction_id=inst.instruction_id,
                    text=inst.text,
                    priority=inst.priority.value if hasattr(inst.priority, "value") else str(inst.priority),
                    status=inst.status.value if hasattr(inst.status, "value") else str(inst.status),
                    created_at=inst_created,
                    expires_at=inst.expires_at,
                    applicable_sources=["all"],
                )
                instruction_contexts.append(inst_ctx)
                evidence_list.append(
                    ObservationEvidence(
                        source_id="operator",
                        observed_at=inst_created,
                        evidence_type=EvidenceType.USER_INSTRUCTION,
                        reference=inst.instruction_id,
                        excerpt=inst.text,
                        metadata={"priority": str(inst.priority)},
                    )
                )

        # Assemble Visual Container
        visual_obs = VisualObservation(
            tradingview=canonical_tv,
            sensibull=canonical_sensi,
        )

        return UnifiedMarketObservation(
            schema_version="1.0",
            observation_id=f"umo_{uuid.uuid4().hex[:10]}",
            observed_at=now,
            instrument=symbol,
            session=session_status.value,
            numerical=numerical_obs,
            visual=visual_obs,
            source_status=sources_status,
            cross_source_validation=validations,
            manual_instruction_context=instruction_contexts,
            evidence=evidence_list,
            warnings=warnings_list,
        )
