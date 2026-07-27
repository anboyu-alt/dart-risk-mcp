"""SE 서버 환경 설정.

Vercel 환경변수에서 읽는다. DART API 키는 여기에 없다 — 사용자 브라우저가
요청마다 동봉하며 서버는 저장하지 않는다.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class SEConfig:
    supabase_url: str
    # repr=False: service_role 키는 RLS를 우회하는 최고 권한 자격증명이다.
    # dataclass 기본 __repr__에 노출되면 로그·예외 문자열 한 번으로 유출된다.
    supabase_service_key: str = field(repr=False)
    cache_bucket: str = "se-cache"
    # 브라우저에 내보내는 공개 키(구 anon). RLS가 실제 방어선이므로 노출돼도
    # 되는 값이지만, repr에 담을 이유는 없어 service key와 같이 가린다.
    supabase_anon_key: str = field(default="", repr=False)

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
            supabase_anon_key=os.environ.get("SUPABASE_ANON_KEY") or "",
        )
