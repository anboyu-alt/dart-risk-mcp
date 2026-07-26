"""Supabase PostgREST 작업 저장소.

Vercel 함수는 프로세스가 요청마다 새로 뜨므로 작업 상태는 외부에 있어야 한다.
이미 인증·캐시에 Supabase를 쓰므로 같은 프로젝트의 테이블을 쓴다.

SE-1의 캐시와 달리 **실패를 삼키지 않는다.** 캐시는 성능 최적화라 실패해도
정확성이 유지되지만, 작업 상태 저장에 실패하면 진행이 유실되고 다음 호출이
같은 일을 반복한다. 조용한 실패는 무한 루프로 이어진다.
"""
from __future__ import annotations

import datetime as _dt

import requests

from se_server.config import SEConfig
from se_server.jobs.model import Job

_TABLE = "se_jobs"


class SupabaseJobStore:
    def __init__(self, config: SEConfig, session=None) -> None:
        self.config = config
        self.session = session or requests.Session()

    def _headers(self) -> dict:
        key = self.config.supabase_service_key
        return {"Authorization": f"Bearer {key}", "apikey": key}

    def _table_url(self) -> str:
        return f"{self.config.supabase_url}/rest/v1/{_TABLE}"

    def save(self, job: Job) -> None:
        headers = self._headers()
        headers["Content-Type"] = "application/json"
        headers["Prefer"] = "resolution=merge-duplicates"
        resp = self.session.post(
            self._table_url(),
            headers=headers,
            json={
                "job_id": job.job_id,
                "state": job.to_dict(),
                "status": job.status,
                "user_id": job.user_id,
                # updated_at을 페이로드에 반드시 넣는다. 스키마의 default now()는
                # INSERT에만 적용되고, PostgREST의 merge-duplicates upsert는
                # 페이로드에 있는 컬럼만 SET하므로, 빼면 최초 삽입 시각에
                # 영원히 고정된다. 이 계층은 항목마다 저장을 반복하는 것이
                # 존재 이유라 그 값은 곧바로 거짓이 된다.
                "updated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
            },
            timeout=15,
        )
        if resp.status_code >= 300:
            raise RuntimeError(f"작업 상태 저장 실패 (HTTP {resp.status_code})")

    def load(self, job_id: str, user_id: str = "") -> Job | None:
        params = {"job_id": f"eq.{job_id}", "select": "state"}
        if user_id:
            # 소유자 필터를 쿼리에 넣는다. 받아온 뒤 비교하면 남의 레코드가
            # 잠시라도 프로세스 메모리에 들어온다.
            params["user_id"] = f"eq.{user_id}"
        resp = self.session.get(
            self._table_url(),
            headers=self._headers(),
            params=params,
            timeout=15,
        )
        if resp.status_code >= 300:
            raise RuntimeError(f"작업 상태 조회 실패 (HTTP {resp.status_code})")
        rows = resp.json()
        if not rows:
            return None
        return Job.from_dict(rows[0]["state"])
