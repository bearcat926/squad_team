from __future__ import annotations

import contextlib
import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .canonicalization import GENESIS_HASH, compute_event_hash
from .models import EventPage, SquadEvent

_HASH_COLUMNS = ("previous_event_hash", "event_payload_hash", "event_hash")


class EventStore:
    """SQLite-backed event stream with an NDJSON audit mirror."""

    def __init__(self, squad_dir: Path, conn: sqlite3.Connection | None = None):
        self.squad_dir = Path(squad_dir)
        self.squad_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.squad_dir / "squad.db"
        self.ndjson_path = self.squad_dir / "events.ndjson"
        self._owns_connection = conn is None
        if conn is not None:
            self.conn = conn
        else:
            self.conn = sqlite3.connect(self.db_path)
            self.conn.row_factory = sqlite3.Row
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA busy_timeout=5000")
        self.conn.execute("""
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
            """)
        self.conn.commit()
        self._ensure_hash_columns()
        self._record_consistency_warning_if_needed()

    # ------------------------------------------------------------------
    # Schema migration: add hash chain columns if missing
    # ------------------------------------------------------------------

    def _ensure_hash_columns(self) -> None:
        """Add hash chain columns to existing databases (idempotent)."""
        existing = {row[1] for row in self.conn.execute("PRAGMA table_info(squad_events)").fetchall()}
        for col in _HASH_COLUMNS:
            if col not in existing:
                self.conn.execute(f"ALTER TABLE squad_events ADD COLUMN {col} TEXT")
        self.conn.commit()

    # ------------------------------------------------------------------
    # Hash chain helpers
    # ------------------------------------------------------------------

    def get_last_event_hash(self, run_id: str) -> str:
        """Return the eventHash of the most recent event for *run_id*, or GENESIS_HASH."""
        row = self.conn.execute(
            "SELECT event_hash FROM squad_events WHERE run_id = ? ORDER BY sequence_number DESC LIMIT 1",
            (run_id,),
        ).fetchone()
        if row is None or row["event_hash"] is None:
            return GENESIS_HASH
        return str(row["event_hash"])

    def get_chain_info(self, run_id: str) -> dict[str, Any]:
        """Return chain metadata for *run_id*."""
        rows = self.conn.execute(
            "SELECT sequence_number, previous_event_hash, event_payload_hash, event_hash, payload "
            "FROM squad_events WHERE run_id = ? ORDER BY sequence_number ASC",
            (run_id,),
        ).fetchall()
        count = len(rows)
        last_hash = GENESIS_HASH
        for row in rows:
            if row["event_hash"] is not None:
                last_hash = str(row["event_hash"])
        valid, errors = self._verify_rows(rows)
        return {
            "eventCount": count,
            "finalEventHash": last_hash if count > 0 else None,
            "valid": valid,
            "errors": errors,
        }

    def verify_chain(self, run_id: str) -> dict[str, Any]:
        """Verify the entire hash chain for *run_id*.

        Returns a dict with ``valid`` (bool), ``eventCount``, ``finalEventHash``,
        and ``errors`` (list[str]).
        """
        rows = self.conn.execute(
            "SELECT sequence_number, previous_event_hash, event_payload_hash, event_hash, payload "
            "FROM squad_events WHERE run_id = ? ORDER BY sequence_number ASC",
            (run_id,),
        ).fetchall()
        count = len(rows)
        last_hash = GENESIS_HASH
        for row in rows:
            if row["event_hash"] is not None:
                last_hash = str(row["event_hash"])
        valid, errors = self._verify_rows(rows)
        return {
            "valid": valid,
            "eventCount": count,
            "finalEventHash": last_hash if count > 0 else None,
            "errors": errors,
        }

    def _verify_rows(self, rows: list[sqlite3.Row]) -> tuple[bool, list[str]]:
        """Walk rows in order and verify each hash link.

        Returns (valid, errors).
        """
        errors: list[str] = []
        prev_hash = GENESIS_HASH
        for row in rows:
            seq = int(row["sequence_number"])
            stored_prev = row["previous_event_hash"]
            stored_payload_hash = row["event_payload_hash"]
            stored_event_hash = row["event_hash"]

            # Rows without hash fields (legacy) are skipped from verification
            if stored_payload_hash is None or stored_event_hash is None:
                errors.append(f"sequence {seq}: missing hash fields (legacy row)")
                continue

            if stored_prev != prev_hash:
                errors.append(f"sequence {seq}: previousEventHash mismatch " f"(expected {prev_hash}, got {stored_prev})")

            payload = json.loads(row["payload"])
            expected_payload_hash, expected_event_hash = compute_event_hash(prev_hash, payload)
            if stored_payload_hash != expected_payload_hash:
                errors.append(f"sequence {seq}: eventPayloadHash mismatch " f"(expected {expected_payload_hash}, got {stored_payload_hash})")
            if stored_event_hash != expected_event_hash:
                errors.append(f"sequence {seq}: eventHash mismatch " f"(expected {expected_event_hash}, got {stored_event_hash})")
            prev_hash = str(stored_event_hash)

        return (len(errors) == 0, errors)

    # ------------------------------------------------------------------
    # Core API
    # ------------------------------------------------------------------

    def append(self, run_id: str, event_type: str, payload: dict[str, Any], critical: bool = False) -> SquadEvent:
        sequence = self._next_sequence(run_id)
        event = SquadEvent(
            id=str(uuid.uuid4()),
            run_id=run_id,
            sequence_number=sequence,
            type=event_type,
            payload=payload,
            critical=critical,
            created_at=datetime.now(UTC).isoformat(),
        )

        # Compute hash chain
        prev_hash = self.get_last_event_hash(run_id)
        payload_hash, event_hash = compute_event_hash(prev_hash, payload)

        payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO squad_events
                    (id, run_id, sequence_number, type, payload, critical, created_at,
                     previous_event_hash, event_payload_hash, event_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.id,
                    event.run_id,
                    event.sequence_number,
                    event.type,
                    payload_json,
                    int(event.critical),
                    event.created_at,
                    prev_hash,
                    payload_hash,
                    event_hash,
                ),
            )
        self._append_ndjson(event, prev_hash, payload_hash, event_hash)
        return event

    def query(self, run_id: str, cursor: int | None = None, limit: int = 100) -> EventPage:
        if cursor is not None:
            rows = self.conn.execute(
                """
                SELECT * FROM squad_events
                WHERE run_id = ? AND sequence_number > ?
                ORDER BY sequence_number ASC
                LIMIT ?
                """,
                (run_id, cursor, limit + 1),
            ).fetchall()
        else:
            rows = self.conn.execute(
                """
                SELECT * FROM squad_events
                WHERE run_id = ?
                ORDER BY sequence_number ASC
                LIMIT ?
                """,
                (run_id, limit + 1),
            ).fetchall()
        visible = rows[:limit]
        events = [self._row_to_event(row) for row in visible]
        next_cursor = None
        if len(rows) > limit and events:
            next_cursor = events[-1].sequence_number
        return EventPage(events=events, next_cursor=next_cursor)

    def close(self) -> None:
        if self._owns_connection:
            self.conn.close()

    def __del__(self) -> None:
        with contextlib.suppress(Exception):
            self.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _next_sequence(self, run_id: str) -> int:
        row = self.conn.execute(
            "SELECT COALESCE(MAX(sequence_number), 0) + 1 AS next_sequence FROM squad_events WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        return int(row["next_sequence"])

    def _append_ndjson(
        self,
        event: SquadEvent,
        previous_event_hash: str,
        event_payload_hash: str,
        event_hash: str,
    ) -> None:
        line = {
            "id": event.id,
            "runId": event.run_id,
            "sequenceNumber": event.sequence_number,
            "type": event.type,
            "payload": event.payload,
            "critical": event.critical,
            "createdAt": event.created_at,
            "previousEventHash": previous_event_hash,
            "eventPayloadHash": event_payload_hash,
            "eventHash": event_hash,
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
        rows = self.conn.execute("""
            SELECT * FROM squad_events
            ORDER BY run_id ASC, sequence_number ASC
            """).fetchall()
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
                    "previousEventHash": row["previous_event_hash"],
                    "eventPayloadHash": row["event_payload_hash"],
                    "eventHash": row["event_hash"],
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
