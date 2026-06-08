#!/usr/bin/env python3
"""Lightweight mutation testing for squad_runtime canonicalization.py.

Bypasses mutmut's infrastructure issues (mutants/ dir PYTHONPATH problems)
by doing AST-level mutation directly and running pytest on each mutant.
"""

from __future__ import annotations

import ast
import hashlib
import json
import subprocess
import sys
import textwrap
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CANON_FILE = ROOT / "squad_runtime" / "canonicalization.py"
TEST_CMD = [sys.executable, "-m", "pytest", "tests/unit/test_event_hash_chain.py", "-q", "--tb=no"]


def mutate_source(source: str, tree: ast.AST) -> list[tuple[str, str]]:
    """Generate mutants by applying simple AST mutations."""
    mutants: list[tuple[str, str]] = []

    # Strategy 1: Replace return values with constants
    for node in ast.walk(tree):
        if isinstance(node, ast.Return) and node.value is not None:
            line = node.lineno
            # Mutant: replace return with None
            mutated = _replace_line(source, line, "        return None  # MUTANT")
            mutants.append((f"return_none_at_line_{line}", mutated))

    # Strategy 2: Negate boolean conditions
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            line = node.lineno
            mutated = _replace_line_with_negation(source, line)
            if mutated != source:
                mutants.append((f"negate_compare_at_line_{line}", mutated))

    # Strategy 3: Swap hash algorithm (sha256 -> md5)
    if "sha256" in source:
        mutated = source.replace("sha256", "md5")
        mutants.append(("swap_sha256_to_md5", mutated))

    # Strategy 4: Remove NFC normalization
    if "NFC" in source:
        mutated = source.replace('unicodedata.normalize("NFC", value)', 'value')
        mutants.append(("remove_nfc_normalization", mutated))

    # Strategy 5: Remove path normalization
    if 'replace("\\\\", "/")' in source:
        mutated = source.replace('replace("\\\\", "/")', 'replace("/", "\\\\")')
        mutants.append(("reverse_path_normalization", mutated))

    # Strategy 6: Remove sort_keys from json.dumps
    if "sort_keys=True" in source:
        mutated = source.replace("sort_keys=True", "sort_keys=False")
        mutants.append(("remove_sort_keys", mutated))

    # Strategy 7: Change separators
    if 'separators=(",", ":")' in source:
        mutated = source.replace('separators=(",", ":")', 'separators=(", ", ": ")')
        mutants.append(("change_separators", mutated))

    return mutants


def _replace_line(source: str, line_no: int, new_content: str) -> str:
    lines = source.splitlines(keepends=True)
    if 0 < line_no <= len(lines):
        indent = len(lines[line_no - 1]) - len(lines[line_no - 1].lstrip())
        lines[line_no - 1] = " " * indent + new_content.strip() + "\n"
    return "".join(lines)


def _replace_line_with_negation(source: str, line_no: int) -> str:
    lines = source.splitlines(keepends=True)
    if 0 < line_no <= len(lines):
        line = lines[line_no - 1]
        if " == " in line:
            lines[line_no - 1] = line.replace(" == " , " != ", 1)
        elif " != " in line:
            lines[line_no - 1] = line.replace(" != ", " == ", 1)
        elif " in " in line:
            lines[line_no - 1] = line.replace(" in ", " not in ", 1)
        else:
            return source
        return "".join(lines)
    return source


def run_test_with_mutant(mutant_source: str, mutant_name: str) -> bool:
    """Write mutant, run tests, return True if tests still pass (mutant survived)."""
    backup = CANON_FILE.read_text(encoding="utf-8")
    try:
        CANON_FILE.write_text(mutant_source, encoding="utf-8")
        result = subprocess.run(
            TEST_CMD,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        return False  # Timeout = tests hung = killed
    finally:
        CANON_FILE.write_text(backup, encoding="utf-8")


def main():
    source = CANON_FILE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    mutants = mutate_source(source, tree)

    print(f"[mutation] Generated {len(mutants)} mutants for canonicalization.py")

    killed = 0
    survived = 0
    errors = 0
    results_list = []

    for name, mutant_source in mutants:
        print(f"  Testing: {name}...", end=" ", flush=True)
        try:
            survived_flag = run_test_with_mutant(mutant_source, name)
            if survived_flag:
                survived += 1
                status = "survived"
                print("SURVIVED ❌")
            else:
                killed += 1
                status = "killed"
                print("KILLED ✅")
        except Exception as exc:
            errors += 1
            status = "error"
            print(f"ERROR: {exc}")
        results_list.append({"name": name, "status": status})

    total = killed + survived
    score = (killed / total * 100) if total > 0 else 0.0

    summary = {
        "schemaVersion": "1.0",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "module": "squad_runtime/canonicalization.py",
        "totalMutants": total,
        "killed": killed,
        "survived": survived,
        "errors": errors,
        "score": round(score, 2),
        "threshold": 60,
        "passed": score >= 60,
        "exitCode": 0 if score >= 60 else 1,
        "mutants": results_list,
    }

    print(f"\n[mutation] Score: {score:.1f}% ({killed}/{total} killed)")
    print(f"[mutation] Status: {'PASS' if summary['passed'] else 'FAIL'}")

    return summary


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=None, help="Output JSON path")
    args = parser.parse_args()

    summary = main()

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        print(f"[mutation] Written to {output_path}")

    sys.exit(summary["exitCode"])
