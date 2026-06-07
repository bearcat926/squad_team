"""Unit tests for the PromptBuilder class."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from squad_runtime.providers.prompt_builder import PromptBuilder


@dataclass(frozen=True)
class FakeContext:
    agent_id: str = "test-agent"
    role: str = "tester"
    task_node_id: str = "node-1"
    task_goal: str = "Run tests"
    checkpoint_id: str = "ckp-1"
    forbidden_paths: tuple[str, ...] = (".squad/*",)
    runtime_facts: list[dict[str, Any]] = field(default_factory=list)
    dependency_summaries: list[dict[str, Any]] = field(default_factory=list)


def test_prompt_builder_includes_agent_info():
    builder = PromptBuilder()
    prompt = builder.build(FakeContext())
    assert "Agent: test-agent" in prompt
    assert "Role: tester" in prompt
    assert "Task Node ID: node-1" in prompt


def test_prompt_builder_includes_contract_requirement():
    builder = PromptBuilder()
    prompt = builder.build(FakeContext())
    assert "Runtime Output Contract: AgentResult" in prompt
    assert "Do not inspect files" in prompt


def test_prompt_builder_includes_forbidden_paths():
    builder = PromptBuilder()
    prompt = builder.build(FakeContext())
    assert ".squad/*" in prompt


def test_prompt_builder_includes_json_shape():
    builder = PromptBuilder()
    prompt = builder.build(FakeContext())
    assert '"taskNodeId"' in prompt
    assert '"agentId"' in prompt
    assert '"workedAgainstCheckpoint"' in prompt


def test_prompt_builder_rejects_acknowledgement_only_pass():
    builder = PromptBuilder()
    prompt = builder.build(FakeContext())
    assert "Do not return status pass for acknowledgement-only output" in prompt
    assert "ready to proceed" in prompt
    assert "return status blocked" in prompt
