from __future__ import annotations

import os
import sqlite3
import tempfile
from pathlib import Path

from labledger.errors import StorageError


def create_backup(source: str | Path, destination: str | Path) -> Path:
    source_path = str(source)
    target = Path(destination)
    if source_path == ":memory:":
        raise StorageError("in-memory databases cannot be backed up by pathname")
    if Path(source_path).resolve() == target.resolve():
        raise StorageError("backup destination must differ from the live database")
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        source_connection = sqlite3.connect(source_path, timeout=10)
        backup_connection = sqlite3.connect(temporary)
        try:
            try:
                source_connection.backup(backup_connection, pages=128, sleep=0.05)
                integrity = [row[0] for row in backup_connection.execute("PRAGMA integrity_check")]
                if integrity != ["ok"]:
                    raise StorageError(f"backup integrity check failed: {integrity}")
                backup_connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            finally:
                backup_connection.close()
        finally:
            source_connection.close()
        with temporary.open("rb") as stream:
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return target
