"""두 sightings.json 합집합 병합 — 동시 push 충돌 복구용.

긴 백필이 도는 동안 다른 워크플로(일일 discover 등)가 같은 sightings 저장소에
push하면 백필의 push가 거부된다. 그때 원격 최신본을 받아 이 스크립트로 우리
수집분을 재병합(dedup)한 뒤 다시 push한다. merge_sightings가 멱등이라 안전.

사용: python scripts/merge_sightings_files.py OURS.json BASE.json
  BASE.json(원격 최신본)에 OURS.json(우리 수집분)을 union 병합해 BASE.json에 덮어씀.
"""
import json
import sys
from pathlib import Path

from scripts.discover_actors import merge_sightings


def _load(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def main():
    if len(sys.argv) != 3:
        raise SystemExit("사용: merge_sightings_files.py OURS.json BASE.json")
    ours_path, base_path = sys.argv[1], sys.argv[2]
    ours = _load(ours_path)
    base = _load(base_path)

    # ours의 모든 sighting 레코드를 base에 재병합 (merge_sightings는 rec['name'] 사용)
    new = []
    for name, recs in ours.get("sightings", {}).items():
        for r in recs:
            new.append({**r, "name": name})
    merge_sightings(base, new)

    # 백필 진행 마커는 '우리 run'의 것을 그대로 반영한다. 백필은 한 번에 하나만
    # 돌고(discover는 이 키를 안 건드림), 5년 재스윕(reset)은 옛 1년 마커를 덮어야
    # 하므로 max가 아니라 ours로 대체한다. ours에 backfill이 없을 때만 base 유지.
    if "backfill" in ours:
        base["backfill"] = ours["backfill"]

    Path(base_path).write_text(
        json.dumps(base, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[REMERGE] {len(new)}개 레코드 재병합 · "
          f"done_until={base.get('backfill', {}).get('done_until', '')} · "
          f"추적 인물 {len(base.get('sightings', {}))}명")


if __name__ == "__main__":
    main()
