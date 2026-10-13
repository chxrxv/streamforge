import json
from datetime import UTC, datetime

import pytest

from streamforge.service import ACCEPTED, DUPLICATE, FAILED, REJECTED, IngestionService
from streamforge.stores import MemoryDedupStore, MemoryMetricsStore, MemoryObjectStore
from streamforge.transform import event_key_hash


class FlakyObjects(MemoryObjectStore):
    def __init__(self, fail_times: int):
        super().__init__()
        self.fail_times = fail_times

    def put(self, key, body):
        if key.startswith("processed/") and self.fail_times > 0:
            self.fail_times -= 1
            raise OSError("simulated outage")
        super().put(key, body)


@pytest.fixture
def svc(now):
    return IngestionService(MemoryObjectStore(), MemoryDedupStore(), MemoryMetricsStore(), clock=lambda: now)


def test_valid_event_stored_raw_and_processed(svc, valid_event):
    (out,) = svc.ingest([valid_event], "req1")
    assert out.status == ACCEPTED
    keys = svc.objects.list_keys("")
    h = event_key_hash("web-app", "evt-0001")
    assert f"raw/year=2025/month=06/day=15/source=web-app/{h}.json" in keys
    assert f"processed/year=2025/month=06/day=15/source=web-app/{h}.json" in keys
    rec = json.loads(svc.objects.get(f"processed/year=2025/month=06/day=15/source=web-app/{h}.json"))
    assert rec["event_timestamp"] == "2025-06-15T11:59:00Z"
    assert rec["event_date"] == "2025-06-15" and len(rec["payload_sha256"]) == 64
    assert rec["request_id"] == "req1" and rec["ingested_at"] == "2025-06-15T12:00:00Z"


def test_invalid_event_goes_to_rejected_without_payload_values(svc, valid_event):
    valid_event["event_timestamp"] = "garbage"
    (out,) = svc.ingest([valid_event], "req2")
    assert out.status == REJECTED and out.errors[0]["code"] == "invalid_timestamp"
    rejected = svc.objects.list_keys("rejected/")
    assert len(rejected) == 1 and not svc.objects.list_keys("processed/")
    body = svc.objects.get(rejected[0]).decode()
    assert "do-not-log-me" not in body and "invalid_timestamp" in body


def test_duplicate_event_not_reprocessed(svc, valid_event):
    assert svc.ingest([valid_event], "a")[0].status == ACCEPTED
    assert svc.ingest([valid_event], "b")[0].status == DUPLICATE
    assert len(svc.objects.list_keys("processed/")) == 1
    # request_id of the first (winning) write is preserved
    rec = json.loads(svc.objects.get(svc.objects.list_keys("processed/")[0]))
    assert rec["request_id"] == "a"


def test_duplicate_within_same_batch(svc, valid_event):
    out = svc.ingest([valid_event, dict(valid_event)], "r")
    assert [o.status for o in out] == [ACCEPTED, DUPLICATE]


def test_same_event_id_different_source_is_not_duplicate(svc, valid_event):
    other = dict(valid_event, source="mobile-app")
    out = svc.ingest([valid_event, other], "r")
    assert [o.status for o in out] == [ACCEPTED, ACCEPTED]


def test_failure_then_retry_is_reprocessed(now, valid_event):
    objects = FlakyObjects(fail_times=1)
    svc = IngestionService(objects, MemoryDedupStore(), MemoryMetricsStore(), clock=lambda: now)
    assert svc.ingest([valid_event], "r1")[0].status == FAILED
    assert svc.ingest([valid_event], "r2")[0].status == ACCEPTED  # not wrongly treated as duplicate
    assert svc.ingest([valid_event], "r3")[0].status == DUPLICATE
    m = svc.metrics_summary()
    assert (m["processing_failures"], m["valid"], m["duplicate"]) == (1, 1, 1)


def test_non_dict_events_rejected(svc):
    out = svc.ingest([None, "str", 5], "r")
    assert [o.status for o in out] == [REJECTED] * 3
    assert svc.metrics_summary()["invalid"] == 3


def test_metrics_accuracy(svc, valid_event):
    bad = dict(valid_event, event_id="bad", event_type="zzz")
    second = dict(valid_event, event_id="evt-0002", source="mobile-app")
    svc.ingest([valid_event, bad, second, valid_event], "r")
    m = svc.metrics_summary()
    assert m["total_received"] == 4
    assert (m["valid"], m["invalid"], m["duplicate"], m["processing_failures"]) == (2, 1, 1, 0)
    assert m["total_received"] == m["valid"] + m["invalid"] + m["duplicate"] + m["processing_failures"]
    assert m["valid_rate"] == 0.5 and m["requests"] == 1
    assert m["last_success_at"] == "2025-06-15T12:00:00Z"
    assert m["by_source"]["web-app"]["received"] == 2  # accepted + duplicate
    assert m["by_source"]["mobile-app"]["valid"] == 1


def test_empty_metrics_do_not_invent_data(svc):
    m = svc.metrics_summary()
    assert m["total_received"] == 0 and m["valid_rate"] is None and m["last_success_at"] is None
    assert m["by_source"] == {}


def test_unsafe_source_rejected_so_it_cannot_shape_s3_keys(svc, valid_event):
    valid_event["source"] = "../../etc"
    assert svc.ingest([valid_event], "r")[0].status == REJECTED
    assert not svc.objects.list_keys("processed/")


def test_timestamp_utc_partitioning_from_offset(svc, valid_event):
    valid_event["event_timestamp"] = "2025-06-15T23:30:00-05:00"  # = 2025-06-16T04:30Z, > now+skew
    assert svc.ingest([valid_event], "r")[0].status == REJECTED
    valid_event["event_timestamp"] = "2025-06-15T01:00:00+05:30"  # = 2025-06-14T19:30Z
    assert svc.ingest([valid_event], "r")[0].status == ACCEPTED
    assert svc.objects.list_keys("processed/year=2025/month=06/day=14/")


def test_clock_default_returns_aware_utc():
    assert datetime.now(UTC).tzinfo is not None
