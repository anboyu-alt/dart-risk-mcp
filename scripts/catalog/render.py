"""분류 결과 → 카탈로그 MD 렌더링. 순수 함수만 두고 I/O는 build_md.py가 담당한다.

포맷은 기존 knowledge/manipulation_catalog/*.md와 바이트 수준으로 호환되어야 한다.
특히 `- **Severity**` 3줄은 core/catalog.py의 _TAXONOMY_META_LINE 정규식이
런타임에 제거하는 대상이라 표기를 바꾸면 점수·등급이 사용자에게 노출된다(v0.8.5 위반).
"""
from __future__ import annotations

from collections import Counter

from .labels import label_for

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


def aggregate_techniques(cases: list[dict], top_n: int = 10) -> list[tuple[str, int]]:
    """사례들의 적발 기법을 빈도순으로 집계한다."""
    counter: Counter = Counter()
    for case in cases:
        for tech in case.get("techniques") or []:
            cleaned = _cell(tech)
            if cleaned:
                counter[cleaned] += 1
    return counter.most_common(top_n)


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
            "### 탐지 키워드",
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
        out += ["", "---", ""]
    return "\n".join(out).rstrip() + "\n"
