"""Repository wrapping EventStore for consistent data access."""

from __future__ import annotations

from typing import Any

from ..event_store import EventStore
from ..models import EventPage, SquadEvent


class EventRepository:
    """Delegates to EventStore; provides a repository-shaped interface."""

    def __init__(self, event_store: EventStore):
        self._store = event_store

    def append(self, run_id: str, event_type: str, payload: dict[str, Any], critical: bool = False) -> SquadEvent:
        return self._store.append(run_id, event_type, payload, critical=critical)

    def query(self, run_id: str, cursor: int | None = None, limit: int = 100) -> EventPage:
        return self._store.query(run_id, cursor=cursor, limit=limit)

    def close(self) -> None:
        self._store.close()
