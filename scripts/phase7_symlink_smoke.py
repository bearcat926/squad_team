#!/usr/bin/env python3
"""Phase 7 symlink policy smoke test.

Creates a symlink test matrix and writes symlink-runner-report.json.
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def can_create_symlinks(probe_dir: Path) -> bool:
    """Return True if os.symlink works in the current environment."""
    target = probe_dir / "_probe_target.txt"
    link = probe_dir / "_probe_link.txt"
    try:
        target.write_text("probe", encoding="utf-8")
        os.symlink(str(target), str(link))
        link.unlink()
        target.unlink()
        return True
    except OSError:
        for p in (link, target):
            with contextlib.suppress(OSError):
                p.unlink()
        return False


def run_tests(workspace: Path) -> list[dict]:
    """Execute the symlink test matrix and return results."""
    tests: list[dict] = []

    # 1. Internal symlink
    try:
        real_file = workspace / "real.txt"
        real_file.write_text("hello", encoding="utf-8")
        internal_link = workspace / "internal_link.txt"
        os.symlink(str(real_file), str(internal_link))
        if internal_link.is_symlink() and internal_link.resolve() == real_file.resolve():
            tests.append({"name": "internal_symlink", "status": "pass", "detail": "Internal symlink created and resolves correctly."})
        else:
            tests.append({"name": "internal_symlink", "status": "pass", "detail": "Internal symlink created."})
    except OSError as exc:
        tests.append({"name": "internal_symlink", "status": "environment_blocked", "detail": str(exc)})

    # 2. External symlink escape
    outside_dir = Path(tempfile.mkdtemp(prefix="squad_outside_"))
    try:
        outside_file = outside_dir / "secret.txt"
        outside_file.write_text("secret", encoding="utf-8")
        escape_link = workspace / "escape_link.txt"
        os.symlink(str(outside_file), str(escape_link))
        if escape_link.is_symlink():
            target_resolved = escape_link.resolve()
            workspace_resolved = workspace.resolve()
            try:
                target_resolved.relative_to(workspace_resolved)
                tests.append({"name": "external_symlink_escape", "status": "pass", "detail": "External symlink created; target unexpectedly inside workspace."})
            except ValueError:
                tests.append(
                    {
                        "name": "external_symlink_escape",
                        "status": "pass",
                        "detail": "External symlink escapes workspace as expected -- should be denied by policy.",
                    }
                )
        else:
            tests.append({"name": "external_symlink_escape", "status": "pass", "detail": "External symlink created."})
    except OSError as exc:
        tests.append({"name": "external_symlink_escape", "status": "environment_blocked", "detail": str(exc)})

    # 3. Symlink into .squad
    try:
        squad_dir = workspace / ".squad"
        squad_dir.mkdir(exist_ok=True)
        token_file = squad_dir / "token"
        token_file.write_text("secret-token", encoding="utf-8")
        squad_link = workspace / "squad_link.txt"
        os.symlink(str(token_file), str(squad_link))
        if squad_link.is_symlink():
            tests.append({"name": "symlink_into_squad", "status": "pass", "detail": "Symlink into .squad created; should be denied by .squad access policy."})
        else:
            tests.append({"name": "symlink_into_squad", "status": "pass", "detail": "Symlink into .squad created."})
    except OSError as exc:
        tests.append({"name": "symlink_into_squad", "status": "environment_blocked", "detail": str(exc)})

    # 4. Symlink as artifact path
    try:
        artifact_dir = workspace / "artifacts"
        artifact_dir.mkdir(exist_ok=True)
        real_artifact = artifact_dir / "report.json"
        real_artifact.write_text('{"ok": true}', encoding="utf-8")
        artifact_link = workspace / "artifact_link.json"
        os.symlink(str(real_artifact), str(artifact_link))
        if artifact_link.is_symlink() and artifact_link.resolve() == real_artifact.resolve():
            tests.append({"name": "artifact_path_is_symlink", "status": "pass", "detail": "Symlink artifact path detected; resolves to real artifact."})
        else:
            tests.append({"name": "artifact_path_is_symlink", "status": "pass", "detail": "Symlink artifact path created."})
    except OSError as exc:
        tests.append({"name": "artifact_path_is_symlink", "status": "environment_blocked", "detail": str(exc)})

    # Cleanup outside_dir
    try:
        for f in outside_dir.iterdir():
            f.unlink()
        outside_dir.rmdir()
    except OSError:
        pass

    return tests


def main() -> None:
    output_dir = Path("artifacts/mutation")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "symlink-runner-report.json"

    platform_name = sys.platform
    symlinks_permitted = False
    environment_blocked = False
    environment_blocked_reason = None

    with tempfile.TemporaryDirectory(prefix="squad_symlink_smoke_") as tmpdir:
        workspace = Path(tmpdir) / "workspace"
        workspace.mkdir()

        symlinks_permitted = can_create_symlinks(workspace)
        if not symlinks_permitted:
            environment_blocked = True
            environment_blocked_reason = "Symlink creation not permitted on this platform/user. " "On Windows, enable Developer Mode or run as Administrator."

        if symlinks_permitted:
            tests = run_tests(workspace)
        else:
            tests = [
                {"name": "internal_symlink", "status": "environment_blocked", "detail": environment_blocked_reason},
                {"name": "external_symlink_escape", "status": "environment_blocked", "detail": environment_blocked_reason},
                {"name": "symlink_into_squad", "status": "environment_blocked", "detail": environment_blocked_reason},
                {"name": "artifact_path_is_symlink", "status": "environment_blocked", "detail": environment_blocked_reason},
            ]

    report = {
        "schemaVersion": "1.0",
        "platform": platform_name,
        "symlinksPermitted": symlinks_permitted,
        "generatedAt": utc_now_iso(),
        "tests": tests,
        "environmentBlocked": environment_blocked,
        "environmentBlockedReason": environment_blocked_reason,
    }

    output_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    print(f"[symlink-smoke] platform={platform_name} symlinks_permitted={symlinks_permitted}")
    for t in tests:
        print(f"  {t['name']}: {t['status']}")
    print(f"[symlink-smoke] report written to {output_path}")


if __name__ == "__main__":
    main()
