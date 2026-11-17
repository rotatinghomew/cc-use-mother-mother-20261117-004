from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from labledger.errors import ContractError
from labledger.service import EvidenceService


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def evidence_packet(service: EvidenceService, study_id: str) -> dict[str, Any]:
    report = service.report(study_id)
    rows = service.export_rows(study_id)
    audit = service.audit(study_id)
    body = {"format": "labledger-evidence-v1", "study_id": study_id,
            "report": report, "audit": audit, "measurements": rows}
    digest = hashlib.sha256(_canonical_json(body)).hexdigest()
    return {**body, "packet_sha256": digest}


def verify_packet(packet: dict[str, Any]) -> bool:
    if not isinstance(packet, dict) or packet.get("format") != "labledger-evidence-v1":
        return False
    expected = packet.get("packet_sha256")
    if not isinstance(expected, str) or len(expected) != 64:
        return False
    body = {key: value for key, value in packet.items() if key != "packet_sha256"}
    return hashlib.sha256(_canonical_json(body)).hexdigest() == expected


def verify_packet_file(path: str | Path) -> dict[str, Any]:
    try:
        packet = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot read evidence packet: {exc}") from exc
    if not verify_packet(packet):
        raise ContractError("evidence packet checksum is invalid")
    return {"valid": True, "study_id": packet["study_id"], "packet_sha256": packet["packet_sha256"],
            "measurement_count": len(packet.get("measurements", []))}


def csv_text(rows: list[dict[str, Any]]) -> str:
    columns = ["run_id", "source_digest", "accepted", "instrument_id", "calibration_id",
               "measurement_id", "sample_id", "cohort", "replicate", "raw_value",
               "corrected_value", "unit", "measured_at", "role"]
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=columns, extrasaction="raise", lineterminator="\n")
    writer.writeheader()
    for row in rows:
        missing = set(columns) - row.keys()
        if missing:
            raise ContractError(f"export row missing columns: {', '.join(sorted(missing))}")
        writer.writerow(row)
    return output.getvalue()


def _atomic_write(destination: str | Path, content: bytes) -> Path:
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(file_descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return path


def export_json(service: EvidenceService, study_id: str, destination: str | Path) -> Path:
    packet = evidence_packet(service, study_id)
    content = json.dumps(packet, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"
    return _atomic_write(destination, content)


def export_csv(service: EvidenceService, study_id: str, destination: str | Path) -> Path:
    rows = service.export_rows(study_id)
    return _atomic_write(destination, csv_text(rows).encode("utf-8"))
