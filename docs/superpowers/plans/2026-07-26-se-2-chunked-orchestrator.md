# SE-2: 청크 오케스트레이터 + 작업 상태 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 회사명 하나를 받아 SE 화면이 필요로 하는 분석 데이터 전체를 **중단·재개 가능한 청크 단위로** 수집하고, 진행 상태를 외부 저장소에 남긴다.

**Architecture:** 작업을 `WorkItem`(DART 호출 1건 또는 원문 1건) 목록으로 쪼개 `Job`에 담는다. `run_step()`은 **시간 예산 안에서 처리 가능한 만큼만** 실행하고 상태를 저장한 뒤 반환하므로, Vercel 함수의 실행 시간 상한을 넘지 않는다. 1단(구조화 API)이 끝나면 그 결과에서 **2단 항목(원문 조회)을 동적으로 확장**한다. HTTP 서버·인증·화면은 이 계획의 범위가 아니며, 산출물은 CLI로 단독 검증한다.

**Tech Stack:** Python 3.11+, `requests`(기존 의존성), Supabase PostgREST(REST 직접 호출, SDK 없음), `unittest`(기존 테스트 관행)

## Global Constraints

- `dart_risk_mcp/` core를 **수정하지 않는다.** SE-1이 추가한 `set_http_cache` 시임과 기존 공개 함수만 사용한다.
- 의존 방향은 `se_server` → `core` **단방향**이다. core는 `se_server`를 참조하지 않는다.
- 새 서드파티 의존성을 추가하지 않는다. 표준 라이브러리 + 기존 `requests`만 쓴다. **`supabase-py`·`gotrue`·`postgrest`·`storage3` 금지** — Supabase는 REST로 직접 호출한다.
- **DART API 키를 저장하지 않는다.** 키는 호출 인자로만 흐르며, 작업 레코드·로그·오류 메시지 어디에도 남기지 않는다. 작업 레코드는 여러 사용자가 공유할 수 있으므로 이 규칙이 특히 중요하다.
- **점수·등급을 만들지 않는다** (v0.8.5 원칙). 이 계층은 사실 데이터만 수집·보관하며 위험도를 정량화하지 않는다.
- **한 항목의 실패가 작업 전체를 중단시키지 않는다.** 실패는 해당 항목에만 기록하고 나머지는 계속 진행한다 (설계 §8 섹션 단위 격리).
- 시간 예산은 **주입 가능**해야 한다. Vercel 플랜별 `maxDuration`이 다르므로 상수로 박지 않는다.
- 테스트는 기존 관행을 따른다: `unittest.TestCase` 클래스, `tests/` 하위, **네트워크 호출 없음**(전부 스텁).
- 주석·docstring은 **한국어**.

---

## 설계 결정

### 왜 작업 계획을 미리 다 만들지 않는가

2단(원문 조회) 대상은 **1단이 끝나야 알 수 있다** — 어떤 공시가 신호에 매칭되는지는 공시 목록을 받아봐야 정해진다. 따라서 작업은 정적 목록이 아니라 **단계별로 확장되는** 구조여야 한다. `expand_stage2()`가 이 확장을 담당한다.

### 왜 항목 단위가 "DART 호출 1건"인가

더 굵게 잡으면(예: 섹션 단위) 한 항목이 시간 예산을 넘겨 영원히 완료되지 못하는 항목이 생긴다. 더 잘게 잡을 수는 없다 — DART 호출은 원자적이다. 다만 `fetch_insider_timeline`처럼 **내부에서 수십 콜을 도는 core 함수**는 하나의 항목이며, 이 경우 예산 초과가 가능하다. 이를 §Task 2의 `oversized` 처리로 다룬다.

### 시간 예산 처리

`run_step(budget_seconds)`는 **항목을 시작하기 전에** 남은 예산을 확인한다. 이미 시작한 항목은 중간에 끊지 않는다(DART 호출을 중단할 수단이 없고, 부분 결과는 쓸모없다). 따라서 실제 소요는 `budget_seconds + 마지막 항목 소요`까지 늘 수 있다. 호출자는 이를 감안해 예산을 실제 상한보다 낮게 잡아야 한다.

---

## File Structure

| 파일 | 책임 |
|---|---|
| `se_server/jobs/__init__.py` | 서브패키지 공개 API |
| `se_server/jobs/model.py` | `WorkItem`·`Job` 자료구조와 직렬화 |
| `se_server/jobs/registry.py` | 1단 항목 정의(어떤 core 함수를 어떤 인자로 부를지) |
| `se_server/jobs/store.py` | `JobStore` 프로토콜 + `MemoryJobStore` |
| `se_server/jobs/supabase_store.py` | `SupabaseJobStore` (PostgREST) |
| `se_server/jobs/runner.py` | `run_step()` 실행기 + 2단 확장 |
| `se_server/jobs/schema.sql` | 작업 테이블 |
| `tests/se/test_job_model.py` | 자료구조·직렬화 |
| `tests/se/test_job_registry.py` | 1단 항목 정의 |
| `tests/se/test_job_store.py` | `MemoryJobStore` |
| `tests/se/test_job_runner.py` | 예산·재개·실패 격리·2단 확장 |
| `tests/se/test_supabase_job_store.py` | PostgREST 계약 (요청 스텁) |
| `scripts/se_analyze.py` | 작업 실행 CLI (중단·재개 실측) |

`model`·`registry`·`store`·`runner`를 나눈 이유: 실행기 테스트가 저장소나 DART를 끌고 오지 않아야 하고, 항목 정의(데이터)와 실행 규칙(로직)이 섞이면 새 섹션을 추가할 때마다 실행기를 고치게 된다.

---

### Task 1: 작업 자료구조와 직렬화

**Files:**
- Create: `se_server/jobs/__init__.py`
- Create: `se_server/jobs/model.py`
- Test: `tests/se/test_job_model.py`

**Interfaces:**
- Consumes: 없음
- Produces:
  - `se_server.jobs.model.WorkItem` — `dataclass`. 필드: `key: str`, `stage: int`, `kind: str`, `params: dict`, `status: str`(`"pending"`|`"done"`|`"failed"`), `result: dict | None`, `error: str`, `attempts: int`
  - `se_server.jobs.model.Job` — `dataclass`. 필드: `job_id: str`, `company: str`, `corp_code: str`, `lookback_years: int`, `items: list[WorkItem]`, `status: str`(`"running"`|`"done"`), `stage2_expanded: bool`
  - `Job.to_dict() -> dict` / `Job.from_dict(data: dict) -> Job`
  - `Job.pending_items() -> list[WorkItem]`
  - `Job.progress() -> tuple[int, int]` — `(완료+실패, 전체)`
  - `WorkItem.to_dict()` / `WorkItem.from_dict()`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/se/test_job_model.py`:

```python
"""작업 자료구조와 직렬화."""
import json
import unittest

from se_server.jobs.model import Job, WorkItem


def _item(key, stage=1, status="pending"):
    return WorkItem(key=key, stage=stage, kind="fetch", params={"a": 1}, status=status)


class TestWorkItem(unittest.TestCase):
    def test_defaults(self):
        item = WorkItem(key="k", stage=1, kind="fetch", params={})
        self.assertEqual(item.status, "pending")
        self.assertIsNone(item.result)
        self.assertEqual(item.error, "")
        self.assertEqual(item.attempts, 0)

    def test_roundtrip(self):
        item = WorkItem(key="k", stage=2, kind="doc", params={"rcept_no": "1"},
                        status="done", result={"text": "x"}, attempts=2)
        restored = WorkItem.from_dict(item.to_dict())
        self.assertEqual(restored, item)

    def test_roundtrip_preserves_error(self):
        item = WorkItem(key="k", stage=1, kind="fetch", params={},
                        status="failed", error="타임아웃", attempts=3)
        self.assertEqual(WorkItem.from_dict(item.to_dict()).error, "타임아웃")


