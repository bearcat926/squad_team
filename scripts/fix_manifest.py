#!/usr/bin/env python3
"""Fix final-artifact-manifest.json: correct paths, recompute hashes, fix sidecars."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(r"E:\Project\squad-runtime-index-mirror")
BASE = Path("artifacts/phase7/3be2fd82ba571270a13087e5a12f2a9d336030c3")
FULL_BASE = PROJECT_ROOT / BASE

# The artifacts to track (relative to BASE)
ARTIFACT_SPECS = [
    # (artifactId, path relative to BASE, required)
    ("quality-baseline.json",        "quality/quality-baseline.json",             True),
    ("encoding-check.json",          "quality/encoding-check.json",               True),
    ("encoding-check.sha256",        "quality/encoding-check.sha256",             True),
    ("summary-phase7.json",          "final/summary-phase7.json",                 True),
    ("FULL_DATA_LOG-phase7.json",    "final/FULL_DATA_LOG-phase7.json",           True),
    ("archive-manifest.json",        "final/archive-manifest.json",               True),
    ("phase7-acceptance-report.md",  "final/phase7-acceptance-report.md",         True),
    ("mutation-summary.json",        "mutation/mutation-summary.json",            True),
    ("schema-migration-report.json", "schema-migration/schema-migration-report.json", True),
    ("symlink-runner-report.json",   "symlink/symlink-runner-report.json",        True),
    ("provider-doctor.json",         "scene-F/provider-doctor.json",              True),
]

# Also include the manifest itself (excluded from self-hash computation)
MANIFEST_REL = "final/final-artifact-manifest.json"
MANIFEST_SIDECAR_REL = "final/final-artifact-manifest.sha256"


def sha256_file(path: Path) -> str:
    return "sha256-" + hashlib.sha256(path.read_bytes()).hexdigest()


def detect_encoding(raw: bytes) -> str:
    if raw[:3] == b"\xef\xbb\xbf":
        return "utf-8-sig"
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return "utf-16"
    try:
        raw.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        pass
    try:
        raw.decode("gbk")
        return "gbk"
    except UnicodeDecodeError:
        pass
    return "latin-1"


def detect_line_ending(raw: bytes) -> str:
    text = raw.decode("utf-8", errors="replace")
    has_crlf = "\r\n" in text
    stripped = text.replace("\r\n", "")
    has_lone_cr = "\r" in stripped
    if has_crlf:
        return "crlf"
    if has_lone_cr:
        return "cr"
    return "lf"


def step1_generate_encoding_check():
    """Run phase7_check_encoding.py to produce encoding-check.json + sidecar."""
    print("=== Step 1: Generate encoding-check.json ===")
    script = PROJECT_ROOT / "scripts" / "phase7_check_encoding.py"
    out_dir = FULL_BASE / "quality"

    # Remove old encoding-check subdir if present (wrong location)
    wrong_dir = FULL_BASE / "quality" / "encoding-check"
    if wrong_dir.is_dir():
        import shutil
        shutil.rmtree(wrong_dir)
        print(f"  Removed wrong subdir: {wrong_dir}")

    # encoding-check.json might be a directory (bug from prior run) — fix it
    enc_json_path = out_dir / "encoding-check.json"
    if enc_json_path.is_dir():
        # Move contents out to a temp location, then remove the dir
        import shutil
        tmp = out_dir / "_enc_tmp"
        if tmp.exists():
            shutil.rmtree(tmp)
        enc_json_path.rename(tmp)
        print(f"  Moved dir {enc_json_path} -> {tmp}")
        # After script runs we'll clean up tmp

    subprocess.check_call(
        [sys.executable, str(script), str(FULL_BASE), "--output", str(out_dir)],
        cwd=str(PROJECT_ROOT),
    )

    # Clean up temp dir if it exists
    tmp = out_dir / "_enc_tmp"
    if tmp.is_dir():
        import shutil
        shutil.rmtree(tmp)
        print(f"  Cleaned up temp dir")

    # Verify output exists
    enc_json = out_dir / "encoding-check.json"
    enc_sha = out_dir / "encoding-check.sha256"
    assert enc_json.exists() and enc_json.is_file(), f"Missing {enc_json}"
    assert enc_sha.exists() and enc_sha.is_file(), f"Missing {enc_sha}"
    print(f"  encoding-check.json: {enc_json}")
    print(f"  encoding-check.sha256: {enc_sha}")


def step2_write_manifest():
    """Compute hashes and write the corrected manifest."""
    print("\n=== Step 2: Write corrected final-artifact-manifest.json ===")

    artifacts = []
    for artifact_id, rel_path, required in ARTIFACT_SPECS:
        full = FULL_BASE / rel_path
        if not full.exists():
            print(f"  WARNING: missing artifact {full}")
            continue
        raw = full.read_bytes()
        h = "sha256-" + hashlib.sha256(raw).hexdigest()
        enc = detect_encoding(raw)
        le = detect_line_ending(raw)
        # Full path from project root
        root_rel = str(BASE / rel_path).replace("\\", "/")
        artifacts.append({
            "artifactId": artifact_id,
            "path": root_rel,
            "sha256": h,
            "encoding": enc,
            "lineEnding": le,
            "required": required,
        })
        print(f"  {artifact_id}: {h}")

    manifest = {
        "schemaVersion": "1.0",
        "commitSha": "3be2fd82ba571270a13087e5a12f2a9d336030c3",
        "generatedAt": datetime.now(UTC).isoformat(),
        "artifactCount": len(artifacts),
        "artifacts": artifacts,
        "manifestSelfHashSidecar": {
            "path": str(BASE / "final/final-artifact-manifest.sha256").replace("\\", "/"),
            "note": "manifest self-hash is stored only in sidecar; no self sha256 is embedded here",
        },
    }

    manifest_path = FULL_BASE / "final" / "final-artifact-manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"\n  Manifest written: {manifest_path}")

    # Write sidecar (just the hash, one line)
    sidecar_path = FULL_BASE / "final" / "final-artifact-manifest.sha256"
    sidecar_path.write_text(
        sha256_file(manifest_path) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"  Sidecar written: {sidecar_path}")
    print(f"  Sidecar content: {sidecar_path.read_text().strip()}")


def step3_verify():
    """Verify everything."""
    print("\n=== Step 3: Verification ===")
    errors = []

    # Load manifest
    manifest_path = FULL_BASE / "final" / "final-artifact-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    # Check no self-hash embedded
    if "sha256" in manifest:
        errors.append("Manifest contains embedded sha256 (should not)")
    else:
        print("  OK: No embedded sha256 in manifest")

    # Read sidecar and compare
    sidecar_path = FULL_BASE / "final" / "final-artifact-manifest.sha256"
    sidecar_hash = sidecar_path.read_text().strip()
    actual_hash = sha256_file(manifest_path)
    if sidecar_hash == actual_hash:
        print(f"  OK: Sidecar matches manifest hash: {sidecar_hash}")
    else:
        errors.append(f"Sidecar mismatch: sidecar={sidecar_hash}, actual={actual_hash}")

    # Check sidecar format (just hash, no filename)
    if "  " in sidecar_hash:
        errors.append(f"Sidecar contains double-space (old format with filename): {sidecar_hash}")
    else:
        print("  OK: Sidecar format is hash-only (no filename)")

    # Verify all artifact paths and hashes
    for art in manifest["artifacts"]:
        full = PROJECT_ROOT / art["path"]
        if not full.exists():
            errors.append(f"Artifact missing: {art['path']}")
            continue
        actual = "sha256-" + hashlib.sha256(full.read_bytes()).hexdigest()
        if actual != art["sha256"]:
            errors.append(f"Hash mismatch for {art['path']}: manifest={art['sha256']}, actual={actual}")
        else:
            print(f"  OK: {art['artifactId']} hash matches")

    # Verify paths are full from root (not relative to final/)
    for art in manifest["artifacts"]:
        if art["path"].startswith("final/") or art["path"].startswith("quality/") or art["path"].startswith("mutation/"):
            errors.append(f"Path not rooted: {art['path']}")
            break
    else:
        print("  OK: All paths are relative to project root")

    # Check encoding-check sidecar too
    enc_sidecar = FULL_BASE / "quality" / "encoding-check.sha256"
    if enc_sidecar.exists():
        enc_sidecar_hash = enc_sidecar.read_text().strip()
        enc_json = FULL_BASE / "quality" / "encoding-check.json"
        enc_actual = sha256_file(enc_json)
        if enc_sidecar_hash == enc_actual:
            print(f"  OK: encoding-check sidecar matches: {enc_sidecar_hash}")
        else:
            errors.append(f"encoding-check sidecar mismatch")
        if "  " in enc_sidecar_hash:
            errors.append(f"encoding-check sidecar has old format")
        else:
            print("  OK: encoding-check sidecar format is hash-only")

    if errors:
        print(f"\n  ERRORS ({len(errors)}):")
        for e in errors:
            print(f"    - {e}")
        sys.exit(1)
    else:
        print("\n  ALL CHECKS PASSED")


if __name__ == "__main__":
    step1_generate_encoding_check()
    step2_write_manifest()
    step3_verify()
