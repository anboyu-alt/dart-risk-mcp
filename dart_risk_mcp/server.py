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
    fetch_document_text,
    find_pattern_match,
    is_amendment_disclosure,
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


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
