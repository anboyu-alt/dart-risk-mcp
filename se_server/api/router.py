"""경로 파싱과 디스패치.

Vercel의 파일 기반 동적 라우팅(api/[id].py) 대신 코드로 라우팅한다.
파일 배치에 라우팅이 있으면 단위 테스트로 검증할 수 없기 때문이다.
vercel.json이 /api/se/ 이하만 이 단일 함수로 rewrite한다
(그 외 /api/* — 예: /api/list.json — 는 기존 CORS 릴레이
api/[endpoint].js가 파일 기반 라우팅으로 그대로 처리한다).

경로에 /se/ 세그먼트를 두는 이유: 기존 CORS 릴레이(api/[endpoint].js)가
`/api/:endpoint` 형태의 단일 세그먼트 동적 라우트를 차지하고 있다.
`/api/analyze`를 그대로 쓰면 그 정규식과 같은 세그먼트를 다투게 되어
rewrite와 릴레이의 파일 기반 라우팅 중 무엇이 이기는지가 Vercel 내부
우선순위에 달린다. 릴레이로 새면 403 {"error":"forbidden"}이 나오는데
하위 경로(/api/analyze/{id}/step)는 경쟁자가 없어 정상 동작하는
**비대칭 실패**라 원인 파악이 매우 어렵다. 두 세그먼트(/api/se/analyze)면
릴레이 정규식이 구조적으로 매칭 불가라 우선순위에 의존하지 않는다.
"""
from __future__ import annotations

import re

# job_id는 secrets.token_urlsafe 결과라 영숫자와 -, _ 만 나온다.
# 이 문자 집합을 벗어나는 값(경로 순회 등)은 애초에 매칭되지 않는다.
_JOB_ID = r"(?P<job_id>[A-Za-z0-9_-]+)"

# 섹션 키. registry 키(insider_timeline)와 원문 키(doc:<rcept_no>) 두 형태다.
# 콜론은 허용하되 `/`·`.`는 배제해 경로 순회를 구조적으로 막는다.
_SECTION_KEY = r"(?P<key>[A-Za-z0-9_:-]+)"

# fullmatch로 대조하므로 ^...$ 앵커를 쓰지 않는다.
_ROUTES: tuple[tuple[str, re.Pattern, str], ...] = (
    ("POST", re.compile(r"/api/se/analyze"), "create"),
    ("POST", re.compile(rf"/api/se/analyze/{_JOB_ID}/step"), "step"),
    ("GET", re.compile(rf"/api/se/analyze/{_JOB_ID}/section/{_SECTION_KEY}"), "section"),
    ("GET", re.compile(rf"/api/se/analyze/{_JOB_ID}"), "get"),
)


def match(method: str, path: str) -> tuple[str, dict] | None:
    """(라우트 이름, 경로 변수)를 반환한다. 매칭 실패 시 None."""
    clean = path.split("?", 1)[0].split("#", 1)[0]
    if len(clean) > 1:
        clean = clean.rstrip("/")
    for route_method, pattern, name in _ROUTES:
        if route_method != method.upper():
            continue
        # fullmatch를 쓴다. Python re의 `$`는 문자열 끝뿐 아니라 줄바꿈
        # 직전에서도 매치되므로, match + $면 "/api/analyze/abc\n"이
        # 통과한다. 라우터는 보안 경계라 이 함정을 남겨두지 않는다.
        m = pattern.fullmatch(clean)
        if m:
            return name, dict(m.groupdict())
    return None
