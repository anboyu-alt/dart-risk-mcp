"""sightings 별칭(alias) 맵 관리 — 같은 인물의 여러 표기를 한 정본으로 합침.

취재로 밝혀진 '한 인물 = 여러 이름'을 등록하면, 다음 merge_sightings가 과거·
신규 데이터를 정본 키로 합쳐 한 행위자로 추적한다. 별칭 데이터는 투자 대상 식별
정보이므로 반드시 비공개 sightings 저장소에서만 다룬다(공개 CI 로그 노출 금지).

사용:
  python scripts/manage_aliases.py add "정본이름" "별칭1" "별칭2" ...
  python scripts/manage_aliases.py list
  python scripts/manage_aliases.py remove "별칭"
환경: SIGHTINGS_PATH (기본: tmp/sightings.json)
"""
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

from dart_risk_mcp.core.known_actors import normalize_name

_DEFAULT = Path(__file__).resolve().parents[1] / "tmp" / "sightings.json"


def _path() -> Path:
    return Path(os.environ.get("SIGHTINGS_PATH") or _DEFAULT)


def _load() -> dict:
    p = _path()
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"version": 1, "sightings": {}}


def _save(data: dict):
    _path().write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def cmd_add(canonical: str, alias_names: list):
    data = _load()
    aliases = data.setdefault("aliases", {})
    canon = normalize_name(canonical)
    added = []
    for a in alias_names:
        an = normalize_name(a)
        if an and an != canon:
            aliases[an] = canon
            added.append(an)
    # 정본 자신이 다른 정본의 별칭으로 잡혀 있으면 정리(체인 방지)
    if canon in aliases:
        del aliases[canon]
    _save(data)
    print(f"[ALIAS] 정본 '{canon}' ← {', '.join(added) or '(변경 없음)'}")
    print(f"[ALIAS] 총 별칭 {len(aliases)}개. 다음 merge_sightings가 과거 데이터를 합칩니다.")


def cmd_remove(alias: str):
    data = _load()
    aliases = data.get("aliases", {})
    an = normalize_name(alias)
    if aliases.pop(an, None) is not None:
        _save(data)
        print(f"[ALIAS] '{an}' 제거")
    else:
        print(f"[ALIAS] '{an}' 없음")


def cmd_list():
    aliases = _load().get("aliases", {})
    if not aliases:
        print("[ALIAS] 등록된 별칭 없음")
        return
    groups = defaultdict(list)
    for a, c in aliases.items():
        groups[c].append(a)
    for canon, al in sorted(groups.items()):
        print(f"  {canon}  ←  {', '.join(sorted(al))}")
    print(f"[ALIAS] 정본 {len(groups)}명 · 별칭 {len(aliases)}개")


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    cmd = sys.argv[1]
    if cmd == "add" and len(sys.argv) >= 4:
        cmd_add(sys.argv[2], sys.argv[3:])
    elif cmd == "remove" and len(sys.argv) == 3:
        cmd_remove(sys.argv[2])
    elif cmd == "list":
        cmd_list()
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
