from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterator


SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS studies (
    study_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    study_id TEXT NOT NULL REFERENCES studies(study_id),
    run_id TEXT NOT NULL,
    source_digest TEXT NOT NULL,
    protocol_version INTEGER NOT NULL,
    instrument_id TEXT NOT NULL,
    unit TEXT NOT NULL,
    reference_cohort TEXT NOT NULL,
    calibration_id TEXT NOT NULL,
    accepted INTEGER NOT NULL CHECK(accepted IN (0, 1)),
    findings_json TEXT NOT NULL,
    diagnostics_json TEXT NOT NULL,
    provenance_json TEXT NOT NULL,
    imported_at TEXT NOT NULL,
    PRIMARY KEY(study_id, run_id)
);
CREATE TABLE IF NOT EXISTS measurements (
    study_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    measurement_id TEXT NOT NULL,
    sample_id TEXT NOT NULL,
    cohort TEXT NOT NULL,
    replicate INTEGER NOT NULL,
    raw_value REAL NOT NULL,
    corrected_value REAL NOT NULL,
    unit TEXT NOT NULL,
    measured_at TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('control', 'sample')),
    PRIMARY KEY(study_id, run_id, measurement_id),
    FOREIGN KEY(study_id, run_id) REFERENCES runs(study_id, run_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS measurements_by_cohort ON measurements(study_id, cohort, run_id);
CREATE TABLE IF NOT EXISTS audit_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    study_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    details_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS audit_by_study ON audit_events(study_id, event_id);
"""

SCHEMA_VERSION = 1
REQUIRED_COLUMNS = {
    "studies": {"study_id", "created_at"},
    "runs": {"study_id", "run_id", "source_digest", "protocol_version", "accepted",
             "findings_json", "diagnostics_json", "provenance_json"},
    "measurements": {"study_id", "run_id", "measurement_id", "raw_value", "corrected_value",
                      "measured_at", "role"},
    "audit_events": {"event_id", "study_id", "run_id", "event_type", "details_json", "created_at"},
}


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


class Database:
    def __init__(self, path: str | Path):
        self.path = str(path)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10, isolation_level=None, factory=ClosingConnection)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    def initialize(self) -> None:
        path = Path(self.path)
        if self.path != ":memory:":
            path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(SCHEMA)
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version > SCHEMA_VERSION:
                raise RuntimeError(f"database schema {version} is newer than supported {SCHEMA_VERSION}")
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        connection.execute("BEGIN IMMEDIATE")
        return _Transaction(connection)

    def schema_status(self) -> dict[str, object]:
        with self.connect() as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            missing = {}
            for table, required in REQUIRED_COLUMNS.items():
                actual = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
                absent = sorted(required - actual)
                if absent:
                    missing[table] = absent
            foreign_key_errors = [tuple(row) for row in connection.execute("PRAGMA foreign_key_check")]
        return {"schema_version": version, "supported_version": SCHEMA_VERSION,
                "missing_columns": missing, "foreign_key_errors": foreign_key_errors,
                "valid": version == SCHEMA_VERSION and not missing and not foreign_key_errors}


class _Transaction:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def __enter__(self) -> sqlite3.Connection:
        return self.connection

    def __exit__(self, exc_type, exc, traceback) -> bool:
        try:
            if exc_type:
                self.connection.rollback()
            else:
                self.connection.commit()
        finally:
            self.connection.close()
        return False
