from __future__ import annotations

from collections import defaultdict
from typing import Any

from labledger.analysis.statistics import mean, sample_variance


def _summary(values: list[float]) -> dict[str, float]:
    center = mean(values)
    variance = sample_variance(values) if len(values) > 1 else 0.0
    return {"n": float(len(values)), "mean": center, "variance": variance}


def _run_cohorts(record: dict[str, Any]) -> dict[str, dict[str, list[float]]]:
    values: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for measurement in record["measurements"]:
        if measurement["role"] == "sample":
            values[measurement["cohort"]][measurement["unit"]].append(measurement["corrected_value"])
    return values


def _contrast(run_id: str, candidate: list[float], reference: list[float]) -> dict[str, Any]:
    candidate_summary = _summary(candidate)
    reference_summary = _summary(reference)
    delta = candidate_summary["mean"] - reference_summary["mean"]
    standard_error = (candidate_summary["variance"] / candidate_summary["n"]
                      + reference_summary["variance"] / reference_summary["n"]) ** 0.5
    return {"run_id": run_id, "candidate_mean": candidate_summary["mean"],
            "reference_mean": reference_summary["mean"], "difference": delta,
            "standard_error": standard_error,
            "replicate_counts": {"candidate": int(candidate_summary["n"]),
                                 "reference": int(reference_summary["n"])} }


def compare_to_reference(run_records: list[dict[str, Any]]) -> dict[str, Any]:
    comparisons: dict[str, list[dict[str, Any]]] = defaultdict(list)
    skipped = []
    for record in run_records:
        if not record["accepted"]:
            continue
        cohorts = _run_cohorts(record)
        reference_name = record["reference_cohort"]
        reference_units = cohorts.get(reference_name, {})
        if len(reference_units) != 1:
            skipped.append({"run_id": record["run_id"], "reason": "reference is missing or has multiple units"})
            continue
        unit, reference_values = next(iter(reference_units.items()))
        for cohort, units in sorted(cohorts.items()):
            if cohort == reference_name:
                continue
            if set(units) != {unit}:
                skipped.append({"run_id": record["run_id"], "cohort": cohort,
                                "reason": "candidate and reference units differ"})
                continue
            comparisons[cohort].append(_contrast(record["run_id"], units[unit], reference_values))
    result = {}
    for cohort, runs in sorted(comparisons.items()):
        differences = [item["difference"] for item in runs]
        result[cohort] = {"runs": runs, "run_count": len(runs),
                          "mean_difference": mean(differences),
                          "difference_spread": max(differences) - min(differences),
                          "direction_consistent": len(differences) < 2 or min(differences) >= 0
                          or max(differences) <= 0}
    return {"reference_cohort_by_run": {record["run_id"]: record["reference_cohort"]
                                        for record in run_records if record["accepted"]},
            "comparisons": result, "skipped": skipped}
