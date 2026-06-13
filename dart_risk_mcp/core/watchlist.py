"""인물↔회사군 워치리스트 영속 저장 (순수 파일 I/O, requests 무관)."""
import json
import os
from datetime import datetime
from pathlib import Path

_DEFAULT_PATH = Path.home() / ".config" / "dart-risk-mcp" / "watchlist.json"


def _watchlist_path() -> Path:
    override = os.environ.get("DART_WATCHLIST_PATH")
    return Path(override) if override else _DEFAULT_PATH


def load_watchlist() -> dict:
    """파일을 읽어 dict 반환. 없거나 손상 시 빈 구조(예외 비전파)."""
    try:
        with open(_watchlist_path(), encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or not isinstance(data.get("persons"), dict):
            return {"version": 1, "persons": {}}
        return data
    except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError):
        return {"version": 1, "persons": {}}


def save_watchlist(data: dict) -> None:
    path = _watchlist_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


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