class TestJob(unittest.TestCase):
    def test_pending_items_excludes_done_and_failed(self):
        job = Job(job_id="j1", company="테스트", corp_code="0", lookback_years=1,
                  items=[_item("a"), _item("b", status="done"), _item("c", status="failed")])
        self.assertEqual([i.key for i in job.pending_items()], ["a"])

    def test_progress_counts_done_and_failed(self):
        job = Job(job_id="j1", company="테스트", corp_code="0", lookback_years=1,
                  items=[_item("a"), _item("b", status="done"), _item("c", status="failed")])
        self.assertEqual(job.progress(), (2, 3))

    def test_progress_on_empty_job(self):
        job = Job(job_id="j1", company="테스트", corp_code="0", lookback_years=1, items=[])
        self.assertEqual(job.progress(), (0, 0))

    def test_roundtrip(self):
        job = Job(job_id="j1", company="셀트리온", corp_code="00421045",
                  lookback_years=3, items=[_item("a"), _item("b", stage=2)],
                  status="running", stage2_expanded=True)
        restored = Job.from_dict(job.to_dict())
        self.assertEqual(restored, job)

    def test_to_dict_is_json_serializable(self):
        """저장소가 JSONB로 넣으므로 순수 JSON 타입만 담겨야 한다."""
        job = Job(job_id="j1", company="테스트", corp_code="0", lookback_years=1,
                  items=[_item("a")])
        json.dumps(job.to_dict())  # 예외가 나면 실패

    def test_dict_does_not_carry_api_key(self):
        """작업 레코드는 공유 저장소에 남으므로 DART 키가 섞이면 안 된다."""
        job = Job(job_id="j1", company="테스트", corp_code="0", lookback_years=1,
                  items=[_item("a")])
        self.assertNotIn("crtfc_key", json.dumps(job.to_dict()))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `python -m pytest tests/se/test_job_model.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'se_server.jobs'`

- [ ] **Step 3: 구현**

`se_server/jobs/__init__.py`:

```python
"""SE 작업(job) 계층 — 청크 실행과 상태 보관."""
from se_server.jobs.model import Job, WorkItem

__all__ = ["Job", "WorkItem"]
```

`se_server/jobs/model.py`:

```python
"""작업 자료구조.

Vercel 함수는 실행 시간 상한이 있어 한 요청에서 분석을 끝낼 수 없다.
작업을 WorkItem 단위로 쪼개 상태를 외부에 남기고, 여러 번의 함수 호출에
나눠 실행한다.

항목 단위는 "DART 호출 1건"이다. 더 굵게 잡으면 한 항목이 시간 예산을
넘겨 영원히 끝나지 않는 항목이 생긴다.

설계: docs/superpowers/specs/2026-07-26-risk-viewer-se-design.md §6.1·§7.3
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

# 항목 상태
PENDING = "pending"
DONE = "done"
FAILED = "failed"


@dataclass
class WorkItem:
    """작업 하나. DART 호출 1건 또는 원문 1건에 대응한다.

    params에는 corp_code·연도·rcept_no 같은 조회 조건만 담는다.
    DART API 키는 절대 담지 않는다 — 작업 레코드는 공유 저장소에 남는다.
    """

    key: str
    stage: int
    kind: str
    params: dict = field(default_factory=dict)
    status: str = PENDING
    result: dict | None = None
    error: str = ""
    attempts: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "WorkItem":
        return cls(
            key=data["key"],
            stage=int(data["stage"]),
            kind=data["kind"],
            params=data.get("params") or {},
            status=data.get("status", PENDING),
            result=data.get("result"),
            error=data.get("error", ""),
            attempts=int(data.get("attempts", 0)),
        )


@dataclass
class Job:
    """회사 하나에 대한 분석 작업."""

    job_id: str
    company: str
    corp_code: str
    lookback_years: int
    items: list[WorkItem] = field(default_factory=list)
    status: str = "running"
    stage2_expanded: bool = False

    def pending_items(self) -> list[WorkItem]:
        return [i for i in self.items if i.status == PENDING]

    def progress(self) -> tuple[int, int]:
        """(끝난 항목 수, 전체 항목 수). 실패도 '끝난' 것으로 센다."""
        finished = sum(1 for i in self.items if i.status in (DONE, FAILED))
        return finished, len(self.items)

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "company": self.company,
            "corp_code": self.corp_code,
            "lookback_years": self.lookback_years,
            "items": [i.to_dict() for i in self.items],
            "status": self.status,
            "stage2_expanded": self.stage2_expanded,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Job":
        return cls(
            job_id=data["job_id"],
            company=data["company"],
            corp_code=data["corp_code"],
            lookback_years=int(data["lookback_years"]),
            items=[WorkItem.from_dict(d) for d in data.get("items") or []],
            status=data.get("status", "running"),
            stage2_expanded=bool(data.get("stage2_expanded", False)),
        )
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest tests/se/test_job_model.py -v`
Expected: PASS — 9 passed

- [ ] **Step 5: 커밋**

```bash
git add se_server/jobs/ tests/se/test_job_model.py
git commit -m "feat(se): 작업 자료구조(WorkItem·Job)와 직렬화"
```

---

### Task 2: 1단 항목 정의(registry)

1단은 구조화 API만 호출한다. 어떤 core 함수를 어떤 인자로 부를지를 **데이터로** 선언해, 섹션을 추가할 때 실행기를 고치지 않아도 되게 한다.

**Files:**
- Create: `se_server/jobs/registry.py`
- Test: `tests/se/test_job_registry.py`

**Interfaces:**
- Consumes: `se_server.jobs.model.WorkItem` (Task 1)
- Produces:
  - `se_server.jobs.registry.STAGE1_SPECS: tuple[Stage1Spec, ...]`
  - `se_server.jobs.registry.Stage1Spec` — `dataclass(frozen=True)`. 필드: `key: str`, `section: str`, `func_name: str`, `param_names: tuple[str, ...]`, `oversized: bool`
  - `se_server.jobs.registry.build_stage1_items(corp_code: str, lookback_years: int) -> list[WorkItem]`
  - `se_server.jobs.registry.resolve_callable(func_name: str) -> Callable` — 이름 → core 함수. 미등록 이름은 `KeyError`

`oversized=True`는 **내부에서 수십 콜을 도는 함수**(`fetch_insider_timeline` 등)를 뜻한다. 실행기는 이런 항목을 예산이 넉넉할 때만 시작한다(§Task 4).

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/se/test_job_registry.py`:

```python
"""1단 항목 정의."""
import unittest

from se_server.jobs.registry import (
    STAGE1_SPECS,
    build_stage1_items,
    resolve_callable,
)


