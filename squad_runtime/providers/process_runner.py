"""Subprocess execution for provider dispatches."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


class ProcessRunner:
    """Runs a subprocess for a provider dispatch, handling timeouts and errors."""

    def __init__(
        self,
        executable: str,
        command_args: list[str] | None = None,
        timeout_sec: float | None = None,
        extra_env: dict[str, str] | None = None,
    ):
        self.executable = executable
        self.command_args = command_args
        self.timeout_sec = timeout_sec if timeout_sec is not None else float(os.environ.get("SQUAD_PROVIDER_TIMEOUT_SEC", "600"))
        self.extra_env = extra_env or {}

    def command(self) -> list[str]:
        """Build the command list."""
        source = shutil.which(self.executable) or self.executable
        if self.command_args is not None:
            return [source, *self.command_args]
        return [
            source,
            "-p",
            "--bare",
            "--disable-slash-commands",
            "--system-prompt",
            "You are a JSON-only API. You have no tools. Never emit tool_call,"
            " function, markdown, commentary, or XML tags."
            " Return only the requested JSON object.",
            "--output-format",
            "json",
            "--no-session-persistence",
        ]

    def run(
        self,
        dispatch_dir: Path,
        prompt: str,
        env_overrides: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str] | None:
        """Execute the subprocess. Returns CompletedProcess or None on timeout."""
        command = self.command()
        env = os.environ.copy()
        env.update(self.extra_env)
        if env_overrides:
            env.update(env_overrides)
        try:
            return subprocess.run(
                command,
                cwd=dispatch_dir,
                env=env,
                input=prompt,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout_sec,
            )
        except subprocess.TimeoutExpired:
            return None

    def check_available(self) -> bool:
        """Check if the executable is available on PATH."""
        return shutil.which(self.executable) is not None
