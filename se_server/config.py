"""SE 서버 환경 설정.

Vercel 환경변수에서 읽는다. DART API 키는 여기에 없다 — 사용자 브라우저가
요청마다 동봉하며 서버는 저장하지 않는다.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class SEConfig:
    supabase_url: str
    supabase_service_key: str
    cache_bucket: str = "se-cache"

    @classmethod
    def from_env(cls) -> "SEConfig":
        url = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
        service_key = os.environ.get("SUPABASE_SERVICE_KEY") or ""
        if not url or not service_key:
            raise ValueError(
                "SUPABASE_URL과 SUPABASE_SERVICE_KEY 환경변수가 필요합니다"
            )
        return cls(
            supabase_url=url,
            supabase_service_key=service_key,
            cache_bucket=os.environ.get("SE_CACHE_BUCKET") or "se-cache",
        )