class TestSpecs(unittest.TestCase):
    def test_keys_are_unique(self):
        keys = [s.key for s in STAGE1_SPECS]
        self.assertEqual(len(keys), len(set(keys)))

    def test_every_func_name_resolves(self):
        """등록된 이름이 실제 core 함수와 연결돼야 한다."""
        for spec in STAGE1_SPECS:
            self.assertTrue(callable(resolve_callable(spec.func_name)), spec.func_name)

    def test_every_param_name_is_supported(self):
        """param_names는 실행기가 채울 수 있는 이름이어야 한다."""
        allowed = {"corp_code", "lookback_years", "lookback_days", "year", "bsns_year"}
        for spec in STAGE1_SPECS:
            self.assertTrue(set(spec.param_names) <= allowed, spec.key)

    def test_param_names_match_real_signatures(self):
        """선언한 param_names가 core 함수가 실제로 받는 인자인지 대조한다.

        전역 허용집합만 검사하면 함수마다 다른 인자명을 놓친다 —
        fetch_company_disclosures는 lookback_years가 아니라 lookback_days를
        받는다. 실행기는 func(api_key=api_key, **params)로 호출하므로
        이름이 틀리면 런타임 TypeError가 난다.
        """
        import inspect

        for spec in STAGE1_SPECS:
            accepted = set(inspect.signature(resolve_callable(spec.func_name)).parameters)
            unknown = set(spec.param_names) - accepted
            self.assertFalse(
                unknown,
                f"{spec.key}: {spec.func_name}가 받지 않는 인자 {unknown}",
            )

    def test_required_params_are_all_supplied(self):
        """기본값 없는 필수 인자를 빠뜨리지 않았는지 확인한다.

        api_key는 실행기가 따로 넘기므로 제외한다.
        """
        import inspect

        items = {i.key: i for i in build_stage1_items("00126380", 1)}
        for spec in STAGE1_SPECS:
            sig = inspect.signature(resolve_callable(spec.func_name))
            required = {
                name
                for name, p in sig.parameters.items()
                if p.default is inspect.Parameter.empty
                and p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)
                and name != "api_key"
            }
            missing = required - set(items[spec.key].params)
            self.assertFalse(missing, f"{spec.key}: 필수 인자 누락 {missing}")

    def test_oversized_only_for_year_proportional_functions(self):
        """oversized 기준: 호출 수가 lookback_years에 비례하는 함수만.

        엔드포인트 몇 개를 1회씩 도는 함수는 연수와 무관한 상수 시간이다.
        """
        by_key = {s.key: s for s in STAGE1_SPECS}
        for key in ("fund_usage", "insider_timeline", "executive_roster",
                    "audit_history", "dividends", "disclosures"):
            self.assertTrue(by_key[key].oversized, f"{key}는 oversized여야 한다")
        for key in ("company_info", "affiliates", "financials", "indicators",
                    "shareholders", "debt_balance", "distress"):
            self.assertFalse(by_key[key].oversized, f"{key}는 oversized가 아니어야 한다")

    def test_unknown_func_name_raises(self):
        with self.assertRaises(KeyError):
            resolve_callable("존재하지_않는_함수")

    def test_covers_expected_sections(self):
        """설계 §7.1의 1단 섹션이 모두 대표된다."""
        sections = {s.section for s in STAGE1_SPECS}
        for expected in ("헤더", "자금", "재무", "지배구조", "감사부실"):
            self.assertIn(expected, sections)


class TestBuildStage1Items(unittest.TestCase):
    def test_builds_one_item_per_spec(self):
        items = build_stage1_items("00126380", 3)
        self.assertEqual(len(items), len(STAGE1_SPECS))

    def test_all_items_are_stage1_and_pending(self):
        for item in build_stage1_items("00126380", 3):
            self.assertEqual(item.stage, 1)
            self.assertEqual(item.status, "pending")

    def test_params_are_filled_from_arguments(self):
        items = {i.key: i for i in build_stage1_items("00126380", 3)}
        for item in items.values():
            if "corp_code" in item.params:
                self.assertEqual(item.params["corp_code"], "00126380")
            if "lookback_years" in item.params:
                self.assertEqual(item.params["lookback_years"], 3)

    def test_params_never_contain_api_key(self):
        """작업 레코드는 공유 저장소에 남는다."""
        for item in build_stage1_items("00126380", 3):
            self.assertNotIn("crtfc_key", item.params)
            self.assertNotIn("api_key", item.params)

    def test_lookback_years_is_clamped_to_1_5(self):
        for raw, expected in ((0, 1), (1, 1), (5, 5), (99, 5)):
            items = build_stage1_items("0", raw)
            with_lookback = [i for i in items if "lookback_years" in i.params]
            self.assertTrue(with_lookback)
            self.assertEqual(with_lookback[0].params["lookback_years"], expected)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `python -m pytest tests/se/test_job_registry.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'se_server.jobs.registry'`

- [ ] **Step 3: 구현**

`se_server/jobs/registry.py`:

```python
"""1단(구조화 API) 항목 정의.

어떤 core 함수를 어떤 인자로 부를지를 데이터로 선언한다. 섹션을 추가할 때
실행기(runner)를 고치지 않고 이 표만 늘리면 된다.

여기 있는 함수는 전부 DART 구조화 엔드포인트만 호출하며 원문 ZIP을 열지
않는다. 원문은 2단 소관이다.

함수 이름을 문자열로 두는 이유: 작업 항목이 JSON으로 직렬화돼 저장소를
왕복하므로, 호출 대상을 이름으로 지목할 수 있어야 한다.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from dart_risk_mcp.core import dart_client
from se_server.jobs.model import WorkItem

# 조회 연수 허용 범위 (core 도구들의 관행과 동일)
_MIN_YEARS = 1
_MAX_YEARS = 5


@dataclass(frozen=True)
class Stage1Spec:
    """1단 항목 하나의 정의.

    param_names는 **해당 core 함수가 실제로 받는 키워드 인자 이름**이어야 한다.
    실행기가 `func(api_key=api_key, **item.params)`로 호출하므로, 이름이
    틀리면 런타임 TypeError가 난다. 예: fetch_company_disclosures는
    lookback_years가 아니라 lookback_days(단위도 일)를 받는다.

    oversized=True의 기준: **호출 수가 lookback_years에 비례하는 함수**
    (연도·분기 루프를 도는 것). 이런 항목은 lookback_years=5에서 수십 콜이
    되어 시간 예산을 통째로 넘길 수 있다. 실행기는 예산이 넉넉할 때만
    시작한다 — 한 번 시작하면 중간에 끊을 수 없기 때문이다.
    엔드포인트 몇 개를 1회씩 도는 함수(fetch_distress_events 4개,
    fetch_debt_balance 5개)는 연수와 무관하게 상수 시간이라 해당하지 않는다.
    """

    key: str
    section: str
    func_name: str
    param_names: tuple[str, ...]
    oversized: bool = False


STAGE1_SPECS: tuple[Stage1Spec, ...] = (
    Stage1Spec("company_info", "헤더", "fetch_company_info", ("corp_code",)),
    # 페이지네이션으로 최대 10회 호출한다(max_pages 기본값).
    Stage1Spec("disclosures", "자금", "fetch_company_disclosures",
               ("corp_code", "lookback_days"), oversized=True),
    Stage1Spec("fund_usage", "자금", "fetch_fund_usage",
               ("corp_code", "lookback_years"), oversized=True),
    Stage1Spec("affiliates", "자금", "fetch_affiliate_investments", ("corp_code",)),
    Stage1Spec("financials", "재무", "fetch_financial_statements", ("corp_code",)),
    Stage1Spec("indicators", "재무", "fetch_company_indicators", ("corp_code", "bsns_year")),
    Stage1Spec("shareholders", "지배구조", "fetch_shareholder_status", ("corp_code",)),
    Stage1Spec("insider_timeline", "지배구조", "fetch_insider_timeline",
               ("corp_code", "lookback_years"), oversized=True),
    Stage1Spec("executive_roster", "지배구조", "fetch_executive_roster",
               ("corp_code", "lookback_years"), oversized=True),
    Stage1Spec("audit_history", "감사부실", "fetch_audit_opinion_history",
               ("corp_code", "lookback_years"), oversized=True),
    Stage1Spec("debt_balance", "감사부실", "fetch_debt_balance", ("corp_code",)),
    # 4개 엔드포인트를 1회씩만 호출한다 — 연수와 무관한 상수 시간이라 oversized 아님.
    Stage1Spec("distress", "감사부실", "fetch_distress_events",
               ("corp_code", "lookback_years")),
    Stage1Spec("dividends", "감사부실", "fetch_dividend_history",
               ("corp_code", "lookback_years"), oversized=True),
)

# 문자열 이름 → core 함수. 임의 이름으로 아무 함수나 부를 수 없게 화이트리스트로 둔다.
_CALLABLES: dict[str, Callable] = {
    spec.func_name: getattr(dart_client, spec.func_name) for spec in STAGE1_SPECS
}


def resolve_callable(func_name: str) -> Callable:
    """등록된 함수 이름을 실제 core 함수로 해석한다. 미등록이면 KeyError."""
    return _CALLABLES[func_name]


def _clamp_years(lookback_years: int) -> int:
    return max(_MIN_YEARS, min(_MAX_YEARS, int(lookback_years)))


def build_stage1_items(corp_code: str, lookback_years: int) -> list[WorkItem]:
    """1단 항목 목록을 만든다. DART 호출은 하지 않는다(순수 함수)."""
    years = _clamp_years(lookback_years)
    # 재무지표는 직전 사업연도를 기준으로 조회한다. 진행 중 연도는 미확정이다.
    bsns_year = str(_previous_business_year())

    items: list[WorkItem] = []
    for spec in STAGE1_SPECS:
        params: dict = {}
        for name in spec.param_names:
            if name == "corp_code":
                params["corp_code"] = corp_code
            elif name == "lookback_years":
                params["lookback_years"] = years
            elif name == "lookback_days":
                # fetch_company_disclosures만 일 단위로 받는다.
                params["lookback_days"] = years * 365
            elif name in ("year", "bsns_year"):
                params[name] = bsns_year
            else:  # pragma: no cover - 아래 테스트가 이 경로를 막는다
                raise ValueError(f"채울 수 없는 param 이름: {spec.key}.{name}")
        items.append(WorkItem(key=spec.key, stage=1, kind=spec.func_name, params=params))
    return items


def _previous_business_year() -> int:
    """직전 사업연도. 테스트에서 고정하기 쉽도록 분리해 둔다."""
    import datetime as _dt

    return _dt.date.today().year - 1
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest tests/se/test_job_registry.py -v`
Expected: PASS — 13 passed

