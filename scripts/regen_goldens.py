"""DART Risk MCP — 골드 출력 재생성 스크립트 (v1.0 GA Step 1).

`tmp/v1_feasibility/regen_v0XX.py` 4개의 임시 패턴을 영구 통합한 단일 진입점.
6개 카테고리 회사 × 23개 MCP 도구를 호출해 `tests/fixtures/sample_outputs/`에
골드 파일을 생성한다. 기존 파일명 규칙을 그대로 유지해 하위 호환을 보장한다.

사용:
    python scripts/regen_goldens.py                      # 전체 재생성
    python scripts/regen_goldens.py --dry-run            # 호출 매트릭스만 출력
    python scripts/regen_goldens.py --companies 셀트리온 --tools capital
    python scripts/regen_goldens.py --quiet

API 키:
    1순위: tmp/_apikey.txt 파일
    2순위: 환경변수 DART_API_KEY

종료 코드: 1개 이상 도구 호출이 실패하면 비-0(CI 활용 가능).
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# API 키는 server import 전에 환경변수로 노출돼야 함
_APIKEY_FILE = ROOT / "tmp" / "_apikey.txt"
if _APIKEY_FILE.exists():
    os.environ["DART_API_KEY"] = _APIKEY_FILE.read_text(encoding="utf-8").strip()
elif not os.environ.get("DART_API_KEY"):
    sys.stderr.write(
        "ERROR: DART_API_KEY 미설정. tmp/_apikey.txt 또는 환경변수로 지정.\n"
    )
    sys.exit(2)

from dart_risk_mcp.core.dart_client import (  # noqa: E402
    fetch_company_disclosures,
    fetch_major_decision,
    resolve_corp,
    resolve_decision_type,
)
from dart_risk_mcp.core.qualifiers import parse_report_name  # noqa: E402
from dart_risk_mcp.core.signals import is_amendment_disclosure  # noqa: E402
from dart_risk_mcp.server import (  # noqa: E402
    analyze_company_risk,
    build_event_timeline,
    check_disclosure_anomaly,
    check_disclosure_risk,
    compare_financials,
    find_actor_overlap,
    find_risk_precedents,
    get_audit_opinion_history,
    get_affiliate_investments,
    get_company_info,
    get_disclosure_document,
    get_executive_compensation,
    get_financial_summary,
    get_major_decision,
    get_shareholder_info,
    list_disclosure_sections,
    list_disclosures_by_stock,
    scan_financial_anomaly,
    search_market_disclosures,
    track_capital_structure,
    track_debt_balance,
    track_fund_usage,
    track_insider_trading,
    view_disclosure,
)

GOLDEN = ROOT / "tests" / "fixtures" / "sample_outputs"

# ────────────────────────────────────────────────────────────────────────────
# 6개 대상 회사 (iridescent plan 라인 211, 사용자 승인 2026-04-26)
# ────────────────────────────────────────────────────────────────────────────
COMPANIES = [
    {"name": "셀트리온",       "stock": "068270", "category": "대형주(코스피·바이오)"},
    {"name": "제이스코홀딩스", "stock": "019660", "category": "중소형(코스닥·위험사례)"},
    {"name": "두산에너빌리티", "stock": "034020", "category": "대형자회사(채무풍부)"},
    {"name": "삼성전자",       "stock": "005930", "category": "대형주표준(대용량)"},
    {"name": "헬릭스미스",     "stock": "084990", "category": "관리종목·부실사례"},
    {"name": "두산",           "stock": "000150", "category": "지주사"},
    {"name": "아틀라스링크",   "stock": "297570", "category": "무자본M&A실증(자금역류)"},
    {"name": "STX",            "stock": "011810", "category": "회생절차실증(DISTRESS_EVENT)"},
    {"name": "나이스정보통신", "stock": "036800", "category": "자사주신탁실증(TREASURY_TRUST)"},
    {"name": "오르비텍",       "stock": "046120", "category": "자금사용미보고실증(FUND_UNREPORTED)"},
]

# ────────────────────────────────────────────────────────────────────────────
# A. 회사명 단일 인자 14개 도구 — (단축명, 호출 함수)
# 단축명은 기존 골드 파일 호환을 위해 변경 금지.
# ────────────────────────────────────────────────────────────────────────────
COMPANY_TOOL_MATRIX: list[tuple[str, Callable[[dict], str]]] = [
    ("analyze",       lambda c: analyze_company_risk(c["name"], 1)),
    ("timeline",      lambda c: build_event_timeline(c["name"], 1)),
    ("company_info",  lambda c: get_company_info(c["name"])),
    ("fs",            lambda c: get_financial_summary(c["name"], "2024", "annual")),
    ("shareholder",   lambda c: get_shareholder_info(c["name"], "2024")),
    ("exec_comp",     lambda c: get_executive_compensation(c["name"], "2024", "annual")),
    ("insider",       lambda c: track_insider_trading(c["name"], 2)),
    ("audit_history", lambda c: get_audit_opinion_history(c["name"], 5)),
    ("debt_balance",  lambda c: track_debt_balance(c["name"], "2024")),
    ("anomaly",       lambda c: check_disclosure_anomaly(c["name"], 1)),
    ("fund_usage",    lambda c: track_fund_usage(c["name"], 3)),
    ("scan_fs",       lambda c: scan_financial_anomaly(c["name"], "2024", "annual")),
    ("capital",       lambda c: track_capital_structure(c["name"], 3)),
    ("affiliates",    lambda c: get_affiliate_investments(c["name"], "2024")),
]

# B. 종목코드 인자 1개 도구
STOCK_TOOL = ("list", lambda c: list_disclosures_by_stock(c["stock"], 1))

# C. rcept_no 인자 4개 도구 — 회사별 첫 정상 공시 rcept를 자동 추출
RCEPT_TOOLS: list[tuple[str, Callable[[str], str]]] = [
    ("risk_check",    lambda r: check_disclosure_risk(r, "")),
    ("doc",           lambda r: get_disclosure_document(r, 8000)),
    ("sections",      lambda r: list_disclosure_sections(r)),
    ("view",          lambda r: view_disclosure(r, "", 1, 4000)),
]

# D. 회사 다중·DS005
MULTI_TOOLS: list[tuple[str, Callable[[list[dict]], str]]] = [
    # find_actor_overlap은 2~5개만 받는다. COMPANIES가 10개로 늘어난 뒤
    # (438831d 이후) 전체를 넘겨 "입력 오류"만 저장되고 있었다 — 전수
    # 재생성을 돌리지 않아 낡은 골드가 그대로 남아 드러나지 않았다.
    ("actor_overlap", lambda cs: find_actor_overlap([c["name"] for c in cs][:5])),
    # compare_financials도 최대 5개 — actor_overlap과 같은 이유로 잘라 넘긴다.
    ("compare_fs",    lambda cs: compare_financials([c["name"] for c in cs][:5], "2024")),
]

# DS005 자동 탐지용 키워드 — 실제 report_nm에서 검색(공백 없는 실제 표기
# 기준. resolve_decision_type의 _DECISION_NAME_MAP과 동일 표기).
DS005_KEYWORDS = [
    "타법인주식및출자증권양수", "타법인주식및출자증권양도",
    "합병결정", "분할결정", "분할합병결정",
    "영업양수", "영업양도", "주식교환", "주식이전",
    "유형자산양수", "유형자산양도",
]

# E. 회사 무관 프리셋 도구
PRECEDENT_KEY_SETS = [
    ["CB_BW", "3PCA", "SHAREHOLDER"],          # 기존 호환
    ["INSOLVENCY", "GOING_CONCERN", "AUDIT"],
    ["REVERSE_SPLIT", "GAMJA_MERGE", "EXEC"],
]

MARKET_PRESETS = [
    "cb_issue", "treasury", "going_concern", "all_risk",  # v1.0.0~v1.0.2 검증
    "reverse_split", "3pca", "shareholder_change", "exec_change",
    "audit_issue", "asset_transfer", "embezzle", "inquiry",  # v1.0.3 신규 검증 8개
    "fund_outflow",  # v1.6.0 신규
    "delisting",  # v1.12.2 신규
]


# ────────────────────────────────────────────────────────────────────────────
# 유틸리티
# ────────────────────────────────────────────────────────────────────────────
def _short_names() -> set[str]:
    """모든 단축명 집합 (--tools 검증용)."""
    s = {t[0] for t in COMPANY_TOOL_MATRIX}
    s.add(STOCK_TOOL[0])
    s.update(t[0] for t in RCEPT_TOOLS)
    s.update(t[0] for t in MULTI_TOOLS)
    s.add("precedents")
    s.add("market")
    s.add("decision")  # DS005 (자동 탐지)
    return s


def _resolve_first_normal_rcept(company: dict, api_key: str) -> str | None:
    """회사의 최근 90일 공시 중 정정공시가 아닌 첫 1건의 rcept_no를 반환."""
    corp = resolve_corp(company["name"], api_key)
    if not corp or not corp[1]:
        return None
    corp_code = corp[1].get("corp_code")
    if not corp_code:
        return None
    discs = fetch_company_disclosures(corp_code, api_key, 90)
    for d in discs:
        if not is_amendment_disclosure(d.get("report_nm", "")):
            rcept = d.get("rcept_no", "").strip()
            if rcept and rcept.isdigit() and len(rcept) >= 10:
                return rcept
    return None


_DS005_MAX_VERIFY_ATTEMPTS = 5


def _detect_ds005_rcept(company: dict, api_key: str) -> tuple[str, str, str] | None:
    """analyze 출력에는 rcept가 없으므로 fetch_company_disclosures에서 직접 키워드 매칭.

    (rcept_no, report_nm, corp_code)를 반환한다 — report_nm은 호출부에서
    resolve_decision_type으로 decision_type을 결정하는 데 쓰인다.

    이전에는 키워드가 매칭된 첫 제목을 검증 없이 그대로 반환했는데, 실측으로
    세 가지 방식으로 깨지는 게 확인됐다:

      A. 부분 문자열 충돌 — DS005_KEYWORDS의 "분할결정"이 "주식분할결정"
         (액면분할 — 회사 조직 분할이 아니고 DS005 공시도 아님)에도 걸린다.
         나이스정보통신 실측: 이 제목이 뽑히고 resolve_decision_type()이
         ''을 반환해 골드가 "❌ decision_type 미지정…" 에러 문자열이 됐다.
      B. 정정 필터 공백 — is_amendment_disclosure는 "기재정정|첨부추가|정정"만
         잡고 "[첨부정정]"을 놓친다(_AMENDMENT_RE는 신호 한정층이 별도로
         처리하는 프로젝트 결정이라 여기서 고치지 않는다). DS005 엔드포인트는
         최초접수일 기준으로 색인되므로, 정정본 자신의 rcept_no로는 그 사안을
         절대 찾을 수 없다. 두산 실측: "[첨부정정]주요사항보고서(…)"가 뽑혀
         조회가 항상 실패했다.
      C. 무마커 재제출 — 대괄호 태그가 전혀 없는, 바이트까지 동일한 제목이
         같은 사안을 날짜만 바꿔 두 번 접수되기도 한다(아틀라스링크
         "주요사항보고서(유형자산양수결정)" 20260722000373 vs 20260810000747
         실측 — 둘 다 rm=''). report_nm·rm 어느 필드로도 구분할 수 없다 —
         실제로 조회해 봐야 어느 쪽이 최초접수일인지 알 수 있다.

    수정:
      1) resolve_decision_type(nm)이 실제로 값을 반환하는 제목만 후보로
         인정한다(A 해결) — 키워드 사전 필터는 그대로 두되(값싼 좁히기),
         최종 판단 권한은 resolve_decision_type에 둔다.
      2) parse_report_name(nm).tags가 하나라도 있는 제목은 전부 건너뛴다
         (B 해결). 재제출본은 태그 종류를 가리지 않고 원본과 다른 rcept_no를
         가지므로, is_amendment_disclosure보다 엄격하게 넓혀야 한다 — 이
         기준이 기존 is_amendment_disclosure 필터를 포함하므로 별도 호출은
         제거했다(중복이라 유지할 이유가 없다).
      3) 후보를 최신순으로 최대 _DS005_MAX_VERIFY_ATTEMPTS건까지 실제
         fetch_major_decision으로 검증해, {"error": ...}가 아닌 첫 결과를
         채택한다(C 해결 — 구분 필드가 없으니 시도해서 확인). 기각된 후보는
         stderr에 사유를 남겨 다음 실행에서 재현 가능하게 한다.
    """
    corp = resolve_corp(company["name"], api_key)
    if not corp or not corp[1]:
        return None
    corp_code = corp[1].get("corp_code")
    if not corp_code:
        return None
    discs = fetch_company_disclosures(corp_code, api_key, 365)  # 최신순

    candidates: list[tuple[str, str]] = []  # (rcept_no, report_nm), 최신순 유지
    for d in discs:
        nm = d.get("report_nm", "")
        if parse_report_name(nm).tags:
            continue
        if not any(kw in nm for kw in DS005_KEYWORDS):
            continue
        if not resolve_decision_type(nm):
            continue
        rcept = d.get("rcept_no", "").strip()
        if rcept:
            candidates.append((rcept, nm))

    for rcept, nm in candidates[:_DS005_MAX_VERIFY_ATTEMPTS]:
        dtype = resolve_decision_type(nm)
        result = fetch_major_decision(rcept, api_key, dtype, corp_code)
        if isinstance(result, dict) and result.get("error"):
            sys.stderr.write(
                f"  DS005 후보 기각: {company['name']} {rcept} ({nm}) — {result['error']}\n"
            )
            continue
        return rcept, nm, corp_code

    return None


def _save(path: Path, content: str, *, quiet: bool, idx: int, total: int, label: str) -> bool:
    """공통 저장 헬퍼. 빈 응답·예외는 False 반환."""
    if not content or not content.strip():
        sys.stderr.write(f"  WARN: {label} 빈 응답 — 파일 미생성\n")
        return False
    path.write_text(content, encoding="utf-8")
    if not quiet:
        print(f"[{idx}/{total}] {label} → {path.name} ({len(content)} chars)")
    return True


def _safe_call(fn: Callable[[], str], label: str) -> str:
    """도구 호출 실패를 캡처해 stderr로 보내고 빈 문자열 반환."""
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write(f"  ERROR {label}: {type(exc).__name__}: {exc}\n")
        return ""


# ────────────────────────────────────────────────────────────────────────────
# 매트릭스 빌더 (dry-run·실행 공통)
# ────────────────────────────────────────────────────────────────────────────
def build_call_matrix(
    companies: list[dict],
    tool_filter: set[str] | None,
    api_key: str,
) -> list[tuple[str, Callable[[], str], Path]]:
    """(label, callable, output_path) 튜플 목록을 반환."""
    calls: list[tuple[str, Callable[[], str], Path]] = []

    # A. 회사명 단일 인자 13개 × N
    for c in companies:
        for short, fn in COMPANY_TOOL_MATRIX:
            if tool_filter and short not in tool_filter:
                continue
            label = f"{c['name']} {short}"
            path = GOLDEN / f"{c['name']}_{short}.txt"
            calls.append((label, (lambda fn=fn, c=c: fn(c)), path))

    # B. 종목코드 1개
    short, fn = STOCK_TOOL
    if not tool_filter or short in tool_filter:
        for c in companies:
            label = f"{c['name']} {short}"
            path = GOLDEN / f"{c['name']}_{short}.txt"
            calls.append((label, (lambda fn=fn, c=c: fn(c)), path))

    # C. rcept 4개 (회사별 자동 추출 후 4 도구 동일 rcept 사용)
    rcept_filtered = [t for t in RCEPT_TOOLS if not tool_filter or t[0] in tool_filter]
    if rcept_filtered:
        for c in companies:
            rcept = _resolve_first_normal_rcept(c, api_key)
            if not rcept:
                sys.stderr.write(f"  SKIP rcept 도구 4종: {c['name']} 정상 공시 없음\n")
                continue
            for short, fn in rcept_filtered:
                label = f"{c['name']} {short}_{rcept}"
                path = GOLDEN / f"{c['name']}_{short}_{rcept}.txt"
                calls.append((label, (lambda fn=fn, r=rcept: fn(r)), path))

    # D-1. 회사 다중 (actor_overlap·compare_fs) — 한 번씩만
    for short, fn in MULTI_TOOLS:
        if tool_filter and short not in tool_filter:
            continue
        if len(companies) < 2:
            continue
        label = short
        path = GOLDEN / f"{short}.txt"
        calls.append((label, (lambda fn=fn, cs=companies: fn(cs)), path))

    # D-2. DS005 자동 탐지
    if not tool_filter or "decision" in tool_filter:
        for c in companies:
            found = _detect_ds005_rcept(c, api_key)
            if not found:
                sys.stderr.write(f"  SKIP DS005: {c['name']} 주요결정 공시 미발견\n")
                continue
            rcept, report_nm, corp_code = found
            dtype = resolve_decision_type(report_nm)
            label = f"{c['name']} decision_{rcept}"
            path = GOLDEN / f"{c['name']}_decision_{rcept}.txt"
            calls.append((
                label,
                (lambda r=rcept, dt=dtype, cc=corp_code: get_major_decision(r, dt, cc)),
                path,
            ))

    # E-1. find_risk_precedents (회사 무관)
    if not tool_filter or "precedents" in tool_filter:
        for keys in PRECEDENT_KEY_SETS:
            label = f"precedents {'_'.join(keys)}"
            path = GOLDEN / f"precedents_{'_'.join(keys)}.txt"
            calls.append((
                label,
                (lambda k=keys: find_risk_precedents(k, 90)),
                path,
            ))

    # E-2. search_market_disclosures (preset별)
    if not tool_filter or "market" in tool_filter:
        for preset in MARKET_PRESETS:
            label = f"market {preset}"
            path = GOLDEN / f"market_{preset}.txt"
            calls.append((
                label,
                (lambda p=preset: search_market_disclosures(p, 7, 50)),
                path,
            ))

    return calls


# ────────────────────────────────────────────────────────────────────────────
# 진입점
# ────────────────────────────────────────────────────────────────────────────
def main() -> int:
    parser = argparse.ArgumentParser(
        description="DART Risk MCP 골드 출력 재생성 (6 회사 × 23 도구)",
    )
    parser.add_argument(
        "--companies", nargs="*",
        help=f"대상 회사명. 미지정 시 6개 전체. 가능: {[c['name'] for c in COMPANIES]}",
    )
    parser.add_argument(
        "--tools", nargs="*",
        help=f"대상 단축명. 미지정 시 전체. 가능: {sorted(_short_names())}",
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="호출 매트릭스만 출력, 파일 쓰지 않음")
    parser.add_argument("--quiet", action="store_true",
                        help="진행 라인 억제, 요약만 출력")
    args = parser.parse_args()

    # 회사 필터
    if args.companies:
        unknown = set(args.companies) - {c["name"] for c in COMPANIES}
        if unknown:
            sys.stderr.write(f"ERROR: 알 수 없는 회사: {unknown}\n")
            return 2
        companies = [c for c in COMPANIES if c["name"] in args.companies]
    else:
        companies = COMPANIES

    # 도구 필터
    tool_filter: set[str] | None = None
    if args.tools:
        valid = _short_names()
        unknown = set(args.tools) - valid
        if unknown:
            sys.stderr.write(f"ERROR: 알 수 없는 단축명: {unknown}\n")
            sys.stderr.write(f"가능: {sorted(valid)}\n")
            return 2
        tool_filter = set(args.tools)

    api_key = os.environ["DART_API_KEY"]
    GOLDEN.mkdir(parents=True, exist_ok=True)

    calls = build_call_matrix(companies, tool_filter, api_key)
    total = len(calls)

    if args.dry_run:
        print(f"# 호출 매트릭스 ({total}건)")
        for label, _, path in calls:
            print(f"  {label}  →  {path.name}")
        return 0

    saved = 0
    failed = 0
    for idx, (label, fn, path) in enumerate(calls, 1):
        out = _safe_call(fn, label)
        if _save(path, out, quiet=args.quiet, idx=idx, total=total, label=label):
            saved += 1
        else:
            failed += 1

    fixture_count = len(list(GOLDEN.glob("*.txt")))
    print(
        f"\n=== 완료: 저장 {saved} / 실패 {failed} / 매트릭스 {total} | "
        f"fixtures 디렉토리 총 {fixture_count}개 ==="
    )

    # 헬릭스미스 부실 라인 자동 검수 (시각 확인용)
    helix_analyze = GOLDEN / "헬릭스미스_analyze.txt"
    if helix_analyze.exists():
        text = helix_analyze.read_text(encoding="utf-8")
        markers = [m for m in ("GOING_CONCERN", "8.4", "부실 단계", "회생절차", "감사범위제한") if m in text]
        # cp949 콘솔 크래시 전례(CLAUDE.md) — 비ASCII 구분자(—·이모지) 금지
        if markers:
            print(f"  [OK] 헬릭스미스 부실 흔적: {markers}")
        else:
            print("  [WARN] 헬릭스미스 analyze에 부실 흔적 없음 - 검수 필요")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
