"""인물↔회사군 워치리스트 영속 저장 (순수 파일 I/O, requests 무관)."""
import json
import logging
import os
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

_DEFAULT_PATH = Path.home() / ".config" / "dart-risk-mcp" / "watchlist.json"


def _watchlist_path() -> Path:
    override = os.environ.get("DART_WATCHLIST_PATH")
    return Path(override) if override else _DEFAULT_PATH


def _quarantine(path) -> "str":
    """읽을 수 없는 파일을 옆으로 치우고 그 경로를 돌려준다.

    치우지 않으면 다음 저장이 **그 위에 덮어쓴다** — 남아 있던 내용까지
    사라진다. 워치리스트는 캐시가 아니라 사용자가 직접 채운 자산이라
    (그래서 ~/.config에 둔다) 조용히 버리면 안 된다.
    """
    for n in range(1, 100):
        bak = path.with_name(path.name + (".corrupt" if n == 1 else f".corrupt{n}"))
        if bak.exists():
            continue
        try:
            os.replace(path, bak)
            return str(bak)
        except OSError:
            return ""
    return ""


def load_watchlist() -> dict:
    """파일을 읽어 dict 반환. 없거나 손상 시 빈 구조(예외 비전파).

    **손상 파일은 옆으로 치운다.** 그러지 않으면 다음 `add` 한 번에 원본이
    통째로 덮어써진다 — 라이브 재현(2026-08-23): 3명이 저장된 파일을 절반만
    남기고(쓰기 도중 중단 흉내) `add`를 한 번 부르니 3명이 전부 사라지고
    새로 추가한 1명만 남았다. 백업도 없었다.
    """
    path = _watchlist_path()
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or not isinstance(data.get("persons"), dict):
            raise ValueError("스키마가 맞지 않는다")
        return data
    except FileNotFoundError:
        return {"version": 1, "persons": {}}
    except (json.JSONDecodeError, OSError, ValueError):
        bak = _quarantine(path)
        log.warning("워치리스트를 읽을 수 없어 옆으로 옮겼습니다: %s", bak or path)
        return {"version": 1, "persons": {}, "_quarantined": bak}


def save_watchlist(data: dict) -> None:
    """임시 파일에 쓰고 교체한다(원자적).

    바로 열어서 쓰면 쓰다가 멈춘 순간 **기존 목록이 잘린 채 남는다**.
    그 상태가 위 `load_watchlist`가 말하는 손상이고, 잘린 파일은 다음
    저장에 덮어써져 사라진다. 애초에 잘리지 않게 한다.
    """
    path = _watchlist_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {k: v for k, v in data.items() if k != "_quarantined"}
    tmp = path.with_name(path.name + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=1)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def add_person(person: str, companies: list[str], note: str = "") -> dict:
    """인물 추가/갱신. companies는 기존과 합집합 병합(순서 보존). 갱신 엔트리 반환."""
    data = load_watchlist()
    persons = data.setdefault("persons", {})
    existing = persons.get(person, {})
    old = existing.get("companies", [])
    merged = list(dict.fromkeys(old + [c for c in companies if c]))
    entry = {
        "companies": merged,
        "note": note if note else existing.get("note", ""),
        "updated": datetime.now().strftime("%Y-%m-%d"),
    }
    persons[person] = entry
    save_watchlist(data)
    return entry


def remove_person(person: str) -> bool:
    data = load_watchlist()
    persons = data.get("persons", {})
    if person in persons:
        del persons[person]
        save_watchlist(data)
        return True
    return False


def get_person_companies(person: str) -> list[str]:
    data = load_watchlist()
    return list(data.get("persons", {}).get(person, {}).get("companies", []))


def list_persons() -> list[tuple[str, int]]:
    data = load_watchlist()
    return sorted(
        (name, len(e.get("companies", [])))
        for name, e in data.get("persons", {}).items()
    )
