"""DART 기업 위험 분석 MCP 서버

3개 도구:
- analyze_company_risk: 기업명/종목코드 → 종합 위험 리포트
- check_disclosure_risk: 공시 접수번호/제목 → 개별 공시 분석
- find_risk_precedents: 신호 조합 → 과거 유사 사례 (제한적 구현)
"""

import os

from mcp.server.fastmcp import FastMCP

from .core import (
    calculate_risk_score,
    estimate_crisis_timeline,
    extract_cb_investors,
    fetch_company_disclosures,
    fetch_disclosure_full,
    fetch_document_content,
    fetch_document_text,
    find_pattern_match,
    is_amendment_disclosure,
    list_document_sections,
    match_signals,
    resolve_corp,
)

mcp = FastMCP("dart-risk-analyzer")

_DART_API_KEY: str = os.environ.get("DART_API_KEY", "")


# ── 공통 헬퍼 ──────────────────────────────────────────────────────────────


def _risk_level(score: int) -> str:
    if score >= 15:
        return "매우위험"
    if score >= 10:
        return "고위험"
    if score >= 7:
        return "위험"
    return "주의"


def _risk_emoji(level: str) -> str:
    return {"매우위험": "🔴", "고위험": "🟠", "위험": "🟡", "주의": "🔵"}.get(level, "⚪")


def _format_amount(amount: str) -> str:
    if not amount:
        return ""
    digits = amount.replace("원", "").replace(",", "")
    if digits.isdigit():
        n = int(digits)
        if n >= 1_000_000_000_000:
            return f"{n // 1_000_000_000_000}조원"
        if n >= 100_000_000:
            return f"{n // 100_000_000}억원"
        if n >= 10_000:
            return f"{n // 10_000}만원"
    return amount


# ── 도구 1: 기업 종합 위험 분석 ────────────────────────────────────────────


