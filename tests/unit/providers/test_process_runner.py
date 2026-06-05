"""Unit tests for the ProcessRunner class."""

from __future__ import annotations

import sys

from squad_runtime.providers.process_runner import ProcessRunner


def test_process_runner_command_with_custom_args():
    runner = ProcessRunner("python", command_args=["-c", "print(1)"])
    cmd = runner.command()
    assert "python" in cmd[0].lower()
    assert "-c" in cmd
    assert "print(1)" in cmd


def test_process_runner_command_default_claude_format():
    runner = ProcessRunner("claude")
    cmd = runner.command()
    assert "--bare" in cmd
    assert "--disable-slash-commands" in cmd
    assert "--output-format" in cmd
    assert "json" in cmd


def test_process_runner_check_available_for_real_executable():
    runner = ProcessRunner(sys.executable)
    assert runner.check_available() is True


def test_process_runner_check_available_for_missing():
    runner = ProcessRunner("definitely-not-a-real-executable-12345")
    assert runner.check_available() is False


def test_process_runner_default_timeout():
    runner = ProcessRunner("claude")
    assert runner.timeout_sec == 600


def test_process_runner_custom_timeout():
    runner = ProcessRunner("claude", timeout_sec=120)
    assert runner.timeout_sec == 120
