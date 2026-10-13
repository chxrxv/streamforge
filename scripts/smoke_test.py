#!/usr/bin/env python3
"""Exercise a deployed StreamForge API. Reads STREAMFORGE_API_URL / STREAMFORGE_API_KEY from env.

Sends a valid event, a replay (duplicate), an invalid event and a batch, then checks that
/metrics moved by exactly the expected amounts. Exit code 0 only if every check passes.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime


def call(base: str, key: str, method: str, path: str, body=None) -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base.rstrip("/") + path, data=data, method=method,
                                 headers={"Content-Type": "application/json", "x-api-key": key})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"{}")


def main() -> int:
    base, key = os.environ.get("STREAMFORGE_API_URL"), os.environ.get("STREAMFORGE_API_KEY")
    if not base or not key:
        print("Set STREAMFORGE_API_URL and STREAMFORGE_API_KEY (see DEPLOYMENT.md)", file=sys.stderr)
        return 2
    run = uuid.uuid4().hex[:8]
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    event = {"event_id": f"smoke-{run}-1", "event_type": "page_view", "event_timestamp": now,
             "source": "smoke-test", "entity_id": "user-smoke", "schema_version": "1.0",
             "payload": {"url": "/smoke"}}
    bad = {**event, "event_id": f"smoke-{run}-bad", "event_timestamp": "not-a-timestamp"}
    batch = {"events": [{**event, "event_id": f"smoke-{run}-b{i}"} for i in range(3)]}

    _, before = call(base, key, "GET", "/metrics")
    results = [("valid event -> 201", call(base, key, "POST", "/events", event)[0] == 201)]
    replay_status, replay_body = call(base, key, "POST", "/events", event)
    replay_ok = (replay_status, replay_body.get("status")) == (200, "duplicate")
    results.append(("replay -> 200 duplicate", replay_ok))
    results.append(("invalid event -> 422", call(base, key, "POST", "/events", bad)[0] == 422))
    results.append(("batch -> 200", call(base, key, "POST", "/events/batch", batch)[0] == 200))
    _, after = call(base, key, "GET", "/metrics")
    # received: 1 valid + 1 replay + 1 invalid + 3 batch = 6; valid +4; invalid +1; duplicate +1
    delta = {k: after[k] - before[k] for k in ("total_received", "valid", "invalid", "duplicate")}
    expected = {"total_received": 6, "valid": 4, "invalid": 1, "duplicate": 1}
    results.append(("metrics delta == expected", delta == expected))
    for name, ok in results:
        print(("PASS " if ok else "FAIL ") + name)
    print("metrics delta:", delta)
    return 0 if all(ok for _, ok in results) else 1


if __name__ == "__main__":
    sys.exit(main())
