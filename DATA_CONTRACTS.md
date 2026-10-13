# Data Contracts (Phase 1)

## Contract: `event` v1.0
Producer: any client of the ingestion API. Consumer: `processed/` readers. Field definitions are in [DATA_DICTIONARY.md](DATA_DICTIONARY.md); enforcement is `src/streamforge/validation.py` (unit-tested in `tests/test_validation.py`).

### Validation rules and error codes
| Code | Rule |
|---|---|
| `missing` | any required field absent or null |
| `invalid_type` | ids not non-empty strings; payload not an object; body not an object |
| `too_long` | id fields > 128 chars |
| `invalid_format` | `source` outside `[A-Za-z0-9._-]{1,64}` |
| `unsupported_event_type` | not in the allowed list |
| `invalid_timestamp` | not ISO-8601 with timezone |
| `in_future` / `too_old` | outside −365 d … +5 min of arrival |
| `unsupported_version` | `schema_version` not in `{1.0}` |
| `too_large` | payload > 32 KB |

### HTTP behaviour
| Case | Status |
|---|---|
| new valid event | 201 `accepted` |
| replay of processed event | 200 `duplicate` |
| validation failure | 422 `rejected` + `errors[]` |
| malformed JSON / bad batch shape | 400 |
| body > 256 KB | 413 |
| storage failure (retry safe) | 503 `failed` |
| batch (`POST /events/batch`, 1–100 events) | 200 with per-event `results`, or 503 if any failed |

### Compatibility policy
- Adding optional fields to the payload or envelope is non-breaking.
- Removing/renaming a required field, or changing a type, requires a new `schema_version` (e.g. `2.0`) that is accepted **alongside** `1.0` during migration.
- Unknown extra top-level fields are currently ignored (not stored in `processed/`, kept in `raw/`).
- Formal versioned data-product contracts, owners and SLAs arrive in Phase 3.
