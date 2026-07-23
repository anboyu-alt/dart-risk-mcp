# -*- coding: utf-8 -*-
"""'상호변경안내' 공시 백필 → corp_renames 소급 개명 맵 + sightings 병합.

행위자명은 공시 원문 파싱이라 제출 시점 사명으로 동결된다. actor_corp_ids
(discover_actors.reconcile_corp_renames)는 '앞으로의' 개명만 잡으므로,
이미 옛 사명으로 저장된 과거 행위자 키는 이 백필이 소급 병합한다.

원리: KRX 수시공시 '상호변경안내'는 DART에도 유통되며(pblntf_ty='I'),
원문에 '변경전 국문 <옛 사명> … 변경후 국문 <새 사명>'과 '과거 상호변경
내역'까지 담긴다. corp_code는 개명 불변이므로 {옛 사명 → corp_code} 맵
(corp_renames)을 sightings에 영속 저장하면, reconcile_corp_renames의
legacy_index가 옛 사명 행위자 키를 현재 사명 키로 병합한다.

환경: DART_API_KEY(또는 tmp/_apikey.txt), SIGHTINGS_PATH(선택).
실행: python scripts/backfill_renames.py --start 2015-01-01 [--dry-run]
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dart_risk_mcp.core.dart_client import (  # noqa: E402
    fetch_market_disclosures,
    fetch_document_text,
)
from dart_risk_mcp.core.known_actors import fold_name  # noqa: E402
import scripts.discover_actors as da  # noqa: E402

# '가. 변경전 국문 엑스큐어 주식회사 영문 Xcure Corp. 나. 변경후 국문 …' 구조.
# 국문 사명만 취하고 영문·다음 항목 표지에서 멈춘다.
_BEFORE_RE = re.compile(
    r"변경\s*전\s*(?:국문)?\s*[:：]?\s*(.{2,60}?)\s*(?:영문|나\s*\.|변경\s*후)")
_AFTER_RE = re.compile(
    r"변경\s*후\s*(?:국문)?\s*[:：]?\s*(.{2,60}?)\s*(?:영문|\d\s*\.|변경\s*사유)")
# '과거 상호변경 내역: … 변경전: 한솔시큐어 주식회사 → 변경후: …'
_PAST_RE = re.compile(r"변경\s*전\s*[:：]\s*([^→\n)]{2,60}?)\s*→")


def extract_renames_from_text(txt: str, fallback_after: str = "") -> tuple[set, str]:
    """원문 → (옛 사명 집합, 새 사명). 새 사명과 fold 동일한 옛 사명은 제외."""
    olds = set()
    m = _BEFORE_RE.search(txt)
    if m:
        olds.add(m.group(1).strip())
    olds |= {x.strip() for x in _PAST_RE.findall(txt)}
    am = _AFTER_RE.search(txt)
    after = am.group(1).strip() if am else (fallback_after or "")
    af = fold_name(after)
    olds = {o for o in olds if o and fold_name(o) and fold_name(o) != af}
    return olds, after


def collect_renames(api_key: str, start: datetime, end: datetime,
                    max_pages: int = 60) -> dict:
    """구간 내 '상호변경' 공시 수집 → {corp_code: {names: [옛 사명], events: []}}.

    거래소공시(I)는 90일에 4,000건을 넘어 페이지 상한에 걸리므로 30일
    청크로 순회한다(누락 방지).
    """
    renames: dict = {}
    cur = start
    while cur <= end:
        chunk_end = min(cur + timedelta(days=29), end)
        discs = fetch_market_disclosures(
            api_key, cur.strftime("%Y%m%d"), chunk_end.strftime("%Y%m%d"),
            pblntf_ty="I", max_pages=max_pages) or []
        hits = [d for d in discs if "상호변경" in (d.get("report_nm") or "")]
        for d in hits:
            rn, cc = d.get("rcept_no", ""), d.get("corp_code", "")
            if not rn or not cc:
                continue
            txt = fetch_document_text(rn, api_key, max_chars=3000) or ""
            olds, after = extract_renames_from_text(txt, d.get("corp_name", ""))
            if not olds:
                continue
            ent = renames.setdefault(cc, {"names": [], "events": []})
            for o in sorted(olds):
                if o not in ent["names"]:
                    ent["names"].append(o)
            rdt = d.get("rcept_dt", "") or ""
            ent["events"].append({
                "date": f"{rdt[:4]}-{rdt[4:6]}" if len(rdt) >= 6 else "",
                "rcept_no": rn, "before": sorted(olds), "after": after,
            })
        print(f"[{cur:%Y-%m-%d}~{chunk_end:%Y-%m-%d}] "
              f"공시 {len(discs)}건 중 상호변경 {len(hits)}건")
        cur = chunk_end + timedelta(days=1)
    return renames


def merge_renames(sdata: dict, renames: dict) -> bool:
    """수집분을 sightings의 corp_renames에 병합 (rcept_no 기준 dedup)."""
    store = sdata.setdefault("corp_renames", {})
    changed = False
    for cc, ent in renames.items():
        dst = store.setdefault(cc, {"names": [], "events": []})
        for n in ent["names"]:
            if n not in dst["names"]:
                dst["names"].append(n)
                changed = True
        seen = {e.get("rcept_no") for e in dst["events"]}
        for e in ent["events"]:
            if e["rcept_no"] not in seen:
                dst["events"].append(e)
                changed = True
    return changed


def _api_key() -> str:
    key = os.environ.get("DART_API_KEY", "")
    if key:
        return key
    p = Path(__file__).resolve().parent.parent / "tmp" / "_apikey.txt"
    return p.read_text(encoding="utf-8").strip() if p.exists() else ""


def main():
    ap = argparse.ArgumentParser(description="상호변경안내 백필 → 소급 개명 병합")
    ap.add_argument("--start", default="", help="YYYY-MM-DD (기본: 종료일-3년)")
    ap.add_argument("--end", default="", help="YYYY-MM-DD (기본: 오늘)")
    ap.add_argument("--dry-run", action="store_true",
                    help="저장 없이 수집·병합 결과만 출력")
    args = ap.parse_args()

    key = _api_key()
    if not key:
        raise SystemExit("DART_API_KEY 또는 tmp/_apikey.txt 필요")
    end = (datetime.strptime(args.end, "%Y-%m-%d") if args.end else datetime.now())
    start = (datetime.strptime(args.start, "%Y-%m-%d") if args.start
             else end - timedelta(days=365 * 3))

    sightings_path = Path(os.environ.get("SIGHTINGS_PATH") or da._DEFAULT_SIGHTINGS)
    sdata = da._load(sightings_path, {"version": 1, "sightings": {}})

    renames = collect_renames(key, start, end)
    n_names = sum(len(e["names"]) for e in renames.values())
    print(f"\n수집: 개명 {len(renames)}개 회사, 옛 사명 {n_names}건")
    for cc, ent in list(renames.items())[:10]:
        print(f"   {cc}: {ent['names']} (현재 이벤트 {len(ent['events'])}건)")

    changed = merge_renames(sdata, renames)
    n_keys_before = len(sdata.get("sightings", {}))
    if da.reconcile_corp_renames(sdata, da._corp_name_index(key),
                                 da._legacy_name_index(sdata)):
        changed = True
    merged = n_keys_before - len(sdata.get("sightings", {}))
    print(f"소급 병합된 행위자 키: {merged}건")

    if args.dry_run:
        print("[dry-run] 저장 생략")
        return
    if changed:
        sightings_path.parent.mkdir(parents=True, exist_ok=True)
        sdata["updated"] = datetime.now().strftime("%Y-%m-%d")
        with open(sightings_path, "w", encoding="utf-8") as f:
            json.dump(sdata, f, ensure_ascii=False, indent=0)
        print(f"저장: {sightings_path}")
    else:
        print("변경 없음")


if __name__ == "__main__":
    main()
