from __future__ import annotations

from collections import defaultdict
from typing import Any

from labledger.analysis.statistics import percentile_summary


def profile_runs(run_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    profiles = []
    for run in sorted(run_records, key=lambda item: item["run_id"]):
        samples: dict[str, list[float]] = defaultdict(list)
        controls = []
        for measurement in run["measurements"]:
            if measurement["role"] == "control":
                controls.append(measurement["corrected_value"])
            else:
                samples[measurement["cohort"]].append(measurement["corrected_value"])
        sample_summary = {cohort: percentile_summary(values) for cohort, values in sorted(samples.items())}
        control_summary = percentile_summary(controls) if controls else None
        profiles.append({"run_id": run["run_id"], "accepted": run["accepted"],
                         "instrument_id": run["instrument_id"], "unit": run["unit"],
                         "protocol_version": run["protocol_version"],
                         "measurement_count": sum(len(values) for values in samples.values()) + len(controls),
                         "control_summary": control_summary, "cohorts": sample_summary,
                         "diagnostic_codes": sorted({item["code"] for item in run.get("diagnostics", [])})})
    return profiles
