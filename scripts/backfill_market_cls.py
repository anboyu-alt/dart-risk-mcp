"""기존 sightings.json에 시장 구분(corp_cls) 소급 채우기.

discover_actors.py는 이제 수집 시점에 corp_cls(list.json 제공)를 담지만,
그 이전에 쌓인 sightings에는 없다. 회사별로 DART company.json을 1회씩
조회해 해당 corp_code의 모든 레코드에 corp_cls를 써 넣는다(멱등 —
이미 값이 있는 회사는 건너뛴다).

사용: SIGHTINGS_PATH=_sightings/sightings.json python scripts/backfill_market_cls.py
환경: DART_API_KEY(또는 tmp/_apikey.txt), SIGHTINGS_PATH.
"""
import json
import os
import time
from pathlib import Path

from dart_risk_mcp.core.dart_client import fetch_company_info
from scripts.refresh_known_actors import _api_key

_DEFAULT = Path(__file__).resolve().parents[1] / "tmp" / "sightings.json"
PACE_SEC = 0.3   # DART 분당 상한 회피


def collect_missing(sdata: dict) -> dict:
    """corp_cls가 비어 있는 corp_code -> 대표 회사명. 이미 값이 있으면 제외."""
    have, need = set(), {}
    for recs in sdata.get("sightings", {}).values():
        for r in recs:
            cc = r.get("corp_code")
            if not cc:
                continue
            if (r.get("corp_cls") or "").strip():
                have.add(cc)
            else:
                need.setdefault(cc, r.get("corp") or cc)
    return {cc: nm for cc, nm in need.items() if cc not in have}


def apply_cls(sdata: dict, cls_map: dict) -> int:
    """cls_map(corp_code -> corp_cls)을 모든 레코드에 반영. 갱신 레코드 수 반환."""
    n = 0
    for recs in sdata.get("sightings", {}).values():
        for r in recs:
            cc = r.get("corp_code")
            if cc in cls_map and not (r.get("corp_cls") or "").strip():
                r["corp_cls"] = cls_map[cc]
                n += 1
    return n


def main():
    key = _api_key()
    if not key:
        raise SystemExit("DART_API_KEY 또는 tmp/_apikey.txt 필요")
    path = Path(os.environ.get("SIGHTINGS_PATH") or _DEFAULT)
    sdata = json.loads(path.read_text(encoding="utf-8"))

    missing = collect_missing(sdata)
    print(f"[START] corp_cls 미상 회사 {len(missing)}곳 조회")
    cls_map = {}
    for i, (cc, nm) in enumerate(sorted(missing.items()), 1):
        info = fetch_company_info(cc, key)
        cls = (info.get("corp_cls") or "").strip() or "E"  # 조회 실패·기타 → 비상장 폴백
        cls_map[cc] = cls
        if i % 20 == 0 or i == len(missing):
            print(f"[DART] {i}/{len(missing)} · {nm} → {cls}")
        time.sleep(PACE_SEC)

    updated = apply_cls(sdata, cls_map)
    if updated:
        path.write_text(json.dumps(sdata, ensure_ascii=False, indent=1), encoding="utf-8")
    dist = {}
    for c in cls_map.values():
        dist[c] = dist.get(c, 0) + 1
    print(f"[SUMMARY] {updated}개 레코드 갱신 · 시장분포 {dist}")
    print("[DONE]")


if __name__ == "__main__":
    main()
