"""Tests for llm_session_started / llm_session_completed lifecycle events.

Verifies that every code path in provider.execute() that emits
llm_session_started also emits llm_session_completed before returning.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from squad_runtime.agent_registry import AgentProfile
from squad_runtime.providers.base import ProviderHealth
from squad_runtime.providers.impl import FakeCliProvider, LocalCliProvider
from squad_runtime.providers.rate_limiter import (
    ProviderRateLimitConfig,
    ProviderRateLimiter,
)
from squad_runtime.runtime import Runtime

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_profile(agent_id: str = "test-agent") -> AgentProfile:
    return AgentProfile(
        agent_id=agent_id,
        display_name="Test Agent",
        role="testing",
        profile_version="profile-v1",
        provider="test_provider",
        output_contract="AgentResult",
    )


def _make_provider(**overrides) -> LocalCliProvider:
    limiter = ProviderRateLimiter(
        {"test_provider": ProviderRateLimitConfig(0.0, 30.0, 30.0, 1)},
        clock=lambda: 0.0,
        sleeper=lambda _: None,
    )
    defaults = dict(
        name="test_provider",
        executable="nonexistent_binary_for_test",
        command_args=["--version"],
        provider_type="real_llm",
        identity_verified=False,
        timeout_sec=60.0,
        rate_limiter=limiter,
    )
    defaults.update(overrides)
    return LocalCliProvider(**defaults)


def _setup_runtime_and_node(tmp_path: Path):
    runtime = Runtime.create(tmp_path / ".squad")
    run = runtime.create_run("test lifecycle events")
    node = runtime.create_node(run.id, "Test task", "backend", "test-agent")
    return runtime, run, node


def _events_of_type(events, run_id: str, event_type: str) -> list[dict]:
    page = events.query(run_id)
    return [e.payload for e in page.events if e.type == event_type]


# ---------------------------------------------------------------------------
# FakeCliProvider
# ---------------------------------------------------------------------------


class TestFakeCliProviderLifecycle:
    def test_fake_cli_records_started_and_completed(self, tmp_path: Path):
        runtime, run, node = _setup_runtime_and_node(tmp_path)
        profile = _make_profile()

        provider = FakeCliProvider()
        result = provider.execute(runtime, node, profile)

        assert result is not None

        started = _events_of_type(runtime.events, run.id, "llm_session_started")
        completed = _events_of_type(runtime.events, run.id, "llm_session_completed")

        assert len(started) == 1
        assert len(completed) == 1
        assert started[0]["dispatchId"] == completed[0]["dispatchId"]
        assert completed[0]["provider"] == "fake_cli"


# ---------------------------------------------------------------------------
# LocalCliProvider: provider_blocked
# ---------------------------------------------------------------------------


class TestProviderBlockedLifecycle:
    def test_unavailable_records_completed_provider_blocked(self, tmp_path: Path):
        runtime, run, node = _setup_runtime_and_node(tmp_path)
        profile = _make_profile()

        provider = _make_provider()
        with patch.object(provider, "health", return_value=ProviderHealth("test_provider", False, "not found")):
            result = provider.execute(runtime, node, profile)

        assert result is None

        started = _events_of_type(runtime.events, run.id, "llm_session_started")
        completed = _events_of_type(runtime.events, run.id, "llm_session_completed")
        blocked = _events_of_type(runtime.events, run.id, "provider_blocked")

        assert len(started) == 1
        assert len(completed) == 1
        assert len(blocked) == 1
        assert completed[0]["outcome"] == "provider_blocked"
        assert started[0]["dispatchId"] == completed[0]["dispatchId"]


# ---------------------------------------------------------------------------
# LocalCliProvider: provider_timeout
# ---------------------------------------------------------------------------


class TestProviderTimeoutLifecycle:
    def test_timeout_records_completed_provider_timeout(self, tmp_path: Path):
        runtime, run, node = _setup_runtime_and_node(tmp_path)
        profile = _make_profile()

        provider = _make_provider()
        with (
            patch.object(provider, "health", return_value=ProviderHealth("test_provider", True, "ok", "real_llm", True)),
            patch.object(provider._runner, "run", return_value=None),
        ):
            result = provider.execute(runtime, node, profile)

        assert result is None

        started = _events_of_type(runtime.events, run.id, "llm_session_started")
        completed = _events_of_type(runtime.events, run.id, "llm_session_completed")
        timeout_ev = _events_of_type(runtime.events, run.id, "agent_timeout")

        assert len(started) == 1
        assert len(completed) == 1
        assert len(timeout_ev) == 1
        assert completed[0]["outcome"] == "provider_timeout"
        assert started[0]["dispatchId"] == completed[0]["dispatchId"]


# ---------------------------------------------------------------------------
# LocalCliProvider: provider_rate_limited
# ---------------------------------------------------------------------------


class TestProviderRateLimitedLifecycle:
    def test_rate_limited_records_completed_rate_limited(self, tmp_path: Path):
        runtime, run, node = _setup_runtime_and_node(tmp_path)
        profile = _make_profile()

        provider = _make_provider()

        fake_completed = MagicMock()
        fake_completed.returncode = 1
        fake_completed.stdout = ""
        fake_completed.stderr = "429 Too Many Requests"

        with (
            patch.object(provider, "health", return_value=ProviderHealth("test_provider", True, "ok", "real_llm", True)),
            patch.object(provider._runner, "run", return_value=fake_completed),
        ):
            result = provider.execute(runtime, node, profile)

        assert result is None

        started = _events_of_type(runtime.events, run.id, "llm_session_started")
        completed = _events_of_type(runtime.events, run.id, "llm_session_completed")
        rate_limited = _events_of_type(runtime.events, run.id, "provider_rate_limited")

        assert len(started) == 1
        assert len(completed) == 1
        assert len(rate_limited) == 1
        assert completed[0]["outcome"] == "provider_rate_limited"
        assert started[0]["dispatchId"] == completed[0]["dispatchId"]


# ---------------------------------------------------------------------------
# LocalCliProvider: invalid_agent_result (non-zero exit code, no rate limit)
# ---------------------------------------------------------------------------


class TestInvalidAgentResultLifecycle:
    def test_nonzero_exit_no_rate_limit_records_completed(self, tmp_path: Path):
        runtime, run, node = _setup_runtime_and_node(tmp_path)
        profile = _make_profile()

        provider = _make_provider()
        # Rate limiter with no config for our provider => won't rate-limit
        provider.rate_limiter = ProviderRateLimiter({})

        fake_completed = MagicMock()
        fake_completed.returncode = 2
        fake_completed.stdout = "garbage"
        fake_completed.stderr = "some error"

        with (
            patch.object(provider, "health", return_value=ProviderHealth("test_provider", True, "ok", "real_llm", True)),
            patch.object(provider._runner, "run", return_value=fake_completed),
        ):
            result = provider.execute(runtime, node, profile)

        assert result is None

        started = _events_of_type(runtime.events, run.id, "llm_session_started")
        completed = _events_of_type(runtime.events, run.id, "llm_session_completed")

        assert len(started) == 1
        assert len(completed) == 1
        assert completed[0]["outcome"] == "invalid_agent_result"

    def test_invalid_output_records_completed(self, tmp_path: Path):
        """When result parser returns None (no valid JSON)."""
        runtime, run, node = _setup_runtime_and_node(tmp_path)
        profile = _make_profile()

        provider = _make_provider()
        provider.rate_limiter = ProviderRateLimiter({})

        fake_completed = MagicMock()
        fake_completed.returncode = 0
        fake_completed.stdout = "not json at all"
        fake_completed.stderr = ""

        with (
            patch.object(provider, "health", return_value=ProviderHealth("test_provider", True, "ok", "real_llm", True)),
            patch.object(provider._runner, "run", return_value=fake_completed),
            patch.object(provider._result_parser, "read_result_payload", return_value=None),
        ):
            result = provider.execute(runtime, node, profile)

        assert result is None

        completed = _events_of_type(runtime.events, run.id, "llm_session_completed")
        assert len(completed) == 1
        assert completed[0]["outcome"] == "invalid_agent_result"

    def test_type_error_on_result_construction_records_completed(self, tmp_path: Path):
        """When AgentResult(**payload) raises TypeError."""
        runtime, run, node = _setup_runtime_and_node(tmp_path)
        profile = _make_profile()

        provider = _make_provider()
        provider.rate_limiter = ProviderRateLimiter({})

        fake_completed = MagicMock()
        fake_completed.returncode = 0
        fake_completed.stdout = "{}"
        fake_completed.stderr = ""

        with (
            patch.object(provider, "health", return_value=ProviderHealth("test_provider", True, "ok", "real_llm", True)),
            patch.object(provider._runner, "run", return_value=fake_completed),
            patch.object(provider._result_parser, "read_result_payload", return_value={"bad": "payload"}),
        ):
            result = provider.execute(runtime, node, profile)

        assert result is None

        completed = _events_of_type(runtime.events, run.id, "llm_session_completed")
        assert len(completed) == 1
        assert completed[0]["outcome"] == "invalid_agent_result"

    def test_metadata_mismatch_records_completed(self, tmp_path: Path):
        """When taskNodeId or agentId doesn't match."""
        runtime, run, node = _setup_runtime_and_node(tmp_path)
        profile = _make_profile()

        provider = _make_provider()
        provider.rate_limiter = ProviderRateLimiter({})

        mismatched_payload = {
            "taskNodeId": "wrong-node-id",
            "agentId": "wrong-agent",
            "status": "pass",
            "summary": "test",
            "evidence": [],
            "artifacts": [],
            "risks": [],
            "nextActions": [],
            "confidence": 0.9,
            "workedAgainstCheckpoint": node.checkpoint_id,
            "agentContractVersion": "v1",
        }

        fake_completed = MagicMock()
        fake_completed.returncode = 0
        fake_completed.stdout = json.dumps(mismatched_payload)
        fake_completed.stderr = ""

        with (
            patch.object(provider, "health", return_value=ProviderHealth("test_provider", True, "ok", "real_llm", True)),
            patch.object(provider._runner, "run", return_value=fake_completed),
        ):
            result = provider.execute(runtime, node, profile)

        assert result is None

        completed = _events_of_type(runtime.events, run.id, "llm_session_completed")
        assert len(completed) == 1
        assert completed[0]["outcome"] == "invalid_agent_result"

    def test_validation_failure_records_completed(self, tmp_path: Path):
        """When validate_agent_result returns invalid."""
        runtime, run, node = _setup_runtime_and_node(tmp_path)
        profile = _make_profile()

        provider = _make_provider()
        provider.rate_limiter = ProviderRateLimiter({})

        valid_payload = {
            "taskNodeId": node.id,
            "agentId": profile.agent_id,
            "status": "pass",
            "summary": "test",
            "evidence": [],
            "artifacts": [],
            "risks": [],
            "nextActions": [],
            "confidence": 0.9,
            "workedAgainstCheckpoint": node.checkpoint_id,
            "agentContractVersion": "v1",
        }

        fake_completed = MagicMock()
        fake_completed.returncode = 0
        fake_completed.stdout = json.dumps(valid_payload)
        fake_completed.stderr = ""

        from squad_runtime.agent_contracts import AgentResultValidation

        with (
            patch.object(provider, "health", return_value=ProviderHealth("test_provider", True, "ok", "real_llm", True)),
            patch.object(provider._runner, "run", return_value=fake_completed),
            patch(
                "squad_runtime.providers.impl.validate_agent_result",
                return_value=AgentResultValidation(valid=False, errors=["test_error"]),
            ),
        ):
            result = provider.execute(runtime, node, profile)

        assert result is None

        completed = _events_of_type(runtime.events, run.id, "llm_session_completed")
        assert len(completed) == 1
        assert completed[0]["outcome"] == "invalid_agent_result"


