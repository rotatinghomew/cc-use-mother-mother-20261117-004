import unittest

from labledger.ingest.contracts import parse_bundle
from labledger.quality.calibration import check_calibration, corrected_value
from labledger.quality.diagnostics import diagnose, duplicate_replicates
from labledger.quality.gates import qualify
from tests.helpers import bundle


class QualityGateTests(unittest.TestCase):
    def parsed(self, payload=None):
        return parse_bundle(payload or bundle(), "digest")

    def test_valid_controls_pass_and_correction_is_applied(self):
        parsed = self.parsed(bundle(offset=0.1))
        decision = qualify(parsed)
        self.assertTrue(decision.accepted)
        first_control = parsed.measurements[0]
        self.assertAlmostEqual(decision.corrected[first_control.measurement_id], 0.9)

    def test_control_outside_range_blocks_run(self):
        parsed = self.parsed(bundle(control=2.0))
        decision = qualify(parsed)
        self.assertFalse(decision.accepted)
        self.assertIn("CONTROL_OUT_OF_RANGE", {item.code for item in decision.findings})

    def test_offset_tolerance_blocks_instead_of_silently_correcting(self):
        parsed = self.parsed(bundle(offset=0.3))
        decision = qualify(parsed)
        self.assertFalse(decision.accepted)
        self.assertIn("OFFSET_OUT_OF_TOLERANCE", {item.code for item in decision.findings})

    def test_calibration_window_covers_every_sample(self):
        payload = bundle()
        payload["measurements"][-1]["measured_at"] = "2026-11-03T10:00:00Z"
        parsed = self.parsed(payload)
        findings = check_calibration(parsed.calibration, parsed.measurements)
        self.assertEqual(findings[0].code, "CALIBRATION_WINDOW_MISS")
        self.assertIn(parsed.measurements[-1].measurement_id, findings[0].detail)

    def test_unit_mismatch_blocks_whole_run(self):
        payload = bundle()
        payload["measurements"][-1]["unit"] = "other"
        decision = qualify(self.parsed(payload))
        self.assertFalse(decision.accepted)
        self.assertIn("UNIT_MISMATCH", {item.code for item in decision.findings})

    def test_missing_cohort_sample_count_blocks_run(self):
        payload = bundle()
        payload["measurements"] = [item for item in payload["measurements"]
                                   if not (item["cohort"] == "candidate" and item["sample_id"] != "candidate-1")]
        decision = qualify(self.parsed(payload))
        self.assertFalse(decision.accepted)
        self.assertIn("INSUFFICIENT_REPLICATES", {item.code for item in decision.findings})

    def test_reference_cohort_missing_is_a_separate_diagnostic(self):
        payload = bundle()
        payload["reference_cohort"] = "absent"
        diagnostics = diagnose(self.parsed(payload), qualify(self.parsed(payload)))
        finding = next(item for item in diagnostics if item.code == "REFERENCE_COHORT_MISSING")
        self.assertEqual(finding.severity, "blocking")

    def test_repeated_sample_replicate_is_detected(self):
        payload = bundle()
        original = payload["measurements"][-1]
        repeated = dict(original, id="different-id")
        payload["measurements"].append(repeated)
        result = duplicate_replicates(self.parsed(payload))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].code, "REPLICATE_COLLISION")

    def test_same_replicate_number_for_different_samples_is_valid(self):
        payload = bundle()
        parsed = self.parsed(payload)
        self.assertEqual(duplicate_replicates(parsed), [])

    def test_controls_do_not_trigger_sample_replicate_collision(self):
        payload = bundle()
        parsed = self.parsed(payload)
        self.assertEqual(duplicate_replicates(parsed), [])

    def test_high_spread_is_advisory_not_an_automatic_rejection(self):
        payload = bundle()
        candidate = [row for row in payload["measurements"] if row["cohort"] == "candidate"]
        for row, value in zip(candidate, (0.1, 3.0, 9.0)):
            row["value"] = value
        parsed = self.parsed(payload)
        decision = qualify(parsed)
        diagnostics = diagnose(parsed, decision)
        warning = next(item for item in diagnostics if item.code == "HIGH_WITHIN_RUN_VARIATION")
        self.assertEqual(warning.severity, "warning")
        self.assertTrue(decision.accepted)

    def test_calibration_corrected_control_can_pass(self):
        payload = bundle(offset=0.15, control=1.15)
        decision = qualify(self.parsed(payload))
        self.assertTrue(decision.accepted)

    def test_empty_valid_window_is_rejected_by_contract(self):
        payload = bundle()
        payload["calibration"]["valid_until"] = "2026-10-31T23:59:59Z"
        from labledger.errors import ContractError
        with self.assertRaises(ContractError):
            self.parsed(payload)

    def test_negative_offset_tolerance_is_rejected(self):
        payload = bundle()
        payload["calibration"]["max_abs_offset"] = -0.1
        from labledger.errors import ContractError
        with self.assertRaisesRegex(ContractError, "tolerance"):
            self.parsed(payload)

    def test_measurement_values_are_preserved_as_raw_and_corrected_separately(self):
        parsed = self.parsed(bundle(offset=0.1))
        decision = qualify(parsed)
        sample = next(item for item in parsed.measurements if item.role == "sample")
        self.assertEqual(sample.value, 2.0)
        self.assertAlmostEqual(decision.corrected[sample.measurement_id], 1.9)

    def test_zero_mean_spread_does_not_crash_diagnostic(self):
        payload = bundle()
        for row in payload["measurements"]:
            if row["cohort"] == "baseline":
                row["value"] = 0.0
        parsed = self.parsed(payload)
        diagnostics = diagnose(parsed, qualify(parsed))
        self.assertIsInstance(diagnostics, list)

    def test_duplicate_ids_are_rejected_before_quality_gate(self):
        payload = bundle()
        payload["measurements"][1]["id"] = payload["measurements"][0]["id"]
        from labledger.errors import ContractError
        with self.assertRaisesRegex(ContractError, "duplicate measurement"):
            self.parsed(payload)

    def test_large_measurement_values_keep_finite_corrected_result(self):
        payload = bundle()
        payload["measurements"][-1]["value"] = 1e11
        decision = qualify(self.parsed(payload))
        self.assertTrue(decision.accepted)
        self.assertGreater(decision.corrected[payload["measurements"][-1]["id"]], 1e10)

    def test_robust_outlier_is_a_warning_and_keeps_source_row_identifiable(self):
        payload = bundle()
        candidate = [row for row in payload["measurements"] if row["cohort"] == "candidate"]
        for row, value in zip(candidate, (3.0, 3.1, 100.0)):
            row["value"] = value
        parsed = self.parsed(payload)
        decision = qualify(parsed)
        findings = diagnose(parsed, decision)
        outlier = next(item for item in findings if item.code == "ROBUST_OUTLIER_CANDIDATE")
        self.assertEqual(outlier.severity, "warning")
        self.assertIn(candidate[-1]["id"], outlier.detail)
        self.assertTrue(decision.accepted)


if __name__ == "__main__":
    unittest.main()
