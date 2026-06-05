"""API authentication compatibility module.

The canonical token_matches implementation lives in security.__init__.
This module re-exports for backward compatibility and provides a
documented entry point for future auth extensions.
"""

from __future__ import annotations

from . import token_matches  # noqa: F401 — re-export

__all__ = ["token_matches"]
