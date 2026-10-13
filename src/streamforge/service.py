"""Ingestion orchestration: validate -> dedupe -> store raw/processed/rejected -> metrics.

Business logic only; storage backends are injected so the same code runs on S3/DynamoDB or in memory.
"""
from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .stores import Claim, DedupStore, MetricsStore, ObjectStore
from .transform import event_key_hash, processed_key, raw_key, rejected_key, to_processed, to_raw
from .validation import safe_diagnostics, validate_event

logger = logging.getLogger("streamforge")

ACCEPTED, REJECTED, DUPLICATE, FAILED = "accepted", "rejected", "duplicate", "failed"
GLOBAL_SCOPE = "global"
SOURCE_SCOPE_PREFIX = "source#"


@dataclass
class EventOutcome:
    index: int
    status: str
    event_id: str | None = None
    errors: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"index": self.index, "status": self.status, "event_id": self.event_id}
        if self.errors:
            out["errors"] = self.errors
        return out


def log_event(level: int, message: str, **fields: Any) -> None:
    """Structured JSON log line. Callers must never pass payload values."""
    logger.log(level, json.dumps({"message": message, **fields}, default=str))


class IngestionService:
    def __init__(
        self,
        objects: ObjectStore,
        dedup: DedupStore,
        metrics: MetricsStore,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.objects = objects
        self.dedup = dedup
        self.metrics = metrics
        self.clock = clock

    def ingest(self, events: list[Any], request_id: str) -> list[EventOutcome]:
        started = time.perf_counter()
        received_at = self.clock()
        outcomes: list[EventOutcome] = []
        per_source: dict[str, dict[str, int]] = {}

        for index, event in enumerate(events):
            outcome = self._ingest_one(index, event, received_at, request_id)
            outcomes.append(outcome)
            if isinstance(event, dict) and outcome.status != REJECTED:
                bucket = per_source.setdefault(str(event["source"]), {})
                bucket["received"] = bucket.get("received", 0) + 1
                bucket[outcome.status] = bucket.get(outcome.status, 0) + 1

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        statuses = (ACCEPTED, REJECTED, DUPLICATE, FAILED)
        counts = {s: sum(1 for o in outcomes if o.status == s) for s in statuses}
        counters = {
            "requests": 1,
            "received": len(events),
            "valid": counts[ACCEPTED],
            "invalid": counts[REJECTED],
            "duplicate": counts[DUPLICATE],
            "failed": counts[FAILED],
            "processing_ms_total": elapsed_ms,
        }
        try:
            last_ok = received_at.isoformat().replace("+00:00", "Z") if counts[ACCEPTED] else None
            self.metrics.record(GLOBAL_SCOPE, counters, last_ok)
            for source, c in per_source.items():
                self.metrics.record(
                    SOURCE_SCOPE_PREFIX + source,
                    {"received": c.get("received", 0), "valid": c.get(ACCEPTED, 0),
                     "duplicate": c.get(DUPLICATE, 0), "failed": c.get(FAILED, 0)},
                    last_ok if c.get(ACCEPTED) else None,
                )
        except Exception:  # metrics must never fail ingestion
            log_event(logging.ERROR, "metrics_write_failed", request_id=request_id)

        log_event(logging.INFO, "batch_processed", request_id=request_id, duration_ms=elapsed_ms, **counts)
        return outcomes

    def _ingest_one(self, index: int, event: Any, received_at: datetime, request_id: str) -> EventOutcome:
        result = validate_event(event, received_at)
        if not result.ok:
            self._reject(index, event, [e.to_dict() for e in result.errors], received_at, request_id)
            event_id = event.get("event_id") if isinstance(event, dict) else None
            return EventOutcome(index, REJECTED, event_id if isinstance(event_id, str) else None,
                                [e.to_dict() for e in result.errors])

        assert result.timestamp is not None
        source, event_id = event["source"], event["event_id"]
        dedup_key = event_key_hash(source, event_id)
        try:
            if self.dedup.claim(dedup_key) is Claim.DUPLICATE:
                return EventOutcome(index, DUPLICATE, event_id)
            self.objects.put(
                raw_key(source, event_id, result.timestamp),
                json.dumps(to_raw(event, received_at, request_id)).encode(),
            )
            self.objects.put(
                processed_key(source, event_id, result.timestamp),
                json.dumps(to_processed(event, result.timestamp, received_at, request_id)).encode(),
            )
            self.dedup.complete(dedup_key)
            return EventOutcome(index, ACCEPTED, event_id)
        except Exception as exc:
            # Claim stays "pending", so a client retry is reprocessed (keys are deterministic).
            log_event(logging.ERROR, "event_processing_failed", request_id=request_id,
                      event_id=event_id, source=source, error_type=type(exc).__name__)
            return EventOutcome(index, FAILED, event_id,
                                [{"field": "$", "code": "processing_failed", "message": "retry later"}])

    def _reject(self, index: int, event: Any, errors: list[dict[str, str]],
                received_at: datetime, request_id: str) -> None:
        record = {
            "rejected_at": received_at.isoformat().replace("+00:00", "Z"),
            "request_id": request_id,
            "index": index,
            "errors": errors,
            "diagnostics": safe_diagnostics(event),
        }
        try:
            self.objects.put(rejected_key(received_at, request_id, index), json.dumps(record).encode())
        except Exception as exc:
            log_event(logging.ERROR, "reject_write_failed", request_id=request_id,
                      error_type=type(exc).__name__)

    def metrics_summary(self) -> dict[str, Any]:
        g = self.metrics.get(GLOBAL_SCOPE)
        received = int(g.get("received", 0))
        valid, invalid = int(g.get("valid", 0)), int(g.get("invalid", 0))
        duplicate, failed = int(g.get("duplicate", 0)), int(g.get("failed", 0))
        requests = int(g.get("requests", 0))
        sources = {}
        for scope in self.metrics.list_scopes(SOURCE_SCOPE_PREFIX):
            s = self.metrics.get(scope)
            sources[scope[len(SOURCE_SCOPE_PREFIX):]] = {
                "received": int(s.get("received", 0)), "valid": int(s.get("valid", 0)),
                "duplicate": int(s.get("duplicate", 0)), "failed": int(s.get("failed", 0)),
                "last_success_at": s.get("last_success_at"),
            }
        return {
            "total_received": received,
            "valid": valid,
            "invalid": invalid,
            "duplicate": duplicate,
            "processing_failures": failed,
            "valid_rate": round(valid / received, 4) if received else None,
            "requests": requests,
            "avg_batch_processing_ms": round(int(g.get("processing_ms_total", 0)) / requests, 2)
            if requests else None,
            "last_success_at": g.get("last_success_at"),
            "by_source": sources,
        }
