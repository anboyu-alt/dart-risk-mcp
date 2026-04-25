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
    resolve_corp,
)
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
]

# ────────────────────────────────────────────────────────────────────────────
# A. 회사명 단일 인자 13개 도구 — (단축명, 호출 함수)
# 단축명은 기존 골드 파일 호환을 위해 변경 금지.
# ────────────────────────────────────────────────────────────────────────────
COMPANY_TOOL_MATRIX: list[tuple[str, Callable[[dict], str]]] = [
    ("analyze",       lambda c: analyze_company_risk(c["name"], 365)),
    ("timeline",      lambda c: build_event_timeline(c["name"], 365)),
    ("company_info",  lambda c: get_company_info(c["name"])),
    ("fs",            lambda c: get_financial_summary(c["name"], "2024", "annual")),
    ("shareholder",   lambda c: get_shareholder_info(c["name"], "2024")),
    ("exec_comp",     lambda c: get_executive_compensation(c["name"], "2024", "annual")),
    ("insider",       lambda c: track_insider_trading(c["name"], 2)),
    ("audit_history", lambda c: get_audit_opinion_history(c["name"], 5)),
    ("debt_balance",  lambda c: track_debt_balance(c["name"], "2024")),
    ("anomaly",       lambda c: check_disclosure_anomaly(c["name"], 365)),
    ("fund_usage",    lambda c: track_fund_usage(c["name"], 3)),
    ("scan_fs",       lambda c: scan_financial_anomaly(c["name"], "2024", "annual")),
    ("capital",       lambda c: track_capital_structure(c["name"], 3)),
]

# B. 종목코드 인자 1개 도구
STOCK_TOOL = ("list", lambda c: list_disclosures_by_stock(c["stock"], 90))

# C. rcept_no 인자 4개 도구 — 회사별 첫 정상 공시 rcept를 자동 추출
RCEPT_TOOLS: list[tuple[str, Callable[[str], str]]] = [
    ("risk_check",    lambda r: check_disclosure_risk(r, "")),
    ("doc",           lambda r: get_disclosure_document(r, 8000)),
    ("sections",      lambda r: list_disclosure_sections(r)),
    ("view",          lambda r: view_disclosure(r, "", 1, 4000)),
]

# D. 회사 다중·DS005
MULTI_TOOLS: list[tuple[str, Callable[[list[dict]], str]]] = [
    ("actor_overlap", lambda cs: find_actor_overlap([c["name"] for c in cs])),
    ("compare_fs",    lambda cs: compare_financials([c["name"] for c in cs], "2024")),
]

# DS005 자동 탐지용 키워드 (analyze 출력에서 검색)
DS005_KEYWORDS = [
    "타법인주식 양수", "타법인주식 양도",
    "합병결정", "분할결정", "분할합병결정",
    "영업양수", "영업양도", "주식교환", "주식이전",
    "유형자산 양수", "유형자산 양도",
]

# E. 회사 무관 프리셋 도구
PRECEDENT_KEY_SETS = [
    ["CB_BW", "3PCA", "SHAREHOLDER"],          # 기존 호환
    ["INSOLVENCY", "GOING_CONCERN", "AUDIT"],
    ["REVERSE_SPLIT", "GAMJA_MERGE", "EXEC"],
]

MARKET_PRESETS = ["cb_issue", "treasury", "going_concern", "all_risk"]


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


def _detect_ds005_rcept(company: dict, api_key: str) -> str | None:
    """analyze 출력에는 rcept가 없으므로 fetch_company_disclosures에서 직접 키워드 매칭."""
    corp = resolve_corp(company["name"], api_key)
    if not corp or not corp[1]:
        return None
    corp_code = corp[1].get("corp_code")
    if not corp_code:
        return None
    discs = fetch_company_disclosures(corp_code, api_key, 365)
    for d in discs:
        nm = d.get("report_nm", "")
        if is_amendment_disclosure(nm):
            continue
        if any(kw in nm for kw in DS005_KEYWORDS):
            rcept = d.get("rcept_no", "").strip()
            if rcept:
                return rcept
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
            rcept = _detect_ds005_rcept(c, api_key)
            if not rcept:
                sys.stderr.write(f"  SKIP DS005: {c['name']} 주요결정 공시 미발견\n")
                continue
            label = f"{c['name']} decision_{rcept}"
            path = GOLDEN / f"{c['name']}_decision_{rcept}.txt"
            calls.append((
                label,
                (lambda r=rcept: get_major_decision(r, "", "")),
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
        if markers:
            print(f"  ✓ 헬릭스미스 부실 흔적: {markers}")
        else:
            print("  ! 헬릭스미스 analyze에 부실 흔적 없음 — 검수 필요")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
