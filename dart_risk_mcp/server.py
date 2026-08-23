"""DART 기업 위험 분석 MCP 서버

3개 도구:
- analyze_company_risk: 기업명/종목코드 → 종합 위험 리포트
- check_disclosure_risk: 공시 접수번호/제목 → 개별 공시 분석
- find_risk_precedents: 신호 조합 → 과거 유사 사례 (제한적 구현)
"""

# PEP 604(`X | None`) 표기를 쓰므로 이 import가 없으면 Python 3.10 미만에서
# import 시점에 TypeError로 죽는다(3.11+에서는 동작 차이 없음).
from __future__ import annotations

import os
import re
import warnings
from collections import Counter
from datetime import datetime, timedelta

from mcp.server.fastmcp import FastMCP

from .core import (
    calculate_risk_score,
    category_prose,
    detect_capital_churn,
    detect_debt_rollover,
    detect_dividend_drain,
    compute_beneish_variables,
    detect_financial_anomaly,
    detect_insider_pre_disclosure,
    detect_profit_direction_divergence,
    detect_restatement,
    extract_rd_ratio_from_report,
    extract_xbrl_depreciation,
    fetch_loss_streak,
    estimate_crisis_timeline,
    extract_cb_investors,
    extract_cfs_ofs_ni,
    extract_loan_advance,
    fetch_affiliate_investments,
    match_affiliate_row,
    summarize_affiliate_stake,
    NOTE_CATEGORIES,
    classify_note_title,
    build_note_summary,
    scan_note_titles,
    extract_rights_offering_investors,
    fetch_audit_opinion_history,
    fetch_company_disclosures,
    fetch_company_disclosures_with_status,
    FETCH_ERROR,
    fetch_market_disclosures,
    fetch_market_disclosures_with_status,
    fetch_company_info,
    get_critical_items,
    get_induty_name,
    fetch_debt_balance,
    fetch_disclosure_full,
    fetch_distress_events,
    fetch_dividend_history,
    fetch_document_content,
    fetch_document_text,
    fetch_outflow_detail,
    classify_outflow_relation,
    classify_target_listing,
    fetch_acquisition_detail,
    fetch_asset_disposal_detail,
    fetch_related_party_detail,
    fetch_earnings_shock_detail,
    fetch_control_change_detail,
    classify_holder_type,
    strip_holder_suffix,
    actor_status,
    add_person,
    get_person_companies,
    list_persons,
    load_watchlist,
    lookup_actor,
    lookup_actors_by_company,
    remove_person,
    fetch_executive_compensation,
    fetch_executive_roster_detail,
    fetch_financial_statements,
    fetch_financial_statements_all,
    fetch_fund_usage,
    fetch_insider_timeline,
    fetch_major_decision,
    resolve_corp_code_from_rcept_no,
    resolve_disclosure_row_with_status,
    normalize_date8,
    fetch_multi_financial,
    fetch_shareholder_status,
    fetch_treasury_decisions,
    fetch_company_indicators,
    find_pattern_match,
    find_pattern_overlaps,
    flag_to_prose,
    is_amendment_disclosure,
    list_document_sections,
    load_catalog_excerpt,
    match_signals,
    pattern_to_prose,
    pattern_checkpoints,
    resolve_corp,
    resolve_decision_type,
    signal_to_prose,
    taxonomy_label_ko,
    CAPITAL_EVENT_KEYS,
    SIGNAL_KEY_TO_TAXONOMY,
    SIGNAL_TYPES,
    _fs_response_to_periods,
    _parse_fs_amount,
)
from .core.taxonomy import CROSS_SIGNAL_PATTERNS
from .core.qualifiers import (
    Qualified,
    TIER_OBSERVED,
    is_false_amendment,
    parse_report_name,
    pick_headline,
    qualify_signals,
)
from .core.signals import strip_amendment_prefix

mcp = FastMCP("dart-risk-analyzer")

_DART_API_KEY: str = os.environ.get("DART_API_KEY", "")


def _estimate_output_size(text: str) -> tuple[int, int]:
    """렌더된 출력의 문자 수와 대략적 토큰 수를 추정한다.

    정밀 토크나이저가 아니라 문자 수 기반 휴리스틱이다(외부 의존성 없음).
    한국어·마크다운 혼합 기준 대략 글자 2.5개당 1토큰으로 환산한다.
    """
    chars = len(text)
    tokens = round(chars / 2.5)
    return chars, tokens


def _append_size_footer(text: str, lookback_years: int) -> str:
    """다년 조회(lookback_years > 1)일 때만 예상 출력 규모 푸터를 덧붙인다."""
    if lookback_years <= 1:
        return text
    chars, tokens = _estimate_output_size(text)
    return text + f"\n\n📊 예상 출력 규모: 약 {chars:,}자 / ~{tokens:,}토큰 (대략적 추정)"


def _shallow_notice(tool_name: str, company: str, dates: "list[str]") -> str:
    """얕은 모드에서 "구간을 좁히면 더 볼 수 있다"를 안내한다.

    넓은 창은 지도라 원문 사실 블록(이자율·상대방·증감률)을 싣지 않는다.
    그 사실을 감추지 않고, 어느 구간을 좁히면 되는지까지 함께 말한다 —
    관찰된 신호가 있으면 가장 최근 신호의 달을 그대로 예시로 쓴다.

    **날짜 리스트를 받는다.** 처음에는 이벤트 리스트를 받아 dict에서 날짜를
    꺼냈는데, `analyze_company_risk`의 이벤트는 dict이고
    `build_event_timeline`의 이벤트는 **튜플**이라 후자에서 AttributeError로
    죽었다(2026-08-23 통합 검증에서 발견 — 두 도구가 각각 테스트를 통과했지만
    자료구조가 다른 것은 아무도 확인하지 않았다). 호출부가 날짜만 뽑아
    넘기면 이 함수가 자료구조를 알 필요가 없다.
    """
    dates = sorted(d for d in (str(x or "")[:8] for x in (dates or []))
                   if len(d) == 8)
    if dates:
        recent = dates[-1]
        span = f'from_date="{recent[:4]}-{recent[4:6]}-01"'
    else:
        span = 'from_date="2026-01-01"'
    return (
        "\n🔎 **더 깊게 보려면**\n"
        "이 조회는 넓은 창이라 지도만 그립니다 — 상대방·이자율·증감률 같은 "
        "원문 확인 내용은 싣지 않았습니다.\n"
        "관심 구간을 좁혀 다시 부르면 원문까지 확인합니다: "
        f'`{tool_name}("{company}", {span})`'
    )


def _fetch_failed_notice(corp_name: str, window_phrase: str) -> str:
    """조회가 **실패**했을 때의 안내 — "자료가 없다"와 구분한다.

    빈 결과를 그대로 화면으로 내면 API 장애·키 오류·한도 초과가 전부
    "이 회사는 조용하다"로 보인다(2026-08-23 에러 경로 감사에서 발견).
    리스크를 알리는 도구에서 이 둘이 섞이면 안 된다.
    """
    return (
        f"⚠ **{corp_name}**의 자료를 불러오지 못했습니다 ({window_phrase}).\n\n"
        "**자료가 없다는 뜻이 아닙니다** — DART 조회가 실패했습니다. "
        "API 키가 올바른지, 일일 호출 한도를 넘지 않았는지 확인한 뒤 다시 "
        "시도해 주세요."
    )


def _alias_note_line(corp_info: dict) -> "str | None":
    """resolve_corp이 채운 alias_note가 있으면 안내 1줄을 반환(없으면 None).

    옛 상호 입력을 현재 상호로 해석했거나(자동 전환), 동명의 다른 상장사가
    상호변경 이력에 있다는 참고를 병기한 경우 둘 다 이 한 줄로 표면화한다.
    판정 어휘 없이 사실만 전달하는 참고 톤.
    """
    note = (corp_info or {}).get("alias_note")
    return f"ℹ️ {note}" if note else None


# 탐색 깊이 — 넓게 볼 땐 얕게, 좁게 볼 땐 깊게 (v1.18.0)
#
# 지금까지는 창이 1년이든 5년이든 원문 확인이 최근 3건으로 고정이라, 5년을
# 조회해도 3년 전 사건은 제목만 보였다. 깊이가 창에 따라가지 않으니 넓은
# 조회는 "많이 보는데 얕게 보는" 어정쩡한 상태였다.
#
# 대신 역할을 나눈다. 넓은 창은 **지도**다 — 신호·패턴·타임라인으로 "언제
# 무슨 일이 있었나"를 보여주고, 원문 사실 블록은 싣지 않는다. 좁은 창은
# **상세**다 — 원문까지 열어 이자율·상대방·증감률을 확인한다. 사용자는 지도에서
# 구간을 고른 뒤 `from_date`/`to_date`로 그 구간을 깊게 본다.
#
# 패턴 게이트(capital_backflow·fund_diversion_chain)의 원문 확인은 **얕은
# 모드에서도 유지한다** — 그건 표시용 사실이 아니라 패턴을 띄울지 말지의
# 판정 입력이라, 빼면 지도에서 패턴 자체가 사라진다.
_DEEP_WINDOW_DAYS = 400        # 1년 조회(365일)에 여유를 둔 경계


def _is_deep_window(days: int) -> bool:
    """이 창에서 원문 사실 블록을 실을지 — 좁은 창일 때만 깊게 본다."""
    return days <= _DEEP_WINDOW_DAYS


def _fmt_date8(d: str) -> str:
    """YYYYMMDD → YYYY.MM.DD. 8자리가 아니면 그대로 돌려준다."""
    return f"{d[:4]}.{d[4:6]}.{d[6:]}" if len(d) == 8 else d


def _exec_role_label(row: dict) -> str:
    """임원현황 행에서 직위·등기 여부를 표시용 사실 라벨로 만든다.

    `ofcps`(직위: 사외이사·수석부사장·대표이사 …)와 `rgist_exctv_at`
    (등기 여부: 사내이사·사외이사·미등기 …)는 원문 표기를 그대로 쓴다 —
    분류하거나 판정하지 않는다. 둘이 같은 값이면 한 번만 적는다
    (실측: 헬스커넥트 「사내이사/사내이사」).

    비어 있으면 빈 문자열 — 호출부가 라벨 없이 기존 형태로 렌더한다.
    """
    # 실측에 원문 개행이 섞여 온다(「등기\n임원」) — 한 줄로 편다.
    pos = " ".join((row.get("ofcps") or "").split())
    reg = " ".join((row.get("rgist_exctv_at") or "").split())
    parts = [p for p in (pos, reg) if p]
    if len(parts) == 2 and parts[0] == parts[1]:
        parts = parts[:1]
    return "/".join(parts)


