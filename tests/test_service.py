import json
import sqlite3
import unittest

from labledger.cli import run
from labledger.errors import ContractError, DuplicateRunError, EvidenceUnavailableError, StorageError, UnknownStudyError
from labledger.service import EvidenceService
from labledger.exports import evidence_packet, export_csv, export_json, verify_packet
from labledger.storage.backup import create_backup
from tests.helpers import Sandbox, bundle


class EvidenceServiceTests(unittest.TestCase):
    def test_import_creates_accepted_run_and_audit_event(self):
        with Sandbox() as box:
            source = box.write("a.json", bundle("a"))
            result = EvidenceService(box.database).import_run(source)
            self.assertTrue(result["accepted"])
            self.assertEqual(result["accepted_runs"], ["a"])
            self.assertEqual(result["status"], "review_required")
            audit = EvidenceService(box.database).audit("study-1")
            self.assertEqual(audit[0]["event_type"], "run.accepted")
            self.assertEqual(audit[0]["details"]["finding_count"], 0)

    def test_identical_upload_is_rejected_without_duplicate_audit(self):
        with Sandbox() as box:
            source = box.write("a.json", bundle("a"))
            service = EvidenceService(box.database)
            service.import_run(source)
            with self.assertRaisesRegex(DuplicateRunError, "identical bytes"):
                service.import_run(source)
            self.assertEqual(len(service.audit("study-1")), 1)

    def test_same_run_identifier_with_changed_content_is_conflict(self):
        with Sandbox() as box:
            service = EvidenceService(box.database)
            service.import_run(box.write("first.json", bundle("a")))
            changed = bundle("a", value_shift=0.3)
            with self.assertRaisesRegex(DuplicateRunError, "different bytes"):
                service.import_run(box.write("changed.json", changed))
            self.assertEqual(len(service.audit("study-1")), 1)

    def test_rejected_quality_run_is_saved_but_excluded_from_analysis(self):
        with Sandbox() as box:
            service = EvidenceService(box.database)
            good = bundle("good")
            bad = bundle("bad", control=3.0)
            self.assertTrue(service.import_run(box.write("good.json", good))["accepted"])
            rejected = service.import_run(box.write("bad.json", bad))
            self.assertFalse(rejected["accepted"])
            self.assertIn("bad", rejected["rejected_runs"])
            self.assertIn("CONTROL_OUT_OF_RANGE",
                          {item["code"] for item in service.findings("study-1", "bad")})
            report = service.report("study-1")
            self.assertEqual(report["excluded_runs"], ["bad"])
            self.assertEqual(report["accepted_runs"], ["good"])

    def test_report_compares_only_after_two_accepted_runs(self):
        with Sandbox() as box:
            service = EvidenceService(box.database)
            service.import_run(box.write("a.json", bundle("a")))
            self.assertFalse(service.report("study-1")["has_comparison"])
            service.import_run(box.write("b.json", bundle("b", value_shift=0.1)))
            report = service.report("study-1", tolerance=0.15)
            self.assertTrue(report["has_comparison"])
            self.assertTrue(report["cohorts"][0]["reproducible"])
            self.assertTrue(report["contrasts"]["comparisons"]["candidate"]["direction_consistent"])

    def test_failed_run_import_does_not_mark_study_ready(self):
        with Sandbox() as box:
            service = EvidenceService(box.database)
            invalid = bundle("bad", control=2.0)
            result = service.import_run(box.write("bad.json", invalid))
            self.assertEqual(result["status"], "review_required")
            self.assertEqual(result["accepted_runs"], [])

    def test_mixed_units_are_reported_by_user_facing_report(self):
        with Sandbox() as box:
            service = EvidenceService(box.database)
            service.import_run(box.write("a.json", bundle("a", unit="signal")))
            service.import_run(box.write("b.json", bundle("b", unit="other")))
            report = service.report("study-1")
            self.assertEqual(report["incompatible_cohorts"], ["baseline", "candidate"])
            self.assertFalse(report["has_comparison"])
            self.assertEqual(report["cohorts"], [])

    def test_diagnostics_are_persisted_separately_from_blocking_findings(self):
        with Sandbox() as box:
            payload = bundle("a")
            for row, value in zip([item for item in payload["measurements"]
                                   if item["cohort"] == "candidate"], (0.1, 4.0, 9.0)):
                row["value"] = value
            service = EvidenceService(box.database)
            result = service.import_run(box.write("a.json", payload))
            self.assertTrue(result["accepted"])
            self.assertIn("HIGH_WITHIN_RUN_VARIATION",
                          {item["code"] for item in service.diagnostics("study-1", "a")})
            self.assertEqual(service.findings("study-1", "a"), [])

    def test_missing_reference_cohort_rejects_import_and_retains_diagnostic(self):
        with Sandbox() as box:
            payload = bundle("a")
            payload["reference_cohort"] = "unknown"
            service = EvidenceService(box.database)
            result = service.import_run(box.write("a.json", payload))
            self.assertFalse(result["accepted"])
            codes = {item["code"] for item in service.findings("study-1", "a")}
            self.assertIn("REFERENCE_COHORT_MISSING", codes)

    def test_unknown_study_is_not_created_by_report(self):
        with Sandbox() as box:
            service = EvidenceService(box.database)
            with self.assertRaises(UnknownStudyError):
                service.report("missing")
            with service.database.connect() as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM studies").fetchone()[0], 0)

    def test_missing_run_does_not_return_an_empty_quality_record(self):
        with Sandbox() as box:
            service = EvidenceService(box.database)
            service.import_run(box.write("a.json", bundle("a")))
            with self.assertRaises(EvidenceUnavailableError):
                service.findings("study-1", "absent")

    def test_database_reopen_preserves_run_findings_and_audit(self):
        with Sandbox() as box:
            source = box.write("a.json", bundle("a", control=4.0))
            EvidenceService(box.database).import_run(source)
            reopened = EvidenceService(box.database)
            self.assertEqual(len(reopened.audit("study-1")), 1)
            self.assertEqual(reopened.findings("study-1", "a")[0]["code"], "CONTROL_OUT_OF_RANGE")

    def test_sql_failure_rolls_back_run_measurements_and_study(self):
        with Sandbox() as box:
            service = EvidenceService(box.database)
            with service.database.connect() as connection:
                connection.execute("CREATE TRIGGER fail_measurement BEFORE INSERT ON measurements "
                                   "BEGIN SELECT RAISE(ABORT, 'forced write failure'); END")
            with self.assertRaises(sqlite3.IntegrityError):
                service.import_run(box.write("a.json", bundle("a")))
            with service.database.connect() as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM studies").fetchone()[0], 0)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0], 0)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0], 0)

    def test_report_rejects_negative_tolerance(self):
        with Sandbox() as box:
            service = EvidenceService(box.database)
            service.import_run(box.write("a.json", bundle("a")))
            from labledger.errors import ContractError
            with self.assertRaisesRegex(ContractError, "non-negative"):
                service.report("study-1", -0.01)

    def test_cli_import_writes_machine_readable_result(self):
        from io import StringIO
        from contextlib import redirect_stdout
        with Sandbox() as box:
            source = box.write("a.json", bundle("a"))
            output = StringIO()
            with redirect_stdout(output):
                code = run(["--database", str(box.database), "import", str(source)])
            self.assertEqual(code, 0)
            payload = json.loads(output.getvalue())
            self.assertEqual(payload["imported_run"], "a")
            self.assertTrue(payload["accepted"])

    def test_cli_reports_contract_errors_with_nonzero_exit(self):
        from io import StringIO
        from contextlib import redirect_stderr
        with Sandbox() as box:
            source = box.write("bad.json", {"study_id": "incomplete"})
            error = StringIO()
            with redirect_stderr(error):
                code = run(["--database", str(box.database), "import", str(source)])
            self.assertEqual(code, 2)
            self.assertIn("missing fields", json.loads(error.getvalue())["error"])

    def test_audit_order_reflects_import_order(self):
        with Sandbox() as box:
            service = EvidenceService(box.database)
            service.import_run(box.write("first.json", bundle("first")))
            service.import_run(box.write("second.json", bundle("second")))
            self.assertEqual([item["run_id"] for item in service.audit("study-1")],
                             ["first", "second"])

    def test_corrupt_json_does_not_create_an_empty_study(self):
        with Sandbox() as box:
            source = box.root / "broken.json"
            source.write_text("not-json", encoding="utf-8")
            service = EvidenceService(box.database)
            from labledger.errors import ContractError
            with self.assertRaises(ContractError):
                service.import_run(source)
            with service.database.connect() as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM studies").fetchone()[0], 0)

    def test_batch_import_records_all_runs_in_one_study(self):
        with Sandbox() as box:
            service = EvidenceService(box.database)
            result = service.import_batch([box.write("a.json", bundle("a")),
                                           box.write("b.json", bundle("b"))])
            self.assertEqual(result["accepted_runs"], ["a", "b"])
            self.assertEqual(len(service.audit("study-1")), 2)
            self.assertEqual(len(result["imported_runs"]), 2)

    def test_batch_with_duplicate_ids_is_rejected_before_any_write(self):
        with Sandbox() as box:
            service = EvidenceService(box.database)
            with self.assertRaisesRegex(ContractError, "duplicate run identifiers"):
                service.import_batch([box.write("a.json", bundle("same")),
                                      box.write("b.json", bundle("same", value_shift=0.1))])
            with service.database.connect() as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM studies").fetchone()[0], 0)

    def test_batch_with_multiple_studies_is_rejected_before_any_write(self):
        with Sandbox() as box:
            service = EvidenceService(box.database)
            with self.assertRaisesRegex(ContractError, "same study"):
                service.import_batch([box.write("a.json", bundle("a", study_id="one")),
                                      box.write("b.json", bundle("b", study_id="two"))])
            with service.database.connect() as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM studies").fetchone()[0], 0)

    def test_empty_batch_is_rejected(self):
        with Sandbox() as box:
            with self.assertRaisesRegex(ContractError, "at least one"):
                EvidenceService(box.database).import_batch([])

    def test_existing_run_conflict_rolls_back_other_batch_members(self):
        with Sandbox() as box:
            service = EvidenceService(box.database)
            service.import_run(box.write("existing.json", bundle("existing")))
            batch = [box.write("new.json", bundle("new")),
                     box.write("conflict.json", bundle("existing", value_shift=0.4))]
            with self.assertRaises(DuplicateRunError):
                service.import_batch(batch)
            self.assertEqual([item["run_id"] for item in service.audit("study-1")], ["existing"])

    def test_batch_database_failure_rolls_back_every_import(self):
        with Sandbox() as box:
            service = EvidenceService(box.database)
            with service.database.connect() as connection:
                connection.execute("CREATE TRIGGER stop_second BEFORE INSERT ON runs "
                                   "WHEN NEW.run_id='b' BEGIN SELECT RAISE(ABORT, 'stop'); END")
            paths = [box.write("a.json", bundle("a")), box.write("b.json", bundle("b"))]
            with self.assertRaises(sqlite3.IntegrityError):
                service.import_batch(paths)
            with service.database.connect() as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM studies").fetchone()[0], 0)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0], 0)

    def test_previewable_reports_preserve_original_digest(self):
        with Sandbox() as box:
            service = EvidenceService(box.database)
            service.import_run(box.write("a.json", bundle("a")))
            evidence = service.provenance("study-1", "a")
            self.assertEqual(len(evidence["source_digest"]), 64)
            self.assertEqual(evidence["calibration"]["calibration_id"], "cal-a")
            self.assertEqual(evidence["control_range"], {"max": 1.3, "min": 0.8})

    def test_stored_evidence_replays_to_same_quality_decision(self):
        with Sandbox() as box:
            service = EvidenceService(box.database)
            service.import_run(box.write("a.json", bundle("a", offset=0.1)))
            replay = service.replay("study-1", "a")
            self.assertTrue(replay["replay_matches"])
            self.assertEqual(replay["mismatches"], [])
            self.assertEqual(replay["measurement_count"], 8)

    def test_replay_preserves_rejected_status_and_findings(self):
        with Sandbox() as box:
            service = EvidenceService(box.database)
            service.import_run(box.write("bad.json", bundle("bad", control=5.0)))
            replay = service.replay("study-1", "bad")
            self.assertTrue(replay["replay_matches"])
            self.assertFalse(replay["replayed_accepted"])

    def test_packet_checksum_detects_tampering(self):
        with Sandbox() as box:
            service = EvidenceService(box.database)
            service.import_run(box.write("a.json", bundle("a")))
            packet = evidence_packet(service, "study-1")
            self.assertTrue(verify_packet(packet))
            packet["measurements"][0]["raw_value"] += 1
            self.assertFalse(verify_packet(packet))

    def test_json_export_is_deterministic_and_verifiable(self):
        with Sandbox() as box:
            service = EvidenceService(box.database)
            service.import_run(box.write("a.json", bundle("a")))
            one = export_json(service, "study-1", box.root / "exports" / "one.json")
            two = export_json(service, "study-1", box.root / "exports" / "two.json")
            self.assertEqual(one.read_bytes(), two.read_bytes())
            self.assertTrue(verify_packet(json.loads(one.read_text(encoding="utf-8"))))

    def test_csv_export_contains_raw_corrected_and_digest_fields(self):
        with Sandbox() as box:
            service = EvidenceService(box.database)
            service.import_run(box.write("a.json", bundle("a", offset=0.1)))
            target = export_csv(service, "study-1", box.root / "measurements.csv")
            text = target.read_text(encoding="utf-8")
            self.assertIn("source_digest", text.splitlines()[0])
            self.assertIn("raw_value", text.splitlines()[0])
            self.assertIn("corrected_value", text.splitlines()[0])
            self.assertEqual(len(text.splitlines()), 9)

    def test_export_unknown_study_does_not_create_file(self):
        with Sandbox() as box:
            service = EvidenceService(box.database)
            target = box.root / "absent.json"
            with self.assertRaises(UnknownStudyError):
                export_json(service, "missing", target)
            self.assertFalse(target.exists())

    def test_database_backup_is_integrity_checked_and_reopenable(self):
        with Sandbox() as box:
            service = EvidenceService(box.database)
            service.import_run(box.write("a.json", bundle("a")))
            target = create_backup(box.database, box.root / "backup.sqlite3")
            self.assertEqual(target, box.root / "backup.sqlite3")
            connection = sqlite3.connect(target)
            try:
                self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0], 1)
            finally:
                connection.close()

    def test_backup_rejects_live_database_as_destination(self):
        with Sandbox() as box:
            with self.assertRaisesRegex(StorageError, "must differ"):
                create_backup(box.database, box.database)

    def test_database_integrity_endpoint_reports_ok(self):
        with Sandbox() as box:
            service = EvidenceService(box.database)
            self.assertEqual(service.integrity(), ["ok"])

    def test_database_status_reports_schema_page_counts_and_health(self):
        with Sandbox() as box:
            service = EvidenceService(box.database)
            status = service.database_status()
            self.assertTrue(status["healthy"])
            self.assertEqual(status["schema"]["schema_version"], 1)
            self.assertGreater(status["metrics"]["page_count"], 0)
            self.assertIn("measurements", status["metrics"]["row_counts"])

    def test_audit_verification_matches_each_imported_decision(self):
        with Sandbox() as box:
            service = EvidenceService(box.database)
            service.import_run(box.write("good.json", bundle("good")))
            service.import_run(box.write("bad.json", bundle("bad", control=4.0)))
            result = service.verify_audit("study-1")
            self.assertTrue(result["valid"])
            self.assertEqual(result["run_count"], 2)
            self.assertEqual(result["findings"], [])

    def test_audit_verification_detects_removed_event(self):
        with Sandbox() as box:
            service = EvidenceService(box.database)
            service.import_run(box.write("a.json", bundle("a")))
            with service.database.connect() as connection:
                connection.execute("DELETE FROM audit_events WHERE run_id='a'")
            result = service.verify_audit("study-1")
            self.assertFalse(result["valid"])
            self.assertEqual(result["findings"][0]["code"], "AUDIT_EVENT_COUNT")

    def test_instrument_crossing_is_flagged_for_human_calibration_review(self):
        with Sandbox() as box:
            service = EvidenceService(box.database)
            first = bundle("a")
            second = bundle("b", value_shift=0.05)
            second["instrument_id"] = "reader-02"
            service.import_run(box.write("a.json", first))
            service.import_run(box.write("b.json", second))
            report = service.report("study-1")
            self.assertTrue(report["cohorts"][0]["cross_instrument"])
            self.assertEqual(report["readiness"]["status"], "limited_evidence")
            self.assertIn("CROSS_INSTRUMENT_REVIEW",
                          {item["code"] for item in report["readiness"]["reasons"]})

    def test_single_bundle_preview_does_not_create_study_or_audit(self):
        with Sandbox() as box:
            service = EvidenceService(box.database)
            preview = service.preview_run(box.write("a.json", bundle("a")))
            self.assertTrue(preview["accepted_if_imported"])
            self.assertIsNone(preview["existing_run_conflict"])
            with service.database.connect() as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM studies").fetchone()[0], 0)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0], 0)

    def test_preview_detects_conflict_without_mutating_study(self):
        with Sandbox() as box:
            service = EvidenceService(box.database)
            service.import_run(box.write("original.json", bundle("a")))
            preview = service.preview_run(box.write("changed.json", bundle("a", value_shift=0.5)))
            self.assertIn("already used", preview["existing_run_conflict"])
            self.assertEqual(len(service.audit("study-1")), 1)

    def test_batch_preview_checks_conflicts_without_committing_new_runs(self):
        with Sandbox() as box:
            service = EvidenceService(box.database)
            service.import_run(box.write("old.json", bundle("old")))
            result = service.preview_batch([box.write("new.json", bundle("new")),
                                            box.write("old-again.json", bundle("old", value_shift=0.2))])
            self.assertFalse(result["ready_to_import"])
            self.assertTrue(result["runs"][1]["existing_digest_conflict"])
            self.assertEqual([item["run_id"] for item in service.audit("study-1")], ["old"])

    def test_batch_preview_rejects_duplicate_ids(self):
        with Sandbox() as box:
            service = EvidenceService(box.database)
            with self.assertRaisesRegex(ContractError, "duplicate run identifiers"):
                service.preview_batch([box.write("one.json", bundle("same")),
                                       box.write("two.json", bundle("same", value_shift=0.2))])

    def test_readiness_explains_single_run_limitation(self):
        with Sandbox() as box:
            service = EvidenceService(box.database)
            service.import_run(box.write("a.json", bundle("a")))
            report = service.report("study-1")
            self.assertEqual(report["readiness"]["status"], "limited_evidence")
            self.assertIn("REPEATED_RUNS_REQUIRED",
                          {item["code"] for item in report["readiness"]["reasons"]})

    def test_readiness_changes_after_two_comparable_clean_runs(self):
        with Sandbox() as box:
            service = EvidenceService(box.database)
            service.import_run(box.write("a.json", bundle("a")))
            service.import_run(box.write("b.json", bundle("b", value_shift=0.05)))
            report = service.report("study-1")
            self.assertEqual(report["readiness"]["status"], "ready_for_interpretation")
            self.assertEqual(report["readiness"]["reasons"], [])

    def test_report_lists_device_inventory_and_accepted_data_coverage(self):
        with Sandbox() as box:
            service = EvidenceService(box.database)
            service.import_run(box.write("a.json", bundle("a")))
            report = service.report("study-1")
            self.assertEqual(report["instruments"][0]["instrument_id"], "instrument-demo")
            self.assertIn("baseline", {item["cohort"] for item in report["coverage"]["cohorts"]})
            self.assertEqual(report["run_profiles"][0]["measurement_count"], 8)


if __name__ == "__main__":
    unittest.main()
