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
    fetch_market_disclosures,
    fetch_company_info,
    fetch_disclosure_full,
    fetch_document_content,
    fetch_document_text,
    fetch_executive_compensation,
    fetch_financial_statements,
    fetch_fund_usage,
    fetch_insider_timeline,
    fetch_major_decision,
    fetch_multi_financial,
    fetch_shareholder_status,
    find_pattern_match,
    is_amendment_disclosure,
    list_document_sections,
    load_catalog_excerpt,
    match_signals,
    resolve_corp,
    resolve_decision_type,
    SIGNAL_KEY_TO_TAXONOMY,
    SIGNAL_TYPES,
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

    # v0.5.0: DS005 결정 공시 최신 10건 구조화 ------------------
    decision_items = [
        d for d in disclosures
        if resolve_decision_type(d.get("report_nm", ""))
    ][:10]
    decisions: list[tuple[dict, dict]] = []
    failed_decisions = 0
    for _d in decision_items:
        _dtype = resolve_decision_type(_d["report_nm"])
        _r = fetch_major_decision(_d["rcept_no"], _DART_API_KEY, _dtype)
        if "error" in _r:
            failed_decisions += 1
            continue
        decisions.append((_d, _r))

    # v0.5.0: 자금사용내역 (최근 3년 고정) -------------------------
    fund_records = fetch_fund_usage(corp_code, _DART_API_KEY, 3)

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
                "report_nm": f"[자금:{_rec['kind']} 회차{_rec['tm']}] {(_rec.get('plan_useprps') or '')[:30]}",
                "rcept_dt": _rec.get("pay_de", "") or f"{_rec.get('year', '')}-00-00",
                "rcept_no": "",
                "is_amendment": False,
            })

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

    # 7. CB 인수자 추출 (최근 3건까지)
    cb_investors: list[dict] = []
    seen_investors: set[str] = set()
    for _cb_rcept in cb_rcept_nos[:3]:
        for inv in extract_cb_investors(_cb_rcept, _DART_API_KEY):
            if inv["name"] not in seen_investors:
                seen_investors.add(inv["name"])
                cb_investors.append(inv)

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

    # v0.5.0: 주요 결정 상대방 섹션 ---------------------------
    if decisions:
        lines += ["", "📑 **주요 결정 상대방** (최근 순, 최대 10건)"]
        for _d, _r in decisions:
            _flag_str = " " + ",".join(_r["flags"]) if _r["flags"] else ""
            lines.append(f"- [{_d['rcept_dt']}] {_d['report_nm']}")
            lines.append(
                f"  → {_r['counterparty'] or '(미기재)'} / "
                f"{_r['amount']:,}원 ({_r['asset_ratio']:.1f}%)"
                f"{_flag_str}"
            )
        if failed_decisions:
            lines.append(f"  (추가 {failed_decisions}건 구조화 조회 실패)")

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
                f"- [{_r['year']} {_r['kind']} 회차{_r['tm']}] "
                f"{','.join(_r['flags'])} | "
                f"계획 {_r['plan_useprps'][:30]} → "
                f"실제 {_r['real_dtls_cn'][:30]}"
            )

    catalog = load_catalog_excerpt(tax_ids_all)
    if catalog:
        lines += ["", catalog]

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

    # v0.5.0: DS005 결정 공시면 구조화 필드 추가 ---------------
    dtype = resolve_decision_type(report_name)
    if dtype and rcept_no and _DART_API_KEY:
        dec = fetch_major_decision(rcept_no, _DART_API_KEY, dtype)
        if "error" not in dec:
            lines += ["", "📑 **결정 공시 구조화 정보**"]
            lines.append(f"- 유형: `{dec['decision_type']}`")
            lines.append(f"- 상대방: {dec['counterparty'] or '(미기재)'}")
            lines.append(
                f"- 금액: {dec['amount']:,}원 "
                f"(자산대비 {dec['asset_ratio']:.2f}%)"
            )
            lines.append(
                f"- 특수관계인: {'예' if dec['related_party'] else '아니오'}"
            )
            lines.append(
                f"- 외부평가: {'실시' if dec['external_eval'] else '미실시'}"
            )
            if dec["flags"]:
                lines.append("- 플래그: " + ", ".join(dec["flags"]))

    # 원문 요약
    if rcept_no and _DART_API_KEY:
        text = fetch_document_text(rcept_no, _DART_API_KEY, max_chars=500)
        if text:
            lines += ["", "━━ 원문 요약 (첫 500자) ━━", text[:500]]

    from .core.signals import SIGNAL_KEY_TO_TAXONOMY as _SKT
    all_tax_ids = list({tid for s in matched for tid in _SKT.get(s["key"], [])})
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
}
_PHASE_ORDER = {"진입기": 0, "심화기": 1, "탈출기": 2}
_PHASE_EMOJI = {"진입기": "🟢", "심화기": "🟡", "탈출기": "🔴"}


