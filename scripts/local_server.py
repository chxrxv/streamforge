#!/usr/bin/env python3
"""Local HTTP wrapper around the same request handler Lambda uses (in-memory stores, no auth).

For development and for validating scripts/smoke_test.py without AWS. NOT a deployment.
"""
from __future__ import annotations

import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from streamforge.api import handle_request  # noqa: E402
from streamforge.service import IngestionService  # noqa: E402
from streamforge.stores import FileObjectStore, MemoryDedupStore, MemoryMetricsStore  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SERVICE = IngestionService(FileObjectStore(ROOT / "local_data"), MemoryDedupStore(), MemoryMetricsStore())


class Handler(BaseHTTPRequestHandler):
    def _serve(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length).decode() if length else None
        resp = handle_request(self.command, self.path.split("?")[0], {"body": body}, SERVICE, "local")
        data = resp["body"].encode()
        self.send_response(resp["statusCode"])
        for k, v in resp["headers"].items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    do_GET = do_POST = _serve

    def log_message(self, *args) -> None:
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    print(f"Local StreamForge on http://127.0.0.1:{port}/ (data in {ROOT / 'local_data'})")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
