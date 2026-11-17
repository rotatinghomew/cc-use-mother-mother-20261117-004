from __future__ import annotations

from collections import Counter
from typing import Any


def quality_summary(run_records: list[dict[str, Any]]) -> dict[str, Any]:
    accepted = 0
    rejected = 0
    diagnostic_counts: Counter[str] = Counter()
    instrument_counts: Counter[str] = Counter()
    protocol_counts: Counter[int] = Counter()
    for record in run_records:
        accepted += int(bool(record["accepted"]))
        rejected += int(not record["accepted"])
        instrument_counts[record["instrument_id"]] += 1
        protocol_counts[record["protocol_version"]] += 1
        for diagnostic in record.get("diagnostics", []):
            diagnostic_counts[diagnostic["code"]] += 1
    total = accepted + rejected
    return {"run_count": total, "accepted_count": accepted, "rejected_count": rejected,
            "acceptance_rate": accepted / total if total else None,
            "diagnostic_counts": dict(sorted(diagnostic_counts.items())),
            "runs_by_instrument": dict(sorted(instrument_counts.items())),
            "runs_by_protocol": {str(key): value for key, value in sorted(protocol_counts.items())}}
