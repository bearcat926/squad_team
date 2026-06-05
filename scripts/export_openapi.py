"""Export the Squad Runtime FastAPI OpenAPI schema to a JSON file.

Usage:
    python scripts/export_openapi.py [--output OUTPUT]

Defaults to ``docs/openapi.json`` relative to the project root.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Ensure the project root is importable when running as a standalone script.
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from squad_runtime.api import create_app  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Export Squad Runtime OpenAPI schema to JSON")
    parser.add_argument(
        "--output",
        type=Path,
        default=_PROJECT_ROOT / "docs" / "openapi.json",
        help="Output file path (default: docs/openapi.json)",
    )
    args = parser.parse_args()

    app = create_app()
    schema = app.openapi()

    output_path: Path = args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(schema, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"OpenAPI schema exported to {output_path}")


if __name__ == "__main__":
    main()
