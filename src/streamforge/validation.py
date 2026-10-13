"""Pure event validation: no AWS or I/O dependencies."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

SUPPORTED_SCHEMA_VERSIONS = frozenset({"1.0"})
SUPPORTED_EVENT_TYPES = frozenset(
    {"page_view", "click", "purchase", "sensor_reading", "user_signup", "model_inference"}
)
REQUIRED_FIELDS = ("event_id", "event_type", "event_timestamp", "source", "entity_id", "payload")
MAX_ID_LENGTH = 128
MAX_PAYLOAD_BYTES = 32 * 1024
MAX_FUTURE_SKEW = timedelta(minutes=5)
MAX_AGE = timedelta(days=365)


@dataclass(frozen=True)
class ValidationError:
    field: str
    code: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"field": self.field, "code": self.code, "message": self.message}


@dataclass
class ValidationResult:
    errors: list[ValidationError] = field(default_factory=list)
    timestamp: datetime | None = None

    @property
    def ok(self) -> bool:
        return not self.errors


def parse_timestamp(value: Any) -> datetime | None:
    """Parse an ISO-8601 string with an explicit UTC offset; return UTC or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _check_id(name: str, value: Any, errors: list[ValidationError]) -> None:
    if not isinstance(value, str) or not value.strip():
        errors.append(ValidationError(name, "invalid_type", f"{name} must be a non-empty string"))
    elif len(value) > MAX_ID_LENGTH:
        errors.append(ValidationError(name, "too_long", f"{name} exceeds {MAX_ID_LENGTH} chars"))


def validate_event(event: Any, now: datetime | None = None) -> ValidationResult:
    """Validate one event against the v1.0 contract. Never raises on bad input."""
    now = now or datetime.now(UTC)
    result = ValidationResult()
    errors = result.errors
    if not isinstance(event, dict):
        errors.append(ValidationError("$", "invalid_type", "event must be a JSON object"))
        return result

    for name in REQUIRED_FIELDS:
        if name not in event or event[name] is None:
            errors.append(ValidationError(name, "missing", f"{name} is required"))

    version = event.get("schema_version", "1.0")
    if version not in SUPPORTED_SCHEMA_VERSIONS:
        errors.append(
            ValidationError(
                "schema_version",
                "unsupported_version",
                f"supported versions: {sorted(SUPPORTED_SCHEMA_VERSIONS)}",
            )
        )

    for name in ("event_id", "source", "entity_id"):
        if event.get(name) is not None:
            _check_id(name, event[name], errors)

    etype = event.get("event_type")
    if etype is not None and etype not in SUPPORTED_EVENT_TYPES:
        errors.append(
            ValidationError(
                "event_type",
                "unsupported_event_type",
                f"must be one of {sorted(SUPPORTED_EVENT_TYPES)}",
            )
        )

    if event.get("event_timestamp") is not None:
        ts = parse_timestamp(event["event_timestamp"])
        if ts is None:
            errors.append(
                ValidationError(
                    "event_timestamp",
                    "invalid_timestamp",
                    "must be ISO-8601 with timezone offset, e.g. 2025-01-31T12:00:00Z",
                )
            )
        elif ts > now + MAX_FUTURE_SKEW:
            errors.append(ValidationError("event_timestamp", "in_future", "timestamp is in the future"))
        elif ts < now - MAX_AGE:
            errors.append(ValidationError("event_timestamp", "too_old", "timestamp older than 365 days"))
        else:
            result.timestamp = ts

    payload = event.get("payload")
    if payload is not None:
        if not isinstance(payload, dict):
            errors.append(ValidationError("payload", "invalid_type", "payload must be a JSON object"))
        elif len(json.dumps(payload, default=str).encode()) > MAX_PAYLOAD_BYTES:
            errors.append(
                ValidationError("payload", "too_large", f"payload exceeds {MAX_PAYLOAD_BYTES} bytes")
            )
    return result


def safe_diagnostics(event: Any) -> dict[str, Any]:
    """Describe an event without leaking payload values: shape, size and a content hash."""
    try:
        body = json.dumps(event, sort_keys=True, default=str).encode()
    except (TypeError, ValueError):
        body = repr(type(event)).encode()
    info: dict[str, Any] = {
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
        "json_type": type(event).__name__,
    }
    if isinstance(event, dict):
        info["top_level_keys"] = sorted(str(k)[:64] for k in event)[:50]
        for name in ("event_id", "event_type", "source"):
            value = event.get(name)
            if isinstance(value, str):
                info[name] = value[:MAX_ID_LENGTH]
    return info
