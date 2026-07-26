"""캐시 백엔드 인터페이스와 인메모리 구현.

두 종류를 나눠 다룬다:
- blob: 공시 원문 ZIP. rcept_no가 불변 식별자이고 정정공시는 새 번호를
  발급받으므로 stale이 발생하지 않는다. TTL 없이 영구 보관한다.
- json: 구조화 API 응답. 확정 연도는 불변이나 최근 연도는 정정될 수
  있으므로 TTL을 둔다.

근거: docs/superpowers/specs/2026-07-26-risk-viewer-se-design.md §6.2
"""
from __future__ import annotations

import time
from typing import Callable, Protocol


class CacheBackend(Protocol):
    """SE 캐시 백엔드가 제공해야 하는 최소 인터페이스."""

    def get_blob(self, key: str) -> bytes | None: ...

    def put_blob(self, key: str, data: bytes) -> None: ...

    def get_json(self, key: str) -> dict | None: ...

    def put_json(self, key: str, value: dict, ttl_seconds: int | None) -> None: ...


class MemoryCache:
    """프로세스 메모리 백엔드. 테스트와 로컬 개발용.

    Vercel 함수는 파일시스템·메모리가 비영속이므로 운영에서는 쓰지 않는다.
    """

    def __init__(self, now: Callable[[], float] = time.time) -> None:
        self._now = now
        self._blobs: dict[str, bytes] = {}
        self._json: dict[str, tuple[float | None, dict]] = {}

    def get_blob(self, key: str) -> bytes | None:
        return self._blobs.get(key)

    def put_blob(self, key: str, data: bytes) -> None:
        self._blobs[key] = data

    def get_json(self, key: str) -> dict | None:
        entry = self._json.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if expires_at is not None and self._now() >= expires_at:
            del self._json[key]
            return None
        return value

    def put_json(self, key: str, value: dict, ttl_seconds: int | None) -> None:
        expires_at = None if ttl_seconds is None else self._now() + ttl_seconds
        self._json[key] = (expires_at, value)
