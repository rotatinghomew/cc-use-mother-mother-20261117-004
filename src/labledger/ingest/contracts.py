from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from labledger.errors import ContractError
from labledger.ingest.migrations import canonicalize


@dataclass(frozen=True)
class Measurement:
    measurement_id: str
    sample_id: str
    cohort: str
    replicate: int
    value: float
    unit: str
    measured_at: str
    role: str


@dataclass(frozen=True)
class Calibration:
    calibration_id: str
    offset: float
    valid_from: str
    valid_until: str
    max_abs_offset: float


@dataclass(frozen=True)
class RunBundle:
    study_id: str
    run_id: str
    protocol_version: int
    instrument_id: str
    unit: str
    control_min: float
    control_max: float
    min_replicates: int
    reference_cohort: str
    calibration: Calibration
    measurements: tuple[Measurement, ...]
    source_digest: str


def _text(value: Any, field: str, *, limit: int = 120) -> str:
    if not isinstance(value, str):
        raise ContractError(f"{field} must be text")
    result = value.strip()
    if not result or len(result) > limit or any(ord(char) < 32 for char in result):
        raise ContractError(f"{field} must be non-empty printable text up to {limit} chars")
    return result


def _number(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise ContractError(f"{field} must be a finite number")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ContractError(f"{field} must be a finite number") from exc
    if result != result or abs(result) == float("inf"):
        raise ContractError(f"{field} must be a finite number")
    return result


def _timestamp(value: Any, field: str) -> str:
    text = _text(value, field)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ContractError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_bundle(payload: dict[str, Any], source_digest: str) -> RunBundle:
    if not isinstance(payload, dict):
        raise ContractError("bundle root must be an object")
    required = {"study_id", "run_id", "protocol_version", "instrument_id", "unit",
                "control_range", "min_replicates", "reference_cohort", "calibration", "measurements"}
    missing = required - payload.keys()
    if missing:
        raise ContractError(f"bundle missing fields: {', '.join(sorted(missing))}")
    unknown = payload.keys() - required
    if unknown:
        raise ContractError(f"bundle contains unknown fields: {', '.join(sorted(unknown))}")
    version = payload["protocol_version"]
    if type(version) is not int or version not in {1, 2}:
        raise ContractError("protocol_version must be 1 or 2")
    payload = canonicalize(payload)
    replicates = payload["min_replicates"]
    if type(replicates) is not int or not 2 <= replicates <= 100:
        raise ContractError("min_replicates must be between 2 and 100")
    control_range = payload["control_range"]
    if not isinstance(control_range, dict) or set(control_range) != {"min", "max"}:
        raise ContractError("control_range must contain min and max")
    control_min = _number(control_range["min"], "control_range.min")
    control_max = _number(control_range["max"], "control_range.max")
    if control_min >= control_max:
        raise ContractError("control_range.min must be below max")
    raw_calibration = payload["calibration"]
    if not isinstance(raw_calibration, dict):
        raise ContractError("calibration must be an object")
    calibration = Calibration(
        _text(raw_calibration.get("id"), "calibration.id"),
        _number(raw_calibration.get("offset"), "calibration.offset"),
        _timestamp(raw_calibration.get("valid_from"), "calibration.valid_from"),
        _timestamp(raw_calibration.get("valid_until"), "calibration.valid_until"),
        _number(raw_calibration.get("max_abs_offset"), "calibration.max_abs_offset"),
    )
    if calibration.valid_from >= calibration.valid_until or calibration.max_abs_offset < 0:
        raise ContractError("calibration interval and tolerance are invalid")
    if abs(calibration.offset) > 1_000_000 or calibration.max_abs_offset > 1_000_000:
        raise ContractError("calibration values exceed the supported numeric range")
    raw_measurements = payload["measurements"]
    if not isinstance(raw_measurements, list) or not raw_measurements:
        raise ContractError("measurements must be a non-empty array")
    if len(raw_measurements) > 50_000:
        raise ContractError("a bundle cannot contain more than 50000 measurements")
    measurements = []
    seen = set()
    for index, row in enumerate(raw_measurements):
        if not isinstance(row, dict):
            raise ContractError(f"measurements[{index}] must be an object")
        keys = {"id", "sample_id", "cohort", "replicate", "value", "unit", "measured_at", "role"}
        if set(row) != keys:
            raise ContractError(f"measurements[{index}] must contain exactly the documented fields")
        measurement_id = _text(row["id"], f"measurements[{index}].id")
        if measurement_id in seen:
            raise ContractError(f"duplicate measurement id: {measurement_id}")
        seen.add(measurement_id)
        replicate = row["replicate"]
        if type(replicate) is not int or replicate < 1:
            raise ContractError(f"measurements[{index}].replicate must be a positive integer")
        role = _text(row["role"], f"measurements[{index}].role")
        if role not in {"control", "sample"}:
            raise ContractError(f"measurements[{index}].role must be control or sample")
        measurements.append(Measurement(
            measurement_id, _text(row["sample_id"], f"measurements[{index}].sample_id"),
            _text(row["cohort"], f"measurements[{index}].cohort"), replicate,
            _number(row["value"], f"measurements[{index}].value"),
            _text(row["unit"], f"measurements[{index}].unit"),
            _timestamp(row["measured_at"], f"measurements[{index}].measured_at"), role,
        ))
        if abs(measurements[-1].value) > 1_000_000_000_000:
            raise ContractError(f"measurements[{index}].value exceeds the supported numeric range")
    if not any(row.role == "control" for row in measurements):
        raise ContractError("at least one control measurement is required")
    return RunBundle(
        _text(payload["study_id"], "study_id"), _text(payload["run_id"], "run_id"),
        version, _text(payload["instrument_id"], "instrument_id"), _text(payload["unit"], "unit"),
        control_min, control_max, replicates, _text(payload["reference_cohort"], "reference_cohort"),
        calibration, tuple(measurements), source_digest,
    )
