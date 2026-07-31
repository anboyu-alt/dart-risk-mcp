# -*- coding: utf-8 -*-
"""공개 리스크 뷰어 기업 검색 맵 재생성 — docs/tool/corp-map.json + corp-aliases.json.

DART corpCode.xml은 상호변경 시 옛 이름을 지우고 새 이름으로 교체한다. 즉
corp-map.json을 그냥 덮어쓰면 사용자가 옛 상호로 검색했을 때 기업을 못 찾게 된다.
이 스크립트는:

  1) corpCode.xml에서 종목코드 보유(상장) 법인만 골라 corp-map.json을 재생성한다.
  2) 재생성 *직전*의 corp-map.json과 corp_code 기준으로 대조해, 같은 corp_code의
     이름이 바뀐 법인의 옛 상호를 docs/tool/corp-aliases.json에 append-only로
     누적한다(뷰어가 옛 이름 검색도 새 이름으로 안내할 수 있게).

corp-map.json 스냅샷은 1회성이라(재생성 스크립트 부재로 2026-07-18 이후 정체),
이 경로만으로는 "그 사이" 있었던 상호변경을 못 잡는다(스냅샷이 이미 새 이름을
담고 있으면 diff가 안 남는다) — 그 과거 이력은 scripts/backfill_corp_aliases.py가
DART 공시 원문을 직접 스캔해 별도로 채운다. 이 스크립트는 "앞으로의" 개명만
자동 포착하는 경량 경로다.

사용:
    python scripts/build_corp_map.py              # corp-map.json + corp-aliases.json 갱신
    python scripts/build_corp_map.py --dry-run     # 파일 쓰기 없이 변경 요약만 출력

환경: DART_API_KEY(우선) 또는 tmp/_apikey.txt
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DOCS_TOOL = ROOT / "docs" / "tool"
CORP_MAP_PATH = DOCS_TOOL / "corp-map.json"
ALIASES_PATH = DOCS_TOOL / "corp-aliases.json"


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


def build_map_from_corp_cache(corp_cache: dict) -> dict:
    """dart_client._corp_cache({name: {corp_code, stock_code}}) → 상장 법인만
    {name: [corp_code, stock_code]} 형식으로, 이름 기준 정렬해 반환.

    corp-map.json은 기존부터 종목코드가 있는(상장) 법인만 담아 왔으므로 그
    관례를 유지한다 — stock_code가 빈 문자열인 비상장 법인은 제외.
    """
    out = {
        name: [info["corp_code"], info.get("stock_code", "")]
        for name, info in corp_cache.items()
        if info.get("stock_code")
    }
    return dict(sorted(out.items(), key=lambda kv: kv[0]))


def merge_aliases(old_map: dict, new_map: dict, existing_aliases: dict) -> dict:
    """corp_code 기준으로 old_map vs new_map을 대조해 별칭을 병합한다 (순수 함수).

    - old_map 이름이 new_map에서 바뀐 corp_code → 옛 이름을 별칭 키로 추가/갱신
      (형식: {"corp_code":..., "stock_code":..., "current": 새이름})
    - 기존 별칭(existing_aliases)은 그 사이 대응 corp_code가 new_map에서 사라져도
      삭제하지 않는다(append-only) — 삭제는 이 함수의 책임이 아니다
    - 별칭의 corp_code가 new_map에도 등장하는데 current가 최신 이름과 다르면
      (2차 개명) current·stock_code를 최신으로 갱신한다
    - 옛 상호가 다른 법인의 "현재 상호"와 우연히 같아도 손대지 않는다(뷰어가
      양쪽 다 보여주도록 그대로 둔다)
    """
    aliases = {name: dict(ent) for name, ent in existing_aliases.items()}

    old_by_code: dict[str, str] = {}
    for name, (code, _stock) in old_map.items():
        old_by_code[code] = name

    new_by_code: dict[str, tuple[str, str]] = {}
    for name, (code, stock) in new_map.items():
        new_by_code[code] = (name, stock)

    # 1) 이번 재생성으로 새로 드러난 개명 — 옛 이름을 별칭으로 추가
    for code, old_name in old_by_code.items():
        hit = new_by_code.get(code)
        if not hit:
            continue
        new_name, new_stock = hit
        if new_name != old_name:
            aliases[old_name] = {
                "corp_code": code,
                "stock_code": new_stock,
                "current": new_name,
            }

    # 2) 기존 별칭 중 그 사이 다시 개명된(2차 개명) 법인은 current를 최신화
    for ent in aliases.values():
        hit = new_by_code.get(ent.get("corp_code", ""))
        if not hit:
            continue
        new_name, new_stock = hit
        if ent.get("current") != new_name:
            ent["current"] = new_name
        if ent.get("stock_code") != new_stock:
            ent["stock_code"] = new_stock

    return aliases


def main():
    ap = argparse.ArgumentParser(
        description="corp-map.json 재생성 + corp-aliases.json 별칭 병합")
    ap.add_argument("--dry-run", action="store_true",
                     help="파일 쓰기 없이 변경 요약만 출력")
    args = ap.parse_args()

    key = _api_key()
    if not key:
        raise SystemExit("DART_API_KEY 또는 tmp/_apikey.txt 필요")

    from dart_risk_mcp.core import dart_client as dc
    dc._load_corp_codes(key)
    if not dc._corp_cache:
        raise SystemExit("corpCode.xml 로드 실패 — API 키 또는 네트워크 확인")

    new_map = build_map_from_corp_cache(dc._corp_cache)
    old_map = _load_json(CORP_MAP_PATH, {})
    existing_aliases = _load_json(ALIASES_PATH, {})

    aliases = merge_aliases(old_map, new_map, existing_aliases)

    added = sorted(set(new_map) - set(old_map))
    removed = sorted(set(old_map) - set(new_map))
    recoded = sorted(n for n in (set(new_map) & set(old_map)) if new_map[n] != old_map[n])
    new_alias_keys = sorted(set(aliases) - set(existing_aliases))

    print(f"[build_corp_map] corp-map {len(old_map)}건 → {len(new_map)}건 "
          f"(추가 {len(added)}, 제거 {len(removed)}, 코드/종목 변경 {len(recoded)})")
    print(f"[build_corp_map] corp-aliases {len(existing_aliases)}건 → {len(aliases)}건 "
          f"(신규/갱신 {len(new_alias_keys)})")
    for name in new_alias_keys[:15]:
        print(f"    {name} → {aliases[name]['current']}")

    if args.dry_run:
        print("[dry-run] 저장 생략")
        return

    DOCS_TOOL.mkdir(parents=True, exist_ok=True)
    # corp-map.json은 기존 압축(구분자 공백 없음) 포맷을 유지해 diff 잡음을 줄인다.
    CORP_MAP_PATH.write_text(
        json.dumps(new_map, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8")
    ALIASES_PATH.write_text(
        json.dumps(aliases, ensure_ascii=False, indent=1, sort_keys=True),
        encoding="utf-8")
    print(f"저장: {CORP_MAP_PATH}")
    print(f"저장: {ALIASES_PATH}")


if __name__ == "__main__":
    main()
