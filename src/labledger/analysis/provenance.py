from __future__ import annotations

from typing import Any


def lineage_summary(history: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(history, key=lambda item: (item["run_id"], item["source_digest"]))
    runs = []
    seen_digests: dict[str, str] = {}
    duplicate_content = []
    protocol_versions = set()
    calibrations: dict[str, list[str]] = {}
    for item in ordered:
        digest = item["source_digest"]
        if digest in seen_digests:
            duplicate_content.append({"run_id": item["run_id"], "same_as": seen_digests[digest]})
        else:
            seen_digests[digest] = item["run_id"]
        protocol_versions.add(item["protocol_version"])
        calibrations.setdefault(item["instrument_id"], []).append(item["calibration_id"])
        runs.append({"run_id": item["run_id"], "digest": digest,
                     "accepted": item["accepted"], "instrument_id": item["instrument_id"],
                     "calibration_id": item["calibration_id"],
                     "protocol_version": item["protocol_version"]})
    return {"runs": runs, "protocol_versions": sorted(protocol_versions),
            "calibrations_by_instrument": {name: values for name, values in sorted(calibrations.items())},
            "duplicate_content": duplicate_content}
