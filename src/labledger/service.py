from __future__ import annotations

from pathlib import Path
from typing import Any

from labledger.analysis.report import build_report
from labledger.analysis.contrasts import compare_to_reference
from labledger.analysis.control_trend import control_trend
from labledger.analysis.provenance import lineage_summary
from labledger.analysis.quality_summary import quality_summary
from labledger.analysis.coverage import cohort_coverage
from labledger.analysis.repeatability import repeatability_summary
from labledger.analysis.readiness import assess_readiness
from labledger.analysis.run_profile import profile_runs
from labledger.analysis.instrument_inventory import instrument_inventory
from labledger.replay import replay_saved
from labledger.errors import ContractError
from labledger.ingest.loaders import load_bundle
from labledger.ingest.manifests import read_manifest
from labledger.quality.gates import QualityDecision, QualityFinding, qualify
from labledger.quality.diagnostics import diagnose
from labledger.storage.database import Database
from labledger.storage.repository import Repository
from labledger.storage.metrics import database_metrics


class EvidenceService:
    def __init__(self, database_path: str | Path):
        self.database = Database(database_path)
        self.database.initialize()

    def import_run(self, source: str | Path) -> dict[str, Any]:
        bundle, decision, diagnostics = self._prepare(source)
        with self.database.transaction() as connection:
            repository = Repository(connection)
            repository.ensure_study(bundle.study_id)
            repository.insert_run(bundle, decision, diagnostics)
            result = repository.study_summary(bundle.study_id)
            result["imported_run"] = bundle.run_id
            result["accepted"] = decision.accepted
            result["findings"] = [item.__dict__ for item in decision.findings]
            result["diagnostics"] = [item.__dict__ for item in diagnostics]
            return result

    def _prepare(self, source: str | Path):
        bundle = load_bundle(source)
        decision = qualify(bundle)
        diagnostics = diagnose(bundle, decision)
        blocking = [QualityFinding(item.code, item.severity, item.detail)
                    for item in diagnostics if item.severity == "blocking"]
        if blocking:
            decision = QualityDecision(False, decision.findings + tuple(blocking), decision.corrected)
        return bundle, decision, diagnostics

    def preview_run(self, source: str | Path) -> dict[str, Any]:
        bundle, decision, diagnostics = self._prepare(source)
        with self.database.connect() as connection:
            existing = Repository(connection).run_digest(bundle.study_id, bundle.run_id)
        conflict = None
        if existing:
            conflict = "identical content is already stored" if existing == bundle.source_digest else \
                "run identifier is already used by different content"
        return {"study_id": bundle.study_id, "run_id": bundle.run_id,
                "source_digest": bundle.source_digest, "measurement_count": len(bundle.measurements),
                "accepted_if_imported": decision.accepted, "findings": [item.__dict__ for item in decision.findings],
                "diagnostics": [item.__dict__ for item in diagnostics], "existing_run_conflict": conflict}

    def preview_batch(self, sources: list[str | Path]) -> dict[str, Any]:
        if not sources:
            raise ContractError("batch must contain at least one bundle")
        prepared = [self._prepare(source) for source in sources]
        study_ids = {item[0].study_id for item in prepared}
        identifiers = [item[0].run_id for item in prepared]
        if len(study_ids) != 1:
            raise ContractError("all bundles in one batch must belong to the same study")
        if len(set(identifiers)) != len(identifiers):
            raise ContractError("a batch cannot contain duplicate run identifiers")
        study_id = next(iter(study_ids))
        entries = []
        with self.database.connect() as connection:
            repository = Repository(connection)
            for bundle, decision, diagnostics in prepared:
                existing = repository.run_digest(study_id, bundle.run_id)
                entries.append({"run_id": bundle.run_id, "accepted_if_imported": decision.accepted,
                                "measurement_count": len(bundle.measurements),
                                "existing_digest_conflict": bool(existing and existing != bundle.source_digest),
                                "findings": [item.code for item in decision.findings],
                                "diagnostics": [item.code for item in diagnostics]})
        return {"study_id": study_id, "run_count": len(entries), "runs": entries,
                "ready_to_import": not any(item["existing_digest_conflict"] for item in entries)}

    def import_batch(self, sources: list[str | Path]) -> dict[str, Any]:
        if not sources:
            raise ContractError("batch must contain at least one bundle")
        prepared = [self._prepare(source) for source in sources]
        study_ids = {item[0].study_id for item in prepared}
        run_ids = [item[0].run_id for item in prepared]
        if len(study_ids) != 1:
            raise ContractError("all bundles in one batch must belong to the same study")
        if len(set(run_ids)) != len(run_ids):
            raise ContractError("a batch cannot contain duplicate run identifiers")
        study_id = next(iter(study_ids))
        with self.database.transaction() as connection:
            repository = Repository(connection)
            repository.ensure_study(study_id)
            for bundle, decision, diagnostics in prepared:
                repository.insert_run(bundle, decision, diagnostics)
            summary = repository.study_summary(study_id)
        summary["imported_runs"] = [{"run_id": bundle.run_id, "accepted": decision.accepted,
                                     "finding_codes": [item.code for item in decision.findings]}
                                    for bundle, decision, diagnostics in prepared]
        return summary

    def import_manifest(self, path: str | Path) -> dict[str, Any]:
        return self.import_batch(read_manifest(path))

    def report(self, study_id: str, tolerance: float = 0.15) -> dict[str, Any]:
        if tolerance < 0:
            raise ContractError("tolerance must be non-negative")
        with self.database.connect() as connection:
            repository = Repository(connection)
            summary = repository.study_summary(study_id)
            records = repository.analysis_records(study_id)
            analysis = repository.reproducibility(study_id, tolerance)
            report = build_report(summary, analysis)
            report["contrasts"] = compare_to_reference(records)
            report["control_trend"] = control_trend(records, change_limit=max(tolerance, 0.05))
            report["lineage"] = lineage_summary(repository.all_provenance(study_id))
            report["quality"] = quality_summary(records)
            report["coverage"] = cohort_coverage(records)
            report["repeatability"] = repeatability_summary(records)
            report["readiness"] = assess_readiness(report)
            report["run_profiles"] = profile_runs(records)
            report["instruments"] = instrument_inventory(records, repository.all_provenance(study_id))
            return report

    def findings(self, study_id: str, run_id: str) -> list[dict[str, str]]:
        with self.database.connect() as connection:
            return Repository(connection).findings(study_id, run_id)

    def audit(self, study_id: str) -> list[dict[str, Any]]:
        with self.database.connect() as connection:
            return Repository(connection).audit_trail(study_id)

    def diagnostics(self, study_id: str, run_id: str) -> list[dict[str, str]]:
        with self.database.connect() as connection:
            return Repository(connection).run_diagnostics(study_id, run_id)

    def provenance(self, study_id: str, run_id: str) -> dict[str, Any]:
        with self.database.connect() as connection:
            return Repository(connection).provenance(study_id, run_id)

    def history(self, study_id: str) -> list[dict[str, Any]]:
        with self.database.connect() as connection:
            return Repository(connection).all_provenance(study_id)

    def studies(self) -> list[dict[str, Any]]:
        with self.database.connect() as connection:
            return Repository(connection).list_studies()

    def verify_audit(self, study_id: str) -> dict[str, Any]:
        with self.database.connect() as connection:
            return Repository(connection).verify_audit(study_id)

    def export_rows(self, study_id: str) -> list[dict[str, Any]]:
        with self.database.connect() as connection:
            repository = Repository(connection)
            repository.study_summary(study_id)
            return repository.evidence_rows(study_id)

    def integrity(self) -> list[str]:
        with self.database.connect() as connection:
            return Repository(connection).integrity_check()

    def database_status(self) -> dict[str, Any]:
        with self.database.connect() as connection:
            metrics = database_metrics(connection, self.database.path)
            integrity = Repository(connection).integrity_check()
        schema = self.database.schema_status()
        return {"schema": schema, "integrity": integrity, "metrics": metrics,
                "healthy": schema["valid"] and integrity == ["ok"]}

    def replay(self, study_id: str, run_id: str) -> dict[str, Any]:
        with self.database.connect() as connection:
            record = Repository(connection).replay_record(study_id, run_id)
        return replay_saved(record)
