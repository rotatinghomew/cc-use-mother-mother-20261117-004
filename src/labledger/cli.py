from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from labledger.errors import LedgerError
from labledger.service import EvidenceService
from labledger.exports import export_csv, export_json, verify_packet_file
from labledger.storage.backup import create_backup


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="labledger", description="Offline laboratory evidence review")
    result.add_argument("--database", default="evidence.sqlite3")
    commands = result.add_subparsers(dest="command", required=True)
    importing = commands.add_parser("import", help="validate and record a run bundle")
    importing.add_argument("bundle", type=Path)
    batch = commands.add_parser("batch", help="atomically import several runs for one study")
    batch.add_argument("bundles", nargs="+", type=Path)
    manifest = commands.add_parser("manifest", help="import bundles listed with verified SHA-256 digests")
    manifest.add_argument("manifest", type=Path)
    preview_batch = commands.add_parser("preview-batch", help="preflight a batch without storing it")
    preview_batch.add_argument("bundles", nargs="+", type=Path)
    report = commands.add_parser("report", help="compare accepted runs")
    report.add_argument("study_id")
    report.add_argument("--tolerance", type=float, default=0.15)
    findings = commands.add_parser("findings", help="show a run's quality findings")
    findings.add_argument("study_id")
    findings.add_argument("run_id")
    audit = commands.add_parser("audit", help="show append-only import decisions")
    audit.add_argument("study_id")
    diagnostics = commands.add_parser("diagnostics", help="show review warnings for a run")
    diagnostics.add_argument("study_id")
    diagnostics.add_argument("run_id")
    provenance = commands.add_parser("provenance", help="show source and protocol lineage")
    provenance.add_argument("study_id")
    provenance.add_argument("run_id", nargs="?")
    exporting = commands.add_parser("export", help="write a traceable study evidence file")
    exporting.add_argument("study_id")
    exporting.add_argument("destination", type=Path)
    exporting.add_argument("--format", choices=("json", "csv"), default="json")
    backup = commands.add_parser("backup", help="create and verify a consistent SQLite snapshot")
    backup.add_argument("destination", type=Path)
    replay = commands.add_parser("replay", help="re-run quality rules against stored raw evidence")
    replay.add_argument("study_id")
    replay.add_argument("run_id")
    preview = commands.add_parser("preview", help="check a bundle without storing it")
    preview.add_argument("bundle", type=Path)
    verify = commands.add_parser("verify-export", help="verify an exported evidence checksum")
    verify.add_argument("packet", type=Path)
    commands.add_parser("studies", help="list studies and run counts")
    audit_check = commands.add_parser("verify-audit", help="check recorded decisions against the audit trail")
    audit_check.add_argument("study_id")
    commands.add_parser("verify-db", help="check SQLite schema, foreign keys, and page integrity")
    return result


def run(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        service = EvidenceService(args.database)
        if args.command == "backup":
            result = {"backup": str(create_backup(args.database, args.destination))}
        elif args.command == "export":
            path = (export_json(service, args.study_id, args.destination) if args.format == "json"
                    else export_csv(service, args.study_id, args.destination))
            result = {"export": str(path), "format": args.format}
        elif args.command == "replay":
            result = service.replay(args.study_id, args.run_id)
        elif args.command == "verify-export":
            result = verify_packet_file(args.packet)
        elif args.command == "studies":
            result = service.studies()
        elif args.command == "verify-audit":
            result = service.verify_audit(args.study_id)
        elif args.command == "verify-db":
            result = service.database_status()
        elif args.command == "preview":
            result = service.preview_run(args.bundle)
        elif args.command == "import":
            result = service.import_run(args.bundle)
        elif args.command == "batch":
            result = service.import_batch(args.bundles)
        elif args.command == "manifest":
            result = service.import_manifest(args.manifest)
        elif args.command == "preview-batch":
            result = service.preview_batch(args.bundles)
        elif args.command == "report":
            result = service.report(args.study_id, args.tolerance)
        elif args.command == "findings":
            result = service.findings(args.study_id, args.run_id)
        elif args.command == "diagnostics":
            result = service.diagnostics(args.study_id, args.run_id)
        elif args.command == "provenance":
            result = (service.provenance(args.study_id, args.run_id) if args.run_id
                      else service.history(args.study_id))
        else:
            result = service.audit(args.study_id)
    except LedgerError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0
