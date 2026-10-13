"""API Gateway (REST, proxy integration) handler. Thin: parsing, routing, HTTP mapping."""
from __future__ import annotations

import base64
import json
import logging
import os
import uuid
from typing import Any

from .service import ACCEPTED, DUPLICATE, FAILED, REJECTED, IngestionService, log_event

MAX_BODY_BYTES = 256 * 1024
MAX_BATCH_SIZE = 100

logging.getLogger("streamforge").setLevel(logging.INFO)
_service: IngestionService | None = None


def get_service() -> IngestionService:
    global _service
    if _service is None:
        from .aws_stores import DynamoDedupStore, DynamoMetricsStore, S3ObjectStore

        _service = IngestionService(
            S3ObjectStore(os.environ["DATA_BUCKET"]),
            DynamoDedupStore(os.environ["STATE_TABLE"]),
            DynamoMetricsStore(os.environ["STATE_TABLE"]),
        )
    return _service


def _response(status: int, body: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json", "Cache-Control": "no-store"},
        "body": json.dumps(body),
    }


def _error(status: int, code: str, message: str, request_id: str) -> dict[str, Any]:
    return _response(status, {"error": {"code": code, "message": message}, "request_id": request_id})


def _parse_json(event: dict[str, Any]) -> tuple[Any, str | None]:
    raw = event.get("body") or ""
    if event.get("isBase64Encoded"):
        try:
            raw = base64.b64decode(raw).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return None, "body is not valid base64/UTF-8"
    if len(raw.encode("utf-8")) > MAX_BODY_BYTES:
        return None, "too_large"
    try:
        return json.loads(raw), None
    except json.JSONDecodeError:
        return None, "body is not valid JSON"


def _single_status(outcome_status: str) -> int:
    return {ACCEPTED: 201, DUPLICATE: 200, REJECTED: 422, FAILED: 503}[outcome_status]


def handle_request(
    method: str, path: str, event: dict[str, Any], service: IngestionService, request_id: str
) -> dict[str, Any]:
    path = path.rstrip("/") or "/"
    if method == "GET" and path == "/health":
        return _response(200, {"status": "ok"})
    if method == "GET" and path == "/metrics":
        return _response(200, service.metrics_summary())
    if method == "POST" and path in ("/events", "/events/batch"):
        data, err = _parse_json(event)
        if err == "too_large":
            return _error(413, "payload_too_large", f"body exceeds {MAX_BODY_BYTES} bytes", request_id)
        if err:
            return _error(400, "malformed_json", err, request_id)
        if path == "/events":
            outcomes = service.ingest([data], request_id)
            o = outcomes[0]
            return _response(_single_status(o.status), {**o.to_dict(), "request_id": request_id})
        if not isinstance(data, dict) or not isinstance(data.get("events"), list):
            return _error(400, "invalid_batch", 'body must be {"events": [...]}', request_id)
        if not 1 <= len(data["events"]) <= MAX_BATCH_SIZE:
            return _error(400, "invalid_batch", f"events must contain 1..{MAX_BATCH_SIZE} items", request_id)
        outcomes = service.ingest(data["events"], request_id)
        statuses = (ACCEPTED, DUPLICATE, REJECTED, FAILED)
        summary = {s: sum(1 for o in outcomes if o.status == s) for s in statuses}
        body = {"summary": summary, "results": [o.to_dict() for o in outcomes], "request_id": request_id}
        # Retryable failures => 503. Replaying the whole batch is safe because of idempotency.
        return _response(503 if summary[FAILED] else 200, body)
    if path in ("/events", "/events/batch", "/metrics", "/health"):
        return _error(405, "method_not_allowed", f"{method} not allowed on {path}", request_id)
    return _error(404, "not_found", f"no route for {method} {path}", request_id)


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    request_id = (event.get("requestContext") or {}).get("requestId") or str(uuid.uuid4())
    method = str(event.get("httpMethod", "")).upper()
    path = str(event.get("path", ""))
    try:
        return handle_request(method, path, event, get_service(), request_id)
    except Exception as exc:
        log_event(logging.ERROR, "unhandled_error", request_id=request_id, error_type=type(exc).__name__)
        return _error(500, "internal_error", "unexpected error; see request_id", request_id)
