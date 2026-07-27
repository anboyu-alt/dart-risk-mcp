"""엔드포인트 로직.

프레임워크를 모른다 — Request를 받아 Response를 돌려주는 순수 함수다.
Vercel 어댑터가 변환을 담당한다.

인증은 **어떤 데이터 경로보다 먼저** 통과해야 한다. 인증 실패 시 저장소를
건드리지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

from dart_risk_mcp.core.dart_client import fetch_disclosure_full, resolve_corp
from dart_risk_mcp.core.known_actors import lookup_actors_by_company
from se_server.api.auth import AuthError, extract_bearer
from se_server.api.router import match
from se_server.api.types import Request, Response
from se_server.jobs import runner
from se_server.jobs.store import JobStore

# Vercel 상한보다 충분히 작고 OVERSIZED_RESERVE(20)보다 큰 값.
_DEFAULT_BUDGET = 25.0

_MIN_YEARS = 1
_MAX_YEARS = 5

# 키 값이나 예외 원문은 담지 않는다 — "확인해 보라"는 방향만 제시한다.
_DART_FETCH_FAILED_MSG = (
    "공시 원문을 가져오지 못했습니다. DART 키가 올바른지, 접속 상태가"
    " 정상인지 확인해 주세요"
)


@dataclass
class Deps:
    store: JobStore
    auth: object  # SupabaseAuth 또는 verify(bearer) -> user_id 를 만족하는 것
    budget_seconds: float = _DEFAULT_BUDGET
    config: object = None  # SEConfig. /api/se/config 응답에만 쓴다


def handle(request: Request, deps: Deps) -> Response:
    """요청 하나를 처리한다."""
    route = match(request.method, request.path)
    if route is None:
        return Response.error(404, "존재하지 않는 경로입니다")
    name, path_vars = route

    # config는 로그인 전에 필요하므로 인증 앞에 둔다. 공개 정보만 담는다.
    if name == "config":
        return _config(deps)

    # 그 외에는 인증이 먼저다. 실패하면 저장소·DART 어디에도 닿지 않는다.
    try:
        user_id = deps.auth.verify(extract_bearer(request.header("Authorization")))
    except AuthError as exc:
        return Response.error(exc.status, exc.message)

    # 빈 user_id는 저장소에서 소유자 검사를 **통째로 끄는** 값이다
    # (JobStore.load의 `if user_id:` 분기). Deps.auth는 덕 타이핑이라
    # 계약이 강제되지 않으므로 핸들러가 스스로 방어한다 — 가드가 조용히
    # 꺼지느니 인증 실패로 떨어뜨리는 편이 안전하다.
    if not isinstance(user_id, str) or not user_id:
        return Response.error(401, "인증에 실패했습니다")

    if name == "create":
        return _create(request, deps, user_id)
    if name == "step":
        return _step(request, deps, user_id, path_vars["job_id"])
    if name == "get":
        return _get(deps, user_id, path_vars["job_id"])
    if name == "section":
        return _section(deps, user_id, path_vars["job_id"], path_vars["key"])
    if name == "disclosure":
        return _disclosure(request, deps, path_vars["rcept_no"])
    if name == "actors":
        return _actors(request, deps)
    # 라우트가 늘었는데 분기를 빠뜨리면 조용히 엉뚱한 핸들러로 새지 않고
    # 여기서 드러난다.
    return Response.error(404, "존재하지 않는 경로입니다")


def _dart_key(request: Request) -> str:
    """DART 키는 헤더로만 받는다.

    쿼리스트링에 넣으면 접근 로그·리퍼러·프록시에 그대로 남는다.
    """
    return request.header("X-DART-Key").strip()


def _clamp_years(raw) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = _MIN_YEARS
    return max(_MIN_YEARS, min(_MAX_YEARS, value))


def _body(request: Request) -> dict:
    """본문을 dict로 정규화한다.

    JSON 배열·null·문자열 본문이 오면 .get()에서 AttributeError가 나
    핸들러 밖으로 전파된다(400이 아니라 500이 된다).
    """
    return request.body if isinstance(request.body, dict) else {}


def _create(request: Request, deps: Deps, user_id: str) -> Response:
    body = _body(request)
    company = str(body.get("company") or "").strip()
    if not company:
        return Response.error(400, "company가 필요합니다")

    api_key = _dart_key(request)
    if not api_key:
        return Response.error(400, "X-DART-Key 헤더가 필요합니다")

    # resolve_corp는 실패 시 None을 반환한다(빈 튜플이 아니다). 곧바로
    # 언패킹하면 TypeError가 나서 아래 404에 도달하지 못하고 500이 된다.
    resolved = resolve_corp(company, api_key)
    if not resolved:
        return Response.error(404, f"기업을 찾지 못했습니다: {company}")
    corp_name, info = resolved

    job = runner.create_job(
        corp_name or company,
        info["corp_code"],
        _clamp_years(body.get("lookback_years", 1)),
        deps.store,
        user_id=user_id,
    )
    return Response(201, {
        "job_id": job.job_id,
        "company": job.company,
        "total": len(job.items),
    })


def _step(request: Request, deps: Deps, user_id: str, job_id: str) -> Response:
    api_key = _dart_key(request)
    if not api_key:
        return Response.error(400, "X-DART-Key 헤더가 필요합니다")

    # 소유자 불일치는 404다. 403으로 구분하면 남의 job_id가 존재하는지를
    # 알려주게 된다.
    if deps.store.load(job_id, user_id=user_id) is None:
        return Response.error(404, "작업을 찾을 수 없습니다")

    try:
        result = runner.run_step(
            job_id, api_key, deps.store,
            budget_seconds=deps.budget_seconds, user_id=user_id,
        )
    except ValueError:
        # run_step의 ValueError는 두 가지다. 어느 쪽이든 사용자가 고칠 수
        # 있는 게 아니므로 내부 문구를 그대로 돌려주지 않는다:
        #   - 작업 없음(사전 확인 이후 사라진 경우) → 404
        #   - 예산이 OVERSIZED_RESERVE 이하 → 서버 설정 오류(500)
        if deps.store.load(job_id, user_id=user_id) is None:
            return Response.error(404, "작업을 찾을 수 없습니다")
        return Response.error(500, "서버 설정 오류로 작업을 진행할 수 없습니다")

    return Response(200, {
        "done": result.done,
        "processed": result.processed,
        "finished": result.finished,
        "total": result.total,
        "stalled": result.stalled,
    })


def _get(deps: Deps, user_id: str, job_id: str) -> Response:
    job = deps.store.load(job_id, user_id=user_id)
    if job is None:
        return Response.error(404, "작업을 찾을 수 없습니다")

    finished, total = job.progress()
    # 섹션 **본문은 담지 않는다.** 화면은 이 응답을 수 초 간격으로 폴링하는데,
    # 본문까지 담으면 같은 데이터를 반복 전송한다(실측 737KB × 폴링 횟수).
    # 완료된 키만 알려주고, 화면이 새로 생긴 키만 개별 조회한다.
    return Response(200, {
        "job_id": job.job_id,
        "company": job.company,
        "status": job.status,
        "finished": finished,
        "total": total,
        "failed": [
            {"key": i.key, "error": i.error} for i in job.items if i.status == "failed"
        ],
        "section_keys": [
            i.key for i in job.items if i.status == "done" and i.result is not None
        ],
    })


def _section(deps: Deps, user_id: str, job_id: str, key: str) -> Response:
    """완료된 섹션 하나를 돌려준다.

    미완료 섹션은 404다 — 부분 결과를 완성된 것처럼 보이게 하면 안 된다.
    """
    job = deps.store.load(job_id, user_id=user_id)
    if job is None:
        return Response.error(404, "작업을 찾을 수 없습니다")

    for item in job.items:
        if item.key == key and item.status == "done" and item.result is not None:
            return Response(200, {"key": key, "value": item.result.get("value")})
    return Response.error(404, "섹션을 찾을 수 없습니다")


def _disclosure(request: Request, deps: Deps, rcept_no: str) -> Response:
    """공시 원문. 우측 패널이 클릭 시 호출한다(3단 로딩).

    작업에 묶지 않는다 — 공시는 공개 데이터라 소유권 개념이 없고, 작업에
    묶으면 화면이 "이 공시가 어느 작업에서 왔는지"를 추적해야 한다.
    """
    api_key = _dart_key(request)
    if not api_key:
        return Response.error(400, "X-DART-Key 헤더가 필요합니다")

    try:
        result = fetch_disclosure_full(rcept_no, api_key) or {}
    except Exception:
        # DART 쪽 실패를 500으로 보고하면 우리 버그로 오해된다.
        # (core는 내부에서 예외를 삼키므로 실제로는 아래 files 분기가
        # 주로 이 역할을 한다 — 이 except는 방어적으로 남겨둔다.)
        return Response.error(502, _DART_FETCH_FAILED_MSG)

    # fetch_disclosure_full은 실패를 예외로 던지지 않고 빈 결과 dict로
    # 삼킨다(core 원칙). "ZIP 자체를 못 받음"과 "문서는 받았으나 본문이
    # 비어 있음"이 똑같이 text=""로 내려오면, DART 키 오류·네트워크
    # 장애·DART 5xx·ZIP 안전검증 거부가 전부 "공시가 없다"는 404로
    # 잘못 표시된다 — 화면이 장애를 "없는 공시"로 오인시키게 된다.
    #
    # 구분 기준: ZIP을 아예 못 받은 경우 core는 `files=[]`인 완전한 빈
    # dict(`empty`)를 그대로 반환한다. ZIP을 받았다면(문서가 없거나
    # 본문이 비어 있는 경우조차) `files`에 ZIP 내 파일 목록이 채워진
    # 채로 반환된다. 그래서 `files`가 비어 있는지가 "받았는가"의 신호다.
    if not result.get("files"):
        return Response.error(502, _DART_FETCH_FAILED_MSG)

    text = result.get("text") or ""
    if not text:
        return Response.error(404, "공시 원문을 찾을 수 없습니다")
    return Response(200, {
        "rcept_no": rcept_no,
        "text": text,
        "char_count": result.get("char_count", len(text)),
        "truncated": bool(result.get("truncated")),
    })


_ACTOR_DISCLAIMER = (
    "공개기록에 근거한 사실 표기입니다. 위험 판정이 아니며, 동명이인일 수 "
    "있습니다. status가 auto_matched인 항목은 동명이인 확인이 되지 않았습니다."
)


def _query(request: Request, name: str) -> str:
    """쿼리 파라미터 하나를 읽는다.

    parse_qs가 이미 퍼센트 디코딩을 하므로 unquote를 또 부르면 안 된다 —
    값에 리터럴 `%`가 있으면(`100%증자`) 이중 디코딩으로 손상된다.
    """
    values = parse_qs(urlsplit(request.path).query).get(name) or []
    return values[0].strip() if values else ""


def _actors(request: Request, deps: Deps) -> Response:
    """회사에 등장한 공개기록 행위자.

    실명을 내보내므로 status와 면책을 **항상** 동반한다. 판정·점수는 없다.
    레지스트리는 opt-in이라 미설정 시 빈 목록이 정상이다(500이 아니다).
    """
    company = _query(request, "company")
    if not company:
        return Response.error(400, "company 파라미터가 필요합니다")

    try:
        found = lookup_actors_by_company(company) or []
    except Exception:
        return Response.error(502, "레지스트리를 조회하지 못했습니다")

    return Response(200, {
        "company": company,
        "actors": [
            {
                "name": name,
                # status 기본값은 가장 약한 auto_matched다. 레코드에 status가
                # 없을 때 verified로 보이면 확인 안 된 정보를 확인된 것처럼
                # 표시하게 된다 — 실명을 다루는 이상 이 방향의 오차는
                # 허용할 수 없다.
                "status": (rec or {}).get("status", "auto_matched"),
                "companies": (rec or {}).get("companies", []),
                "evidence": (rec or {}).get("evidence", ""),
            }
            for name, rec in found
        ],
        "disclaimer": _ACTOR_DISCLAIMER,
    })


def _config(deps: Deps) -> Response:
    """브라우저 로그인에 필요한 공개 설정.

    **service_role 키를 절대 담지 않는다.** anon 키는 브라우저 노출을 전제로
    설계된 값이며 RLS가 실제 방어선이다.
    """
    config = deps.config
    return Response(200, {
        "supabase_url": getattr(config, "supabase_url", ""),
        "supabase_anon_key": getattr(config, "supabase_anon_key", ""),
    })


def build_deps() -> Deps:
    """환경변수에서 의존성을 조립한다. Vercel 어댑터가 요청마다 호출한다."""
    from se_server.api.auth import SupabaseAuth
    from se_server.cache import SupabaseCache
    from se_server.config import SEConfig
    from se_server.http_cache import install
    from se_server.jobs.supabase_store import SupabaseJobStore

    config = SEConfig.from_env()
    # DART 응답 캐시를 core 시임에 주입한다(SE-1).
    install(SupabaseCache(config))
    return Deps(store=SupabaseJobStore(config), auth=SupabaseAuth(config), config=config)
