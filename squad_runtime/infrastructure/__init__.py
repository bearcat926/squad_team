"""Infrastructure layer: database, schema, and migration management."""

from .migrations import run_migrations

__all__ = ["run_migrations"]
