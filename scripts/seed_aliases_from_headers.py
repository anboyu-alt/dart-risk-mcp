# -*- coding: utf-8 -*-
"""공시 원문 헤더 상호 대조 → 전 시장(코스피 포함) 개명 소급 시딩 (1회성).

## 왜 필요한가

docs/tool/corp-aliases.json은 지금까지 '상호변경안내' 공시 백필
(scripts/backfill_corp_aliases.py)로 채웠는데, 그 서식은 **코스닥만** 낸다 —
코스피(유가증권)는 이 서식 자체를 DART에 내지 않는다(한화오션 2023-04~08
공시 62건 실측: 상호 관련 공시 0건). 그래서 "대우조선해양 → 한화오션" 같은
코스피 개명은 백필 경로로는 영원히 못 잡는다.

DART list.json은 과거 공시를 조회해도 접수 당시 상호가 아니라 **현재** 상호로
표기한다(실측) — 목록만 봐서는 그 공시가 옛 이름 시절에 나갔는지 알 수 없다.
하지만 공시 **원문 ZIP**에는 제출 당시 상호가 헤더에 그대로 박제돼 있다:

    대우조선해양/단일판매ㆍ공급계약체결/(2023.03.14)단일판매ㆍ공급계약체결

(rcept_no 20230314800431, fetch_document_text 태그 제거 후 원문 그대로 —
현재 사명은 '한화오션'이므로 이 헤더 자체가 개명의 증거다.)

## 원리

corp-map.json(현재 3,810개 상장사) 각각에 대해:
  1. list.json(corp_code, bgn_de, end_de, sort_mth=asc)으로 윈도우 내 가장
     오래된 공시 1건을 고른다(ZIP이 큰 정기보고서는 피함 — pick_seed_disclosure).
  2. 그 공시의 원문 헤더에서 회사명을 파싱한다(parse_header_corp_name).
  3. 법인 표기 제거 후 현재 이름과 다르면 개명 레코드로 채택한다.

기업당 정확히 2콜(list 1 + document 1)이라 3,810개 전체를 훑어도
~7,600콜로 끝난다. **1회성** 스크립트다 — 이후의 개명은
scripts/build_corp_map.py(corpCode.xml diff, 매주 자동)가 앞으로의 몫을
계속 잡아준다. 이 스크립트가 메우는 건 "과거, corp-map.json이 이미 최신
이름을 담고 있어 diff가 안 남는 구간"뿐이다.

## 사용

    python scripts/seed_aliases_from_headers.py --dry-run --limit 30
    python scripts/seed_aliases_from_headers.py --from 20230801 --to 20260801

환경: DART_API_KEY(우선) 또는 tmp/_apikey.txt. 키를 로그에 남기지 않는다.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dart_risk_mcp.core.dart_client import (  # noqa: E402
    DART_BASE,
    _retry,
    fetch_document_text,
)
from dart_risk_mcp.core.signals import strip_amendment_prefix  # noqa: E402
from scripts.backfill_corp_aliases import (  # noqa: E402
    is_valid_alias_record,
    merge_backfill_records,
    strip_corp_form,
)

DOCS_TOOL = ROOT / "docs" / "tool"
CORP_MAP_PATH = DOCS_TOOL / "corp-map.json"
ALIASES_PATH = DOCS_TOOL / "corp-aliases.json"

SAVE_EVERY = 500     # 중간 저장 주기(기업 수) — 장시간 실행 타임아웃 대비
LOG_EVERY = 200       # 진행 로그 주기(기업 수)

# 원문 헤더 '회사명/보고서명/(YYYY.MM.DD)…' 구조. fetch_document_text가 태그를
# 지우고 공백을 단일화한 뒤라도 슬래시(/)는 원문 그대로 남는다(실측 확인).
_HEADER_RE = re.compile(
    r"(?P<corp>[^/\s][^/]{0,49}?)/(?P<report>[^/]{1,80}?)/\(\d{4}\.\d{2}\.\d{2}\)")

# ZIP이 큰 정기보고서 — 소급 시딩에서 피하는 대상(그 외 유형 중 가장 오래된 것 우선)
_PERIODIC_RE = re.compile(r"사업보고서|반기보고서|분기보고서|감사보고서")


def _norm_ws(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def parse_header_corp_name(text: str, report_nm: str) -> str:
    """공시 원문 헤더에서 '회사명/보고서명/(날짜)' 패턴을 찾아 회사명을 반환한다.

    report_nm(list.json의 공시명)과 헤더 내 보고서명을 공백 정규화 후
    전방 일치로 검증해 본문 중 우연한 '/' 나열을 오탐하지 않게 한다.
    report_nm이 정정공시 접두사([기재정정] 등)를 달고 있으면 원 제목 기준으로
    비교한다(원문 헤더에는 접두사가 안 붙는 경우가 실측상 대부분이라).
    불일치·헤더 미검출 시 빈 문자열을 반환한다(순수 함수).
    """
    if not text or not report_nm:
        return ""
    list_norm = _norm_ws(strip_amendment_prefix(report_nm)) or _norm_ws(report_nm)
    if not list_norm:
        return ""

    # 원문 앞부분의 CSS 서문(태그 제거 후에도 텍스트로 남음)이 500자를 훌쩍
    # 넘는 문서가 많아 탐색 범위를 넉넉히 잡는다 — 1차 실행에서 500자 제한이
    # 헤더 미검출 45%의 주원인이었다(2026-08-01 실측).
    for m in _HEADER_RE.finditer(text[:4000]):
        corp = m.group("corp").strip()
        if not corp or len(corp) < 2 or len(corp) > 50:
            continue
        header_report = _norm_ws(m.group("report"))
        if not header_report:
            continue
        if header_report.startswith(list_norm) or list_norm.startswith(header_report):
            return corp
    return ""


def pick_seed_disclosures(disclosures: list[dict], limit: int = 4) -> list[dict]:
    """윈도우 내 공시 목록에서 시딩용 후보 공시를 오래된 순으로 최대 limit건 고른다.

    가장 오래된 것부터(rcept_dt 오름차순, 동률은 rcept_no로) ZIP이 큰
    정기보고서(사업/반기/분기보고서·감사보고서)가 아닌 것을 우선 채우고,
    부족하면 정기보고서로 보충한다. 입력 목록의 정렬 순서를 신뢰하지 않고
    이 함수 내부에서 다시 정렬한다.

    후보를 여러 건 주는 이유(1차 실행 실측): '임원ㆍ주요주주특정증권등
    소유상황보고서'류는 '회사명/보고서명/(날짜)' 슬래시 헤더가 없는 별도
    서식이라, 가장 오래된 1건만 보면 헤더 미검출이 49%에 달했다. 호출자는
    헤더가 파싱될 때까지 후보를 순서대로 시도한다.
    """
    if not disclosures:
        return []
    ordered = sorted(
        disclosures,
        key=lambda d: (d.get("rcept_dt") or "", d.get("rcept_no") or ""))
    non_periodic = [d for d in ordered if not _PERIODIC_RE.search(d.get("report_nm") or "")]
    periodic = [d for d in ordered if _PERIODIC_RE.search(d.get("report_nm") or "")]
    return (non_periodic + periodic)[:limit]


def pick_seed_disclosure(disclosures: list[dict]) -> dict | None:
    """기존 호환 래퍼 — 후보 중 첫 건 (테스트·진단용)."""
    picked = pick_seed_disclosures(disclosures, limit=1)
    return picked[0] if picked else None


def _api_key() -> str:
    key = os.environ.get("DART_API_KEY", "")
    if key:
        return key
    p = ROOT / "tmp" / "_apikey.txt"
    return p.read_text(encoding="utf-8").strip() if p.exists() else ""


def _load_json(path: Path, default):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default


def fetch_window_disclosures(corp_code: str, api_key: str, bgn_de: str, end_de: str,
                              page_count: int = 100) -> list[dict]:
    """corp_code의 윈도우 내 공시를 list.json 1콜로 조회한다(오래된 순 요청).

    sort_mth=asc로 요청해 윈도우 내 가장 오래된 page_count건을 우선 받는다
    (총 건수가 이보다 많아도, 우리가 원하는 "가장 오래된 것"은 이미 첫
    페이지 안에 있으므로 페이지네이션이 필요 없다).
    """
    if not api_key or not corp_code:
        return []
    params = {
        "crtfc_key": api_key,
        "corp_code": corp_code,
        "bgn_de": bgn_de,
        "end_de": end_de,
        "page_no": 1,
        "page_count": page_count,
        "sort": "date",
        "sort_mth": "asc",
    }
    try:
        data = _retry("GET", f"{DART_BASE}/list.json", params=params).json()
    except Exception:
        return []
    if data.get("status") != "000":
        return []
    return data.get("list", []) or []


def _print_ascii(line: str) -> None:
    """Windows 콘솔(cp949)에서 인코딩 불가 문자가 print를 죽이지 않게 한다."""
    enc = sys.stdout.encoding or "utf-8"
    print(line.encode(enc, errors="replace").decode(enc))


def run_seed(api_key: str, corp_map: dict, bgn_de: str, end_de: str,
             sleep_s: float = 0.12):
    """corp_map(현재 이름 → [corp_code, stock_code]) 전체를 순회해 개명 레코드를 모은다.

    제너레이터 — SAVE_EVERY 기업마다 (그 구간에서 새로 발견한 레코드 목록,
    누적 통계 dict)를 yield한다. 호출자가 매 체크포인트마다 중간 저장할 수
    있게(장시간 실행 타임아웃 대비) 하기 위함이다.
    """
    records: list[dict] = []
    stats = {
        "target": len(corp_map), "no_disclosure": 0, "no_header": 0,
        "errors": 0, "invalid": 0, "renamed": 0,
    }
    names = sorted(corp_map)
    checkpoint_start = 0
    for i, name in enumerate(names, 1):
        entry = corp_map[name]  # corp-map.json 형식: [corp_code, stock_code]
        corp_code = entry[0] if entry else ""
        stock_code = entry[1] if len(entry) > 1 else ""
        if not corp_code:
            stats["no_disclosure"] += 1
            continue

        discs = fetch_window_disclosures(corp_code, api_key, bgn_de, end_de)
        candidates = pick_seed_disclosures(discs)
        if not candidates:
            stats["no_disclosure"] += 1
        else:
            # 헤더가 파싱될 때까지 후보를 오래된 순으로 시도 — 소유상황보고서류
            # (슬래시 헤더 없는 서식)가 첫 후보인 기업의 미검출을 줄인다.
            header_name, chosen = "", candidates[0]
            for cand in candidates:
                rcept_no = cand.get("rcept_no", "")
                report_nm = cand.get("report_nm", "") or ""
                try:
                    txt = fetch_document_text(rcept_no, api_key, max_chars=6000) if rcept_no else ""
                except Exception:
                    txt = ""
                    stats["errors"] += 1
                time.sleep(sleep_s)
                header_name = parse_header_corp_name(txt, report_nm) if txt else ""
                if header_name:
                    chosen = cand
                    break

            rcept_no = chosen.get("rcept_no", "")
            if not header_name:
                stats["no_header"] += 1
            else:
                old = strip_corp_form(header_name)
                new = strip_corp_form(name)
                if old and old != new:
                    if is_valid_alias_record(old, new):
                        rdt = chosen.get("rcept_dt", "") or ""
                        date = f"{rdt[:4]}-{rdt[4:6]}-{rdt[6:8]}" if len(rdt) >= 8 else rdt
                        records.append({
                            "old_name": old, "new_name": new,
                            "corp_code": corp_code, "stock_code": stock_code,
                            "rcept_no": rcept_no, "date": date,
                        })
                        stats["renamed"] += 1
                    else:
                        stats["invalid"] += 1

        if i % LOG_EVERY == 0 or i == len(names):
            # ASCII 구분자만 사용 — 비ASCII 구분자(—, · 등)는 cp949 콘솔/파이프에서
            # UnicodeEncodeError로 프로세스를 통째로 죽인 전례가 있다.
            _print_ascii(f"[진행] {i}/{len(names)} | 개명 발견 {stats['renamed']}건 | "
                         f"헤더미검출 {stats['no_header']} | 공시없음 {stats['no_disclosure']} | "
                         f"오류 {stats['errors']} | 무효 {stats['invalid']}")

        if i % SAVE_EVERY == 0 or i == len(names):
            stats["_checkpoint_at"] = i
            yield records[checkpoint_start:], dict(stats)
            checkpoint_start = len(records)


def main():
    ap = argparse.ArgumentParser(
        description="공시 원문 헤더 상호 대조 — 전 시장 개명 소급 시딩 (1회성)")
    ap.add_argument("--from", dest="from_date", default="",
                     help="YYYYMMDD (기본: 3년 전)")
    ap.add_argument("--to", dest="to_date", default="", help="YYYYMMDD (기본: 오늘)")
    ap.add_argument("--limit", type=int, default=0, help="테스트용 앞 N개 기업만 처리")
    ap.add_argument("--start-after", default="",
                     help="이 이름(정렬 기준) 뒤부터 처리 — 중단된 실행 재개용")
    ap.add_argument("--dry-run", action="store_true", help="저장 없이 통계만 출력")
    args = ap.parse_args()

    # stdout이 콘솔이든 파일 리다이렉트든 utf-8로 강제 — Windows 기본 cp949가
    # 특수문자(예: em dash) 출력에서 UnicodeEncodeError로 장시간 실행을 죽인
    # 전례(2026-08-01 1차 시딩 실행 중단)에 대한 근본 방어.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    except Exception:
        pass

    key = _api_key()
    if not key:
        raise SystemExit("DART_API_KEY 또는 tmp/_apikey.txt 필요")

    end = datetime.strptime(args.to_date, "%Y%m%d") if args.to_date else datetime.now()
    start = (datetime.strptime(args.from_date, "%Y%m%d") if args.from_date
             else end - timedelta(days=365 * 3))
    bgn_de, end_de = start.strftime("%Y%m%d"), end.strftime("%Y%m%d")

    corp_map = _load_json(CORP_MAP_PATH, {})
    if not corp_map:
        raise SystemExit(f"{CORP_MAP_PATH} 비어있음 — build_corp_map.py 먼저 실행")
    if args.start_after:
        corp_map = {n: e for n, e in corp_map.items() if n > args.start_after}
    if args.limit > 0:
        corp_map = dict(list(sorted(corp_map.items()))[: args.limit])

    print(f"[START] 대상 기업 {len(corp_map)}곳 · 윈도우 {bgn_de}~{end_de}")

    existing = _load_json(ALIASES_PATH, {})
    removed = sorted(
        name for name, ent in existing.items()
        if not is_valid_alias_record(name, ent.get("current", "")))
    cleaned = {name: ent for name, ent in existing.items() if name not in set(removed)}
    if removed:
        print(f"[정리] 기존 별칭 중 쓰레기 {len(removed)}건 제거: {', '.join(removed)}")

    merged = dict(cleaned)
    last_stats: dict = {}
    for chunk_records, stats in run_seed(key, corp_map, bgn_de, end_de):
        last_stats = stats
        if args.dry_run:
            continue
        merged = merge_backfill_records(merged, chunk_records)
        DOCS_TOOL.mkdir(parents=True, exist_ok=True)
        ALIASES_PATH.write_text(
            json.dumps(merged, ensure_ascii=False, indent=1, sort_keys=True),
            encoding="utf-8")
        _print_ascii(f"    [중간저장] {stats.get('_checkpoint_at', '?')}/{len(corp_map)} "
                     f"시점 -> 별칭 {len(merged)}건")

    print(f"\n[SUMMARY] 대상 {last_stats.get('target', 0)} · "
          f"공시없음 {last_stats.get('no_disclosure', 0)} · "
          f"헤더미검출 {last_stats.get('no_header', 0)} · "
          f"오류 {last_stats.get('errors', 0)} · "
          f"무효 {last_stats.get('invalid', 0)} · "
          f"개명 발견 {last_stats.get('renamed', 0)}건")

    if args.dry_run:
        print("[dry-run] 저장 생략")
        return

    print(f"저장: {ALIASES_PATH} (별칭 {len(existing)}건 -> {len(merged)}건)")


if __name__ == "__main__":
    main()