@mcp.tool()
def build_event_timeline(company_name: str, lookback_days: int = 365) -> str:
    """기업의 공시 이벤트를 시간순으로 정렬해 조작 흐름의 서사를 구성한다.

    각 이벤트를 진입기(자금 조달/경영권 진입), 심화기(지배구조 변화),
    탈출기(의심/수사/부실) 단계로 분류하고, 알려진 위기 패턴과 매칭한다.

    Args:
        company_name: 기업명 (예: "에코프로") 또는 종목코드 6자리 (예: "086520")
        lookback_days: 조회 기간 (기본 365일, 최대 365일)
    """
    if not _DART_API_KEY:
        return "❌ DART_API_KEY 환경변수가 설정되지 않았습니다."

    lookback_days = min(max(lookback_days, 1), 365)

    result = resolve_corp(company_name, _DART_API_KEY)
    if not result:
        return f"❌ '{company_name}'에 해당하는 기업을 DART에서 찾을 수 없습니다."
    corp_name, corp_info = result
    corp_code = corp_info["corp_code"]
    stock_code = corp_info.get("stock_code", "")

    disclosures = fetch_company_disclosures(corp_code, _DART_API_KEY, lookback_days)
    if not disclosures:
        return (
            f"📋 **{corp_name}** ({stock_code or corp_code})\n\n"
            f"최근 {lookback_days}일간 공시가 없습니다."
        )

    # 이벤트 수집: (날짜, 단계, 신호키, 신호라벨, 공시명)
    events: list[tuple[str, str, str, str, str]] = []
    all_tax_ids: set[str] = set()

    from .core.signals import SIGNAL_KEY_TO_TAXONOMY

    for d in disclosures:
        report_nm = d.get("report_nm", "")
        rcept_dt = d.get("rcept_dt", "")[:10]
        if is_amendment_disclosure(report_nm):
            continue
        matched = match_signals(report_nm)
        for sig in matched:
            phase = _PHASE_MAP.get(sig["key"], "심화기")
            events.append((rcept_dt, phase, sig["key"], sig["label"], report_nm))
            tax_ids = SIGNAL_KEY_TO_TAXONOMY.get(sig["key"], [])
            all_tax_ids.update(tax_ids)

    if not events:
        return (
            f"📋 **{corp_name}** ({stock_code or corp_code})\n\n"
            f"최근 {lookback_days}일간 위험 신호 이벤트가 없습니다.\n"
            f"(전체 공시 {len(disclosures)}건 검토)"
        )

    # 날짜순 정렬
    events.sort(key=lambda e: e[0])

    # 단계별 그룹핑
    phases: dict[str, list] = {"진입기": [], "심화기": [], "탈출기": []}
    for evt in events:
        phases[evt[1]].append(evt)

    # 패턴 매칭
    pattern = find_pattern_match(list(all_tax_ids))

    # 타임라인 출력
    first_date = events[0][0]
    last_date = events[-1][0]
    lines = [
        f"⏳ **이벤트 타임라인: {corp_name}** ({stock_code or corp_code})",
        f"기간: {first_date} ~ {last_date} | 이벤트 {len(events)}건",
        "",
    ]

    for phase_name in ("진입기", "심화기", "탈출기"):
        phase_events = phases[phase_name]
        if not phase_events:
            continue
        emoji = _PHASE_EMOJI[phase_name]
        lines.append(f"{emoji} **[{phase_name}]**")
        for evt in phase_events:
            lines.append(f"  • {evt[0]}  [{evt[3]}]  {evt[4]}")
        lines.append("")

    if pattern:
        lines += [
            "━━ 패턴 매칭 ━━",
            f"⚠️ **\"{pattern['name']}\"** 패턴과 유사",
            f"  → {pattern.get('description', '')}",
            f"  → 위기 사이클: 약 {pattern.get('timeline_months', '?')}개월",
            "",
        ]

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
            for inv in extract_cb_investors(rn, _DART_API_KEY):
                if inv["name"] not in seen:
                    seen.add(inv["name"])
                    investors.append(inv)
        if investors:
            lines.append("━━ CB/BW 인수자 (행위자) ━━")
            for inv in investors:
                amt = _format_amount(inv.get("amount", ""))
                lines.append(f"  • {inv['name']}" + (f" — {amt}" if amt else ""))
            lines.append("")

    lines.append("⚠️ 이 타임라인은 공시 제목 기반 자동 분류이며, 실제 상황과 다를 수 있습니다.")
    return "\n".join(lines)


