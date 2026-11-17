from dataclasses import dataclass
from datetime import datetime

from labledger.ingest.contracts import Calibration, Measurement


@dataclass(frozen=True)
class CalibrationFinding:
    code: str
    severity: str
    detail: str


def check_calibration(calibration: Calibration, measurements: tuple[Measurement, ...]) -> list[CalibrationFinding]:
    findings = []
    if abs(calibration.offset) > calibration.max_abs_offset:
        findings.append(CalibrationFinding("OFFSET_OUT_OF_TOLERANCE", "blocking",
                                           "calibration offset exceeds its declared tolerance"))
    start = datetime.fromisoformat(calibration.valid_from.replace("Z", "+00:00"))
    end = datetime.fromisoformat(calibration.valid_until.replace("Z", "+00:00"))
    invalid_ids = []
    for measurement in measurements:
        observed = datetime.fromisoformat(measurement.measured_at.replace("Z", "+00:00"))
        if not start <= observed <= end:
            invalid_ids.append(measurement.measurement_id)
    if invalid_ids:
        findings.append(CalibrationFinding("CALIBRATION_WINDOW_MISS", "blocking",
                                           f"measurements outside calibration window: {', '.join(invalid_ids)}"))
    return findings


def corrected_value(value: float, calibration: Calibration) -> float:
    return value - calibration.offset
