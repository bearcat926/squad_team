"""Canonicalization utilities for event hash chain computation.

Canonicalization Spec Version: 1.0
Rules:
  - JSON payloads are serialized with json.dumps(ensure_ascii=False, sort_keys=True, separators=(',', ':'))
  - Text values undergo NFC Unicode normalization
  - Path separators are normalized to forward slash /
  - No trailing whitespace on lines
  - LF line endings only
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from typing import Any

CANONICALIZATION_SPEC_VERSION = "1.0"

GENESIS_HASH = "sha256-e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def canonical_json_bytes(payload: dict[str, Any]) -> bytes:
    """Serialize a payload to canonical JSON bytes.

    Canonical form: sorted keys, no extra whitespace, ensure_ascii=False, compact separators.
    """
    normalized = _normalize_payload(payload)
    return json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    """Compute SHA-256 hex digest with 'sha256-' prefix."""
    return "sha256-" + hashlib.sha256(data).hexdigest()


def normalize_text(value: str) -> str:
    """NFC normalize text and strip trailing whitespace per line."""
    value = unicodedata.normalize("NFC", value)
    lines = value.split("\n")
    return "\n".join(line.rstrip() for line in lines)


def normalize_path(value: str) -> str:
    """Normalize path separators to forward slash."""
    return value.replace("\\", "/")


def compute_event_hash(previous_event_hash: str, payload: dict[str, Any]) -> tuple[str, str]:
    """Compute eventPayloadHash and eventHash for a single event.

    Returns (eventPayloadHash, eventHash).
    """
    payload_bytes = canonical_json_bytes(payload)
    payload_hash = sha256_hex(payload_bytes)
    chain_input = (previous_event_hash + payload_hash).encode("utf-8")
    event_hash = sha256_hex(chain_input)
    return payload_hash, event_hash


def verify_event_hash(
    previous_event_hash: str,
    payload: dict[str, Any],
    expected_payload_hash: str,
    expected_event_hash: str,
) -> bool:
    """Verify that an event's hashes match recomputation."""
    payload_hash, event_hash = compute_event_hash(previous_event_hash, payload)
    return payload_hash == expected_payload_hash and event_hash == expected_event_hash


def _normalize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Recursively normalize a payload dict."""
    result = {}
    for key, value in payload.items():
        nkey = normalize_text(key) if isinstance(key, str) else key
        result[nkey] = _normalize_value(value)
    return result


def _normalize_value(value: Any) -> Any:
    if isinstance(value, str):
        return normalize_text(value)
    if isinstance(value, dict):
        return _normalize_payload(value)
    if isinstance(value, list):
        return [_normalize_value(item) for item in value]
    return value