- [ ] **Step 5: 커밋**

```bash
git add se_server/jobs/registry.py tests/se/test_job_registry.py
git commit -m "feat(se): 1단 항목 정의 registry — core 함수 화이트리스트"
```

---

### Task 3: 작업 저장소 (인메모리)

**Files:**
- Create: `se_server/jobs/store.py`
- Modify: `se_server/jobs/__init__.py`
- Test: `tests/se/test_job_store.py`

**Interfaces:**
- Consumes: `se_server.jobs.model.Job` (Task 1)
- Produces:
  - `se_server.jobs.store.JobStore` — 프로토콜. `save(job: Job) -> None`, `load(job_id: str) -> Job | None`
  - `se_server.jobs.store.MemoryJobStore` — 위 프로토콜의 인메모리 구현
  - `se_server.jobs.store.new_job_id() -> str` — 충돌 없는 작업 ID

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/se/test_job_store.py`:

```python
"""작업 저장소 기본 동작."""
import unittest

from se_server.jobs.model import Job, WorkItem
from se_server.jobs.store import MemoryJobStore, new_job_id


def _job(job_id="j1"):
    return Job(job_id=job_id, company="테스트", corp_code="0", lookback_years=1,
               items=[WorkItem(key="a", stage=1, kind="fetch", params={})])


class TestMemoryJobStore(unittest.TestCase):
    def test_load_missing_returns_none(self):
        self.assertIsNone(MemoryJobStore().load("없음"))

    def test_save_then_load(self):
        store = MemoryJobStore()
        store.save(_job())
        loaded = store.load("j1")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.company, "테스트")

    def test_save_overwrites(self):
        store = MemoryJobStore()
        store.save(_job())
        job = store.load("j1")
        job.status = "done"
        store.save(job)
        self.assertEqual(store.load("j1").status, "done")

    def test_loaded_job_is_detached_copy(self):
        """저장소가 돌려준 객체를 고쳐도 저장분이 바뀌면 안 된다.

        실제 저장소(Postgres)는 항상 새 객체를 만들어 돌려주므로, 인메모리
        구현이 참조를 공유하면 테스트가 실서비스와 다르게 동작한다.
        """
        store = MemoryJobStore()
        store.save(_job())
        loaded = store.load("j1")
        loaded.status = "오염"
        self.assertEqual(store.load("j1").status, "running")


class TestNewJobId(unittest.TestCase):
    def test_ids_are_unique(self):
        ids = {new_job_id() for _ in range(200)}
        self.assertEqual(len(ids), 200)

    def test_id_is_url_safe(self):
        import re
        self.assertRegex(new_job_id(), r"^[A-Za-z0-9_-]+$")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `python -m pytest tests/se/test_job_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'se_server.jobs.store'`

- [ ] **Step 3: 구현**

`se_server/jobs/store.py`:

```python
"""작업 저장소 인터페이스와 인메모리 구현."""
from __future__ import annotations

import secrets
from typing import Protocol

from se_server.jobs.model import Job


class JobStore(Protocol):
    """작업 상태를 보관하는 저장소가 제공해야 하는 최소 인터페이스."""

    def save(self, job: Job) -> None: ...

    def load(self, job_id: str) -> Job | None: ...


def new_job_id() -> str:
    """URL에 그대로 넣을 수 있는 작업 ID."""
    return secrets.token_urlsafe(12)


class MemoryJobStore:
    """프로세스 메모리 저장소. 테스트와 로컬 개발용.

    Vercel 함수는 요청마다 새 프로세스라 운영에서는 쓸 수 없다.

    저장·조회 모두 dict를 거쳐 복사본을 만든다. 실제 저장소(Postgres)는
    항상 새 객체를 돌려주므로, 참조를 공유하면 테스트가 실서비스와 다르게
    동작해 재개 버그를 놓치게 된다.
    """

    def __init__(self) -> None:
        self._jobs: dict[str, dict] = {}

    def save(self, job: Job) -> None:
        self._jobs[job.job_id] = job.to_dict()

    def load(self, job_id: str) -> Job | None:
        data = self._jobs.get(job_id)
        if data is None:
            return None
        return Job.from_dict(data)
```

`se_server/jobs/__init__.py`를 아래로 교체:

```python
"""SE 작업(job) 계층 — 청크 실행과 상태 보관."""
from se_server.jobs.model import Job, WorkItem
from se_server.jobs.store import JobStore, MemoryJobStore, new_job_id

__all__ = ["Job", "WorkItem", "JobStore", "MemoryJobStore", "new_job_id"]
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest tests/se/test_job_store.py -v`
Expected: PASS — 6 passed

- [ ] **Step 5: 커밋**

```bash
git add se_server/jobs/store.py se_server/jobs/__init__.py tests/se/test_job_store.py
git commit -m "feat(se): 작업 저장소 인터페이스와 인메모리 구현"
```

---

### Task 4: 청크 실행기 + 2단 확장

이 계획의 핵심이다. 시간 예산 안에서 항목을 처리하고, 1단이 끝나면 2단(원문) 항목을 동적으로 확장한다.

**Files:**
- Create: `se_server/jobs/runner.py`
- Test: `tests/se/test_job_runner.py`

