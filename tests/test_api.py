import base64
import json

import pytest

from streamforge import api
from streamforge.service import IngestionService
from streamforge.stores import MemoryDedupStore, MemoryMetricsStore, MemoryObjectStore


@pytest.fixture
def service(now):
    return IngestionService(MemoryObjectStore(), MemoryDedupStore(), MemoryMetricsStore(), clock=lambda: now)


@pytest.fixture
def call(service, monkeypatch):
    monkeypatch.setattr(api, "_service", service)

    def _call(method, path, body=None, raw=None, b64=False):
        payload = raw if raw is not None else (json.dumps(body) if body is not None else None)
        if b64 and payload is not None:
            payload = base64.b64encode(payload.encode()).decode()
        event = {"httpMethod": method, "path": path, "body": payload, "isBase64Encoded": b64,
                 "requestContext": {"requestId": "rid-1"}}
        resp = api.handler(event, None)
        assert resp["headers"]["Content-Type"] == "application/json"
        return resp["statusCode"], json.loads(resp["body"])

    return _call


def test_post_valid_event_201(call, valid_event):
    status, body = call("POST", "/events", valid_event)
    assert status == 201
    assert body == {"index": 0, "status": "accepted", "event_id": "evt-0001", "request_id": "rid-1"}


def test_duplicate_is_200_not_error(call, valid_event):
    call("POST", "/events", valid_event)
    status, body = call("POST", "/events", valid_event)
    assert (status, body["status"]) == (200, "duplicate")


def test_missing_fields_422_with_details(call, valid_event):
    del valid_event["source"]
    status, body = call("POST", "/events", valid_event)
    assert status == 422 and body["status"] == "rejected"
    assert {"field": "source", "code": "missing", "message": "source is required"} in body["errors"]


def test_invalid_timestamp_422(call, valid_event):
    valid_event["event_timestamp"] = "not-a-date"
    assert call("POST", "/events", valid_event)[0] == 422


def test_malformed_json_400(call):
    status, body = call("POST", "/events", raw="{oops")
    assert status == 400 and body["error"]["code"] == "malformed_json"


def test_empty_body_400(call):
    assert call("POST", "/events")[0] == 400


def test_non_object_body_422(call):
    status, body = call("POST", "/events", ["a"])
    assert status == 422 and body["errors"][0]["code"] == "invalid_type"


def test_body_too_large_413(call):
    status, body = call("POST", "/events", raw=json.dumps({"x": "y" * 300_000}))
    assert status == 413 and body["error"]["code"] == "payload_too_large"


def test_base64_body(call, valid_event):
    assert call("POST", "/events", valid_event, b64=True)[0] == 201


def test_batch_mixed(call, valid_event):
    bad = dict(valid_event, event_id="bad", payload="nope")
    ok2 = dict(valid_event, event_id="evt-2")
    status, body = call("POST", "/events/batch", {"events": [valid_event, bad, ok2, valid_event]})
    assert status == 200
    assert body["summary"] == {"accepted": 2, "duplicate": 1, "rejected": 1, "failed": 0}
    assert [r["status"] for r in body["results"]] == ["accepted", "rejected", "accepted", "duplicate"]


@pytest.mark.parametrize("body", [{"events": []}, {"events": "x"}, [], {"nope": 1}])
def test_batch_shape_errors_400(call, body):
    assert call("POST", "/events/batch", body)[0] == 400


def test_batch_size_limit(call, valid_event):
    assert call("POST", "/events/batch", {"events": [valid_event] * 101})[0] == 400


def test_metrics_endpoint_reflects_activity(call, valid_event):
    assert call("GET", "/metrics")[1]["total_received"] == 0
    call("POST", "/events", valid_event)
    call("POST", "/events", valid_event)
    call("POST", "/events", dict(valid_event, event_id="x", event_type="bad"))
    status, m = call("GET", "/metrics")
    assert status == 200
    assert (m["total_received"], m["valid"], m["invalid"], m["duplicate"]) == (3, 1, 1, 1)
    assert m["last_success_at"] == "2025-06-15T12:00:00Z"


def test_health_routing_and_errors(call):
    assert call("GET", "/health") == (200, {"status": "ok"})
    assert call("GET", "/nothing")[0] == 404
    status, body = call("PUT", "/events")
    assert status == 405 and body["request_id"] == "rid-1"


def test_storage_failure_returns_503_and_retry_succeeds(service, call, valid_event, monkeypatch):
    original = service.objects.put
    state = {"fail": True}

    def flaky(key, body):
        if state["fail"] and key.startswith("processed/"):
            raise OSError("down")
        original(key, body)

    monkeypatch.setattr(service.objects, "put", flaky)
    status, body = call("POST", "/events", valid_event)
    assert status == 503 and body["status"] == "failed"
    state["fail"] = False
    assert call("POST", "/events", valid_event)[0] == 201


def test_unhandled_exception_returns_500_without_details(call, service, monkeypatch):
    def boom():
        raise RuntimeError("secret internals")

    monkeypatch.setattr(service, "metrics_summary", boom)
    status, body = call("GET", "/metrics")
    assert status == 500 and "secret" not in json.dumps(body)
