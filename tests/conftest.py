from datetime import UTC, datetime

import pytest

NOW = datetime(2025, 6, 15, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def now() -> datetime:
    return NOW


@pytest.fixture
def valid_event() -> dict:
    return {
        "event_id": "evt-0001",
        "event_type": "page_view",
        "event_timestamp": "2025-06-15T11:59:00Z",
        "source": "web-app",
        "entity_id": "user-42",
        "schema_version": "1.0",
        "payload": {"url": "/home", "secret_note": "do-not-log-me"},
    }