**Interfaces:**
- Consumes: Task 1·2·3 전부
- Produces:
  - `se_server.jobs.runner.create_job(company, corp_code, lookback_years, store) -> Job`
  - `se_server.jobs.runner.run_step(job_id, api_key, store, budget_seconds=45.0, now=time.monotonic) -> StepResult`
  - `se_server.jobs.runner.StepResult` — `dataclass`. 필드: `done: bool`, `processed: int`, `finished: int`, `total: int`
  - `se_server.jobs.runner.expand_stage2(job) -> int` — 추가된 항목 수 반환
  - `se_server.jobs.runner.MAX_ATTEMPTS: int` = 2
  - `se_server.jobs.runner.OVERSIZED_RESERVE: float` = 20.0 — oversized 항목을 시작하려면 남아야 하는 최소 예산(초)

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/se/test_job_runner.py`:

```python
"""청크 실행기 — 예산·재개·실패 격리·2단 확장."""
import unittest
from unittest import mock

from se_server.jobs import runner
from se_server.jobs.model import Job, WorkItem
from se_server.jobs.store import MemoryJobStore


class _Clock:
    """호출할 때마다 step초씩 흐르는 가짜 단조 시계."""

    def __init__(self, step=1.0):
        self.t = 0.0
        self.step = step

    def __call__(self):
        value = self.t
        self.t += self.step
        return value


def _job_with(items, **kw):
    return Job(job_id="j1", company="테스트", corp_code="00126380",
               lookback_years=1, items=items, **kw)


def _stage1(key, kind="fetch_company_info"):
    return WorkItem(key=key, stage=1, kind=kind, params={"corp_code": "00126380"})


class TestCreateJob(unittest.TestCase):
    def test_creates_and_saves_stage1_items(self):
        store = MemoryJobStore()
        job = runner.create_job("셀트리온", "00421045", 3, store)
        self.assertTrue(job.items)
        self.assertTrue(all(i.stage == 1 for i in job.items))
        self.assertIsNotNone(store.load(job.job_id))

    def test_job_id_is_unique_per_call(self):
        store = MemoryJobStore()
        a = runner.create_job("A", "1", 1, store)
        b = runner.create_job("B", "2", 1, store)
        self.assertNotEqual(a.job_id, b.job_id)


class TestRunStepBudget(unittest.TestCase):
    def test_stops_when_budget_exhausted(self):
        store = MemoryJobStore()
        job = _job_with([_stage1(f"k{i}") for i in range(10)])
        store.save(job)
        with mock.patch.object(runner, "resolve_callable", return_value=lambda **kw: {"ok": 1}):
            result = runner.run_step("j1", "KEY", store, budget_seconds=3.0, now=_Clock(1.0))
        self.assertFalse(result.done)
        self.assertLess(result.processed, 10)
        self.assertGreater(result.processed, 0)

    def test_resumes_from_saved_state(self):
        """두 번째 호출이 첫 호출이 남긴 항목부터 이어받는다."""
        store = MemoryJobStore()
        store.save(_job_with([_stage1(f"k{i}") for i in range(6)]))
        with mock.patch.object(runner, "resolve_callable", return_value=lambda **kw: {"ok": 1}):
            first = runner.run_step("j1", "KEY", store, budget_seconds=3.0, now=_Clock(1.0))
            second = runner.run_step("j1", "KEY", store, budget_seconds=100.0, now=_Clock(1.0))
        self.assertEqual(first.processed + second.processed, 6)
        self.assertTrue(second.done)

    def test_oversized_item_needs_reserve(self):
        """oversized 항목은 남은 예산이 충분할 때만 시작한다."""
        store = MemoryJobStore()
        item = WorkItem(key="insider_timeline", stage=1, kind="fetch_insider_timeline",
                        params={"corp_code": "0", "lookback_years": 5})
        store.save(_job_with([item]))
        called = []
        with mock.patch.object(runner, "resolve_callable",
                               return_value=lambda **kw: called.append(1) or {"ok": 1}):
            result = runner.run_step("j1", "KEY", store,
                                     budget_seconds=runner.OVERSIZED_RESERVE - 1.0,
                                     now=_Clock(0.0))
        self.assertEqual(called, [])
        self.assertFalse(result.done)

    def test_completed_job_reports_done_without_work(self):
        store = MemoryJobStore()
        store.save(_job_with([_stage1("k0")], status="done", stage2_expanded=True))
        job = store.load("j1")
        job.items[0].status = "done"
        store.save(job)
        with mock.patch.object(runner, "resolve_callable") as resolve:
            result = runner.run_step("j1", "KEY", store, budget_seconds=100.0, now=_Clock(1.0))
        resolve.assert_not_called()
        self.assertTrue(result.done)


class TestFailureIsolation(unittest.TestCase):
    def test_failing_item_does_not_stop_others(self):
        store = MemoryJobStore()
        store.save(_job_with([_stage1("bad"), _stage1("good")]))

        def resolve(name):
            def fn(**kw):
                raise RuntimeError("DART 오류")
            return fn

        with mock.patch.object(runner, "resolve_callable", side_effect=resolve):
            runner.run_step("j1", "KEY", store, budget_seconds=100.0, now=_Clock(0.1))
            runner.run_step("j1", "KEY", store, budget_seconds=100.0, now=_Clock(0.1))
        job = store.load("j1")
        self.assertTrue(all(i.status == "failed" for i in job.items))

    def test_item_retries_up_to_max_attempts(self):
        store = MemoryJobStore()
        store.save(_job_with([_stage1("flaky")]))
        calls = {"n": 0}

        def fn(**kw):
            calls["n"] += 1
            raise RuntimeError("일시 오류")

        with mock.patch.object(runner, "resolve_callable", return_value=fn):
            for _ in range(5):
                runner.run_step("j1", "KEY", store, budget_seconds=100.0, now=_Clock(0.1))
        self.assertEqual(calls["n"], runner.MAX_ATTEMPTS)
        self.assertEqual(store.load("j1").items[0].status, "failed")

    def test_error_message_does_not_leak_api_key(self):
        store = MemoryJobStore()
        store.save(_job_with([_stage1("bad")]))

        def fn(**kw):
            raise RuntimeError("요청 실패: crtfc_key=SECRET_KEY_VALUE")

        with mock.patch.object(runner, "resolve_callable", return_value=fn):
            runner.run_step("j1", "KEY", store, budget_seconds=100.0, now=_Clock(0.1))
        self.assertNotIn("SECRET_KEY_VALUE", store.load("j1").items[0].error)


