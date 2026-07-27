"""Supabase REST 인증 헤더.

Supabase가 API 키 체계를 바꿨다. 신형 키(sb_secret_..., sb_publishable_...)는
**JWT가 아니며 Authorization 헤더에서 거부된다.** 반면 legacy service_role
키는 JWT라 Authorization을 요구하는 경로(Storage 등)가 있다.

따라서 apikey는 항상 보내고, Authorization: Bearer는 키가 JWT일 때만 붙인다.
이러면 두 형식을 모두 지원하며, legacy가 걷어내져도 코드를 고칠 필요가 없다.

주의: 사용자 JWT를 Authorization에 넣는 경로(se_server/api/auth.py)는 이
함수를 쓰지 않는다. 거기서는 Authorization이 **사용자 토큰**이고 apikey만
서비스 키다.
"""
from __future__ import annotations


def looks_like_jwt(key) -> bool:
    """키가 JWT 형태(base64url 3파트)인지 판정한다.

    legacy service_role 키가 이 형태다. 신형 sb_secret_ 키는 아니다.
    """
    if not isinstance(key, str):
        return False
    parts = key.split(".")
    return len(parts) == 3 and all(parts)


def auth_headers(key: str) -> dict:
    """Supabase REST 요청의 인증 헤더를 만든다.

    호출자가 반환값에 Content-Type 등을 덧붙이므로 매번 새 dict를 돌려준다.
    """
    headers = {"apikey": key}
    if looks_like_jwt(key):
        headers["Authorization"] = f"Bearer {key}"
    return headers
