import json

import boto3
import pytest
from moto import mock_aws

from streamforge.aws_stores import DynamoDedupStore, DynamoMetricsStore, S3ObjectStore
from streamforge.service import ACCEPTED, DUPLICATE, IngestionService
from streamforge.stores import Claim


@pytest.fixture
def aws(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-south-1")
    with mock_aws():
        s3 = boto3.client("s3")
        s3.create_bucket(
            Bucket="sf-test", CreateBucketConfiguration={"LocationConstraint": "ap-south-1"}
        )
        ddb = boto3.resource("dynamodb")
        ddb.create_table(
            TableName="sf-state",
            KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        yield s3, ddb


def test_s3_store_roundtrip(aws):
    store = S3ObjectStore("sf-test", aws[0])
    store.put("a/b.json", b"{}")
    assert store.get("a/b.json") == b"{}" and store.get("nope") is None
    assert store.list_keys("a/") == ["a/b.json"]


def test_dedup_claim_lifecycle(aws):
    d = DynamoDedupStore("sf-state", aws[1])
    assert d.claim("k") is Claim.NEW
    assert d.claim("k") is Claim.RETRY  # claimed but not completed
    d.complete("k")
    assert d.claim("k") is Claim.DUPLICATE


def test_metrics_atomic_counters(aws):
    m = DynamoMetricsStore("sf-state", aws[1])
    m.record("global", {"received": 2, "valid": 1}, "2025-01-01T00:00:00Z")
    m.record("global", {"received": 3, "valid": 3})
    assert m.get("global") == {"received": 5, "valid": 4, "last_success_at": "2025-01-01T00:00:00Z"}
    m.record("source#a", {"received": 1})
    m.record("source#b", {"received": 1})
    assert m.list_scopes("source#") == ["source#a", "source#b"]
    assert m.get("missing") == {}


def test_end_to_end_on_aws_adapters(aws, valid_event, now):
    objects = S3ObjectStore("sf-test", aws[0])
    svc = IngestionService(
        objects, DynamoDedupStore("sf-state", aws[1]), DynamoMetricsStore("sf-state", aws[1]),
        clock=lambda: now,
    )
    assert svc.ingest([valid_event], "r1")[0].status == ACCEPTED
    assert svc.ingest([valid_event], "r2")[0].status == DUPLICATE
    (key,) = objects.list_keys("processed/")
    assert key.startswith("processed/year=2025/month=06/day=15/source=web-app/")
    assert json.loads(objects.get(key))["event_id"] == "evt-0001"
    m = svc.metrics_summary()
    assert (m["total_received"], m["valid"], m["duplicate"]) == (2, 1, 1)
