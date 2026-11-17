from collections import defaultdict
from typing import Any

from labledger.analysis.statistics import percentile_summary


def analyze_runs(run_records: list[dict[str, Any]], *, tolerance: float) -> dict[str, Any]:
    if tolerance < 0:
        raise ValueError("tolerance cannot be negative")
    by_cohort: dict[str, list[tuple[str, list[float]]]] = defaultdict(list)
    excluded = []
    units_by_cohort: dict[str, set[str]] = defaultdict(set)
    instruments_by_cohort: dict[str, set[str]] = defaultdict(set)
    for record in run_records:
        if not record["accepted"]:
            excluded.append(record["run_id"])
            continue
        grouped: dict[str, list[float]] = defaultdict(list)
        for measurement in record["measurements"]:
            if measurement["role"] == "sample":
                grouped[measurement["cohort"]].append(measurement["corrected_value"])
                units_by_cohort[measurement["cohort"]].add(measurement["unit"])
                instruments_by_cohort[measurement["cohort"]].add(record["instrument_id"])
        for cohort, values in grouped.items():
            by_cohort[cohort].append((record["run_id"], values))
    cohorts = {}
    incompatible = sorted(cohort for cohort, units in units_by_cohort.items() if len(units) > 1)
    for cohort, runs in sorted(by_cohort.items()):
        if cohort in incompatible:
            continue
        run_summaries = {run_id: percentile_summary(values) for run_id, values in sorted(runs)}
        means = [summary["mean"] for summary in run_summaries.values()]
        spread = max(means) - min(means) if len(means) > 1 else 0.0
        cohorts[cohort] = {"runs": run_summaries, "run_count": len(runs), "mean_spread": spread,
                           "reproducible": len(runs) >= 2 and spread <= tolerance,
                           "instrument_ids": sorted(instruments_by_cohort[cohort]),
                           "cross_instrument": len(instruments_by_cohort[cohort]) > 1}
    return {"cohorts": cohorts, "excluded_runs": sorted(excluded),
            "incompatible_cohorts": incompatible, "tolerance": tolerance,
            "has_comparison": any(item["run_count"] >= 2 for item in cohorts.values())}
