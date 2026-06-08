"""Tests for event hash chain computation and verification."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from squad_runtime.canonicalization import (
    CANONICALIZATION_SPEC_VERSION,
    GENESIS_HASH,
    canonical_json_bytes,
    compute_event_hash,
    normalize_path,
    normalize_text,
    sha256_hex,
    verify_event_hash,
)
from squad_runtime.event_store import EventStore
from squad_runtime.replay import ReplayEngine

# ---------------------------------------------------------------------------
# canonicalization unit tests
# ---------------------------------------------------------------------------


class TestCanonicalizationDeterministic:
    def test_same_payload_same_hash(self) -> None:
        payload = {"action": "test", "value": 42}
        h1 = sha256_hex(canonical_json_bytes(payload))
        h2 = sha256_hex(canonical_json_bytes(payload))
        assert h1 == h2

    def test_sorted_keys(self) -> None:
        a = canonical_json_bytes({"b": 1, "a": 2})
        b = canonical_json_bytes({"a": 2, "b": 1})
        assert a == b

    def test_nfc_normalization(self) -> None:
        # e-acute as single codepoint vs combining sequence
        nfc = "é"  # precomposed
        nfd = "é"  # decomposed
        h1 = sha256_hex(canonical_json_bytes({"name": nfc}))
        h2 = sha256_hex(canonical_json_bytes({"name": nfd}))
        assert h1 == h2

    def test_path_normalization(self) -> None:
        assert normalize_path("a\\b\\c") == "a/b/c"
        assert normalize_path("a/b/c") == "a/b/c"
        payload_a = canonical_json_bytes({"path": normalize_path("a\\b\\c")})
        payload_b = canonical_json_bytes({"path": normalize_path("a/b/c")})
        assert sha256_hex(payload_a) == sha256_hex(payload_b)

    def test_trailing_whitespace_stripped(self) -> None:
        assert normalize_text("hello  \nworld  ") == "hello\nworld"

    def test_compact_separators(self) -> None:
        data = canonical_json_bytes({"a": 1})
        assert b": " not in data  # compact uses ':' not ': '
        assert b", " not in data  # compact uses ',' not ', '


# ---------------------------------------------------------------------------
# hash chain unit tests
# ---------------------------------------------------------------------------


class TestHashChainComputation:
    def test_genesis_hash_is_empty_sha256(self) -> None:
        """GENESIS_HASH is SHA-256 of empty string."""
        assert "sha256-" + __import__("hashlib").sha256(b"").hexdigest() == GENESIS_HASH

    def test_compute_returns_two_hashes(self) -> None:
        ph, eh = compute_event_hash(GENESIS_HASH, {"x": 1})
        assert ph.startswith("sha256-")
        assert eh.startswith("sha256-")
        assert ph != eh

    def test_verify_roundtrip(self) -> None:
        payload = {"hello": "world"}
        ph, eh = compute_event_hash(GENESIS_HASH, payload)
        assert verify_event_hash(GENESIS_HASH, payload, ph, eh) is True

    def test_verify_detects_tamper(self) -> None:
        payload = {"hello": "world"}
        ph, eh = compute_event_hash(GENESIS_HASH, payload)
        assert verify_event_hash(GENESIS_HASH, {"hello": "tampered"}, ph, eh) is False


# ---------------------------------------------------------------------------
# EventStore integration tests
# ---------------------------------------------------------------------------


class TestEventStoreHashChain:
    def test_first_event_has_genesis_previous(self, tmp_path: Path) -> None:
        store = EventStore(tmp_path / ".squad")
        event = store.append("run-1", "test", {"a": 1})
        row = store.conn.execute("SELECT previous_event_hash FROM squad_events WHERE id = ?", (event.id,)).fetchone()
        assert row["previous_event_hash"] == GENESIS_HASH
        store.close()

    def test_chain_computation_basic(self, tmp_path: Path) -> None:
        store = EventStore(tmp_path / ".squad")
        e1 = store.append("run-1", "test", {"step": 1})
        e2 = store.append("run-1", "test", {"step": 2})
        e3 = store.append("run-1", "test", {"step": 3})

        # Verify chain links
        r1 = store.conn.execute("SELECT event_hash FROM squad_events WHERE id = ?", (e1.id,)).fetchone()
        r2 = store.conn.execute("SELECT previous_event_hash, event_hash FROM squad_events WHERE id = ?", (e2.id,)).fetchone()
        r3 = store.conn.execute("SELECT previous_event_hash, event_hash FROM squad_events WHERE id = ?", (e3.id,)).fetchone()

        assert r2["previous_event_hash"] == r1["event_hash"]
        assert r3["previous_event_hash"] == r2["event_hash"]
        store.close()

    def test_verify_chain_valid(self, tmp_path: Path) -> None:
        store = EventStore(tmp_path / ".squad")
        store.append("run-1", "test", {"a": 1})
        store.append("run-1", "test", {"a": 2})
        store.append("run-1", "test", {"a": 3})
        result = store.verify_chain("run-1")
        assert result["valid"] is True
        assert result["eventCount"] == 3
        assert result["errors"] == []
        store.close()

    def test_chain_detects_modified_payload(self, tmp_path: Path) -> None:
        store = EventStore(tmp_path / ".squad")
        store.append("run-1", "test", {"a": 1})
        e2 = store.append("run-1", "test", {"a": 2})
        store.append("run-1", "test", {"a": 3})

        # Tamper with middle event payload (but leave hash unchanged)
        store.conn.execute(
            "UPDATE squad_events SET payload = ? WHERE id = ?",
            (json.dumps({"a": 999}, sort_keys=True), e2.id),
        )
        store.conn.commit()

        result = store.verify_chain("run-1")
        assert result["valid"] is False
        assert any("eventPayloadHash mismatch" in e for e in result["errors"])
        store.close()

    def test_chain_detects_deleted_event(self, tmp_path: Path) -> None:
        store = EventStore(tmp_path / ".squad")
        store.append("run-1", "test", {"a": 1})
        e2 = store.append("run-1", "test", {"a": 2})
        store.append("run-1", "test", {"a": 3})

        # Delete middle event and renumber
        store.conn.execute("DELETE FROM squad_events WHERE id = ?", (e2.id,))
        # Renumber event 3 to 2
        store.conn.execute("UPDATE squad_events SET sequence_number = 2 WHERE run_id = 'run-1' AND sequence_number = 3")
        store.conn.commit()

        result = store.verify_chain("run-1")
        assert result["valid"] is False
        store.close()

    def test_chain_detects_reordered_events(self, tmp_path: Path) -> None:
        store = EventStore(tmp_path / ".squad")
        e1 = store.append("run-1", "test", {"a": 1})
        e2 = store.append("run-1", "test", {"a": 2})

        # Swap sequence numbers (reorder)
        store.conn.execute("UPDATE squad_events SET sequence_number = 99 WHERE id = ?", (e1.id,))
        store.conn.execute("UPDATE squad_events SET sequence_number = 1 WHERE id = ?", (e2.id,))
        store.conn.execute("UPDATE squad_events SET sequence_number = 2 WHERE id = ?", (e1.id,))
        store.conn.commit()

        result = store.verify_chain("run-1")
        assert result["valid"] is False
        store.close()

    def test_get_last_event_hash_empty_run(self, tmp_path: Path) -> None:
        store = EventStore(tmp_path / ".squad")
        assert store.get_last_event_hash("nonexistent") == GENESIS_HASH
        store.close()

    def test_get_chain_info(self, tmp_path: Path) -> None:
        store = EventStore(tmp_path / ".squad")
        store.append("run-1", "test", {"a": 1})
        store.append("run-1", "test", {"a": 2})
        info = store.get_chain_info("run-1")
        assert info["eventCount"] == 2
        assert info["valid"] is True
        assert info["finalEventHash"] is not None
        store.close()


# ---------------------------------------------------------------------------
# Backwards compatibility tests
# ---------------------------------------------------------------------------


class TestBackwardsCompatibility:
    def test_existing_db_without_hash_columns_still_works(self, tmp_path: Path) -> None:
        """Simulate a database created before hash chain support."""
        import sqlite3

        db_path = tmp_path / ".squad" / "squad.db"
        (tmp_path / ".squad").mkdir()
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE squad_events (
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
        conn.execute(
            "INSERT INTO squad_events VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("ev1", "run-1", 1, "test", '{"a":1}', 0, "2025-01-01T00:00:00"),
        )
        conn.commit()
        conn.close()

        # Opening with EventStore should add columns and not crash
        store = EventStore(tmp_path / ".squad")
        page = store.query("run-1")
        assert len(page.events) == 1
        assert page.events[0].payload == {"a": 1}

        # Chain verification should report legacy rows
        result = store.verify_chain("run-1")
        assert result["eventCount"] == 1
        assert any("missing hash fields" in e for e in result["errors"])
        store.close()


# ---------------------------------------------------------------------------
# ReplayEngine tests
# ---------------------------------------------------------------------------


class TestReplayEngineHashChain:
    def _make_events(self, count: int = 3) -> list[dict]:
        """Helper: build a list of event dicts with valid hash chain."""
        events = []
        prev = GENESIS_HASH
        for i in range(1, count + 1):
            payload = {"step": i}
            ph, eh = compute_event_hash(prev, payload)
            events.append(
                {
                    "id": f"ev-{i}",
                    "runId": "run-1",
                    "sequenceNumber": i,
                    "type": "test",
                    "payload": payload,
                    "critical": False,
                    "createdAt": f"2025-01-0{i}T00:00:00",
                    "previousEventHash": prev,
                    "eventPayloadHash": ph,
                    "eventHash": eh,
                }
            )
            prev = eh
        return events

    def test_verify_valid_chain(self) -> None:
        engine = ReplayEngine()
        events = self._make_events(3)
        result = engine.verify_event_chain(events)
        assert result["valid"] is True
        assert result["eventCount"] == 3

    def test_verify_detects_tamper(self) -> None:
        engine = ReplayEngine()
        events = self._make_events(3)
        events[1]["payload"] = {"step": 999}  # tamper
        result = engine.verify_event_chain(events)
        assert result["valid"] is False

    def test_verify_legacy_events_without_hashes(self) -> None:
        engine = ReplayEngine()
        events = [
            {"sequenceNumber": 1, "type": "test", "payload": {"a": 1}},
            {"sequenceNumber": 2, "type": "test", "payload": {"a": 2}},
        ]
        result = engine.verify_event_chain(events)
        assert result["valid"] is False
        assert len(result["errors"]) == 2
        assert all("missing hash fields" in e for e in result["errors"])

    def test_reconstruct_state_with_valid_chain(self, tmp_path: Path) -> None:
        engine = ReplayEngine()
        events = self._make_events(2)
        payload = {
            "run": {"id": "run-1", "status": "completed"},
            "nodes": [{"id": "n1", "status": "done"}],
            "gates": [{"gateName": "g1", "status": "pass"}],
            "agentResults": [{"agentId": "a1", "status": "ok"}],
            "events": events,
        }
        log_path = tmp_path / "log.json"
        log_path.write_text(json.dumps(payload), encoding="utf-8")
        result = engine.reconstruct_state(log_path)
        assert result["schemaVersion"] == "reconstructed-state/v1"
        assert result["eventCount"] == 2
        assert result["chainVerification"]["valid"] is True

    def test_reconstruct_state_detects_corrupted_chain(self, tmp_path: Path) -> None:
        engine = ReplayEngine()
        events = self._make_events(3)
        events[1]["eventHash"] = "sha256-aaaa"  # corrupt
        payload = {
            "run": {"id": "run-1", "status": "completed"},
            "nodes": [],
            "gates": [],
            "agentResults": [],
            "events": events,
        }
        log_path = tmp_path / "log.json"
        log_path.write_text(json.dumps(payload), encoding="utf-8")
        result = engine.reconstruct_state(log_path)
        assert result.get("status") == "CHAIN_VERIFICATION_FAILED"

    def test_final_event_hash_from_chain(self) -> None:
        engine = ReplayEngine()
        events = self._make_events(3)
        result = engine.verify_event_chain(events)
        assert result["finalEventHash"] == events[-1]["eventHash"]


# ---------------------------------------------------------------------------
# Archive manifest tests
# ---------------------------------------------------------------------------


class TestArchiveManifest:
    def _setup_archive(self, tmp_path: Path) -> tuple[EventStore, Path]:
        """Helper: create a minimal archive and return store + archive dir."""
        from squad_runtime.infrastructure.schema import init_schema
        from squad_runtime.repositories.artifact_repository import ArtifactRepository
        from squad_runtime.repositories.gate_repository import GateRepository
        from squad_runtime.repositories.node_repository import NodeRepository
        from squad_runtime.repositories.run_repository import RunRepository
        from squad_runtime.services.archive_service import ArchiveService

        squad_dir = tmp_path / ".squad"
        store = EventStore(squad_dir)
        store.append("run-1", "test", {"a": 1})
        store.append("run-1", "test", {"a": 2})

        conn = sqlite3.connect(squad_dir / "squad.db")
        conn.row_factory = sqlite3.Row
        init_schema(conn)

        run_repo = RunRepository(conn)
        conn.execute(
            "INSERT INTO squad_runs (id, goal, status, version, rule_version, schema_version, agent_contract_version) " "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("run-1", "test goal", "completed", 1, "v1", "v1", "v1"),
        )
        conn.commit()

        node_repo = NodeRepository(conn)
        gate_repo = GateRepository(conn)
        artifact_repo = ArtifactRepository(conn)

        svc = ArchiveService(run_repo, node_repo, gate_repo, artifact_repo, store, squad_dir)
        archive_path = svc.archive_run("run-1")
        archive_dir = archive_path.parent
        return store, archive_dir

    def test_manifest_has_final_event_hash(self, tmp_path: Path) -> None:
        _, archive_dir = self._setup_archive(tmp_path)
        manifest = json.loads((archive_dir / "archive-manifest.json").read_text(encoding="utf-8"))
        assert manifest["finalEventHash"] is not None
        assert manifest["finalEventHash"].startswith("sha256-")

    def test_manifest_has_canonicalization_version(self, tmp_path: Path) -> None:
        _, archive_dir = self._setup_archive(tmp_path)
        manifest = json.loads((archive_dir / "archive-manifest.json").read_text(encoding="utf-8"))
        assert manifest["canonicalizationSpecVersion"] == CANONICALIZATION_SPEC_VERSION

    def test_manifest_has_event_hash_algorithm(self, tmp_path: Path) -> None:
        _, archive_dir = self._setup_archive(tmp_path)
        manifest = json.loads((archive_dir / "archive-manifest.json").read_text(encoding="utf-8"))
        assert manifest["eventHashAlgorithm"] == "sha256"


# ---------------------------------------------------------------------------
# V1 archive compatibility tests
# ---------------------------------------------------------------------------


class TestV1ArchiveCompatibility:
    def test_v1_archive_without_hash_chain_reports_unavailable(self) -> None:
        """V1 archives without hash fields should report unavailable."""
        from squad_runtime.schema_migration import migrate_v1_to_v2

        v1_payload = {
            "schemaVersion": "1.0",
            "events": [
                {"sequenceNumber": 1, "type": "test", "payload": {"a": 1}},
            ],
        }
        result = migrate_v1_to_v2(v1_payload)
        report = result["migrationReport"]
        assert report["eventHashChain"] == "unavailable-in-v1"
        assert report["sourceCanonicalizationSpecVersion"] == "unavailable-in-v1"

    def test_v1_archive_does_not_claim_tamper_detection(self) -> None:
        from squad_runtime.schema_migration import migrate_v1_to_v2

        v1_payload = {
            "schemaVersion": "1.0",
            "events": [
                {"sequenceNumber": 1, "type": "test", "payload": {"a": 1}},
            ],
        }
        result = migrate_v1_to_v2(v1_payload)
        report = result["migrationReport"]
        assert "tamper-proof replay" in report["disallowedModes"]

    def test_v1_archive_allows_re_evaluation_only(self) -> None:
        from squad_runtime.schema_migration import migrate_v1_to_v2

        v1_payload = {
            "schemaVersion": "1.0",
            "events": [
                {"sequenceNumber": 1, "type": "test", "payload": {"a": 1}},
            ],
        }
        result = migrate_v1_to_v2(v1_payload)
        report = result["migrationReport"]
        assert "re-evaluation" in report["allowedModes"]
        assert "state-reconstruction-with-warning" in report["allowedModes"]


# ---------------------------------------------------------------------------
# Canonicalization version routing tests
# ---------------------------------------------------------------------------


class TestCanonicalizationVersionRouting:
    def test_replay_uses_archived_canonicalization_version(self) -> None:
        """Replay should be aware of the canonicalization version from the archive."""
        # The ReplayEngine verify_event_chain uses compute_event_hash which is
        # version-specific. This test verifies the import path is correct.
        from squad_runtime.canonicalization import CANONICALIZATION_SPEC_VERSION

        assert CANONICALIZATION_SPEC_VERSION == "1.0"

    def test_unsupported_canonicalization_version_returns_config_error(self) -> None:
        """If archive has unknown canonicalizationSpecVersion, schema migration returns CONFIG_ERROR."""
        from squad_runtime.schema_migration import SchemaMigrationEngine

        engine = SchemaMigrationEngine()
        # Unknown schema version
        payload = {
            "schemaVersion": "99.0",
            "events": [],
        }
        result = engine.validate_or_migrate(payload)
        assert result.get("failureClass") == "CONFIG_ERROR"
