from __future__ import annotations

from typing import Any


def assess_readiness(report: dict[str, Any]) -> dict[str, Any]:
    reasons = []
    accepted = report["accepted_runs"]
    rejected = report["rejected_runs"]
    if len(accepted) < 2:
        reasons.append({"code": "REPEATED_RUNS_REQUIRED",
                        "detail": "at least two accepted runs are needed for repeatability assessment"})
    if rejected:
        reasons.append({"code": "REJECTED_EVIDENCE_PRESENT",
                        "detail": "one or more runs failed quality gates and remain excluded"})
    if report["incompatible_cohorts"]:
        reasons.append({"code": "UNIT_INCOMPATIBILITY",
                        "detail": "some cohorts use incompatible units across accepted runs"})
    if any(item["cross_instrument"] for item in report["cohorts"]):
        reasons.append({"code": "CROSS_INSTRUMENT_REVIEW",
                        "detail": "at least one comparison spans instruments and needs calibration review"})
    if not report["coverage"]["complete"]:
        reasons.append({"code": "INCOMPLETE_COHORT_COVERAGE",
                        "detail": "at least one observed or reference cohort is absent from an accepted run"})
    if not report["has_comparison"]:
        reasons.append({"code": "NO_REPRODUCIBILITY_COMPARISON",
                        "detail": "no cohort has comparable observations in two accepted runs"})
    if len(accepted) >= 2 and not reasons:
        status = "ready_for_interpretation"
    elif accepted:
        status = "limited_evidence"
    else:
        status = "review_required"
    return {"status": status, "reasons": reasons,
            "comparison_count": sum(1 for item in report["cohorts"] if item["run_count"] >= 2),
            "accepted_run_count": len(accepted), "rejected_run_count": len(rejected)}
