"""엔드포인트 로직.

프레임워크를 모른다 — Request를 받아 Response를 돌려주는 순수 함수다.
Vercel 어댑터가 변환을 담당한다.

인증은 **어떤 데이터 경로보다 먼저** 통과해야 한다. 인증 실패 시 저장소를
건드리지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass

from dart_risk_mcp.core.dart_client import resolve_corp
from se_server.api.auth import AuthError, extract_bearer
from se_server.api.router import match
from se_server.api.types import Request, Response
from se_server.jobs import runner
from se_server.jobs.store import JobStore

# Vercel 상한보다 충분히 작고 OVERSIZED_RESERVE(20)보다 큰 값.
_DEFAULT_BUDGET = 25.0

_MIN_YEARS = 1
_MAX_YEARS = 5


@dataclass
class Deps:
    store: JobStore
    auth: object  # SupabaseAuth 또는 verify(bearer) -> user_id 를 만족하는 것
    budget_seconds: float = _DEFAULT_BUDGET


def handle(request: Request, deps: Deps) -> Response:
    """요청 하나를 처리한다."""
    route = match(request.method, request.path)
    if route is None:
        return Response.error(404, "존재하지 않는 경로입니다")
    name, path_vars = route

    # 인증이 먼저다. 실패하면 저장소·DART 어디에도 닿지 않는다.
    try:
        user_id = deps.auth.verify(extract_bearer(request.header("Authorization")))
    except AuthError as exc:
        return Response.error(exc.status, exc.message)

    if name == "create":
        return _create(request, deps, user_id)
    if name == "step":
        return _step(request, deps, user_id, path_vars["job_id"])
    return _get(deps, user_id, path_vars["job_id"])


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


def _create(request: Request, deps: Deps, user_id: str) -> Response:
    company = str(request.body.get("company") or "").strip()
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
        _clamp_years(request.body.get("lookback_years", 1)),
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
    except ValueError as exc:
        return Response.error(400, str(exc))

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
    # 섹션별로 완료된 항목만 노출한다. 아직 안 끝난 항목은 넣지 않는다 —
    # 부분 결과를 완성된 것처럼 보이게 하면 안 된다.
    sections: dict[str, dict] = {}
    for item in job.items:
        if item.status != "done" or item.result is None:
            continue
        sections[item.key] = item.result.get("value")

    return Response(200, {
        "job_id": job.job_id,
        "company": job.company,
        "status": job.status,
        "finished": finished,
        "total": total,
        "failed": [
            {"key": i.key, "error": i.error} for i in job.items if i.status == "failed"
        ],
        "sections": sections,
    })
