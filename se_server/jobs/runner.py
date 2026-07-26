"""청크 실행기.

Vercel 함수의 실행 시간 상한 때문에 한 요청에서 분석을 끝낼 수 없다.
run_step()은 주어진 시간 예산 안에서 처리 가능한 만큼만 실행하고 상태를
저장한 뒤 반환한다. 호출자는 done이 될 때까지 반복 호출한다.

**예산은 근사치다.** 이미 시작한 항목은 중간에 끊지 않는다 — DART 호출을
중단할 수단이 없고 부분 결과는 쓸모없다. 따라서 실제 소요는
budget_seconds + 마지막 항목 소요까지 늘 수 있으므로, 호출자는 예산을
실제 상한보다 낮게 잡아야 한다.

설계: docs/superpowers/specs/2026-07-26-risk-viewer-se-design.md §6.1·§7.3
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Callable

from dart_risk_mcp.core.dart_client import fetch_disclosure_full
from dart_risk_mcp.core.signals import match_signals
from se_server.jobs.model import DONE, FAILED, Job, WorkItem
from se_server.jobs.registry import build_stage1_items, resolve_callable
from se_server.jobs.store import JobStore, new_job_id

# 항목당 최대 시도 횟수. core가 이미 429/5xx를 재시도하므로 여기서는 얕게 잡는다.
MAX_ATTEMPTS = 2

# oversized 항목(내부에서 수십 콜을 도는 함수)을 시작하려면 남아야 하는 예산(초).
# 시작한 항목은 끊을 수 없으므로, 예산이 얼마 안 남았을 때 시작하면 상한을 넘긴다.
OVERSIZED_RESERVE = 20.0

# 오류 메시지에서 지울 자격증명 패턴. 작업 레코드는 공유 저장소에 남는다.
_SECRET_RE = re.compile(r"(crtfc_key|api_key|apikey)=[^\s&'\"]+", re.IGNORECASE)


@dataclass
class StepResult:
    done: bool
    processed: int
    finished: int
    total: int


def create_job(company: str, corp_code: str, lookback_years: int, store: JobStore) -> Job:
    """1단 항목으로 채운 새 작업을 만들어 저장한다."""
    job = Job(
        job_id=new_job_id(),
        company=company,
        corp_code=corp_code,
        lookback_years=lookback_years,
        items=build_stage1_items(corp_code, lookback_years),
    )
    store.save(job)
    return job


def _scrub(message: str) -> str:
    """오류 메시지에서 자격증명을 지운다."""
    return _SECRET_RE.sub(r"\1=***", message)


def _is_oversized(item: WorkItem) -> bool:
    from se_server.jobs.registry import STAGE1_SPECS

    for spec in STAGE1_SPECS:
        if spec.key == item.key:
            return spec.oversized
    return False


def _execute(item: WorkItem, api_key: str) -> dict:
    """항목 하나를 실행하고 결과를 dict로 감싼다.

    core 함수의 반환 타입은 list·dict·set 등 제각각이라, JSON 직렬화가
    가능한 형태로 통일해 {"value": ...}에 담는다.
    """
    if item.stage == 2:
        value = fetch_disclosure_full(item.params["rcept_no"], api_key)
    else:
        func: Callable = resolve_callable(item.kind)
        value = func(api_key=api_key, **item.params)
    return {"value": _jsonable(value)}


def _jsonable(value):
    """set 등 JSON으로 직렬화되지 않는 타입을 변환한다."""
    if isinstance(value, set):
        return sorted(value)
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def expand_stage2(job: Job) -> int:
    """1단의 공시 목록에서 신호 매칭 공시를 골라 2단 항목을 추가한다.

    2단 대상은 1단이 끝나야 알 수 있으므로 작업 계획을 미리 다 만들 수 없다.
    이미 확장했으면 아무것도 하지 않는다(멱등).

    **완료 표시 규칙:** 1단에 남은 항목이 있으면 아직 확장할 때가 아니므로
    표시하지 않는다. 1단이 끝났다면 공시 결과가 없거나(조회 실패) 비어 있어도
    확장 패스는 수행된 것이므로 표시한다 — 표시하지 않으면 추가할 항목이
    없는데도 job.status가 영원히 "running"에 머물러 호출자가 무한 루프에 빠진다.

    반환: 추가된 항목 수.
    """
    if job.stage2_expanded:
        return 0
    if job.pending_items():
        # 1단이 아직 진행 중이다. 공시 목록이 확정되지 않았다.
        return 0

    disclosures = None
    for item in job.items:
        if item.key == "disclosures" and item.status == DONE and item.result:
            disclosures = item.result.get("value")
            break
    if disclosures is None:
        # 공시 조회가 실패했거나 항목 자체가 없다. 추가할 2단 항목은 없지만
        # 확장 패스는 끝났으므로 표시해야 작업이 완료될 수 있다.
        job.stage2_expanded = True
        return 0

    existing = {i.params.get("rcept_no") for i in job.items if i.stage == 2}
    added = 0
    for row in disclosures:
        rcept_no = (row or {}).get("rcept_no")
        if not rcept_no or rcept_no in existing:
            continue
        if not match_signals(row.get("report_nm", "")):
            continue
        job.items.append(WorkItem(
            key=f"doc:{rcept_no}",
            stage=2,
            kind="fetch_disclosure_full",
            params={"rcept_no": rcept_no},
        ))
        existing.add(rcept_no)
        added += 1

    job.stage2_expanded = True
    return added


def run_step(
    job_id: str,
    api_key: str,
    store: JobStore,
    budget_seconds: float = 45.0,
    now: Callable[[], float] = time.monotonic,
) -> StepResult:
    """예산 안에서 처리 가능한 만큼 항목을 실행하고 상태를 저장한다."""
    job = store.load(job_id)
    if job is None:
        raise ValueError(f"작업을 찾을 수 없습니다: {job_id}")

    started = now()
    processed = 0

    while True:
        # 1단이 모두 끝났으면 2단 항목을 확장한다.
        if not job.pending_items() and not job.stage2_expanded:
            expand_stage2(job)

        pending = job.pending_items()
        if not pending:
            break

        item = pending[0]
        elapsed = now() - started
        remaining = budget_seconds - elapsed
        if remaining <= 0:
            break
        if _is_oversized(item) and remaining < OVERSIZED_RESERVE:
            break

        item.attempts += 1
        try:
            item.result = _execute(item, api_key)
            item.status = DONE
            item.error = ""
        except Exception as exc:  # noqa: BLE001 — 한 항목의 실패가 작업을 멈추면 안 된다
            item.error = _scrub(str(exc))
            if item.attempts >= MAX_ATTEMPTS:
                item.status = FAILED
        processed += 1

    if not job.pending_items() and job.stage2_expanded:
        job.status = "done"
    store.save(job)

    finished, total = job.progress()
    return StepResult(
        done=job.status == "done",
        processed=processed,
        finished=finished,
        total=total,
    )
