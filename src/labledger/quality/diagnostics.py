from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from statistics import median

from labledger.ingest.contracts import RunBundle
from labledger.quality.gates import QualityDecision


@dataclass(frozen=True)
class Diagnostic:
    code: str
    severity: str
    scope: str
    detail: str


def _group_samples(bundle: RunBundle, decision: QualityDecision) -> dict[str, list[float]]:
    groups: dict[str, list[float]] = defaultdict(list)
    for measurement in bundle.measurements:
        if measurement.role == "sample":
            groups[measurement.cohort].append(decision.corrected[measurement.measurement_id])
    return groups


def duplicate_replicates(bundle: RunBundle) -> list[Diagnostic]:
    seen: set[tuple[str, str, int]] = set()
    findings = []
    for item in bundle.measurements:
        key = item.cohort, item.sample_id, item.replicate
        if item.role == "sample" and key in seen:
            findings.append(Diagnostic("REPLICATE_COLLISION", "blocking", item.cohort,
                                       f"sample {item.sample_id} repeats replicate {item.replicate}"))
        if item.role == "sample":
            seen.add(key)
    return findings


def check_reference_cohort(bundle: RunBundle) -> list[Diagnostic]:
    cohorts = {item.cohort for item in bundle.measurements if item.role == "sample"}
    if bundle.reference_cohort not in cohorts:
        return [Diagnostic("REFERENCE_COHORT_MISSING", "blocking", bundle.reference_cohort,
                           "declared reference cohort has no sample measurements")]
    return []


def spread_warnings(bundle: RunBundle, decision: QualityDecision, *, max_cv: float = 0.5) -> list[Diagnostic]:
    findings = []
    for cohort, values in sorted(_group_samples(bundle, decision).items()):
        center = sum(values) / len(values)
        if center == 0:
            continue
        variance = sum((value - center) ** 2 for value in values) / max(1, len(values) - 1)
        cv = variance ** 0.5 / abs(center)
        if cv > max_cv:
            findings.append(Diagnostic("HIGH_WITHIN_RUN_VARIATION", "warning", cohort,
                                       f"coefficient of variation {cv:.6f} exceeds {max_cv:.6f}"))
    return findings


def outlier_candidates(bundle: RunBundle, decision: QualityDecision, *, threshold: float = 3.5) -> list[Diagnostic]:
    findings = []
    groups: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for measurement in bundle.measurements:
        if measurement.role == "sample":
            groups[measurement.cohort].append(
                (measurement.measurement_id, decision.corrected[measurement.measurement_id]))
    for cohort, rows in sorted(groups.items()):
        if len(rows) < 3:
            continue
        center = median(value for _, value in rows)
        deviations = [abs(value - center) for _, value in rows]
        mad = median(deviations)
        for measurement_id, value in rows:
            distance = abs(value - center)
            score = (distance / (1.4826 * mad)) if mad else (float("inf") if distance else 0.0)
            if score > threshold:
                findings.append(Diagnostic("ROBUST_OUTLIER_CANDIDATE", "warning", cohort,
                                           f"measurement {measurement_id} has robust z-score {score:.6g}"))
    return findings


def diagnose(bundle: RunBundle, decision: QualityDecision) -> list[Diagnostic]:
    return (duplicate_replicates(bundle) + check_reference_cohort(bundle)
            + spread_warnings(bundle, decision) + outlier_candidates(bundle, decision))
