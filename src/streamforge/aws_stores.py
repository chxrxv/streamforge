"""AWS-backed implementations of the store interfaces (S3 objects, DynamoDB state)."""
from __future__ import annotations

import time
from typing import Any

import boto3
from botocore.exceptions import ClientError

from .stores import Claim

DEDUP_TTL_SECONDS = 30 * 24 * 3600  # idempotency window: 30 days (see ARCHITECTURE.md)


class S3ObjectStore:
    def __init__(self, bucket: str, client: Any = None) -> None:
        self.bucket = bucket
        self.client = client or boto3.client("s3")

    def put(self, key: str, body: bytes) -> None:
        self.client.put_object(
            Bucket=self.bucket, Key=key, Body=body, ContentType="application/json"
        )

    def get(self, key: str) -> bytes | None:
        try:
            return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        except ClientError as exc:
            if exc.response["Error"]["Code"] in ("NoSuchKey", "404"):
                return None
            raise

    def list_keys(self, prefix: str) -> list[str]:
        keys: list[str] = []
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            keys.extend(obj["Key"] for obj in page.get("Contents", []))
        return keys


class DynamoDedupStore:
    """Claim = conditional put. Status 'pending' until complete() marks it 'done'."""

    def __init__(self, table_name: str, resource: Any = None) -> None:
        self.table = (resource or boto3.resource("dynamodb")).Table(table_name)

    def claim(self, dedup_key: str) -> Claim:
        pk = f"dedup#{dedup_key}"
        try:
            self.table.put_item(
                Item={"pk": pk, "status": "pending", "expires_at": int(time.time()) + DEDUP_TTL_SECONDS},
                ConditionExpression="attribute_not_exists(pk)",
            )
            return Claim.NEW
        except ClientError as exc:
            if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise
        item = self.table.get_item(Key={"pk": pk}, ConsistentRead=True).get("Item", {})
        return Claim.DUPLICATE if item.get("status") == "done" else Claim.RETRY

    def complete(self, dedup_key: str) -> None:
        self.table.update_item(
            Key={"pk": f"dedup#{dedup_key}"},
            UpdateExpression="SET #s = :done",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":done": "done"},
        )


class DynamoMetricsStore:
    def __init__(self, table_name: str, resource: Any = None) -> None:
        self.table = (resource or boto3.resource("dynamodb")).Table(table_name)

    @staticmethod
    def _pk(scope: str) -> str:
        return f"metrics#{scope}"

    def record(self, scope: str, counters: dict[str, int], last_success_at: str | None = None) -> None:
        names: dict[str, str] = {}
        values: dict[str, Any] = {}
        add_parts = []
        for i, (name, amount) in enumerate(counters.items()):
            names[f"#c{i}"] = name
            values[f":v{i}"] = amount
            add_parts.append(f"#c{i} :v{i}")
        expr = "ADD " + ", ".join(add_parts)
        if last_success_at:
            names["#ls"] = "last_success_at"
            values[":ls"] = last_success_at
            expr += " SET #ls = :ls"
        self.table.update_item(
            Key={"pk": self._pk(scope)},
            UpdateExpression=expr,
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
        )

    def get(self, scope: str) -> dict[str, int | str]:
        item = self.table.get_item(Key={"pk": self._pk(scope)}, ConsistentRead=True).get("Item", {})
        return {k: (int(v) if k != "last_success_at" else v) for k, v in item.items() if k != "pk"}

    def list_scopes(self, prefix: str) -> list[str]:
        scopes: list[str] = []
        kwargs: dict[str, Any] = {
            "FilterExpression": "begins_with(pk, :p)",
            "ExpressionAttributeValues": {":p": self._pk(prefix)},
            "ProjectionExpression": "pk",
        }
        while True:
            page = self.table.scan(**kwargs)
            scopes.extend(i["pk"][len("metrics#"):] for i in page.get("Items", []))
            if "LastEvaluatedKey" not in page:
                return sorted(scopes)
            kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]
