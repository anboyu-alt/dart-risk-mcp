"""Supabase Storage(blob) + PostgREST(json) 캐시 백엔드.

Vercel 함수는 파일시스템이 비영속이므로 캐시는 외부 저장소여야 한다.
인증에 이미 Supabase를 쓰므로 신규 벤더를 늘리지 않는다.

SDK를 쓰지 않고 REST를 직접 호출한다 — supabase-py는 gotrue/postgrest/
storage3/realtime을 함께 끌고 오는데 우리가 쓰는 건 오브젝트 GET/POST와
테이블 조회뿐이다.

캐시 쓰기 실패는 삼킨다. 캐시는 성능 최적화이지 정확성의 일부가 아니며,
저장 실패로 분석 전체를 중단시키면 안 된다. 읽기 실패도 미스로 처리한다.
"""
from __future__ import annotations

import datetime as _dt

import requests

from se_server.config import SEConfig

_TABLE = "se_cache"


class SupabaseCache:
    def __init__(self, config: SEConfig, session=None) -> None:
        self.config = config
        self.session = session or requests.Session()

    # ── 공통 ──────────────────────────────────────
    def _headers(self) -> dict:
        key = self.config.supabase_service_key
        return {"Authorization": f"Bearer {key}", "apikey": key}

    def _object_url(self, key: str) -> str:
        return (
            f"{self.config.supabase_url}/storage/v1/object/"
            f"{self.config.cache_bucket}/{key}"
        )

    def _table_url(self) -> str:
        return f"{self.config.supabase_url}/rest/v1/{_TABLE}"

    # ── blob (원문 ZIP, 영구) ─────────────────────
    def get_blob(self, key: str) -> bytes | None:
        try:
            resp = self.session.get(self._object_url(key), headers=self._headers(), timeout=30)
        except Exception:
            return None
        if resp.status_code != 200:
            return None
        return resp.content

    def put_blob(self, key: str, data: bytes) -> None:
        headers = self._headers()
        headers["x-upsert"] = "true"
        headers["Content-Type"] = "application/zip"
        try:
            self.session.post(
                self._object_url(key), headers=headers, data=data, timeout=60
            )
        except Exception:
            return

    # ── json (구조화 응답, TTL) ────────────────────
    def get_json(self, key: str) -> dict | None:
        params = {"key": f"eq.{key}", "select": "value,expires_at"}
        try:
            resp = self.session.get(
                self._table_url(), headers=self._headers(), params=params, timeout=15
            )
        except Exception:
            return None
        if resp.status_code != 200:
            return None
        try:
            rows = resp.json()
        except ValueError:
            return None
        if not rows:
            return None
        row = rows[0]
        expires_at = row.get("expires_at")
        if expires_at:
            try:
                deadline = _dt.datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            except ValueError:
                return None
            if _dt.datetime.now(_dt.timezone.utc) >= deadline:
                return None
        return row.get("value")

    def put_json(self, key: str, value: dict, ttl_seconds: int | None) -> None:
        expires_at = None
        if ttl_seconds is not None:
            deadline = _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(seconds=ttl_seconds)
            expires_at = deadline.isoformat()
        headers = self._headers()
        headers["Content-Type"] = "application/json"
        headers["Prefer"] = "resolution=merge-duplicates"
        try:
            self.session.post(
                self._table_url(),
                headers=headers,
                json={"key": key, "value": value, "expires_at": expires_at},
                timeout=15,
            )
        except Exception:
            return
