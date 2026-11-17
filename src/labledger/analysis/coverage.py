from __future__ import annotations

from collections import defaultdict
from typing import Any


def cohort_coverage(run_records: list[dict[str, Any]]) -> dict[str, Any]:
    accepted = [item for item in run_records if item["accepted"]]
    rejected = [item["run_id"] for item in run_records if not item["accepted"]]
    counts: dict[str, dict[str, int]] = defaultdict(dict)
    expected = set()
    for run in accepted:
        observed = {item["cohort"] for item in run["measurements"] if item["role"] == "sample"}
        expected.add(run["reference_cohort"])
        expected.update(observed)
        for cohort in observed:
            counts[cohort][run["run_id"]] = sum(
                1 for row in run["measurements"] if row["role"] == "sample" and row["cohort"] == cohort)
    run_ids = [item["run_id"] for item in accepted]
    cohorts = []
    for cohort in sorted(expected):
        by_run = counts.get(cohort, {})
        present = sorted(by_run)
        cohorts.append({"cohort": cohort, "present_runs": present,
                        "missing_runs": sorted(set(run_ids) - set(present)),
                        "measurement_counts": dict(sorted(by_run.items())),
                        "coverage_fraction": len(present) / len(run_ids) if run_ids else 0.0})
    return {"accepted_runs": run_ids, "rejected_runs": sorted(rejected),
            "cohorts": cohorts, "complete": all(not item["missing_runs"] for item in cohorts)}
