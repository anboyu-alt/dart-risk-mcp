"""경로 파싱과 디스패치.

Vercel의 파일 기반 동적 라우팅(api/[id].py) 대신 코드로 라우팅한다.
파일 배치에 라우팅이 있으면 단위 테스트로 검증할 수 없기 때문이다.
vercel.json이 /api/* 전부를 단일 함수로 rewrite한다.
"""
from __future__ import annotations

import re

# job_id는 secrets.token_urlsafe 결과라 영숫자와 -, _ 만 나온다.
# 이 문자 집합을 벗어나는 값(경로 순회 등)은 애초에 매칭되지 않는다.
_JOB_ID = r"(?P<job_id>[A-Za-z0-9_-]+)"

_ROUTES: tuple[tuple[str, re.Pattern, str], ...] = (
    ("POST", re.compile(r"^/api/analyze$"), "create"),
    ("POST", re.compile(rf"^/api/analyze/{_JOB_ID}/step$"), "step"),
    ("GET", re.compile(rf"^/api/analyze/{_JOB_ID}$"), "get"),
)


def match(method: str, path: str) -> tuple[str, dict] | None:
    """(라우트 이름, 경로 변수)를 반환한다. 매칭 실패 시 None."""
    clean = path.split("?", 1)[0].split("#", 1)[0]
    if len(clean) > 1:
        clean = clean.rstrip("/")
    for route_method, pattern, name in _ROUTES:
        if route_method != method.upper():
            continue
        m = pattern.match(clean)
        if m:
            return name, dict(m.groupdict())
    return None
