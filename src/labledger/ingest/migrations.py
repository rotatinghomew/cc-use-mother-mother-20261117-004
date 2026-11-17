from __future__ import annotations

from copy import deepcopy
from typing import Any

from labledger.errors import ContractError


def canonicalize(payload: dict[str, Any]) -> dict[str, Any]:
    """升级受支持的历史数据结构且不改变其含义。"""
    version = payload.get("protocol_version")
    if version not in {1, 2}:
        return payload
    migrated = deepcopy(payload)
    rows = migrated.get("measurements")
    if not isinstance(rows, list):
        return migrated
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        if version == 1:
            if "reading" not in row or "value" in row:
                raise ContractError(f"protocol 1 measurement {index} must use reading, not value")
            row["value"] = row.pop("reading")
        elif "reading" in row:
            raise ContractError(f"protocol 2 measurement {index} must use value, not reading")
    return migrated


def accepted_protocol_versions() -> tuple[int, ...]:
    return (1, 2)


def schema_description(version: int) -> dict[str, Any]:
    if version not in accepted_protocol_versions():
        raise ContractError(f"unsupported protocol version: {version}")
    return {"version": version, "measurement_value_field": "reading" if version == 1 else "value",
            "measurement_identity_fields": ("id", "sample_id", "cohort", "replicate"),
            "timestamp_timezone_required": True, "unknown_measurement_fields": "rejected",
            "calibration_required": True, "control_range_required": True,
            "reference_cohort_required": True, "digest_scope": "exact source bytes",
            "measurement_roles": ("control", "sample"), "timestamp_normalization": "UTC",
            "protocol_versions": accepted_protocol_versions(), "unit_conversion": "never implicit"}


def measurement_value_field(version: int) -> str:
    return str(schema_description(version)["measurement_value_field"])
