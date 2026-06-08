#!/usr/bin/env python3
"""Phase 7 — Quality baseline collection.

Runs pytest, coverage, ruff, black, mypy, and ResourceWarning checks,
then emits quality-baseline.json plus raw log files.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

# ─── helpers ────────────────────────────────────────────────────────────────


def sha256_hex(data: str) -> str:
    return "sha256-" + hashlib.sha256(data.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    return "sha256-" + hashlib.sha256(path.read_bytes()).hexdigest()


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def normalize_lf(text: str) -> str:
    return text.replace("\r\n", "\n")


def run_cmd(command_id: str, cmd: list[str], cwd: str, *, required: bool = True):
    """Execute *cmd* and return a command-record dict."""
    start = time.time()
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=cwd,
        )
        exit_code = proc.returncode
        stdout_raw = proc.stdout
        stderr_raw = proc.stderr
    except Exception as exc:
        exit_code = -1
        stdout_raw = ""
        stderr_raw = str(exc)
    duration = round(time.time() - start, 2)

    stdout_text = normalize_lf(stdout_raw)
    stderr_text = normalize_lf(stderr_raw)

    stdout_path = f"{command_id}.stdout.txt"
    stderr_path = f"{command_id}.stderr.txt"

    return {
        "commandId": command_id,
        "command": " ".join(cmd),
        "exitCode": exit_code,
        "durationSeconds": duration,
        "stdoutPath": stdout_path,
        "stderrPath": stderr_path,
        "sha256": {
            "stdout": sha256_hex(stdout_text),
            "stderr": sha256_hex(stderr_text),
        },
        "required": required,
        "stdout_text": stdout_text,
        "stderr_text": stderr_text,
    }


# ─── git helpers ────────────────────────────────────────────────────────────


def git_info(cwd: str) -> tuple[str, bool]:
    """Return (commit_sha, dirty). Falls back gracefully outside a repo."""
    try:
        sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            text=True,
            cwd=cwd,
            stderr=subprocess.DEVNULL,
        ).strip()
        status = subprocess.check_output(
            ["git", "status", "--porcelain"],
            text=True,
            cwd=cwd,
            stderr=subprocess.DEVNULL,
        ).strip()
        return sha, bool(status)
    except Exception:
        return "no-git-repo", False


# ─── T0 encoding check ─────────────────────────────────────────────────────


def check_t0_encoding(out_dir: Path) -> dict:
    """Verify that every file written by this script is UTF-8, no BOM, LF."""
    results: list[dict] = []
    skip = {"encoding-check.json", "encoding-check.sha256"}
    for fpath in sorted(out_dir.iterdir()):
        if fpath.is_dir():
            continue
        if fpath.name in skip:
            continue
        raw = fpath.read_bytes()
        is_bom = raw[:3] == b"\xef\xbb\xbf"
        has_crlf = b"\r\n" in raw
        try:
            raw.decode("utf-8")
            enc_ok = True
        except UnicodeDecodeError:
            enc_ok = False

        status = "pass" if (enc_ok and not is_bom and not has_crlf) else "fail"
        results.append(
            {
                "path": fpath.name,
                "encoding": "utf-8" if enc_ok else "not-utf-8",
                "bom": is_bom,
                "lineEnding": "crlf" if has_crlf else "lf",
                "sha256": sha256_file(fpath),
                "status": status,
            }
        )

    return {
        "schemaVersion": "1.0",
        "commitSha": "",  # filled by caller
        "generatedAt": utc_now_iso(),
        "files": results,
    }


# ─── main ───────────────────────────────────────────────────────────────────

COMMANDS = [
    {
        "id": "pytest",
        "cmd": [sys.executable, "-m", "pytest", "tests", "-q"],
        "required": True,
    },
    {
        "id": "coverage",
        "cmd": [
            sys.executable,
            "-m",
            "pytest",
            "tests",
            "-q",
            "--cov=squad_runtime",
            "--cov-report=term-missing",
            "--cov-fail-under=90",
        ],
        "required": True,
    },
    {
        "id": "ruff",
        "cmd": [sys.executable, "-m", "ruff", "check", "."],
        "required": True,
    },
    {
        "id": "black",
        "cmd": [sys.executable, "-m", "black", "--check", "."],
        "required": True,
    },
    {
        "id": "mypy",
        "cmd": [sys.executable, "-m", "mypy", "squad_runtime"],
        "required": True,
    },
    {
        "id": "resource-warning",
        "cmd": [
            sys.executable,
            "-m",
            "pytest",
            "tests",
            "-q",
            "-W",
            "error::ResourceWarning",
        ],
        "required": False,
    },
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 7 quality baseline collector")
    parser.add_argument(
        "--output",
        required=True,
        help="Output directory for baseline artifacts",
    )
    args = parser.parse_args()

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    project_root = str(Path(__file__).resolve().parent.parent)

    commit_sha, dirty = git_info(project_root)

    # ── run each command ────────────────────────────────────────────────
    records: list[dict] = []
    for entry in COMMANDS:
        rec = run_cmd(entry["id"], entry["cmd"], project_root, required=entry["required"])
        # persist raw logs
        (out_dir / rec["stdoutPath"]).write_text(rec["stdout_text"], encoding="utf-8", newline="\n")
        (out_dir / rec["stderrPath"]).write_text(rec["stderr_text"], encoding="utf-8", newline="\n")
        # strip transient text before serialising
        clean = {k: v for k, v in rec.items() if k not in ("stdout_text", "stderr_text")}
        records.append(clean)
        print(f"[phase7] {rec['commandId']} exit={rec['exitCode']} {rec['durationSeconds']}s")

    # ── quality-baseline.json ───────────────────────────────────────────
    baseline = {
        "schemaVersion": "1.0",
        "commitSha": commit_sha,
        "dirty": dirty,
        "generatedAt": utc_now_iso(),
        "commands": records,
    }
    baseline_path = out_dir / "quality-baseline.json"
    baseline_path.write_text(
        json.dumps(baseline, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    # ── T0 encoding check ──────────────────────────────────────────────
    enc_report = check_t0_encoding(out_dir)
    enc_report["commitSha"] = commit_sha
    enc_path = out_dir / "encoding-check.json"
    enc_path.write_text(
        json.dumps(enc_report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    # sidecar hash for encoding-check.json itself
    sidecar_path = out_dir / "encoding-check.sha256"
    sidecar_path.write_text(sha256_file(enc_path) + "\n", encoding="utf-8", newline="\n")

    print(f"[phase7] baseline written to {out_dir}")


if __name__ == "__main__":
    main()