class TestExpandStage2(unittest.TestCase):
    def _job_with_disclosures(self, disclosures):
        item = _stage1("disclosures", kind="fetch_company_disclosures")
        item.status = "done"
        item.result = {"value": disclosures}
        return _job_with([item])

    def test_adds_items_only_for_signal_matched(self):
        job = self._job_with_disclosures([
            {"rcept_no": "1", "report_nm": "전환사채권 발행결정"},
            {"rcept_no": "2", "report_nm": "임원ㆍ주요주주특정증권등소유상황보고서"},
        ])
        added = runner.expand_stage2(job)
        self.assertEqual(added, 1)
        stage2 = [i for i in job.items if i.stage == 2]
        self.assertEqual(stage2[0].params["rcept_no"], "1")

    def test_is_idempotent(self):
        job = self._job_with_disclosures([{"rcept_no": "1", "report_nm": "전환사채권 발행결정"}])
        runner.expand_stage2(job)
        self.assertEqual(runner.expand_stage2(job), 0)
        self.assertEqual(len([i for i in job.items if i.stage == 2]), 1)

    def test_sets_expanded_flag(self):
        job = self._job_with_disclosures([])
        runner.expand_stage2(job)
        self.assertTrue(job.stage2_expanded)

    def test_does_not_expand_while_stage1_pending(self):
        """1단이 진행 중이면 공시 목록이 확정되지 않았으므로 확장하지 않는다."""
        job = _job_with([_stage1("disclosures", kind="fetch_company_disclosures")])
        self.assertEqual(runner.expand_stage2(job), 0)
        self.assertFalse(job.stage2_expanded)

    def test_marks_expanded_when_disclosures_missing(self):
        """공시 조회가 실패해도 확장 패스는 끝난 것으로 표시해야 한다.

        표시하지 않으면 추가할 항목이 없는데도 job.status가 영원히 running에
        머물러 호출자가 무한 루프에 빠진다.
        """
        item = _stage1("company_info")
        item.status = "done"
        item.result = {"value": {}}
        job = _job_with([item])  # disclosures 항목 자체가 없다
        self.assertEqual(runner.expand_stage2(job), 0)
        self.assertTrue(job.stage2_expanded)

    def test_marks_expanded_when_disclosures_failed(self):
        item = _stage1("disclosures", kind="fetch_company_disclosures")
        item.status = "failed"
        item.error = "DART 오류"
        job = _job_with([item])
        self.assertEqual(runner.expand_stage2(job), 0)
        self.assertTrue(job.stage2_expanded)

    def test_deduplicates_repeated_rcept_no(self):
        job = self._job_with_disclosures([
            {"rcept_no": "1", "report_nm": "전환사채권 발행결정"},
            {"rcept_no": "1", "report_nm": "전환사채권 발행결정"},
        ])
        self.assertEqual(runner.expand_stage2(job), 1)


class TestStage2Execution(unittest.TestCase):
    def test_stage2_item_calls_document_fetch(self):
        store = MemoryJobStore()
        item = WorkItem(key="doc:1", stage=2, kind="fetch_disclosure_full",
                        params={"rcept_no": "1"})
        store.save(_job_with([item], stage2_expanded=True))
        with mock.patch.object(runner, "fetch_disclosure_full",
                               return_value={"text": "본문"}) as fetch:
            runner.run_step("j1", "KEY", store, budget_seconds=100.0, now=_Clock(0.1))
        fetch.assert_called_once()
        self.assertEqual(fetch.call_args[0][0], "1")
        self.assertEqual(store.load("j1").items[0].status, "done")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `python -m pytest tests/se/test_job_runner.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'se_server.jobs.runner'`

- [ ] **Step 3: 구현**

`se_server/jobs/runner.py`:

```python
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
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest tests/se/test_job_runner.py -v`
Expected: PASS — 17 passed

- [ ] **Step 5: 전체 회귀 확인**

Run: `python -m pytest tests/ -q`
Expected: 기존 통과 수 + 이 계획에서 추가한 항목. 실패 0

- [ ] **Step 6: 커밋**

```bash
git add se_server/jobs/runner.py tests/se/test_job_runner.py
git commit -m "feat(se): 청크 실행기 — 예산 기반 실행·재개·2단 동적 확장"
```

---

### Task 5: Supabase 작업 저장소

**Files:**
- Create: `se_server/jobs/supabase_store.py`
- Create: `se_server/jobs/schema.sql`
- Modify: `se_server/jobs/__init__.py`
- Test: `tests/se/test_supabase_job_store.py`

**Interfaces:**
- Consumes: `se_server.jobs.model.Job` (Task 1), `se_server.jobs.store.JobStore` (Task 3), `se_server.config.SEConfig` (SE-1)
- Produces:
  - `se_server.jobs.supabase_store.SupabaseJobStore(config: SEConfig, session=None)` — `JobStore` 구현

**저장소 실패 처리가 캐시와 다른 이유:** SE-1의 캐시는 실패를 삼켰다(성능 최적화이므로). **작업 상태는 다르다** — 저장에 실패하면 진행이 유실되고 다음 호출이 같은 일을 반복한다. 따라서 `save` 실패는 **예외를 전파**한다. `load` 실패도 전파한다(작업 없음과 조회 실패는 다르게 다뤄야 한다).

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/se/test_supabase_job_store.py`:

```python
"""SupabaseJobStore의 HTTP 계약. 실제 네트워크는 타지 않는다."""
import unittest
from unittest import mock

from se_server.config import SEConfig
from se_server.jobs.model import Job, WorkItem
from se_server.jobs.supabase_store import SupabaseJobStore

CFG = SEConfig(
    supabase_url="https://proj.supabase.co",
    supabase_service_key="SERVICE_KEY",
    cache_bucket="se-cache",
)


def _resp(status=200, json_body=None):
    r = mock.Mock()
    r.status_code = status
    r.json.return_value = json_body if json_body is not None else []
    return r


def _job():
    return Job(job_id="j1", company="테스트", corp_code="0", lookback_years=1,
               items=[WorkItem(key="a", stage=1, kind="fetch", params={})])


class TestSave(unittest.TestCase):
    def test_upserts_with_merge_duplicates(self):
        session = mock.Mock()
        session.post.return_value = _resp(201)
        SupabaseJobStore(CFG, session=session).save(_job())
        headers = session.post.call_args[1]["headers"]
        self.assertIn("resolution=merge-duplicates", headers["Prefer"])
        self.assertEqual(headers["Authorization"], "Bearer SERVICE_KEY")

    def test_payload_carries_job_id_and_state(self):
        session = mock.Mock()
        session.post.return_value = _resp(201)
        SupabaseJobStore(CFG, session=session).save(_job())
        payload = session.post.call_args[1]["json"]
        self.assertEqual(payload["job_id"], "j1")
        self.assertEqual(payload["state"]["company"], "테스트")

    def test_failure_raises(self):
        """작업 상태 저장 실패는 삼키면 안 된다 — 진행이 유실된다."""
        session = mock.Mock()
        session.post.return_value = _resp(500)
        with self.assertRaises(RuntimeError):
            SupabaseJobStore(CFG, session=session).save(_job())

    def test_network_error_propagates(self):
        session = mock.Mock()
        session.post.side_effect = RuntimeError("네트워크 오류")
        with self.assertRaises(RuntimeError):
            SupabaseJobStore(CFG, session=session).save(_job())

    def test_service_key_not_in_payload(self):
        session = mock.Mock()
        session.post.return_value = _resp(201)
        SupabaseJobStore(CFG, session=session).save(_job())
        import json
        self.assertNotIn("SERVICE_KEY", json.dumps(session.post.call_args[1]["json"]))


class TestLoad(unittest.TestCase):
    def test_returns_job(self):
        session = mock.Mock()
        session.get.return_value = _resp(200, json_body=[{"state": _job().to_dict()}])
        loaded = SupabaseJobStore(CFG, session=session).load("j1")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.company, "테스트")

    def test_empty_result_returns_none(self):
        session = mock.Mock()
        session.get.return_value = _resp(200, json_body=[])
        self.assertIsNone(SupabaseJobStore(CFG, session=session).load("없음"))

    def test_query_filters_by_job_id(self):
        session = mock.Mock()
        session.get.return_value = _resp(200, json_body=[])
        SupabaseJobStore(CFG, session=session).load("j1")
        self.assertEqual(session.get.call_args[1]["params"]["job_id"], "eq.j1")

    def test_http_error_raises(self):
        """조회 실패와 '작업 없음'은 다르게 다뤄야 한다."""
        session = mock.Mock()
        session.get.return_value = _resp(500)
        with self.assertRaises(RuntimeError):
            SupabaseJobStore(CFG, session=session).load("j1")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `python -m pytest tests/se/test_supabase_job_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'se_server.jobs.supabase_store'`

