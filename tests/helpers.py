from __future__ import annotations

import json
import tempfile
from pathlib import Path


def bundle(run_id: str = "run-a", *, study_id: str = "study-1", unit: str = "signal",
           reference: str = "baseline", candidate: str = "candidate", offset: float = 0.0,
           control: float = 1.0, value_shift: float = 0.0, protocol: int = 2) -> dict:
    measurements = []
    timestamp = "2026-11-01T10:00:00Z"
    for index, value in enumerate([control, control + 0.02], start=1):
        measurements.append({"id": f"{run_id}-control-{index}", "sample_id": f"ctrl-{index}",
                             "cohort": "controls", "replicate": index, "value": value,
                             "unit": unit, "measured_at": timestamp, "role": "control"})
    for cohort, values in ((reference, [2.0, 2.2, 1.8]),
                           (candidate, [3.0 + value_shift, 3.2 + value_shift, 2.8 + value_shift])):
        for index, value in enumerate(values, start=1):
            measurements.append({"id": f"{run_id}-{cohort}-{index}", "sample_id": f"{cohort}-{index}",
                                 "cohort": cohort, "replicate": index,
                                 "value": value,
                                 "unit": unit, "measured_at": timestamp, "role": "sample"})
    if protocol == 1:
        for row in measurements:
            row["reading"] = row.pop("value")
    return {"study_id": study_id, "run_id": run_id, "protocol_version": protocol,
            "instrument_id": "instrument-demo", "unit": unit,
            "control_range": {"min": 0.8, "max": 1.3}, "min_replicates": 2,
            "reference_cohort": reference,
            "calibration": {"id": f"cal-{run_id}", "offset": offset,
                            "valid_from": "2026-11-01T00:00:00Z",
                            "valid_until": "2026-11-02T00:00:00Z", "max_abs_offset": 0.2},
            "measurements": measurements}


class Sandbox:
    def __enter__(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.database = self.root / "evidence.sqlite3"
        return self

    def write(self, name: str, payload: dict) -> Path:
        path = self.root / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def __exit__(self, exc_type, exc, traceback):
        self.temp.cleanup()
        return False
