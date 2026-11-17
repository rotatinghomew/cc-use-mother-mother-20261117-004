from __future__ import annotations

import json
import tempfile
from pathlib import Path

from labledger.service import EvidenceService


def run() -> int:
    root = Path(__file__).resolve().parents[2]
    first = root / "fixtures" / "run-a.json"
    second = root / "fixtures" / "run-b.json"
    with tempfile.TemporaryDirectory(prefix="labledger-demo-") as folder:
        service = EvidenceService(Path(folder) / "demo.sqlite3")
        result = service.import_batch([first, second])
        report = service.report("demo-study", tolerance=0.15)
        if len(result["accepted_runs"]) != 2 or not report["has_comparison"]:
            raise RuntimeError("demo data did not produce a qualified cross-run comparison")
        print(json.dumps({"import": result, "report": report}, ensure_ascii=False,
                         sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
