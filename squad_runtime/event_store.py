from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import EventPage, SquadEvent


class EventStore:
    """SQLite-backed event stream with an NDJSON audit mirror."""

    def __init__(self, squad_dir: Path):
        self.squad_dir = Path(squad_dir)
        self.squad_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.squad_dir / "squad.db"
        self.ndjson_path = self.squad_dir / "events.ndjson"
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=5000")
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS squad_events (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                sequence_number INTEGER NOT NULL,
                type TEXT NOT NULL,
                payload TEXT NOT NULL,
                critical INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(run_id, sequence_number)
            )
            """
        )
        self.conn.commit()
        self._record_consistency_warning_if_needed()

    def append(self, run_id: str, event_type: str, payload: dict[str, Any], critical: bool = False) -> SquadEvent:
        sequence = self._next_sequence(run_id)
        event = SquadEvent(
            id=str(uuid.uuid4()),
            run_id=run_id,
            sequence_number=sequence,
            type=event_type,
            payload=payload,
            critical=critical,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO squad_events
                    (id, run_id, sequence_number, type, payload, critical, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (event.id, event.run_id, event.sequence_number, event.type, payload_json, int(event.critical), event.created_at),
            )
        self._append_ndjson(event)
        return event

    def query(self, run_id: str, cursor: int | None = None, limit: int = 100) -> EventPage:
        params: list[Any] = [run_id]
        where = "run_id = ?"
        if cursor is not None:
            where += " AND sequence_number > ?"
            params.append(cursor)
        params.append(limit + 1)
        rows = self.conn.execute(
            f"""
            SELECT * FROM squad_events
            WHERE {where}
            ORDER BY sequence_number ASC
            LIMIT ?
            """,
            params,
        ).fetchall()
        visible = rows[:limit]
        events = [self._row_to_event(row) for row in visible]
        next_cursor = None
        if len(rows) > limit and events:
            next_cursor = events[-1].sequence_number
        return EventPage(events=events, next_cursor=next_cursor)

    def close(self) -> None:
        self.conn.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def _next_sequence(self, run_id: str) -> int:
        row = self.conn.execute(
            "SELECT COALESCE(MAX(sequence_number), 0) + 1 AS next_sequence FROM squad_events WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        return int(row["next_sequence"])

    def _append_ndjson(self, event: SquadEvent) -> None:
        line = {
            "id": event.id,
            "runId": event.run_id,
            "sequenceNumber": event.sequence_number,
            "type": event.type,
            "payload": event.payload,
            "critical": event.critical,
            "createdAt": event.created_at,
        }
        with self.ndjson_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(line, ensure_ascii=False, sort_keys=True) + "\n")

    def _record_consistency_warning_if_needed(self) -> None:
        sqlite_count = int(self.conn.execute("SELECT COUNT(*) AS count FROM squad_events").fetchone()["count"])
        ndjson_count = self._ndjson_line_count()
        if sqlite_count == ndjson_count:
            return
        self.append(
            "system",
            "event_store_consistency_warning",
            {
                "sqliteEventCount": sqlite_count,
                "ndjsonLineCount": ndjson_count,
                "sourceOfTruth": "sqlite",
            },
            critical=True,
        )
        self._rebuild_ndjson_from_sqlite()

    def _rebuild_ndjson_from_sqlite(self) -> None:
        rows = self.conn.execute(
            """
            SELECT * FROM squad_events
            ORDER BY run_id ASC, sequence_number ASC
            """
        ).fetchall()
        with self.ndjson_path.open("w", encoding="utf-8") as handle:
            for row in rows:
                event = self._row_to_event(row)
                line = {
                    "id": event.id,
                    "runId": event.run_id,
                    "sequenceNumber": event.sequence_number,
                    "type": event.type,
                    "payload": event.payload,
                    "critical": event.critical,
                    "createdAt": event.created_at,
                }
                handle.write(json.dumps(line, ensure_ascii=False, sort_keys=True) + "\n")

    def _ndjson_line_count(self) -> int:
        if not self.ndjson_path.exists():
            return 0
        count = 0
        with self.ndjson_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    count += 1
        return count

    def _row_to_event(self, row: sqlite3.Row) -> SquadEvent:
        return SquadEvent(
            id=row["id"],
            run_id=row["run_id"],
            sequence_number=int(row["sequence_number"]),
            type=row["type"],
            payload=json.loads(row["payload"]),
            critical=bool(row["critical"]),
            created_at=row["created_at"],
        )

