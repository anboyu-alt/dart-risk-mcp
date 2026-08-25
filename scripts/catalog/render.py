"""분류 결과 → 카탈로그 MD 렌더링. 순수 함수만 두고 I/O는 build_md.py가 담당한다.

포맷은 기존 knowledge/manipulation_catalog/*.md와 바이트 수준으로 호환되어야 한다.
특히 `- **Severity**` 3줄은 core/catalog.py의 _TAXONOMY_META_LINE 정규식이
런타임에 제거하는 대상이라 표기를 바꾸면 점수·등급이 사용자에게 노출된다(v0.8.5 위반).
"""
from __future__ import annotations

from collections import Counter

from .labels import label_for


def _detecting_signals(tid: str) -> str:
    """이 taxonomy를 실제로 켜는 신호와, 그 신호가 찾는 **DART 실제 표기**.

    옛 렌더는 `TAXONOMY[tid]["keywords"]`를 「### 탐지 키워드」로 실었다.
    그런데 `match_signals`는 그 목록을 **쓰지 않는다** — `SIGNAL_TYPES`의
    키워드로 매칭한다. 1년 코퍼스 실측(2026-08-25): taxonomy 키워드 217개 중
    **166개(76%)**가 신호 제목에 0건이고, **17개 taxonomy는 전멸**이다.
    예: 1.5의 「돌려막기·리파이낸싱·차환」은 DART 제목에 없고, 실제로는
    `CB_BW`(전환사채권발행결정 등)와 구조화 탐지 `CB_ROLLOVER`가 켠다.

    이 발췌는 `load_catalog_excerpt`를 거쳐 **사용자 출력에 그대로 실린다** —
    「탐지 키워드」라는 제목으로 검색하지도 않는 말을 보여주고 있었다.

    개념어는 지우지 않는다(유형을 설명하는 값이 있다) — **제목만** 사실에
    맞추고, 실제로 켜는 것을 위에 둔다.
    """
    from dart_risk_mcp.core.signals import (
        NON_TITLE_SIGNALS, SIGNAL_KEY_TO_TAXONOMY, SIGNAL_LABELS, SIGNAL_TYPES,
    )

    kw_by_key = {s["key"]: list(s.get("keywords") or []) for s in SIGNAL_TYPES}
    owners = [k for k, v in SIGNAL_KEY_TO_TAXONOMY.items() if tid in v]
    if not owners:
        return "— (제목 신호로는 발화하지 않습니다)"
    rows = []
    for key in sorted(owners):
        label = SIGNAL_LABELS.get(key, key)
        why = NON_TITLE_SIGNALS.get(key)
        kws = kw_by_key.get(key) or []
        if why or not kws:
            rows.append(f"- **{label}** — 제목으로 발화하지 않습니다")
        else:
            shown = ", ".join(kws[:6]) + (" …" if len(kws) > 6 else "")
            rows.append(f"- **{label}** — {shown}")
    return chr(10).join(rows)

# core/catalog.py의 _CATEGORY_TO_FILE과 동일해야 한다(테스트가 기계적으로 검증).
CATEGORY_FILES: dict[str, str] = {
    "Convertible Bond & Debt Manipulation": "01_cb_debt.md",
    "Capital Structure Manipulation": "02_capital_structure.md",
    "Ownership & Control": "03_ownership_control.md",
    "Governance & Disclosure": "04_governance.md",
    "Corporate Action Manipulation": "05_corporate_action.md",
    "Accounting & Financial Reporting": "06_accounting.md",
    "Market Manipulation & Trading": "07_market_manipulation.md",
    "Crisis & Distress Signals": "08_crisis_distress.md",
}

CATEGORY_KO: dict[str, str] = {
    "Convertible Bond & Debt Manipulation": "전환사채·부채 조작",
    "Capital Structure Manipulation": "자본구조 조작",
    "Ownership & Control": "지분·지배권",
    "Governance & Disclosure": "거버넌스·공시",
    "Corporate Action Manipulation": "기업행동 조작",
    "Accounting & Financial Reporting": "회계·재무보고",
    "Market Manipulation & Trading": "시장조작·거래",
    "Crisis & Distress Signals": "위기·부실 신호",
}


def _cell(value: str) -> str:
    """개행·파이프를 정리한다(MD 표·리스트가 깨지지 않도록)."""
    return " ".join(str(value or "").replace("|", "/").split())


