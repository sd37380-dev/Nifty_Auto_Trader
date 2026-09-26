"""
Sensibull Market Observation Source.

Observes NIFTY derivatives market sentiment (Option Chain, PCR, Max Pain, IV, OI)
via browser automation without executing trades or bypassing security barriers.
STRICT INVARIANT: Observation only. No buy/sell decisions, no anti-bot bypass.
"""

from datetime import datetime, timezone
import logging
import re
from typing import Any, Dict, List, Optional

from nifty_trader.browser.browser_agent import BrowserAgent
from nifty_trader.browser.models import BrowserObservation
from nifty_trader.observation.models import (
    ObservationFreshness,
    ObservationSourceType,
    OptionChainStrike,
    SensibullObservation,
    SensibullStatus,
    SourceObservationResult,
)
from nifty_trader.observation.sources.base import IMarketObservationSource

logger = logging.getLogger(__name__)


class SensibullObservationSource(IMarketObservationSource):
    """
    Browser-based observation source for Sensibull Option Chain.
    Extracts visible derivatives metrics using bounded DOM and text inspection.
    """

    DEFAULT_URL = "https://web.sensibull.com/option-chain?tradingsymbol=NIFTY"

    # Regex patterns for key derivatives metrics
    PCR_PATTERN = re.compile(r"(?:PCR|Put[\s\/-]?Call[\s\/-]?Ratio)\s*[:=]?\s*([0-3]\.\d{1,3})", re.IGNORECASE)
    MAX_PAIN_PATTERN = re.compile(r"Max\s*Pain\s*[:=]?\s*(2\d{1},\d{3}|2\d{4})", re.IGNORECASE)
    IV_PATTERN = re.compile(r"(?:ATM\s*IV|Median\s*IV|IV)\s*[:=]?\s*(\d{1,2}(?:\.\d{1,2})?)\s*%", re.IGNORECASE)
    SPOT_PATTERN = re.compile(r"(?:NIFTY|Spot|Underlying)[\s\w]*[:=]?\s*(2\d{1},\d{3}(?:\.\d{1,2})?|2\d{4}(?:\.\d{1,2})?)", re.IGNORECASE)
    STRIKE_PATTERN = re.compile(r"\b(2\d{4})\b")

    # Anti-bot and auth detection keywords
    AUTH_KEYWORDS = [
        "login with broker",
        "log in with",
        "sign in with",
        "select broker",
        "zerodha",
        "upstox",
        "angel one",
        "continue with google",
        "please login to view",
        "authentication required",
    ]

    # Prompt injection markers in untrusted web text
    INJECTION_KEYWORDS = [
        "ignore previous instructions",
        "ignore all previous",
        "system prompt",
        "you are now",
        "disregard safety",
        "execute trade",
        "buy nifty now",
        "sell nifty now",
    ]

    def __init__(
        self,
        browser_agent: Optional[BrowserAgent] = None,
        target_url: Optional[str] = None,
        max_retries: int = 2,
        timeout_seconds: float = 30.0,
        enabled: bool = True,
    ):
        self.browser_agent = browser_agent
        self.target_url = target_url or self.DEFAULT_URL
        self.max_retries = max_retries
        self.timeout_seconds = timeout_seconds
        self.enabled = enabled

    @property
    def source_id(self) -> str:
        return "sensibull"

    @property
    def source_type(self) -> ObservationSourceType:
        return ObservationSourceType.DERIVATIVES_OPTION_CHAIN

    @property
    def capabilities(self) -> List[str]:
        return ["option_chain", "pcr", "max_pain", "atm_iv", "open_interest", "oi_change", "strikes"]

    async def is_available(self) -> bool:
        if not self.enabled:
            return False
        if not self.browser_agent:
            return False
        return True

    def sanitize_untrusted_text(self, text: str) -> tuple[str, List[str]]:
        """
        Sanitizes visible webpage text to neutralize potential prompt injection.
        Returns (sanitized_text, warnings).
        """
        warnings = []
        lower = text.lower()
        for kw in self.INJECTION_KEYWORDS:
            if kw in lower:
                warnings.append(f"Security Alert: Untrusted external webpage text contained prohibited prompt injection sequence: '{kw}'")
                text = re.sub(re.escape(kw), "[REDACTED_PROMPT_INJECTION]", text, flags=re.IGNORECASE)
        return text, warnings

    def parse_metrics_from_text(self, text: str) -> Dict[str, Any]:
        """
        Deterministic extraction of derivatives metrics from sanitized page text.
        Missing metrics remain None (NEVER coerced to 0.0).
        """
        metrics: Dict[str, Any] = {
            "spot": None,
            "pcr": None,
            "max_pain": None,
            "atm_iv": None,
            "strikes": [],
        }

        # 1. Spot price
        spot_match = self.SPOT_PATTERN.search(text)
        if spot_match:
            try:
                metrics["spot"] = float(spot_match.group(1).replace(",", ""))
            except ValueError:
                pass

        # 2. PCR (Put-Call Ratio)
        pcr_match = self.PCR_PATTERN.search(text)
        if pcr_match:
            try:
                val = float(pcr_match.group(1))
                if 0.1 <= val <= 3.0:
                    metrics["pcr"] = round(val, 3)
            except ValueError:
                pass

        # 3. Max Pain
        mp_match = self.MAX_PAIN_PATTERN.search(text)
        if mp_match:
            try:
                val = float(mp_match.group(1).replace(",", ""))
                if 18000 <= val <= 32000:
                    metrics["max_pain"] = val
            except ValueError:
                pass

        # 4. ATM IV
        iv_match = self.IV_PATTERN.search(text)
        if iv_match:
            try:
                metrics["atm_iv"] = float(iv_match.group(1))
            except ValueError:
                pass

        # 5. Extract prominent strikes (50-point increments for NIFTY)
        raw_strikes = self.STRIKE_PATTERN.findall(text)
        valid_strikes = []
        for s in raw_strikes:
            try:
                strike_val = float(s)
                if 18000 <= strike_val <= 32000 and (strike_val % 50 == 0):
                    valid_strikes.append(strike_val)
            except ValueError:
                continue

        # Sort and deduplicate strikes
        if valid_strikes:
            unique_sorted = sorted(list(set(valid_strikes)))
            metrics["strikes"] = [OptionChainStrike(strike=s) for s in unique_sorted[:15]]

        return metrics

    def detect_auth_required(self, visible_text: str, page_title: str) -> bool:
        """
        Checks if the page exhibits authentication or login barriers.
        """
        combined = f"{page_title}\n{visible_text}".lower()
        return any(kw in combined for kw in self.AUTH_KEYWORDS)

    async def observe(self, symbol: str = "NIFTY", **kwargs) -> SourceObservationResult:
        """
        Executes bounded Sensibull observation workflow.
        """
        now = datetime.now(timezone.utc)
        warnings: List[str] = []
        errors: List[str] = []

        if not self.enabled:
            obs = SensibullObservation(
                status=SensibullStatus.NOT_AVAILABLE,
                warnings=["Sensibull observation source is disabled in configuration."],
                timestamp=now,
            )
            return SourceObservationResult(
                source_id=self.source_id,
                source_type=self.source_type,
                success=False,
                status=SensibullStatus.NOT_AVAILABLE.value,
                timestamp=now,
                data=obs.model_dump(),
                warnings=obs.warnings,
            )

        if not self.browser_agent:
            obs = SensibullObservation(
                status=SensibullStatus.ERROR,
                errors=["Browser agent is not configured or unavailable for Sensibull."],
                timestamp=now,
            )
            return SourceObservationResult(
                source_id=self.source_id,
                source_type=self.source_type,
                success=False,
                status=SensibullStatus.ERROR.value,
                timestamp=now,
                data=obs.model_dump(),
                errors=obs.errors,
            )

        # Execute bounded browser navigation
        try:
            logger.info("Observing Sensibull Option Chain at %s...", self.target_url)
            browser_obs: BrowserObservation = await self.browser_agent.navigate(
                url=self.target_url,
                capture_screen=True,
                screenshot_prefix="sensibull_nifty",
            )
        except Exception as e:
            logger.warning("Sensibull browser navigation failed: %s", e)
            obs = SensibullObservation(
                status=SensibullStatus.NOT_LOADED,
                errors=[f"Navigation error: {str(e)}"],
                timestamp=now,
            )
            return SourceObservationResult(
                source_id=self.source_id,
                source_type=self.source_type,
                success=False,
                status=SensibullStatus.NOT_LOADED.value,
                timestamp=now,
                data=obs.model_dump(),
                errors=obs.errors,
            )

        # 1. Sanitize untrusted web content (Prompt Injection Defense)
        sanitized_text, injection_warnings = self.sanitize_untrusted_text(browser_obs.visible_text)
        warnings.extend(injection_warnings)
        if browser_obs.warnings:
            warnings.extend(browser_obs.warnings)

        # 2. Extract metrics
        parsed = self.parse_metrics_from_text(sanitized_text)

        # 3. Check for Authentication Requirement
        has_auth_barrier = self.detect_auth_required(sanitized_text, browser_obs.page_title)
        has_actual_data = (parsed["pcr"] is not None or len(parsed["strikes"]) > 0 or parsed["max_pain"] is not None)

        if has_auth_barrier and not has_actual_data:
            logger.info("Sensibull requires user authentication. Flagging AUTHENTICATION_REQUIRED.")
            obs = SensibullObservation(
                status=SensibullStatus.AUTHENTICATION_REQUIRED,
                screenshot_reference=browser_obs.screenshot_path,
                visible_text=sanitized_text[:2000],
                warnings=warnings + ["Sensibull page requires user broker authentication."],
                timestamp=now,
                freshness=ObservationFreshness.UNKNOWN,
            )
            return SourceObservationResult(
                source_id=self.source_id,
                source_type=self.source_type,
                success=False,
                status=SensibullStatus.AUTHENTICATION_REQUIRED.value,
                timestamp=now,
                data=obs.model_dump(),
                warnings=obs.warnings,
            )

        # Determine status
        if parsed["pcr"] is not None or parsed["spot"] is not None or parsed["strikes"]:
            status = SensibullStatus.OBSERVED
            confidence = 0.9 if (parsed["pcr"] is not None and parsed["spot"] is not None) else 0.6
            freshness = ObservationFreshness.FRESH
        else:
            status = SensibullStatus.PARSE_FAILED
            confidence = 0.2
            freshness = ObservationFreshness.UNKNOWN
            warnings.append("Could not extract recognized option chain metrics from visible Sensibull DOM.")

        important_levels = []
        if parsed["max_pain"]:
            important_levels.append(parsed["max_pain"])
        if parsed["spot"]:
            important_levels.append(parsed["spot"])

        obs = SensibullObservation(
            status=status,
            instrument=symbol,
            spot_reference=parsed["spot"],
            option_chain_available=(status == SensibullStatus.OBSERVED),
            pcr=parsed["pcr"],
            max_pain_information=parsed["max_pain"],
            iv_information={"atm_iv": parsed["atm_iv"]} if parsed["atm_iv"] else {},
            strike_information=parsed["strikes"],
            important_levels=important_levels,
            screenshot_reference=browser_obs.screenshot_path,
            visible_text=sanitized_text[:4000],
            warnings=warnings,
            errors=errors,
            confidence=confidence,
            freshness=freshness,
            timestamp=now,
        )

        return SourceObservationResult(
            source_id=self.source_id,
            source_type=self.source_type,
            success=(status == SensibullStatus.OBSERVED),
            status=status.value,
            timestamp=now,
            data=obs.model_dump(),
            warnings=warnings,
            errors=errors,
        )
