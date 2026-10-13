#!/usr/bin/env python3
"""Run the pipeline locally (filesystem storage in ./local_data). This is NOT a cloud deployment."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from streamforge.service import IngestionService  # noqa: E402
from streamforge.stores import FileObjectStore, MemoryDedupStore, MemoryMetricsStore  # noqa: E402


def main() -> None:
    service = IngestionService(FileObjectStore(ROOT / "local_data"), MemoryDedupStore(), MemoryMetricsStore())
    events = json.loads((ROOT / "samples" / "events_batch.json").read_text())["events"]
    # Re-stamp sample events to "now" so they pass the timestamp-window check.
    from datetime import UTC, datetime
    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    for e in events:
        if isinstance(e, dict) and e.get("event_timestamp") == "__NOW__":
            e["event_timestamp"] = stamp
    for outcome in service.ingest(events, "local-demo"):
        print(outcome.to_dict())
    print(json.dumps(service.metrics_summary(), indent=2))
    print("Files written under", ROOT / "local_data")


if __name__ == "__main__":
    main()