@mcp.tool()
def analyze_company_risk(company_name: str, lookback_days: int = 90) -> str:
    """기업명 또는 종목코드로 최근 공시 기반 투자 위험도를 분석한다.

    Args:
        company_name: 기업명 (예: "에코프로") 또는 종목코드 6자리 (예: "086520")
        lookback_days: 조회 기간 (기본 90일, 최대 365일)
    """
    if not _DART_API_KEY:
        return "❌ DART_API_KEY 환경변수가 설정되지 않았습니다."

    lookback_days = min(max(lookback_days, 1), 365)

    # 1. 기업 조회
    result = resolve_corp(company_name, _DART_API_KEY)
    if not result:
        return f"❌ '{company_name}'에 해당하는 기업을 DART에서 찾을 수 없습니다."
    corp_name, corp_info = result
    corp_code = corp_info["corp_code"]
    stock_code = corp_info.get("stock_code", "")

    # 2. 공시 목록 조회
    disclosures = fetch_company_disclosures(corp_code, _DART_API_KEY, lookback_days)
    if not disclosures:
        return (
            f"📋 **{corp_name}** ({stock_code or corp_code})\n\n"
            f"최근 {lookback_days}일간 탐지된 의심 공시가 없습니다."
        )

    # 3. 신호 분류 + 정정공시 필터
    signal_events: list[dict] = []
    cb_rcept_nos: list[str] = []

    for d in disclosures:
        report_nm = d.get("report_nm", "")
        rcept_no = d.get("rcept_no", "")
        rcept_dt = d.get("rcept_dt", "")[:10]
        is_amendment = is_amendment_disclosure(report_nm)
        matched = match_signals(report_nm)

        for sig in matched:
            signal_events.append(
                {
                    "key": sig["key"],
                    "label": sig["label"],
                    "score": 0 if is_amendment else sig["score"],
                    "report_nm": report_nm,
                    "rcept_dt": rcept_dt,
                    "rcept_no": rcept_no,
                    "is_amendment": is_amendment,
                }
            )
            if sig["key"] == "CB_BW" and not is_amendment and rcept_no:
                cb_rcept_nos.append(rcept_no)

    if not signal_events:
        return (
            f"📋 **{corp_name}** ({stock_code or corp_code})\n\n"
            f"최근 {lookback_days}일간 탐지된 의심 공시가 없습니다.\n"
            f"(전체 공시 {len(disclosures)}건 검토)"
        )

    # 4. 위험점수
    total_score = sum(e["score"] for e in signal_events)
    level = _risk_level(total_score)
    emoji = _risk_emoji(level)

    # 5. 복합 패턴
    from .core.signals import SIGNAL_KEY_TO_TAXONOMY as _SKT

    sig_keys = list({e["key"] for e in signal_events if not e["is_amendment"]})
    tax_ids_all = list({tid for k in sig_keys for tid in _SKT.get(k, [])})
    pattern = find_pattern_match(tax_ids_all)

    # 6. 타임라인 (가장 고점수 신호 기준)
    top_signal = max(
        (e for e in signal_events if not e["is_amendment"]),
        key=lambda e: e["score"],
        default=None,
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

    # 7. CB 인수자 추출 (첫 번째 공시만)
    cb_investors: list[dict] = []
    if cb_rcept_nos:
        cb_investors = extract_cb_investors(cb_rcept_nos[0], _DART_API_KEY)

    # ── 리포트 조립 ──
    lines = [
        f"📊 **기업 리스크 분석: {corp_name}**",
        f"종목코드: {stock_code}" if stock_code else f"Corp code: {corp_code}",
        "",
        f"{emoji} **위험 등급: {level}** ({total_score}점)",
        f"조회 기간: 최근 {lookback_days}일 | 전체 공시 {len(disclosures)}건 검토",
        "",
        f"━━ 탐지된 신호 ({len(signal_events)}건) ━━",
    ]

    for e in sorted(signal_events, key=lambda x: x["rcept_dt"], reverse=True):
        amend_tag = " ⚠️ 정정공시 (점수 제외)" if e["is_amendment"] else ""
        score_tag = "" if e["is_amendment"] else f" ({e['score']}점)"
        lines.append(
            f"• [{e['key']}] {e['report_nm']} — {e['rcept_dt']}{score_tag}{amend_tag}"
        )

    if pattern:
        lines += [
            "",
            "━━ 복합 패턴 ━━",
            f"• ⚠️ **\"{pattern['name']}\"** 패턴 매칭",
            f"  → {pattern.get('description', '')}",
        ]

    if cb_investors:
        lines += ["", "━━ CB 인수자 ━━"]
        for inv in cb_investors:
            amt = _format_amount(inv.get("amount", ""))
            lines.append(f"• {inv['name']}" + (f" — {amt}" if amt else ""))

    if timeline_text:
        lines += ["", "━━ 위기 타임라인 ━━", timeline_text]

    return "\n".join(lines)


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

    title = report_name or f"접수번호 {rcept_no}"
    is_amendment = is_amendment_disclosure(title)
    matched = match_signals(title)

    lines = [f"📋 **공시 리스크 분석**", f"공시: {title}", ""]

    if not matched:
        lines.append("이 공시에서 의심 신호가 탐지되지 않았습니다.")
    else:
        for sig in matched:
            from .core.signals import SIGNAL_KEY_TO_TAXONOMY

            tax_ids = SIGNAL_KEY_TO_TAXONOMY.get(sig["key"], [])
            score = 0 if is_amendment else sig["score"]
            lines += [
                f"신호 유형: **{sig['label']}** ({sig['key']}, {score}점{' — 정정공시 제외' if is_amendment else ''})",
                f"정정공시 여부: {'예 (기존 공시의 수정)' if is_amendment else '아니오 (원본 공시)'}",
            ]

            # 타임라인
            if tax_ids and not is_amendment:
                tl = estimate_crisis_timeline(tax_ids[0])
                if tl:
                    tl_parts = []
                    months = tl.get("months_to_impact")
                    loss = tl.get("equity_loss_pct")
                    if months and months < 999:
                        tl_parts.append(f"위기 도달 약 {months}개월")
                    if loss:
                        tl_parts.append(f"지분 손실 추정 {loss}%")
                    if tl_parts:
                        lines += ["", "━━ 위기 타임라인 ━━", "• " + ", ".join(tl_parts)]

    # CB/BW면 인수자 추출
    if rcept_no and any(s["key"] == "CB_BW" for s in matched) and not is_amendment:
        if not _DART_API_KEY:
            lines += ["", "⚠️ DART_API_KEY 미설정 — CB 인수자 조회 불가"]
        else:
            investors = extract_cb_investors(rcept_no, _DART_API_KEY)
            if investors:
                lines += ["", "━━ CB/BW 인수자 ━━"]
                for inv in investors:
                    amt = _format_amount(inv.get("amount", ""))
                    lines.append(f"• {inv['name']}" + (f" — {amt}" if amt else ""))

    # 원문 요약
    if rcept_no and _DART_API_KEY:
        text = fetch_document_text(rcept_no, _DART_API_KEY, max_chars=500)
        if text:
            lines += ["", "━━ 원문 요약 (첫 500자) ━━", text[:500]]

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

    from .core.signals import SIGNAL_KEY_TO_TAXONOMY, SIGNAL_TYPES

    sig_map = {s["key"]: s for s in SIGNAL_TYPES}
    valid_keys = []
    unknown = []

    for k in signal_types:
        k_upper = k.upper()
        if k_upper in sig_map:
            valid_keys.append(k_upper)
        else:
            unknown.append(k)

    lines = ["📚 **신호 위험 해석**", ""]

    if unknown:
        known_list = ", ".join(sig_map.keys())
        lines.append(f"⚠️ 알 수 없는 신호: {', '.join(unknown)}")
        lines.append(f"사용 가능한 신호: {known_list}")
        lines.append("")

    for key in valid_keys:
        sig = sig_map[key]
        tax_ids = SIGNAL_KEY_TO_TAXONOMY.get(key, [])
        lines += [
            f"━━ {sig['label']} ({key}, {sig['score']}점) ━━",
            f"키워드: {', '.join(sig['keywords'][:5])}",
        ]
        for tid in tax_ids:
            tl = estimate_crisis_timeline(tid)
            if tl:
                months = tl.get("months_to_impact")
                loss = tl.get("equity_loss_pct")
                parts = []
                if months and months < 999:
                    parts.append(f"위기까지 {months}개월")
                if loss:
                    parts.append(f"손실 {loss}%")
                if parts:
                    lines.append(f"• 분류 {tid}: " + ", ".join(parts))
        lines.append("")

    # 복합 패턴
    if len(valid_keys) >= 2:
        tax_ids_flat = list({tid for k in valid_keys for tid in SIGNAL_KEY_TO_TAXONOMY.get(k, [])})
        pattern = find_pattern_match(tax_ids_flat)
        if pattern:
            lines += [
                "━━ 복합 패턴 감지 ━━",
                f"⚠️ **\"{pattern['name']}\"**",
                pattern.get("description", ""),
                "",
            ]

    # 점수 합산
    total = sum(sig_map[k]["score"] for k in valid_keys)
    level = _risk_level(total)
    emoji = _risk_emoji(level)
    lines.append(f"{emoji} 신호 합산 점수: **{total}점** ({level})")

    return "\n".join(lines)


# ── 도구 4: 종목코드로 공시 접수번호 목록 조회 ────────────────────────────


@mcp.tool()
def list_disclosures_by_stock(stock_code: str, lookback_days: int = 90) -> str:
    """종목코드로 최근 공시의 접수번호(rcept_no) 목록을 조회한다.

    반환된 접수번호는 get_disclosure_document, view_disclosure,
    check_disclosure_risk 등에 바로 사용할 수 있다.

    Args:
        stock_code: 종목코드 6자리 (예: "086520")
        lookback_days: 조회 기간 (기본 90일, 최대 365일)
    """
    import re as _re

    if not _DART_API_KEY:
        return "❌ DART_API_KEY 환경변수가 설정되지 않았습니다."

    if not _re.match(r"^\d{6}$", stock_code):
        return "❌ 종목코드는 6자리 숫자여야 합니다. 예: '086520'"

    lookback_days = min(max(lookback_days, 1), 365)

    result = resolve_corp(stock_code, _DART_API_KEY)
    if not result:
        return f"❌ 종목코드 '{stock_code}'에 해당하는 기업을 DART에서 찾을 수 없습니다."

    corp_name, corp_info = result
    corp_code = corp_info["corp_code"]

    disclosures = fetch_company_disclosures(corp_code, _DART_API_KEY, lookback_days)
    if not disclosures:
        return (
            f"📋 **{corp_name}** ({stock_code})\n\n"
            f"최근 {lookback_days}일간 공시가 없습니다."
        )

    lines = [
        f"📋 **{corp_name}** ({stock_code}) 공시 접수번호 목록",
        f"조회 기간: 최근 {lookback_days}일 | 총 {len(disclosures)}건",
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

    return "\n".join(lines)


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
            lines.append(f"   [{sec['id']}] {sec['title']}")
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
