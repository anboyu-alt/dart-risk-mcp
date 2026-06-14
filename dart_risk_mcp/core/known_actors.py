"""공개기록 행위자 레지스트리 (동봉 데이터 로드/조회, 순수 표준 라이브러리)."""
import json
import os
from importlib import resources


def load_known_actors() -> dict:
    """동봉 known_actors.json 로드. 환경변수 DART_KNOWN_ACTORS_PATH로 오버라이드.

    파일 부재/손상 시 빈 구조 반환(예외 비전파).
    """
    override = os.environ.get("DART_KNOWN_ACTORS_PATH")
    try:
        if override:
            with open(override, encoding="utf-8") as f:
                data = json.load(f)
        else:
            text = (resources.files("dart_risk_mcp") / "data" / "known_actors.json").read_text(
                encoding="utf-8")
            data = json.loads(text)
        if not isinstance(data, dict) or not isinstance(data.get("actors"), dict):
            return {"version": 1, "actors": {}}
        return data
    except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError, ModuleNotFoundError):
        return {"version": 1, "actors": {}}


def lookup_actor(name: str) -> list[dict]:
    """인물명 정확 매칭 → 기록 리스트(없으면 [])."""
    if not name or not name.strip():
        return []
    return list(load_known_actors().get("actors", {}).get(name.strip(), []))
