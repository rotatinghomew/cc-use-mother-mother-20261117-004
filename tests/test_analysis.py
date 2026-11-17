import unittest

from labledger.analysis.contrasts import compare_to_reference
from labledger.analysis.reproducibility import analyze_runs
from labledger.analysis.statistics import (coefficient_of_variation, mean, percentile_summary,
                                           quantile, sample_variance, standard_deviation)
from tests.helpers import bundle


def record(payload, accepted=True, *, corrected_shift=0.0):
    measurements = [{"measurement_id": item["id"], "cohort": item["cohort"],
                     "role": item["role"], "unit": item["unit"], "sample_id": item["sample_id"],
                     "corrected_value": item["value"] + corrected_shift}
                    for item in payload["measurements"]]
    return {"run_id": payload["run_id"], "accepted": accepted, "instrument_id": payload["instrument_id"],
            "reference_cohort": payload["reference_cohort"], "measurements": measurements}


class DescriptiveStatisticsTests(unittest.TestCase):
    def test_mean_uses_all_observations(self):
        self.assertEqual(mean([1, 2, 5]), 8 / 3)

    def test_mean_rejects_empty_input(self):
        with self.assertRaisesRegex(ValueError, "at least one"):
            mean([])

    def test_sample_variance_uses_unbiased_denominator(self):
        self.assertEqual(sample_variance([1, 2, 3]), 1)

    def test_sample_variance_rejects_single_observation(self):
        with self.assertRaisesRegex(ValueError, "at least two"):
            sample_variance([3])

    def test_standard_deviation_is_square_root_of_sample_variance(self):
        self.assertEqual(standard_deviation([1, 2, 3]), 1)

    def test_coefficient_of_variation_is_scale_invariant(self):
        self.assertAlmostEqual(coefficient_of_variation([10, 20, 30]),
                               coefficient_of_variation([100, 200, 300]))

    def test_coefficient_of_variation_rejects_zero_mean(self):
        with self.assertRaisesRegex(ValueError, "zero mean"):
            coefficient_of_variation([-1, 1])

    def test_quantile_interpolates_between_observations(self):
        self.assertEqual(quantile([0, 10], 0.25), 2.5)

    def test_quantile_endpoints_match_sample_extremes(self):
        self.assertEqual(quantile([4, 1, 7], 0), 1)
        self.assertEqual(quantile([4, 1, 7], 1), 7)

    def test_quantile_rejects_invalid_probability_and_empty_data(self):
        for values, probability in (([], 0.5), ([1], -0.1), ([1], 1.1)):
            with self.subTest(values=values, probability=probability), self.assertRaises(ValueError):
                quantile(values, probability)

    def test_percentile_summary_keeps_single_sample_defined(self):
        summary = percentile_summary([5])
        self.assertEqual(summary["sample_sd"], 0)
        self.assertEqual(summary["cv"], 0)

    def test_percentile_summary_reports_interquartile_points(self):
        summary = percentile_summary([1, 2, 3, 4])
        self.assertEqual(summary["median"], 2.5)
        self.assertEqual(summary["p25"], 1.75)
        self.assertEqual(summary["p75"], 3.25)

    def test_nonzero_mean_summary_reports_cv(self):
        summary = percentile_summary([2, 4, 6])
        self.assertAlmostEqual(summary["cv"], 0.5)


class CrossRunAnalysisTests(unittest.TestCase):
    def test_two_runs_within_tolerance_are_reproducible(self):
        first = bundle("a")
        second = bundle("b", value_shift=0.05)
        analysis = analyze_runs([record(first), record(second)], tolerance=0.1)
        self.assertTrue(analysis["cohorts"]["candidate"]["reproducible"])
        self.assertEqual(analysis["cohorts"]["candidate"]["run_count"], 2)

    def test_two_runs_outside_tolerance_are_not_reproducible(self):
        first = bundle("a")
        second = bundle("b", value_shift=0.5)
        analysis = analyze_runs([record(first), record(second)], tolerance=0.1)
        self.assertFalse(analysis["cohorts"]["candidate"]["reproducible"])

    def test_single_run_is_not_mislabeled_reproducible(self):
        analysis = analyze_runs([record(bundle("a"))], tolerance=10)
        self.assertFalse(analysis["cohorts"]["candidate"]["reproducible"])
        self.assertFalse(analysis["has_comparison"])

    def test_rejected_run_is_excluded_from_estimate(self):
        accepted = bundle("good")
        rejected = bundle("bad", value_shift=100)
        analysis = analyze_runs([record(accepted), record(rejected, accepted=False)], tolerance=1)
        self.assertEqual(analysis["cohorts"]["candidate"]["run_count"], 1)
        self.assertEqual(analysis["excluded_runs"], ["bad"])

    def test_mixed_units_are_reported_and_never_compared(self):
        first = bundle("a", unit="signal")
        second = bundle("b", unit="other")
        analysis = analyze_runs([record(first), record(second)], tolerance=0.1)
        self.assertIn("candidate", analysis["incompatible_cohorts"])
        self.assertNotIn("candidate", analysis["cohorts"])
        self.assertFalse(analysis["has_comparison"])

    def test_negative_tolerance_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "negative"):
            analyze_runs([], tolerance=-1)

    def test_reference_contrast_uses_run_local_baseline(self):
        first = record(bundle("a"))
        second = record(bundle("b", value_shift=0.2))
        result = compare_to_reference([first, second])
        candidate = result["comparisons"]["candidate"]
        self.assertEqual(candidate["run_count"], 2)
        self.assertAlmostEqual(candidate["runs"][0]["difference"], 1.0)
        self.assertAlmostEqual(candidate["runs"][1]["difference"], 1.2)
        self.assertTrue(candidate["direction_consistent"])

    def test_reference_comparison_reports_standard_error_and_sample_counts(self):
        result = compare_to_reference([record(bundle("a"))])
        candidate = result["comparisons"]["candidate"]["runs"][0]
        self.assertGreater(candidate["standard_error"], 0)
        self.assertEqual(candidate["replicate_counts"], {"candidate": 3, "reference": 3})

    def test_missing_reference_is_explained_not_substituted(self):
        payload = bundle("a")
        current = record(payload)
        current["reference_cohort"] = "not-present"
        result = compare_to_reference([current])
        self.assertEqual(result["comparisons"], {})
        self.assertIn("missing", result["skipped"][0]["reason"])

    def test_candidate_with_incompatible_unit_is_skipped(self):
        current = record(bundle("a"))
        for row in current["measurements"]:
            if row["cohort"] == "candidate":
                row["unit"] = "different"
        result = compare_to_reference([current])
        self.assertEqual(result["comparisons"], {})
        self.assertEqual(result["skipped"][0]["cohort"], "candidate")

    def test_rejected_runs_do_not_contribute_to_contrasts(self):
        result = compare_to_reference([record(bundle("a"), accepted=False)])
        self.assertEqual(result["comparisons"], {})

    def test_opposite_effect_directions_are_visible(self):
        left = record(bundle("a"))
        right = record(bundle("b"))
        for row in right["measurements"]:
            if row["cohort"] == "candidate":
                row["corrected_value"] = 1.0
        result = compare_to_reference([left, right])
        self.assertFalse(result["comparisons"]["candidate"]["direction_consistent"])


if __name__ == "__main__":
    unittest.main()
