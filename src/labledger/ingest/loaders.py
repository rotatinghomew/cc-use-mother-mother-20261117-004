from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from labledger.errors import ContractError
from labledger.ingest.contracts import RunBundle, parse_bundle


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ContractError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def decode_json(content: bytes) -> tuple[dict[str, Any], str]:
    digest = hashlib.sha256(content).hexdigest()
    try:
        text = content.decode("utf-8-sig")
        payload = json.loads(text, object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"input is not valid UTF-8 JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ContractError("bundle root must be an object")
    return payload, digest


def load_bundle(path: str | Path) -> RunBundle:
    source = Path(path)
    try:
        content = source.read_bytes()
    except OSError as exc:
        raise ContractError(f"cannot read input {source}: {exc}") from exc
    if len(content) > 8_000_000:
        raise ContractError("input exceeds the 8 MB bundle limit")
    payload, digest = decode_json(content)
    return parse_bundle(payload, digest)


def encode_canonical(bundle: RunBundle) -> str:
    from dataclasses import asdict

    return json.dumps(asdict(bundle), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
