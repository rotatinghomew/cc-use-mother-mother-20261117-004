from __future__ import annotations

from collections import defaultdict
from statistics import median
from typing import Any


def control_trend(run_records: list[dict[str, Any]], *, change_limit: float) -> dict[str, Any]:
    if change_limit < 0:
        raise ValueError("change_limit cannot be negative")
    histories: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for run in run_records:
        controls = [item["corrected_value"] for item in run["measurements"] if item["role"] == "control"]
        if not controls:
            continue
        histories[(run["instrument_id"], run["unit"])].append(
            {"run_id": run["run_id"], "accepted": run["accepted"],
             "center": median(controls), "control_count": len(controls)})
    instruments = []
    for (instrument_id, unit), history in sorted(histories.items()):
        reference_runs = [item for item in history if item["accepted"]]
        reference_data = reference_runs or history
        reference = median(item["center"] for item in reference_data)
        runs = []
        for item in history:
            delta = item["center"] - reference
            runs.append({**item, "delta_from_median": delta,
                         "drift_warning": abs(delta) > change_limit})
        instruments.append({"instrument_id": instrument_id, "unit": unit,
                            "reference_control_median": reference,
                            "reference_run_count": len(reference_runs), "runs": runs,
                            "warning_runs": [item["run_id"] for item in runs if item["drift_warning"]]})
    return {"change_limit": change_limit, "instruments": instruments}
