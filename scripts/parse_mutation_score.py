#!/usr/bin/env python3
"""Parse mutation testing results and enforce score threshold."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

THRESHOLD = 60


def parse_mutation_score(results_path: str) -> float:
    """Parse mutmut results output to extract kill rate."""
    content = Path(results_path).read_text(encoding="utf-8")
    # mutmut results format: "X/Y killed (Z%)"
    # or individual lines with survived/killed markers
    killed = len(re.findall(r"^Killed\b", content, re.MULTILINE))
    survived = len(re.findall(r"^Survived\b", content, re.MULTILINE))
    # Also check for timeout
    timeout = len(re.findall(r"^Timeout\b", content, re.MULTILINE))
    total = killed + survived + timeout
    if total == 0:
        return 0.0
    return ((killed + timeout) / total) * 100


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse mutation testing results and enforce score threshold")
    parser.add_argument("--results", default="artifacts/mutation/mutmut-results.txt")
    parser.add_argument("--output", default="artifacts/mutation/mutation-summary.json")
    parser.add_argument("--threshold", type=int, default=THRESHOLD)
    args = parser.parse_args()

    results_path = Path(args.results)
    if not results_path.exists():
        print(f"Warning: {results_path} not found, creating placeholder")
        score = 0.0
    else:
        score = parse_mutation_score(str(results_path))

    summary = {
        "schemaVersion": "1.0",
        "generatedAt": datetime.now(UTC).isoformat(),
        "score": round(score, 2),
        "threshold": args.threshold,
        "passed": score >= args.threshold,
        "rawReportPath": str(results_path),
        "exitCode": 0 if score >= args.threshold else 1,
    }

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    print(f"Mutation score: {score:.2f}% (threshold: {args.threshold}%)")
    print(f"Status: {'PASS' if summary['passed'] else 'FAIL'}")

    sys.exit(summary["exitCode"])


if __name__ == "__main__":
    main()
