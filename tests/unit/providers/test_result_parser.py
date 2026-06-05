"""Unit tests for the ResultParser class."""

from __future__ import annotations

import json
from pathlib import Path

from squad_runtime.providers.result_parser import ResultParser


def test_result_parser_reads_final_result_json(tmp_path: Path):
    parser = ResultParser()
    final_result = tmp_path / "final-result.json"
    payload = {"taskNodeId": "n1", "agentId": "a1", "status": "pass"}
    final_result.write_text(json.dumps(payload), encoding="utf-8")
    result = parser.read_result_payload(final_result, "ignored stdout")
    assert result == payload


def test_result_parser_falls_back_to_stdout(tmp_path: Path):
    parser = ResultParser()
    final_result = tmp_path / "nonexistent.json"
    payload = {"taskNodeId": "n1", "agentId": "a1", "status": "pass"}
    result = parser.read_result_payload(final_result, json.dumps(payload))
    assert result == payload


def test_result_parser_returns_none_for_empty(tmp_path: Path):
    parser = ResultParser()
    final_result = tmp_path / "nonexistent.json"
    assert parser.read_result_payload(final_result, "") is None
    assert parser.read_result_payload(final_result, "   ") is None


def test_result_parser_extracts_single_json_from_prose(tmp_path: Path):
    parser = ResultParser()
    final_result = tmp_path / "nonexistent.json"
    payload = {"taskNodeId": "n1", "status": "pass"}
    stdout = f"Here is the result:\n{json.dumps(payload)}\nDone."
    result = parser.read_result_payload(final_result, stdout)
    assert result == payload


def test_result_parser_unwraps_claude_cli_wrapper(tmp_path: Path):
    parser = ResultParser()
    final_result = tmp_path / "nonexistent.json"
    inner = {"taskNodeId": "n1", "status": "pass"}
    wrapper = {"type": "result", "subtype": "success", "result": json.dumps(inner)}
    result = parser.read_result_payload(final_result, json.dumps(wrapper))
    assert result == inner


def test_result_parser_rejects_multiple_json_objects(tmp_path: Path):
    parser = ResultParser()
    final_result = tmp_path / "nonexistent.json"
    stdout = '{"a":1}{"b":2}'
    result = parser.read_result_payload(final_result, stdout)
    assert result is None


def test_result_parser_handles_utf8_bom(tmp_path: Path):
    parser = ResultParser()
    final_result = tmp_path / "final-result.json"
    payload = {"taskNodeId": "n1", "status": "pass"}
    final_result.write_bytes(b"\xef\xbb\xbf" + json.dumps(payload).encode("utf-8"))
    result = parser.read_result_payload(final_result, "")
    assert result == payload
