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

# 중간 저장 간격(초). 함수가 죽어도 이 간격만큼만 유실된다. 매 항목마다
# 저장하면 state가 커질수록 페이로드가 O(n²)이 되므로 시간으로 조절한다.
SAVE_INTERVAL = 5.0

# 오류 메시지에서 지울 자격증명 패턴. 작업 레코드는 공유 저장소에 남는다.
_SECRET_RE = re.compile(r"(crtfc_key|api_key|apikey)=[^\s&'\"]+", re.IGNORECASE)

# 2단 확장의 입력이 되는 1단 항목 키. registry.STAGE1_SPECS와 반드시 일치해야
# 하며, 어긋나면 2단이 통째로 조용히 비활성화된다(테스트가 이를 고정한다).
DISCLOSURES_KEY = "disclosures"

# 이보다 짧은 api_key는 오류 메시지에서 치환하지 않는다. 실제 DART 키는 40자이며,
# 한 글자짜리 값을 치환하면 메시지의 무관한 문자까지 지워 진단이 불가능해진다.
_MIN_SCRUB_LEN = 8


@dataclass
class StepResult:
    """한 단계 실행 결과.

    stalled=True는 **이 단계에서 아무 항목도 처리하지 못한 채 끝났다**는
    뜻이다(processed == 0 and not done). 남은 항목이 전부 oversized인데
    예산이 OVERSIZED_RESERVE보다 작은 경우뿐 아니라, budget_seconds가
    0 이하로 넘어와 첫 항목을 시작하기도 전에 예산이 소진된 경우도
    포함한다 — 원인을 구분하지 않는다. 이 신호가 없으면 호출자는
    "예산 소진(진행 중)"과 "영구 정지"를 구분할 수 없어 같은 예산으로
    무한 반복하게 된다.

    호출자는 stalled를 만나면 예산을 올리거나 작업을 실패로 처리해야 한다.
    실행기가 예산을 무시하고 강제 실행하지 않는 이유: Vercel 상한을 넘기면
    함수가 항목 도중에 죽어 save()조차 실행되지 않고, attempts도 남지 않아
    오히려 진짜 무한 루프가 된다.
    """

    done: bool
    processed: int
    finished: int
    total: int
    stalled: bool = False


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


def _scrub(message: str, api_key: str = "") -> str:
    """오류 메시지에서 자격증명을 지운다.

    정규식만으로는 부족하다 — `{"crtfc_key": "V"}`(콜론), `crtfc_key="V"`
    (따옴표), `crtfc_key = V`(공백), URL 경로에 박힌 값, 파라미터명 없이
    노출된 값을 모두 놓친다. 실제 키 문자열을 알고 있으므로 그것을 직접
    치환하는 것이 가장 확실하다. 정규식은 다른 사용자의 키나 형태 변형을
    잡는 보조 수단으로 남긴다.
    """
    scrubbed = message
    # 너무 짧은 키는 치환하지 않는다 — "1" 같은 값이면 메시지의 숫자를
    # 전부 지워 진단 정보가 사라진다. 실제 DART 키는 40자다.
    if len(api_key) >= _MIN_SCRUB_LEN:
        scrubbed = scrubbed.replace(api_key, "***")
    return _SECRET_RE.sub(r"\1=***", scrubbed)


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
    # 반환값도 스크럽한다. core의 일부 함수는 실패를 예외가 아니라
    # {"error": "DART 조회 실패: <요청 URL 전체>"} 같은 **값**으로 돌려주며,
    # 그 URL에는 crtfc_key가 박혀 있다. 작업 레코드는 공유 저장소에 남으므로
    # error 필드만 스크럽해서는 부족하다.
    return {"value": _scrub_values(_jsonable(value), api_key)}


def _scrub_values(value, api_key: str):
    """중첩 구조 안의 모든 문자열에서 자격증명을 지운다."""
    if isinstance(value, str):
        return _scrub(value, api_key)
    if isinstance(value, dict):
        return {k: _scrub_values(v, api_key) for k, v in value.items()}
    if isinstance(value, list):
        return [_scrub_values(v, api_key) for v in value]
    return value