# ---------------------------------------------------------------------------
# LocalCliProvider: checkpoint_mismatch
# ---------------------------------------------------------------------------


class TestCheckpointMismatchLifecycle:
    def test_checkpoint_mismatch_records_completed(self, tmp_path: Path):
        runtime, run, node = _setup_runtime_and_node(tmp_path)
        profile = _make_profile()

        provider = _make_provider()
        provider.rate_limiter = ProviderRateLimiter({})

        wrong_checkpoint_payload = {
            "taskNodeId": node.id,
            "agentId": profile.agent_id,
            "status": "pass",
            "summary": "test",
            "evidence": [],
            "artifacts": [],
            "risks": [],
            "nextActions": [],
            "confidence": 0.9,
            "workedAgainstCheckpoint": "wrong-checkpoint-id",
            "agentContractVersion": "v1",
        }

        fake_completed = MagicMock()
        fake_completed.returncode = 0
        fake_completed.stdout = json.dumps(wrong_checkpoint_payload)
        fake_completed.stderr = ""

        with (
            patch.object(provider, "health", return_value=ProviderHealth("test_provider", True, "ok", "real_llm", True)),
            patch.object(provider._runner, "run", return_value=fake_completed),
        ):
            result = provider.execute(runtime, node, profile)

        assert result is None

        completed = _events_of_type(runtime.events, run.id, "llm_session_completed")
        checkpoint_ev = _events_of_type(runtime.events, run.id, "checkpoint_mismatch")

        assert len(completed) == 1
        assert len(checkpoint_ev) == 1
        assert completed[0]["outcome"] == "checkpoint_mismatch"


