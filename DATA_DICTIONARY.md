# Data Dictionary (Phase 1)

All sample/demo data in this repository is **synthetic**.

## Ingest event (input, schema v1.0)
| Field | Type | Required | Meaning |
|---|---|---|---|
| event_id | string ≤128 | yes | Producer-unique id within `source`; idempotency key |
| event_type | string | yes | One of `page_view, click, purchase, sensor_reading, user_signup, model_inference` |
| event_timestamp | string | yes | ISO-8601 **with** offset or `Z`; not >5 min in future, not >365 days old |
| source | string | yes | Producing system, `[A-Za-z0-9._-]{1,64}` |
| entity_id | string ≤128 | yes | Business entity the event is about (user, device…) |
| schema_version | string | no (default `1.0`) | Contract version; only `1.0` supported |
| payload | object | yes | Event-specific attributes, ≤32 KB |

## Processed record (`processed/`)
| Field | Type | Meaning |
|---|---|---|
| event_id, source, entity_id, event_type, schema_version, payload | as input | passed through |
| event_timestamp | string | normalised to UTC, `Z` suffix |
| event_date | string `YYYY-MM-DD` | UTC date of the event; the partition column |
| payload_sha256 | string | hash of canonical JSON payload (change detection, lineage) |
| ingested_at | string | when the API received it (UTC) |
| request_id | string | API Gateway request id of the winning write |
| pipeline_version | string | version of the transform that produced the record |

## Raw record (`raw/`)
`{received_at, request_id, event}` — the event exactly as submitted, plus the envelope.

## Rejected record (`rejected/`)
`{rejected_at, request_id, index, errors[], diagnostics{sha256,size_bytes,json_type,top_level_keys,event_id?,event_type?,source?}}` — no payload values.

## Metrics (`GET /metrics`)
| Field | Meaning |
|---|---|
| total_received | all events seen |
| valid | new events validated and stored |
| invalid | failed validation |
| duplicate | valid but already processed |
| processing_failures | storage errors (client should retry) |
| valid_rate | valid / total_received (null if none) |
| requests | API calls that carried events |
| avg_batch_processing_ms | mean wall time per request |
| last_success_at | arrival time of the latest request with ≥1 newly stored event |
| by_source | per-source received/valid/duplicate/failed/last_success_at |

## State table (DynamoDB `pk`)
`dedup#<hash>` → `{status: pending|done, expires_at}`; `metrics#global`, `metrics#source#<name>` → counters.