def _jsonable(value):
    """JSON으로 직렬화되지 않는 타입을 변환한다.

    core 함수는 반환 타입이 제각각이라(list·dict·set) 통일이 필요하다.
    특히 fetch_executive_roster는 dict[str, set[str]]을 돌려준다.

    저장소(JSONB)에 넣기 직전에 터지면 진행이 통째로 유실되므로, 알 수 없는
    타입은 예외를 던지는 대신 str()로 낮춘다 — 데이터 형태가 조금 나빠지는
    것이 작업 전체를 잃는 것보다 낫다.
    """
    if isinstance(value, (set, frozenset)):
        return sorted(_jsonable(v) for v in value)
    if isinstance(value, dict):
        # JSON 객체 키는 문자열이어야 한다. tuple 키 등은 str로 낮춘다.
        return {
            k if isinstance(k, str) else str(k): _jsonable(v)
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def expand_stage2(job: Job) -> int:
    """1단의 공시 목록에서 신호 매칭 공시를 골라 2단 항목을 추가한다.

    2단 대상은 1단이 끝나야 알 수 있으므로 작업 계획을 미리 다 만들 수 없다.
    이미 확장했으면 아무것도 하지 않는다(멱등).

    **완료 표시 규칙:** 남은 항목이 있으면 아직 확장할 때가 아니므로
    표시하지 않는다(이 함수는 1단만 있는 시점에 호출되므로 실질적으로
    "1단이 진행 중"과 같다). 남은 항목이 없다면 공시 결과가 없거나(조회 실패)
    비어 있어도 확장 패스는 수행된 것이므로 표시한다 — 표시하지 않으면
    추가할 항목이 없는데도 job.status가 영원히 "running"에 머물러 호출자가
    무한 루프에 빠진다.

    반환: 추가된 항목 수.
    """
    if job.stage2_expanded:
        return 0
    if job.pending_items():
        # 아직 처리할 항목이 남았다. 공시 목록이 확정되지 않았다.
        return 0

    disclosures = None
    for item in job.items:
        if item.key == DISCLOSURES_KEY and item.status == DONE and item.result:
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
    save_interval_seconds: float = SAVE_INTERVAL,
) -> StepResult:
    """예산 안에서 처리 가능한 만큼 항목을 실행하고 상태를 저장한다.

    budget_seconds가 OVERSIZED_RESERVE 이하이고 대기 중인 oversized 항목이
    있으면 ValueError를 던진다. remaining = budget_seconds - elapsed이고
    elapsed는 첫 now() 측정부터 항상 0보다 크므로, 이 조건에서는
    remaining < OVERSIZED_RESERVE가 **항상** 참이 되어 oversized 항목을
    절대 시작할 수 없다 — 조용히 고착되게 두는 대신 설정 오류로 즉시
    알린다. oversized 항목이 남아있지 않다면 작은 예산도 정상 동작한다.

    라이브 실측: `--budget 20`(=OVERSIZED_RESERVE)으로 셀트리온 1년 분석을
    돌리자 13개 항목 중 작은 7개만 처리되고 oversized 6개는 영원히
    시작되지 못한 채 영구 고착됐다.
    """
    job = store.load(job_id)
    if job is None:
        raise ValueError(f"작업을 찾을 수 없습니다: {job_id}")

    if budget_seconds <= OVERSIZED_RESERVE and any(
        _is_oversized(i) for i in job.pending_items()
    ):
        pending_oversized = [i for i in job.pending_items() if _is_oversized(i)]
        keys = ", ".join(sorted(i.key for i in pending_oversized))
        raise ValueError(
            f"budget_seconds={budget_seconds:.1f}초가 OVERSIZED_RESERVE="
            f"{OVERSIZED_RESERVE:.1f}초 이하입니다. remaining = budget_seconds - "
            "elapsed이고 elapsed는 항상 0보다 크므로, 이 예산으로는 대기 중인 "
            f"oversized 항목({keys})을 영원히 시작할 수 없습니다. "
            "budget_seconds를 OVERSIZED_RESERVE보다 크게 설정하세요."
        )

    started = now()
    last_saved = started
    processed = 0

    while True:
        # 1단이 모두 끝났으면 2단 항목을 확장한다.
        if not job.pending_items() and not job.stage2_expanded:
            expand_stage2(job)

        pending = job.pending_items()
        if not pending:
            break

        elapsed = now() - started
        remaining = budget_seconds - elapsed
        if remaining <= 0:
            break

        # 남은 예산으로 시작할 수 있는 첫 항목을 고른다. 목록 순서를 그대로
        # 따르면(pending[0] 고정) 앞에 놓인 oversized 항목 하나가 뒤의 작은
        # 항목 전부를 막는다(head-of-line 블로킹) — 예산이 작은 환경에서는
        # 실행 가능한 항목이 많이 남았는데도 작업이 통째로 멈춘다.
        item = None
        for candidate in pending:
            if _is_oversized(candidate) and remaining < OVERSIZED_RESERVE:
                continue
            item = candidate
            break

        if item is None:
            # 남은 항목이 전부 oversized인데 예산이 부족하다. 더 처리할 수
            # 없으므로 나간다 — stalled 여부는 반환 직전에 processed/done만
            # 보고 판정한다(아래 참고).
            break

        item.attempts += 1
        try:
            item.result = _execute(item, api_key)
            item.status = DONE
            item.error = ""
        except Exception as exc:  # noqa: BLE001 — 한 항목의 실패가 작업을 멈추면 안 된다
            item.error = _scrub(str(exc), api_key)
            if item.attempts >= MAX_ATTEMPTS:
                item.status = FAILED
        processed += 1

        # 중간 저장. 루프 끝에서 한 번만 저장하면, Vercel이 마지막 항목의
        # 예산 초과분에서 함수를 죽였을 때 그 단계의 결과가 **전부** 유실되고
        # attempts조차 남지 않아 같은 지점에서 영구 반복한다.
        # 매 항목마다 전량 upsert하면 state가 커질수록 페이로드가 O(n²)이 되므로
        # 시간 간격으로 조절한다.
        if now() - last_saved >= save_interval_seconds:
            store.save(job)
            last_saved = now()

    if not job.pending_items() and job.stage2_expanded:
        job.status = "done"
    store.save(job)

    finished, total = job.progress()
    done = job.status == "done"
    return StepResult(
        done=done,
        processed=processed,
        finished=finished,
        total=total,
        # 아무것도 처리하지 못한 채 끝났다면(oversized 예약분 부족이든,
        # budget_seconds<=0이든) 이 예산으로는 진행이 불가능하다는 뜻이다.
        # 사유를 구분하지 않는다 — 호출자의 대응은 어느 쪽이든 "예산을
        # 올리거나 실패 처리"로 같고, 구분하려 들면 budget<=0처럼 신호가
        # 빠지는 구멍이 생긴다.
        stalled=processed == 0 and not done,
    )
