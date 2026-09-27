"""
Package 5: Bounded Retry Policy.

Provides deterministic exponential backoff with optional jitter for handling
transient perception or model reasoning failures safely without runaway loops.
"""

import logging
import random
from typing import Optional

logger = logging.getLogger(__name__)


class BoundedRetryPolicy:
    """
    Calculates bounded exponential backoff delays with safety limits.
    """

    def __init__(
        self,
        max_attempts: int = 5,
        initial_backoff_seconds: float = 5.0,
        max_backoff_seconds: float = 60.0,
        multiplier: float = 2.0,
        enable_jitter: bool = True,
    ):
        self.max_attempts = max_attempts
        self.initial_backoff = initial_backoff_seconds
        self.max_backoff = max_backoff_seconds
        self.multiplier = multiplier
        self.enable_jitter = enable_jitter

    def should_retry(self, consecutive_failures: int) -> bool:
        """Returns True if failure count is strictly less than max_attempts."""
        return consecutive_failures < self.max_attempts

    def get_backoff_delay(self, consecutive_failures: int) -> float:
        """
        Calculates exponential backoff delay in seconds bounded by max_backoff.
        """
        exponent = max(0, consecutive_failures)
        delay = self.initial_backoff * (self.multiplier ** min(exponent, 6))
        bounded = min(delay, self.max_backoff)

        if self.enable_jitter and bounded > 1.0:
            # Add up to 15% random jitter to avoid lockstep retries
            jitter_amount = random.uniform(0.0, bounded * 0.15)
            bounded += jitter_amount

        return round(bounded, 2)
