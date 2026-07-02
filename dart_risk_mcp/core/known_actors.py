"""공개기록 행위자 레지스트리 (원격 로드 + 동봉 fallback, 순수 표준+requests)."""
import json
import os
import re
import time
from importlib import resources
from pathlib import Path

import requests

_WS_RE = re.compile(r"\s+")


def normalize_name(name: str) -> str:
    """인물명 표기 정규화 — 공백 단일화 + 라틴 표기 대문자 통일.

    'Liu Huan'/'LIU HUAN'처럼 표기만 다른 동일 인물이 sightings 병합·
    레지스트리 매칭에서 분리되지 않도록 한다(한글은 대소문자가 없어 영향 없음).
    """
    return _WS_RE.sub(" ", (name or "").strip()).upper()

_REMOTE_URL = (
    "https://raw.githubusercontent.com/anboyu-alt/dart-risk-mcp/master/"
    "dart_risk_mcp/data/known_actors.json"
)
_CACHE_FILE = Path.home() / ".cache" / "dart-risk-mcp" / "known_actors_remote.json"
_CACHE_TTL = 24 * 3600


def _valid(data) -> bool:
    return isinstance(data, dict) and isinstance(data.get("actors"), dict)


def _bundled() -> dict:
    try:
        text = (resources.files("dart_risk_mcp") / "data" / "known_actors.json").read_text(
            encoding="utf-8")
        data = json.loads(text)
        return data if _valid(data) else {"version": 1, "actors": {}}
    except Exception:
        return {"version": 1, "actors": {}}


def load_known_actors() -> dict:
    """레지스트리 로드. 우선순위: 환경변수 경로 > 신선한 원격 캐시 > 원격 fetch > 동봉.

    원격 실패 시 동봉 데이터로 graceful fallback(예외 비전파).
    """
    override = os.environ.get("DART_KNOWN_ACTORS_PATH")
    if override:
        try:
            with open(override, encoding="utf-8") as f:
                data = json.load(f)
            return data if _valid(data) else {"version": 1, "actors": {}}
        except Exception:
            return {"version": 1, "actors": {}}

    # 24h 신선 캐시
    try:
        if _CACHE_FILE.exists() and (time.time() - _CACHE_FILE.stat().st_mtime) < _CACHE_TTL:
            data = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
            if _valid(data):
                return data
    except Exception:
        pass

    # 원격 fetch
    try:
        resp = requests.get(_REMOTE_URL, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            if _valid(data):
                try:
                    _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
                    _CACHE_FILE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
                except Exception:
                    pass
                return data
    except Exception:
        pass

    return _bundled()


def lookup_actor(name: str) -> list[dict]:
    """인물명 매칭 → 기록 리스트(없으면 []).

    정확 일치 우선, 실패 시 표기 정규화(공백·대소문자) 일치로 폴백 —
    레지스트리 키가 'LIU HUAN'일 때 'Liu Huan' 조회도 매칭된다.
    """
    if not name or not name.strip():
        return []
    actors = load_known_actors().get("actors", {})
    hit = actors.get(name.strip())
    if hit is not None:
        return list(hit)
    want = normalize_name(name)
    for key, recs in actors.items():
        if normalize_name(key) == want:
            return list(recs)
    return []
