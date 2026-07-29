"""core 레지스트리 캐시 시임(set_registry_cache)에 꽂히는 배선 계층.

dart_client.py의 _http_cache/set_http_cache/get_http_cache 패턴, 그리고
se_server/http_cache.py의 install()을 그대로 따른다. 다만 정책이 없다 —
행위자 레지스트리는 rcept_no별 blob/json 분기도, DART status 필드에 따른
캐시 가능 여부 판정도 필요 없는 **전역 단일 자산**이라, install은 백엔드를
core 시임에 그대로 주입하기만 한다(SupabaseCache가 이미 get_json/put_json을
직접 제공하므로 CachingHttp 같은 어댑터 클래스가 필요 없다).

TTL은 24시간 고정이다 — dart_risk_mcp.core.known_actors._CACHE_TTL(기존
24시간 파일 캐시)과 반드시 같아야 한다. 두 캐시가 다른 주기로 만료되면
어느 쪽이 최신인지 추론할 수 없다. 실제 만료 시각은 known_actors._load_raw가
Notion 조회 성공 후 `cache.put_json(key, data, _CACHE_TTL)`을 직접 호출해
결정한다 — 이 모듈의 ttl_seconds 인자는 se_server/http_cache.py의
install(backend, json_ttl_seconds)과 시그니처를 맞추기 위한 자리이며, 지금은
core로 전달되는 배선이 없다(core가 인자화된 TTL을 받게 바뀌면 그때 연결한다).

캐시 키는 이 모듈이 아니라 known_actors._REGISTRY_CACHE_KEY(고정 문자열
하나)로 core가 계산한다. 레지스트리는 회사·인물별로 나눌 필요가 없는 전역
자산이고, NOTION_TOKEN·DB_KNOWN_ACTORS(자격증명)는 키에도 캐시된 값에도
들어가지 않는다 — DB id를 키에 섞을 이유도 없다(레지스트리 DB를 여러 개
쓸 계획이 없다).

비공개 레포 패턴(dart-risk-mcp-sightings + SIGHTINGS_REPO_TOKEN — 매일 도는
cron 워크플로우가 사진(sightings)·발굴 상태를 유지하는 방식)을 여기서 쓰지
않는 이유: 그건 **배치 경로**의 해법이지 **요청 시점 경로**에는 맞지 않는다.
Vercel 함수가 사용자 요청마다 GitHub API를 왕복하며 별도 토큰
(SIGHTINGS_REPO_TOKEN)까지 들고 있어야 하는데, SE는 이미 Supabase가
인증·작업 저장소로 배선돼 있다. 신규 벤더·신규 자격증명을 늘리지 않고
기존 Supabase 테이블(se_cache)에 고정 키 하나로 얹는 편이 단순하고
공격면도 늘지 않는다.
"""
from __future__ import annotations

from dart_risk_mcp.core import known_actors

# known_actors._CACHE_TTL과 반드시 같은 값 — 모듈 docstring 참고.
_DEFAULT_TTL_SECONDS = 24 * 3600


def install(backend, ttl_seconds: int = _DEFAULT_TTL_SECONDS):
    """레지스트리 캐시 백엔드를 core 시임에 주입하고 그대로 반환한다.

    backend는 get_json(key)/put_json(key, value, ttl_seconds) 두 메서드만
    제공하면 된다(SupabaseCache가 이미 만족 — CacheBackend 전체를 요구하지
    않는다, core가 se_server 타입을 알 필요가 없어서다).
    """
    known_actors.set_registry_cache(backend)
    return backend
