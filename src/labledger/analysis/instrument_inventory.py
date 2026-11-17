from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any


def instrument_inventory(run_records: list[dict[str, Any]], history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    provenance = {(item["run_id"], item["instrument_id"]): item for item in history}
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for run in run_records:
        grouped[run["instrument_id"]].append(run)
    inventory = []
    for instrument_id, runs in sorted(grouped.items()):
        units = Counter(run["unit"] for run in runs)
        accepted = [run for run in runs if run["accepted"]]
        rejected = [run for run in runs if not run["accepted"]]
        protocols = Counter(run["protocol_version"] for run in runs)
        cohorts = set()
        diagnostic_counts: Counter[str] = Counter()
        calibrations = []
        for run in runs:
            cohorts.update(item["cohort"] for item in run["measurements"] if item["role"] == "sample")
            diagnostic_counts.update(item["code"] for item in run.get("diagnostics", []))
            item = provenance.get((run["run_id"], instrument_id))
            if item:
                calibrations.append(item["calibration_id"])
        inventory.append({"instrument_id": instrument_id,
                          "run_ids": sorted(run["run_id"] for run in runs),
                          "accepted_runs": sorted(run["run_id"] for run in accepted),
                          "rejected_runs": sorted(run["run_id"] for run in rejected),
                          "units": dict(sorted(units.items())),
                          "protocol_versions": {str(key): value for key, value in sorted(protocols.items())},
                          "calibration_ids": calibrations, "cohorts": sorted(cohorts),
                          "diagnostic_counts": dict(sorted(diagnostic_counts.items()))})
    return inventory
