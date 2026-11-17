from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


TABLES = ("studies", "runs", "measurements", "audit_events")


def database_metrics(connection: sqlite3.Connection, database_path: str) -> dict[str, Any]:
    page_count = connection.execute("PRAGMA page_count").fetchone()[0]
    page_size = connection.execute("PRAGMA page_size").fetchone()[0]
    freelist = connection.execute("PRAGMA freelist_count").fetchone()[0]
    journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
    counts = {table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
              for table in TABLES}
    path = Path(database_path)
    size = path.stat().st_size if database_path != ":memory:" and path.exists() else 0
    return {"database_path": database_path, "file_bytes": size, "page_count": page_count,
            "page_size": page_size, "allocated_bytes": page_count * page_size,
            "free_pages": freelist, "journal_mode": journal_mode, "row_counts": counts}