def _join(items, empty: str = "—") -> str:
    vals = [_cell(x) for x in (items or []) if _cell(x)]
    return ", ".join(vals) if vals else empty


def render_case(case: dict) -> str:
    """적발 사례 한 건을 렌더한다. 줄 끝 두 칸 공백은 MD 줄바꿈이라 유지한다."""
    title = _cell(case.get("title", "제목미상"))
    url = _cell(case.get("url", ""))
    head = f"[{title}]({url})" if url else title
    lines = [
        f"- **{_cell(case.get('date', ''))} / {_cell(case.get('agency', ''))}** — {head}  ",
        f"  - 적발 기법: {_join(case.get('techniques'))}  ",
        f"  - 제재: {_join(case.get('sanctions'))}  ",
        f"  - 인용 법조: {_join(case.get('laws'))}  ",
    ]
    summary = _cell(case.get("summary", ""))
    if summary:
        lines.append(f"  - 요약: {summary}")
    return "\n".join(lines)


def _aggregate_field(cases: list[dict], field: str, top_n: int = 10) -> list[tuple[str, int]]:
    """사례들의 지정 필드(값이 리스트인 필드)를 빈도순으로 집계한다."""
    counter: Counter = Counter()
    for case in cases:
        for value in case.get(field) or []:
            cleaned = _cell(value)
            if cleaned:
                counter[cleaned] += 1
    return counter.most_common(top_n)


def aggregate_techniques(cases: list[dict], top_n: int = 10) -> list[tuple[str, int]]:
    """사례들의 적발 기법을 빈도순으로 집계한다."""
    return _aggregate_field(cases, "techniques", top_n)


def aggregate_laws(cases: list[dict], top_n: int = 10) -> list[tuple[str, int]]:
    """사례들의 인용 법조를 빈도순으로 집계한다."""
    return _aggregate_field(cases, "laws", top_n)


def render_category(
    category: str,
    tids: list[str],
    cases_by_tid: dict[str, list[dict]],
    labels: dict[str, dict],
    taxonomy: dict[str, dict],
    generated_on: str,
) -> str:
    """카테고리 MD 한 파일 전체를 렌더한다."""
    ko = CATEGORY_KO.get(category, category)
    ordered = sorted(tids, key=lambda t: [int(x) for x in t.split(".")])
    out: list[str] = [
        f"# {ko}",
        f"> 카테고리: {category}  ",
        f"> 생성일: {generated_on}  ",
        f"> 포함 유형: {', '.join(ordered)}",
        "",
        "---",
        "",
    ]
    for tid in ordered:
        entry = taxonomy.get(tid, {})
        lab = label_for(tid, labels, taxonomy)
        cases = cases_by_tid.get(tid) or []
        out += [
            f"## {tid}: {lab['title']}",
            "",
            f"- **Severity**: {entry.get('severity', '')}",
            f"- **Base Score**: {entry.get('base_score', '')}",
            f"- **Crisis Timeline**: {entry.get('crisis_timeline_months', '')}개월",
            "",
            "### 정의",
            lab["definition"],
            "",
            "### 이 유형을 켜는 신호",
            _detecting_signals(tid),
            "",
            "### 개념어 (참고 — 도구가 검색하는 말이 아닙니다)",
            ", ".join(entry.get("keywords") or []),
            "",
            "### 위험 신호",
        ]
        out += [f"- {flag}" for flag in lab["red_flags"]]
        out += ["", "### 금감원·금융위 적발 사례", ""]
        if cases:
            out += [render_case(c) for c in cases]
        else:
            out.append("적발 사례 없음 — 수집 범위에서 해당 유형의 보도자료가 확인되지 않았습니다.")
        out += ["", "### 적발 기법 종합", ""]
        agg = aggregate_techniques(cases)
        if agg:
            out += [f"- {tech} ({n}건)" for tech, n in agg]
        else:
            out.append("—")
        out += ["", "### 인용 법조", ""]
        laws = aggregate_laws(cases)
        if laws:
            out += [f"- {law} ({n}건)" for law, n in laws]
        else:
            out.append("—")
        out += ["", "### 기존 현장 기사 인용", ""]
        articles = lab["field_articles"]
        if articles:
            out += [f"- {_cell(a)}" for a in articles]
        else:
            out.append("—")
        out += ["", "---", ""]
    return "\n".join(out).rstrip() + "\n"
