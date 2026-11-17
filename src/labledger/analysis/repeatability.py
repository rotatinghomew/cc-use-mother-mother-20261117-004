from __future__ import annotations

from collections import defaultdict
from math import sqrt
from typing import Any

from labledger.analysis.statistics import mean, sample_variance


def repeatability_summary(run_records: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for run in run_records:
        if not run["accepted"]:
            continue
        for measurement in run["measurements"]:
            if measurement["role"] == "sample":
                groups[measurement["cohort"]][run["run_id"]].append(measurement["corrected_value"])
    result = {}
    for cohort, runs in sorted(groups.items()):
        run_means = {run_id: mean(values) for run_id, values in sorted(runs.items())}
        residual_ss = 0.0
        residual_df = 0
        for values in runs.values():
            if len(values) > 1:
                residual_ss += sample_variance(values) * (len(values) - 1)
                residual_df += len(values) - 1
        pooled_within_sd = sqrt(residual_ss / residual_df) if residual_df else 0.0
        between_run_sd = sqrt(sample_variance(run_means.values())) if len(run_means) > 1 else 0.0
        result[cohort] = {"run_means": run_means, "pooled_within_run_sd": pooled_within_sd,
                          "between_run_sd": between_run_sd,
                          "measurement_count": sum(map(len, runs.values())),
                          "run_count": len(runs)}
    return result
