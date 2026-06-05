"""Database connection management for Squad Runtime."""

from __future__ import annotations

import sqlite3
from pathlib import Path


class Database:
    """Manages a SQLite connection with WAL mode and busy_timeout."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=5000")

    def close(self) -> None:
        self.conn.close()