def _resolve_window(
    lookback_years: int,
    lookback_days: "int | None",
    from_date: str = "",
    to_date: str = "",
) -> "tuple[str, str, int, int, str, str]":
    """조회 창을 (bgn_de, end_de, days, max_pages, 표시문구, 오류) 로 해석한다.

    `from_date`/`to_date`가 주어지면 그 구간이 우선하고 lookback_years는
    무시한다. 형식이 틀리면 마지막 원소에 사용자용 오류 문구가 담긴다 —
    조용히 무시하고 엉뚱한 창을 조회하지 않는다.
    """
    if from_date or to_date:
        bgn = normalize_date8(from_date) if from_date else ""
        end = normalize_date8(to_date) if to_date else ""
        if from_date and not bgn:
            return "", "", 0, 0, "", f"from_date 형식이 올바르지 않습니다: {from_date!r} (예: 2024-01-01)"
        if to_date and not end:
            return "", "", 0, 0, "", f"to_date 형식이 올바르지 않습니다: {to_date!r} (예: 2024-06-30)"
        today = datetime.now().strftime("%Y%m%d")
        end = end or today
        # 시작일이 미래면 조회할 게 없다. 그대로 두면 DART가 빈 목록을 주고
        # 화면에는 "공시 없음"이 뜬다 — **아직 오지 않은 기간과 조용한 기간이
        # 같은 모양**이 된다. 연도를 한 자리 잘못 친 사용자가 그걸 "이 회사는
        # 조용하다"로 읽는다. 같은 종류의 결함을 관찰 윈도우 표기에서 이미
        # 한 번 고쳤다(v1.12.3 — 아직 오지 않은 날짜가 창 끝에 찍히던 건).
        if bgn and bgn > today:
            return "", "", 0, 0, "", (
                f"from_date({_fmt_date8(bgn)})가 미래입니다 — "
                f"오늘({_fmt_date8(today)})까지만 조회할 수 있습니다."
            )
        # 종료일이 미래인 것은 막지 않는다. "2024-01-01부터 지금까지"를
        # 넉넉한 종료일로 표현하는 건 자연스러운 의도다. 대신 **실제로 조회한
        # 구간**을 표기하도록 오늘로 좁힌다 — 표기와 동작이 어긋나면 그것도
        # 거짓이다.
        clamped = end > today
        if clamped:
            end = today
        # 시작일을 안 주면 종료일 기준 1년 — "그 시점까지 1년"이 자연스럽다
        if not bgn:
            bgn = (datetime.strptime(end, "%Y%m%d") - timedelta(days=365)).strftime("%Y%m%d")
        if bgn > end:
            return "", "", 0, 0, "", f"from_date({bgn})가 to_date({end})보다 뒤입니다."
        days = (datetime.strptime(end, "%Y%m%d") - datetime.strptime(bgn, "%Y%m%d")).days + 1
        # 페이지 상한은 창 길이에 비례 — 1년당 10페이지(1,000건)라는 기존 관례
        max_pages = max(10, min(50, (days // 365 + 1) * 10))
        phrase = f"{_fmt_date8(bgn)}~{_fmt_date8(end)}"
        if clamped:
            phrase += " (종료일이 미래라 오늘까지로 좁혔습니다)"
        return bgn, end, days, max_pages, phrase, ""

    days, max_pages, phrase = _resolve_lookback(lookback_years, lookback_days)
    return "", "", days, max_pages, phrase, ""


def _resolve_lookback(
    lookback_years: int, lookback_days: "int | None"
) -> "tuple[int, int, str]":
    """조회 윈도우를 (일수, max_pages, 표시문구)로 해석한다.

    lookback_days(deprecated)가 명시되면 구버전 동작(일 단위, 1~365 클램프)을
    보존하고, 아니면 lookback_years(1~5)를 일수로 환산한다. lookback_days는
    v1.4.0에서 deprecated 별칭이며 다음 minor에서 제거 예정이다.
    """
    if lookback_days is not None:
        warnings.warn(
            "lookback_days는 deprecated입니다. lookback_years(1~5)를 사용하세요.",
            DeprecationWarning,
            stacklevel=3,
        )
        days = min(max(lookback_days, 1), 365)
        return days, 10, f"{days}일"
    years = min(max(lookback_years, 1), 5)
    days = years * 365
    phrase = f"{days}일" if years == 1 else f"{years}년"
    # 페이지 상한은 창과 무관하게 최소 50페이지(5,000건)를 준다.
    #
    # 옛 공식 `years * 10`은 1년 조회에 1,000건만 허용해 **대형사에서
    # 절단됐다**(2026-08-23 실측: 삼성전자 1년 2,891건 중 1,000건만 조회).
    # 1년 코퍼스(법인 45,426개)에서 1년 1,000건을 넘는 법인은 23개(0.05%)이고
    # **5,000건을 넘는 법인은 0개**라, 50페이지면 1년 조회는 전부 덮인다.
    #
    # 상한을 올려도 작은 회사는 비용이 늘지 않는다 — fetch_company_disclosures가
    # total_count로 조기 종료하므로 공시가 적으면 1페이지에서 끝난다. 비용이
    # 느는 것은 지금 절단되던 0.05%뿐이다.
    return days, max(50, years * 10), phrase


# ── 공통 헬퍼 ──────────────────────────────────────────────────────────────


def _format_amount(amount: str) -> str:
    if not amount:
        return ""
    sign = ""
    body = amount
    if body.startswith("-"):
        sign, body = "-", body[1:]
    digits = body.replace("원", "").replace(",", "")
    if digits.isdigit():
        n = int(digits)
        if n >= 1_000_000_000_000:
            return f"{sign}{n // 1_000_000_000_000}조원"
        if n >= 100_000_000:
            return f"{sign}{n // 100_000_000}억원"
        if n >= 10_000:
            return f"{sign}{n // 10_000}만원"
    return amount


_FUND_KIND_LABEL = {"public": "공모", "private": "사모"}
# DART 응답에서 회차가 비어 있을 때 오는 플레이스홀더 값들
_EMPTY_TM_VALUES = {"", "-", "—", "–"}
# 같은 signal_key가 이 횟수를 넘기면 그 뒤의 이벤트는 prose(→) 해설을 생략한다.
# v0.7.4: 제이스코홀딩스처럼 전환사채 공시가 10건 몰리면 같은 해설이 반복 출력되는
# 피로감을 줄이기 위한 renderer-side dedup. 첫 3건만 full prose.
_PROSE_REPEAT_LIMIT = 3


def _fund_kind_korean(kind: str | None) -> str:
    """`kind`(public/private) → 공모/사모. 그 외는 `기타`."""
    return _FUND_KIND_LABEL.get((kind or "").lower(), "기타")


def _fund_round_korean(tm: str | None) -> str:
    """회차 문자열을 `제N회차`로 포맷. 값이 비어 있으면 빈 문자열."""
    tm_s = (tm or "").strip()
    if tm_s in _EMPTY_TM_VALUES:
        return ""
    return f"제{tm_s}회차"


def _format_fund_event_name(rec: dict) -> str:
    """자금사용 레코드를 사용자 노출용 한글 라벨로 정리한다.

    v0.7.3: 기존 `[자금:public 회차-]` 형태가 영문·placeholder를 노출해 디버그 로그처럼
    보이던 문제를 수정. `kind`는 공모/사모로 변환, 회차가 비었으면 통째로 생략.
    """
    kind_label = _fund_kind_korean(rec.get("kind"))
    tm_part = _fund_round_korean(rec.get("tm"))
    use = (rec.get("plan_useprps") or "").strip()[:30]
    head = f"[자금조달({kind_label}){' ' + tm_part if tm_part else ''}]"
    return f"{head} {use}".strip() if use else head


def _format_fund_year_prefix(rec: dict) -> str:
    """`[YYYY 공모 제N회차]` / `[YYYY 사모]` 형태로 연도+조달유형+회차 프리픽스를 만든다.

    v0.7.3: 기존 `[2023 public 회차-]` 형태가 사용자 출력에 노출되던 문제를 수정.
    `조달자금 사용내역` 블록의 공통 프리픽스로 사용.
    """
    year = rec.get("year", "")
    kind_label = _fund_kind_korean(rec.get("kind"))
    tm_part = _fund_round_korean(rec.get("tm"))
    inner = " ".join(p for p in [str(year), kind_label, tm_part] if p)
    return f"[{inner}]"


def _clean_report_name(name: str) -> str:
    """DART 원본 공시명에 섞인 과다 공백을 한 칸으로 압축한다.

    v0.7.3: 원본이 고정폭 패딩으로 저장돼 `전환가액의조정              (제4회차)` 같이
    긴 공백이 사용자 출력에 그대로 드러나던 문제를 수정.
    """
    return re.sub(r"\s{2,}", " ", (name or "")).strip()


def _compose_top_signal_sentence(label: str, prose: str) -> str:
    """🎯 리드의 '가장 무거운 신호' 문장을 조립한다.

    v0.7.3: 기존 형태 `가장 무게 있는 신호는 'X'이며, X 공시입니다. ...`가
    라벨과 prose 첫 문장에서 같은 말을 반복하던 문제를 수정. prose 첫 문장이
    라벨을 단순히 되풀이하는 `... 공시입니다.` 꼴이면 그 문장을 건너뛰고
    다음 문장부터 이어 붙인다.
    """
    if not prose:
        return f"가장 무게 있는 신호는 '{label}'입니다."

    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", prose.strip()) if s.strip()]
    if not sentences:
        return f"가장 무게 있는 신호는 '{label}'입니다."

    # 라벨의 앞부분(공백 제거)이 첫 문장 안에 포함되고 그 문장이 '입니다.'로 끝나면
    # 라벨 되풀이로 판정하여 생략.
    label_core = (label or "").replace(" ", "")
    first = sentences[0]
    first_core = first.replace(" ", "")
    is_restatement = (
        len(label_core) >= 3
        and label_core[: min(6, len(label_core))] in first_core
        and (first_core.endswith("입니다.") or first_core.endswith("공시입니다."))
    )
    if is_restatement:
        rest = " ".join(sentences[1:]).strip()
        if rest:
            return f"가장 무게 있는 신호는 '{label}'입니다. {rest}"
        return f"가장 무게 있는 신호는 '{label}'입니다."
    return f"가장 무게 있는 신호는 '{label}'이며, {prose}"


def _registry_company_section(corp_name: str) -> list[str]:
    """회사→인물 레지스트리 역방향 대조 섹션 (매칭 없으면 []).

    사실 표기 전용 — 판정·점수 없음(v0.8.5). 해당 회사가 태깅된 기록만
    표시하고, 그 인물의 나머지 기록은 lookup_known_actor 안내로 위임한다.
    """
    hits = lookup_actors_by_company(corp_name)
    if not hits:
        return []
    lines = [
        "📎 공개기록 참고 (사실 표기 — 판정 아님): "
        "이 회사에 등장 기록이 있는 등재 행위자",
    ]
    has_auto = has_seed = False
    shown_counts: dict[str, int] = {}
    for nm, r in hits:
        st = actor_status(r)
        has_auto = has_auto or st == "auto_matched"
        has_seed = has_seed or st == "maintainer_seed"
        prefix = "[자동 매칭 · 동명이인 미확인] " if st == "auto_matched" else ""
        src = r.get("source", "")
        date = r.get("date", "")
        tag = f"{src}({date})" if date else src
        lines.append(f"  • {prefix}{nm} — {tag}: {r.get('evidence', '')}")
        shown_counts[nm] = shown_counts.get(nm, 0) + 1
    # lookup_actor(nm) — 정확 키가 아니라 lookup_actor와 동일한 정규화+폴딩
    # 병합을 거친 카운트. registry_actors.get(nm, [])(정확 키 조회)로는
    # SE-5b가 고친 '두 키에 나뉜 같은 실체'(예: '(주)베이트리' 1건 +
    # '주식회사 베이트리' 2건)에서 이 안내가 가리키는 lookup_known_actor(nm)의
    # 실제 반환 건수(3건)와 어긋난다 — 안내문이 자기가 가리키는 도구의 결과와
    # 모순되면 안 된다.
    for nm, n_shown in shown_counts.items():
        total = len(lookup_actor(nm))
        if total > n_shown:
            lines.append(
                f"    ({nm} 레지스트리 전체 기록 {total}건 — "
                f'자세히: lookup_known_actor("{nm}"))'
            )
    if has_auto:
        lines.append("  ⚠ 일부는 시장 공시 자동 매칭 (동일인 여부 미확인)")
    if has_seed:
        lines.append("  ⚠ 일부는 제작자 모니터링 등록 (공시 자동매칭 아님, 혐의·확정 아님)")
    lines.append("  ⚠ 원본 공시로 사실 확인 권장 · 동명이인 가능성 있음")
    return lines


# ── v1.6.1: 자금유출·양수거래 상대방 확인 + capital_backflow 게이트 ─────────
# capital_backflow(자금 역류) 패턴은 최대주주변경(3.1) + 자금유출성거래(5.7)가
# 둘 다 탐지되면 무조건 발화했다. 하지만 자금유출성거래는 제목만으로 매칭되므로
# 계열사 지원이 일상인 회사도 걸린다. 여기서 원문 상대방·관계를 확인해, 실제로
# 계열·특수관계(비연결)에 자금이 흘렀을 때만 패턴을 발화시킨다.

# 제목으로 발화하지 않는 신호를 조회했을 때 붙는 사실 안내(판정 아님).
_NON_TITLE_NOTE = {
    "structured": (
        "※ 이 신호는 공시 제목이 아니라 구조화 데이터로 판정됩니다 — "
        "제목 스캔(analyze_company_risk·search_market_disclosures)에서는 나타나지 않습니다."
    ),
    "covered": (
        "※ 이 유형의 공시는 실제로는 다른 신호가 잡습니다 — 제목 스캔에서 이 키로는 "
        "나타나지 않습니다(1년 실측 0건)."
    ),
    "absent": (
        "※ 이 개념은 DART 공시 제목에 등장하지 않습니다 — 여러 공시의 조합·시계열로만 "
        "성립하는 유형이라 제목 스캔에서는 나타나지 않습니다(1년 실측 0건)."
    ),
}

_OUTFLOW_CLASS_LABEL = {
    "affiliated": "계열·특수관계",
    "subsidiary": "종속회사",
    "external": "외부",
    "unknown": "미확인",
}

# DS005로 커버되는 결정 유형 중 "처분(양도)" 3종 — work item 4: 기존에는 이
# 확인 흐름이 신호 매칭(양수 키워드)에만 걸려 있어 양도 결정이 통째로 빠졌다.
_OUTFLOW_DIV_DECISION_TYPES = ("tangible_div", "business_div", "stock_div")


def _outflow_review_candidates(
    signal_events: list[dict], disclosures: list[dict]
) -> list[tuple[str, str, str]]:
    """상대방 확인 후보를 (rcept_dt, report_nm, rcept_no) 최신순으로 모은다.

    FUND_OUTFLOW/ACQ_REVIEW 신호가 매칭된 공시 + 신호 매칭 여부와 무관하게
    제목만으로 판별되는 처분(양도) 결정을 합쳐 중복 제거한다.
    """
    items: dict[str, tuple[str, str]] = {}
    for e in signal_events:
        # ASSET_TRANSFER(자산 처분·양도)도 상대방 확인 대상이다 — taxonomy 5.3이
        # "특수관계인에게 공정가 미만으로 이전"이라 상대·관계 없이는 정상적인
        # 자산 교체와 구분되지 않는다(2026-08-22, 1년 실측 약 200건).
        if e["key"] not in ("FUND_OUTFLOW", "ACQ_REVIEW", "ASSET_TRANSFER") or e["is_amendment"]:
            continue
        rcept = e.get("rcept_no", "")
        if not rcept:
            continue
        items.setdefault(rcept, (e["rcept_dt"], e["report_nm"]))
    for d in disclosures:
        if resolve_decision_type(d.get("report_nm", "")) not in _OUTFLOW_DIV_DECISION_TYPES:
            continue
        rcept = d.get("rcept_no", "")
        if not rcept:
            continue
        items.setdefault(rcept, (d.get("rcept_dt", "")[:10], d.get("report_nm", "")))
    return sorted(
        ((rcept, dt, nm) for rcept, (dt, nm) in items.items()),
        key=lambda t: t[1], reverse=True,
    )


def _outflow_row(
    rcept_dt: str, report_nm: str, rcept_no: str,
    counterparty: str, relation: str, classification: str, amount: int,
) -> dict:
    return {
        "rcept_dt": rcept_dt, "report_nm": report_nm, "rcept_no": rcept_no,
        "counterparty": counterparty, "relation": relation,
        "classification": classification, "amount": amount,
    }


# 자산 처분·양도 서식인가 — DS005(resolve_decision_type)로 읽히지 않는 제목을
# 원문 파서로 넘기기 위한 판별. ASSET_TRANSFER 키워드와 짝을 이룬다.
_ASSET_DISPOSAL_TITLE_MARKS = (
    "유형자산처분", "비유동자산처분", "유형자산양도",
    "특수관계인에대한자산양도", "영업양도",
)


def _is_asset_disposal_title(report_nm: str) -> bool:
    flat = (report_nm or "").replace(" ", "")
    return any(m in flat for m in _ASSET_DISPOSAL_TITLE_MARKS)


def _confirm_outflow_counterparties(
    signal_events: list[dict],
    disclosures: list[dict],
    corp_code: str,
    decisions_by_rcept: "dict[str, dict] | None" = None,
) -> list[dict]:
    """자금유출·양수거래(+처분) 공시 최근 최대 4건의 상대방·관계를 확인한다.

    - 금전대여·채무보증·담보제공(DS005에 없음): fetch_outflow_detail로 원문 직접 확인.
    - 유형자산·영업·타법인 주식 양수/양도(DS005): 이미 fetch된 decisions_by_rcept를
      재사용해 추가 호출 없이 채운다. 없으면(캐시 밖) 최대 2건까지만 보충 조회한다.
    """
    decisions_by_rcept = decisions_by_rcept or {}
    candidates = _outflow_review_candidates(signal_events, disclosures)[:4]

    out: list[dict] = []
    extra_fetches = 0
    for rcept, rcept_dt, report_nm in candidates:
        dtype = resolve_decision_type(report_nm)
        if dtype:
            r = decisions_by_rcept.get(rcept)
            if r is None and extra_fetches < 2:
                extra_fetches += 1
                try:
                    _r = fetch_major_decision(rcept, _DART_API_KEY, dtype, corp_code)
                    r = _r if "error" not in _r else None
                except Exception:
                    r = None
            if r is None:
                out.append(_outflow_row(rcept_dt, report_nm, rcept, "", "", "unknown", 0))
                continue
            relation = r.get("relation_text") or ""
            cls = (
                classify_outflow_relation(relation) if relation
                else ("affiliated" if r.get("related_party") else "unknown")
            )
            out.append(_outflow_row(
                rcept_dt, report_nm, rcept,
                r.get("counterparty") or "", relation, cls, r.get("amount", 0),
            ))
        elif _is_asset_disposal_title(report_nm):
            # 「유형자산 처분결정」(자율공시)·「특수관계인에 대한 자산양도」(공정거래법)
            # 등은 resolve_decision_type이 빈 값이라 DS005로 못 읽는다. 원문에는
            # 거래상대·관계·가액이 구조적으로 있어 직접 파싱한다(실측 상대방 100%).
            try:
                detail = fetch_asset_disposal_detail(rcept, _DART_API_KEY)
            except Exception:
                detail = {}
            rel = (detail or {}).get("relation", "")
            out.append(_outflow_row(
                rcept_dt, report_nm, rcept,
                (detail or {}).get("counterparty", ""), rel,
                classify_outflow_relation(rel) if rel else "unknown",
                (detail or {}).get("amount", 0),
            ))
        else:
            try:
                detail = fetch_outflow_detail(rcept, _DART_API_KEY)
            except Exception:
                detail = {}
            if not detail or not detail.get("kind"):
                out.append(_outflow_row(rcept_dt, report_nm, rcept, "", "", "unknown", 0))
                continue
            cls = classify_outflow_relation(detail.get("relation", ""))
            out.append(_outflow_row(
                rcept_dt, report_nm, rcept,
                detail.get("counterparty", ""), detail.get("relation", ""),
                cls, detail.get("amount", 0),
            ))
    return out


def _format_affiliate_stake_line(stake: dict) -> str:
    """summarize_affiliate_stake 결과를 사실 문구 한 줄로 조립한다 (순수 함수).

    지분 변동이 사실상 없으면(값 없음 또는 0.005%p 미만) 지분 구간을 생략,
    순이익은 흑자/적자 구분 없이 부호 그대로 표기한다("conduit"/"경유" 같은
    구조 단정 어휘는 쓰지 않는다). 표기할 사실이 하나도 없으면 빈 문자열.
    """
    parts: list[str] = []
    if stake.get("first_acquired"):
        parts.append(f"최초취득 {stake['first_acquired']}")
    sb, se = stake.get("stake_begin"), stake.get("stake_end")
    if sb is not None and se is not None and abs(se - sb) >= 0.005:
        direction = "확대" if se > sb else "축소"
        parts.append(f"지분 {sb:.1f}→{se:.1f}% {direction}")
    profit = stake.get("recent_net_profit")
    if profit is not None:
        parts.append(f"피출자사 최근 순이익 {_format_amount(str(profit))}")
    return " · ".join(parts)


def _build_affiliate_stake_facts(confirmations: list[dict], corp_code: str) -> dict[str, str]:
    """종속회사로 확인된 상대방을 타법인 출자현황과 대조해 사실 문구를 만든다.

    subsidiary 분류 확인 항목이 없으면 API 호출 없이 빈 dict를 반환한다.
    있으면 직전 연도 → (실패 시) 그 전 연도 순으로 최대 2회만 조회한다.
    매칭 실패·API 실패는 조용히 생략(기존 표기 그대로) — 점수 가산 없음.
    """
    subs = [c for c in confirmations if c["classification"] == "subsidiary" and c.get("counterparty")]
    if not subs or not corp_code or not _DART_API_KEY:
        return {}
    year = datetime.now().year - 1
    rows: list[dict] = []
    for y in (year, year - 1):
        try:
            rows = fetch_affiliate_investments(corp_code, _DART_API_KEY, str(y))
        except Exception:
            rows = []
        if rows:
            break
    if not rows:
        return {}
    facts: dict[str, str] = {}
    for c in subs:
        row = match_affiliate_row(rows, c["counterparty"])
        if not row:
            continue
        line = _format_affiliate_stake_line(summarize_affiliate_stake(row))
        if line:
            facts[c["counterparty"]] = line
    return facts


def _render_outflow_confirmations(
    confirmations: list[dict], affiliate_facts: "dict[str, str] | None" = None
) -> list[str]:
    """확인된 상대방 목록을 출력 줄로 렌더링한다.

    affiliate_facts가 있고 상대방이 종속회사로 분류됐으면(_build_affiliate_stake_facts),
    타법인 출자현황 대조 사실을 해당 줄에 병기한다(후속 3위 — conduit 사실 병기).
    """
    affiliate_facts = affiliate_facts or {}
    lines: list[str] = []
    for c in confirmations:
        cp = c["counterparty"] or "(미확인)"
        cls_label = _OUTFLOW_CLASS_LABEL.get(c["classification"], "미확인")
        lines.append(f"- [{c['rcept_dt']}] {_clean_report_name(c['report_nm'])}")
        rel_txt = f" ({c['relation']})" if c["relation"] else ""
        amt_txt = f" — {_format_amount(str(c['amount']))}" if c.get("amount") else ""
        lines.append(f"  → 거래상대방: {cp} · 관계: {cls_label}{rel_txt}{amt_txt}")
        if c["classification"] == "subsidiary":
            fact = affiliate_facts.get(c["counterparty"])
            if fact:
                lines.append(f"    ↳ 타법인출자현황: {fact}")
    return lines


# 실질 경영권 변경 제목 — SHAREHOLDER 신호 키워드에는 일상적 5% 보고
# ("주식등의대량보유상황보고서")도 포함되어 taxonomy 3.1이 흔하게 켜진다.
# 한농화성 실측(2026-08): 대량보유보고 2건 + 계열사 대여만으로 패턴이
# 발화하는 오탐이 확인돼, 패턴 게이트는 제목 수준의 실질 경영권 변경
# (최대주주변경·경영권)을 별도로 요구한다.
_CONTROL_CHANGE_TITLE_RE = re.compile(r"최대주주\s*변경|경영권")


def _has_control_change_title(disclosures: list[dict]) -> bool:
    """조회 창 내에 실질 경영권 변경 계열 제목의 공시가 있는지."""
    return any(
        _CONTROL_CHANGE_TITLE_RE.search(d.get("report_nm") or "") for d in disclosures
    )


# ── v1.7.0: 최대주주변경 원문 상세 — 신규 최대주주 실체 사실 표기 ──────────
# 금감원 무자본 M&A 합동점검(2019-12-19): 적발 24사의 신규 최대주주 82%가
# 비외감법인·투자조합, 인수자금 대부분이 주식담보대출(단계①). 지금까지는
# "최대주주변경" 제목만 SHAREHOLDER 신호를 켰다 — 신규 최대주주가 누구인지,
# 자금을 어떻게 조달했는지는 원문을 열어야만 보였다. 이 블록은 조회 창 내
# 최근 최대주주변경 공시 1건의 원문을 추가로 확인해 사실만 표기한다
# (판정 없음, v0.8.5 원칙).
_CONTROL_CHANGE_REPORT_RE = re.compile(r"최대주주\s*변경")
# "최대주주 변경을 수반하는 주식양수도 계약 체결/해제"류 예고성 공시는
# "1. 변경내용" 구조 자체가 없어(parse_control_change_detail 대상 아님)
# 제목에 "계약"이 있으면 제외한다.
_CONTROL_CHANGE_PRECURSOR_RE = re.compile(r"계약")


def _find_latest_control_change(disclosures: list[dict]) -> "dict | None":
    """조회 창 내 최대주주변경(정정·예고성 공시 제외) 최근 1건을 찾는다."""
    candidates = [
        d for d in disclosures
        if not is_amendment_disclosure(d.get("report_nm") or "")
        and _CONTROL_CHANGE_REPORT_RE.search(d.get("report_nm") or "")
        and not _CONTROL_CHANGE_PRECURSOR_RE.search(d.get("report_nm") or "")
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda d: d.get("rcept_dt", ""))


def _control_change_actor_lines(name: str) -> list[str]:
    """신규 최대주주 명칭을 공개기록 레지스트리와 대조한다(사실 표기 — 판정 아님).

    레지스트리 미설정 시 lookup_actor가 조용히 빈 리스트를 반환하므로
    (load_known_actors 기본값 = 빈 스켈레톤) 여기서도 자연히 생략된다
    (기존 graceful 비활성화 관례).
    """
    stripped = strip_holder_suffix(name)
    recs = lookup_actor(stripped)
    if not recs:
        return []
    lines = ["  📎 공개기록 참고 (사실 표기 — 판정 아님):"]
    for r in recs:
        src = r.get("source", "")
        date = r.get("date", "")
        ev = r.get("evidence", "")
        tag = f"{src}({date})" if date else src
        lines.append(f"    • {stripped} — {tag}: {ev}")
    if any(actor_status(r) == "auto_matched" for r in recs):
        lines.append("    ⚠ 일부는 시장 공시 자동 매칭 (동일인 여부 미확인)")
    if any(actor_status(r) == "maintainer_seed" for r in recs):
        lines.append("    ⚠ 일부는 제작자 모니터링 등록 (공시 자동매칭 아님, 혐의·확정 아님)")
    lines.append("    ⚠ 원본 공시로 사실 확인 권장 · 동명이인 가능성 있음")
    return lines


_RP_KIND_LABEL = {
    "borrow": "자금차입", "collateral": "담보 제공받음", "investment": "출자", "": "거래",
}


def _related_party_detail_block(
    signal_events: list[dict], max_check: int = 3
) -> list[str]:
    """특수관계인 자금거래(들어오는 방향) 최근 건의 원문 확인 블록.

    taxonomy 4.2가 요구하는 것은 "가격 괴리"인데 제목에는 없다. 원문에는
    상대방·관계·금액과 **이자율**이 있어 조건을 눈으로 볼 수 있다
    (2026-08-22 실측: 이자율 4.6%~8.95%로 편차가 크고, 상대가 「동일인」인
    개인 차입도 있었다).

    원문 추출에 전부 실패하면 빈 리스트를 반환해 블록 자체를 생략한다
    (기존 심화 블록 관례). 점수 가산 없음(v0.8.5) — 판정 어휘를 쓰지 않는다.
    """
    picked: list[dict] = []
    seen: set[str] = set()
    for e in sorted(signal_events, key=lambda x: x.get("rcept_dt", ""), reverse=True):
        if e.get("key") != "RELATED_PARTY" or e.get("is_amendment"):
            continue
        rcept = e.get("rcept_no") or ""
        if not rcept or rcept in seen:
            continue
        seen.add(rcept)
        picked.append(e)
        if len(picked) >= max_check:
            break
    if not picked:
        return []

    rows: list[tuple[dict, dict]] = []
    for e in picked:
        try:
            detail = fetch_related_party_detail(e["rcept_no"], _DART_API_KEY)
        except Exception:
            detail = {}
        if detail and detail.get("counterparty"):
            rows.append((e, detail))
    if not rows:
        return []

    lines = [
        "",
        "🤝 **특수관계인 자금거래 확인**",
        "계열사·최대주주에게서 돈이나 담보를 받아온 건입니다. 이자율과 규모가"
        " 조건을 따져볼 지점입니다.",
    ]
    for e, d in rows:
        kind = _RP_KIND_LABEL.get(d.get("kind", ""), "거래")
        lines.append(
            f"- [{(e.get('rcept_dt') or '')[:10]}] {_clean_report_name(e.get('report_nm', ''))}"
        )
        rel = f" ({d['relation']})" if d.get("relation") else ""
        amt = f" — {_format_amount(str(d['amount']))}" if d.get("amount") else ""
        lines.append(f"  → {kind} 상대: {d['counterparty']}{rel}{amt}")
        extra: list[str] = []
        if d.get("interest_rate"):
            extra.append(f"이자율 {d['interest_rate']}%")
        if d.get("equity_ratio"):
            # 원문 표기 그대로 온다 — 숫자만이면 % 를 붙이고, "자본잠식" 같은
            # 문자 표기(dart_client.parse_related_party_detail 주석 참고)면
            # 그대로 둔다("자본잠식%"가 되지 않도록).
            _er = str(d["equity_ratio"]).strip()
            if re.fullmatch(r"-?[\d,]+(?:\.\d+)?", _er):
                _er += "%"
            extra.append(f"자기자본 대비 {_er}")
        if extra:
            lines.append("    " + " · ".join(extra))
    return lines


def _earnings_shock_block(
    signal_events: list[dict], max_check: int = 2
) -> list[str]:
    """손익구조 급변 공시 최근 건의 원문 확인 블록.

    제목만으로는 증가인지 감소인지 알 수 없다. 원문 표에 계정별
    **증감비율(%)**과 **흑자적자전환여부**가 있어 방향을 사실로 표기한다.
    """
    picked: list[dict] = []
    seen: set[str] = set()
    for e in sorted(signal_events, key=lambda x: x.get("rcept_dt", ""), reverse=True):
        if e.get("key") != "EARNINGS_SHOCK" or e.get("is_amendment"):
            continue
        rcept = e.get("rcept_no") or ""
        if not rcept or rcept in seen:
            continue
        seen.add(rcept)
        picked.append(e)
        if len(picked) >= max_check:
            break
    if not picked:
        return []

    rows: list[tuple[dict, dict]] = []
    for e in picked:
        try:
            detail = fetch_earnings_shock_detail(e["rcept_no"], _DART_API_KEY)
        except Exception:
            detail = {}
        if detail and detail.get("rows"):
            rows.append((e, detail))
    if not rows:
        return []

    lines = ["", "📉 **손익구조 급변 내역**"]
    for e, d in rows:
        lines.append(
            f"- [{(e.get('rcept_dt') or '')[:10]}] {_clean_report_name(e.get('report_nm', ''))}"
        )
        for r in d["rows"]:
            pct = (
                f"{r['change_pct']:+.1f}%" if r["change_pct"] is not None else "—"
            )
            turn = f" · {r['turn']}" if r["turn"] else ""
            lines.append(f"    {r['account']}: {pct}{turn}")
    return lines


def _control_change_detail_block(d: dict) -> list[str]:
    """최대주주변경 공시 1건의 원문에서 뽑은 신규 최대주주 상세 블록.

    원문 추출 실패(빈 dict) 시 빈 리스트를 반환해 블록 자체를 생략한다
    (기존 심화 블록 관례 — capital_backflow 게이트와 동일 태도). 점수
    가산 없음(v0.8.5), 판정 어휘 없음 — 명칭·유형·자금은 사실 표기만.
    """
    rcept_no = d.get("rcept_no", "")
    detail = fetch_control_change_detail(rcept_no, _DART_API_KEY)
    if not detail:
        return []
    prev = detail["prev_holder"] or "(미기재)"
    new = detail["new_holder"] or "(미기재)"
    ratio_txt = f" ({detail['new_ratio']:.2f}%)" if detail["new_ratio"] else ""
    holder_type = classify_holder_type(detail["new_holder"])

    lines = [
        "",
        "🔁 **최대주주 변경 상세**",
        f"[{(d.get('rcept_dt') or '')[:10]}] {_clean_report_name(d.get('report_nm', ''))}",
        f"  변경전 → 변경후: {prev} → {new}{ratio_txt}",
        f"  명칭 기준: {holder_type}",
    ]
    if detail["reason"]:
        lines.append(f"  변경사유: {detail['reason']}")
    if detail["purpose"]:
        lines.append(f"  지분인수목적: {detail['purpose']}")

    self_fund_txt = _format_amount(str(detail["self_fund"])) if detail["self_fund"] else "0원"
    fund_line = f"  인수자금: 자기자금 {self_fund_txt}"
    if detail["borrowed_fund"]:
        fund_line += f" / 차입금 {_format_amount(str(detail['borrowed_fund']))}"
    lines.append(fund_line)

    if detail["borrowed_fund"] > 0:
        if detail["lender"]:
            lines.append(f"    차입처: {detail['lender']}")
        if detail["collateral"]:
            lines.append(f"    담보내역: {detail['collateral']}")
        lines.append(
            "    ※ 금감원 무자본 M&A 합동점검(2019-12-19)은 주식담보 차입을 통한 "
            "인수를 무자본 M&A 인수 단계로 지목했습니다(사실 인용)."
        )

    lines += _control_change_actor_lines(detail["new_holder"])
    return lines


def _confirm_acquisition_targets(
    signal_events: list[dict],
    disclosures: list[dict],
    max_check: int = 3,
) -> list[dict]:
    """ACQ_REVIEW(타법인 주식·출자증권 취득/양수) 최근 건의 대상사·관계를 확인한다.

    DS005를 쓰지 않고 **원문을 직접 읽는다**(2026-08-22 실측 근거):
      · 「타법인주식및출자증권취득결정」(자율공시, 실측상 4배 흔함)은
        `resolve_decision_type`이 빈 값을 돌려줘 DS005 조회 자체가 불가능하다.
      · 법정 「주요사항보고서(…양수결정)」조차 DS005가 "구조화 데이터 없음"을
        반환하는 사례가 실측됐다(KR모터스 20251001, 코아스 20250904).
    반면 원문은 두 서식 모두 구조가 일정해 `parse_acquisition_detail`이
    25개사 32건 표본에서 **32/32(100%)** 파싱에 성공했다.

    Returns: 확인 행 목록. 각 행은 rcept_dt/report_nm/rcept_no/issuer/
    relation/classification/amount/equity_ratio.
    """
    by_rcept = {d.get("rcept_no"): d for d in disclosures}
    picked: list[dict] = []
    seen: set[str] = set()
    for e in sorted(signal_events, key=lambda x: x.get("rcept_dt", ""), reverse=True):
        if e.get("key") != "ACQ_REVIEW" or e.get("is_amendment"):
            continue
        rcept = e.get("rcept_no") or ""
        if not rcept or rcept in seen:
            continue
        seen.add(rcept)
        picked.append(e)
        if len(picked) >= max_check:
            break

    out: list[dict] = []
    for e in picked:
        rcept = e["rcept_no"]
        d = by_rcept.get(rcept, {})
        row = {
            "rcept_dt": e.get("rcept_dt", "") or d.get("rcept_dt", ""),
            "report_nm": e.get("report_nm", "") or d.get("report_nm", ""),
            "rcept_no": rcept, "issuer": "", "relation": "",
            "classification": "unknown", "amount": 0, "equity_ratio": 0.0,
            "nation": "", "listing": "unknown",
        }
        try:
            det = fetch_acquisition_detail(rcept, _DART_API_KEY)
        except Exception:
            det = {}
        if det and det.get("issuer"):
            row["issuer"] = det["issuer"]
            row["relation"] = det.get("relation", "")
            row["amount"] = det.get("amount", 0)
            row["equity_ratio"] = det.get("equity_ratio", 0.0)
            row["classification"] = classify_outflow_relation(det.get("relation", ""))
            row["nation"] = det.get("nation", "")
            # 금감원 무자본 M&A 합동점검(2019-12)의 "유용 최대 경로는 비상장주식
            # 취득(55%)" 축. 판정은 사실 표기용이며 게이트 통과 조건에는 쓰지
            # 않는다 — 정상적인 비상장 자회사 편입도 대부분 비상장이기 때문.
            try:
                row["listing"] = classify_target_listing(
                    det.get("issuer", ""), det.get("nation", "")
                )
            except Exception:
                row["listing"] = "unknown"
        out.append(row)
    return out


# 취득 대상의 국내 상장 여부 표시 라벨. 미확인은 아무것도 붙이지 않는다
# (없는 사실을 만들어 표기하지 않는다는 v0.8.5 원칙).
_ACQ_LISTING_LABEL = {"listed": "(상장)", "unlisted": "(비상장)", "unknown": ""}


def _render_acquisition_confirmations(confirmations: list[dict]) -> list[str]:
    """확인된 취득 대상 목록을 출력 줄로 렌더링한다(사실 표기만)."""
    lines: list[str] = []
    for c in confirmations:
        tgt = c["issuer"] or "(미확인)"
        cls_label = _OUTFLOW_CLASS_LABEL.get(c["classification"], "미확인")
        lines.append(f"- [{c['rcept_dt']}] {_clean_report_name(c['report_nm'])}")
        rel_txt = f" ({c['relation']})" if c["relation"] else ""
        amt_txt = f" — {_format_amount(str(c['amount']))}" if c.get("amount") else ""
        ratio_txt = (
            f" · 자기자본 대비 {c['equity_ratio']:.1f}%" if c.get("equity_ratio") else ""
        )
        listing_txt = _ACQ_LISTING_LABEL.get(c.get("listing", "unknown"), "")
        nation_txt = f" · 국적 {c['nation']}" if c.get("nation") else ""
        lines.append(
            f"  → 취득 대상: {tgt}{listing_txt}{nation_txt} · 관계: "
            f"{cls_label}{rel_txt}{amt_txt}{ratio_txt}"
        )
    return lines


def _fund_diversion_gate(confirmations: list[dict]) -> dict:
    """fund_diversion_chain 발화 여부를 확인된 취득 대상 관계로 판정한다(순수 함수).

    발화 조건: classification == "affiliated"(계열·특수관계·최대주주·주요주주)
    **이면서 취득 대상이 비상장(listing == "unlisted")**인 건이 1건 이상.
    미충족 시 대체 사실 블록 라인을 만들어 반환한다 —
    `_capital_backflow_gate`와 같은 구조다.

    **왜 관계인가 (2026-08-22 실측)**: 이 패턴은 요구 신호가 1.1+5.8 둘뿐이라
    겹침 2개면 곧 전부 일치이고, 재현율 수정 후 1년 기준 **142개사**에서
    발화한다 — 제목만으로는 정상적인 사업 확장 M&A와 구분되지 않는다.
    게이트 후보를 셋 재봤다(25개사·32건 원문 전수):

      · **비상장 대상 여부** — 금감원 근거("조달자금 유용의 최대 경로가
        비상장주식 취득 55%")에 가장 충실하지만, 대상사 이름을 corpCode에서
        찾지 못하는 건이 **23/32(72%)**라 판정 자체가 안 된다. 기각.
      · **자기자본 대비 과대** — 중앙값 13.8%, 최대 52.1%로 100% 초과가 0건.
        임계를 어디에 두든 거의 전부를 차단하거나 아무것도 못 거른다. 기각.
      · **관계 표기** — 계열회사 7 · 최대주주/주요주주/관계회사 3 ·
        종속회사 2 · 무관계("-") 19 · 미확인 1. **확인율이 높고 판별력이 있다.**

    회사 단위 통과율은 25곳 중 8곳(32%)으로, 142개사 기준 약 45개사까지
    좁혀진다 — 게이트가 실제로 작동하면서 전부 차단하지도 않는다.

    종속회사(subsidiary)는 통과시키지 않는다 — 모회사가 자회사 지분을 늘리는
    것은 정상적인 지배구조 정리라 `capital_backflow`와 같은 판단이다.
    """
    if not confirmations:
        return {"pass": False, "affiliated": [], "fact_lines": []}

    affiliated = [c for c in confirmations if c["classification"] == "affiliated"]
    # 통과 조건은 **계열·특수관계 AND 비상장 대상**이다(2026-08-22 강화).
    # 금감원 무자본 M&A 합동점검이 집계한 유용 경로가 "비상장주식 취득 55%"라
    # 두 축이 함께 서야 이 패턴의 근거와 맞는다. 70건 실측에서 계열 확인 10건 중
    # 8건이 비상장이었고, 빠지는 2건은 **지주회사가 상장 계열사 지분을 취득한
    # 건**이었다(녹십자홀딩스→녹십자웰빙, 사토시홀딩스→한국첨단소재) — 정상적인
    # 그룹 내 거래라 조준이 정확하다.
    #
    # 상장 여부가 unknown이면 통과시키지 않는다 — 비상장이라는 것을 확인하지
    # 못했다는 뜻이고, CRITICAL 카드는 확인된 사실 위에서만 띄운다.
    core = [c for c in affiliated if c.get("listing") == "unlisted"]
    if core:
        return {"pass": True, "affiliated": core, "fact_lines": []}

    if affiliated:
        # 계열 취득은 맞지만 대상이 상장사(또는 상장 여부 미확인)인 경우 —
        # 금감원이 지적한 비상장주식 취득 경로와는 다르다는 사실을 남긴다.
        listed_only = all(c.get("listing") == "listed" for c in affiliated)
        why = (
            "대상이 모두 상장사라 금감원이 지적한 비상장주식 취득 경로와는 다릅니다"
            if listed_only
            else "대상의 상장 여부를 원문에서 확인하지 못했습니다"
        )
        lines = [
            f"타법인 주식·출자증권 취득 {len(confirmations)}건 — 계열·특수관계 "
            f"취득 {len(affiliated)}건이 확인됐으나 {why}",
        ]
        lines += _render_acquisition_confirmations(confirmations)
        return {"pass": False, "affiliated": affiliated, "fact_lines": lines}

    known = [c for c in confirmations if c["classification"] != "unknown"]
    if known:
        labels = sorted({_OUTFLOW_CLASS_LABEL[c["classification"]] for c in known})
        lines = [
            f"타법인 주식·출자증권 취득 {len(confirmations)}건 — 확인된 대상은 "
            f"{'/'.join(labels)}(각 실명·관계 표기), 계열·특수관계 취득은 미확인",
        ]
        lines += _render_acquisition_confirmations(confirmations)
        return {"pass": False, "affiliated": [], "fact_lines": lines}

    rcepts = ", ".join(c["rcept_no"] for c in confirmations if c["rcept_no"])
    return {
        "pass": False, "affiliated": [],
        "fact_lines": [f"취득 대상 미확인 — 원문 확인 필요 (rcept: {rcepts})"],
    }


def _capital_backflow_gate(
    confirmations: list[dict],
    has_control_change: bool = True,
    affiliate_facts: "dict[str, str] | None" = None,
) -> dict:
    """capital_backflow 발화 여부를 확인된 상대방 관계로 판정한다(순수 함수).

    발화 조건: ① 창 내 실질 경영권 변경 제목 존재(has_control_change) AND
    ② classification == "affiliated" 항목이 1건 이상.
    미충족 시 대체 사실 블록 라인을 만들어 반환한다(원문 확인 없이 경고하지
    않는다는 v0.8.5 원칙 — 관계가 전부 미확인이면 패턴은커녕 사실 블록도
    '확인 필요' 안내로 그친다). affiliate_facts는 판정에 관여하지 않는 순수
    렌더링 재료다 — 종속회사 상대의 타법인 출자현황 사실을 fact_lines에
    병기할 뿐, pass/affiliated 계산에는 영향을 주지 않는다(후속 3위).
    """
    if not confirmations:
        return {"pass": False, "affiliated": [], "fact_lines": []}

    affiliated = [c for c in confirmations if c["classification"] == "affiliated"]

    if not has_control_change:
        # 유출 상대는 확인됐어도 경영권 변경이라는 전제 자체가 없다 —
        # 패턴 미적용, 확인된 사실만 나열 (일상적 계열 지원과 구분).
        lines = [
            "자금유출성 공시 상대방 확인 — 조회 창 내 실질 경영권 변경"
            "(최대주주변경 등) 공시는 없어 자금 역류 패턴은 적용하지 않음",
        ]
        lines += _render_outflow_confirmations(confirmations, affiliate_facts)
        return {"pass": False, "affiliated": affiliated, "fact_lines": lines}
    if affiliated:
        return {"pass": True, "affiliated": affiliated, "fact_lines": []}

    known = [c for c in confirmations if c["classification"] != "unknown"]
    if known:
        labels = sorted({_OUTFLOW_CLASS_LABEL[c["classification"]] for c in known})
        lines = [
            f"자금유출성 공시 {len(confirmations)}건 — 확인된 상대방은 "
            f"{'/'.join(labels)}(각 실명·관계 표기), 특수관계 유출은 미확인",
        ]
        lines += _render_outflow_confirmations(confirmations, affiliate_facts)
        return {"pass": False, "affiliated": [], "fact_lines": lines}

    rcepts = ", ".join(c["rcept_no"] for c in confirmations if c["rcept_no"])
    return {
        "pass": False, "affiliated": [],
        "fact_lines": [f"상대방 미확인 — 원문 확인 필요 (rcept: {rcepts})"],
    }


def _taxonomy_dates(
    events: list, key_to_tax: dict, fallback_date: str = ""
) -> "dict[str, list[str]]":
    """관찰 이벤트를 {taxonomy id: [YYYYMMDD, ...]}로 접는다(패턴 창 게이트 입력).

    날짜 표기는 호출부마다 다르다 — list.json은 "20260616", 자금사용 레코드는
    "2026-01-25"나 "2026-00-00"이 온다. 숫자만 남겨 앞 8자리를 쓰고, 8자리가
    안 되면 버린다("2026-00-00"의 월·일 0은 창 비교에서 의미가 없다).

    날짜가 없는 합성 이벤트(CAPITAL_CHURN·재무 YoY 플래그)는 `fallback_date`로
    둔다 — 이들은 제목 없이 스캔 창 전체를 근거로 만들어지므로 최신일에
    놓는 것이 의미에 맞다(CAPITAL_CHURN 자체가 "최근 12개월 집중"이다).
    """
    out: "dict[str, list[str]]" = {}
    for e in events:
        if e.get("is_amendment"):
            continue
        raw = "".join(ch for ch in str(e.get("rcept_dt") or "") if ch.isdigit())
        dt = raw[:8] if len(raw) >= 8 else ""
        if len(dt) == 8 and dt[4:6] != "00" and dt[6:8] != "00":
            pass
        else:
            dt = fallback_date
        if not dt:
            continue
        for tid in key_to_tax.get(e["key"], []):
            out.setdefault(tid, []).append(dt)
    return out


def _render_pattern_watch_block(
    tax_ids: "list[str] | set[str]",
    outflow_confirmations: list[dict],
    has_control_change: bool,
    affiliate_facts: "dict[str, str] | None" = None,
    max_show: int = 3,
    taxonomy_dates: "dict[str, list[str]] | None" = None,
    acq_confirmations: "list[dict] | None" = None,
) -> tuple[list[str], list[str], list[dict]]:
    """관찰된 taxonomy와 등록 패턴의 부분 겹침을 "무엇이 보이고 무엇이 안
    보이는지" 사실로 렌더한다(analyze_company_risk·build_event_timeline 공용).

    "전부 일치할 때만 발화"(find_pattern_match)에서 "관찰된 만큼 보여주고
    무엇을 확인할지 알려주기"(find_pattern_overlaps)로 바꾼 렌더러 — 실측상
    전부 일치는 회사당 0.2개뿐이라 등록 패턴의 checkpoints가 사실상 노출되지
    않았다. 판정 어휘(위험·의심·가능성 높음·해당됨)를 쓰지 않는다(v0.8.5
    무판정 원칙) — "구성 신호 N개 중 M개가 관찰됐다"는 사실 서술만 한다.

    capital_backflow는 v1.6.1에서 도입된 내용 확인 게이트를 그대로
    보존한다 — 이 패턴은 signal_sequence가 2개뿐이라 min_overlap=2에서
    겹침 목록에 나타나는 순간 이미 전부 일치이므로, 게이트가 실패하면
    부분 관찰 표기에서도 목록에서 완전히 제외하고 기존 사실 블록
    (capital_backflow_fact_lines)으로 대체한다 — 게이트를 우회해 "2개 중
    2개 관찰"로 표시하면 v1.6.1이 없앤 오탐이 되살아난다.

    Returns:
        (lines, capital_backflow_fact_lines, filtered) — lines는 겹치는
        패턴이 없으면 빈 리스트(블록 자체 생략). capital_backflow_fact_lines는
        게이트가 실패했을 때만 채워진다(기존 elif 경로와 동일하게 호출부가
        렌더). filtered는 게이트를 통과한 겹침 전체(표시 상한 적용 전) —
        호출부가 요약 문장에서 최상위 겹침 하나를 참조할 때 쓴다.
    """
    overlaps = find_pattern_overlaps(
        list(tax_ids), min_overlap=2, taxonomy_dates=taxonomy_dates
    )

    cb_gate: "dict | None" = None
    capital_backflow_fact_lines: list[str] = []
    fund_diversion_fact_lines: list[str] = []
    filtered: list[dict] = []
    for ov in overlaps:
        if ov["pattern_id"] == "capital_backflow":
            cb_gate = _capital_backflow_gate(
                outflow_confirmations, has_control_change, affiliate_facts
            )
            if not cb_gate["pass"]:
                capital_backflow_fact_lines = cb_gate["fact_lines"]
                continue
        elif ov["pattern_id"] == "fund_diversion_chain":
            # capital_backflow와 같은 이유의 내용 확인 게이트 — 이 패턴도
            # 요구 신호가 2개(1.1+5.8)뿐이라 겹침 2개면 곧 전부 일치이고,
            # 제목만으로는 정상 사업확장 M&A와 구분되지 않는다(1년 실측
            # 142개사 발화). 취득 대상이 계열·특수관계로 확인될 때만 표시.
            fd_gate = _fund_diversion_gate(acq_confirmations or [])
            if not fd_gate["pass"]:
                fund_diversion_fact_lines = fd_gate["fact_lines"]
                continue
        filtered.append(ov)

    # 두 게이트의 대체 사실 블록은 성격이 달라 각자의 헤더를 달고 나간다
    # (합쳐서 한 헤더 아래 두면 취득 대상이 "자금유출 상대방"으로 표시된다).
    # capital_backflow 겹침이 아예 없으면 게이트가 호출되지 않아 확인 결과가
    # 렌더되지 않았다 — 자산 처분·양도만 있는 회사(3.1이 없어 패턴 자체가 성립
    # 안 함)에서 "누구에게 팔았나"가 통째로 사라졌다(2026-08-22 실측: 흥아해운·
    # 효성투자개발). 확인된 상대방은 패턴 주장이 아니라 사실이므로 그대로 낸다.
    if outflow_confirmations and cb_gate is None and not capital_backflow_fact_lines:
        capital_backflow_fact_lines = _render_outflow_confirmations(
            outflow_confirmations, affiliate_facts
        )

    _fact_lines: list[str] = []
    if capital_backflow_fact_lines:
        _fact_lines += ["━━ 자금유출·자산이전 상대방 확인 ━━"] + capital_backflow_fact_lines
    if fund_diversion_fact_lines:
        if _fact_lines:
            _fact_lines.append("")
        _fact_lines += ["━━ 타법인 취득 대상 확인 ━━"] + fund_diversion_fact_lines
    if not filtered:
        return [], _fact_lines, []

    lines: list[str] = ["", "━━ 관찰된 신호가 겹치는 등록 패턴 ━━"]
    shown = filtered[:max_show]
    for ov in shown:
        matched_labels = " · ".join(
            f"{taxonomy_label_ko(t)}({t})" for t in ov["matched"]
        )
        lines.append("")
        lines.append(
            f"▸ {ov['name']} — 구성 신호 {ov['n_total']}개 중 "
            f"{ov['n_matched']}개가 이 기간 공시에서 관찰됐습니다"
        )
        lines.append(f"   관찰됨: {matched_labels}")
        if ov["missing"]:
            missing_labels = " · ".join(
                f"{taxonomy_label_ko(t)}({t})" for t in ov["missing"]
            )
            lines.append(f"   안 보임: {missing_labels}")
        if ov["checkpoints"]:
            lines.append("   확인해볼 것:")
            for cp in ov["checkpoints"]:
                lines.append(f"     - {cp}")
        if ov["pattern_id"] == "capital_backflow" and cb_gate and cb_gate["affiliated"]:
            lines.append("   확인된 특수관계 유출:")
            for _c in cb_gate["affiliated"]:
                _amt = _format_amount(str(_c["amount"])) if _c.get("amount") else ""
                _amt_txt = f", {_amt}" if _amt else ""
                lines.append(
                    f"     - {_c['counterparty'] or '(미확인)'}"
                    f"({_c['relation'] or '계열·특수관계'}{_amt_txt})"
                )

    if len(filtered) > max_show:
        lines.append("")
        lines.append(f"외 {len(filtered) - max_show}개 패턴이 2개 이상 겹칩니다.")

    return lines, _fact_lines, filtered


# ── 도구 1: 기업 종합 위험 분석 ────────────────────────────────────────────


@mcp.tool()
def analyze_company_risk(
    company_name: str,
    lookback_years: int = 1,
    lookback_days: int | None = None,
    from_date: str = "",
    to_date: str = "",
) -> str:
    """기업명 또는 종목코드로 공시 기반 불공정거래 위험 신호를 분석한다.

    공개기록 레지스트리(opt-in)가 설정돼 있고 이 회사가 등재 행위자의
    관련기업으로 태깅된 경우, 리포트 말미에 공개기록 참고 섹션이 추가된다.

    Args:
        company_name: 기업명 (예: "에코프로") 또는 종목코드 6자리 (예: "086520")
        lookback_years: 조회 기간(년). 기본 1년, 1~5년 범위. 1년을 넘으면
            원문 사실 블록 없이 신호·패턴·타임라인만 담은 "지도"가 된다 —
            특정 구간을 깊게 보려면 from_date/to_date로 좁혀 다시 조회한다.
        from_date: 조회 시작일(선택). "2024-01-01"·"20240101" 형식. 주면
            lookback_years는 무시된다.
        to_date: 조회 종료일(선택). 미지정 시 오늘. from_date만 주면 그날부터
            오늘까지, to_date만 주면 그날 기준 1년.
    """
    if not _DART_API_KEY:
        return "❌ DART_API_KEY 환경변수가 설정되지 않았습니다."

    bgn_de, end_de, lookback_days, max_pages, window_phrase, win_err = _resolve_window(
        lookback_years, lookback_days, from_date, to_date
    )
    if win_err:
        return f"❌ {win_err}"
    deep = _is_deep_window(lookback_days)

    # 1. 기업 조회
    result = resolve_corp(company_name, _DART_API_KEY)
    if not result:
        return f"❌ '{company_name}'에 해당하는 기업을 DART에서 찾을 수 없습니다."
    corp_name, corp_info = result
    corp_code = corp_info["corp_code"]
    stock_code = corp_info.get("stock_code", "")

    # 2. 공시 목록 조회
    disclosures, fetch_status = fetch_company_disclosures_with_status(
        corp_code, _DART_API_KEY, lookback_days, max_pages=max_pages,
        bgn_de=bgn_de, end_de=end_de,
    )
    if fetch_status == FETCH_ERROR:
        return _fetch_failed_notice(corp_name, window_phrase)
    # (조기 반환 제거 — 공시가 없어도 v0.6.0 자본 churn / 재무 이상 스캔은 별도로 수행)

    # 3. 신호 분류 + 정정공시 필터
    signal_events: list[dict] = []
    cb_rcept_nos: list[str] = []

    for d in disclosures:
        report_nm = d.get("report_nm", "")
        rcept_no = d.get("rcept_no", "")
        rcept_dt = d.get("rcept_dt", "")[:10]
        is_amendment = is_amendment_disclosure(report_nm)
        parsed = parse_report_name(report_nm)
        matched = match_signals(report_nm)
        # '[정정명령부과]증권신고서'처럼 _AMENDMENT_RE에 걸리지만 실제
        # 정정이 아닌 공시는 접두를 벗겨 재매칭한다. 진짜 정정공시의
        # 기존 동작(신호 없음)은 바뀌지 않는다.
        if not matched and is_amendment and is_false_amendment(parsed):
            matched = match_signals(strip_amendment_prefix(report_nm))
            # is_false_amendment가 참이라는 것은 이 태그가 정정 꼬리표가
            # 아니라는 단언이다. 플래그를 True로 남겨두면 신호를 되살려
            # 놓고도 non_amend_events·sig_keys·헤드라인에서 다시 빼버려
            # 헤더 건수와 본문이 어긋난다(리뷰 C2).
            is_amendment = False
        qualified = qualify_signals(matched, parsed, d)

        for sig, q in zip(matched, qualified):
            signal_events.append(
                {
                    "key": sig["key"],
                    "label": q.label,
                    "score": 0 if is_amendment else sig["score"],
                    "report_nm": report_nm,
                    "rcept_dt": rcept_dt,
                    "rcept_no": rcept_no,
                    "is_amendment": is_amendment,
                    "tier": q.tier,
                    "reason": q.reason,
                    "note": q.note,
                }
            )
            if sig["key"] == "CB_BW" and not is_amendment and rcept_no:
                cb_rcept_nos.append(rcept_no)

    # v0.5.0: DS005 결정 공시 최신 10건 구조화 ------------------
    decision_items = [
        d for d in disclosures
        if resolve_decision_type(d.get("report_nm", ""))
    ][:10]
    decisions: list[tuple[dict, dict]] = []
    failed_decisions = 0
    for _d in decision_items:
        _dtype = resolve_decision_type(_d["report_nm"])
        _r = fetch_major_decision(_d["rcept_no"], _DART_API_KEY, _dtype, corp_code)
        if "error" in _r:
            failed_decisions += 1
            continue
        decisions.append((_d, _r))

    # v0.5.0: 자금사용내역 (최근 3년 고정) -------------------------
    fund_records = fetch_fund_usage(corp_code, _DART_API_KEY, 3)

    # v0.9.0: 부실 후속 이벤트(부도/영업정지/회생/해산) 흡수 — 발생 시 사실 표기만 ------
    # 연 단위 API라 올림으로 맞추고(365일→1년; 기존 +1은 기본 조회에서
    # 2년치를 수집해 조회 기간 밖 이벤트가 섞였다 — 감사 E-3), 연 경계
    # 잔여분은 rcept_dt 컷오프로 정확히 창을 맞춘다.
    distress_events = fetch_distress_events(
        corp_code, _DART_API_KEY,
        max(1, (lookback_days + 364) // 365),
    )
    _distress_cutoff = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y%m%d")
    for _de in distress_events:
        if (_de.get("rcept_dt") or "") and _de["rcept_dt"] < _distress_cutoff:
            continue
        signal_events.append({
            "key": "DISTRESS_EVENT",
            "label": "부실 단계 진입",
            "score": 0,
            "report_nm": _de.get("summary") or "부실 사건",
            "rcept_dt": _de.get("rcept_dt", ""),
            "rcept_no": _de.get("rcept_no", ""),
            "is_amendment": False,
            "subtype": _de.get("subtype"),
        })

    # v0.5.0: 신규 플래그를 signal_events에 합산 (패턴 매칭용) ----
    _v5_lookup = {s["key"]: s for s in SIGNAL_TYPES}
    for _d, _r in decisions:
        for _fkey in _r["flags"]:
            _meta = _v5_lookup.get(_fkey, {"label": _fkey, "score": 3})
            signal_events.append({
                "key": _fkey,
                "label": _meta["label"],
                "score": _meta["score"],
                "report_nm": f"[결정:{_r['decision_type']}] {_r.get('counterparty', '') or _d['report_nm']}",
                "rcept_dt": _d.get("rcept_dt", "")[:10],
                "rcept_no": _d.get("rcept_no", ""),
                "is_amendment": False,
            })
    for _rec in fund_records:
        for _fkey in _rec["flags"]:
            _meta = _v5_lookup.get(_fkey, {"label": _fkey, "score": 3})
            signal_events.append({
                "key": _fkey,
                "label": _meta["label"],
                "score": _meta["score"],
                "report_nm": _format_fund_event_name(_rec),
                "rcept_dt": _rec.get("pay_de", "") or f"{_rec.get('year', '')}-00-00",
                "rcept_no": "",
                "is_amendment": False,
            })

    # 한정층 — 공시에서 온 신호만 tier를 갖는다. 재무·부실 플래그(DISTRESS_EVENT·
    # 결정 공시 플래그·자금사용 플래그, 아래에서 append될 CAPITAL_CHURN·재무제표
    # YoY 이상 포함)는 제목이 없어 한정 대상이 아니므로 기본값 observed로 남는다.
    # detect_capital_churn·재무이상 스캔이 procedural(제목 기반 강등) 신호까지
    # 세지 않도록, 이 두 탐지보다 앞에서 분리한다 — 이후 두 탐지가 신호를
    # 추가하면 observed_events에도 함께 추가한다(둘 다 제목이 없어 태생적으로
    # observed 취급).
    observed_events = [
        e for e in signal_events
        if e.get("tier", TIER_OBSERVED) == TIER_OBSERVED
    ]
    procedural_events = [
        e for e in signal_events
        if e.get("tier", TIER_OBSERVED) != TIER_OBSERVED
    ]

    # ============ v0.6.0 블록 시작 ============
    # 자본 churn 탐지 (최근 12개월 window) — procedural로 강등된 신호는
    # 반복 횟수에 포함시키지 않는다(observed_events만 사용).
    try:
        churn = detect_capital_churn(observed_events, lookback_years=1)
        if "CAPITAL_CHURN" in churn["flags"]:
            _churn_event = {
                "key": "CAPITAL_CHURN",
                "label": "자본 이벤트 과다 반복",
                "score": 7,
                "report_nm": f"최근 12개월 내 자본 이벤트 {churn['max_12m_count']}건 집중",
                "rcept_dt": "",
                "rcept_no": "",
                "is_amendment": False,
            }
            signal_events.append(_churn_event)
            observed_events.append(_churn_event)
    except Exception:
        churn = {"flags": [], "events": [], "max_12m_count": 0, "total_events": 0, "by_year": {}}

    # 재무이상 스캔 (당기/전기)
    _v6_labels = {
        "AR_SURGE": ("매출채권/매출 비율 급등", 8),
        "INVENTORY_SURGE": ("재고자산/매출 비율 급등", 7),
        "CASH_GAP": ("순이익·현금흐름 괴리", 8),
        "CAPITAL_IMPAIRMENT": ("자본잠식 근접", 9),
    }
    fs_flags: list[str] = []
    fs_metrics: list[dict] = []
    try:
        _year = str(datetime.now().year - 1)
        # 전체 계정 과목 필요 (매출채권·재고자산 포함) → fnlttSinglAcntAll 사용. CFS 우선, 없으면 OFS.
        fs_list = fetch_financial_statements_all(corp_code, _DART_API_KEY, _year, "annual", "CFS")
        if not fs_list:
            fs_list = fetch_financial_statements_all(corp_code, _DART_API_KEY, _year, "annual", "OFS")
        if fs_list:
            _cur, _pri = _fs_response_to_periods({"list": fs_list})
            fs_flags, fs_metrics = detect_financial_anomaly(_cur, _pri)
            for f in fs_flags:
                label, score = _v6_labels[f]
                _fs_event = {
                    "key": f,
                    "label": label,
                    "score": score,
                    "report_nm": f"{_year} 재무제표 YoY 이상",
                    "rcept_dt": "",
                    "rcept_no": "",
                    "is_amendment": False,
                }
                signal_events.append(_fs_event)
                observed_events.append(_fs_event)
    except Exception:
        pass
    # ============ v0.6.0 블록 끝 ============

    # 5. 복합 패턴 — 부분 겹침(관찰된 만큼 보여주고 무엇을 확인할지 알려주기).
    # find_pattern_match(전부 일치)는 find_risk_precedents 등 다른 호출부가
    # 계속 쓰므로 그대로 둔다.
    from .core.signals import SIGNAL_KEY_TO_TAXONOMY as _SKT

    sig_keys = list({e["key"] for e in observed_events if not e["is_amendment"]})
    tax_ids_all = list({tid for k in sig_keys for tid in _SKT.get(k, [])})
    # 패턴 창 게이트 입력 — 날짜 없는 합성 이벤트는 조회 창의 최신 공시일에 둔다.
    _latest_dt = max(
        (
            "".join(ch for ch in str(d.get("rcept_dt") or "") if ch.isdigit())[:8]
            for d in disclosures
        ),
        default="",
    )
    tax_dates_all = _taxonomy_dates(observed_events, _SKT, _latest_dt)

    # v1.6.1: 자금유출·양수거래(+처분) 상대방 확인 — decisions는 이미 위에서
    # fetch됐으므로 재사용(추가 호출 없음). capital_backflow 게이트에도 쓰인다.
    outflow_confirmations: list[dict] = []
    try:
        _decisions_by_rcept = {d["rcept_no"]: r for d, r in decisions}
        outflow_confirmations = _confirm_outflow_counterparties(
            observed_events, disclosures, corp_code, _decisions_by_rcept
        )
    except Exception:
        outflow_confirmations = []

    # 후속 3위: 종속회사로 확인된 상대방을 타법인 출자현황과 대조(사실 병기).
    # subsidiary 분류가 없으면 API 호출 없이 즉시 빈 dict.
    try:
        _affiliate_facts = _build_affiliate_stake_facts(outflow_confirmations, corp_code)
    except Exception:
        _affiliate_facts = {}

    # v1.13.0: fund_diversion_chain 내용 확인 게이트 입력 — 5.8이 관찰되지
    # 않았으면 원문을 열지 않는다(호출 예산 0).
    _acq_confirmations: list[dict] = []
    if "5.8" in tax_ids_all:
        try:
            _acq_confirmations = _confirm_acquisition_targets(
                observed_events, disclosures
            )
        except Exception:
            _acq_confirmations = []

    pattern_overlap_lines, capital_backflow_fact_lines, _pattern_overlaps = _render_pattern_watch_block(
        tax_ids_all,
        outflow_confirmations,
        _has_control_change_title(disclosures),
        _affiliate_facts,
        taxonomy_dates=tax_dates_all,
        acq_confirmations=_acq_confirmations,
    )

    # 6. 타임라인 (내부 랭킹 점수 기준 — 출력에는 노출되지 않음)
    # 헤드라인 — 양면적 신호는 단독으로 후보가 되지 않는다.
    _order = [s["key"] for s in sorted(SIGNAL_TYPES, key=lambda x: -x["score"])]
    _cands = [
        Qualified(key=e["key"], label=e["label"], tier=TIER_OBSERVED, reason="", note="")
        for e in observed_events if not e["is_amendment"]
    ]
    _head = pick_headline(_cands, _order)
    top_signal = None
    if _head is not None:
        top_signal = next(
            (e for e in observed_events
             if e["key"] == _head.key and not e["is_amendment"]),
            None,
        )
    timeline_text = ""
    if top_signal:
        from .core.signals import SIGNAL_KEY_TO_TAXONOMY

        tax_ids = SIGNAL_KEY_TO_TAXONOMY.get(top_signal["key"], [])
        if tax_ids:
            tl = estimate_crisis_timeline(tax_ids[0])
            if tl:
                months = tl.get("months_to_impact")
                loss = tl.get("equity_loss_pct")
                if months and months < 999:
                    timeline_text = f"• {top_signal['label']} 신호 기준: 위기 도달까지 약 {months}개월"
                    if loss:
                        timeline_text += f", 예상 지분 손실 {loss}%"

    # 7. CB 인수자 추출 (최근 3건까지)
    cb_investors: list[dict] = []
    seen_investors: set[str] = set()
    for _cb_rcept in cb_rcept_nos[:3]:
        for inv in extract_cb_investors(_cb_rcept, _DART_API_KEY, corp_code):
            if inv["name"] not in seen_investors:
                seen_investors.add(inv["name"])
                cb_investors.append(inv)

    # ── 리포트 조립 ──

    # 🎯 3문장 요약 — 맨 위에 독립적으로 읽히는 단락
    non_amend_events = [e for e in observed_events if not e["is_amendment"]]
    top_signal_label = (
        top_signal.get("label", "") if top_signal else ""
    )
    top_signal_prose = (
        signal_to_prose(top_signal["key"]) if top_signal else ""
    )
    # 첫 문장: 규모 (사실 서술)
    s1 = (
        f"지난 {window_phrase} 동안 **{corp_name}**의 공시 "
        f"{len(disclosures)}건을 살펴본 결과, 주목할 만한 공시·"
        f"재무 이벤트가 **{len(non_amend_events)}건** 관찰됐습니다."
    )
    # 둘째 문장: 관찰된 사실의 성격 (점수·등급 제거, 포지셔닝 고지)
    s2 = (
        "이 도구는 공시 기록에서 관찰된 사실만 서술합니다. "
        "기업의 위험도를 정량화하거나 등급을 부여하지 않으며, "
        "법적 판단이나 투자 결정의 근거가 아닙니다."
    )
    # 셋째 문장: 가장 눈에 띄는 신호
    if top_signal:
        s3 = _compose_top_signal_sentence(top_signal_label, top_signal_prose)
    elif non_amend_events:
        # 유형 목록과 건수 모두 정정공시를 제외한 같은 모집단(non_amend_events)에서
        # 센다 — 목록만 걸러내면 건수가 부풀고, 전부 정정이면 꼬리가 빈 채로
        # "이 기간 관찰된 유형: "만 남는다(리뷰 C2 연계).
        _types = sorted({(e["key"], e["label"]) for e in non_amend_events})
        _txt = " · ".join(
            f"{label} {sum(1 for e in non_amend_events if e['key'] == key)}건"
            for key, label in _types
        )
        s3 = f"이 기간 관찰된 유형: {_txt}"
    else:
        s3 = (
            "이 기간 공시에서는 관찰 신호가 없습니다. "
            "공시 외 지표(재무·감사의견·연속적자)는 아래 블록에서 확인하세요."
        )

    summary_block = f"📋 {s1}\n\n{s2}\n\n{s3}"

    lines = [
        f"📋 **기업 공시 관찰 요약: {corp_name}**",
        f"종목코드: {stock_code}" if stock_code else f"Corp code: {corp_code}",
        "",
        summary_block,
        "",
        f"조회 기간: 최근 {window_phrase} | 전체 공시 {len(disclosures)}건 검토",
        "",
    ]
    _alias_note = _alias_note_line(corp_info)
    if _alias_note:
        lines.insert(1, _alias_note)
    if observed_events:
        lines += [
            f"━━ 관찰된 신호 ({len(observed_events)}건) ━━",
        ]

        # 같은 signal_key가 많이 반복될 때 해설(→)을 첫 3건에만 붙여 가독성을 보존한다.
        _key_counts = Counter(e["key"] for e in observed_events)
        _key_seen: dict[str, int] = {}
        for e in sorted(observed_events, key=lambda x: x["rcept_dt"], reverse=True):
            amend_tag = " · 정정공시(관찰 대상 제외)" if e["is_amendment"] else ""
            date = e["rcept_dt"] or "-"
            _key_seen[e["key"]] = _key_seen.get(e["key"], 0) + 1
            _show_prose = (
                _key_counts[e["key"]] <= _PROSE_REPEAT_LIMIT
                or _key_seen[e["key"]] <= _PROSE_REPEAT_LIMIT
            )
            meaning = signal_to_prose(e["key"]) if _show_prose else ""
            one_liner = meaning if meaning else (e["label"] if _show_prose else "")
            # 첫 줄: 날짜 · 공시명
            lines.append(
                f"• {date} · {_clean_report_name(e['report_nm'])}{amend_tag}"
            )
            # 두번째 줄: 의미 해설 (반복 N회 초과 시 생략)
            if one_liner:
                lines.append(f"  → {one_liner}")
            # 사실 주석 (방향 불일치 등) — tier와 무관하게, 있으면 항상 표시
            if e.get("note"):
                lines.append(f"  ※ {e['note']}")

    if procedural_events:
        lines.append(f"\n━━ 절차·사후 보고 ({len(procedural_events)}건) ━━")
        lines.append(
            "회사가 낸 사건 자체의 공시가 아니거나, 이미 끝난 건의 사후 보고입니다."
        )
        for e in procedural_events[:20]:
            lines.append(f"• {e['rcept_dt']} · {e['report_nm']}")
            lines.append(f"  → {e.get('reason', '')}")
            # 사실 주석 (방향 불일치 등) — tier와 무관하게, 있으면 항상 표시
            if e.get("note"):
                lines.append(f"  ※ {e['note']}")
        if len(procedural_events) > 20:
            lines.append(f"… 외 {len(procedural_events) - 20}건")

    if pattern_overlap_lines:
        lines += pattern_overlap_lines
    # 게이트가 막은 쪽의 **확인된 사실**은 다른 패턴 발화 여부와 무관하게
    # 보여준다(2026-08-22). 옛 elif는 겹치는 패턴이 하나라도 있으면 이 블록을
    # 통째로 숨겼는데, 여기 담기는 것은 패턴 주장이 아니라 원문에서 확인한
    # 사실(상대방 실명·관계·금액)이라 감출 이유가 없다 — 코아스 실측에서
    # 「이화전기공업, 자기자본 대비 447.3%」가 숨겨지는 것을 확인하고 고쳤다.
    if capital_backflow_fact_lines:
        # 헤더는 _render_pattern_watch_block이 각 블록에 이미 붙여 보낸다
        lines += [""] + capital_backflow_fact_lines

    if cb_investors:
        lines += [
            "",
            "━━ CB 인수자 ━━",
            "아래는 이 기업이 발행한 전환사채(CB)를 실제로 받아간 "
            "개인·법인입니다. 같은 이름이 다른 기업에도 반복 등장하면 "
            "세력 이동의 단서가 됩니다.",
            "",
        ]
        for inv in cb_investors:
            amt = _format_amount(inv.get("amount", ""))
            lines.append(f"• {inv['name']}" + (f" — {amt}" if amt else ""))

    if timeline_text:
        lines += ["", "━━ 위기 타임라인 ━━", timeline_text]

    # v0.5.0: 주요 결정 상대방 섹션 ---------------------------
    if decisions:
        lines += [
            "",
            "📑 **주요 결정 상대방** (최근 순, 최대 10건)",
            "양수도·합병 같은 주요 결정의 거래 상대방과 규모입니다. "
            "상대방이 특수관계인이거나, 거래 규모가 회사 자산 대비 "
            "과도하거나, 외부 평가가 생략됐을 때 아래에 '주목할 이유'를 "
            "덧붙입니다.",
            "",
        ]
        for _d, _r in decisions:
            lines.append(f"- [{_d['rcept_dt']}] {_clean_report_name(_d['report_nm'])}")
            lines.append(
                f"  → {_r['counterparty'] or '(미기재)'} / "
                f"{_r['amount']:,}원 (자산 대비 {_r['asset_ratio']:.1f}%)"
            )
            for f in _r["flags"]:
                title, body = flag_to_prose(f)
                if title:
                    lines.append(f"    • **주목할 이유:** {title}")
        if failed_decisions:
            lines.append(f"  (추가 {failed_decisions}건 구조화 조회 실패)")

    # v1.6.1: 자금유출·양수거래(+처분) 상대방 확인 섹션 -----------
    # capital_backflow 게이트가 이미 이 내용을 사실 블록으로 표기한 경우
    # (capital_backflow_fact_lines) 중복 출력하지 않는다.
    if outflow_confirmations and not capital_backflow_fact_lines:
        lines += [
            "",
            f"🔍 **자금유출·양수거래 상대방 확인** (최근 최대 {len(outflow_confirmations)}건)",
            "금전대여·채무보증·담보제공·유형자산양수/양도·영업양수/양도·"
            "타법인주식및출자증권양수/양도로 매칭된 공시의 거래상대방·관계를 "
            "확인합니다. 관계는 계열·특수관계/종속회사/외부/미확인 4범주로 "
            "분류하며, 판정이 아닌 사실 표기입니다.",
            "",
        ]
        lines += _render_outflow_confirmations(outflow_confirmations, _affiliate_facts)

    # v0.6.0 자본 변동 타임라인 (최근 12개월 요약)
    if churn.get("events"):
        lines.append("")
        lines.append("## 📊 자본 변동 타임라인 (최근 12개월)")
        _cutoff = (datetime.now() - timedelta(days=365)).strftime("%Y%m%d")
        recent = [e for e in churn["events"] if (e.get("rcept_dt") or "").replace("-", "") >= _cutoff]
        if recent:
            for e in recent[:10]:
                lines.append(f"- {e['rcept_dt']} · {_clean_report_name(e['report_nm'])}")
            if len(recent) > 10:
                lines.append(f"- ... (+{len(recent) - 10}건)")
        else:
            lines.append("- 최근 12개월 내 자본 이벤트 없음")

    # v0.6.0 재무 이상 스캔
    if fs_metrics:
        lines.append("")
        lines.append("## 📊 재무 이상 스캔")
        flagged_only = [m for m in fs_metrics if m.get("flagged")]
        if flagged_only:
            for m in flagged_only:
                flag_key = _METRIC_TO_FLAG.get(m["name"], "")
                if not flag_key:
                    continue
                title, body = flag_to_prose(flag_key, m)
                lines.append("")
                lines.append(f"**{title}**")
                lines.append(body)
        else:
            lines.append("- 모든 지표 정상")

    # v0.5.0: 자금사용내역 요약 섹션 ---------------------------
    if fund_records:
        _anomaly_recs = [r for r in fund_records if r["flags"]]
        lines += [
            "",
            f"💰 **조달자금 사용내역** (최근 3년, {len(fund_records)}건, "
            f"이상 {len(_anomaly_recs)}건)",
        ]
        for _r in _anomaly_recs[:5]:
            lines.append(
                f"- {_format_fund_year_prefix(_r)} "
                f"계획 \"{_r['plan_useprps'][:30]}\" → "
                f"실제 \"{_r['real_dtls_cn'][:30]}\""
            )
            for f in _r["flags"]:
                title, _ = flag_to_prose(f)
                if title:
                    lines.append(f"    • **주목할 이유:** {title}")

    # v0.9.0: 부실 후속 단계 진입 경고 — 사실 표기만(점수 가산 없음)
    if distress_events:
        _DISTRESS_LABEL = {
            "default":        "부도발생",
            "business_susp":  "영업정지",
            "rehabilitation": "회생절차 개시신청",
            "dissolution":    "해산사유 발생",
        }
        lines += [
            "",
            "⚠ **부실 단계 진입 — 주요사항보고서 발생**",
        ]
        seen_dates: set[tuple] = set()
        for _de in sorted(distress_events, key=lambda x: x.get("rcept_dt", "")):
            key = (_de.get("rcept_dt"), _de.get("subtype"))
            if key in seen_dates:
                continue
            seen_dates.add(key)
            lbl = _DISTRESS_LABEL.get(_de.get("subtype"), "부실 사건")
            lines.append(
                f"   • {_de.get('rcept_dt', '-')}  [{lbl}]  {_de.get('summary', '')}"
            )

    # v1.14.0: 특수관계인 자금거래·손익구조 급변 원문 사실 블록.
    # 해당 신호가 관찰되지 않았으면 두 함수 모두 원문을 열지 않는다(호출 예산 0).
    if deep:
        lines += _related_party_detail_block(observed_events)
        lines += _earnings_shock_block(observed_events)

    # v1.7.0: 최대주주변경 원문 상세 — 원문 추출 실패 시 블록 자체 생략
    _latest_ctrl_change = _find_latest_control_change(disclosures) if deep else None
    if _latest_ctrl_change:
        lines += _control_change_detail_block(_latest_ctrl_change)

    catalog = load_catalog_excerpt(tax_ids_all)
    if catalog:
        lines += ["", catalog]

    reg_section = _registry_company_section(corp_name)
    if reg_section:
        lines += [""] + reg_section

    if not deep:
        lines.append(_shallow_notice(
            "analyze_company_risk", corp_name,
            [e.get("rcept_dt") or e.get("date") or "" for e in observed_events],
        ))

    return _append_size_footer("\n".join(lines), lookback_years)


# ── 도구 2: 개별 공시 분석 ─────────────────────────────────────────────────


@mcp.tool()
def check_disclosure_risk(rcept_no: str = "", report_name: str = "") -> str:
    """DART 공시 접수번호 또는 공시 제목으로 해당 공시의 위험도를 분석한다.

    Args:
        rcept_no: DART 접수번호 14자리 (예: "20240315000123")
        report_name: 공시 제목 (접수번호 없을 때 사용, 예: "전환사채권발행결정")
    """
    if not rcept_no and not report_name:
        return "❌ rcept_no(접수번호) 또는 report_name(공시 제목) 중 하나를 입력하세요."

    # 접수번호가 있으면 제목 동반 여부와 무관하게 원본 행을 복원한다. 행이 있어야
    # R1(제출인 ≠ 회사)이 발화하는데, 예전에는 report_name이 함께 오면 행을 아예
    # 조회하지 않아 같은 공시가 호출 형태에 따라 다른 판정을 받았다. 실패하면
    # 기존 동작(자리표시자 제목, 무신호)으로 조용히 퇴화한다 — 회귀가 아니다.
    filing: "dict | None" = None
    lookup_status = ""
    if rcept_no and _DART_API_KEY:
        filing, lookup_status = resolve_disclosure_row_with_status(
            rcept_no, _DART_API_KEY
        )

    # 제목을 직접 넘긴 호출자는 그 제목이 보이길 기대하므로 report_name이 우선한다.
    # 판정 입력(filing)은 조회한 행을 그대로 쓴다.
    if report_name:
        title = report_name.strip()
    elif filing and filing.get("report_nm"):
        title = filing["report_nm"].strip()
    else:
        title = f"접수번호 {rcept_no}"

    parsed = parse_report_name(title)
    is_amendment = is_amendment_disclosure(title)
    matched = match_signals(title)
    qualified = qualify_signals(matched, parsed, filing)

    lines = ["📋 **공시 리스크 분석**", f"공시: {title}"]
    if filing and filing.get("flr_nm"):
        lines.append(f"제출인: {filing['flr_nm']}")
    lines.append("")

    if not matched:
        if is_amendment:
            # match_signals는 정정공시에 항상 []를 반환하므로 루프 안의
            # amendment_note는 도달 불능이었다(감사 E-2) — 여기서 안내한다
            lines.append("정정공시입니다 — 원공시의 번복/수정이므로 신호 관찰"
                         " 대상에서 제외됩니다. 원공시 접수번호로 다시 조회하세요.")
        elif not report_name and lookup_status in ("scan_limit", "error"):
            # 제목을 복원하지 못한 채 "신호 없음"이라고 하면, 정말 신호가 없는
            # 공시와 조회에 실패한 공시가 같은 화면으로 보인다. 둘을 가른다.
            if lookup_status == "scan_limit":
                lines.append(
                    "⚠ 이 공시의 제목을 확인하지 못했습니다 — 접수일에 공시가"
                    " 매우 많아 조회 범위(하루 5,000건)를 넘었습니다."
                )
                lines.append(
                    "**신호가 없다는 뜻이 아닙니다.** 공시 제목을 함께 넘기면"
                    " 바로 분석할 수 있습니다:"
                    " `check_disclosure_risk(rcept_no=\"...\", report_name=\"...\")`"
                )
            else:
                lines.append(
                    "⚠ 이 공시의 제목을 확인하지 못했습니다 — 조회 중 오류가"
                    " 발생했습니다(일시적일 수 있습니다). **신호가 없다는 뜻이"
                    " 아닙니다.** 잠시 후 다시 시도하거나 공시 제목을 함께"
                    " 넘겨 주세요."
                )
        elif not report_name and not filing and rcept_no:
            lines.append(
                "이 접수번호를 찾지 못했습니다 — 접수번호가 정확한지, 접수일이"
                " 번호 앞 8자리와 같은지 확인해 주세요(드물게 다른 공시가"
                " 있습니다). 공시 제목을 함께 넘기면 바로 분석할 수 있습니다."
            )
        else:
            lines.append("이 공시에서 의심 신호가 탐지되지 않았습니다.")
    else:
        for sig, q in zip(matched, qualified):
            from .core.signals import SIGNAL_KEY_TO_TAXONOMY

            tax_ids = SIGNAL_KEY_TO_TAXONOMY.get(sig["key"], [])
            prose = signal_to_prose(sig["key"])
            amendment_note = " (정정공시 — 원공시의 번복/수정이므로 관찰 대상에서 제외됩니다.)" if is_amendment else ""
            if q.tier == TIER_OBSERVED:
                lines.append(f"🎯 **{q.label}**{amendment_note}")
                if prose:
                    lines.append(prose)
                if q.note:
                    lines.append(f"※ {q.note}")
                lines.append("")
            else:
                # 단건 도구라 #163의 두 층 절 구분은 과하다 — 한 건의 판정과
                # 사유만 보인다.
                lines.append("⚪ **절차·사후 보고**")
                lines.append(q.reason)
                # 강등 사유는 q.reason이 이미 구체적으로 말한다. 여기 덧붙이는
                # 문장은 R1/R1b(제출인 다름)뿐 아니라 R2(결과·해제)·R3(자회사)·
                # R4(해명)·R5(정정)도 덮어야 하므로 analyze_company_risk와 같은
                # 한정 표현을 쓴다 — "회사가 낸 공시가 아니다"로 단정하면 결과
                # 보고서류에서 사유와 정면으로 모순된다.
                lines.append(
                    f"→ 제목에 [{q.label}] 신호가 매칭되지만, 회사가 낸 사건 "
                    "자체의 공시가 아니거나 이미 끝난 건의 사후 보고입니다."
                )
                if q.note:
                    lines.append(f"※ {q.note}")
                lines.append("")
                continue

            # 타임라인
            if tax_ids and not is_amendment:
                tl = estimate_crisis_timeline(tax_ids[0])
                if tl:
                    tl_parts = []
                    months = tl.get("months_to_impact")
                    loss = tl.get("equity_loss_pct")
                    if months and months < 999:
                        tl_parts.append(f"위기 도달까지 평균 {months}개월이 걸린 사례가 보고돼 있습니다")
                    if loss:
                        tl_parts.append(f"주가·지분 손실은 평균 {loss}% 수준으로 추정됩니다")
                    if tl_parts:
                        lines += [
                            "━━ 과거 유사 신호가 끝까지 간 경우의 참고 궤적 ━━",
                            "과거 같은 유형의 신호가 확산된 사례를 모아 보면, "
                            + ", ".join(tl_parts) + ".",
                            "",
                        ]

    # CB/BW면 인수자 추출 (check_disclosure_risk는 corp_code 불명 → HTML 폴백)
    if (
        rcept_no
        and any(
            q.key == "CB_BW" and q.tier == TIER_OBSERVED for q in qualified
        )
        and not is_amendment
    ):
        if not _DART_API_KEY:
            lines += ["", "⚠️ DART_API_KEY 미설정 — CB 인수자 조회 불가"]
        else:
            investors = extract_cb_investors(rcept_no, _DART_API_KEY, "")
            if investors:
                lines += ["", "━━ CB/BW 인수자 ━━"]
                for inv in investors:
                    amt = _format_amount(inv.get("amount", ""))
                    lines.append(f"• {inv['name']}" + (f" — {amt}" if amt else ""))

    # v0.5.0: DS005 결정 공시면 구조화 필드 추가 ---------------
    dtype = resolve_decision_type(report_name)
    if dtype and rcept_no and _DART_API_KEY:
        # DS005는 corp_code+날짜가 항상 필수(rcept_no 단독 모드 없음) —
        # 접수일 하루치 주요사항보고 목록에서 corp_code를 역해석하고,
        # 실패하면 헛호출 없이 섹션을 생략한다.
        _dec_corp = resolve_corp_code_from_rcept_no(rcept_no, _DART_API_KEY)
        dec = (
            fetch_major_decision(rcept_no, _DART_API_KEY, dtype, _dec_corp)
            if _dec_corp
            else {"error": "corp_code 역해석 실패 — 섹션 생략"}
        )
        if "error" not in dec:
            lines += ["", "📑 **주요 결정 공시에서 읽히는 거래 구조**"]
            lines.append(f"- 거래 상대방: {dec['counterparty'] or '공시에 기재되지 않았습니다'}")
            lines.append(
                f"- 거래 금액: {dec['amount']:,}원 "
                f"(회사 자산총액 대비 {dec['asset_ratio']:.2f}% 규모)"
            )
            lines.append(
                "- 특수관계인 여부: "
                + ("예 — 회사와 이해관계가 얽힌 상대방입니다" if dec["related_party"]
                   else "아니오")
            )
            lines.append(
                "- 외부 평가: "
                + ("실시 — 회계법인 등 독립된 제3자가 가격을 검증했습니다" if dec["external_eval"]
                   else "미실시 — 외부 기관의 가격 검증이 없었습니다")
            )
            if dec["flags"]:
                lines.append("")
                lines.append("이 결정에서 주의할 점:")
                for fl in dec["flags"]:
                    title, body = flag_to_prose(fl)
                    if body:
                        lines.append(f"  • **{title}** — {body}")
                    else:
                        lines.append(f"  • {title}")

    # 원문 요약
    if rcept_no and _DART_API_KEY:
        text = fetch_document_text(rcept_no, _DART_API_KEY, max_chars=500)
        if text:
            lines += ["", "━━ 원문 요약 (첫 500자) ━━", text[:500]]
        elif not report_name:
            # 제목도 없고 원문 조회도 실패 — 아무것도 분석하지 못한 상태를
            # "신호 없음"으로 오인하지 않도록 사실을 명시(라이브 스모크 실측:
            # 존재하지 않는 접수번호가 유효 공시처럼 읽히던 문제)
            lines += ["", "⚠️ 이 접수번호의 원문을 조회하지 못했습니다 — "
                          "접수번호 오류이거나 일시적 조회 실패일 수 있습니다. "
                          "위 결과는 제목·원문을 확인하지 못한 상태이므로 "
                          "'신호 없음'으로 해석하지 마세요."]

    from .core.signals import SIGNAL_KEY_TO_TAXONOMY as _SKT
    # 발췌는 관찰 신호에만 붙인다. 강등된 신호까지 넣으면 전부 강등된 공시에서도
    # 수 KB 카탈로그가 출력을 뒤덮어 방금 내린 강등을 시각적으로 되돌린다.
    all_tax_ids = list({
        tid
        for q in qualified
        if q.tier == TIER_OBSERVED
        for tid in _SKT.get(q.key, [])
    })
    catalog = load_catalog_excerpt(all_tax_ids)
    if catalog:
        lines += ["", catalog]

    return "\n".join(lines)


# ── 도구 3: 선례 검색 (경량 구현) ─────────────────────────────────────────


@mcp.tool()
def find_risk_precedents(signal_types: list[str], lookback_days: int = 90) -> str:
    """신호 유형 조합으로 해당 신호의 특성과 위험 해석을 반환한다.

    Args:
        signal_types: 신호 유형 목록 (예: ["CB_BW", "3PCA", "SHAREHOLDER"])
        lookback_days: 참고용 (현재 버전에서는 사용되지 않음)
    """
    if not signal_types:
        return "❌ signal_types 목록을 입력하세요. 예: ['CB_BW', 'SHAREHOLDER']"

    from .core.signals import (
        NON_TITLE_SIGNALS,
        SIGNAL_KEY_TO_TAXONOMY,
        SIGNAL_TYPES,
    )

    sig_map = {s["key"]: s for s in SIGNAL_TYPES}
    valid_keys = []
    unknown = []

    for k in signal_types:
        k_upper = k.upper()
        if k_upper in sig_map:
            valid_keys.append(k_upper)
        else:
            unknown.append(k)

    lines = ["📚 **신호별 해석 — 왜 주목해야 하는지**", ""]

    if unknown:
        known_list = ", ".join(sig_map.keys())
        lines.append(f"⚠️ 알 수 없는 신호 키: {', '.join(unknown)}")
        lines.append(f"(참고용으로만 입력받는 내부 키 목록: {known_list})")
        lines.append("")

    for key in valid_keys:
        sig = sig_map[key]
        tax_ids = SIGNAL_KEY_TO_TAXONOMY.get(key, [])
        prose = signal_to_prose(key)
        lines.append(f"━━ {sig['label']} ━━")
        if prose:
            lines.append(prose)
        # 이 신호가 공시 제목으로는 발화하지 않는다면 그 사실을 먼저 알린다 —
        # 조회는 되는데 실제로는 한 번도 안 잡히는 신호를 설명만 보여주면
        # "이 도구가 이걸 탐지한다"는 인상을 준다(2026-08-22 1년 실측).
        _route = NON_TITLE_SIGNALS.get(key)
        if _route:
            lines.append(_NON_TITLE_NOTE[_route])
        tl_sentences: list[str] = []
        for tid in tax_ids:
            tl = estimate_crisis_timeline(tid)
            if tl:
                months = tl.get("months_to_impact")
                loss = tl.get("equity_loss_pct")
                parts = []
                if months and months < 999:
                    parts.append(f"위기 도달까지 평균 약 {months}개월이 걸렸습니다")
                if loss:
                    parts.append(f"주가·지분 손실은 평균 {loss}% 수준이었습니다")
                if parts:
                    tl_sentences.append(", ".join(parts))
        if tl_sentences:
            lines.append(
                "과거 같은 유형의 신호가 끝까지 간 사례를 모아 보면, "
                + "; ".join(tl_sentences) + "."
            )
        lines.append("")

    # 복합 패턴
    if len(valid_keys) >= 2:
        tax_ids_flat = list({tid for k in valid_keys for tid in SIGNAL_KEY_TO_TAXONOMY.get(k, [])})
        pattern = find_pattern_match(tax_ids_flat)
        if pattern:
            lines += [
                "━━ 이 신호들이 동시에 나타날 때의 의미 ━━",
                f"⚠️ **\"{pattern['name']}\"** 패턴과 유사합니다.",
            ]
            prose_body = pattern_to_prose(pattern.get("pattern_id", ""))
            lines.append(prose_body or pattern.get("description", ""))
            _checkpoints = pattern_checkpoints(pattern.get("pattern_id", ""))
            if _checkpoints:
                lines.append("")
                lines.append("확인 포인트:")
                for _cp in _checkpoints:
                    lines.append(f"  • {_cp}")
            lines.append("")

    all_tax_ids = list({tid for k in valid_keys for tid in SIGNAL_KEY_TO_TAXONOMY.get(k, [])})
    catalog = load_catalog_excerpt(all_tax_ids)
    if catalog:
        lines += ["", catalog]

    return "\n".join(lines)


# ── 도구 4: 이벤트 타임라인 (서사 구조) ────────────────────────────────────

# 단계 분류: 신호 키 → 진입/심화/탈출
_PHASE_MAP = {
    # 진입기: 자금 조달 / 자본구조 변경
    "CB_BW": "진입기", "CB_REPAY": "진입기", "EB": "진입기", "RCPS": "진입기",
    "CB_ROLLOVER": "진입기", "CB_BUYBACK": "진입기", "TREASURY_EB": "진입기",
    "3PCA": "진입기", "REVERSE_SPLIT": "진입기", "RIGHTS_UNDER": "진입기",
    "TREASURY": "진입기", "MGMT": "진입기", "DEMERGER": "진입기",
    # 심화기: 지배구조 변화 / 기업활동 조작
    "SHAREHOLDER": "심화기", "EXEC": "심화기", "MGMT_DISPUTE": "심화기",
    "CIRCULAR": "심화기", "RELATED_PARTY": "심화기", "GAMJA_MERGE": "심화기",
    "ASSET_TRANSFER": "심화기", "BUYBACK_NEG": "심화기", "DISTRESS_MA": "심화기",
    "EQUITY_SPLIT": "심화기", "REVENUE_IRREG": "심화기", "CONTINGENT": "심화기",
    "THEME_STOCK": "심화기",
    # 탈출기: 위기 / 부실 / 수사
    "INQUIRY": "탈출기", "AUDIT": "탈출기", "EMBEZZLE": "탈출기",
    "INSOLVENCY": "탈출기", "DEBT_RESTR": "탈출기", "GOING_CONCERN": "탈출기",
    "ASSET_SPIRAL": "탈출기", "MEETING_VIOL": "탈출기", "DISCLOSURE_VIOL": "탈출기",
    "CAPITAL_RED": "탈출기", "ACTIVIST": "탈출기",
    # v0.5.0: 자금흐름·주요결정
    "DECISION_RELATED_PARTY": "진입기",
    "FUND_DIVERSION":         "진입기",
    "DECISION_OVERSIZED":     "심화기",
    "DECISION_NO_EXTVAL":     "심화기",
    "FUND_UNREPORTED":        "심화기",
    # v0.6.0: 자본 이벤트 과다 반복 + 재무제표 YoY 이상
    "CAPITAL_CHURN":       "심화기",
    "AR_SURGE":            "심화기",
    "INVENTORY_SURGE":     "심화기",
    "CASH_GAP":            "탈출기",
    "CAPITAL_IMPAIRMENT":  "탈출기",
}
_PHASE_ORDER = {"진입기": 0, "심화기": 1, "탈출기": 2}


@mcp.tool()
def build_event_timeline(
    company_name: str,
    lookback_years: int = 1,
    lookback_days: int | None = None,
    from_date: str = "",
    to_date: str = "",
) -> str:
    """기업의 공시 이벤트를 시간순으로 정렬해 조작 흐름의 서사를 구성한다.

    각 이벤트를 진입기(자금 조달/경영권 진입), 심화기(지배구조 변화),
    탈출기(의심/수사/부실) 단계로 분류하고, 알려진 위기 패턴과 매칭한다.

    공개기록 레지스트리(opt-in)가 설정돼 있고 이 회사가 등재 행위자의
    관련기업으로 태깅된 경우, 리포트 말미에 공개기록 참고 섹션이 추가된다.

    Args:
        company_name: 기업명 (예: "에코프로") 또는 종목코드 6자리 (예: "086520")
        lookback_years: 조회 기간(년). 기본 1년, 1~5년 범위. 1년을 넘으면
            원문 사실 블록 없이 신호·패턴·타임라인만 담은 "지도"가 된다.
        from_date: 조회 시작일(선택). "2024-01-01"·"20240101" 형식. 주면
            lookback_years는 무시된다.
        to_date: 조회 종료일(선택). 미지정 시 오늘. from_date만 주면 그날부터
            오늘까지, to_date만 주면 그날 기준 1년.
    """
    if not _DART_API_KEY:
        return "❌ DART_API_KEY 환경변수가 설정되지 않았습니다."

    bgn_de, end_de, lookback_days, max_pages, window_phrase, win_err = _resolve_window(
        lookback_years, lookback_days, from_date, to_date
    )
    if win_err:
        return f"❌ {win_err}"
    deep = _is_deep_window(lookback_days)

    result = resolve_corp(company_name, _DART_API_KEY)
    if not result:
        return f"❌ '{company_name}'에 해당하는 기업을 DART에서 찾을 수 없습니다."
    corp_name, corp_info = result
    corp_code = corp_info["corp_code"]
    stock_code = corp_info.get("stock_code", "")

    _alias_note = _alias_note_line(corp_info)
    _note_block = f"{_alias_note}\n\n" if _alias_note else ""

    disclosures, fetch_status = fetch_company_disclosures_with_status(
        corp_code, _DART_API_KEY, lookback_days, max_pages=max_pages,
        bgn_de=bgn_de, end_de=end_de,
    )
    if fetch_status == FETCH_ERROR:
        return _fetch_failed_notice(corp_name, window_phrase)
    if not disclosures:
        return (
            f"📋 **{corp_name}** ({stock_code or corp_code})\n\n"
            f"{_note_block}"
            f"최근 {window_phrase}간 공시가 없습니다."
        )

    # 이벤트 수집: (날짜, 단계, 신호키, 신호라벨, 공시명)
    events: list[tuple[str, str, str, str, str]] = []
    all_tax_ids: set[str] = set()
    all_tax_dates: dict[str, list[str]] = {}

    from .core.signals import SIGNAL_KEY_TO_TAXONOMY

    for d in disclosures:
        report_nm = d.get("report_nm", "")
        rcept_dt = d.get("rcept_dt", "")[:10]
        rcept_no = d.get("rcept_no", "")
        parsed = parse_report_name(report_nm)
        if is_amendment_disclosure(report_nm) and not is_false_amendment(parsed):
            continue
        matched = match_signals(report_nm) or match_signals(
            strip_amendment_prefix(report_nm)
        )
        qualified = qualify_signals(matched, parsed, d)
        for sig, q in zip(matched, qualified):
            if q.tier != TIER_OBSERVED:
                continue
            phase = _PHASE_MAP.get(sig["key"], "심화기")
            events.append((rcept_dt, phase, sig["key"], q.label, report_nm, rcept_no))
            tax_ids = SIGNAL_KEY_TO_TAXONOMY.get(sig["key"], [])
            all_tax_ids.update(tax_ids)
            _dt = "".join(ch for ch in rcept_dt if ch.isdigit())[:8]
            if len(_dt) == 8:
                for _tid in tax_ids:
                    all_tax_dates.setdefault(_tid, []).append(_dt)

    if not events:
        # 헤더는 정상 경로(아래 ⏳ 라인)와 같은 형식을 쓴다 — 도구가 상황에 따라
        # 자기 이름을 다르게 대면 출력 계약이 깨진다. 한정층 도입 후 공시 신호가
        # 전부 강등되는 회사(헬릭스미스 실측)에서 이 경로가 실제로 발화한다.
        return (
            f"⏳ **이벤트 타임라인: {corp_name}** ({stock_code or corp_code})\n\n"
            f"{_note_block}"
            f"최근 {window_phrase}간 관찰된 신호 이벤트가 없습니다.\n"
            f"공시 외 지표(재무·감사의견·연속적자)는 analyze_company_risk에서 확인하세요.\n"
            f"(전체 공시 {len(disclosures)}건 검토)"
        )

    # 날짜순 정렬
    events.sort(key=lambda e: e[0])

    # 단계별 그룹핑
    phases: dict[str, list] = {"진입기": [], "심화기": [], "탈출기": []}
    for evt in events:
        phases[evt[1]].append(evt)

    # 패턴 매칭 — 부분 겹침(관찰된 만큼 보여주고 무엇을 확인할지 알려주기).
    # events 튜플(rcept_dt, phase, key, label, report_nm, rcept_no)을
    # _confirm_outflow_counterparties가 기대하는 dict 형태로 변환한다.
    _outflow_signal_events = [
        {
            "key": evt[2], "report_nm": evt[4], "rcept_dt": evt[0],
            "rcept_no": evt[5] if len(evt) > 5 else "", "is_amendment": False,
        }
        for evt in events
        if evt[2] in ("FUND_OUTFLOW", "ACQ_REVIEW", "ASSET_TRANSFER")
    ]
    outflow_confirmations: list[dict] = []
    try:
        outflow_confirmations = _confirm_outflow_counterparties(
            _outflow_signal_events, disclosures, corp_code
        )
    except Exception:
        outflow_confirmations = []
    try:
        _affiliate_facts = _build_affiliate_stake_facts(outflow_confirmations, corp_code)
    except Exception:
        _affiliate_facts = {}

    # v1.13.0: fund_diversion_chain 게이트 입력 — 5.8이 관찰되지 않았으면
    # 원문을 열지 않는다(호출 예산 0).
    _acq_confirmations: list[dict] = []
    if "5.8" in all_tax_ids:
        try:
            _acq_confirmations = _confirm_acquisition_targets(
                [
                    {"key": evt[2], "rcept_dt": evt[0], "report_nm": evt[4],
                     "rcept_no": evt[5], "is_amendment": False}
                    for evt in events if evt[2] == "ACQ_REVIEW"
                ],
                disclosures,
            )
        except Exception:
            _acq_confirmations = []

    # v1.6.1: capital_backflow 게이트 — analyze_company_risk와 동일한 확인
    # 로직(_render_pattern_watch_block 내부에서 재사용).
    pattern_overlap_lines, capital_backflow_fact_lines, _pattern_overlaps = _render_pattern_watch_block(
        all_tax_ids,
        outflow_confirmations,
        _has_control_change_title(disclosures),
        _affiliate_facts,
        taxonomy_dates=all_tax_dates,
        acq_confirmations=_acq_confirmations,
    )
    _top_overlap = _pattern_overlaps[0] if _pattern_overlaps else None

    # 타임라인 출력
    first_date = events[0][0]
    last_date = events[-1][0]

    # 🎯 맨 위 3~4줄 요약 — 이 단락만 읽어도 상황이 그려진다
    phase_counts = {p: len(phases[p]) for p in ("진입기", "심화기", "탈출기")}
    busiest_phase = max(phase_counts, key=lambda p: phase_counts[p])
    phase_plain = {
        "진입기": "자금 조달·자본 구조 변경이 몰려 있는 '진입기'",
        "심화기": "지배구조·경영권 움직임이 늘어난 '심화기'",
        "탈출기": "감사·수사·부실 관련 공시가 많은 '탈출기'",
    }
    summary_lines = [
        f"⏳ **이벤트 타임라인: {corp_name}** ({stock_code or corp_code})",
    ]
    _alias_note = _alias_note_line(corp_info)
    if _alias_note:
        summary_lines.append(_alias_note)
    summary_lines += [
        "",
        "🎯 **한눈에 보는 요약**",
        (
            f"- 최근 {window_phrase} 동안 위험 신호로 분류된 공시 "
            f"{len(events)}건이 {first_date}부터 {last_date}까지 이어졌습니다."
        ),
        (
            f"- 이 가운데 가장 많이 몰려 있는 단계는 {phase_plain[busiest_phase]}로, "
            f"총 {phase_counts[busiest_phase]}건이 이 구간에 해당합니다."
        ),
    ]
    if _top_overlap:
        summary_lines.append(
            f"- 이 기간 관찰된 신호는 등록 패턴 \"{_top_overlap['name']}\"의 "
            f"구성 신호 {_top_overlap['n_total']}개 중 {_top_overlap['n_matched']}개와 "
            f"겹칩니다(상세는 아래 참고)."
        )
    summary_lines.append("")

    lines = summary_lines

    # 단계 설명 머리말
    lines.append(
        "아래 타임라인은 공시를 세 단계로 나눠 보여줍니다. "
        "진입기는 자금을 끌어오거나 자본 구조를 바꾸는 움직임, "
        "심화기는 경영권·지배구조가 흔들리는 움직임, "
        "탈출기는 감사·수사·부실 등 위기가 드러나는 움직임입니다."
    )
    lines.append("")

    for phase_name in ("진입기", "심화기", "탈출기"):
        phase_events = phases[phase_name]
        if not phase_events:
            continue
        lines.append(f"**[{phase_name}] — {phase_events[0][0]} 이후 {len(phase_events)}건**")
        # 이 단계에서 처음 등장한 신호에 대해 한 줄 해설을 붙여준다(중복 방지).
        seen_keys: set[str] = set()
        for evt in phase_events:
            lines.append(f"  • {evt[0]}  [{evt[3]}]  {evt[4]}")
            sig_key = evt[2]
            if sig_key not in seen_keys:
                prose = signal_to_prose(sig_key)
                if prose:
                    lines.append(f"      → {prose}")
                seen_keys.add(sig_key)
            # v0.5.0: 결정 공시면 상대방 한 줄 추가
            _dtype = resolve_decision_type(evt[4])
            _evt_rcept = evt[5] if len(evt) > 5 else ""
            if _dtype and _evt_rcept and _DART_API_KEY:
                _dec = fetch_major_decision(_evt_rcept, _DART_API_KEY, _dtype, corp_code)
                if "error" not in _dec and _dec["counterparty"]:
                    lines.append(
                        f"      └ 거래 상대방: {_dec['counterparty']} "
                        f"({_dec['amount']:,}원)"
                    )
        lines.append("")

    if pattern_overlap_lines:
        lines += pattern_overlap_lines
        lines.append("")
    if capital_backflow_fact_lines:
        lines += [""] + capital_backflow_fact_lines
        lines.append("")

    # v1.6.1: 자금유출·양수거래(+처분) 상대방 확인 상세 — capital_backflow
    # 게이트가 이미 사실 블록으로 표기한 경우 중복 출력하지 않는다.
    if outflow_confirmations and not capital_backflow_fact_lines:
        lines += [
            "━━ 자금유출·양수거래 상대방 확인 ━━",
            "금전대여·채무보증·담보제공·유형자산양수/양도·영업양수/양도·"
            "타법인주식및출자증권양수/양도로 매칭된 공시의 거래상대방·관계를 "
            "확인합니다. 판정이 아닌 사실 표기입니다.",
            "",
        ]
        lines += _render_outflow_confirmations(outflow_confirmations, _affiliate_facts)
        lines.append("")

    # CB 인수자 (있으면) — match_signals는 이미 정정공시 제외 처리
    cb_rcept_list = [
        d.get("rcept_no", "")
        for d in disclosures
        if any(s["key"] == "CB_BW" for s in match_signals(d.get("report_nm", "")))
        and d.get("rcept_no")
    ]
    if cb_rcept_list:
        seen: set[str] = set()
        investors: list[dict] = []
        for rn in cb_rcept_list[:3]:
            for inv in extract_cb_investors(rn, _DART_API_KEY, corp_code):
                if inv["name"] not in seen:
                    seen.add(inv["name"])
                    investors.append(inv)
        if investors:
            lines.append("━━ 이 기간에 등장한 CB/BW 인수자 ━━")
            lines.append(
                "이 인수자들은 전환사채·신주인수권부사채로 회사의 빚을 떠안은 쪽이며, "
                "나중에 주식으로 바꿀 경우 새로운 주요 주주가 될 수 있습니다."
            )
            for inv in investors:
                amt = _format_amount(inv.get("amount", ""))
                lines.append(f"  • {inv['name']}" + (f" — {amt}" if amt else ""))
            lines.append("")

    # v0.6.0 재무 징후 블록 (공시 이벤트가 아닌 스칼라 판정)
    try:
        _year = str(datetime.now().year - 1)
        # 전체 계정 과목 필요 (매출채권·재고자산 포함) → fnlttSinglAcntAll 사용. CFS 우선, 없으면 OFS.
        fs_list = fetch_financial_statements_all(corp_code, _DART_API_KEY, _year, "annual", "CFS")
        if not fs_list:
            fs_list = fetch_financial_statements_all(corp_code, _DART_API_KEY, _year, "annual", "OFS")
        if fs_list:
            _cur, _pri = _fs_response_to_periods({"list": fs_list})
            fs_flags, fs_metrics = detect_financial_anomaly(_cur, _pri)
            if fs_flags:
                lines.append("━━ 재무제표에서 함께 잡힌 이상 신호 ━━")
                lines.append(
                    f"{_year} 사업보고서를 전년과 비교해 보면, "
                    "공시 이벤트와 별개로 아래 항목이 이상 구간에 들어 있습니다."
                )
                # fs_metrics는 [{"name", "current", "prior", "delta", "flagged"}...] 리스트.
                # _METRIC_TO_FLAG로 지표명 → flag 키를 역추적해 prose 렌더.
                _rendered: set[str] = set()
                for _m in fs_metrics:
                    if not _m.get("flagged"):
                        continue
                    _fl = _METRIC_TO_FLAG.get(_m.get("name", ""), "")
                    if not _fl or _fl in _rendered:
                        continue
                    _rendered.add(_fl)
                    _title, _body = flag_to_prose(_fl, _m)
                    lines.append(f"  • **{_title}**")
                    if _body:
                        lines.append(f"    {_body}")
                lines.append("")
    except Exception:
        pass

    # v1.7.0: 최대주주변경 원문 상세 — 원문 추출 실패 시 블록 자체 생략.
    # 직전 섹션(자금유출 상대방 확인 등)이 이미 trailing 빈 줄을 남겼을 수
    # 있어, 블록 첫 줄의 빈 줄과 겹치면 하나를 걷어내 이중 공백을 막는다.
    _detail_signal_events = [
        {
            "key": evt[2], "report_nm": evt[4], "rcept_dt": evt[0],
            "rcept_no": evt[5] if len(evt) > 5 else "", "is_amendment": False,
        }
        for evt in events
        if evt[2] in ("RELATED_PARTY", "EARNINGS_SHOCK")
    ]
    for _blk in ((
        _related_party_detail_block(_detail_signal_events),
        _earnings_shock_block(_detail_signal_events),
    ) if deep else ()):
        if _blk and _blk[0] == "" and lines and lines[-1] == "":
            _blk = _blk[1:]
        lines += _blk

    _latest_ctrl_change = _find_latest_control_change(disclosures) if deep else None
    if _latest_ctrl_change:
        _ctrl_block = _control_change_detail_block(_latest_ctrl_change)
        if _ctrl_block and _ctrl_block[0] == "" and lines and lines[-1] == "":
            _ctrl_block = _ctrl_block[1:]
        lines += _ctrl_block + [""]

    reg_section = _registry_company_section(corp_name)
    if reg_section:
        lines += reg_section + [""]

    lines.append("⚠️ 이 타임라인은 공시 제목 기반 자동 분류이며, 실제 상황과 다를 수 있습니다.")
    if not deep:
        # timeline의 events는 튜플이다 — evt[0]이 접수일(rcept_dt)
        lines.append(_shallow_notice(
            "build_event_timeline", corp_name,
            [evt[0] for evt in events if evt],
        ))

    return _append_size_footer("\n".join(lines), lookback_years)


# ── 도구 5: 세력 추적 (공통 CB/BW/EB + 유상증자 인수자) ──────────────────


@mcp.tool()
def lookup_known_actor(name: str) -> str:
    """인물명으로 공개기록 레지스트리를 조회한다 (사실 표기 — 판정 아님).

    출처가 명확한 공개기록(DART 임원현황·CB/유상증자 인수 등)에 그 인물이 어느
    상장사에 등장했는지를 사실로만 반환한다. 위험 판정·점수·등급은 부여하지 않으며,
    동명이인 가능성과 원본 확인 필요를 함께 고지한다.

    Args:
        name: 조회할 인물명
    """
    records = lookup_actor(name)
    if not records:
        return (f"'{name}'에 대한 공개기록이 레지스트리에 없습니다. "
                "(등재는 공개 출처가 확인된 경우에만 이뤄집니다.)")
    lines = [f"📎 '{name}' 공개기록 (사실 표기 — 판정 아님):"]
    has_seed = False
    has_auto = False
    for r in records:
        src = r.get("source", "")
        ev = r.get("evidence", "")
        date = r.get("date", "")
        url = r.get("url", "")
        st = actor_status(r)
        if st == "maintainer_seed":
            has_seed = True
        elif st == "auto_matched":
            has_auto = True
        prefix = "[자동 매칭 · 동명이인 미확인] " if st == "auto_matched" else ""
        head = f"  • {prefix}{src}"
        if date:
            head += f" ({date})"
        head += f": {ev}"
        lines.append(head)
        if url:
            lines.append(f"      출처: {url}")
    if has_auto:
        lines.append("⚠ 자동 매칭 항목은 시장 공시 이름 매칭 결과로 동일인 여부가 미확인입니다 — 원본 공시로 반드시 확인하세요.")
    if has_seed:
        lines.append("⚠ 일부 항목은 공시 자동매칭이 아닌 제작자 모니터링 등록입니다 (혐의·확정 아님).")
    lines.append("⚠ 원본 공시로 사실 확인 권장 · 동명이인 가능성 있음 · 본 기록은 판정이 아닙니다.")
    return "\n".join(lines)


@mcp.tool()
def manage_watchlist(
    action: str,
    person: str = "",
    companies: list[str] | None = None,
    note: str = "",
) -> str:
    """감시 대상 인물↔회사군 워치리스트를 관리한다 (list / show / add / remove).

    DART는 인물명 역검색이 불가능해 회사 목록을 직접 입력해야 한다. 자주 보는
    인물의 연관 회사군을 저장해두면 find_actor_overlap(watchlist=인물명)으로 바로
    재조회할 수 있다. 회사군은 사용자가 직접 채운다(예: find_actor_overlap의 임원
    겸직 결과를 add).

    Args:
        action: "list" | "show" | "add" | "remove"
        person: 인물명 (show/add/remove에 필요)
        companies: 회사명 목록 (add에 필요, 기존과 합집합 병합)
        note: 메모 (add 시 선택)
    """
    # 파일이 손상돼 옆으로 치워졌으면 **먼저 알린다**. 빈 목록만 보면
    # 사용자는 자기 목록이 사라진 줄 안다 — 실제로는 .corrupt 파일에
    # 내용이 남아 있어 손으로 되살릴 수 있다.
    quarantined = (load_watchlist() or {}).get("_quarantined")
    notice = (
        f"⚠ 워치리스트 파일을 읽을 수 없어 `{quarantined}` 로 옮겨 두고 "
        f"새 목록으로 시작했습니다. 옮긴 파일에 이전 내용이 남아 있으니 "
        f"필요하면 직접 확인하세요." + "\n\n"
    ) if quarantined else ""
    return notice + _manage_watchlist_body(action, person, companies, note)




def _manage_watchlist_body(
    action: str, person: str, companies: list, note: str,
) -> str:
    """manage_watchlist의 본체 — 손상 안내를 붙이기 위해 분리했다.

    분기마다 return이 여러 곳이라, 안내를 각 return에 끼워 넣는 대신
    본체를 감싸는 편이 읽기 쉽다.
    """
    companies = list(companies or [])
    act = (action or "").strip().lower()

    if act == "list":
        rows = list_persons()
        if not rows:
            return ("워치리스트가 비어 있습니다. "
                    "manage_watchlist(action='add', person='홍길동', "
                    "companies=['회사1','회사2'])로 추가하세요.")
        lines = ["📋 워치리스트 등록 인물:"]
        for name, cnt in rows:
            lines.append(f"  • {name} — {cnt}개사")
        return "\n".join(lines)

    if act == "show":
        if not person:
            return "입력 오류: show에는 person이 필요합니다."
        comps = get_person_companies(person)
        if not comps:
            return f"'{person}'은(는) 워치리스트에 없습니다."
        note_txt = load_watchlist().get("persons", {}).get(person, {}).get("note", "")
        lines = [f"👤 {person} — {len(comps)}개사:"]
        for c in comps:
            lines.append(f"  • {c}")
        if note_txt:
            lines.append(f"메모: {note_txt}")
        lines.append(f"→ find_actor_overlap(watchlist='{person}') 으로 분석할 수 있습니다.")
        return "\n".join(lines)

    if act == "add":
        if not person or not companies:
            return "입력 오류: add에는 person과 companies(1개 이상)가 필요합니다."
        entry = add_person(person, companies, note)
        return (f"✅ '{person}' 갱신 — 총 {len(entry['companies'])}개사: "
                f"{', '.join(entry['companies'])}")

    if act == "remove":
        if not person:
            return "입력 오류: remove에는 person이 필요합니다."
        ok = remove_person(person)
        return (f"🗑 '{person}' 삭제됨." if ok
                else f"'{person}'은(는) 워치리스트에 없습니다.")

    return "입력 오류: action은 list / show / add / remove 중 하나여야 합니다."


@mcp.tool()
def find_actor_overlap(
    company_names: list[str] | None = None,
    lookback_years: int = 1,
    watchlist: str = "",
) -> str:
    """여러 기업(2~5개)의 CB/BW/EB 인수자 + 유상증자 인수자를 비교해 공통 행위자(세력)를 탐지한다.

    DART API 제약상, 분석 대상 기업을 직접 지정해야 한다.
    "행위자 이름으로 역검색"은 현재 불가능하다.

    CB/BW/EB 공시(CB_BW, EB 신호)와 유상증자 공시(3PCA, RIGHTS_UNDER 신호)를
    모두 수집해 인수자를 통합 비교하며, 공통 행위자에는 출처 태그(CB / 유상증자)를 표시한다.

    무자본 M&A 세력은 인수 시점에 CB를 한 번 박은 뒤 수년에 걸쳐 리픽싱·차환으로
    굴리므로, 신규 CB 발행결정 공시는 과거에 몰린다. lookback_years로 조회 윈도우를
    넓혀야 단년 창에 안 잡히는 다년 공통 인수자를 포착할 수 있다.

    Args:
        company_names: 비교할 기업명 또는 종목코드 목록 (2~5개, 예: ["에코프로", "바이오제닉스"])
        lookback_years: 조회 기간(년). 기본 1년(하위호환), 1~5년 범위.
        watchlist: 저장된 워치리스트 인물명. 지정 시 해당 회사군을 company_names와
            합집합으로 분석한다 (manage_watchlist로 관리).
    """
    names = list(company_names or [])
    watchlist_note = ""
    if watchlist:
        wl_companies = get_person_companies(watchlist)
        if wl_companies:
            names = list(dict.fromkeys(names + wl_companies))
            watchlist_note = (f"ℹ️ 워치리스트 '{watchlist}'에서 "
                              f"{len(wl_companies)}개사를 불러왔습니다.")
        else:
            watchlist_note = (f"ℹ️ 워치리스트 '{watchlist}'를 찾지 못했습니다. "
                              "manage_watchlist(action='list')로 등록 인물을 확인하세요.")
    company_names = names

    if not isinstance(company_names, list) or not (2 <= len(company_names) <= 5):
        base = "입력 오류: 2개 이상 5개 이하 기업명(또는 종목코드) 리스트를 전달하세요."
        return f"{base}\n{watchlist_note}" if watchlist_note else base

    lookback_years = min(max(lookback_years, 1), 5)
    lookback_days = lookback_years * 365
    # 기본 1년은 기존 '최근 365일' 문구를 유지(골드 호환), N년은 정직하게 반영
    window_label = "최근 365일" if lookback_years == 1 else f"최근 {lookback_years}년"

    api_key = os.environ.get("DART_API_KEY") or _DART_API_KEY
    if not api_key:
        return "DART_API_KEY 환경변수가 설정되지 않았습니다."

    company_names = list(dict.fromkeys(company_names))  # 중복 제거 (순서 보존)

    CB_SIGNAL_KEYS = {"CB_BW", "EB"}
    RIGHTS_SIGNAL_KEYS = {"3PCA", "RIGHTS_UNDER"}
    # 기업당 CB 최대 3건 + 유상증자 최대 3건 (각 소스 독립 상한, 총 ≤ 6건)
    # 공통 상한을 쓰면 CB 공시가 많은 기업에서 유상증자 몫을 빼앗겨 "머지"가 CB-only로 회귀함
    MAX_DOCS_PER_SOURCE = 3

    # actor_map: {"actor_name": [(company, source, amount, rcept_no, role), ...]}
    # role은 임원 항목에만 채워진다(직위/등기 여부) — 동명이인을 눈으로
    # 가릴 수 있게 하는 사실 표기이며 필터가 아니다.
    actor_map: dict[str, list[tuple]] = {}
    per_company_solo: dict[str, list[tuple]] = {}
    failed: list[str] = []
    fetch_failed: list[str] = []   # 회사는 찾았는데 공시를 못 받은 것

    for query in company_names:
        result = resolve_corp(query, api_key)
        if not result:
            failed.append(query)
            continue
        corp_name, corp_info = result
        corp_code = corp_info["corp_code"]

        # 다년 조회인데 기본 상한(10페이지=1,000건)을 써서 절단되던 자리다
        # (2026-08-23 실측: 삼성전자 5년 3,547건 중 1,000건만 조회).
        # _resolve_lookback의 기존 관례대로 창에 비례해 올린다 — 1년
        # 코퍼스 기준 이 상한을 넘는 법인은 0.05%(대부분 펀드 공시를
        # 쏟아내는 자산운용사)라 그 이상은 과하다.
        # 조회 실패한 회사를 "비교했다"고 세면, 아래 요약의 "동시에 등장한
        # 인수자는 발견되지 않았습니다"가 **읽지 못한 회사를 근거로** 나온다.
        # 못 받은 회사는 analyzed에서 빼고 따로 알린다(2026-08-23 후속 감사).
        disclosures, fetch_status = fetch_company_disclosures_with_status(
            corp_code, api_key, lookback_days=lookback_days,
            max_pages=max(10, (lookback_days // 365 + 1) * 10),
        )
        if fetch_status == FETCH_ERROR:
            fetch_failed.append(query)   # analyzed 필터가 query 기준이다
            continue
        disclosures = disclosures or []

        cb_rcepts: list[str] = []
        rights_rcepts: list[str] = []
        for d in disclosures:
            report_nm = d.get("report_nm", "")
            rcept_no = d.get("rcept_no", "")
            if not rcept_no or is_amendment_disclosure(report_nm):
                continue
            signals = match_signals(report_nm) or []
            keys = {s["key"] for s in signals}
            if keys & CB_SIGNAL_KEYS and len(cb_rcepts) < MAX_DOCS_PER_SOURCE:
                cb_rcepts.append(rcept_no)
            if keys & RIGHTS_SIGNAL_KEYS and len(rights_rcepts) < MAX_DOCS_PER_SOURCE:
                rights_rcepts.append(rcept_no)
            # 두 소스 모두 상한에 도달하면 조기 종료 (최대 6건까지만 수집)
            if (len(cb_rcepts) >= MAX_DOCS_PER_SOURCE
                    and len(rights_rcepts) >= MAX_DOCS_PER_SOURCE):
                break

        investors: list[tuple] = []  # (source, inv_dict, rcept_no)
        for rn in cb_rcepts:
            for inv in (extract_cb_investors(rn, api_key, corp_code) or []):
                investors.append(("CB", inv, rn))
        for rn in rights_rcepts:
            for inv in (extract_rights_offering_investors(rn, api_key, corp_code) or []):
                investors.append(("유상증자", inv, rn))

        for source, inv, rn in investors:
            name = (inv.get("name") or "").strip()
            if not name:
                continue
            amount = inv.get("amount", "")
            entry = (corp_name, source, amount, rn, "")
            actor_map.setdefault(name, []).append(entry)
            per_company_solo.setdefault(corp_name, []).append(
                (name, source, amount, rn, ""))

        # 등기임원 겸직 수집 (조합명 비고정성 우회 — 사람 이름은 고정점)
        #
        # 직위·등기 여부를 함께 담는 `_detail`을 쓴다. 이름만 보면 **동명이인이
        # 세력으로 보인다** — 대조군 실측(2026-08-23): 삼성전자 「이혁재」는
        # 사외이사(등기), 셀트리온 「이혁재」는 수석부사장(미등기)인데 이름만
        # 같아서 "2개 회사에 등장"으로 표시됐다. 반대로 진짜 사례인
        # CG인바이츠·헬스커넥트의 신용규·이호영은 **양쪽 다 사내이사**다.
        # 직위를 사실로 병기하면 사용자가 그 둘을 눈으로 가를 수 있다.
        #
        # 거르지는 않는다 — 사외이사라고 세력이 아니라는 보장이 없고, 이
        # 레포는 판정을 하지 않는다(v0.8.5). 표기만 늘린다.
        # 같은 엔드포인트·같은 연도 루프라 호출 예산은 그대로다.
        for row in fetch_executive_roster_detail(
                corp_code, api_key, lookback_years) or []:
            name = (row.get("nm") or "").strip()
            if not name:
                continue
            year_label = ", ".join(row.get("years") or [])
            role = _exec_role_label(row)
            entry = (corp_name, "임원", year_label, "", role)
            actor_map.setdefault(name, []).append(entry)
            per_company_solo.setdefault(corp_name, []).append(
                (name, "임원", year_label, "", role))

    # 공통 인수자: 2개 이상 서로 다른 기업에 등장
    common = {
        actor: entries
        for actor, entries in actor_map.items()
        if len({e[0] for e in entries}) >= 2
    }
    singles = {
        actor: entries
        for actor, entries in actor_map.items()
        if len({e[0] for e in entries}) == 1
    }

    analyzed = [q for q in company_names if q not in failed and q not in fetch_failed]
    if not analyzed and fetch_failed:
        return _fetch_failed_notice(", ".join(fetch_failed), f"최근 {lookback_years}년")

    lines: list[str] = []
    lines.append(f"🔍 **여러 회사를 동시에 드나든 '돈을 댄 사람'(공통 행위자) 분석**")
    lines.append("")

    # 🎯 맨 위 요약 — 왜 이런 비교를 하는지 + 오늘 무엇을 찾았는지
    lines.append("🎯 **한눈에 보는 요약**")
    lines.append(
        "- 이 도구는 서로 다른 회사들의 전환사채(CB)·신주인수권부사채(BW)·"
        "교환사채(EB)·유상증자 '인수자' 명단을 모아, 두 회사 이상에 동시에 "
        "이름이 오른 개인·법인이 있는지 확인합니다."
    )
    lines.append(
        "- 같은 이름이 여러 회사의 자금조달에 반복 등장한다면, 우연의 일치가 "
        "아니라 같은 세력이 여러 상장사를 연쇄적으로 인수·유용하는 '무자본 "
        "M&A' 패턴을 의심해 볼 근거가 됩니다."
    )
    if common:
        lines.append(
            f"- 이번 비교({', '.join(analyzed)} · {len(analyzed)}개 회사)에서 "
            f"2곳 이상에 동시에 등장한 인수자가 **{len(common)}명/건** 발견됐습니다."
        )
    else:
        lines.append(
            f"- 이번 비교({', '.join(analyzed)} · {len(analyzed)}개 회사)에서 "
            "2곳 이상에 동시에 등장한 인수자는 발견되지 않았습니다."
        )
    lines.append("")

    if watchlist_note:
        lines.append(watchlist_note)
        lines.append("")

    if fetch_failed:
        lines.append(
            f"⚠ 공시를 불러오지 못해 비교에서 빠진 기업: {', '.join(fetch_failed)} "
            "— **신호가 없다는 뜻이 아닙니다.** DART 조회가 실패했습니다."
        )
        lines.append("")

    if failed:
        lines.append(
            f"ℹ️ DART에서 찾지 못한 기업: {', '.join(failed)} "
            "(기업명 철자나 종목코드를 다시 확인해 주세요.)"
        )
        lines.append("")

    lines.append("━━ 여러 회사에 동시에 등장한 인수자 ━━")
    if not common:
        lines.append(
            "  ✅ 2곳 이상에 공통으로 이름이 오른 인수자는 이번 비교 범위에서 "
            f"발견되지 않았습니다. 다만 이 결과는 {window_label}, 기업당 CB 최대 "
            "3건 + 유상증자 최대 3건으로 좁힌 범위의 판정입니다."
        )
    else:
        lines.append(
            "아래 인수자들은 비교 대상 회사 중 2곳 이상의 CB/BW/EB 또는 "
            "유상증자 공시에 이름이 올랐습니다. 괄호 안의 [CB] / [유상증자]는 "
            "어느 경로로 지분을 취득했는지를 뜻합니다."
        )
        for actor, entries in sorted(common.items(), key=lambda x: -len({e[0] for e in x[1]})):
            company_set = sorted({e[0] for e in entries})
            source_set = sorted({e[1] for e in entries})
            # 회사별 직위를 붙인다 — 「사외이사 ↔ 미등기 수석부사장」처럼
            # 갈리면 동명이인일 가능성을 사용자가 스스로 읽을 수 있다.
            shown = []
            for c in company_set:
                roles = sorted({e[4] for e in entries if e[0] == c and e[4]})
                shown.append(f"{c}({'/'.join(roles)})" if roles else c)
            lines.append(
                f"  ⚠️ **{actor}** — {len(company_set)}개 회사에 "
                f"[{' · '.join(source_set)}] 경로로 등장: "
                f"{', '.join(shown)}"
            )
    lines.append("")

    lines.append("━━ 회사별 전체 인수자·임원 명단 (중복 제거) ━━")
    for corp_name, entries in per_company_solo.items():
        # (name, source) 단위로 묶고, 임원은 연도라벨을 합집합으로 모은다
        seen: dict[tuple, set] = {}
        roles_of: dict[tuple, set] = {}
        for n, src, amt, _rn, role in entries:
            seen.setdefault((n, src), set())
            roles_of.setdefault((n, src), set())
            if src == "임원" and amt:
                seen[(n, src)].update(amt.split(", "))
            if role:
                roles_of[(n, src)].add(role)
        if not seen:
            continue
        lines.append(f"  • {corp_name} — 총 {len(seen)}명:")
        for (name, source), years in sorted(seen.items())[:10]:
            if source == "임원" and years:
                role = "/".join(sorted(roles_of.get((name, source)) or ()))
                suffix = f", {role}" if role else ""
                lines.append(
                    f"      [임원] {name} ({', '.join(sorted(years))}{suffix})")
            else:
                lines.append(f"      [{source}] {name}")

    no_data = [cn for cn in analyzed if cn not in per_company_solo]
    if no_data:
        lines.append("")
        lines.append(
            f"ℹ️ {window_label} 안에 CB·BW·EB·유상증자 공시 자체가 없는 회사: "
            f"{', '.join(no_data)}"
        )

    lines.append("")
    # 공개기록 대조 (사실 표면화 — 판정 아님)
    known_hits = []
    for nm in sorted(actor_map.keys()):
        recs = lookup_actor(nm)
        if recs:
            known_hits.append((nm, recs))
    if known_hits:
        lines.append("📎 공개기록 참고 (사실 표기 — 판정 아님):")
        for nm, recs in known_hits:
            for r in recs:
                src = r.get("source", "")
                date = r.get("date", "")
                ev = r.get("evidence", "")
                tag = f"{src}({date})" if date else src
                lines.append(f"  • {nm} — {tag}: {ev}")
        if any(actor_status(r) == "auto_matched" for _, recs in known_hits for r in recs):
            lines.append("  ⚠ 일부는 시장 공시 자동 매칭 (동일인 여부 미확인)")
        if any(actor_status(r) == "maintainer_seed" for _, recs in known_hits for r in recs):
            lines.append("  ⚠ 일부는 제작자 모니터링 등록 (공시 자동매칭 아님, 혐의·확정 아님)")
        lines.append("  ⚠ 원본 공시로 사실 확인 권장 · 동명이인 가능성 있음")
        lines.append("")

    lines.append(
        f"⚠️ 이 결과는 DART 공개 API 범위 내 분석입니다. {window_label} 이내 "
        "CB/BW/EB/유상증자 공시 인수자와 임원현황(등기임원) 겸직을 함께 대조하며, "
        "회사당 CB 최대 3건 + 유상증자 최대 3건으로 제한됩니다. 따라서 '공통 "
        "행위자 없음'이 '세력이 없다'는 결론으로 이어지지는 않습니다."
    )
    return "\n".join(lines)


# ── 도구 6: 종목코드로 공시 접수번호 목록 조회 ────────────────────────────


@mcp.tool()
def list_disclosures_by_stock(
    stock_code: str,
    lookback_years: int = 1,
    lookback_days: int | None = None,
    from_date: str = "",
    to_date: str = "",
) -> str:
    """종목코드로 최근 공시의 접수번호(rcept_no) 목록을 조회한다.

    반환된 접수번호는 get_disclosure_document, view_disclosure,
    check_disclosure_risk 등에 바로 사용할 수 있다.

    Args:
        stock_code: 종목코드 6자리 (예: "086520")
        lookback_years: 조회 기간(년). 기본 1년, 1~5년 범위.
    """
    import re as _re

    if not _DART_API_KEY:
        return "❌ DART_API_KEY 환경변수가 설정되지 않았습니다."

    if not _re.match(r"^\d{6}$", stock_code):
        return "❌ 종목코드는 6자리 숫자여야 합니다. 예: '086520'"

    bgn_de, end_de, lookback_days, max_pages, window_phrase, win_err = _resolve_window(
        lookback_years, lookback_days, from_date, to_date
    )
    if win_err:
        return f"❌ {win_err}"

    result = resolve_corp(stock_code, _DART_API_KEY)
    if not result:
        return f"❌ 종목코드 '{stock_code}'에 해당하는 기업을 DART에서 찾을 수 없습니다."

    corp_name, corp_info = result
    corp_code = corp_info["corp_code"]
    _alias_note = _alias_note_line(corp_info)
    _note_block = f"{_alias_note}\n\n" if _alias_note else ""

    disclosures, fetch_status = fetch_company_disclosures_with_status(
        corp_code, _DART_API_KEY, lookback_days, max_pages=max_pages,
        bgn_de=bgn_de, end_de=end_de,
    )
    if fetch_status == FETCH_ERROR:
        return _fetch_failed_notice(corp_name, window_phrase)
    if not disclosures:
        return (
            f"📋 **{corp_name}** ({stock_code})\n\n"
            f"{_note_block}"
            f"최근 {window_phrase}간 공시가 없습니다."
        )

    lines = [
        f"📋 **{corp_name}** ({stock_code}) 공시 접수번호 목록",
    ]
    if _alias_note:
        lines.append(_alias_note)
    lines += [
        f"조회 기간: 최근 {window_phrase} | 총 {len(disclosures)}건",
        "",
    ]
    for d in disclosures:
        rcept_no = d.get("rcept_no", "")
        report_nm = d.get("report_nm", "")
        rcept_dt = d.get("rcept_dt", "")[:10]
        lines.append(f"• {rcept_no}  {rcept_dt}  {report_nm}")

    lines += [
        "",
        "💡 접수번호로 원문을 읽으려면: get_disclosure_document(rcept_no=\"...\")",
    ]

    return _append_size_footer("\n".join(lines), lookback_years)


# ── 도구 5: 공시 원문 전체 조회 (단일 호출) ───────────────────────────────


@mcp.tool()
def get_disclosure_document(rcept_no: str, max_chars: int = 8000) -> str:
    """DART 공시 접수번호로 공시 원문 전체를 조회한다.

    한 번의 호출로 원문 내용과 수록 파일 목록을 반환한다.
    긴 문서는 max_chars로 제한하며, 잘린 경우 안내 메시지가 표시된다.
    더 긴 문서나 특정 섹션을 읽으려면 list_disclosure_sections / view_disclosure 를 사용한다.

    Args:
        rcept_no: DART 접수번호 14자리 (예: "20240315000123")
        max_chars: 최대 반환 글자수 (기본 8000, 최대 20000)
    """
    if not _DART_API_KEY:
        return "❌ DART_API_KEY 환경변수가 설정되지 않았습니다."
    if not rcept_no:
        return "❌ rcept_no(접수번호)를 입력하세요."

    result = fetch_disclosure_full(rcept_no, _DART_API_KEY, max_chars)

    if not result["text"] and not result["files"]:
        return f"❌ 접수번호 {rcept_no}의 공시 원문을 불러올 수 없습니다."

    files = result["files"]
    main_file = result["main_file"]
    text = result["text"]
    char_count = result["char_count"]
    truncated = result["truncated"]

    lines = [
        f"📄 **공시 원문 조회: {rcept_no}**",
        f"수록 파일 ({len(files)}개): {', '.join(files)}",
        f"주 문서: {main_file}",
        "",
        "━━ 원문 내용 ━━",
        text,
    ]

    if truncated:
        lines.append(f"\n... (전체 {char_count:,}자 중 {len(text):,}자 표시)")
        lines.append("💡 더 읽으려면: list_disclosure_sections / view_disclosure 도구를 사용하세요.")

    return "\n".join(lines)


# ── 도구 6: 공시 원문 목차 조회 ────────────────────────────────────────────


@mcp.tool()
def list_disclosure_sections(rcept_no: str) -> str:
    """DART 공시 원문의 목차(섹션 구조)를 조회한다.

    view_disclosure 호출 전에 이 도구로 섹션 ID와 분량을 먼저 확인하면 좋다.

    Args:
        rcept_no: DART 접수번호 14자리 (예: "20240315000123")
    """
    if not _DART_API_KEY:
        return "❌ DART_API_KEY 환경변수가 설정되지 않았습니다."
    if not rcept_no:
        return "❌ rcept_no(접수번호)를 입력하세요."

    file_list = list_document_sections(rcept_no, _DART_API_KEY)
    if not file_list:
        return f"❌ 접수번호 {rcept_no}의 공시 원문을 불러올 수 없습니다."

    lines = [f"📑 **공시 원문 목차**", f"접수번호: {rcept_no}", ""]

    for f in file_list:
        lines.append(f"━━ 파일 {f['file_index']}: {f['doc_title']} ━━")
        lines.append(f"   파일명: {f['filename']} | 전체 {f['char_length']:,}자")
        for sec in f["sections"]:
            tags = classify_note_title(sec.get("title", ""))
            suffix = ""
            if tags:
                labels = "·".join(NOTE_CATEGORIES[k][0] for k in tags)
                suffix = f"  ⟨주석: {labels}⟩"
            lines.append(f"   [{sec['id']}] {sec['title']}{suffix}")
        lines.append("")

    # 주석 카테고리 요약 — 섹션 제목 + 원문 <TITLE> 스캔 병합 (kreports NOTE_KEYWORDS 이식).
    # 사업보고서 주석 항목은 섹션으로 안 잡히는 경우가 많아 TITLE 스캔이 주 경로.
    try:
        _title_hits = scan_note_titles(rcept_no, _DART_API_KEY)
    except Exception:
        _title_hits = []
    note_summary = build_note_summary(file_list, _title_hits)
    if note_summary:
        lines.append("🔎 **주석 카테고리 감지** (제목 키워드 기준 — 원문 확인 필요)")
        for label, entries in note_summary:
            lines.append(f"   {label}: {', '.join(entries)}")
        lines.append(
            "   ↳ 섹션 id는 view_disclosure(section_id=...)로, "
            "'파일N (약 X% 지점)'은 view_disclosure(rcept_no, page=...)로 근처 페이지를 여세요."
        )
        lines.append("")

    lines.append("💡 view_disclosure(rcept_no, section_id=\"...\") 로 특정 섹션을 읽을 수 있습니다.")
    return "\n".join(lines)


# ── 도구 5: 공시 원문 내용 조회 ────────────────────────────────────────────


@mcp.tool()
def view_disclosure(
    rcept_no: str,
    section_id: str = "",
    page: int = 1,
    page_size: int = 4000,
) -> str:
    """DART 공시 원문을 조회한다. 섹션 지정 또는 페이지 단위로 전체 원문을 읽을 수 있다.

    사용법:
    1. list_disclosure_sections(rcept_no) → 목차/섹션 ID 확인
    2. view_disclosure(rcept_no, section_id="f0s2") → 특정 섹션 읽기
    3. view_disclosure(rcept_no, page=2) → 다음 페이지로 순차 읽기

    Args:
        rcept_no: DART 접수번호 14자리 (예: "20240315000123")
        section_id: 섹션 ID (list_disclosure_sections 결과 참조, 비워두면 전체 문서)
        page: 페이지 번호 (기본 1)
        page_size: 페이지당 글자 수 (기본 4000, 범위 1000~8000)
    """
    if not _DART_API_KEY:
        return "❌ DART_API_KEY 환경변수가 설정되지 않았습니다."
    if not rcept_no:
        return "❌ rcept_no(접수번호)를 입력하세요."
    page_size = max(1000, min(8000, page_size))

    # section_id에서 file_index 파싱
    file_index = 0
    import re as _re
    fi_m = _re.match(r"f(\d+)", section_id)
    if fi_m:
        file_index = int(fi_m.group(1))

    result = fetch_document_content(
        rcept_no=rcept_no,
        api_key=_DART_API_KEY,
        file_index=file_index,
        section_id=section_id or None,
        page=page,
        page_size=page_size,
    )

    if not result["content"]:
        return f"❌ 접수번호 {rcept_no}의 원문을 불러올 수 없습니다."

    total = result["total_pages"]
    cur = result["page"]

    header_lines = [
        f"📄 **공시 원문** (페이지 {cur}/{total})",
        f"접수번호: {rcept_no}" + (f" | 섹션: {section_id}" if section_id else ""),
        f"파일: {result['doc_title']}",
        "━" * 40,
        "",
    ]

    footer_lines = ["", "━" * 40]
    if result["has_more"]:
        next_args = f'rcept_no="{rcept_no}", page={cur + 1}'
        if section_id:
            next_args += f', section_id="{section_id}"'
        footer_lines.append(f"▶ 다음 페이지: view_disclosure({next_args})")
    else:
        footer_lines.append("✅ 마지막 페이지입니다.")

    return "\n".join(header_lines) + result["content"] + "\n".join(footer_lines)


# ── 도구 10: 기업 개요 조회 ───────────────────────────────────────────────


@mcp.tool()
def get_company_info(company_name: str) -> str:
    """기업 개요를 조회한다 (대표자, 업종, 설립일, 상장 구분 등).

    Args:
        company_name: 기업명 (예: "삼성전자") 또는 종목코드 6자리 (예: "005930")
    """
    if not _DART_API_KEY:
        return "❌ DART_API_KEY 환경변수가 설정되지 않았습니다."

    result = resolve_corp(company_name, _DART_API_KEY)
    if not result:
        return f"❌ '{company_name}'에 해당하는 기업을 DART에서 찾을 수 없습니다."
    corp_name, corp_info = result
    corp_code = corp_info["corp_code"]

    info = fetch_company_info(corp_code, _DART_API_KEY)
    if not info:
        return f"❌ {corp_name}의 기업 개요를 불러올 수 없습니다."

    lines = [
        f"🏢 **기업 개요: {info.get('corp_name', corp_name)}**",
    ]
    _alias_note = _alias_note_line(corp_info)
    if _alias_note:
        lines.append(_alias_note)
    lines += [
        "",
        f"• 종목코드: {info.get('stock_code', '-')}",
        f"• 대표자: {info.get('ceo_nm', '-')}",
        f"• 법인구분: {info.get('corp_cls_nm', '-')}",
        f"• 업종: {info.get('induty_code', '-')}",
        f"• 설립일: {info.get('est_dt', '-')}",
        f"• 결산월: {info.get('acc_mt', '-')}월",
        f"• 주소: {info.get('adres', '-')}",
        f"• 홈페이지: {info.get('hm_url', '-')}",
        f"• IR: {info.get('ir_url', '-')}",
        f"• 전화: {info.get('phn_no', '-')}",
    ]
    return "\n".join(lines)


# ── 도구 11: 재무제표 조회 ────────────────────────────────────────────────


@mcp.tool()
def get_financial_summary(
    company_name: str, year: str = "", report_type: str = "annual"
) -> str:
    """기업의 주요 재무제표를 조회한다 (매출, 영업이익, 순이익, 자산, 부채).

    Args:
        company_name: 기업명 (예: "삼성전자") 또는 종목코드 6자리
        year: 사업연도 4자리 (예: "2024"). 미입력 시 직전 연도
        report_type: 보고서 유형 — "annual"(사업보고서), "half"(반기), "q1"(1분기), "q3"(3분기)
    """
    if not _DART_API_KEY:
        return "❌ DART_API_KEY 환경변수가 설정되지 않았습니다."

    result = resolve_corp(company_name, _DART_API_KEY)
    if not result:
        return f"❌ '{company_name}'에 해당하는 기업을 DART에서 찾을 수 없습니다."
    corp_name, corp_info = result
    corp_code = corp_info["corp_code"]
    stock_code = corp_info.get("stock_code", "")

    items = fetch_financial_statements(corp_code, _DART_API_KEY, year, report_type)
    if not items:
        return f"❌ {corp_name}의 재무제표를 불러올 수 없습니다. 연도/보고서 유형을 확인하세요."

    # 연결/개별 구분
    fs_div = items[0].get("fs_div", "")
    fs_label = "연결재무제표" if fs_div == "CFS" else "개별재무제표"
    bsns_year = items[0].get("bsns_year", year)

    lines = [
        f"📊 **{corp_name} 재무제표** ({stock_code or corp_code})",
        f"사업연도: {bsns_year} | {fs_label}",
        "",
    ]

    for item in items:
        nm = item.get("account_nm", "")
        cur = item.get("thstrm_amount", "-")
        prev = item.get("frmtrm_amount", "-")
        lines.append(f"• {nm}: {cur} (전기: {prev})")

    lines += [
        "",
        "⚠️ 금액 단위는 원화(원)이며 DART 공시 기준입니다.",
    ]
    return "\n".join(lines)


# ── 도구 12: 다중 기업 재무 비교 ──────────────────────────────────────────


@mcp.tool()
def compare_financials(company_names: list[str], year: str = "") -> str:
    """여러 기업의 재무제표를 비교한다 (최대 5개 기업).

    매출액, 영업이익, 당기순이익, 자산총계, 부채총계를 나란히 비교한다.

    Args:
        company_names: 비교할 기업명 목록 (2~5개, 예: ["삼성전자", "SK하이닉스"])
        year: 사업연도 4자리 (예: "2024"). 미입력 시 직전 연도
    """
    if not _DART_API_KEY:
        return "❌ DART_API_KEY 환경변수가 설정되지 않았습니다."
    if len(company_names) < 2:
        return "❌ 최소 2개 기업을 입력하세요."
    if len(company_names) > 5:
        return "❌ 최대 5개 기업까지 비교할 수 있습니다."

    # 기업 코드 수집
    corp_map: list[tuple[str, str]] = []  # (corp_name, corp_code)
    failed: list[str] = []
    for name in company_names:
        result = resolve_corp(name, _DART_API_KEY)
        if not result:
            failed.append(name)
            continue
        corp_name, corp_info = result
        corp_map.append((corp_name, corp_info["corp_code"]))

    if len(corp_map) < 2:
        return f"❌ 비교 가능한 기업이 2개 미만입니다. 찾을 수 없는 기업: {', '.join(failed)}"

    corp_codes = [cc for _, cc in corp_map]
    items = fetch_multi_financial(corp_codes, _DART_API_KEY, year)

    if not items:
        return "❌ 재무 데이터를 불러올 수 없습니다. 연도를 확인하세요."

    # 기업별 그룹핑
    by_corp: dict[str, list[dict]] = {}
    for item in items:
        cname = item.get("corp_name", item.get("stock_code", ""))
        by_corp.setdefault(cname, []).append(item)

    lines = [
        f"📊 **재무 비교** ({len(by_corp)}개 기업)",
        "",
    ]

    if failed:
        lines.append(f"⚠️ 찾을 수 없는 기업: {', '.join(failed)}")
        lines.append("")

    for cname, corp_items in by_corp.items():
        lines.append(f"━━ {cname} ━━")
        for item in corp_items:
            nm = item.get("account_nm", "")
            cur = item.get("thstrm_amount", "-")
            lines.append(f"  • {nm}: {cur}")
        lines.append("")

    lines.append("⚠️ 금액 단위는 원화(원)이며 DART 공시 기준입니다.")
    return "\n".join(lines)


# ── 도구 13: 최대주주/대량보유자 조회 ─────────────────────────────────────


@mcp.tool()
def get_shareholder_info(company_name: str, year: str = "") -> str:
    """기업의 최대주주 및 5% 이상 대량보유자 현황을 조회한다.

    Args:
        company_name: 기업명 (예: "삼성전자") 또는 종목코드 6자리
        year: 사업연도 4자리 (예: "2024"). 미입력 시 직전 연도
    """
    if not _DART_API_KEY:
        return "❌ DART_API_KEY 환경변수가 설정되지 않았습니다."

    result = resolve_corp(company_name, _DART_API_KEY)
    if not result:
        return f"❌ '{company_name}'에 해당하는 기업을 DART에서 찾을 수 없습니다."
    corp_name, corp_info = result
    corp_code = corp_info["corp_code"]
    stock_code = corp_info.get("stock_code", "")

    data = fetch_shareholder_status(corp_code, _DART_API_KEY, year)

    major = data.get("major_holders", [])
    bulk = data.get("bulk_holders", [])

    if not major and not bulk:
        return f"❌ {corp_name}의 주주 정보를 불러올 수 없습니다. 연도를 확인하세요."

    lines = [
        f"👥 **주주 현황: {corp_name}** ({stock_code or corp_code})",
        "",
    ]

    if major:
        lines.append("━━ 최대주주 및 특수관계인 ━━")
        for h in major:
            nm = h.get("nm", "-")
            relate = h.get("relate", "")
            stock_cnt = h.get("bsis_posesn_stock_co", "-")
            ratio = h.get("bsis_posesn_stock_qota_rt", "-")
            lines.append(f"  • {nm} ({relate}): {stock_cnt}주 ({ratio}%)")
        lines.append("")

    if bulk:
        lines.append("━━ 5% 이상 대량보유자 ━━")
        for h in bulk:
            nm = h.get("reprt_nm", h.get("nm", "-"))
            stock_cnt = h.get("stkqy", "-")
            ratio = h.get("stkrt", "-")
            lines.append(f"  • {nm}: {stock_cnt}주 ({ratio}%)")
        lines.append("")

    lines.append("⚠️ DART 공시 기준이며, 최신 변동 사항은 반영되지 않을 수 있습니다.")
    return "\n".join(lines)


# ── 도구 14: 시장 전체 preset 스캔 ─────────────────────────────────────────

_PRESET_TO_SIGNALS: dict[str, list[str]] = {
    # CB_REPAY·CB_ROLLOVER·CB_BUYBACK·TREASURY_EB는 제목으로 발화하지 않아
    # (1년 실측 0건, NON_TITLE_SIGNALS 참고) preset에서 뺐다 — 남겨 두면
    # 이 preset이 그 유형까지 훑는다는 인상을 준다. 해당 공시는 CB_BW·EB·
    # TREASURY가 이미 잡는다.
    "cb_issue":           ["CB_BW", "EB", "RCPS"],
    "treasury":           ["TREASURY"],
    # GAMJA_MERGE·CAPITAL_RED도 같은 이유로 제거 — 감자·합병 제목은
    # REVERSE_SPLIT·MGMT가 잡고, CAPITAL_RED의 후보였던 「주식소각결정」은
    # 원문상 주주환원이라 의미가 반대다(2026-08-22 2차 정리).
    "reverse_split":      ["REVERSE_SPLIT"],
    # RIGHTS_UNDER 제거 — 후보였던 「주주배정후 실권주 일반공모」는 실권주가
    # **일반투자자**에게 넘어간 건이라 taxonomy 2.5("특수관계인이 인수")와
    # 조건이 정반대다(2026-08-22 원문 실측).
    "3pca":               ["3PCA"],
    "shareholder_change": ["SHAREHOLDER", "MGMT_DISPUTE"],
    "exec_change":        ["EXEC"],
    "audit_issue":        ["AUDIT", "DISCLOSURE_VIOL"],
    # ASSET_SPIRAL 제거(연쇄·헐값은 단건 제목으로 판정 불가). ASSET_TRANSFER는
    # 2026-08-22 실측 표기로 되살아나 이 preset이 실제로 동작하게 됐다.
    "asset_transfer":     ["ASSET_TRANSFER", "DEMERGER"],
    "going_concern":      ["GOING_CONCERN", "INSOLVENCY", "DEBT_RESTR"],
    # DELISTING_RISK는 전용 preset으로 분리한다 — going_concern에 합류시켰더니
    # 라이브 14일 스캔에서 표시 40건 중 39건이 상장폐지 절차가 되어 기존
    # GOING_CONCERN·INSOLVENCY 발화를 덮었다(실측 2026-08-22). 발화량이 크게
    # 다른 신호를 한 preset에 섞으면 적은 쪽이 보이지 않는다.
    # 퇴출 트랙 두 단계를 한 preset에 둔다 — 발화량이 비슷해(90일 실측:
    # DELISTING_RISK 177건 · WATCH_ISSUE 120건) 한쪽이 다른 쪽을 덮지 않고,
    # 행마다 라벨이 달라 단계를 구분할 수 있다. going_concern에 합류시켰을 때
    # 생겼던 잠식(표시 40건 중 39건)과는 상황이 다르다.
    "delisting":          ["DELISTING_RISK", "WATCH_ISSUE"],
    "embezzle":           ["EMBEZZLE"],
    "inquiry":            ["INQUIRY"],
    "fund_outflow":       ["FUND_OUTFLOW", "ACQ_REVIEW"],
    "all_risk":           [],  # 모든 신호
}


@mcp.tool()
def get_affiliate_investments(company_name: str, year: str = "") -> str:
    """
    타법인 출자현황을 조회합니다 — 이 회사가 어떤 법인들에 돈을 넣었는지.

    피출자 법인명·출자목적·기말 지분율·장부가액·최초취득일·피투자사
    최근 재무(총자산/순이익)를 사실로 나열합니다. 무자본 M&A 세력의
    SPC·자회사망 추적, 특수관계자 자산 공동화 패턴 확인에 활용합니다.

    Args:
        company_name: 기업명 또는 종목코드(6자리).
        year: 사업연도(예: "2024"). 빈 값이면 직전 연도.

    Returns:
        출자 내역 표(장부가액 상위 30건) + 요약 사실 + 단위 유의 안내.
    """
    api_key = os.environ.get("DART_API_KEY", "")
    if not api_key:
        return "❌ DART_API_KEY 환경변수가 설정되지 않았습니다."

    corp_info = resolve_corp(company_name, api_key)
    if not corp_info or not corp_info[1]:
        return f"❌ 기업 '{company_name}'을(를) 찾을 수 없습니다."
    corp_name, info = corp_info
    corp_code = info["corp_code"]

    if not year:
        from datetime import datetime
        year = str(datetime.now().year - 1)

    rows = fetch_affiliate_investments(corp_code, api_key, year)
    if not rows:
        return (f"🏢 **{corp_name}** ({info.get('stock_code','')}) — 타법인 출자현황 ({year})\n\n"
                "해당 연도 사업보고서에서 타법인 출자 내역을 찾지 못했습니다. "
                "(출자가 없거나, 보고서 미제출·데이터 미제공일 수 있습니다)")

    def _ratio(r):
        try:
            return float(str(r.get("trmend_blce_qota_rt", "")).replace(",", ""))
        except (TypeError, ValueError):
            return None

    def _book(r):
        v = _parse_fs_amount(r.get("trmend_blce_acntbk_amount"))
        return v if v is not None else -1

    # 요약 사실
    total = len(rows)
    majority = sum(1 for r in rows if (_ratio(r) or 0) >= 50)
    loss_cnt = 0
    for r in rows:
        ni = _parse_fs_amount(r.get("recent_bsns_year_fnnr_sttus_thstrm_ntpf"))
        if ni is not None and ni < 0:
            loss_cnt += 1
    new_cnt = sum(1 for r in rows if str(r.get("frst_acqs_de", "")).startswith(year))

    lines = [
        f"🏢 **{corp_name}** ({info.get('stock_code','')}) — 타법인 출자현황 ({year} 사업보고서 기준)",
        "",
        f"총 {total}건 · 기말 지분율 50% 이상 {majority}건 · "
        f"피투자사 최근 사업연도 순이익 적자 {loss_cnt}건 · {year}년 신규 취득 {new_cnt}건",
        "",
        "| 피출자 법인 | 출자목적 | 기말지분율(%) | 기말장부가액 | 최초취득일 | 피투자사 순이익 |",
        "|---|---|---|---|---|---|",
    ]

    def _cell(v) -> str:
        """마크다운 표 셀 정제 — 개행·파이프가 표 구조를 깨지 않게."""
        s = str(v if v not in (None, "") else "-").strip()
        return " ".join(s.replace("|", "／").split())

    shown = sorted(rows, key=_book, reverse=True)[:30]
    for r in shown:
        lines.append(
            f"| {_cell(r.get('inv_prm'))} | {_cell(r.get('invstmnt_purps'))} "
            f"| {_cell(r.get('trmend_blce_qota_rt'))} | {_cell(r.get('trmend_blce_acntbk_amount'))} "
            f"| {_cell(r.get('frst_acqs_de'))} | {_cell(r.get('recent_bsns_year_fnnr_sttus_thstrm_ntpf'))} |"
        )

    if total > len(shown):
        lines.append("")
        lines.append(f"... 외 {total - len(shown)}건 (장부가액 상위 30건만 표시)")

    lines.append("")
    lines.append(
        "📎 참고: 금액은 DART 응답 원문 표기 그대로이며 보고서에 따라 단위(천원/백만원)가 "
        "다를 수 있습니다 — 정확한 단위는 공시 원문을 확인하세요. 지분율 50% 이상이라도 "
        "연결 종속 여부는 실질지배력 판단에 따릅니다."
    )
    lines.append(
        "💡 같은 인물·조합이 여러 회사에 등장하는지는 `find_actor_overlap`, "
        "연결/별도 순이익 역전 여부는 `scan_financial_anomaly`와 함께 보면 "
        "출자망의 의미를 입체적으로 볼 수 있습니다."
    )
    return "\n".join(lines)


def _filter_market_rows(
    raw: list[dict], target_keys: set
) -> "tuple[list[tuple[dict, list]], int]":
    """시장 스캔 행을 한정해 관찰 신호만 남긴다.

    (filtered, procedural_count)를 반환한다. filtered의 원소는
    (list.json 행, list[Qualified])이며 Qualified는 observed만 담는다.

    네트워크를 타지 않는 순수 함수로 분리해 합성 행으로 테스트할 수 있게 했다.
    preset 필터를 observed에만 거는 것이 핵심이다 — 강등된 신호가 preset을
    통과시키면 제외의 의미가 없다.

    procedural_count는 preset(target_keys) 범위로 스코프한다 — target_keys가
    있으면 그 preset의 신호 키를 하나라도 가진(강등되기 전 qual 기준) 행만
    센다. 전체 시장의 강등 건수를 preset과 무관하게 더하면 "관찰 신호 M건"은
    preset 범위인데 "절차·사후 보고 K건"은 시장 전체 범위가 되어 같은 문장
    안에서 서로 다른 모집단을 말하게 된다(fix round 1 발견). target_keys가
    비어 있으면(all_risk) 이 구분이 없어 기존처럼 모든 강등 행을 센다.
    """
    filtered: list[tuple[dict, list]] = []
    procedural_count = 0
    for d in raw:
        report_nm = d.get("report_nm", "")
        sigs = match_signals(report_nm)
        if not sigs:
            continue
        parsed = parse_report_name(report_nm)
        qual = qualify_signals(sigs, parsed, d)
        obs = [q for q in qual if q.tier == TIER_OBSERVED]
        if not obs:
            if not target_keys or any(q.key in target_keys for q in qual):
                procedural_count += 1
            continue
        if target_keys and not any(q.key in target_keys for q in obs):
            continue
        filtered.append((d, obs))
    return filtered, procedural_count


# 시장 스캔 대기 예산 (v1.18.1)
#
# 허용 대기는 1분이다. 시장 스캔은 창에 비례해 길어지므로 어느 창부터
# 분기를 줄지 실측으로 정한다 — 7일 17.7초 · 14일 107.5초(2026-08-23,
# 하루 청크 전환 전 기준). 경계는 그 사이이고, 여유를 둬 10일로 잡는다.
_LONG_SCAN_DAYS = 10

# 하루당 조회 페이지 추정 — 1년 코퍼스 실측(270,882건 / 244영업일)에서
# 하루 중앙값 774건(8페이지)이다. 주말은 공시가 거의 없어 달력일 기준
# 평균은 이보다 낮지만, 안내는 넉넉한 쪽으로 말한다.
_EST_PAGES_PER_DAY = 8
_EST_SECONDS_PER_PAGE = 0.75      # API 응답 0.6초 + 간격


def _estimate_scan_seconds(days: int) -> int:
    """이 창을 스캔하는 데 걸릴 대략의 초. 안내 문구 전용(정확한 값이 아니다)."""
    return int(days * _EST_PAGES_PER_DAY * _EST_SECONDS_PER_PAGE)


@mcp.tool()
def search_market_disclosures(
    preset: str,
    days: int = 7,
    max_results: int = 50,
    from_date: str = "",
    to_date: str = "",
    confirm_long: bool = False,
) -> str:
    """시장 전체 공시에서 preset에 해당하는 위험 신호를 일괄 스캔한다.

    기업명을 지정하지 않고 전체 상장사 공시를 조회하므로, 특정 위험 신호가 시장에
    얼마나 확산되어 있는지 조기경보로 활용할 수 있다.

    사용법:
    - "최근 7일 동안 CB/BW 발행 공시 전수": search_market_disclosures("cb_issue", 7)
    - "최근 30일 자사주 취득 결정": search_market_disclosures("treasury", 30)
    - "최근 14일 감자 공시": search_market_disclosures("reverse_split", 14)

    Args:
        preset: 신호 프리셋 — cb_issue / treasury / reverse_split / 3pca /
                shareholder_change / exec_change / audit_issue / asset_transfer /
                going_concern / delisting / embezzle / inquiry / fund_outflow /
            all_risk
        days: 조회 기간 (기본 7일, 최대 90일). from_date/to_date를 주면 무시된다.
        max_results: 최대 반환 건수 (기본 50, 최대 200)
        from_date: 조회 시작일(선택). "2024-01-01"·"20240101" 형식.
        to_date: 조회 종료일(선택). 미지정 시 오늘.
        confirm_long: 창이 길어 오래 걸리는 조회를 실제로 실행할지. 미지정
            상태로 긴 창을 요청하면 예상 소요와 함께 안내만 반환한다.
    """
    from datetime import datetime, timedelta

    if not _DART_API_KEY:
        return "❌ DART_API_KEY 환경변수가 설정되지 않았습니다."
    if preset not in _PRESET_TO_SIGNALS:
        return (
            f"❌ 알 수 없는 preset: {preset!r}\n"
            f"허용값: {', '.join(sorted(_PRESET_TO_SIGNALS))}"
        )
    max_results = max(1, min(200, max_results))

    now = datetime.now()

    # 시점 지정 — 주면 days를 무시한다(analyze_company_risk와 같은 계약)
    if from_date or to_date:
        _bgn = normalize_date8(from_date) if from_date else ""
        _end = normalize_date8(to_date) if to_date else ""
        if from_date and not _bgn:
            return f"❌ from_date 형식이 올바르지 않습니다: {from_date!r} (예: 2024-01-01)"
        if to_date and not _end:
            return f"❌ to_date 형식이 올바르지 않습니다: {to_date!r} (예: 2024-06-30)"
        _end = _end or now.strftime("%Y%m%d")
        _bgn = _bgn or (datetime.strptime(_end, "%Y%m%d") - timedelta(days=6)).strftime("%Y%m%d")
        if _bgn > _end:
            return f"❌ from_date({_bgn})가 to_date({_end})보다 뒤입니다."
        scan_start = datetime.strptime(_bgn, "%Y%m%d")
        scan_end = datetime.strptime(_end, "%Y%m%d")
        days = (scan_end - scan_start).days + 1
        if days > 90:
            return (
                f"❌ 조회 구간이 {days}일입니다 — 시장 전체 스캔은 최대 90일까지"
                " 지원합니다. 구간을 나눠 조회하세요."
            )
        window_label = f"{_bgn[:4]}.{_bgn[4:6]}.{_bgn[6:]}~{_end[:4]}.{_end[4:6]}.{_end[6:]}"
    else:
        days = max(1, min(90, days))
        # 양끝 포함이라 days-1을 빼야 정확히 days일 창이 된다
        scan_start = now - timedelta(days=days - 1)
        scan_end = now
        window_label = f"최근 {days}일"

    # 대기 예산 분기 — 시장 스캔은 하루당 여러 페이지를 훑어 창에 비례해
    # 길어진다(실측: 7일 17.7초 · 14일 107.5초 · 30일 219초 · 90일 671초).
    # 허용 대기 1분을 넘길 창은 바로 실행하지 않고, 예상 소요와 좁히는 법을
    # 안내한 뒤 confirm_long=True를 받아 실행한다 — 11분을 기다리게 해놓고
    # 결과가 절단돼 있는 것보다, 무엇을 기다리는지 먼저 아는 편이 낫다.
    if days > _LONG_SCAN_DAYS and not confirm_long:
        est = _estimate_scan_seconds(days)
        return (
            f"⏳ **{window_label} 스캔은 약 {est // 60}분 {est % 60}초 걸립니다**\n"
            "(하루 평균 8페이지를 훑고, 공시가 몰린 날은 60페이지가 넘습니다.)\n\n"
            "그대로 진행하려면:\n"
            f'  `search_market_disclosures("{preset}", days={days}, confirm_long=True)`\n\n'
            "더 빨리 보려면 구간을 좁히세요:\n"
            f'  `search_market_disclosures("{preset}", days={_LONG_SCAN_DAYS})`  '
            f"— 약 {_estimate_scan_seconds(_LONG_SCAN_DAYS)}초\n"
            f'  `search_market_disclosures("{preset}", from_date="2026-03-01", to_date="2026-03-31")`'
            "  — 특정 달만"
        )

    # 날짜 청크 스캔 — 한 호출(max_pages=10, 1,000건)로 창 전체를 덮으려던
    # 기존 방식은 시장 일평균 공시가 ~500건이라 2~3일이면 상한에 걸리고,
    # DART가 최신순으로 주므로 "최근 30일" 요청이 실제로는 최근 1~2일만
    # 스캔되는 조용한 절단이 있었다(실사고 2026-08-05: asset_transfer 30일
    # 스캔이 7/22 아틀라스링크 유형자산양수를 놓침). 2일 청크면 청크당
    # 상한(1,000건) 아래에 안전히 들어온다. 그래도 상한에 닿은 청크는
    # 절단 가능으로 세어 커버리지를 정직하게 보고한다.
    # **하루 청크로 직행한다** (v1.18.1). 옛 구현은 2일 청크로 돌다 상한에
    # 닿으면 하루로 재분할했는데, 1년 코퍼스 실측에서 **2일 묶음의 92%가
    # 상한에 닿았다**(122개 중 112개). 거의 항상 재분할된다면 2일 청크는
    # 헛조회를 한 번 더 하는 것일 뿐이라, 처음부터 하루씩 도는 편이 호출이
    # 적고 절단도 없다.
    #
    # 하루 상한도 15페이지(1,500건)에서 70페이지(7,000건)로 올린다. 실측
    # 하루 분포는 중앙값 774 · p90 2,224 · **최대 6,006**건이라, 옛 상한은
    # 영업일의 18%에서 깨졌다. 70페이지면 244영업일 전부를 덮는다.
    _PAGES_PER_DAY = 70
    raw: list[dict] = []
    seen_rcept: set[str] = set()
    truncated_chunks = 0

    def _collect(items: list[dict]) -> None:
        for d in items:
            rc = d.get("rcept_no", "")
            if rc and rc in seen_rcept:
                continue
            if rc:
                seen_rcept.add(rc)
            raw.append(d)

    # 하루라도 조회에 실패하면 그날 공시가 통째로 빠진다. 절단은 이미
    # 알리면서 실패는 안 알리고 있었다(2026-08-23 후속 감사) — 스캔이
    # 완전했던 것처럼 보이는 쪽이 더 위험하다.
    failed_days: list[str] = []
    cur = scan_start
    while cur <= scan_end:
        day_str = cur.strftime("%Y%m%d")
        day_items, day_status = fetch_market_disclosures_with_status(
            _DART_API_KEY, day_str, day_str, max_pages=_PAGES_PER_DAY,
        )
        if day_status == FETCH_ERROR:
            failed_days.append(day_str)
        if len(day_items) >= _PAGES_PER_DAY * 100:
            truncated_chunks += 1
        _collect(day_items)
        cur += timedelta(days=1)

    if not raw:
        return f"❌ {window_label} 시장 공시를 불러올 수 없습니다."

    if failed_days:
        _fd = ", ".join(failed_days[:5]) + ("…" if len(failed_days) > 5 else "")
        failed_note = (
            f"⚠ 조회에 실패한 날: {len(failed_days)}일 ({_fd}) "
            "— **그날 신호가 없다는 뜻이 아닙니다.** 아래 목록에서 빠져 "
            "있습니다. 창을 좁혀 다시 시도하면 채워집니다."
        )
    else:
        failed_note = ""

    target_keys = set(_PRESET_TO_SIGNALS[preset])

    filtered, procedural_count = _filter_market_rows(raw, target_keys)

    filtered.sort(key=lambda x: x[0].get("rcept_dt", ""), reverse=True)
    truncated = len(filtered) > max_results
    shown = filtered[:max_results]

    coverage = (
        f"전체 {len(raw)}건 중 관찰 신호 {len(filtered)}건 "
        f"(표시 {len(shown)}건)"
    )
    if procedural_count:
        coverage += f" · 절차·사후 보고 {procedural_count}건 제외"
    if failed_days:
        coverage += f" · 조회 실패 {len(failed_days)}일 제외"
    if truncated_chunks:
        coverage += (
            f" · 스캔 구간 일부 절단({truncated_chunks}일이 상한 7,000건 도달"
            " — 해당 일자 공시가 매우 많아 일부 누락 가능)"
        )
    lines = [
        f"🔍 **시장 공시 스캔** (preset={preset}, {window_label})",
        coverage,
        "",
    ]

    if failed_note:
        lines += [failed_note, ""]

    if not shown:
        # 실패한 날이 있으면 ✅로 단정하지 않는다 — 못 본 날이 있는 채로
        # "없습니다"를 체크표시와 함께 내면 스캔이 완전했다는 뜻이 된다.
        if failed_days:
            lines.append(
                f"이번 스캔에서 '{preset}' 프리셋에 해당하는 공시는 나오지 "
                f"않았습니다. 다만 위 {len(failed_days)}일은 조회하지 못했습니다."
            )
            return "\n".join(lines)
        lines.append(f"✅ 해당 기간에 '{preset}' 프리셋에 해당하는 공시가 없습니다.")
        return "\n".join(lines)

    lines.append(f"{'─' * 60}")
    for d, sigs in shown:
        corp_nm = d.get("corp_name", "-")
        rcept_dt = d.get("rcept_dt", "")
        rcept_no = d.get("rcept_no", "")
        report_nm = d.get("report_nm", "")
        sig_labels = ", ".join(q.label for q in sigs)
        lines.append(f"{rcept_dt} | {corp_nm}")
        lines.append(f"  📄 {report_nm}")
        lines.append(f"  🔖 [{sig_labels}] rcept_no={rcept_no}")

    if truncated:
        lines += ["", f"⚠️ {len(filtered) - max_results}건 더 있음. max_results 를 늘리세요."]

    lines += [
        "",
        "💡 개별 공시 상세: check_disclosure_risk(rcept_no=...)",
        "💡 기업 종합 분석: analyze_company_risk(company_name=...)",
    ]
    return "\n".join(lines)


@mcp.tool()
def get_executive_compensation(
    company_name: str,
    year: str = "",
    report_type: str = "annual",
) -> str:
    """임원 보수 현황을 조회합니다 (불공정거래 탐지 참고 자료).

    5억 이상 고액수령자·개인별 보수·미등기임원 보수·주총 승인 한도
    4개 섹션을 반환합니다.

    Args:
        company_name: 기업명 또는 종목코드
        year: 사업연도 (기본값: 직전 연도)
        report_type: annual(사업) | half(반기) | q1(1분기) | q3(3분기)

    Returns:
        임원 보수 4섹션 텍스트
    """
    if not _DART_API_KEY:
        return "오류: DART_API_KEY 환경변수가 설정되지 않았습니다."

    _resolved = resolve_corp(company_name, _DART_API_KEY)
    corp_name, meta = _resolved if _resolved else ("", {})
    if not corp_name:
        return f"기업을 찾을 수 없습니다: {company_name}"
    corp_code = meta["corp_code"]

    data = fetch_executive_compensation(corp_code, _DART_API_KEY, year, report_type)
    if data.get("fetch_failed"):
        # 4개 엔드포인트가 모두 실패 — 「(공시 없음)」 네 줄로 보이면
        # 보수 공시가 없는 회사와 구분되지 않는다.
        return _fetch_failed_notice(corp_name, f"{year}년 {report_type}")

    import datetime as _dt
    display_year = year or str(_dt.datetime.now().year - 1)

    def _rows(items: list[dict], cols: list[tuple[str, str]]) -> str:
        if not items:
            return "    (공시 없음)"
        lines = []
        for item in items:
            parts = [f"{label}: {item.get(key, '-')}" for key, label in cols]
            lines.append("    • " + " | ".join(parts))
        return "\n".join(lines)

    high_pay_cols = [("nm", "성명"), ("ofcps", "직위"), ("mendng_totamt", "보수총액(원)")]
    indv_cols = [("nm", "성명"), ("ofcps", "직위"), ("mendng_totamt", "보수총액(원)"), ("stk_optn_exrcs_mny", "스톡옵션행사액")]
    unreg_cols = [("mendng_totamt", "미등기임원 보수총액(원)"), ("nmpr", "인원수")]
    agm_cols = [("mendng_totamt", "주총승인 보수한도(원)"), ("nmpr", "이사인원수")]

    lines = [
        f"━━━ [{corp_name}] 임원 보수 현황 ({display_year}년 {report_type}) ━━━",
        "",
        "① 5억 이상 고액수령자",
        _rows(data["high_pay"], high_pay_cols),
        "",
        "② 개인별 보수 현황",
        _rows(data["individual"], indv_cols),
        "",
        "③ 미등기임원 보수",
        _rows(data["unregistered"], unreg_cols),
        "",
        "④ 주총 승인 보수한도",
        _rows(data["agm_limit"], agm_cols),
        "",
        "─────────────────────────────────────────────",
        "※ 임원 보수 정보는 공시 기반 불공정거래 탐지의 참고 자료이며,",
        "   경영진의 사익 추구 여부 등 이상 징후 파악에 활용됩니다.",
        "💡 임원 지분 변동: track_insider_trading(company_name=...)",
    ]
    return "\n".join(lines)


@mcp.tool()
def track_insider_trading(company_name: str, lookback_years: int = 2) -> str:
    """최대주주·5% 대량보유자의 지분 변동 시계열을 분석합니다.

    보유 비율(Δ) 변화로 매수·매도 클러스터를 탐지합니다.

    Args:
        company_name: 기업명 또는 종목코드
        lookback_years: 조회 연수 (기본값 2년, 최대 5년)

    Returns:
        보고자별 지분 변동 테이블 + 클러스터 알림
    """
    if not _DART_API_KEY:
        return "오류: DART_API_KEY 환경변수가 설정되지 않았습니다."

    _resolved = resolve_corp(company_name, _DART_API_KEY)
    corp_name, meta = _resolved if _resolved else ("", {})
    if not corp_name:
        return f"기업을 찾을 수 없습니다: {company_name}"
    corp_code = meta["corp_code"]

    lookback_years = max(1, min(5, lookback_years))
    records = fetch_insider_timeline(corp_code, _DART_API_KEY, lookback_years)

    if not records:
        return f"[{corp_name}] 최근 {lookback_years}년간 대량보유·최대주주 공시 없음."

    # ── source별 정규화 — 의미 없는 합산 행/빈 ratio/회사 자기주식 row 스킵 ──
    _SKIP_HOLDER_TOKENS = {"계", "합계", "총계", "Total", "TOTAL", "-", ""}

    def _parse_ratio(val) -> float | None:
        if val in (None, "", "-"):
            return None
        try:
            return float(str(val).replace(",", "").replace("%", "").strip())
        except (ValueError, AttributeError):
            return None

    def _normalize_date(s: str) -> str:
        """YYYY.MM.DD / YYYY-MM-DD / YYYYMMDD 등 날짜 표기를 YYYYMMDD로 정규화."""
        if not s:
            return ""
        digits = "".join(ch for ch in str(s) if ch.isdigit())
        return digits[:8] if len(digits) >= 8 else str(s)

    def _extract_row(rec: dict) -> tuple[str, float, str, str] | None:
        """레코드를 (holder, ratio_pct, date_yyyymmdd, source_label)로 정규화.

        반환 None이면 시계열에 포함하지 않는다.
        - exec_treasury: 회사 자체 자기주식 활동이라 보고자별 시계열에 부적합 → None
        - 합산 행/빈 holder/ratio 결측 → None
        """
        src = rec.get("source")
        if src == "exec_treasury":
            return None
        if src == "elestock":
            holder = (rec.get("repror") or "").strip()
            # elestock(임원·주요주주 소유보고)의 소유비율 필드는 sp_stock_lmp_rate.
            # (과거 stkqy_rt는 응답에 없어 항상 None이었음 — 구필드 폴백 유지)
            ratio = _parse_ratio(rec.get("sp_stock_lmp_rate") or rec.get("stkqy_rt"))
            date = _normalize_date(rec.get("rcept_dt"))
        elif src == "hyslr_chg":
            holder = (rec.get("mxmm_shrholdr_nm") or "").strip()
            ratio = _parse_ratio(rec.get("qota_rt"))
            date = _normalize_date(rec.get("change_on") or rec.get("rcept_dt"))
        else:  # hyslr (기본)
            holder = (rec.get("nm") or "").strip()
            ratio = _parse_ratio(rec.get("trmend_posesn_stock_qota_rt"))
            date = _normalize_date(rec.get("rcept_dt") or rec.get("bsns_year"))
        if holder in _SKIP_HOLDER_TOKENS:
            return None
        if ratio is None:
            return None
        if not date:
            return None
        source_label = _SOURCE_LABEL.get(src, "기타")
        return (holder, ratio, date, source_label)

    _SOURCE_LABEL = {
        "elestock":      "대량보유",
        "hyslr":         "최대주주",
        "hyslr_chg":     "최대주주 변동",
        "exec_treasury": "임원·주요주주 자기주식",
    }

    # ── 보고자별 시계열 구성 ──────────────────────────────────
    from collections import defaultdict
    timeline: dict[str, list[tuple[float, str, str]]] = defaultdict(list)
    treasury_count = 0
    # lookback 윈도우 cutoff (hyslr_chg는 전체 이력을 반환하므로 연도 외 데이터 필터)
    cutoff_dt = datetime.now() - timedelta(days=lookback_years * 365)
    for rec in records:
        if rec.get("source") == "exec_treasury":
            treasury_count += 1
            continue
        row = _extract_row(rec)
        if row is None:
            continue
        holder, ratio, date, src_label = row
        # 날짜 윈도우 필터 — 8자리(YYYYMMDD)는 정확 비교, 4자리(YYYY)는 연 시작으로 가정
        try:
            if len(date) >= 8:
                rec_dt = datetime.strptime(date[:8], "%Y%m%d")
            elif len(date) == 4 and date.isdigit():
                rec_dt = datetime.strptime(date + "0101", "%Y%m%d")
            else:
                rec_dt = None
        except ValueError:
            rec_dt = None
        if rec_dt is not None and rec_dt < cutoff_dt:
            continue
        timeline[holder].append((ratio, date, src_label))

    lines = [
        f"━━━ [{corp_name}] 임원·대주주 지분 변동 시계열 (최근 {lookback_years}년) ━━━",
        "",
    ]

    if not timeline:
        lines.append("(추출 가능한 보고자별 보유 비율 없음 — 합산 행·미보고 항목만 존재)")
        if treasury_count:
            lines.append(f"※ 자기주식 활동 보고 {treasury_count}건은 별도 수집됨 (track_capital_structure 참고)")

    # ── 클러스터 탐지 (30일 윈도우) ───────────────────────────
    buy_cluster: list[str] = []
    sell_cluster: list[str] = []
    # 관측 1건·0.00%로 변동이 확인되지 않는 보고자 (위 주석 참고)
    flat_only: list[str] = []
    insider_sells: list[dict] = []  # v0.8.6 INSIDER_PRE_DISCLOSURE 입력용

    import datetime as _dt

    for holder, rows in timeline.items():
        # rows: list[(ratio, date_yyyymmdd, source_label)]
        rows_sorted = sorted(rows, key=lambda r: r[1])
        # ── 인접 중복 dedup: 같은 ratio가 연속되면 첫 1건만 유지 (분기 4회 호출 노이즈 억제)
        deduped: list[tuple[float, str, str]] = []
        for ratio, date, src_lbl in rows_sorted:
            if deduped and abs(deduped[-1][0] - ratio) < 0.005:
                continue  # 0.005%p 미만 차이는 동일 데이터로 간주
            deduped.append((ratio, date, src_lbl))
        if not deduped:
            continue

        # 관측이 1건뿐이고 비율이 0.00%면 **변동이 없다** — 이 도구가 말하는
        # 것은 "지분 변동 시계열"인데 그런 줄은 변동을 담지 않는다. 그런데
        # 회사가 클수록 그 줄이 출력을 뒤덮어, 정작 Δ가 붙은 줄이 묻힌다.
        #
        # 라이브 실측(2026-08-23, 2년 조회):
        #   삼성전자         3,311줄 중 1,065줄이 이 형태 · Δ 있는 줄은 70줄
        #   두산에너빌리티      283줄 중    63줄            · Δ  1줄
        #   셀트리온           422줄 중    16줄            · Δ 71줄
        #   소형사(제이스코 등)                0줄
        #
        # 지우지 않는다 — 아래에서 인원수를 사실로 남긴다. 관측이 2건 이상
        # 이거나 비율이 0.00%를 넘으면 그대로 전부 표기한다.
        if len(deduped) == 1 and abs(deduped[0][0]) < 0.005:
            flat_only.append(holder)
            continue

        lines.append(f"▶ {holder}")
        prev_ratio: float | None = None
        prev_date: str = ""
        for ratio, date, src_lbl in deduped:
            delta = ratio - prev_ratio if prev_ratio is not None else 0.0
            delta_str = f" (Δ{delta:+.2f}%)" if prev_ratio is not None else ""
            lines.append(f"    {date}  {ratio:.2f}%{delta_str}  [{src_lbl}]")

            if prev_ratio is not None and delta < 0:
                insider_sells.append({
                    "holder": holder,
                    "rcept_dt": date,
                    "delta_pct": delta,
                })
                try:
                    d_prev = _dt.datetime.strptime(prev_date[:8], "%Y%m%d")
                    d_curr = _dt.datetime.strptime(date[:8], "%Y%m%d")
                    within_30d = abs((d_curr - d_prev).days) <= 30
                except ValueError:
                    within_30d = False
                if within_30d and delta < -0.5:
                    sell_cluster.append(holder)
            elif prev_ratio is not None and delta > 0:
                try:
                    d_prev = _dt.datetime.strptime(prev_date[:8], "%Y%m%d")
                    d_curr = _dt.datetime.strptime(date[:8], "%Y%m%d")
                    within_30d = abs((d_curr - d_prev).days) <= 30
                except ValueError:
                    within_30d = False
                if within_30d and delta > 0.5:
                    buy_cluster.append(holder)
            prev_ratio, prev_date = ratio, date
        lines.append("")

    if buy_cluster:
        lines += [
            f"⚠️  매수 클러스터 탐지: {', '.join(set(buy_cluster))}",
            "   30일 이내 0.5%p 이상 보유 증가 — 불공정거래 전조 가능성 검토 권장",
            "",
        ]
    if sell_cluster:
        lines += [
            f"⚠️  매도 클러스터 탐지: {', '.join(set(sell_cluster))}",
            "   30일 이내 0.5%p 이상 보유 감소 — 정보 우위 매도 가능성 검토 권장",
            "",
        ]

    # ── v0.8.6: INSIDER_PRE_DISCLOSURE 패턴 탐지 ──────────────
    # 매도 이벤트 ±30일 내 부정 공시(감사의견·부도·횡령·조회공시 등) 동시 발생 시 표기.
    # 점수 가산 없음(v0.8.5 원칙) — 사실 표기만.
    if insider_sells:
        try:
            disclosures = fetch_company_disclosures(
                corp_code, _DART_API_KEY, lookback_years * 365,
                max_pages=lookback_years * 10,
            )
            signal_events: list[dict] = []
            for d in disclosures or []:
                report_nm = d.get("report_nm", "")
                if is_amendment_disclosure(report_nm):
                    continue
                for sig in match_signals(report_nm):
                    signal_events.append({
                        "key": sig["key"],
                        "rcept_dt": d.get("rcept_dt", ""),
                        "report_nm": report_nm,
                    })
            pre_flags = detect_insider_pre_disclosure(insider_sells, signal_events, window_days=30)
        except Exception:
            pre_flags = []

        if pre_flags:
            lines += [
                "⚠️  매도 + 인접 부정 공시 패턴 탐지 (정보 우위 매도 가능성 검토)",
            ]
            # holder + sell_date + disclosure 단위로 정렬·중복 제거
            seen_keys: set[tuple] = set()
            for f in sorted(pre_flags, key=lambda x: (x["sell_date"], x["holder"])):
                key = (f["holder"], f["sell_date"], f["disclosure_key"], f["disclosure_date"])
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                lines.append(
                    f"   • {f['holder']}  매도일 {f['sell_date']}  Δ{f['delta_pct']:+.2f}%p  "
                    f"→ {f['days_gap']}일 후 {f['disclosure_key']} 공시 ({f['disclosure_date']})"
                )
            lines.append("")

    if flat_only:
        # 접은 것을 사실로 남긴다 — 목록에서 빠졌다는 것과 존재하지 않는다는
        # 것이 같은 화면이 되면 안 된다.
        lines += [
            "",
            f"※ 관측 1건·보유 비율 0.00%로 변동이 확인되지 않는 보고자 "
            f"{len(flat_only)}명은 위 목록에서 접었습니다 "
            f"(예: {', '.join(sorted(flat_only)[:3])}).",
        ]

    lines += [
        "─────────────────────────────────────────────",
        "※ 공시 지연으로 실시간 내부자 거래 현황과 차이가 있을 수 있습니다.",
        "   본 정보는 공시 기반 불공정거래 위험 모니터링 목적으로만 활용하십시오.",
        "💡 임원 보수 조회: get_executive_compensation(company_name=...)",
    ]
    # 다년 조회 규모 푸터 — 다른 다년 도구와 같은 관례인데 이 도구에만
    # 빠져 있었다(2026-08-23 실측: 삼성전자 2년 40,464자에 안내 없음).
    return _append_size_footer("\n".join(lines), lookback_years)


@mcp.tool()
def get_audit_opinion_history(company_name: str, lookback_years: int = 5) -> str:
    """감사의견·감사인 교체·비감사용역 이력을 조회합니다.

    DART OpenAPI 3개 엔드포인트(`accnutAdtorNmNdAdtOpinion`,
    `adtServcCnclsSttus`, `accnutAdtorNonAdtServcCnclsSttus`)를 결합해
    연도별 감사의견·감사인·보수 경고 신호를 한글 서술로 반환합니다.

    Args:
        company_name: 기업명 또는 종목코드(6자리).
        lookback_years: 1~10(밖이면 5로 강제).

    Returns:
        감사의견 표·감사인 교체 이력·비감사용역 계약 건수 텍스트.
    """
    api_key = _DART_API_KEY
    if not api_key:
        return "❌ DART_API_KEY 환경변수가 설정되지 않았습니다."

    if not isinstance(lookback_years, int) or not (1 <= lookback_years <= 10):
        lookback_years = 5

    corp_info = resolve_corp(company_name, api_key)
    if not corp_info or not corp_info[1]:
        return f"❌ 기업 '{company_name}'을(를) 찾을 수 없습니다."
    corp_name, info = corp_info

    data = fetch_audit_opinion_history(info["corp_code"], api_key, lookback_years)

    if not data["opinions"]:
        return (
            f"📋 **{corp_name}** ({info.get('stock_code','')}) — 감사의견 이력\n\n"
            f"최근 {lookback_years}년 감사의견 공시를 찾지 못했습니다. "
            "비상장·소규모 기업이거나 DART 보고서 제출 의무가 없는 경우일 수 있습니다."
        )

    lines = [
        f"📋 **{corp_name}** ({info.get('stock_code','')}) — 감사의견 이력 (최근 {lookback_years}년)",
        "",
        "**연도별 감사의견**",
    ]
    # DART 보수 필드는 기업별·연도별 단위(천원/백만원)가 일관되지 않아
    # v0.8.0에서는 절대 금액 표시를 생략했고, 2026-08-23에는 같은 이유로
    # 비중 경고도 뺐다(단위가 없어 나눌 수 없다). 계약 건수만 사실로 적는다.
    for o in data["opinions"]:
        opinion_text = (o.get("opinion") or "").strip()
        # "적정" / "적정의견" 표기 혼용을 정규화
        norm = opinion_text.replace("의견", "")
        if norm in ("한정", "부적정", "의견거절"):
            suffix = f" ⚠ {norm}의견"
        elif norm:
            suffix = f" · {norm}의견"
        else:
            suffix = ""
        lines.append(
            f"- {o['year']}: {o['auditor'] or '미확인'} "
            f"(연속 {o['tenure_years']}년차){suffix}"
        )
    lines.append("")

    if data["auditor_changes"]:
        lines.append("**감사인 교체 이력**")
        for c in data["auditor_changes"]:
            lines.append(f"- {c['from_year']}→{c['to_year']}: {c['from']} → {c['to']}")
        if len(data["auditor_changes"]) >= 2:
            lines.append("  ⚠ 3년 내 2회 이상 교체는 감사 독립성 경고 신호입니다.")
        lines.append("")

    # 비감사용역은 **건수만** 사실로 적는다. 보수 비중은 내지 않는다 —
    # DART 응답에 단위가 없고 회사·연도마다 달라 감사보수와 나눌 수 없다
    # (core의 "독립성 경고" 주석에 실측 근거). 옛 구현은 그 비율로 경고를
    # 띄웠고, 12개사 중 4개사가 단위 불일치 때문에 경고를 받았다.
    _contracts = data.get("non_audit_contracts") or {}
    if _contracts:
        lines.append("**비감사용역 계약 (참고)**")
        for y in sorted(_contracts, reverse=True):
            lines.append(f"- {y}: {_contracts[y]}건")
        lines.append(
            "  같은 감사인에게 세무·자문 등을 함께 맡긴 계약의 건수입니다. "
            "보수 비중은 DART가 단위를 함께 제공하지 않아 산출하지 않습니다 "
            "— 필요하면 사업보고서 원문에서 직접 확인하세요."
        )
        lines.append("")

    # 연속 적자 연수 — 계속기업 맥락의 사실 표기 (kreports going_concern 다년 확장)
    try:
        _streak = fetch_loss_streak(info["corp_code"], api_key, min(lookback_years, 5))
    except Exception:
        _streak = {}
    _op_n = _streak.get("op_loss_streak", 0)
    _ni_n = _streak.get("ni_loss_streak", 0)
    if _op_n >= 2 or _ni_n >= 2:
        _yrs = _streak.get("years", [])
        _latest = _yrs[0]["year"] if _yrs else "?"
        lines.append("**연속 적자 (참고)**")
        parts = []
        if _op_n >= 2:
            parts.append(f"영업손실 {_op_n}년 연속({_latest - _op_n + 1}~{_latest})")
        if _ni_n >= 2:
            parts.append(f"순손실 {_ni_n}년 연속({_latest - _ni_n + 1}~{_latest})")
        lines.append("- " + " · ".join(parts))
        lines.append(
            "  사업보고서 기준 사실 표기입니다. 코스닥 관리종목 지정 요건은 "
            "장기 영업손실 등과 연관되므로 거래소 공시·별도 기준 수치를 함께 "
            "확인하세요."
        )
        lines.append("")

    lines.append(
        "📎 참고: DART 사업보고서 기준 감사의견입니다. 반기·분기 감사인 리뷰 "
        "의견은 별도 공시로 조회하세요."
    )
    return "\n".join(lines)


_DEBT_KIND_LABEL = {
    "corporate_bond": "회사채",
    "short_term_bond": "단기사채",
    "commercial_paper": "기업어음",
    "new_capital": "신종자본증권",
    "cnd_capital": "조건부자본증권",
}


@mcp.tool()
def track_debt_balance(company_name: str, year: str = "") -> str:
    """미상환 채무증권 5종 잔액을 조회합니다.

    회사채·단기사채·기업어음·신종자본증권·조건부자본증권 잔액과
    1년 이내 만기 비중을 집계해 한글 서술로 반환합니다.

    Args:
        company_name: 기업명 또는 종목코드(6자리).
        year: 사업연도(YYYY). 비우면 직전 연도.

    Returns:
        종류별 잔액 표 + 만기 1년 이내 비중 텍스트.
    """
    api_key = _DART_API_KEY
    if not api_key:
        return "❌ DART_API_KEY 환경변수가 설정되지 않았습니다."

    _resolved = resolve_corp(company_name, api_key)
    corp_name, info = _resolved if _resolved else ("", {})
    if not info:
        return f"❌ 기업 '{company_name}'을(를) 찾을 수 없습니다."

    data = fetch_debt_balance(info["corp_code"], api_key, year)
    if data["total"] <= 0:
        return (
            f"💰 **{corp_name}** ({info.get('stock_code','')}) — 채무증권 잔액 "
            f"({data['year'] or year or '최근'})\n\n"
            "미상환 채무증권 잔액이 없거나 해당 공시를 찾지 못했습니다. "
            "비상장·소규모 기업이거나 채무증권 발행 실적이 없는 경우입니다."
        )

    total_eok = data["total"] // 100_000_000
    m1y_share = data["maturity_1y_share"]

    lines = [
        f"💰 **{corp_name}** ({info.get('stock_code','')}) — 미상환 채무증권 잔액 ({data['year']}년)",
        "",
        f"**총 잔액: {total_eok:,}억원** (만기 1년 이내 비중 {m1y_share:.1%})",
        "",
        "**종류별 내역**",
    ]
    for kind, v in data["by_kind"].items():
        label = _DEBT_KIND_LABEL.get(kind, kind)
        kind_eok = v["total"] // 100_000_000
        within_eok = v["maturity_under_1y"] // 100_000_000
        share = (v["maturity_under_1y"] / v["total"]) if v["total"] else 0.0
        lines.append(
            f"- {label}: {kind_eok:,}억 (1년 이내 {within_eok:,}억 · {share:.0%})"
        )

    if m1y_share >= 0.30:
        lines += [
            "",
            f"⚠ 전체 채무의 {m1y_share:.0%}가 1년 이내 만기 — "
            "단기 상환·차환 부담이 집중된 구간입니다.",
        ]

    lines += [
        "",
        "📎 사업보고서 기준 잔액입니다. 분기·반기 공시 이후의 신규 발행·상환은 "
        "반영되지 않을 수 있습니다.",
    ]
    return "\n".join(lines)


@mcp.tool()
def check_disclosure_anomaly(
    company_name: str, lookback_years: int = 1, lookback_days: int | None = None
) -> str:
    """공시 구조 지표 5종의 건수·비율을 집계해 사실 요약을 반환합니다.

    정정공시 비율·감사의견 이슈·공시의무 위반·자본 스트레스·조회공시 빈도
    5개 지표를 나열합니다. 위험도를 정량화하거나 등급화하지 않습니다(v0.8.5 원칙).

    Args:
        company_name: 기업명 또는 종목코드
        lookback_years: 조회 기간(년). 기본 1년, 1~5년 범위.

    Returns:
        지표별 탐지 건수·근거 공시명 텍스트 (점수·등급 없음)
    """
    if not _DART_API_KEY:
        return "오류: DART_API_KEY 환경변수가 설정되지 않았습니다."

    _resolved = resolve_corp(company_name, _DART_API_KEY)
    corp_name, meta = _resolved if _resolved else ("", {})
    if not corp_name:
        return f"기업을 찾을 수 없습니다: {company_name}"
    corp_code = meta["corp_code"]

    lookback_days, max_pages, window_phrase = _resolve_lookback(lookback_years, lookback_days)

    disclosures, fetch_status = fetch_company_disclosures_with_status(
        corp_code, _DART_API_KEY, lookback_days, max_pages=max_pages)
    if fetch_status == FETCH_ERROR:
        return _fetch_failed_notice(corp_name, window_phrase)
    total = len(disclosures)
    if total == 0:
        # v0.8.5는 이 도구에서 점수 계산을 제거했는데 문구에 "스코어"가
        # 남아 있었다(2026-08-23 발견). 이 도구는 건수·비율만 나열한다.
        return f"[{corp_name}] 최근 {window_phrase} 공시가 조회되지 않아 지표를 낼 수 없습니다."

    # ── 지표 집계 ──────────────────────────────────────────────
    amendment_count = sum(1 for d in disclosures if is_amendment_disclosure(d.get("report_nm", "")))

    _CAPITAL_STRESS = {"REVERSE_SPLIT", "CAPITAL_RED", "RIGHTS_UNDER", "3PCA"}

    audit_hits: list[str] = []
    viol_hits: list[str] = []
    capital_hits: list[str] = []
    inquiry_hits: list[str] = []

    for d in disclosures:
        nm = d.get("report_nm", "")
        if is_amendment_disclosure(nm):
            continue
        sigs = match_signals(nm)
        keys = {s["key"] for s in sigs}
        if "AUDIT" in keys:
            audit_hits.append(nm)
        if "DISCLOSURE_VIOL" in keys:
            viol_hits.append(nm)
        if keys & _CAPITAL_STRESS:
            capital_hits.append(nm)
        if "INQUIRY" in keys:
            inquiry_hits.append(nm)

    # ── 지표 집계 (건수·비율만) ─────────────────────────────────
    amend_ratio = amendment_count / total
    # v0.8.5: 내부 스코어 계산을 제거. 출력에는 건수·비율·사실만 노출한다.
    # 감사의견 구조화 엔드포인트는 감사인 교체 이력에만 사용한다
    # (비감사용역 비중 경고는 단위 문제로 2026-08-23에 제거).
    _audit_struct = fetch_audit_opinion_history(corp_code, _DART_API_KEY, 5)
    _auditor_change_count = len(_audit_struct.get("auditor_changes", []))
    _indep_warnings = _audit_struct.get("independence_warnings", [])

    def _top3(items: list[str]) -> str:
        shown = items[:3]
        rest = len(items) - len(shown)
        out = "\n".join(f"    • {nm}" for nm in shown)
        if rest:
            out += f"\n    … 외 {rest}건"
        return out

    # 상단 한 줄 요약 (점수/등급 제거 — 관찰된 사실만)
    summary = (
        f"📋 최근 {window_phrase} 동안 **{corp_name}**의 공시 "
        f"{total}건을 5개 구조 지표로 분류했습니다. 이 도구는 공시 행태의 "
        "사실 요약만 제공하며, 기업의 위험도를 등급화하지 않습니다."
    )

    lines = [
        f"━━━ [{corp_name}] 공시 구조 관찰 요약 ━━━",
        f"조회기간: 최근 {window_phrase} / 총 공시 {total}건 (정정공시 {amendment_count}건)",
        "",
        summary,
        "",
        "── 지표별 내역 ──────────────────────────────",
        "",
        f"**① 정정공시 비율** ({amendment_count}/{total}건, {amend_ratio:.0%})",
        (
            "이미 낸 공시를 고쳐서 다시 내는 비율입니다. 정상 기업은 보통 "
            "5% 안쪽이고, 20%를 넘으면 최초 공시 품질이 떨어지거나 "
            "정보를 조금씩 흘려보내는 의도가 있을 수 있습니다."
        ),
        "",
        f"**② 감사의견 이슈** ({len(audit_hits)}건)",
        (
            "회계감사 과정에서 한정·부적정·거절 의견이 나오거나 감사인이 "
            "중도 교체된 건수입니다. 감사의견 거절은 코스닥에서 상장폐지로 "
            "직결되는 가장 무거운 신호 중 하나입니다."
        ),
    ]
    if audit_hits:
        lines.append(_top3(audit_hits))
    if _auditor_change_count >= 2:
        lines.append(
            f"  ⚠ 최근 5년간 감사인 교체 {_auditor_change_count}회 "
            "— 감사 독립성 훼손 가능성이 제기되는 맥락입니다."
        )
    # 비감사용역 비중 경고는 2026-08-23에 뺐다 — 단위가 없는 금액으로
    # 계산한 비율이라 12개사 중 4개사에 잘못 떴다(core 주석 참고).
    if _indep_warnings:
        lines.append(
            f"  ⚠ 비감사용역 비중 초과 연도: {', '.join(_indep_warnings)}."
        )
    lines += [
        "",
        f"**③ 공시의무 위반** ({len(viol_hits)}건)",
        (
            "거래소가 불성실공시법인으로 지정하거나 공시 철회·정정을 "
            "반복한 건수입니다. 한 해 한두 건이면 실무 실수일 수 있지만, "
            "반복되면 기본 거버넌스가 흔들리는 신호입니다."
        ),
    ]
    if viol_hits:
        lines.append(_top3(viol_hits))
    lines += [
        "",
        f"**④ 자본 스트레스** ({len(capital_hits)}건)",
        (
            "액면병합·자본감소·주주배정 실권·제3자배정 증자처럼 "
            "'자본을 주무르는' 공시의 누적 건수입니다. 상장폐지 회피나 "
            "특정 세력 지분 몰아주기 맥락에서 집중 관찰됩니다."
        ),
    ]
    if capital_hits:
        lines.append(_top3(capital_hits))
    lines += [
        "",
        f"**⑤ 조회공시 빈도** ({len(inquiry_hits)}건)",
        (
            "거래소가 주가·거래량 급변 원인을 묻기 위해 회사에 해명을 "
            "요구한 건수입니다. 빈번하면 회사 주변에서 비공식 정보 "
            "유통이나 세력 개입이 있을 가능성이 커집니다."
        ),
    ]
    if inquiry_hits:
        lines.append(_top3(inquiry_hits))
    lines += [
        "",
        "─────────────────────────────────────────────",
        "※ 본 결과는 공시 기반 불공정거래 위험 모니터링 목적의 참고 자료이며,",
        "   법적 판단이나 투자 결정의 근거로 사용할 수 없습니다.",
        "💡 세부 분석: analyze_company_risk(company_name=...)",
    ]
    return _append_size_footer("\n".join(lines), lookback_years)


@mcp.tool()
def track_fund_usage(company_name: str, lookback_years: int = 3) -> str:
    """공모/사모 자금 사용내역(계획 vs 실제)을 조회해 조달자금 유용·
    목적외 사용 신호를 탐지한다. zombie_ma·fake_new_biz 패턴의 핵심 증거.

    Args:
        company_name: 기업명 또는 6자리 종목코드
        lookback_years: 조회 연도 수 (1~5, 기본 3)
    """
    if not _DART_API_KEY:
        return "❌ DART_API_KEY 환경변수가 설정되지 않았습니다."
    if not isinstance(lookback_years, int) or not (1 <= lookback_years <= 5):
        return "❌ lookback_years는 1~5 사이 정수여야 합니다."

    _resolved = resolve_corp(company_name, _DART_API_KEY)
    corp_name, info = _resolved if _resolved else ("", {})
    if not info:
        return f"❌ '{company_name}'에 해당하는 기업을 찾을 수 없습니다."

    records = fetch_fund_usage(info["corp_code"], _DART_API_KEY, lookback_years)
    if not records:
        return (
            f"💰 **{corp_name}** 자금사용내역\n\n"
            f"최근 {lookback_years}년간 등록된 공모/사모 자금사용내역이 없습니다.\n"
            f"(정기보고서(사업/반기/분기) 제출 시점에만 갱신됩니다.)"
        )

    anomaly_records = [r for r in records if r["flags"]]

    # 상단 요약
    if anomaly_records:
        summary = (
            f"🎯 **{corp_name}**이(가) 유상증자·CB 발행으로 모은 자금 중 "
            f"{len(anomaly_records)}건에서 '계획과 실제 집행의 불일치' 또는 "
            "'실제 사용 내역 미보고' 신호가 감지됐습니다. 정상 기업에서는 "
            "계획과 실제가 대체로 맞아떨어집니다. 아래 개별 건에서 무엇이 "
            "어긋났는지 확인하세요."
        )
    else:
        summary = (
            f"🎯 최근 {lookback_years}년 동안 **{corp_name}**의 공모·사모 "
            "자금 사용 내역은 계획과 실제가 대체로 맞아떨어집니다. "
            "조달 자금 유용으로 해석할 만한 신호는 없습니다."
        )

    lines = [
        f"💰 **{corp_name}** 조달자금 사용내역 (lookback={lookback_years}년)",
        f"총 {len(records)}건 조회",
        "",
        summary,
        "",
    ]

    for rec in records:
        lines.append(
            f"{_format_fund_year_prefix(rec)} "
            f"납입 {rec['pay_amount']:,}원"
        )
        lines.append(
            f"  계획: {rec['plan_useprps'][:60] or '(공란)'} "
            f"({rec['plan_amount']:,}원)"
        )
        lines.append(
            f"  실제: {rec['real_dtls_cn'][:60] or '(공란)'} "
            f"({rec['real_dtls_amount']:,}원)"
        )
        if rec["dffrnc_resn"]:
            lines.append(f"  차이사유: {rec['dffrnc_resn'][:100]}")
        # 플래그 → 한국어 서술
        for f in rec["flags"]:
            title, body = flag_to_prose(f)
            if title and body:
                lines.append(f"  ⚠ **{title}**")
                lines.append(f"    {body}")
        lines.append("")

    if anomaly_records:
        lines.append(f"🚨 **이상 신호가 감지된 건: {len(anomaly_records)}건**")
        lines.append("")
        # load_catalog_excerpt는 taxonomy ID(예: "5.1")를 받는다 — 패턴 키
        # 문자열("zombie_ma" 등)을 넘기면 TAXONOMY에 없는 키라 조용히 전부
        # 스킵되어 빈 문자열이 반환된다(과거 버그, SE-13 Task 1). 여기서는
        # zombie_ma·fake_new_biz 패턴의 signal_sequence(실제 taxonomy ID
        # 목록)를 CROSS_SIGNAL_PATTERNS에서 가져와 하드코딩 중복 없이 사용한다.
        _fund_usage_tax_ids = list(dict.fromkeys(
            CROSS_SIGNAL_PATTERNS["zombie_ma"]["signal_sequence"]
            + CROSS_SIGNAL_PATTERNS["fake_new_biz"]["signal_sequence"]
        ))
        excerpt = load_catalog_excerpt(_fund_usage_tax_ids)
        if excerpt:
            lines.append(excerpt)
    else:
        lines.append("✅ 계획과 실제 사용이 맞아떨어져, 별도 경고 신호는 없습니다.")

    # v0.9.0: 배당 이력 + 적자 시점 배당 유출(DIVIDEND_DRAIN) 표기 ----------
    dividend_records = fetch_dividend_history(
        info["corp_code"], _DART_API_KEY, lookback_years
    )
    if dividend_records:
        lines += ["", "**배당 이력 (alotMatter)**"]
        # 분기 4회 호출 노이즈 제거: (bsns_year, se, stock_knd) 기준 dedup
        seen_div: set[tuple] = set()
        cash_dividends: list[dict] = []
        for r in dividend_records:
            key = (r.get("bsns_year"), r.get("se"), r.get("stock_knd"))
            if key in seen_div:
                continue
            seen_div.add(key)
            cash_dividends.append(r)
        for r in sorted(cash_dividends, key=lambda x: (x.get("bsns_year", ""), x.get("se", "")))[:20]:
            yr = r.get("bsns_year", "-")
            se = r.get("se", "-")
            kn = r.get("stock_knd", "-")
            ts = r.get("thstrm", "-") or "-"
            fr = r.get("frmtrm", "-") or "-"
            lines.append(
                f"- {yr}  {se} ({kn})  당기 {ts} / 전기 {fr}"
            )

        # DIVIDEND_DRAIN 검출 — alotMatter 자체에 같은 (bsns_year,
        # reprt_code) 그룹으로 bundling된 (연결)/(별도) 당기순이익을
        # 그대로 사용한다(별도 재무제표 조회 없음, v1.6.x 재설계).
        drain_flags = detect_dividend_drain(dividend_records)
        if drain_flags:
            lines += [
                "",
                "⚠ **적자 시점 배당 유출 패턴 탐지**",
            ]
            for fl in drain_flags[:5]:
                # CFS(연결)는 alotMatter 원문 자체가 지배기업소유주지분순이익
                # (비지배지분 제외)만 담고 있어(두산 2023 실측 확정 —
                # core/dart_client.py의 _DIVIDEND_DRAIN_NI_SE 주석 참고),
                # "당기순이익"이라고만 쓰면 회사 전체 순이익으로 오독될 수
                # 있다 — 라벨에 지배지분 기준임을 병기한다. OFS(별도)는
                # 개념상 비지배지분이 없어 해당 사항 없음.
                label = "연결·지배지분 기준" if fl["fs_div"] == "CFS" else "별도"
                lines.append(
                    f"   • {fl['bsns_year']} 사업연도 ({label}) 당기순이익 "
                    f"{fl['net_income']:,.0f}백만원 + 현금배당금총액 "
                    f"{fl['dividend']:,.0f}백만원  → 자금 유출 경로 검토 권장"
                )

    return "\n".join(lines)


@mcp.tool()
def get_major_decision(rcept_no: str, decision_type: str = "", corp_code: str = "") -> str:
    """DS005 주요사항보고서 12종 결정 공시(양수도·합병·분할·교환)를
    구조화 필드로 조회한다. related_party_hollowing·delisting_evasion
    패턴의 경로 추적에 사용.

    Args:
        rcept_no: 14자리 접수번호
        decision_type: 결정 유형 (미지정 시 지원 타입 안내).
            business_acq | business_div | tangible_acq | tangible_div |
            stock_acq | stock_div | bond_acq | bond_div |
            merger | demerger | demerger_merger | stock_exchange
        corp_code: DART 기업 코드 8자리. 권장 — DART API가
            rcept_no 단독 호출을 거부하는 엔드포인트가 있어 정확한
            조회를 위해 corp_code 전달을 권장한다. 미지정 시 rcept_no
            단독 폴백을 시도하나 일부 결정 유형은 빈 결과가 반환될 수 있다.
    """
    if not _DART_API_KEY:
        return "❌ DART_API_KEY 환경변수가 설정되지 않았습니다."

    result = fetch_major_decision(rcept_no, _DART_API_KEY, decision_type, corp_code)
    if "error" in result:
        return f"❌ {result['error']}"

    # 결정 유형 한국어 라벨
    decision_label_map = {
        "business_acq": "영업 양수",
        "business_div": "영업 양도",
        "tangible_acq": "유형자산 양수",
        "tangible_div": "유형자산 양도",
        "stock_acq": "타법인 주식 양수",
        "stock_div": "타법인 주식 양도",
        "bond_acq": "채권 인수",
        "bond_div": "채권 발행",
        "merger": "합병",
        "demerger": "분할",
        "demerger_merger": "분할합병",
        "stock_exchange": "주식교환·이전",
    }
    decision_label = decision_label_map.get(
        result["decision_type"], result["decision_type"]
    )

    # 상단 요약
    if result["flags"]:
        summary = (
            f"🎯 이 공시는 **{decision_label}** 결정이며, "
            f"{len(result['flags'])}개 이상 신호가 겹쳤습니다. 아래 '주목할 "
            "이유' 블록에서 무엇이 왜 문제인지 쉽게 설명합니다."
        )
    else:
        summary = (
            f"🎯 이 공시는 **{decision_label}** 결정이며, 특수관계·과대거래·"
            "외부평가 기준으로는 특이 신호가 감지되지 않았습니다."
        )

    lines = [
        f"📑 **주요사항 결정 공시** (rcept_no={rcept_no})",
        "",
        summary,
        "",
        f"- 결정 유형: {decision_label}",
        f"- 상대방: {result['counterparty'] or '(미기재)'}",
        f"- 금액: {result['amount']:,}원",
        f"- 자산 총액 대비: {result['asset_ratio']:.2f}%",
        f"- 특수관계인 여부: {'예' if result['related_party'] else '아니오'}",
        f"- 외부평가 실시: {'예' if result['external_eval'] else '아니오'}",
        f"- 결의일: {result['bddd'] or '(미기재)'}",
    ]
    if result["flags"]:
        lines.append("")
        lines.append("### 주목할 이유")
        lines.append("")
        for f in result["flags"]:
            title, body = flag_to_prose(f)
            if title and body:
                lines.append(f"**{title}**")
                lines.append(body)
                lines.append("")
    lines.append(f"원문 전체 보기: `view_disclosure('{rcept_no}')`")
    return "\n".join(lines)


# ── 도구 20: 재무 이상 스캔 ────────────────────────────────────────────────


# 지표명 → 이상 징후일 때 사용할 플래그 키
_METRIC_TO_FLAG: dict[str, str] = {
    "매출채권/매출": "AR_SURGE",
    "재고자산/매출": "INVENTORY_SURGE",
    "순이익 vs 영업현금흐름": "CASH_GAP",
    "자본총계/자본금": "CAPITAL_IMPAIRMENT",
    "연결/별도 당기순이익": "CFS_OFS_REVERSAL",
    "대여금·선급금(재무상태표)": "LOAN_ADVANCE_SURGE",
}


@mcp.tool()
def scan_financial_anomaly(
    company_name: str,
    year: str = "",
    report_type: str = "annual",
) -> str:
    """
    재무제표 4개 지표(매출채권·재고자산·현금흐름·자본잠식)를 전년 대비로 비교해
    분식·부실 초기 조짐을 탐지합니다. 발생액 비율(사실 표기)과 연결/별도
    당기순이익 비교(별도>연결 역전 시 종속회사 합산 손실 플래그)를 함께 표기합니다.

    Args:
        company_name: 기업명 또는 종목코드(6자리).
        year: 사업연도(예: "2024"). 빈 값이면 직전 연도.
        report_type: "annual"(사업보고서) | "half"(반기) | "q1" | "q3".

    Returns:
        지표별 당기/전기/Δ 표 + 이상 징후별 쉬운 설명 텍스트.
    """
    api_key = os.environ.get("DART_API_KEY", "")
    if not api_key:
        return "❌ DART_API_KEY 환경변수가 설정되지 않았습니다."

    corp_info = resolve_corp(company_name, api_key)
    if not corp_info or not corp_info[1]:
        return f"❌ 기업 '{company_name}'을(를) 찾을 수 없습니다."
    corp_name, info = corp_info
    corp_code = info["corp_code"]

    if not year:
        from datetime import datetime
        year = str(datetime.now().year - 1)

    # 전체 계정 과목 필요 (매출채권·재고자산 포함) → fnlttSinglAcntAll 사용. CFS 우선, 없으면 OFS.
    fs_list = fetch_financial_statements_all(corp_code, api_key, year, report_type, "CFS")
    _fs_div_used = "CFS"
    if not fs_list:
        fs_list = fetch_financial_statements_all(corp_code, api_key, year, report_type, "OFS")
        _fs_div_used = "OFS"
    if not fs_list:
        return (f"📊 **{corp_name}** ({info.get('stock_code','')}) — {year} {report_type}\n\n"
                "재무제표 조회 불가(데이터 없음 또는 권한 부족).")

    current, prior = _fs_response_to_periods({"list": fs_list})

    # 연결/별도 당기순이익 비교용 — fnlttSinglAcnt는 CFS/OFS 행을 한 응답에 함께 준다.
    _cfs_ni, _ofs_ni = None, None
    try:
        _acnt_rows = fetch_financial_statements(corp_code, api_key, year, report_type)
        _cfs_ni, _ofs_ni = extract_cfs_ofs_ni(_acnt_rows)
    except Exception:
        pass

    # v0.8.8: 단일회사 주요 재무지표 — 당기·전기 동시 조회 (전년 대비 추세 표기)
    _reprt_map = {"annual": "11011", "half": "11012", "q1": "11013", "q3": "11014"}
    _reprt = _reprt_map.get(report_type, "11011")
    _current_indx = fetch_company_indicators(corp_code, api_key, year, _reprt)
    _prior_year = str(int(year) - 1) if year.isdigit() else ""
    _prior_indx = (
        fetch_company_indicators(corp_code, api_key, _prior_year, _reprt)
        if _prior_year else {}
    )

    # 대여금·선급금 (금감원 2019-12 무자본 M&A 합동점검 유의사항 ③) — fs_list는
    # 이미 당기/전기 금액을 함께 담고 있어 추가 API 호출 없이 추출 가능.
    _loan_advance = extract_loan_advance(fs_list)

    flags, metrics = detect_financial_anomaly(
        current, prior,
        current_indx=_current_indx, prior_indx=_prior_indx,
        cfs_ni=_cfs_ni, ofs_ni=_ofs_ni,
        loan_advance=_loan_advance,
    )

    # 영업이익 vs 순이익 부호 괴리 (kreports op_net_divergence 이식·확장)
    _pd_flags, _pd_metrics = detect_profit_direction_divergence(current)
    flags.extend(_pd_flags)
    metrics.extend(_pd_metrics)

    # 전기 수치 재작성 감지 — 직전 연도 fnlttSinglAcnt 1회 추가 호출 후 대조
    _restate: list = []
    try:
        if year.isdigit():
            _prev_rows = fetch_financial_statements(
                corp_code, api_key, str(int(year) - 1), report_type)
            _restate = detect_restatement(_acnt_rows, _prev_rows)
    except Exception:
        _restate = []
    if _restate:
        flags.append("RESTATEMENT")
        metrics.append({
            "name": "전기 수치 재작성",
            "details": _restate,
            "flagged": True,
            "flag_key": "RESTATEMENT",
        })

    # 상단 한 줄 요약
    flagged_metrics = [m for m in metrics if m.get("flagged")]
    if flagged_metrics:
        summary = (
            f"🎯 **{corp_name}**의 {year} {report_type} 재무제표에서 이상 징후 "
            f"{len(flagged_metrics)}개를 찾았습니다. 아래 표의 각 지표가 "
            "전년과 얼마나 달라졌는지 먼저 확인하고, 그 아래 '이 지표가 "
            "말하는 것'에서 왜 주목할 만한지 쉽게 설명합니다."
        )
    else:
        summary = (
            f"🎯 **{corp_name}**의 {year} {report_type} 재무제표에서는 "
            "분식·부실 초기 조짐으로 해석할 만한 이상이 감지되지 않았습니다."
        )

    lines = [
        f"📊 **{corp_name}** ({info.get('stock_code','')}) — 재무 이상 스캔 ({year}, {report_type})",
        "",
        summary,
        "",
        "| 지표 | 당기 | 전기 | 변화 |",
        "|---|---|---|---|",
    ]
    # v0.8.8: indx 항목은 별도 블록으로 분리 — 4지표 본 표는 종전 그대로 유지
    _fs_metrics = [m for m in metrics if m.get("source") != "indx"]
    _indx_metrics = [m for m in metrics if m.get("source") == "indx"]
    for m in _fs_metrics:
        name = m["name"]
        if name == "순이익 vs 영업현금흐름":
            cur = (
                f"순이익 {m['current_ni']:,} / "
                f"영업현금흐름 {m['current_ocf']:,}"
            )
            pri = "-"
            delta = "-"
        elif name == "연결/별도 당기순이익":
            cur = (
                f"연결 {m['current_cfs']:,} / "
                f"별도 {m['current_ofs']:,}"
            )
            pri = "-"
            gp = m.get("gap_pct")
            delta = f"연결-별도 {gp:+.1f}%" if gp is not None else "-"
        elif name == "영업이익 vs 순이익":
            cur = (
                f"영업이익 {m['current_op']:,} / "
                f"순이익 {m['current_ni']:,}"
            )
            pri = "-"
            delta = "-"
        elif name == "전기 수치 재작성":
            _det = m.get("details") or []
            _top = _det[0] if _det else {}
            _tp = _top.get("diff_pct")
            cur = f"{len(_det)}개 계정 불일치"
            pri = "-"
            delta = f"최대 {_tp:+.1f}%" if _tp is not None else "-"
        elif name == "대여금·선급금(재무상태표)":
            cur = f"{m['current']:,}원"
            pri = f"{m['prior']:,}원"
            delta = f"{m['current'] / m['prior']:.1f}배" if m["prior"] else "신규"
        elif "current" in m and "prior" in m:
            cur = f"{m['current']:.1f}{m.get('unit','')}"
            pri = f"{m['prior']:.1f}{m.get('unit','')}"
            delta = f"{m['delta']:+.1f}%p"
        else:
            cur = f"{m.get('current', 0):.1f}{m.get('unit','')}"
            pri = "-"
            delta = "-"
        lines.append(f"| {name} | {cur} | {pri} | {delta} |")

    # v0.8.8: 전년 대비 추세 (DART 재무지표 기준) — 사실 표기만
    if _indx_metrics:
        lines.append("")
        lines.append("**전년 대비 추세 (DART 재무지표 기준)**")
        for m in _indx_metrics:
            cv = m["current"]
            pv = m["prior"]
            unit = m.get("unit", "%")
            dp = m.get("delta_pct")
            if dp is None:
                trend = "전년 0 또는 비교 불가"
            else:
                # 음수=둔화/감소, 양수=상승
                trend = f"전년 대비 {dp:+.1f}%"
            lines.append(
                f"- {m['name']}  {pv:.2f}{unit} → {cv:.2f}{unit}  ({trend})"
            )

    # Beneish 연구 변수 — 지수 사실 표기만, 합산 점수·판정 없음(v0.8.5 원칙).
    # 감가상각비는 사업보고서 XBRL 기재값에서 좁게 추출해 DEPI·TATA 복원 (annual만).
    _dep = {}
    if report_type == "annual":
        try:
            _dep = extract_xbrl_depreciation(corp_code, api_key, _fs_div_used, year=year)
        except Exception:
            _dep = {}
    _beneish = compute_beneish_variables(
        current, prior,
        dep_current=_dep.get("current"), dep_prior=_dep.get("prior"),
    )
    if _beneish:
        lines.append("")
        lines.append("**이익조작 연구 변수 (Beneish 개별 변수 — 사실 표기, 합산·판정 없음)**")
        for b in _beneish:
            lines.append(f"- {b['key']}({b['name']}): {b['value']:.2f} — {b['meaning']}")
        lines.append(
            "  ※ 지수는 전년=1.00 기준 상대값입니다(단, TATA는 당기 비율). "
            "개별 변수만으로 이익조작을 판정할 수 없으며, 학계 모형(M-Score) "
            "합산은 본 도구의 점수 금지 원칙에 따라 제공하지 않습니다."
        )
        if _dep:
            lines.append(
                "  ※ DEPI·TATA의 감가상각비는 최근 사업보고서 XBRL 기재값입니다."
            )

    # 연구개발비 비중 — 사업보고서 기재값 사실 표기 (kreports 이식, annual만)
    if report_type == "annual":
        try:
            _rd = extract_rd_ratio_from_report(corp_code, api_key)
        except Exception:
            _rd = {}
        _rd_vals = _rd.get("values") or []
        if _rd_vals:
            trail = " → ".join(f"{v:.2f}%" for v in _rd_vals)
            lines.append("")
            lines.append("**연구개발비 비중 (사업보고서 기재)**")
            lines.append(f"- 연구개발비/매출액: {trail} (당기부터 과거 순, {_rd.get('report_nm', '사업보고서')})")
            if len(_rd_vals) >= 2:
                if _rd_vals[0] > _rd_vals[-1]:
                    lines.append("- 당기 비중은 과거 대비 높아진 수준입니다.")
                elif _rd_vals[0] < _rd_vals[-1]:
                    lines.append(
                        "- 당기 비중은 과거 대비 낮아진 수준입니다. 신사업·신기술 "
                        "발표가 잦은데 연구개발 비중이 낮아지는 경우 발표의 실체를 "
                        "원문으로 확인하세요."
                    )
                else:
                    lines.append("- 당기 비중은 과거와 유사한 수준입니다.")
            lines.append("  ※ 산정 기준(정부보조금 차감 여부 등)이 회사마다 달라 원문 표 확인이 필요합니다.")

    # 대여금·선급금 (계정 노출 시) — 금감원 2019-12 무자본 M&A 합동점검
    # 유의사항 ③(자금조달 이후 관계회사 대여·선급금 확인) 도구화. 계정 자체가
    # 재무제표에 노출되지 않는 회사가 흔해(실측: 아틀라스링크 2025 CFS 159행
    # 중 0건) 노출된 회사에서만 표기한다 — 미발화가 정상.
    _la_bs = _loan_advance.get("bs_items") or []
    _la_cf = _loan_advance.get("cf_items") or []
    if _la_bs or _la_cf:
        lines.append("")
        lines.append("### 대여금·선급금 (계정 노출 시)")
        if _la_bs:
            lines.append("**재무상태표(잔액)**")
            for _it in _la_bs:
                _cur_s = f"{_it['current']:,}원" if _it["current"] is not None else "-"
                _pri_s = f"{_it['prior']:,}원" if _it["prior"] is not None else "-"
                lines.append(f"- {_it['account_nm']}: 당기 {_cur_s} / 전기 {_pri_s}")
        if _la_cf:
            lines.append("**현금흐름표(증감)**")
            for _it in _la_cf:
                _cur_s = f"{_it['current']:,}원" if _it["current"] is not None else "-"
                _pri_s = f"{_it['prior']:,}원" if _it["prior"] is not None else "-"
                lines.append(f"- {_it['account_nm']}: 당기 {_cur_s} / 전기 {_pri_s}")
        lines.append(
            "  ※ 금감원 무자본 M&A 합동점검(2019-12)이 관계회사 대여·선급금을 "
            "유용 경로로 지목했습니다 — 상세는 재무제표 주석을 확인하세요."
        )

    lines.append("")
    if flagged_metrics:
        lines.append("### 이 지표가 말하는 것")
        lines.append("")
        for m in flagged_metrics:
            flag_key = m.get("flag_key") or _METRIC_TO_FLAG.get(m["name"], "")
            if not flag_key:
                continue
            title, body = flag_to_prose(flag_key, m)
            lines.append(f"**{title}**")
            lines.append(body)
            lines.append("")
    else:
        lines.append(
            "네 지표 모두 정상 범위입니다. 단, 재무제표는 감사 전 수치가 포함될 "
            "수 있어 스크리닝 참고용으로만 활용하세요."
        )
        lines.append("")

    # 업종별 유의 회계정책 — 업종 일반의 정적 참고 자료 (기업 판정·점수 아님, v0.8.5 원칙)
    try:
        _comp = fetch_company_info(corp_code, api_key)
        _induty = (_comp or {}).get("induty_code", "")
    except Exception:
        _induty = ""
    if _induty:
        _items = get_critical_items(_induty)
        if _items:
            lines.append("### 업종별 유의 회계정책 (참고)")
            lines.append(f"업종: {get_induty_name(_induty)} (KSIC {_induty})")
            for _key, _title, _priority, _desc in _items:
                _tag = "핵심" if _priority == "high" else "참고"
                lines.append(f"- [{_tag}] {_title} — {_desc}")
            lines.append(
                "※ 위 항목은 이 업종 일반에서 회계처리 판단의 영향이 큰 영역을 "
                "안내하는 정적 자료로, 이 기업에 대한 판정이 아닙니다."
            )
            lines.append("")

    lines.append(
        "📎 참고: DART 공시 기준 수치입니다. 감사 전 수치가 포함될 수 있고, "
        "회계 전문가 판단을 대체하지 않습니다. 이상 징후가 나왔더라도 "
        "실제 분식 여부는 감사보고서·공시 원문을 함께 봐야 합니다."
    )
    return "\n".join(lines)


@mcp.tool()
def track_capital_structure(
    company_name: str,
    lookback_years: int = 3,
) -> str:
    """
    자본 이벤트(증자·감자·자사주·CB/BW/EB/RCPS 등)를 시간순으로 집계해
    '자본 주무르기' 리듬을 탐지합니다.

    Args:
        company_name: 기업명 또는 종목코드(6자리).
        lookback_years: 1~5(밖이면 3으로 강제).

    Returns:
        이벤트 총수·12개월 집중도·연도별 집계·시계열·플래그 텍스트.
    """
    api_key = os.environ.get("DART_API_KEY", "")
    if not api_key:
        return "❌ DART_API_KEY 환경변수가 설정되지 않았습니다."

    if not isinstance(lookback_years, int) or not (1 <= lookback_years <= 5):
        lookback_years = 3

    corp_info = resolve_corp(company_name, api_key)
    if not corp_info or not corp_info[1]:
        return f"❌ 기업 '{company_name}'을(를) 찾을 수 없습니다."
    corp_name, info = corp_info
    corp_code = info["corp_code"]

    # 다년 조회 — 기본 상한(1,000건)이면 공시가 많은 회사에서 절단된다
    # (2026-08-23 실측). 창에 비례해 올린다.
    # 조회 실패를 "자료 없음"과 구분한다 — 아래 요약이 이벤트 0건일 때
    # "자본 주무르기로 볼 만한 리듬은 없습니다"라고 **단정**하므로, 못 받은
    # 것을 없는 것으로 내면 화면이 거짓을 말한다(2026-08-23 후속 감사).
    disclosures, fetch_status = fetch_company_disclosures_with_status(
        corp_code, api_key, lookback_years * 365,
        max_pages=lookback_years * 10,
    )
    if fetch_status == FETCH_ERROR:
        return _fetch_failed_notice(corp_name, f"최근 {lookback_years}년")

    # match_signals로 신호 탐지 + 자본 이벤트만 필터는 detect_capital_churn이 처리
    signal_events: list[dict] = []
    for d in disclosures:
        matches = match_signals(d.get("report_nm", ""))
        for m in matches:
            signal_events.append({
                "key": m["key"],
                "label": m["label"],
                "score": m.get("score", 0),
                "report_nm": d.get("report_nm", ""),
                "rcept_dt": d.get("rcept_dt", ""),
                "rcept_no": d.get("rcept_no", ""),
                "is_amendment": is_amendment_disclosure(d.get("report_nm", "")),
            })

    # v0.8.7: 자사주 결정 4종 구조화 데이터 보강 (TREASURY 직접/처분 + TREASURY_TRUST 체결/해지)
    # 키워드 매칭으로 이미 들어온 동일 rcept_no는 중복 방지.
    treasury_decisions = fetch_treasury_decisions(corp_code, api_key, lookback_years)
    _existing_rcept = {e.get("rcept_no") for e in signal_events if e.get("rcept_no")}
    for t in treasury_decisions:
        if t.get("rcept_no") in _existing_rcept:
            continue
        signal_events.append({
            "key": t["key"],
            "label": t["report_nm"],
            "score": 0,
            "report_nm": t["report_nm"],
            "rcept_dt": t["rcept_dt"],
            "rcept_no": t["rcept_no"],
            "is_amendment": False,
            "decision_type": t["decision_type"],
        })

    result = detect_capital_churn(signal_events, lookback_years)
    churn_flagged = "CAPITAL_CHURN" in result["flags"]

    # 상단 요약
    if churn_flagged:
        title, body = flag_to_prose("CAPITAL_CHURN", result)
        summary = f"🎯 **{title}**\n\n{body}"
    elif result["total_events"] == 0:
        summary = (
            f"🎯 최근 {lookback_years}년 동안 **{corp_name}**에서는 증자·감자·"
            "자사주·메자닌 같은 자본 구조 변경 공시가 감지되지 않았습니다. "
            "자본 주무르기로 볼 만한 리듬은 없습니다."
        )
    else:
        summary = (
            f"🎯 최근 {lookback_years}년 동안 자본 이벤트 {result['total_events']}건이 "
            f"관찰됐지만 12개월 최대 집중도가 {result['max_12m_count']}건으로 "
            "'3건 이상 몰림' 기준(자본 이벤트 집중 판정)에는 미치지 못했습니다. "
            "개별 이벤트의 성격은 아래 시계열에서 확인하세요."
        )

    lines = [
        f"📊 **{corp_name}** ({info.get('stock_code','')}) — 자본구조 추적 (최근 {lookback_years}년)",
        "",
        summary,
        "",
        f"자본 이벤트 총 **{result['total_events']}건** · "
        f"12개월 최대 집중도: **{result['max_12m_count']}건**",
        "",
    ]
    if result["by_year"]:
        lines.append("**연도별 집계**")
        for y in sorted(result["by_year"].keys()):
            lines.append(f"- {y}: {result['by_year'][y]}건")
        lines.append("")

    # v0.8.0: 채무증권 잔액 추이 + CB_ROLLOVER 판정
    from datetime import datetime as _dt
    _current_year = _dt.now().year
    _balance_years = [str(_current_year - 1 - i) for i in range(max(lookback_years, 3))]
    _balance_history: list[tuple[int, int]] = []
    _balance_by_year: dict[int, dict] = {}
    for _y in _balance_years:
        _bal = fetch_debt_balance(corp_code, api_key, _y)
        if _bal["total"] > 0 and _bal["year"] is not None:
            _balance_history.append((_bal["year"], _bal["total"]))
            _balance_by_year[_bal["year"]] = _bal

    if _balance_history:
        _balance_history.sort(key=lambda x: x[0])
        lines.append("**채무증권 잔액 추이**")
        for _y, _tot in _balance_history:
            _eok = _tot // 100_000_000
            _m1y = _balance_by_year[_y]["maturity_1y_share"]
            lines.append(f"- {_y}: 총 {_eok:,}억원 (1년 이내 {_m1y:.0%})")
        lines.append("")

    _rollover_flag = detect_debt_rollover(_balance_history, signal_events)
    if _rollover_flag == "CB_ROLLOVER":
        lines += [
            "⚠ **CB_ROLLOVER 탐지** — 최근 3년간 채무증권 잔액이 10% 이내로 "
            "평탄하게 유지되면서 같은 기간 CB/BW 발행이 2건 이상 관찰됐습니다. "
            "신규 발행 자금으로 만기 도래분을 차환하는 '롤오버' 징후입니다.",
            "",
        ]

    if result["events"]:
        lines.append("**시계열** (최대 30건)")
        _events_slice = result["events"][:30]
        _cap_key_counts = Counter(e["key"] for e in _events_slice)
        _cap_key_seen: dict[str, int] = {}
        for e in _events_slice:
            _cap_key_seen[e["key"]] = _cap_key_seen.get(e["key"], 0) + 1
            _show_prose = (
                _cap_key_counts[e["key"]] <= _PROSE_REPEAT_LIMIT
                or _cap_key_seen[e["key"]] <= _PROSE_REPEAT_LIMIT
            )
            if _show_prose:
                meaning = signal_to_prose(e["key"], e.get("report_nm", ""))
                one_liner = meaning.split("다.")[0] + "다." if meaning else e.get("label", "")
            else:
                one_liner = ""
            lines.append(
                f"- {e['rcept_dt']} · {e['report_nm']}"
                + (f"\n  → {one_liner}" if one_liner else "")
            )
        if len(result["events"]) > 30:
            lines.append(f"- ... (총 {len(result['events'])}건 중 30건 표시)")
        lines.append("")

    if churn_flagged:
        pattern = pattern_to_prose("capital_churn_anomaly")
        if pattern:
            lines.append("**유사 패턴 서술**")
            lines.append(pattern)
            lines.append("")

    lines.append(
        "📎 참고: 이 도구는 공시 '횟수·리듬'을 잡아냅니다. 정확한 희석률이나 "
        "실제 조달 금액은 `get_major_decision` 또는 `get_disclosure_document`로 "
        "개별 공시를 열어 확인해야 합니다."
    )
    return "\n".join(lines)


def main() -> None:
    import sys
    transport = "sse" if "--sse" in sys.argv else "stdio"
    if transport == "sse":
        port = int(os.environ.get("PORT", "8000"))
        mcp.run(transport="sse", host="0.0.0.0", port=port)
    else:
        mcp.run()


if __name__ == "__main__":
    main()
