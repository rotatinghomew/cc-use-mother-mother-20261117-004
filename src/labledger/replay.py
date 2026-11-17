from __future__ import annotations

import json
from typing import Any

from labledger.ingest.contracts import Calibration, Measurement, RunBundle
from labledger.quality.diagnostics import diagnose
from labledger.quality.gates import QualityDecision, QualityFinding, qualify


def replay_saved(record: dict[str, Any]) -> dict[str, Any]:
    stored_run = record["run"]
    provenance = json.loads(stored_run["provenance_json"])
    calibration = Calibration(**provenance["calibration"])
    measurements = tuple(Measurement(
        item["measurement_id"], item["sample_id"], item["cohort"], item["replicate"],
        item["raw_value"], item["unit"], item["measured_at"], item["role"]
    ) for item in record["measurements"])
    bundle = RunBundle(
        stored_run["study_id"], stored_run["run_id"], stored_run["protocol_version"],
        stored_run["instrument_id"], stored_run["unit"], provenance["control_range"]["min"],
        provenance["control_range"]["max"], provenance["min_replicates"],
        provenance["reference_cohort"], calibration, measurements, stored_run["source_digest"],
    )
    decision = qualify(bundle)
    diagnostics = diagnose(bundle, decision)
    blocking = tuple(QualityFinding(item.code, item.severity, item.detail)
                     for item in diagnostics if item.severity == "blocking")
    if blocking:
        decision = QualityDecision(False, decision.findings + blocking, decision.corrected)
    expected_findings = json.loads(stored_run["findings_json"])
    expected_diagnostics = json.loads(stored_run["diagnostics_json"])
    actual_findings = [item.__dict__ for item in decision.findings]
    actual_diagnostics = [item.__dict__ for item in diagnostics]
    mismatches = []
    if bool(stored_run["accepted"]) != decision.accepted:
        mismatches.append("accepted")
    if expected_findings != actual_findings:
        mismatches.append("findings")
    if expected_diagnostics != actual_diagnostics:
        mismatches.append("diagnostics")
    saved_values = {row["measurement_id"]: row["corrected_value"] for row in record["measurements"]}
    for item in measurements:
        if abs(saved_values[item.measurement_id] - decision.corrected[item.measurement_id]) > 1e-12:
            mismatches.append(f"corrected:{item.measurement_id}")
    return {"study_id": bundle.study_id, "run_id": bundle.run_id,
            "replay_matches": not mismatches, "mismatches": mismatches,
            "replayed_accepted": decision.accepted,
            "measurement_count": len(measurements), "source_digest": bundle.source_digest}