- [ ] **Step 3: 구현**

`se_server/jobs/supabase_store.py`:

```python
"""Supabase PostgREST 작업 저장소.

Vercel 함수는 프로세스가 요청마다 새로 뜨므로 작업 상태는 외부에 있어야 한다.
이미 인증·캐시에 Supabase를 쓰므로 같은 프로젝트의 테이블을 쓴다.

SE-1의 캐시와 달리 **실패를 삼키지 않는다.** 캐시는 성능 최적화라 실패해도
정확성이 유지되지만, 작업 상태 저장에 실패하면 진행이 유실되고 다음 호출이
같은 일을 반복한다. 조용한 실패는 무한 루프로 이어진다.
"""
from __future__ import annotations

import requests

from se_server.config import SEConfig
from se_server.jobs.model import Job

_TABLE = "se_jobs"


class SupabaseJobStore:
    def __init__(self, config: SEConfig, session=None) -> None:
        self.config = config
        self.session = session or requests.Session()

    def _headers(self) -> dict:
        key = self.config.supabase_service_key
        return {"Authorization": f"Bearer {key}", "apikey": key}

    def _table_url(self) -> str:
        return f"{self.config.supabase_url}/rest/v1/{_TABLE}"

    def save(self, job: Job) -> None:
        headers = self._headers()
        headers["Content-Type"] = "application/json"
        headers["Prefer"] = "resolution=merge-duplicates"
        resp = self.session.post(
            self._table_url(),
            headers=headers,
            json={"job_id": job.job_id, "state": job.to_dict(), "status": job.status},
            timeout=15,
        )
        if resp.status_code >= 300:
            raise RuntimeError(f"작업 상태 저장 실패 (HTTP {resp.status_code})")

    def load(self, job_id: str) -> Job | None:
        resp = self.session.get(
            self._table_url(),
            headers=self._headers(),
            params={"job_id": f"eq.{job_id}", "select": "state"},
            timeout=15,
        )
        if resp.status_code >= 300:
            raise RuntimeError(f"작업 상태 조회 실패 (HTTP {resp.status_code})")
        rows = resp.json()
        if not rows:
            return None
        return Job.from_dict(rows[0]["state"])
```

`se_server/jobs/schema.sql`:

```sql
-- SE 작업 테이블. Supabase SQL 에디터에서 1회 실행한다.
-- state는 Job.to_dict() 전체를 담는다. DART API 키는 여기 들어가지 않는다.

create table if not exists se_jobs (
  job_id     text primary key,
  state      jsonb not null,
  status     text not null default 'running',
  updated_at timestamptz not null default now()
);

create index if not exists se_jobs_status_idx on se_jobs (status);

-- service_role만 접근한다. 브라우저는 이 테이블을 직접 읽지 않는다.
alter table se_jobs enable row level security;
```

`se_server/jobs/__init__.py`를 아래로 교체:

```python
"""SE 작업(job) 계층 — 청크 실행과 상태 보관."""
from se_server.jobs.model import Job, WorkItem
from se_server.jobs.store import JobStore, MemoryJobStore, new_job_id
from se_server.jobs.supabase_store import SupabaseJobStore

__all__ = [
    "Job", "WorkItem", "JobStore", "MemoryJobStore", "new_job_id", "SupabaseJobStore",
]
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest tests/se/test_supabase_job_store.py -v`
Expected: PASS — 9 passed

- [ ] **Step 5: 커밋**

```bash
git add se_server/jobs/supabase_store.py se_server/jobs/schema.sql se_server/jobs/__init__.py tests/se/test_supabase_job_store.py
git commit -m "feat(se): Supabase 작업 저장소 — 실패를 전파해 진행 유실을 막는다"
```

---

### Task 6: 작업 실행 CLI + 중단·재개 실측

이 계획의 목표(중단·재개 가능한 청크 실행)를 실제로 검증하는 유일한 태스크다.

**Files:**
- Create: `scripts/se_analyze.py`
- Test: `tests/se/test_se_analyze.py`

**Interfaces:**
- Consumes: Task 1~5 전부, SE-1의 `se_server.cache`·`se_server.http_cache`
- Produces:
  - `scripts.se_analyze.run_to_completion(company, api_key, lookback_years, store, budget_seconds) -> tuple[str, list[StepResult]]` — `(job_id, 단계별 결과)`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/se/test_se_analyze.py`:

```python
"""작업 실행 CLI의 순수 로직. DART 호출은 스텁한다."""
import unittest
from unittest import mock

from scripts import se_analyze
from se_server.jobs.store import MemoryJobStore


class TestRunToCompletion(unittest.TestCase):
    def test_loops_until_done(self):
        store = MemoryJobStore()
        with mock.patch.object(
            se_analyze, "resolve_corp",
            return_value=("테스트회사", {"corp_code": "0", "stock_code": "0"}),
        ), mock.patch.object(
            se_analyze.runner, "resolve_callable", return_value=lambda **kw: []
        ), mock.patch.object(
            se_analyze.runner, "fetch_disclosure_full", return_value={"text": ""}
        ):
            job_id, steps = se_analyze.run_to_completion(
                "테스트회사", "KEY", 1, store, budget_seconds=1000.0
            )
        self.assertTrue(steps)
        self.assertTrue(steps[-1].done)
        self.assertEqual(store.load(job_id).status, "done")

    def test_small_budget_needs_multiple_steps(self):
        """예산을 잘게 주면 여러 단계로 나뉘고, 그래도 끝까지 간다."""
        store = MemoryJobStore()
        clock = {"t": 0.0}

        def tick():
            clock["t"] += 5.0
            return clock["t"]

        with mock.patch.object(
            se_analyze, "resolve_corp",
            return_value=("테스트회사", {"corp_code": "0", "stock_code": "0"}),
        ), mock.patch.object(
            se_analyze.runner, "resolve_callable", return_value=lambda **kw: []
        ), mock.patch.object(
            se_analyze.runner, "fetch_disclosure_full", return_value={"text": ""}
        ):
            job_id, steps = se_analyze.run_to_completion(
                "테스트회사", "KEY", 1, store, budget_seconds=6.0, now=tick
            )
        self.assertGreater(len(steps), 1)
        self.assertTrue(steps[-1].done)

    def test_unresolved_company_raises(self):
        with mock.patch.object(se_analyze, "resolve_corp", return_value=(None, None)):
            with self.assertRaises(ValueError):
                se_analyze.run_to_completion("없는회사", "KEY", 1, MemoryJobStore(), 100.0)

    def test_guards_against_infinite_loop(self):
        """진행이 없는데 done도 아니면 무한 루프에 빠지지 않고 중단해야 한다."""
        store = MemoryJobStore()
        stuck = se_analyze.runner.StepResult(done=False, processed=0, finished=0, total=3)
        with mock.patch.object(
            se_analyze, "resolve_corp",
            return_value=("테스트회사", {"corp_code": "0", "stock_code": "0"}),
        ), mock.patch.object(se_analyze.runner, "run_step", return_value=stuck):
            with self.assertRaises(RuntimeError):
                se_analyze.run_to_completion("테스트회사", "KEY", 1, store, 100.0)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `python -m pytest tests/se/test_se_analyze.py -v`
Expected: FAIL — `ImportError: cannot import name 'se_analyze' from 'scripts'`

- [ ] **Step 3: 구현**

`scripts/se_analyze.py`:

