"""Pure transformations and storage-key layout (no AWS calls)."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

PIPELINE_VERSION = "1.0.0"


def event_key_hash(source: str, event_id: str) -> str:
    """Stable identity for an event: event_id is unique per source, not globally."""
    return hashlib.sha256(f"{source}\x1f{event_id}".encode()).hexdigest()[:32]


def partition(prefix: str, ts: datetime) -> str:
    return f"{prefix}/year={ts:%Y}/month={ts:%m}/day={ts:%d}"


def raw_key(source: str, event_id: str, event_ts: datetime) -> str:
    return f"{partition('raw', event_ts)}/source={source}/{event_key_hash(source, event_id)}.json"


def processed_key(source: str, event_id: str, event_ts: datetime) -> str:
    return f"{partition('processed', event_ts)}/source={source}/{event_key_hash(source, event_id)}.json"


def rejected_key(received_at: datetime, request_id: str, index: int) -> str:
    return f"{partition('rejected', received_at)}/{request_id}-{index}.json"


def to_processed(event: dict[str, Any], event_ts: datetime, received_at: datetime, request_id: str) -> dict:
    """Normalise a validated event into the processed-record schema (see DATA_DICTIONARY.md)."""
    payload = event["payload"]
    return {
        "event_id": event["event_id"],
        "source": event["source"],
        "entity_id": event["entity_id"],
        "event_type": event["event_type"],
        "event_timestamp": event_ts.isoformat().replace("+00:00", "Z"),
        "event_date": event_ts.strftime("%Y-%m-%d"),
        "schema_version": event.get("schema_version", "1.0"),
        "payload": payload,
        "payload_sha256": hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "ingested_at": received_at.isoformat().replace("+00:00", "Z"),
        "request_id": request_id,
        "pipeline_version": PIPELINE_VERSION,
    }


def to_raw(event: dict[str, Any], received_at: datetime, request_id: str) -> dict:
    return {
        "received_at": received_at.isoformat().replace("+00:00", "Z"),
        "request_id": request_id,
        "event": event,
    }
