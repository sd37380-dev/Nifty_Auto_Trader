"""
Stage 6: Context Selector.

Prioritizes and bounds information provided to the Trading Brain.
Enforces the 10-tier ranking priority from Section 7 of the specification
and limits maximum context size to prevent context explosion and model degradation.
"""

from enum import IntEnum
import logging
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class ContextPriority(IntEnum):
    """
    10-tier priority order according to Stage 6 Specification Section 7.
    Lower numerical value = higher priority.
    """
    LATEST_OBSERVATION = 1
    REQUESTED_OBSERVATION_INFO = 2
    TIMEFRAME_1H_CONTEXT = 3
    TIMEFRAME_15M_CONTEXT = 4
    SOURCE_CROSS_CHECKS_AND_CONFLICTS = 5
    PREVIOUS_BRAIN_STATE = 6
    ACTIVE_HYPOTHESES_SCENARIOS = 7
    MANUAL_INSTRUCTIONS = 8
    RELEVANT_MEMORY = 9
    OLDER_HISTORICAL_INFO = 10


class PrioritizedContextItem(BaseModel):
    """
    A discrete contextual block tagged with priority and metadata.
    """
    priority: ContextPriority
    category: str
    title: str
    content: str
    is_mandatory: bool = False
    source_attribution: Optional[str] = None

    @property
    def char_count(self) -> int:
        return len(self.content)


class ContextSelector:
    """
    Ranks, selects, and fits contextual elements into a bounded budget.
    """

    def __init__(self, max_total_chars: int = 16000):
        self.max_total_chars = max_total_chars

    def select(
        self,
        items: List[PrioritizedContextItem],
        budget_chars: Optional[int] = None,
    ) -> List[PrioritizedContextItem]:
        """
        Sorts items by priority and fits them within the character budget.
        Mandatory items are always retained. Lower priority items are truncated or dropped.
        """
        budget = budget_chars or self.max_total_chars
        # Sort items: mandatory first, then by priority enum ascending (1 to 10)
        sorted_items = sorted(items, key=lambda x: (not x.is_mandatory, x.priority.value))

        selected: List[PrioritizedContextItem] = []
        current_chars = 0

        for item in sorted_items:
            item_len = len(item.content)
            if current_chars + item_len <= budget or item.is_mandatory:
                selected.append(item)
                current_chars += item_len
            else:
                # Calculate available remaining budget
                remaining = budget - current_chars
                if remaining > 300 and not item.is_mandatory:
                    # Provide truncated summary
                    truncated_content = item.content[: remaining - 50] + "\n... [TRUNCATED DUE TO CONTEXT BUDGET]"
                    truncated_item = PrioritizedContextItem(
                        priority=item.priority,
                        category=item.category,
                        title=item.title,
                        content=truncated_content,
                        is_mandatory=False,
                        source_attribution=item.source_attribution,
                    )
                    selected.append(truncated_item)
                    current_chars += len(truncated_content)
                    logger.debug("Truncated context item '%s' to fit remaining budget (%d chars)", item.title, remaining)
                else:
                    logger.debug("Skipped context item '%s' due to exhausted budget (%d/%d chars)", item.title, current_chars, budget)

        # Re-sort selected items by priority order for cohesive prompt generation
        return sorted(selected, key=lambda x: x.priority.value)
