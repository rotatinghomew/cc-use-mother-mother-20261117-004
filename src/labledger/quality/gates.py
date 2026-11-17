from collections import Counter
from dataclasses import dataclass

from labledger.ingest.contracts import RunBundle
from labledger.quality.calibration import CalibrationFinding, check_calibration, corrected_value


@dataclass(frozen=True)
class QualityFinding:
    code: str
    severity: str
    detail: str


@dataclass(frozen=True)
class QualityDecision:
    accepted: bool
    findings: tuple[QualityFinding, ...]
    corrected: dict[str, float]


def _convert_calibration_findings(items: list[CalibrationFinding]) -> list[QualityFinding]:
    return [QualityFinding(item.code, item.severity, item.detail) for item in items]


def qualify(bundle: RunBundle) -> QualityDecision:
    findings = _convert_calibration_findings(check_calibration(bundle.calibration, bundle.measurements))
    cohorts = Counter()
    sample_ids = set()
    corrected = {}
    for row in bundle.measurements:
        if row.unit != bundle.unit:
            findings.append(QualityFinding("UNIT_MISMATCH", "blocking",
                                           f"{row.measurement_id} uses {row.unit}, expected {bundle.unit}"))
        if row.role == "sample":
            cohorts[row.cohort] += 1
            sample_ids.add((row.cohort, row.sample_id))
        corrected[row.measurement_id] = corrected_value(row.value, bundle.calibration)
    controls = [corrected[row.measurement_id] for row in bundle.measurements if row.role == "control"]
    if not controls:
        findings.append(QualityFinding("CONTROL_MISSING", "blocking", "no controls were supplied"))
    else:
        outside = [value for value in controls if not bundle.control_min <= value <= bundle.control_max]
        if outside:
            findings.append(QualityFinding("CONTROL_OUT_OF_RANGE", "blocking",
                                           f"{len(outside)} corrected control value(s) outside declared range"))
    for cohort, count in sorted(cohorts.items()):
        distinct = len({sample for group, sample in sample_ids if group == cohort})
        if distinct < bundle.min_replicates:
            findings.append(QualityFinding("INSUFFICIENT_REPLICATES", "blocking",
                                           f"cohort {cohort} has {distinct} samples; needs {bundle.min_replicates}"))
        elif count < bundle.min_replicates:
            findings.append(QualityFinding("INSUFFICIENT_MEASUREMENTS", "blocking",
                                           f"cohort {cohort} has {count} measurements; needs {bundle.min_replicates}"))
    return QualityDecision(not any(item.severity == "blocking" for item in findings),
                           tuple(findings), corrected)
