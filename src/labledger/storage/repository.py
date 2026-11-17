from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from labledger.analysis.reproducibility import analyze_runs
from labledger.quality.diagnostics import diagnose
from labledger.errors import DuplicateRunError, EvidenceUnavailableError, UnknownStudyError
from labledger.ingest.contracts import RunBundle
from labledger.quality.gates import QualityDecision


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class Repository:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def ensure_study(self, study_id: str, now: str | None = None) -> None:
        self.connection.execute("INSERT OR IGNORE INTO studies(study_id, created_at) VALUES (?, ?)",
                                (study_id, now or utc_now()))

    def run_digest(self, study_id: str, run_id: str) -> str | None:
        row = self.connection.execute("SELECT source_digest FROM runs WHERE study_id=? AND run_id=?",
                                      (study_id, run_id)).fetchone()
        return row["source_digest"] if row else None

    def insert_run(self, bundle: RunBundle, decision: QualityDecision, diagnostics: list[Any]) -> None:
        existing = self.run_digest(bundle.study_id, bundle.run_id)
        if existing:
            if existing == bundle.source_digest:
                raise DuplicateRunError("run already imported with identical bytes")
            raise DuplicateRunError("run id already exists with different bytes")
        now = utc_now()
        findings = [item.__dict__ for item in decision.findings]
        self.connection.execute(
            "INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (bundle.study_id, bundle.run_id, bundle.source_digest, bundle.protocol_version,
             bundle.instrument_id, bundle.unit, bundle.reference_cohort, bundle.calibration.calibration_id,
             int(decision.accepted), json.dumps(findings, sort_keys=True),
             json.dumps([item.__dict__ for item in diagnostics], sort_keys=True),
             json.dumps({"calibration": bundle.calibration.__dict__,
                         "control_range": {"min": bundle.control_min, "max": bundle.control_max},
                         "min_replicates": bundle.min_replicates,
                         "reference_cohort": bundle.reference_cohort,
                         "protocol_version": bundle.protocol_version}, sort_keys=True), now),
        )
        for item in bundle.measurements:
            self.connection.execute(
                "INSERT INTO measurements VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (bundle.study_id, bundle.run_id, item.measurement_id, item.sample_id, item.cohort,
                 item.replicate, item.value, decision.corrected[item.measurement_id], item.unit,
                 item.measured_at, item.role),
            )
        event_type = "run.accepted" if decision.accepted else "run.rejected"
        self.connection.execute("INSERT INTO audit_events(study_id, run_id, event_type, details_json, created_at) "
                                "VALUES (?, ?, ?, ?, ?)",
                                (bundle.study_id, bundle.run_id, event_type,
                                 json.dumps({"digest": bundle.source_digest, "finding_count": len(findings)},
                                            sort_keys=True), now))

    def study_summary(self, study_id: str) -> dict[str, Any]:
        study = self.connection.execute("SELECT study_id FROM studies WHERE study_id=?", (study_id,)).fetchone()
        if not study:
            raise UnknownStudyError(f"unknown study: {study_id}")
        rows = self.connection.execute("SELECT run_id, protocol_version, accepted, findings_json "
                                       "FROM runs WHERE study_id=? ORDER BY run_id", (study_id,)).fetchall()
        accepted = [row for row in rows if row["accepted"]]
        rejected = [row for row in rows if not row["accepted"]]
        state = "ready" if len(accepted) >= 2 else "review_required"
        if rejected:
            state = "review_required"
        return {"study_id": study_id, "status": state,
                "accepted_runs": [row["run_id"] for row in accepted],
                "rejected_runs": [row["run_id"] for row in rejected],
                "protocol_versions": sorted({row["protocol_version"] for row in rows})}

    def analysis_records(self, study_id: str) -> list[dict[str, Any]]:
        if not self.connection.execute("SELECT 1 FROM studies WHERE study_id=?", (study_id,)).fetchone():
            raise UnknownStudyError(f"unknown study: {study_id}")
        runs = self.connection.execute("SELECT run_id, accepted, reference_cohort, instrument_id, unit, "
                                       "protocol_version, diagnostics_json FROM runs "
                                       "WHERE study_id=? ORDER BY run_id",
                                       (study_id,)).fetchall()
        result = []
        for run in runs:
            measurements = self.connection.execute(
                "SELECT measurement_id, cohort, corrected_value, role, unit, sample_id FROM measurements "
                "WHERE study_id=? AND run_id=? ORDER BY measurement_id", (study_id, run["run_id"]),
            ).fetchall()
            result.append({"run_id": run["run_id"], "accepted": bool(run["accepted"]),
                           "reference_cohort": run["reference_cohort"],
                           "instrument_id": run["instrument_id"], "unit": run["unit"],
                           "protocol_version": run["protocol_version"],
                           "diagnostics": json.loads(run["diagnostics_json"]),
                           "measurements": [dict(row) for row in measurements]})
        return result

    def findings(self, study_id: str, run_id: str) -> list[dict[str, str]]:
        row = self.connection.execute("SELECT findings_json FROM runs WHERE study_id=? AND run_id=?",
                                      (study_id, run_id)).fetchone()
        if not row:
            raise EvidenceUnavailableError(f"run not found: {run_id}")
        return json.loads(row["findings_json"])

    def audit_trail(self, study_id: str) -> list[dict[str, Any]]:
        rows = self.connection.execute("SELECT run_id, event_type, details_json, created_at "
                                       "FROM audit_events WHERE study_id=? ORDER BY event_id", (study_id,)).fetchall()
        return [{"run_id": row["run_id"], "event_type": row["event_type"],
                 "details": json.loads(row["details_json"]), "created_at": row["created_at"]}
                for row in rows]

    def reproducibility(self, study_id: str, tolerance: float) -> dict[str, Any]:
        records = self.analysis_records(study_id)
        return analyze_runs(records, tolerance=tolerance)

    def run_diagnostics(self, study_id: str, run_id: str) -> list[dict[str, str]]:
        row = self.connection.execute("SELECT diagnostics_json FROM runs WHERE study_id=? AND run_id=?",
                                      (study_id, run_id)).fetchone()
        if not row:
            raise EvidenceUnavailableError(f"run not found: {run_id}")
        return json.loads(row["diagnostics_json"])

    def provenance(self, study_id: str, run_id: str) -> dict[str, Any]:
        row = self.connection.execute("SELECT source_digest, instrument_id, unit, calibration_id, "
                                      "provenance_json, accepted FROM runs "
                                      "WHERE study_id=? AND run_id=?", (study_id, run_id)).fetchone()
        if not row:
            raise EvidenceUnavailableError(f"run not found: {run_id}")
        return {"study_id": study_id, "run_id": run_id, "source_digest": row["source_digest"],
                "instrument_id": row["instrument_id"], "unit": row["unit"],
                "calibration_id": row["calibration_id"], "accepted": bool(row["accepted"]),
                **json.loads(row["provenance_json"])}

    def all_provenance(self, study_id: str) -> list[dict[str, Any]]:
        rows = self.connection.execute("SELECT run_id FROM runs WHERE study_id=? ORDER BY imported_at, run_id",
                                       (study_id,)).fetchall()
        return [self.provenance(study_id, row["run_id"]) for row in rows]

    def evidence_rows(self, study_id: str) -> list[dict[str, Any]]:
        query = """
        SELECT m.run_id, r.source_digest, r.accepted, r.instrument_id, r.calibration_id,
               m.measurement_id, m.sample_id, m.cohort, m.replicate, m.raw_value,
               m.corrected_value, m.unit, m.measured_at, m.role
        FROM measurements AS m
        JOIN runs AS r ON r.study_id=m.study_id AND r.run_id=m.run_id
        WHERE m.study_id=?
        ORDER BY m.run_id, m.role, m.cohort, m.sample_id, m.replicate, m.measurement_id
        """
        return [dict(row) for row in self.connection.execute(query, (study_id,)).fetchall()]

    def integrity_check(self) -> list[str]:
        return [row[0] for row in self.connection.execute("PRAGMA integrity_check").fetchall()]

    def list_studies(self) -> list[dict[str, Any]]:
        rows = self.connection.execute("""
        SELECT s.study_id, s.created_at, COUNT(r.run_id) AS run_count,
               SUM(CASE WHEN r.accepted=1 THEN 1 ELSE 0 END) AS accepted_count,
               SUM(CASE WHEN r.accepted=0 THEN 1 ELSE 0 END) AS rejected_count
        FROM studies AS s LEFT JOIN runs AS r ON r.study_id=s.study_id
        GROUP BY s.study_id, s.created_at ORDER BY s.created_at, s.study_id
        """).fetchall()
        return [{"study_id": row["study_id"], "created_at": row["created_at"],
                 "run_count": row["run_count"], "accepted_count": row["accepted_count"] or 0,
                 "rejected_count": row["rejected_count"] or 0} for row in rows]

    def verify_audit(self, study_id: str) -> dict[str, Any]:
        self.study_summary(study_id)
        findings = []
        rows = self.connection.execute("SELECT r.run_id, r.accepted, r.source_digest, r.findings_json, "
                                      "COUNT(a.event_id) AS event_count, "
                                      "MIN(a.event_type) AS event_type, MIN(a.details_json) AS details_json "
                                      "FROM runs AS r LEFT JOIN audit_events AS a "
                                      "ON a.study_id=r.study_id AND a.run_id=r.run_id "
                                      "WHERE r.study_id=? GROUP BY r.run_id", (study_id,)).fetchall()
        for row in rows:
            if row["event_count"] != 1:
                findings.append({"run_id": row["run_id"], "code": "AUDIT_EVENT_COUNT",
                                 "detail": f"expected one audit event, found {row['event_count']}"})
                continue
            expected_type = "run.accepted" if row["accepted"] else "run.rejected"
            if row["event_type"] != expected_type:
                findings.append({"run_id": row["run_id"], "code": "AUDIT_DECISION_MISMATCH",
                                 "detail": f"expected {expected_type}, found {row['event_type']}"})
            details = json.loads(row["details_json"])
            if details.get("digest") != row["source_digest"]:
                findings.append({"run_id": row["run_id"], "code": "AUDIT_DIGEST_MISMATCH",
                                 "detail": "audit digest differs from stored source digest"})
            expected_count = len(json.loads(row["findings_json"]))
            if details.get("finding_count") != expected_count:
                findings.append({"run_id": row["run_id"], "code": "AUDIT_FINDING_COUNT_MISMATCH",
                                 "detail": "audit finding count differs from stored quality findings"})
        orphaned = self.connection.execute("SELECT a.run_id FROM audit_events AS a "
                                           "LEFT JOIN runs AS r ON r.study_id=a.study_id AND r.run_id=a.run_id "
                                           "WHERE a.study_id=? AND r.run_id IS NULL ORDER BY a.event_id",
                                           (study_id,)).fetchall()
        for row in orphaned:
            findings.append({"run_id": row["run_id"], "code": "ORPHAN_AUDIT_EVENT",
                             "detail": "audit event has no matching stored run"})
        return {"study_id": study_id, "valid": not findings, "run_count": len(rows), "findings": findings}

    def replay_record(self, study_id: str, run_id: str) -> dict[str, Any]:
        run = self.connection.execute("SELECT * FROM runs WHERE study_id=? AND run_id=?",
                                      (study_id, run_id)).fetchone()
        if not run:
            raise EvidenceUnavailableError(f"run not found: {run_id}")
        measurements = self.connection.execute("SELECT * FROM measurements WHERE study_id=? AND run_id=? "
                                               "ORDER BY measurement_id", (study_id, run_id)).fetchall()
        return {"run": dict(run), "measurements": [dict(item) for item in measurements]}