```python
"""SE 분석 작업 실행 — 청크 실행과 재개를 실측한다.

사용:
    python scripts/se_analyze.py 셀트리온 --years 1 --budget 20

    # 진행 상태만 확인
    python scripts/se_analyze.py --job-id <ID> --status

API 키는 환경변수 DART_API_KEY 또는 tmp/_apikey.txt에서 읽는다.
키는 호출 인자로만 흐르며 작업 레코드에 저장되지 않는다.
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dart_risk_mcp.core.dart_client import resolve_corp  # noqa: E402
from se_server.cache import MemoryCache  # noqa: E402
from se_server.http_cache import install  # noqa: E402
from se_server.jobs import MemoryJobStore  # noqa: E402
from se_server.jobs import runner  # noqa: E402

# 진행이 전혀 없는 단계가 이만큼 연속되면 중단한다(무한 루프 방지).
_MAX_STALLED_STEPS = 3


def _load_api_key() -> str:
    key = os.environ.get("DART_API_KEY", "").strip()
    if key:
        return key
    path = os.path.join(os.path.dirname(__file__), "..", "tmp", "_apikey.txt")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    raise ValueError("DART_API_KEY 환경변수 또는 tmp/_apikey.txt가 필요합니다")


def run_to_completion(company, api_key, lookback_years, store, budget_seconds, now=time.monotonic):
    """작업을 만들고 done이 될 때까지 run_step을 반복한다.

    반환: (job_id, 단계별 StepResult 목록)
    """
    corp_name, info = resolve_corp(company, api_key)
    if not info:
        raise ValueError(f"기업을 찾지 못했습니다: {company}")

    job = runner.create_job(corp_name or company, info["corp_code"], lookback_years, store)
    steps = []
    stalled = 0

    while True:
        result = runner.run_step(
            job.job_id, api_key, store, budget_seconds=budget_seconds, now=now
        )
        steps.append(result)
        if result.done:
            break
        if result.processed == 0:
            stalled += 1
            if stalled >= _MAX_STALLED_STEPS:
                raise RuntimeError(
                    f"진행이 멈췄습니다 ({result.finished}/{result.total} 완료). "
                    "예산이 너무 작아 어떤 항목도 시작하지 못했을 수 있습니다."
                )
        else:
            stalled = 0

    return job.job_id, steps


def main() -> int:
    parser = argparse.ArgumentParser(description="SE 분석 작업 실행")
    parser.add_argument("company", help="기업명 또는 종목코드")
    parser.add_argument("--years", type=int, default=1, help="조회 연수 (기본 1)")
    parser.add_argument("--budget", type=float, default=45.0,
                        help="단계당 시간 예산 초 (기본 45)")
    args = parser.parse_args()

    api_key = _load_api_key()
    install(MemoryCache())
    store = MemoryJobStore()

    started = time.monotonic()
    job_id, steps = run_to_completion(
        args.company, api_key, args.years, store, args.budget
    )
    elapsed = time.monotonic() - started

    job = store.load(job_id)
    failed = [i for i in job.items if i.status == "failed"]

    print(f"작업 {job_id} — {len(steps)}단계 · {elapsed:.1f}초")
    for n, step in enumerate(steps, 1):
        print(f"  {n}단계: {step.processed}건 처리 ({step.finished}/{step.total})")
    if failed:
        print(f"\n실패 {len(failed)}건 (나머지는 정상 수집):")
        for item in failed[:10]:
            print(f"  - {item.key}: {item.error[:80]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest tests/se/test_se_analyze.py -v`
Expected: PASS — 4 passed

- [ ] **Step 5: 전체 회귀 확인**

Run: `python -m pytest tests/ -q`
Expected: 실패 0

- [ ] **Step 6: 라이브 실측 (API 키 필요)**

Run: `python scripts/se_analyze.py 셀트리온 --years 1 --budget 20`

Expected: **여러 단계로 나뉘어 실행되고 마지막에 완료된다.** 확인할 것:
- 단계가 2개 이상인가 (1개면 예산이 너무 커서 청크 실행이 검증되지 않은 것이다 — `--budget`을 낮춰 재실행)
- 실패 항목이 있다면 그것만 실패하고 나머지는 수집됐는가
- 총 소요가 `단계 수 × 예산`을 크게 넘지 않는가

API 키가 없으면 건너뛰고 그 사실을 명확히 기록한다. **수치를 각색하지 않는다.**

- [ ] **Step 7: 커밋**

```bash
git add scripts/se_analyze.py tests/se/test_se_analyze.py
git commit -m "feat(se): 작업 실행 CLI — 중단·재개 실측"
```

---

## 이 계획이 다루지 않는 것

| 항목 | 어디서 |
|---|---|
| HTTP 엔드포인트(`POST /analyze`, `/step`, `GET /analyze/{id}`) | SE-3 |
| Supabase Auth 가드, 사용자별 접근 통제 | SE-3 |
| 수집한 데이터를 섹션별 화면 데이터로 가공 | SE-4 |
| 롱스크롤 본문 + 우측 슬라이드 패널 | SE-4 |
| 행위자 레지스트리 대조(⚑) | SE-4 |
| 브라우저 폴링 루프 | SE-3·SE-4 |

SE-2의 산출물은 **"회사명 → 수집 완료된 원시 데이터"** 까지다. 이 단계에서 화면을 의식해 데이터를 가공하면, SE-4에서 화면이 바뀔 때마다 수집 계층을 고치게 된다.

## 선행 조건

- **SE-1이 머지되어 있어야 한다.** 이 계획은 `se_server.cache`·`se_server.http_cache`·`se_server.config`를 사용한다.
- SE-1의 캐시가 없으면 청크 실행이 매번 DART를 다시 때려 재개의 이점이 사라진다.

## 자체 검토 결과

- **스펙 커버리지:** §6.1(3단 로딩) → Task 2·4. §7.3(청크 실행·재개) → Task 4·6. §8(항목 단위 실패 격리) → Task 4. §5(DART 키 미저장) → Task 1·2·4의 전용 테스트. 3단(클릭 시 원문)은 SE-3 소관이라 이 계획 밖.
- **설계와의 의도적 차이 1건:** 설계 §7.3은 작업 상태를 "Postgres"라고만 적었다. 이 계획은 `se_jobs` 단일 테이블 + `state` JSONB로 구현한다. 항목별 테이블로 정규화하면 매 단계마다 조인·다건 업데이트가 필요한데, 한 작업의 상태는 통째로 읽고 통째로 쓰는 접근 패턴이라 이득이 없다.
- **타입 일관성:** `WorkItem`/`Job` 필드가 Task 1 정의와 Task 3~6 사용에서 일치. `JobStore.save`/`load` 시그니처가 Task 3 정의와 Task 5 구현에서 일치. `StepResult` 필드가 Task 4 정의와 Task 6 사용에서 일치.
- **미해결 위험 2건:**
  1. `oversized` 항목 하나가 예산보다 오래 걸리면 그 항목은 영원히 완료되지 못한다. `OVERSIZED_RESERVE`(20초)가 실제로 충분한지는 Task 6의 라이브 실측으로만 확인 가능하다. 부족하면 해당 core 함수를 더 잘게 쪼개야 하는데, 그건 core 수정이라 별도 판단이 필요하다.
  2. `Job.to_dict()`가 모든 항목 결과를 담으므로 한 행이 커진다. 원문 텍스트를 결과에 통째로 넣으면 수 MB가 될 수 있다. Task 6 실측에서 행 크기를 확인하고, 크면 원문 결과는 캐시(Storage)에 두고 작업 레코드에는 참조만 남기는 방향으로 SE-3에서 조정한다.
