"""DART 기업 위험 분석 MCP 서버

3개 도구:
- analyze_company_risk: 기업명/종목코드 → 종합 위험 리포트
- check_disclosure_risk: 공시 접수번호/제목 → 개별 공시 분석
- find_risk_precedents: 신호 조합 → 과거 유사 사례 (제한적 구현)
"""

import os
import re
from collections import Counter
from datetime import datetime, timedelta

from mcp.server.fastmcp import FastMCP

from .core import (
    calculate_risk_score,
    category_prose,
    detect_capital_churn,
    detect_debt_rollover,
    detect_financial_anomaly,
    estimate_crisis_timeline,
    extract_cb_investors,
    extract_rights_offering_investors,
    fetch_audit_opinion_history,
    fetch_company_disclosures,
    fetch_market_disclosures,
    fetch_company_info,
    fetch_debt_balance,
    fetch_disclosure_full,
    fetch_document_content,
    fetch_document_text,
    fetch_executive_compensation,
    fetch_financial_statements,
    fetch_financial_statements_all,
    fetch_fund_usage,
    fetch_insider_timeline,
    fetch_major_decision,
    fetch_multi_financial,
    fetch_shareholder_status,
    find_pattern_match,
    flag_to_prose,
    is_amendment_disclosure,
    list_document_sections,
    load_catalog_excerpt,
    match_signals,
    pattern_to_prose,
    resolve_corp,
    resolve_decision_type,
    signal_to_prose,
    CAPITAL_EVENT_KEYS,
    SIGNAL_KEY_TO_TAXONOMY,
    SIGNAL_TYPES,
    _fs_response_to_periods,
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
    # (조기 반환 제거 — 공시가 없어도 v0.6.0 자본 churn / 재무 이상 스캔은 별도로 수행)

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
        _r = fetch_major_decision(_d["rcept_no"], _DART_API_KEY, _dtype, corp_code)
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
                "report_nm": _format_fund_event_name(_rec),
                "rcept_dt": _rec.get("pay_de", "") or f"{_rec.get('year', '')}-00-00",
                "rcept_no": "",
                "is_amendment": False,
            })

    # ============ v0.6.0 블록 시작 ============
    # 자본 churn 탐지 (최근 12개월 window)
    try:
        churn = detect_capital_churn(signal_events, lookback_years=1)
        if "CAPITAL_CHURN" in churn["flags"]:
            signal_events.append({
                "key": "CAPITAL_CHURN",
                "label": "자본 이벤트 과다 반복",
                "score": 7,
                "report_nm": f"최근 12개월 내 자본 이벤트 {churn['max_12m_count']}건 집중",
                "rcept_dt": "",
                "rcept_no": "",
                "is_amendment": False,
            })
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
                signal_events.append({
                    "key": f,
                    "label": label,
                    "score": score,
                    "report_nm": f"{_year} 재무제표 YoY 이상",
                    "rcept_dt": "",
                    "rcept_no": "",
                    "is_amendment": False,
                })
    except Exception:
        pass
    # ============ v0.6.0 블록 끝 ============

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
        for inv in extract_cb_investors(_cb_rcept, _DART_API_KEY, corp_code):
            if inv["name"] not in seen_investors:
                seen_investors.add(inv["name"])
                cb_investors.append(inv)

    # ── 리포트 조립 ──

    # 🎯 3문장 요약 — 맨 위에 독립적으로 읽히는 단락
    non_amend_events = [e for e in signal_events if not e["is_amendment"]]
    top_signal_label = (
        top_signal.get("label", "") if top_signal else ""
    )
    top_signal_prose = (
        signal_to_prose(top_signal["key"]) if top_signal else ""
    )
    # 첫 문장: 규모
    s1 = (
        f"지난 {lookback_days}일 동안 **{corp_name}**의 공시 "
        f"{len(disclosures)}건을 살펴본 결과, 위험 신호로 꼽을 만한 공시·"
        f"재무 이벤트가 **{len(non_amend_events)}건** 감지됐습니다."
    )
    # 둘째 문장: 등급
    s2 = (
        f"종합 위험 점수는 {total_score}점으로 **{level}** 등급에 해당합니다. "
        "점수는 공시 기반 불공정거래 가능성의 참고값이며, 법적 판단이나 "
        "투자 결정의 근거는 아닙니다."
    )
    # 셋째 문장: 가장 무거운 신호
    if top_signal:
        s3 = _compose_top_signal_sentence(top_signal_label, top_signal_prose)
    else:
        s3 = "가장 주목할 만한 단일 신호는 감지되지 않았습니다."

    summary_block = f"🎯 {s1}\n\n{s2}\n\n{s3}"

    lines = [
        f"📊 **기업 리스크 분석: {corp_name}**",
        f"종목코드: {stock_code}" if stock_code else f"Corp code: {corp_code}",
        "",
        summary_block,
        "",
        f"{emoji} **위험 등급: {level}** ({total_score}점)",
        f"조회 기간: 최근 {lookback_days}일 | 전체 공시 {len(disclosures)}건 검토",
        "",
        f"━━ 탐지된 신호 ({len(signal_events)}건) ━━",
    ]

    # 같은 signal_key가 많이 반복될 때 해설(→)을 첫 3건에만 붙여 가독성을 보존한다.
    _key_counts = Counter(e["key"] for e in signal_events)
    _key_seen: dict[str, int] = {}
    for e in sorted(signal_events, key=lambda x: x["rcept_dt"], reverse=True):
        amend_tag = " · 정정공시(점수 제외)" if e["is_amendment"] else ""
        score_tag = "" if e["is_amendment"] else f" · {e['score']}점"
        date = e["rcept_dt"] or "-"
        _key_seen[e["key"]] = _key_seen.get(e["key"], 0) + 1
        _show_prose = (
            _key_counts[e["key"]] <= _PROSE_REPEAT_LIMIT
            or _key_seen[e["key"]] <= _PROSE_REPEAT_LIMIT
        )
        meaning = signal_to_prose(e["key"]) if _show_prose else ""
        one_liner = meaning if meaning else (e["label"] if _show_prose else "")
        # 첫 줄: 날짜 · 공시명 · 점수
        lines.append(
            f"• {date} · {_clean_report_name(e['report_nm'])}{score_tag}{amend_tag}"
        )
        # 두번째 줄: 의미 해설 (반복 N회 초과 시 생략)
        if one_liner:
            lines.append(f"  → {one_liner}")

    if pattern:
        pattern_key = None
        for k, v in __import__(
            "dart_risk_mcp.core.taxonomy", fromlist=["CROSS_SIGNAL_PATTERNS"]
        ).CROSS_SIGNAL_PATTERNS.items():
            if v.get("name") == pattern.get("name"):
                pattern_key = k
                break
        pattern_body = pattern_to_prose(pattern_key) if pattern_key else ""
        lines += [
            "",
            "━━ 복합 패턴 ━━",
            f"⚠️ **\"{pattern['name']}\"** 패턴이 감지됐습니다.",
        ]
        if pattern_body:
            lines.append("")
            lines.append(pattern_body)
        elif pattern.get("description"):
            lines.append(f"  → {pattern['description']}")

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
            prose = signal_to_prose(sig["key"])
            amendment_note = " (정정공시이므로 이번 분석에서는 위험 점수 0으로 처리합니다.)" if is_amendment else ""
            lines.append(f"🎯 **{sig['label']}**{amendment_note}")
            if prose:
                lines.append(prose)
            lines.append("")

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
    if rcept_no and any(s["key"] == "CB_BW" for s in matched) and not is_amendment:
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
        dec = fetch_major_decision(rcept_no, _DART_API_KEY, dtype, "")
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
            lines.append("")

    # 점수 합산
    total = sum(sig_map[k]["score"] for k in valid_keys)
    level = _risk_level(total)
    emoji = _risk_emoji(level)
    lines.append(
        f"{emoji} 이 신호 조합의 종합 위험도는 **{level}**입니다."
    )

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
        rcept_no = d.get("rcept_no", "")
        if is_amendment_disclosure(report_nm):
            continue
        matched = match_signals(report_nm)
        for sig in matched:
            phase = _PHASE_MAP.get(sig["key"], "심화기")
            events.append((rcept_dt, phase, sig["key"], sig["label"], report_nm, rcept_no))
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
        "",
        "🎯 **한눈에 보는 요약**",
        (
            f"- 최근 {lookback_days}일 동안 위험 신호로 분류된 공시 "
            f"{len(events)}건이 {first_date}부터 {last_date}까지 이어졌습니다."
        ),
        (
            f"- 이 가운데 가장 많이 몰려 있는 단계는 {phase_plain[busiest_phase]}로, "
            f"총 {phase_counts[busiest_phase]}건이 이 구간에 해당합니다."
        ),
    ]
    if pattern:
        summary_lines.append(
            f"- 이 흐름은 과거 금감원 적발 사례 중 \"{pattern['name']}\" 패턴과 "
            f"유사한 궤적을 그리고 있습니다(상세는 아래 참고)."
        )
    summary_lines.append("")

    lines = summary_lines

    # 단계 설명 머리말
    lines.append(
        "아래 타임라인은 공시를 세 단계로 나눠 보여줍니다. "
        "🟢 진입기는 자금을 끌어오거나 자본 구조를 바꾸는 움직임, "
        "🟡 심화기는 경영권·지배구조가 흔들리는 움직임, "
        "🔴 탈출기는 감사·수사·부실 등 위기가 드러나는 움직임입니다."
    )
    lines.append("")

    for phase_name in ("진입기", "심화기", "탈출기"):
        phase_events = phases[phase_name]
        if not phase_events:
            continue
        emoji = _PHASE_EMOJI[phase_name]
        lines.append(f"{emoji} **[{phase_name}] — {phase_events[0][0]} 이후 {len(phase_events)}건**")
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

    if pattern:
        pattern_id = pattern.get("pattern_id", "")
        prose_body = pattern_to_prose(pattern_id)
        lines += [
            "━━ 과거 금감원 적발 사례와의 유사도 ━━",
            f"⚠️ **\"{pattern['name']}\"** 패턴과 유사한 흐름입니다.",
        ]
        lines.append(prose_body or pattern.get("description", ""))
        months = pattern.get("timeline_months")
        if months:
            lines.append(
                f"과거 유사 사례에서는 위기가 본격화되기까지 평균 약 {months}개월이 걸린 것으로 집계됩니다."
            )
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

    lines.append("⚠️ 이 타임라인은 공시 제목 기반 자동 분류이며, 실제 상황과 다를 수 있습니다.")
    return "\n".join(lines)


