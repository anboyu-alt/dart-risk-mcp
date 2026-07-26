"""Supabase Auth JWT 검증.

로컬 서명 검증 대신 Supabase에 묻는다. 로컬 검증은 빠르지만 로그아웃·계정
정지가 토큰 만료까지 반영되지 않는데, 인가제 서비스에서 접근 취소가 즉시
되지 않는 것은 받아들이기 어렵다.

대신 결과를 짧은 TTL로 캐시한다. step 엔드포인트는 한 분석당 수십 번
호출되므로 캐시가 없으면 인증이 병목이 되고 Supabase 요청 한도도 소모한다.
"""
from __future__ import annotations

import hashlib
import time
from typing import Callable

import requests

from se_server.config import SEConfig

_DEFAULT_TTL = 60.0

# 캐시 항목이 이 수를 넘으면 만료분을 쓸어낸다. 만료 항목은 같은 토큰이 다시
# 올 때만 덮어써지는데, 회전된 JWT는 재등장하지 않아 영원히 남는다.
_CACHE_SWEEP_AT = 512


class AuthError(Exception):
    """인증 실패. status로 HTTP 응답 코드를 구분한다."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def extract_bearer(header_value) -> str:
    """Authorization 헤더에서 Bearer 토큰만 꺼낸다. 형식이 아니면 빈 문자열.

    비문자열 입력도 조용히 빈 문자열로 떨어뜨린다. 여기서 AttributeError가
    나면 인증 실패(401)가 아니라 서버 오류(500)로 보고돼 원인 파악이 어렵다.
    """
    if not isinstance(header_value, str):
        return ""
    parts = header_value.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return ""
    return parts[1].strip()


class SupabaseAuth:
    def __init__(
        self,
        config: SEConfig,
        session=None,
        ttl_seconds: float = _DEFAULT_TTL,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config
        self.session = session or requests.Session()
        self.ttl_seconds = ttl_seconds
        self._now = now
        # 키는 토큰 해시다. 원문을 키로 쓰면 메모리 덤프·예외 출력에
        # 자격증명이 그대로 남는다.
        self._cache: dict[str, tuple[float, str]] = {}

    @staticmethod
    def _key(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def verify(self, bearer: str) -> str:
        """토큰을 검증하고 사용자 ID를 반환한다. 실패 시 AuthError."""
        if not bearer:
            raise AuthError(401, "인증 토큰이 없습니다")

        key = self._key(bearer)
        hit = self._cache.get(key)
        if hit is not None and self._now() < hit[0]:
            return hit[1]

        try:
            resp = self.session.get(
                f"{self.config.supabase_url}/auth/v1/user",
                headers={
                    "Authorization": f"Bearer {bearer}",
                    "apikey": self.config.supabase_service_key,
                },
                timeout=10,
            )
        except Exception:
            # Supabase 장애를 인증 실패(401)로 보고하면 사용자가 자기 자격증명
            # 문제로 오해한다. 일시적 장애임을 구분해 알린다.
            raise AuthError(503, "인증 서버에 연결할 수 없습니다") from None

        # 5xx·429는 **서버 쪽 문제**다. 401로 보고하면 사용자가 자기 자격증명
        # 문제로 오해한다. 호스티드 서비스에서는 전송 실패보다 게이트웨이
        # 5xx·요청한도 초과가 오히려 흔하다.
        if resp.status_code >= 500 or resp.status_code == 429:
            raise AuthError(503, "인증 서버가 일시적으로 응답하지 않습니다")
        if resp.status_code != 200:
            raise AuthError(401, "인증에 실패했습니다")

        try:
            payload = resp.json()
        except ValueError:
            raise AuthError(503, "인증 서버 응답을 해석할 수 없습니다") from None

        # 응답 형태를 신뢰하지 않는다. dict가 아니거나 id가 문자열이 아니면
        # 인증 실패로 본다 — 여기서 AttributeError가 나면 500이 되고,
        # 숫자 id를 그대로 통과시키면 반환 타입 선언(-> str)이 거짓이 된다.
        user_id = payload.get("id") if isinstance(payload, dict) else None
        if not isinstance(user_id, str) or not user_id:
            raise AuthError(401, "인증에 실패했습니다")

        # 실패는 캐시하지 않는다 — 캐시하면 계정이 복구돼도 TTL 동안 막힌다.
        self._prune()
        self._cache[key] = (self._now() + self.ttl_seconds, user_id)
        return user_id

    def _prune(self) -> None:
        """만료된 캐시 항목을 쓸어낸다.

        만료 항목은 같은 토큰이 다시 올 때만 덮어써지는데, 회전된 JWT는
        재등장하지 않으므로 그대로 두면 무한히 쌓인다. Vercel은 프로세스가
        짧아 영향이 작지만 장기 실행 환경에서는 메모리 누수다.
        """
        if len(self._cache) < _CACHE_SWEEP_AT:
            return
        now = self._now()
        expired = [k for k, (expires, _) in self._cache.items() if now >= expires]
        for key in expired:
            del self._cache[key]
