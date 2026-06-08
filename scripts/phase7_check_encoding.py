#!/usr/bin/env python3
"""Phase 7 — Encoding compliance checker.

Scans a directory for text files and reports UTF-8 / BOM / CRLF status.
Writes encoding-check.json + encoding-check.sha256 sidecar.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

# ─── constants ──────────────────────────────────────────────────────────────

BINARY_EXTENSIONS = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".bmp",
        ".ico",
        ".webp",
        ".svg",
        ".mp3",
        ".mp4",
        ".wav",
        ".avi",
        ".mov",
        ".mkv",
        ".flac",
        ".ogg",
        ".zip",
        ".tar",
        ".gz",
        ".bz2",
        ".xz",
        ".7z",
        ".rar",
        ".pdf",
        ".doc",
        ".docx",
        ".xls",
        ".xlsx",
        ".ppt",
        ".pptx",
        ".exe",
        ".dll",
        ".so",
        ".dylib",
        ".o",
        ".obj",
        ".pyc",
        ".pyo",
        ".whl",
        ".egg",
        ".db",
        ".sqlite",
        ".sqlite3",
        ".woff",
        ".woff2",
        ".ttf",
        ".otf",
        ".eot",
        ".class",
        ".jar",
        ".war",
    }
)

SKIP_NAMES = frozenset({"encoding-check.json", "encoding-check.sha256"})


# ─── helpers ────────────────────────────────────────────────────────────────


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def sha256_bytes(data: bytes) -> str:
    return "sha256-" + hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def is_binary_path(path: Path) -> bool:
    if path.suffix.lower() in BINARY_EXTENSIONS:
        return True
    # Heuristic: read first 8 KB and check for null bytes
    try:
        chunk = path.read_bytes()[:8192]
        return b"\x00" in chunk
    except OSError:
        return True  # unreadable — treat as binary/skip


def detect_encoding(raw: bytes) -> str:
    """Best-effort encoding detection without external deps."""
    # Check for BOM first
    if raw[:3] == b"\xef\xbb\xbf":
        return "utf-8-sig"
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return "utf-16"

    # Try UTF-8
    try:
        raw.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        pass

    # Try GBK
    try:
        raw.decode("gbk")
        return "gbk"
    except UnicodeDecodeError:
        pass

    # Try latin-1 (always succeeds)
    return "latin-1"


def has_bom(raw: bytes) -> bool:
    return raw[:3] == b"\xef\xbb\xbf"


def line_ending(raw: bytes) -> str:
    """Return 'crlf', 'lf', or 'mixed'."""
    text = raw.decode("utf-8", errors="replace")
    has_crlf = "\r\n" in text
    # Strip CRLF then check for lone CR
    stripped = text.replace("\r\n", "")
    has_lone_cr = "\r" in stripped
    has_lf = "\n" in text
    if has_crlf and has_lf:
        return "crlf"  # dominant
    if has_crlf:
        return "crlf"
    if has_lone_cr:
        return "cr"
    return "lf"


# ─── git helper ─────────────────────────────────────────────────────────────


def git_commit_sha(cwd: str) -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            text=True,
            cwd=cwd,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return "no-git-repo"


# ─── main ───────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 7 encoding compliance checker")
    parser.add_argument("directory", help="Directory to scan")
    parser.add_argument("--output", required=True, help="Output directory for report")
    args = parser.parse_args()

    scan_dir = Path(args.directory).resolve()
    out_dir = Path(args.output).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    commit_sha = git_commit_sha(str(scan_dir))

    files_report: list[dict] = []

    for fpath in sorted(scan_dir.rglob("*")):
        if not fpath.is_file():
            continue
        rel = fpath.relative_to(scan_dir)
        rel_str = rel.as_posix()

        # Skip self-referential report files
        if rel_str in SKIP_NAMES:
            continue
        # Skip binary
        if is_binary_path(fpath):
            continue
        # Skip common non-text directories
        parts = rel.parts
        if any(p in parts for p in ("__pycache__", ".git", ".mypy_cache", ".ruff_cache", "node_modules", ".tox", ".eggs")):
            continue

        raw = fpath.read_bytes()
        encoding = detect_encoding(raw)
        bom = has_bom(raw)
        ending = line_ending(raw)
        file_hash = sha256_bytes(raw)

        is_utf8 = encoding in ("utf-8", "utf-8-sig")
        status = "pass" if (is_utf8 and not bom and ending == "lf") else "warn" if is_utf8 else "fail"

        files_report.append(
            {
                "path": rel_str,
                "encoding": encoding,
                "bom": bom,
                "lineEnding": ending,
                "sha256": file_hash,
                "status": status,
            }
        )

    report = {
        "schemaVersion": "1.0",
        "commitSha": commit_sha,
        "generatedAt": utc_now_iso(),
        "files": files_report,
        "selfHashSidecar": {
            "path": "encoding-check.sha256",
            "note": "encoding-check.json self hash is stored only in sidecar; no self sha256 is embedded here",
        },
    }

    report_path = out_dir / "encoding-check.json"
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    sidecar_path = out_dir / "encoding-check.sha256"
    sidecar_path.write_text(sha256_file(report_path) + "\n", encoding="utf-8", newline="\n")

    n_files = len(files_report)
    n_pass = sum(1 for f in files_report if f["status"] == "pass")
    n_warn = sum(1 for f in files_report if f["status"] == "warn")
    n_fail = sum(1 for f in files_report if f["status"] == "fail")
    print(f"[encoding] scanned {n_files} files: {n_pass} pass, {n_warn} warn, {n_fail} fail")
    print(f"[encoding] report written to {out_dir}")


if __name__ == "__main__":
    main()
