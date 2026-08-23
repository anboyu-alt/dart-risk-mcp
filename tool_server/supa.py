"""Supabase PostgREST 최소 래퍼 — 접속 분석 저장·조회 전용.

공개 뷰어 트래픽 전용이라 인가제 경로와 코드를 묶지 않는다 — 두 경계를
묶으면 한쪽 사고가 다른 쪽으로 번진다(`tool_server/doc.py`가 실패 판별
규칙을 복제해 둔 것과 같은 이유).

post/get을 주입 가능하게 둔 이유: 테스트가 네트워크를 타지 않기 위해서다.
"""
from __future__ import annotations

import os

import requests

_TIMEOUT = 5


def supa_config() -> tuple[str, str]:
    """(url, service_key). 둘 중 하나라도 없으면 ("", "")."""
    url = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY") or ""
    if not url or not key:
        return "", ""
    return url, key


def _headers(key: str) -> dict:
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        # 삽입 응답 본문은 쓰지 않는다 — 수집은 fire-and-forget이다.
        "Prefer": "return=minimal",
    }


def insert_row(table: str, row: dict, *, post=None) -> bool:
    """한 행 삽입. 실패는 False로 삼킨다 — 수집 실패가 뷰어를 깨면 안 된다."""
    url, key = supa_config()
    if not url:
        return False
    sender = post or requests.post
    try:
        resp = sender(
            f"{url}/rest/v1/{table}",
            json=row,
            headers=_headers(key),
            timeout=_TIMEOUT,
        )
    except Exception:  # noqa: BLE001 — 어떤 실패든 수집 포기로 처리한다
        return False
    return 200 <= getattr(resp, "status_code", 500) < 300


def select_rows(path: str, *, get=None) -> list[dict]:
    """PostgREST 조회. path 예: "v_corp_ranking?order=views.desc&limit=50".

    실패는 빈 목록으로 삼킨다 — 대시보드가 500 대신 "데이터 없음"을 보이는
    편이 낫다. 원인은 서버 로그에 남는다.
    """
    url, key = supa_config()
    if not url:
        return []
    fetcher = get or requests.get
    try:
        resp = fetcher(
            f"{url}/rest/v1/{path}",
            headers=_headers(key),
            timeout=_TIMEOUT,
        )
        if not (200 <= getattr(resp, "status_code", 500) < 300):
            return []
        payload = resp.json()
    except Exception:  # noqa: BLE001
        return []
    return payload if isinstance(payload, list) else []
