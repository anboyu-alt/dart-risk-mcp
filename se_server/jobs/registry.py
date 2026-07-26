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
    # 페이지네이션 상한을 반드시 함께 넘긴다. max_pages 기본값 10은 1000건에서
    # 조용히 잘리며(core가 log.warning만 남기고 break) 다년 조회에서 오래된
    # 공시 위주로 결과가 누락된다. 기존 MCP 도구도 같은 이유로 years*10을
    # 넘긴다(server.py `_resolve_lookback`, CHANGELOG "다년 누락 방지").
    Stage1Spec("disclosures", "자금", "fetch_company_disclosures",
               ("corp_code", "lookback_days", "max_pages"), oversized=True),
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
            elif name == "max_pages":
                # server.py _resolve_lookback과 같은 공식. 기본값 10을 쓰면
                # 1000건에서 조용히 잘려 다년 조회의 공시가 누락된다.
                params["max_pages"] = years * 10
            elif name in ("year", "bsns_year"):
                params[name] = bsns_year
            else:  # pragma: no cover - 위 테스트(test_param_names_match_real_signatures)가 이 경로를 막는다
                raise ValueError(f"채울 수 없는 param 이름: {spec.key}.{name}")
        items.append(WorkItem(key=spec.key, stage=1, kind=spec.func_name, params=params))
    return items


def _previous_business_year() -> int:
    """직전 사업연도. 테스트에서 고정하기 쉽도록 분리해 둔다."""
    import datetime as _dt

    return _dt.date.today().year - 1
