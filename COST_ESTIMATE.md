# Cost Estimate (Phase 1)

> Estimates from public on-demand list prices and the assumptions below. They have **not** been checked against a real AWS bill (nothing is deployed yet). Prices vary by region; re-check the AWS pricing pages and use AWS Budgets.

| Service | Billing model | Assumption: 100k events/month, ~2 KB each, batches of 10 | Approx. |
|---|---|---|---|
| API Gateway (REST) | per million requests (~US$3.5) | ~10k requests | < $0.05 |
| Lambda | requests + GB-s; free tier 1M req / 400k GB-s | 10k × ~100 ms × 256 MB | $0 (free tier) |
| DynamoDB on-demand | per million read/write units (~$1.25 / $0.25) | ~3 writes/event | ~$0.50 |
| S3 | storage + PUT (~$0.005 per 1k PUT) | 200k PUTs (raw+processed), ~0.4 GB | ~$1.00 |
| CloudWatch Logs | ingestion + storage, 7-day retention | tiny | < $0.50 |
| **Total** | | | **roughly $1–3 / month** |

The dominant driver is S3 PUT count (one object per event ×2). Compaction to larger Parquet files (later phase) cuts this.

## Safeguards
- Usage plan caps traffic at 10 000 requests/day (and 10 rps), bounding worst-case spend from abuse.
- No always-on compute, NAT gateways, databases, or provisioned capacity.
- Create a monthly AWS Budget alert (e.g. $5) before deploying.
- Teardown: see [DEPLOYMENT.md](DEPLOYMENT.md#teardown).
