import pytest

from streamforge.validation import parse_timestamp, safe_diagnostics, validate_event


def codes(result):
    return {(e.field, e.code) for e in result.errors}


def test_valid_event(valid_event, now):
    r = validate_event(valid_event, now)
    assert r.ok and r.timestamp.isoformat() == "2025-06-15T11:59:00+00:00"


def test_schema_version_defaults(valid_event, now):
    del valid_event["schema_version"]
    assert validate_event(valid_event, now).ok


@pytest.mark.parametrize(
    "name", ["event_id", "event_type", "event_timestamp", "source", "entity_id", "payload"]
)
def test_missing_required(valid_event, now, name):
    del valid_event[name]
    assert (name, "missing") in codes(validate_event(valid_event, now))


@pytest.mark.parametrize(
    "ts", ["yesterday", "2025-06-15T11:59:00", 12345, "2025-13-45T00:00:00Z", ""]
)
def test_invalid_timestamps(valid_event, now, ts):
    valid_event["event_timestamp"] = ts
    assert ("event_timestamp", "invalid_timestamp") in codes(validate_event(valid_event, now))


def test_future_and_old_timestamps(valid_event, now):
    valid_event["event_timestamp"] = "2025-06-16T00:00:00Z"
    assert ("event_timestamp", "in_future") in codes(validate_event(valid_event, now))
    valid_event["event_timestamp"] = "2023-01-01T00:00:00Z"
    assert ("event_timestamp", "too_old") in codes(validate_event(valid_event, now))


def test_offset_timestamp_normalised_to_utc():
    assert parse_timestamp("2025-06-15T17:30:00+05:30").isoformat() == "2025-06-15T12:00:00+00:00"


def test_unsupported_event_type(valid_event, now):
    valid_event["event_type"] = "nope"
    assert ("event_type", "unsupported_event_type") in codes(validate_event(valid_event, now))


@pytest.mark.parametrize("payload", ["string", [1, 2], 5])
def test_malformed_payload(valid_event, now, payload):
    valid_event["payload"] = payload
    assert ("payload", "invalid_type") in codes(validate_event(valid_event, now))


def test_payload_too_large(valid_event, now):
    valid_event["payload"] = {"blob": "x" * 40_000}
    assert ("payload", "too_large") in codes(validate_event(valid_event, now))


def test_unsupported_schema_version(valid_event, now):
    valid_event["schema_version"] = "9.9"
    assert ("schema_version", "unsupported_version") in codes(validate_event(valid_event, now))


@pytest.mark.parametrize("bad", [None, [], "x", 3])
def test_non_object_event(bad, now):
    assert codes(validate_event(bad, now)) == {("$", "invalid_type")}


def test_non_string_id(valid_event, now):
    valid_event["event_id"] = 123
    assert ("event_id", "invalid_type") in codes(validate_event(valid_event, now))


def test_diagnostics_exclude_payload_values(valid_event):
    d = safe_diagnostics(valid_event)
    assert "do-not-log-me" not in str(d)
    assert d["event_id"] == "evt-0001" and len(d["sha256"]) == 64
    assert "payload" in d["top_level_keys"]
