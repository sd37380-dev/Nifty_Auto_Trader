"""
Stage 6: Context Security Validator.

Guards the Trading Brain prompt context against prompt injection, malicious external
web content (from TradingView / Sensibull browser scraping), and instruction spoofing.

STRICT INVARIANT: Web content is untrusted perceptual data only, never system commands.
"""

import logging
import re
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)


class ContextSecurityValidator:
    """
    Sanitizes and quarantines untrusted external web text before context injection.
    """

    # Directives that attempt to hijack LLM system instructions
    INJECTION_PATTERNS = [
        re.compile(r"(?i)(system\s*:)", re.IGNORECASE),
        re.compile(r"(?i)(ignore\s+(all\s+)?(previous|prior)\s+instructions)", re.IGNORECASE),
        re.compile(r"(?i)(disregard\s+(all\s+)?(previous|prior)\s+instructions)", re.IGNORECASE),
        re.compile(r"(?i)(you\s+are\s+now\s+a)", re.IGNORECASE),
        re.compile(r"(?i)(new\s+system\s+prompt\s*:)", re.IGNORECASE),
        re.compile(r"(?i)(execute\s+order\s*:)", re.IGNORECASE),
        re.compile(r"(?i)(buy\s+now\s+immediately)", re.IGNORECASE),
        re.compile(r"(?i)(sell\s+now\s+immediately)", re.IGNORECASE),
        re.compile(r"(?i)(override\s+safety\s+rules)", re.IGNORECASE),
        re.compile(r"(?i)(bypass\s+risk\s+limits)", re.IGNORECASE),
    ]

    @classmethod
    def sanitize_untrusted_text(
        cls,
        raw_text: Optional[str],
        source: str = "web_browser",
        max_length: int = 2000,
    ) -> str:
        """
        Sanitizes raw text extracted from external web pages, neutralizes injection
        attempts, and encapsulates the text within quarantined data delimiters.
        """
        if not raw_text:
            return ""

        sanitized = raw_text.strip()

        # 1. Truncate to maximum permissible length to prevent context explosion
        if len(sanitized) > max_length:
            sanitized = sanitized[:max_length] + " ... [TRUNCATED_FOR_SECURITY]"

        # 2. Check and neutralize injection patterns
        injection_detected = False
        for pattern in cls.INJECTION_PATTERNS:
            if pattern.search(sanitized):
                injection_detected = True
                sanitized = pattern.sub("[SANITIZED_INJECTION_ATTEMPT]", sanitized)

        if injection_detected:
            logger.warning(
                "Potential prompt injection pattern detected in untrusted source '%s'. Neutralized.",
                source,
            )

        # 3. Encapsulate within explicit untrusted data boundary
        return (
            f"<untrusted_external_data source=\"{source}\">\n"
            f"{sanitized}\n"
            f"</untrusted_external_data>"
        )

    @classmethod
    def validate_instruction_source(
        cls,
        instruction_text: str,
        created_by: str,
    ) -> Tuple[bool, Optional[str]]:
        """
        Verifies that trading directives or steering instructions originate strictly
        from authorized human operators, not web pages or tool outputs.
        """
        trusted_creators = {"human_operator", "system_admin", "cli_user"}
        if created_by not in trusted_creators:
            return False, f"Unauthorized instruction creator '{created_by}'. Only trusted operators permitted."

        return True, None
