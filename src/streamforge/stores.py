"""Storage interfaces plus in-memory/filesystem implementations for tests and local runs."""
from __future__ import annotations

import enum
import threading
from collections import Counter
from pathlib import Path
from typing import Protocol


class Claim(enum.Enum):
    NEW = "new"  # first time we see this event
    RETRY = "retry"  # a previous attempt claimed it but never completed
    DUPLICATE = "duplicate"  # a previous attempt completed


class ObjectStore(Protocol):
    def put(self, key: str, body: bytes) -> None: ...
    def get(self, key: str) -> bytes | None: ...
    def list_keys(self, prefix: str) -> list[str]: ...


class DedupStore(Protocol):
    def claim(self, dedup_key: str) -> Claim: ...
    def complete(self, dedup_key: str) -> None: ...


class MetricsStore(Protocol):
    def record(self, scope: str, counters: dict[str, int], last_success_at: str | None = None) -> None: ...
    def get(self, scope: str) -> dict[str, int | str]: ...
    def list_scopes(self, prefix: str) -> list[str]: ...


class MemoryObjectStore:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put(self, key: str, body: bytes) -> None:
        self.objects[key] = body

    def get(self, key: str) -> bytes | None:
        return self.objects.get(key)

    def list_keys(self, prefix: str) -> list[str]:
        return sorted(k for k in self.objects if k.startswith(prefix))


class FileObjectStore(MemoryObjectStore):
    """Writes under a local directory with the same key layout as S3 (local dev only)."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def put(self, key: str, body: bytes) -> None:
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)

    def get(self, key: str) -> bytes | None:
        path = self.root / key
        return path.read_bytes() if path.is_file() else None

    def list_keys(self, prefix: str) -> list[str]:
        return sorted(p.relative_to(self.root).as_posix() for p in self.root.rglob("*") if p.is_file()
                      and p.relative_to(self.root).as_posix().startswith(prefix))


class MemoryDedupStore:
    def __init__(self) -> None:
        self.state: dict[str, str] = {}
        self._lock = threading.Lock()

    def claim(self, dedup_key: str) -> Claim:
        with self._lock:
            status = self.state.get(dedup_key)
            if status is None:
                self.state[dedup_key] = "pending"
                return Claim.NEW
            return Claim.DUPLICATE if status == "done" else Claim.RETRY

    def complete(self, dedup_key: str) -> None:
        with self._lock:
            self.state[dedup_key] = "done"


class MemoryMetricsStore:
    def __init__(self) -> None:
        self.data: dict[str, Counter] = {}
        self.last_success: dict[str, str] = {}

    def record(self, scope: str, counters: dict[str, int], last_success_at: str | None = None) -> None:
        bucket = self.data.setdefault(scope, Counter())
        for name, value in counters.items():
            bucket[name] += value
        if last_success_at:
            self.last_success[scope] = last_success_at

    def get(self, scope: str) -> dict[str, int | str]:
        out: dict[str, int | str] = dict(self.data.get(scope, {}))
        if scope in self.last_success:
            out["last_success_at"] = self.last_success[scope]
        return out

    def list_scopes(self, prefix: str) -> list[str]:
        return sorted(s for s in self.data if s.startswith(prefix))
