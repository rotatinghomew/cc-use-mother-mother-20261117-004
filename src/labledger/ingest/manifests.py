from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from labledger.errors import ContractError


def read_manifest(path: str | Path) -> list[Path]:
    manifest_path = Path(path)
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot read bundle manifest: {exc}") from exc
    if not isinstance(payload, dict) or set(payload) != {"bundles"}:
        raise ContractError("manifest must be an object containing only bundles")
    entries = payload["bundles"]
    if not isinstance(entries, list) or not entries:
        raise ContractError("manifest bundles must be a non-empty array")
    if len(entries) > 100:
        raise ContractError("manifest cannot contain more than 100 bundles")
    root = manifest_path.resolve().parent
    result = []
    resolved_seen = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict) or set(entry) != {"path", "sha256"}:
            raise ContractError(f"manifest bundles[{index}] must contain path and sha256")
        relative = entry["path"]
        digest = entry["sha256"]
        if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
            raise ContractError(f"manifest bundles[{index}].path must be relative")
        if not isinstance(digest, str) or len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise ContractError(f"manifest bundles[{index}].sha256 must be lowercase SHA-256 hex")
        candidate = manifest_path.parent / relative
        if any(parent.is_symlink() for parent in (candidate, *candidate.parents) if parent.exists()):
            raise ContractError(f"manifest bundles[{index}] cannot reference symlinks")
        resolved = candidate.resolve()
        if not resolved.is_relative_to(root):
            raise ContractError(f"manifest bundles[{index}] escapes its manifest directory")
        if not resolved.is_file():
            raise ContractError(f"manifest bundles[{index}] is not a regular file")
        if resolved in resolved_seen:
            raise ContractError(f"manifest contains a duplicate path: {relative}")
        resolved_seen.add(resolved)
        actual = hashlib.sha256(resolved.read_bytes()).hexdigest()
        if actual != digest:
            raise ContractError(f"manifest digest mismatch for {relative}")
        result.append(resolved)
    return result


def manifest_template(paths: list[str | Path], *, root: str | Path) -> dict[str, Any]:
    base = Path(root).resolve()
    entries = []
    for item in paths:
        path = Path(item).resolve()
        if not path.is_relative_to(base) or not path.is_file():
            raise ContractError("all manifest inputs must be files inside the chosen root")
        entries.append({"path": path.relative_to(base).as_posix(),
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    return {"bundles": sorted(entries, key=lambda item: item["path"])}
