# StreamForge — Real-Time AI Data Platform

Reliable, observable, analytics-ready data pipelines for AI and business intelligence.

A data-engineering portfolio project targeting Amazon Data Engineer I (CMT, Job ID 10499657).

## Status

| Item | Status |
|---|---|
| Phase 1 code + tests | in progress |
| AWS deployment | **not deployed** (see DEPLOYMENT.md) |

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