# ── 도구 5: 세력 추적 (공통 CB/BW/EB + 유상증자 인수자) ──────────────────


@mcp.tool()
def find_actor_overlap(company_names: list[str]) -> str:
    """여러 기업(2~5개)의 CB/BW/EB 인수자 + 유상증자 인수자를 비교해 공통 행위자(세력)를 탐지한다.

    DART API 제약상, 분석 대상 기업을 직접 지정해야 한다.
    "행위자 이름으로 역검색"은 현재 불가능하다.

    CB/BW/EB 공시(CB_BW, EB 신호)와 유상증자 공시(3PCA, RIGHTS_UNDER 신호)를
    모두 수집해 인수자를 통합 비교하며, 공통 행위자에는 출처 태그(CB / 유상증자)를 표시한다.

    Args:
        company_names: 비교할 기업명 또는 종목코드 목록 (2~5개, 예: ["에코프로", "바이오제닉스"])
    """
    if not isinstance(company_names, list) or not (2 <= len(company_names) <= 5):
        return "입력 오류: 2개 이상 5개 이하 기업명(또는 종목코드) 리스트를 전달하세요."

    api_key = os.environ.get("DART_API_KEY") or _DART_API_KEY
    if not api_key:
        return "DART_API_KEY 환경변수가 설정되지 않았습니다."

    company_names = list(dict.fromkeys(company_names))  # 중복 제거 (순서 보존)

    CB_SIGNAL_KEYS = {"CB_BW", "EB"}
    RIGHTS_SIGNAL_KEYS = {"3PCA", "RIGHTS_UNDER"}
    # 기업당 CB 최대 3건 + 유상증자 최대 3건 (각 소스 독립 상한, 총 ≤ 6건)
    # 공통 상한을 쓰면 CB 공시가 많은 기업에서 유상증자 몫을 빼앗겨 "머지"가 CB-only로 회귀함
    MAX_DOCS_PER_SOURCE = 3

    # actor_map: {"actor_name": [(company, source, amount, rcept_no), ...]}
    actor_map: dict[str, list[tuple]] = {}
    per_company_solo: dict[str, list[tuple]] = {}
    failed: list[str] = []

    for query in company_names:
        result = resolve_corp(query, api_key)
        if not result:
            failed.append(query)
            continue
        corp_name, corp_info = result
        corp_code = corp_info["corp_code"]

        disclosures = fetch_company_disclosures(corp_code, api_key, lookback_days=365) or []

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
            entry = (corp_name, source, amount, rn)
            actor_map.setdefault(name, []).append(entry)
            per_company_solo.setdefault(corp_name, []).append((name, source, amount, rn))

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

    analyzed = [q for q in company_names if q not in failed]

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
            "발견되지 않았습니다. 다만 이 결과는 최근 365일, 기업당 CB 최대 "
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
            lines.append(
                f"  ⚠️ **{actor}** — {len(company_set)}개 회사에 "
                f"[{' · '.join(source_set)}] 경로로 등장: "
                f"{', '.join(company_set)}"
            )
    lines.append("")

    lines.append("━━ 회사별 전체 인수자 명단 (중복 제거) ━━")
    for corp_name, entries in per_company_solo.items():
        unique = sorted({(n, s) for n, s, _, _ in entries})
        if not unique:
            continue
        lines.append(f"  • {corp_name} — 총 {len(unique)}명:")
        for name, source in unique[:10]:
            lines.append(f"      [{source}] {name}")

    no_data = [cn for cn in analyzed if cn not in per_company_solo]
    if no_data:
        lines.append("")
        lines.append(
            "ℹ️ 최근 365일 안에 CB·BW·EB·유상증자 공시 자체가 없는 회사: "
            f"{', '.join(no_data)}"
        )

    lines.append("")
    lines.append(
        "⚠️ 이 결과는 DART 공개 API 범위 내 분석입니다. 최근 365일 이내 "
        "CB/BW/EB/유상증자 공시만 대상으로 하며, 회사당 CB 최대 3건 + "
        "유상증자 최대 3건으로 제한됩니다. 따라서 '공통 인수자 없음'이 "
        "'세력이 없다'는 결론으로 이어지지는 않습니다."
    )
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
def get_audit_opinion_history(company_name: str, lookback_years: int = 5) -> str:
    """감사의견·감사인 교체·비감사용역 이력을 조회합니다.

    DART OpenAPI 3개 엔드포인트(`accnutAdtorNmNdAdtOpinion`,
    `adtServcCnclsSttus`, `accnutAdtorNonAdtServcCnclsSttus`)를 결합해
    연도별 감사의견·감사인·보수 경고 신호를 한글 서술로 반환합니다.

    Args:
        company_name: 기업명 또는 종목코드(6자리).
        lookback_years: 1~10(밖이면 5로 강제).

    Returns:
        감사의견 표·교체 이력·독립성 경고 텍스트.
    """
    api_key = _DART_API_KEY
    if not api_key:
        return "❌ DART_API_KEY 환경변수가 설정되지 않았습니다."

    if not isinstance(lookback_years, int) or not (1 <= lookback_years <= 10):
        lookback_years = 5

    corp_info = resolve_corp(company_name, api_key)
    if not corp_info[1]:
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
    for o in data["opinions"]:
        warn = ""
        if o["opinion"] in ("한정", "부적정", "의견거절"):
            warn = f" ⚠ {o['opinion']}"
        elif o["opinion"] and o["opinion"] != "적정":
            warn = f" ({o['opinion']})"
        fee_parts = []
        if o["audit_fee_okwon"]:
            fee_parts.append(f"보수 {o['audit_fee_okwon']//100_000_000}억")
        if o["non_audit_fee_okwon"]:
            fee_parts.append(f"비감사 {o['non_audit_fee_okwon']//100_000_000}억")
        fee_str = f" · {' / '.join(fee_parts)}" if fee_parts else ""
        lines.append(
            f"- {o['year']}: {o['auditor'] or '미확인'} "
            f"(연속 {o['tenure_years']}년차){fee_str}{warn}"
        )
    lines.append("")

    if data["auditor_changes"]:
        lines.append("**감사인 교체 이력**")
        for c in data["auditor_changes"]:
            lines.append(f"- {c['from_year']}→{c['to_year']}: {c['from']} → {c['to']}")
        if len(data["auditor_changes"]) >= 2:
            lines.append("  ⚠ 3년 내 2회 이상 교체는 감사 독립성 경고 신호입니다.")
        lines.append("")

    if data["independence_warnings"]:
        lines.append("**독립성 경고**")
        for w in data["independence_warnings"]:
            lines.append(f"- ⚠ {w}")
        lines.append(
            "  비감사용역(세무·자문 등) 보수가 감사·비감사 합계의 30% 이상이면 "
            "외감법상 독립성 훼손 우려가 제기됩니다."
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

    corp_name, info = resolve_corp(company_name, api_key)
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

    # v0.8.0: 구조화 엔드포인트 보강 (실패 시 기존 키워드 매칭 점수 유지)
    _audit_struct = fetch_audit_opinion_history(corp_code, _DART_API_KEY, 5)
    _audit_bonus = 0
    _auditor_change_count = len(_audit_struct.get("auditor_changes", []))
    _indep_warnings = _audit_struct.get("independence_warnings", [])
    if _auditor_change_count >= 2:
        _audit_bonus += 5
    if _indep_warnings:
        _audit_bonus += 3
    s_audit = min(20, s_audit + _audit_bonus)

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

    # 상단 한 줄 요약
    summary = (
        f"🎯 최근 {lookback_days}일 동안 **{corp_name}**의 공시 활동 "
        f"{total}건을 5개 구조 지표로 집계한 결과 **{total_score}/100점 "
        f"({grade})**입니다. 점수 자체는 불공정거래 가능성의 '강도'를 "
        "가늠하는 참고값이며, 실제 해석은 아래 지표별 설명과 함께 봐야 합니다."
    )

    lines = [
        f"━━━ [{corp_name}] 공시 구조 이상 스코어 ━━━",
        f"조회기간: 최근 {lookback_days}일 / 총 공시 {total}건 (정정공시 {amendment_count}건)",
        "",
        summary,
        "",
        f"**종합 스코어: {total_score}/100  [{grade}]**",
        "",
        "── 지표별 내역 ──────────────────────────────",
        "",
        f"**① 정정공시 비율 — {s_amend}/25점** ({amendment_count}/{total}건, {amend_ratio:.0%})",
        (
            "이미 낸 공시를 고쳐서 다시 내는 비율입니다. 정상 기업은 보통 "
            "5% 안쪽이고, 20%를 넘으면 최초 공시 품질이 떨어지거나 "
            "정보를 조금씩 흘려보내는 의도가 있을 수 있습니다."
        ),
        "",
        f"**② 감사의견 이슈 — {s_audit}/20점** ({len(audit_hits)}건)",
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
            "— 감사 독립성 훼손 경고(+5점)."
        )
    if _indep_warnings:
        lines.append(
            f"  ⚠ 비감사용역 비중 초과 연도: {', '.join(_indep_warnings)} (+3점)."
        )
    lines += [
        "",
        f"**③ 공시의무 위반 — {s_viol}/15점** ({len(viol_hits)}건)",
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
        f"**④ 자본 스트레스 — {s_capital}/25점** ({len(capital_hits)}건)",
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
        f"**⑤ 조회공시 빈도 — {s_inquiry}/15점** ({len(inquiry_hits)}건)",
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
        excerpt = load_catalog_excerpt(["zombie_ma", "fake_new_biz"])
        if excerpt:
            lines.append(excerpt)
    else:
        lines.append("✅ 계획과 실제 사용이 맞아떨어져, 별도 경고 신호는 없습니다.")

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
}


@mcp.tool()
def scan_financial_anomaly(
    company_name: str,
    year: str = "",
    report_type: str = "annual",
) -> str:
    """
    재무제표 4개 지표(매출채권·재고자산·현금흐름·자본잠식)를 전년 대비로 비교해
    분식·부실 초기 조짐을 탐지합니다.

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
    if not corp_info[1]:
        return f"❌ 기업 '{company_name}'을(를) 찾을 수 없습니다."
    corp_name, info = corp_info
    corp_code = info["corp_code"]

    if not year:
        from datetime import datetime
        year = str(datetime.now().year - 1)

    # 전체 계정 과목 필요 (매출채권·재고자산 포함) → fnlttSinglAcntAll 사용. CFS 우선, 없으면 OFS.
    fs_list = fetch_financial_statements_all(corp_code, api_key, year, report_type, "CFS")
    if not fs_list:
        fs_list = fetch_financial_statements_all(corp_code, api_key, year, report_type, "OFS")
    if not fs_list:
        return (f"📊 **{corp_name}** ({info.get('stock_code','')}) — {year} {report_type}\n\n"
                "재무제표 조회 불가(데이터 없음 또는 권한 부족).")

    current, prior = _fs_response_to_periods({"list": fs_list})
    flags, metrics = detect_financial_anomaly(current, prior)

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
    for m in metrics:
        name = m["name"]
        if name == "순이익 vs 영업현금흐름":
            cur = (
                f"순이익 {m['current_ni']:,} / "
                f"영업현금흐름 {m['current_ocf']:,}"
            )
            pri = "-"
            delta = "-"
        elif "current" in m and "prior" in m:
            cur = f"{m['current']:.1f}{m.get('unit','')}"
            pri = f"{m['prior']:.1f}{m.get('unit','')}"
            delta = f"{m['delta']:+.1f}%p"
        else:
            cur = f"{m.get('current', 0):.1f}{m.get('unit','')}"
            pri = "-"
            delta = "-"
        lines.append(f"| {name} | {cur} | {pri} | {delta} |")

    lines.append("")
    if flagged_metrics:
        lines.append("### 이 지표가 말하는 것")
        lines.append("")
        for m in flagged_metrics:
            flag_key = _METRIC_TO_FLAG.get(m["name"], "")
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
    if not corp_info[1]:
        return f"❌ 기업 '{company_name}'을(를) 찾을 수 없습니다."
    corp_name, info = corp_info
    corp_code = info["corp_code"]

    disclosures = fetch_company_disclosures(corp_code, api_key, lookback_years * 365)

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
            "'3건 이상 몰림' 기준(CAPITAL_CHURN)에는 미치지 못했습니다. "
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