# ---------------------------------------------------------------------------
# Full data log invariant
# ---------------------------------------------------------------------------


class TestFullDataLogLifecycleInvariant:
    def test_every_started_has_matching_completed(self, tmp_path: Path):
        """Run a successful dispatch via FakeCliProvider and verify the
        lifecycle invariant: every llm_session_started has a matching
        llm_session_completed with the same dispatchId."""
        runtime, run, node = _setup_runtime_and_node(tmp_path)
        profile = _make_profile()

        provider = FakeCliProvider()
        provider.execute(runtime, node, profile)

        started = _events_of_type(runtime.events, run.id, "llm_session_started")
        completed = _events_of_type(runtime.events, run.id, "llm_session_completed")

        assert len(started) == len(completed), "Mismatched started/completed counts"

        started_ids = {e["dispatchId"] for e in started}
        completed_ids = {e["dispatchId"] for e in completed}
        assert started_ids == completed_ids, "dispatchId sets differ between started and completed"

    def test_failed_dispatch_also_satisfies_invariant(self, tmp_path: Path):
        """Run a dispatch that fails (provider_blocked) and verify the
        lifecycle invariant still holds."""
        runtime, run, node = _setup_runtime_and_node(tmp_path)
        profile = _make_profile()

        provider = _make_provider()
        with patch.object(provider, "health", return_value=ProviderHealth("test_provider", False, "down")):
            provider.execute(runtime, node, profile)

        started = _events_of_type(runtime.events, run.id, "llm_session_started")
        completed = _events_of_type(runtime.events, run.id, "llm_session_completed")

        assert len(started) == 1
        assert len(completed) == 1
        assert started[0]["dispatchId"] == completed[0]["dispatchId"]
