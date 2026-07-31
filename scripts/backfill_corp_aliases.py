# -*- coding: utf-8 -*-
"""'상호변경안내' 공시 백필 → 공개 리스크 뷰어 corp-aliases.json 별칭 시드.

DART corpCode.xml은 상호변경 시 옛 상호를 지우고 새 상호로 교체하므로, 스냅샷
1장(docs/tool/corp-map.json)만으로는 "그 사이"의 개명을 알 수 없다. 이 스크립트는
시장 전체 공시(corp_code 없이 /api/list.json)를 날짜 구간으로 스캔해 '상호변경안내'
공시를 찾고, 원문에서 변경전/후 국문 상호를 추출해 옛 상호 → 현재 상호 별칭을
docs/tool/corp-aliases.json에 append-only로 누적한다.

pblntf_ty 실측(2026-06-12, rcept_no 20260612900563 "주식회사 알로이스" →
"주식회사 아틀라스링크" 상호변경안내, 좁은 날짜 구간으로 직접 조회해 확인):
거래소공시 유형 'I'로 필터링해도 이 공시가 그대로 걸린다 — scripts/backfill_renames.py
(sightings 소급 개명 백필)가 이미 같은 사실에 의존하고 있어 그 전례를 그대로 재사용.

정규식 패턴도 backfill_renames.py의 라이브 검증된 패턴을 재사용한다. 이 스크립트는
그 결과를 (비공개 sightings가 아니라) **공개** corp-aliases.json에 적되, 법인 표기
(주식회사/㈜/(주))를 제거해 corp-map.json의 이름 표기(법인 표기 없는 bare name)와
맞춘다.

사용:
    python scripts/backfill_corp_aliases.py                        # 기본: 최근 7일
    python scripts/backfill_corp_aliases.py --from 20260601 --to 20260731
    python scripts/backfill_corp_aliases.py --dry-run

환경: DART_API_KEY(우선) 또는 tmp/_apikey.txt
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
    fetch_document_text,
    fetch_market_disclosures,
)

DOCS_TOOL = ROOT / "docs" / "tool"
ALIASES_PATH = DOCS_TOOL / "corp-aliases.json"

# '가. 변경전 국문 주식회사 알로이스 영문 ALOYS Inc. 나. 변경후 국문 …' 구조.
# scripts/backfill_renames.py(sightings 소급 개명 백필)와 동일 패턴 — 라이브 검증됨.
_BEFORE_RE = re.compile(
    r"변경\s*전\s*(?:국문)?\s*[:：]?\s*(.{2,60}?)\s*(?:영문|나\s*\.|변경\s*후)")
_AFTER_RE = re.compile(
    r"변경\s*후\s*(?:국문)?\s*[:：]?\s*(.{2,60}?)\s*(?:영문|\d\s*\.|변경\s*사유)")
# '과거 상호변경 내역: … 변경전: 한솔시큐어 주식회사 → 변경후: …'
_PAST_RE = re.compile(r"변경\s*전\s*[:：]\s*([^→\n)]{2,60}?)\s*→")

_CORP_PREFIX_RE = re.compile(r"^(?:주식회사|㈜|\(주\))\s*")
_CORP_SUFFIX_RE = re.compile(r"\s*(?:주식회사|㈜|\(주\))$")


def strip_corp_form(name: str) -> str:
    """법인 표기(주식회사/㈜/(주)) 접두·접미 제거 — corp-map.json 이름 표기와 일치시킨다."""
    name = (name or "").strip()
    name = _CORP_PREFIX_RE.sub("", name)
    name = _CORP_SUFFIX_RE.sub("", name)
    return name.strip()


def extract_renames_from_text(txt: str, fallback_after: str = "") -> tuple[set, str]:
    """공시 원문(태그 제거된 텍스트) → (옛 상호 집합, 새 상호). 법인 표기는 제거해서 반환.

    fallback_after: 원문에서 '변경후' 문구를 못 찾을 때 쓸 값(보통 공시 목록의
    현재 corp_name — 단, 이후 재개명됐다면 최신 이름일 수 있음).
    """
    olds = set()
    m = _BEFORE_RE.search(txt)
    if m:
        olds.add(m.group(1).strip())
    olds |= {x.strip() for x in _PAST_RE.findall(txt)}

    am = _AFTER_RE.search(txt)
    after_raw = am.group(1).strip() if am else (fallback_after or "")
    after = strip_corp_form(after_raw)

    olds_stripped = {strip_corp_form(o) for o in olds if o}
    olds_stripped = {o for o in olds_stripped if o and o != after}
    return olds_stripped, after


def _api_key() -> str:
    """DART API 키 로드 — 환경변수 우선, 없으면 tmp/_apikey.txt 폴백."""
    key = os.environ.get("DART_API_KEY", "")
    if key:
        return key
    p = ROOT / "tmp" / "_apikey.txt"
    return p.read_text(encoding="utf-8").strip() if p.exists() else ""


def _load_json(path: Path, default):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default


def collect_renames(api_key: str, start: datetime, end: datetime,
                     max_pages: int = 60, sleep_s: float = 0.15) -> tuple[list[dict], dict]:
    """구간 내 '상호변경안내' 공시를 스캔해 개명 레코드 목록을 추출한다.

    거래소공시(pblntf_ty='I')는 90일에 4,000건을 넘길 수 있어(페이지 상한)
    30일 청크로 순회한다(누락 방지). 반환: (레코드 목록, 통계 dict).
    각 레코드: {old_name, new_name, corp_code, stock_code, rcept_no, date}
    """
    records: list[dict] = []
    stats = {"scanned": 0, "candidates": 0, "extracted": 0, "no_match": 0, "errors": 0}
    cur = start
    while cur <= end:
        chunk_end = min(cur + timedelta(days=29), end)
        discs = fetch_market_disclosures(
            api_key, cur.strftime("%Y%m%d"), chunk_end.strftime("%Y%m%d"),
            pblntf_ty="I", max_pages=max_pages) or []
        stats["scanned"] += len(discs)
        hits = [d for d in discs if "상호변경" in (d.get("report_nm") or "")]
        stats["candidates"] += len(hits)

        for d in hits:
            rn, cc = d.get("rcept_no", ""), d.get("corp_code", "")
            if not rn or not cc:
                continue
            try:
                txt = fetch_document_text(rn, api_key, max_chars=3000) or ""
                olds, after = extract_renames_from_text(txt, d.get("corp_name", ""))
            except Exception:
                stats["errors"] += 1
                continue
            finally:
                time.sleep(sleep_s)

            if not olds or not after:
                stats["no_match"] += 1
                continue

            stock = d.get("stock_code", "") or ""
            rdt = d.get("rcept_dt", "") or ""
            date = f"{rdt[:4]}-{rdt[4:6]}-{rdt[6:8]}" if len(rdt) >= 8 else rdt
            for old in sorted(olds):
                records.append({
                    "old_name": old,
                    "new_name": after,
                    "corp_code": cc,
                    "stock_code": stock,
                    "rcept_no": rn,
                    "date": date,
                })
                stats["extracted"] += 1

        print(f"[{cur:%Y-%m-%d}~{chunk_end:%Y-%m-%d}] "
              f"공시 {len(discs)}건 중 상호변경안내 후보 {len(hits)}건")
        cur = chunk_end + timedelta(days=1)

    return records, stats


def merge_backfill_records(existing_aliases: dict, records: list[dict]) -> dict:
    """백필 레코드를 기존 별칭 맵에 append-only 병합한다 (순수 함수, 테스트 가능).

    같은 옛 상호가 다시 등장하면(중복 스캔 등) 최신 레코드로 갱신한다.
    레코드는 호출자가 시간순으로 넘기면 그 순서를 그대로 반영한다.
    """
    aliases = {name: dict(ent) for name, ent in existing_aliases.items()}
    for r in records:
        old, new = r.get("old_name", ""), r.get("new_name", "")
        if not old or not new or old == new:
            continue
        aliases[old] = {
            "corp_code": r.get("corp_code", ""),
            "stock_code": r.get("stock_code", ""),
            "current": new,
        }
    return aliases


def main():
    ap = argparse.ArgumentParser(
        description="상호변경안내 공시 백필 → corp-aliases.json 별칭 시드")
    ap.add_argument("--from", dest="from_date", default="",
                     help="YYYYMMDD (기본: 종료일-7일, 주간 워크플로우 증분용)")
    ap.add_argument("--to", dest="to_date", default="", help="YYYYMMDD (기본: 오늘)")
    ap.add_argument("--dry-run", action="store_true",
                     help="저장 없이 스캔·추출 결과만 출력")
    args = ap.parse_args()

    key = _api_key()
    if not key:
        raise SystemExit("DART_API_KEY 또는 tmp/_apikey.txt 필요")

    end = datetime.strptime(args.to_date, "%Y%m%d") if args.to_date else datetime.now()
    start = (datetime.strptime(args.from_date, "%Y%m%d") if args.from_date
             else end - timedelta(days=7))

    records, stats = collect_renames(key, start, end)
    print(f"\n스캔: 공시 {stats['scanned']}건, 상호변경안내 후보 {stats['candidates']}건, "
          f"추출 {stats['extracted']}건, 패턴 불일치 {stats['no_match']}건, "
          f"오류 {stats['errors']}건")

    existing = _load_json(ALIASES_PATH, {})
    merged = merge_backfill_records(existing, records)
    new_keys = sorted(set(merged) - set(existing))
    print(f"별칭: 기존 {len(existing)}건 → {len(merged)}건 (신규/갱신 {len(new_keys)}건)")
    for name in new_keys[:15]:
        print(f"    {name} → {merged[name]['current']}")

    if args.dry_run:
        print("[dry-run] 저장 생략")
        return

    if merged == existing:
        print("변경 없음")
        return

    DOCS_TOOL.mkdir(parents=True, exist_ok=True)
    ALIASES_PATH.write_text(
        json.dumps(merged, ensure_ascii=False, indent=1, sort_keys=True),
        encoding="utf-8")
    print(f"저장: {ALIASES_PATH}")


if __name__ == "__main__":
    main()