# ── 도구 5: 세력 추적 (공통 CB 인수자) ────────────────────────────────────


@mcp.tool()
def find_actor_overlap(company_names: list[str]) -> str:
    """여러 기업의 CB/BW 인수자를 비교해 공통 행위자(세력)를 탐지한다.

    DART API 제약상, 분석 대상 기업을 직접 지정해야 한다.
    "행위자 이름으로 역검색"은 현재 불가능하다.

    Args:
        company_names: 비교할 기업명 목록 (2~5개, 예: ["에코프로", "바이오제닉스"])
    """
    if not _DART_API_KEY:
        return "❌ DART_API_KEY 환경변수가 설정되지 않았습니다."

    if len(company_names) < 2:
        return "❌ 최소 2개 기업을 입력하세요."
    if len(company_names) > 5:
        return "❌ 최대 5개 기업까지 비교할 수 있습니다."
    company_names = list(dict.fromkeys(company_names))  # 중복 제거 (순서 보존)

    # 기업별 CB 인수자 수집
    corp_investors: dict[str, list[dict]] = {}  # corp_name → [{"name":..., "amount":...}]
    failed: list[str] = []

    for name in company_names:
        result = resolve_corp(name, _DART_API_KEY)
        if not result:
            failed.append(name)
            continue
        corp_name, corp_info = result
        corp_code = corp_info["corp_code"]

        disclosures = fetch_company_disclosures(corp_code, _DART_API_KEY, 365)
        cb_rcepts = [
            d.get("rcept_no", "")
            for d in disclosures
            if any(s["key"] == "CB_BW" for s in match_signals(d.get("report_nm", "")))
            and not is_amendment_disclosure(d.get("report_nm", ""))
            and d.get("rcept_no")
        ]

        investors: list[dict] = []
        seen: set[str] = set()
        for rn in cb_rcepts[:3]:
            for inv in extract_cb_investors(rn, _DART_API_KEY):
                if inv["name"] not in seen:
                    seen.add(inv["name"])
                    investors.append({**inv, "corp_name": corp_name})

        corp_investors[corp_name] = investors

    if failed:
        lines_fail = [f"⚠️ 찾을 수 없는 기업: {', '.join(failed)}"]
    else:
        lines_fail = []

    # 인수자별로 등장 기업 집계
    actor_corps: dict[str, list[dict]] = {}  # investor_name → [{corp_name, amount}]
    for corp_name, investors in corp_investors.items():
        for inv in investors:
            actor_corps.setdefault(inv["name"], []).append(
                {"corp_name": corp_name, "amount": inv.get("amount", "")}
            )

    # 공통 행위자 (2개 이상 기업)
    overlaps = {k: v for k, v in actor_corps.items() if len(v) >= 2}
    singles = {k: v for k, v in actor_corps.items() if len(v) == 1}

    lines = [
        f"🔍 **공통 CB/BW 인수자 분석** ({len(corp_investors)}개 기업 비교)",
        f"분석 대상: {', '.join(corp_investors.keys())}",
        "",
    ]
    lines.extend(lines_fail)

    if overlaps:
        lines.append("━━ 공통 행위자 (세력 추적) ━━")
        for actor, entries in sorted(overlaps.items(), key=lambda x: -len(x[1])):
            detail = ", ".join(
                f"{e['corp_name']} {_format_amount(e['amount'])}" if e['amount']
                else e['corp_name']
                for e in entries
            )
            lines.append(f"  ⚠️ **{actor}**: {detail} → {len(entries)}개 기업 관여")
        lines.append("")
    else:
        lines += ["✅ 공통 행위자가 발견되지 않았습니다.", ""]

    if singles:
        lines.append("━━ 기업별 단독 인수자 ━━")
        for actor, entries in singles.items():
            e = entries[0]
            amt = _format_amount(e['amount']) if e.get('amount') else ""
            lines.append(f"  • {e['corp_name']}: {actor}" + (f" — {amt}" if amt else ""))
        lines.append("")

    no_cb = [cn for cn, inv in corp_investors.items() if not inv]
    if no_cb:
        lines.append(f"ℹ️ CB/BW 공시 없음: {', '.join(no_cb)}")

    lines.append("⚠️ DART 공개 API 범위 내 분석이며, 비공개 거래는 포함되지 않습니다.")
    return "\n".join(lines)


