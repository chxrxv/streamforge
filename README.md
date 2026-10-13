# StreamForge — Real-Time AI Data Platform

Reliable, observable, analytics-ready data pipelines for AI and business intelligence.

A data-engineering portfolio project targeting Amazon Data Engineer I (CMT, Job ID 10499657).

## Status

| Item | Status |
|---|---|
| Phase 1 code + tests | implemented; 72 tests passing locally |
| Local run | works (`scripts/local_server.py` + `scripts/smoke_test.py`) |
| AWS deployment | **not deployed** – no AWS credentials/CLI in the build environment; see [DEPLOYMENT.md](DEPLOYMENT.md) |

## Roadmap

1. **Phase 1** – Ingestion API (API Gateway + Lambda), validation, S3 raw/processed/rejected, idempotency, metrics, CDK.
2. **Phase 2** – SQL/data model/analytics.
3. **Phase 3** – Event-driven processing, DLQ, contracts, backfill.
4. **Phase 4** – Semantic layer API + dashboard.
5. **Phase 5** – Optional (Parquet/Athena/etc.), chosen by value and cost.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
.\.venv\Scripts\python -m pytest
```

## Phase 1 at a glance
`POST /events`, `POST /events/batch`, `GET /metrics` behind API Gateway (API key + throttling) → Lambda → S3 `raw/`, `processed/`, `rejected/` (Hive-style partitions), DynamoDB for idempotency claims and atomic quality counters. Infrastructure is AWS CDK (Python).

Docs: [ARCHITECTURE](ARCHITECTURE.md) · [DATA_DICTIONARY](DATA_DICTIONARY.md) · [DATA_CONTRACTS](DATA_CONTRACTS.md) · [DEPLOYMENT](DEPLOYMENT.md) · [COST_ESTIMATE](COST_ESTIMATE.md)

Try it locally:
```powershell
.\.venv\Scripts\python scripts\local_demo.py
```
