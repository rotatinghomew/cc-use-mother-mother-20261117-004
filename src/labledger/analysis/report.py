from __future__ import annotations

from typing import Any


def build_report(study: dict[str, Any], analysis: dict[str, Any]) -> dict[str, Any]:
    cohorts = []
    for name, item in analysis["cohorts"].items():
        cohorts.append({"cohort": name, "run_count": item["run_count"],
                        "mean_spread": round(item["mean_spread"], 8),
                        "reproducible": item["reproducible"], "runs": item["runs"],
                        "instrument_ids": item["instrument_ids"],
                        "cross_instrument": item["cross_instrument"]})
    return {"study_id": study["study_id"], "status": study["status"],
            "protocol_versions": study["protocol_versions"], "accepted_runs": study["accepted_runs"],
            "rejected_runs": study["rejected_runs"], "cohorts": cohorts,
            "excluded_runs": analysis["excluded_runs"], "tolerance": analysis["tolerance"],
            "incompatible_cohorts": analysis["incompatible_cohorts"],
            "has_comparison": analysis["has_comparison"]}
