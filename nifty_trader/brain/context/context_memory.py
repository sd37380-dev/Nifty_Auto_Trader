"""
Stage 6: Context Memory Store.

Provides historical trading setup memories and post-mortem observations to the Brain.

STRICT INVARIANT:
Memory is contextual evidence for human/AI pattern comparison, NEVER deterministic trading rules.
The Brain must treat historical experience as descriptive context, not automated execution instructions.
"""

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
import uuid

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class ContextMemoryItem(BaseModel):
    """
    A single historical observation or setup memory.
    """
    memory_id: str = Field(default_factory=lambda: f"mem_{uuid.uuid4().hex[:8]}")
    setup_type: str = Field(description="Descriptive setup pattern, e.g. 'breakout_failure', 'range_rejection'")
    timeframe: str = Field(description="Relevant timeframe, e.g. '15M', '1H'")
    observed_characteristics: str = Field(description="Observed market features at the time")
    historical_outcome: str = Field(description="What transpired following the setup")
    lessons: str = Field(description="Takeaways or contextual caveats")
    relevance_score: float = Field(default=0.5, ge=0.0, le=1.0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    tags: List[str] = Field(default_factory=list)


class ContextMemoryStore:
    """
    Bounded historical memory repository for providing descriptive context to the Brain.
    """

    def __init__(self, storage_path: Optional[Path] = None, max_items: int = 100):
        self.storage_path = storage_path
        self.max_items = max_items
        self._items: Dict[str, ContextMemoryItem] = {}
        if storage_path and storage_path.exists():
            self._load()

    def add_memory(self, item: ContextMemoryItem) -> str:
        """Adds a memory item, evicting oldest if capacity reached."""
        if len(self._items) >= self.max_items and item.memory_id not in self._items:
            # Evict oldest item
            oldest_id = min(self._items.keys(), key=lambda k: self._items[k].created_at)
            del self._items[oldest_id]

        self._items[item.memory_id] = item
        if self.storage_path:
            self._persist()
        return item.memory_id

    def get_memory(self, memory_id: str) -> Optional[ContextMemoryItem]:
        return self._items.get(memory_id)

    def query_relevant(
        self,
        setup_type: Optional[str] = None,
        timeframe: Optional[str] = None,
        query_text: Optional[str] = None,
        limit: int = 3,
    ) -> List[ContextMemoryItem]:
        """
        Retrieves top relevant memory items matching criteria.
        """
        candidates = list(self._items.values())
        if setup_type:
            setup_lower = setup_type.lower()
            candidates = [c for c in candidates if setup_lower in c.setup_type.lower()]
        if timeframe:
            tf_lower = timeframe.lower()
            candidates = [c for c in candidates if tf_lower in c.timeframe.lower()]
        if query_text:
            qt_lower = query_text.lower()
            candidates = [
                c for c in candidates
                if qt_lower in c.observed_characteristics.lower()
                or qt_lower in c.historical_outcome.lower()
                or any(qt_lower in t.lower() for t in c.tags)
            ]

        # Rank by relevance score descending
        candidates.sort(key=lambda x: x.relevance_score, reverse=True)
        return candidates[:limit]

    def format_for_context(self, items: List[ContextMemoryItem]) -> str:
        """
        Formats memory items with explicit non-rule warning tags.
        """
        if not items:
            return "No historical contextual memories relevant to current setup."

        header = (
            "### HISTORICAL CONTEXTUAL EVIDENCE (NON-DETERMINISTIC EXPERIENCE - NOT TRADING RULES)\n"
            "> [!NOTE] The following memories are provided solely as historical contextual evidence for pattern "
            "comparison. They must NEVER be treated as hard-coded trading rules, triggers, or orders.\n\n"
        )
        lines = []
        for i, mem in enumerate(items, start=1):
            lines.append(
                f"{i}. [Memory ID: {mem.memory_id}] Setup: {mem.setup_type} ({mem.timeframe})\n"
                f"   * Observed: {mem.observed_characteristics}\n"
                f"   * Historical Outcome: {mem.historical_outcome}\n"
                f"   * Contextual Lessons: {mem.lessons}\n"
                f"   * Tags: {', '.join(mem.tags) if mem.tags else 'None'}"
            )
        return header + "\n".join(lines)

    def _persist(self) -> None:
        if not self.storage_path:
            return
        try:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            data = [json.loads(item.model_dump_json()) for item in self._items.values()]
            with open(self.storage_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error("Failed to persist context memory store: %s", e)

    def _load(self) -> None:
        if not self.storage_path or not self.storage_path.exists():
            return
        try:
            with open(self.storage_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for raw in data:
                item = ContextMemoryItem.model_validate(raw)
                self._items[item.memory_id] = item
        except Exception as e:
            logger.error("Failed to load context memory store: %s", e)