# ── 도구 6: 종목코드로 공시 접수번호 목록 조회 ────────────────────────────


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
    "cb_issue":           ["CB_BW", "CB_REPAY", "CB_ROLLOVER", "CB_BUYBACK", "EB", "RCPS", "TREASURY_EB"],
    "treasury":           ["TREASURY"],
    "reverse_split":      ["REVERSE_SPLIT", "CAPITAL_RED", "GAMJA_MERGE"],
    "3pca":               ["3PCA", "RIGHTS_UNDER"],
    "shareholder_change": ["SHAREHOLDER", "MGMT_DISPUTE"],
    "exec_change":        ["EXEC"],
    "audit_issue":        ["AUDIT", "DISCLOSURE_VIOL"],
    "asset_transfer":     ["ASSET_TRANSFER", "ASSET_SPIRAL", "DEMERGER"],
    "going_concern":      ["GOING_CONCERN", "INSOLVENCY", "DEBT_RESTR"],
    "embezzle":           ["EMBEZZLE"],
    "inquiry":            ["INQUIRY"],
    "all_risk":           [],  # 모든 신호
}


@mcp.tool()
def search_market_disclosures(preset: str, days: int = 7, max_results: int = 50) -> str:
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
                going_concern / embezzle / inquiry / all_risk
        days: 조회 기간 (기본 7일, 최대 90일)
        max_results: 최대 반환 건수 (기본 50, 최대 200)
    """
    from datetime import datetime, timedelta

    if not _DART_API_KEY:
        return "❌ DART_API_KEY 환경변수가 설정되지 않았습니다."
    if preset not in _PRESET_TO_SIGNALS:
        return (
            f"❌ 알 수 없는 preset: {preset!r}\n"
            f"허용값: {', '.join(sorted(_PRESET_TO_SIGNALS))}"
        )
    days = max(1, min(90, days))
    max_results = max(1, min(200, max_results))

    now = datetime.now()
    bgn_de = (now - timedelta(days=days)).strftime("%Y%m%d")
    end_de = now.strftime("%Y%m%d")

    raw = fetch_market_disclosures(_DART_API_KEY, bgn_de, end_de, max_pages=10)
    if not raw:
        return f"❌ 최근 {days}일 시장 공시를 불러올 수 없습니다."

    target_keys = set(_PRESET_TO_SIGNALS[preset])

    filtered: list[tuple[dict, list[dict]]] = []
    for d in raw:
        report_nm = d.get("report_nm", "")
        sigs = match_signals(report_nm)
        if not sigs:
            continue
        if target_keys and not any(s["key"] in target_keys for s in sigs):
            continue
        filtered.append((d, sigs))

    filtered.sort(key=lambda x: x[0].get("rcept_dt", ""), reverse=True)
    truncated = len(filtered) > max_results
    shown = filtered[:max_results]

    lines = [
        f"🔍 **시장 공시 스캔** (preset={preset}, 최근 {days}일)",
        f"전체 {len(raw)}건 중 신호 일치 {len(filtered)}건 (표시 {len(shown)}건)",
        "",
    ]

    if not shown:
        lines.append(f"✅ 해당 기간에 '{preset}' 프리셋에 해당하는 공시가 없습니다.")
        return "\n".join(lines)

    lines.append(f"{'─' * 60}")
    for d, sigs in shown:
        corp_nm = d.get("corp_name", "-")
        rcept_dt = d.get("rcept_dt", "")
        rcept_no = d.get("rcept_no", "")
        report_nm = d.get("report_nm", "")
        sig_labels = ", ".join(s["label"] for s in sigs)
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

    corp_name, meta = resolve_corp(company_name, _DART_API_KEY)
    if not corp_name:
        return f"기업을 찾을 수 없습니다: {company_name}"
    corp_code = meta["corp_code"]

    data = fetch_executive_compensation(corp_code, _DART_API_KEY, year, report_type)

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

    corp_name, meta = resolve_corp(company_name, _DART_API_KEY)
    if not corp_name:
        return f"기업을 찾을 수 없습니다: {company_name}"
    corp_code = meta["corp_code"]

    lookback_years = max(1, min(5, lookback_years))
    records = fetch_insider_timeline(corp_code, _DART_API_KEY, lookback_years)

    if not records:
        return f"[{corp_name}] 최근 {lookback_years}년간 대량보유·최대주주 공시 없음."

    # ── 보고자별 시계열 구성 ──────────────────────────────────
    from collections import defaultdict
    timeline: dict[str, list[dict]] = defaultdict(list)
    for rec in records:
        holder = rec.get("repror") or rec.get("nm", "미상")
        timeline[holder].append(rec)

    def _parse_ratio(val: str) -> float:
        try:
            return float(str(val).replace(",", "").replace("%", "").strip())
        except (ValueError, AttributeError):
            return 0.0

    lines = [
        f"━━━ [{corp_name}] 임원·대주주 지분 변동 시계열 (최근 {lookback_years}년) ━━━",
        "",
    ]

    # ── 클러스터 탐지 (30일 윈도우) ───────────────────────────
    buy_cluster: list[str] = []
    sell_cluster: list[str] = []

    import datetime as _dt

    for holder, recs in timeline.items():
        recs_sorted = sorted(recs, key=lambda r: r.get("rcept_dt", r.get("bsns_year", "")))
        ratios = [_parse_ratio(r.get("stkqy_rt", r.get("trmend_posesn_stock_qota_rt", "0"))) for r in recs_sorted]

        lines.append(f"▶ {holder}")
        for i, rec in enumerate(recs_sorted):
            date = rec.get("rcept_dt") or rec.get("bsns_year", "-")
            ratio = ratios[i]
            delta = ratios[i] - ratios[i - 1] if i > 0 else 0.0
            delta_str = f" (Δ{delta:+.2f}%)" if i > 0 else ""
            source_label = "대량보유" if rec.get("source") == "elestock" else "최대주주"
            lines.append(f"    {date}  {ratio:.2f}%{delta_str}  [{source_label}]")

            if i > 0:
                try:
                    d_prev = _dt.datetime.strptime(recs_sorted[i - 1].get("rcept_dt", "00000000")[:8], "%Y%m%d")
                    d_curr = _dt.datetime.strptime(rec.get("rcept_dt", "00000000")[:8], "%Y%m%d")
                    within_30d = abs((d_curr - d_prev).days) <= 30
                except ValueError:
                    within_30d = False
                if within_30d and delta > 0.5:
                    buy_cluster.append(holder)
                elif within_30d and delta < -0.5:
                    sell_cluster.append(holder)
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

    lines += [
        "─────────────────────────────────────────────",
        "※ 공시 지연으로 실시간 내부자 거래 현황과 차이가 있을 수 있습니다.",
        "   본 정보는 공시 기반 불공정거래 위험 모니터링 목적으로만 활용하십시오.",
        "💡 임원 보수 조회: get_executive_compensation(company_name=...)",
    ]
    return "\n".join(lines)


@mcp.tool()
def check_disclosure_anomaly(company_name: str, lookback_days: int = 365) -> str:
    """공시 구조 지표를 집계해 0~100 이상 스코어를 반환합니다.

    정정공시 비율·감사의견 이슈·공시의무 위반·자본 스트레스·조회공시 빈도
    5개 지표를 가중 합산합니다.

    Args:
        company_name: 기업명 또는 종목코드
        lookback_days: 조회 기간 (기본값 365일)

    Returns:
        0~100 스코어 + 지표별 내역 텍스트
    """
    if not _DART_API_KEY:
        return "오류: DART_API_KEY 환경변수가 설정되지 않았습니다."

    corp_name, meta = resolve_corp(company_name, _DART_API_KEY)
    if not corp_name:
        return f"기업을 찾을 수 없습니다: {company_name}"
    corp_code = meta["corp_code"]

    disclosures = fetch_company_disclosures(corp_code, _DART_API_KEY, lookback_days)
    total = len(disclosures)
    if total == 0:
        return f"[{corp_name}] 최근 {lookback_days}일 공시 없음 — 스코어 산출 불가."

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

    # ── 가중 스코어 (상한 100) ─────────────────────────────────
    amend_ratio = amendment_count / total
    s_amend = min(25, round(amend_ratio * 25))
    s_audit = min(20, len(audit_hits) * 20)
    s_viol = min(15, len(viol_hits) * 15)
    s_capital = min(25, len(capital_hits) * 5)
    s_inquiry = min(15, len(inquiry_hits) * 5)
    total_score = min(100, s_amend + s_audit + s_viol + s_capital + s_inquiry)

    if total_score >= 70:
        grade = "심각"
    elif total_score >= 50:
        grade = "높음"
    elif total_score >= 30:
        grade = "보통"
    else:
        grade = "낮음"

    def _top3(items: list[str]) -> str:
        shown = items[:3]
        rest = len(items) - len(shown)
        out = "\n".join(f"    • {nm}" for nm in shown)
        if rest:
            out += f"\n    … 외 {rest}건"
        return out

    lines = [
        f"━━━ [{corp_name}] 공시 구조 이상 스코어 ━━━",
        f"조회기간: 최근 {lookback_days}일 / 총 공시 {total}건 (정정공시 {amendment_count}건)",
        "",
        f"종합 스코어: {total_score}/100  [{grade}]",
        "",
        "── 지표별 내역 ──────────────────────────────",
        f"① 정정공시 비율   {s_amend:2d}점  ({amendment_count}/{total}건, {amend_ratio:.0%})",
        f"② 감사의견 이슈   {s_audit:2d}점  ({len(audit_hits)}건)",
    ]
    if audit_hits:
        lines.append(_top3(audit_hits))
    lines += [
        f"③ 공시의무 위반   {s_viol:2d}점  ({len(viol_hits)}건)",
    ]
    if viol_hits:
        lines.append(_top3(viol_hits))
    lines += [
        f"④ 자본 스트레스   {s_capital:2d}점  ({len(capital_hits)}건)",
    ]
    if capital_hits:
        lines.append(_top3(capital_hits))
    lines += [
        f"⑤ 조회공시 빈도   {s_inquiry:2d}점  ({len(inquiry_hits)}건)",
    ]
    if inquiry_hits:
        lines.append(_top3(inquiry_hits))
    lines += [
        "",
        "─────────────────────────────────────────────",
        "※ 본 스코어는 공시 기반 불공정거래 위험 모니터링 목적의 참고 지표이며,",
        "   법적 판단이나 투자 결정의 근거로 사용할 수 없습니다.",
        "💡 세부 분석: analyze_company_risk(company_name=...)",
    ]
    return "\n".join(lines)


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

    corp_name, info = resolve_corp(company_name, _DART_API_KEY)
    if not info:
        return f"❌ '{company_name}'에 해당하는 기업을 찾을 수 없습니다."

    records = fetch_fund_usage(info["corp_code"], _DART_API_KEY, lookback_years)
    if not records:
        return (
            f"💰 **{corp_name}** 자금사용내역\n\n"
            f"최근 {lookback_years}년간 등록된 공모/사모 자금사용내역이 없습니다.\n"
            f"(정기보고서(사업/반기/분기) 제출 시점에만 갱신됩니다.)"
        )

    lines = [
        f"💰 **{corp_name}** 조달자금 사용내역 (lookback={lookback_years}년)",
        f"총 {len(records)}건 조회",
        "",
    ]
    anomaly_records = []
    for rec in records:
        flags_str = " ".join(f"⚠{f}" for f in rec["flags"])
        if rec["flags"]:
            anomaly_records.append(rec)
        lines.append(
            f"[{rec['year']} {rec['kind']} 회차{rec['tm']}] "
            f"납입 {rec['pay_amount']:,}원"
        )
        lines.append(
            f"  계획: {rec['plan_useprps'][:60] or '(공란)'} "
            f"({rec['plan_amount']:,}원)"
        )
        lines.append(
            f"  실제: {rec['real_dtls_cn'][:60] or '(공란)'} "
            f"({rec['real_dtls_amount']:,}원) {flags_str}"
        )
        if rec["dffrnc_resn"]:
            lines.append(f"  차이사유: {rec['dffrnc_resn'][:100]}")
        lines.append("")

    if anomaly_records:
        lines.append(f"🚨 **이상 플래그 {len(anomaly_records)}건**")
        lines.append("")
        lines.append(load_catalog_excerpt(["zombie_ma", "fake_new_biz"]))
    else:
        lines.append("✅ 탐지된 이상 플래그 없음")

    return "\n".join(lines)


@mcp.tool()
def get_major_decision(rcept_no: str, decision_type: str = "") -> str:
    """DS005 주요사항보고서 12종 결정 공시(양수도·합병·분할·교환)를
    구조화 필드로 조회한다. related_party_hollowing·delisting_evasion
    패턴의 경로 추적에 사용.

    Args:
        rcept_no: 14자리 접수번호
        decision_type: 결정 유형 (미지정 시 지원 타입 안내).
            business_acq | business_div | tangible_acq | tangible_div |
            stock_acq | stock_div | bond_acq | bond_div |
            merger | demerger | demerger_merger | stock_exchange
    """
    if not _DART_API_KEY:
        return "❌ DART_API_KEY 환경변수가 설정되지 않았습니다."

    result = fetch_major_decision(rcept_no, _DART_API_KEY, decision_type)
    if "error" in result:
        return f"❌ {result['error']}"

    lines = [
        f"📑 **주요사항 결정 공시** (rcept_no={rcept_no})",
        f"- 유형: `{result['decision_type']}`",
        f"- 상대방: {result['counterparty'] or '(미기재)'}",
        f"- 금액: {result['amount']:,}원",
        f"- 자산대비: {result['asset_ratio']:.2f}%",
        f"- 특수관계인: {'예' if result['related_party'] else '아니오'}",
        f"- 외부평가: {'실시' if result['external_eval'] else '미실시'}",
        f"- 결의일: {result['bddd'] or '(미기재)'}",
    ]
    if result["flags"]:
        lines.append("")
        lines.append("🚨 **탐지 플래그**: " + ", ".join(result["flags"]))
        tax_ids = sorted({
            t for f in result["flags"]
            for t in SIGNAL_KEY_TO_TAXONOMY.get(f, [])
        })
        if tax_ids:
            lines.append(f"관련 taxonomy ID: {', '.join(tax_ids)}")
    lines.append("")
    lines.append(f"원문 전체 보기: `view_disclosure('{rcept_no}')`")
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
