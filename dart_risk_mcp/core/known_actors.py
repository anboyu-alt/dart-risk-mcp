"""공개기록 행위자 레지스트리 (Notion opt-in + 동봉 fallback, 순수 표준+requests).

레지스트리 데이터는 배포물에 싣지 않는다 — 제작자의 비공개 Notion DB가
원본이며, 접근 권한(NOTION_TOKEN + DB_KNOWN_ACTORS)을 부여받은 사용자만
opt-in으로 조회한다. 동봉 JSON은 빈 스켈레톤이다.

로드 우선순위: DART_KNOWN_ACTORS_PATH(로컬 JSON) > Notion(24h 캐시) > 동봉.
"""
import json
import os
import re
import time
from importlib import resources
from pathlib import Path

import requests

_CACHE_FILE = Path.home() / ".cache" / "dart-risk-mcp" / "known_actors_notion.json"
_CACHE_TTL = 24 * 3600

_NOTION_BASE = "https://api.notion.com/v1"
_NOTION_VERSION = "2022-06-28"

_WS_RE = re.compile(r"\s+")


def normalize_name(name: str) -> str:
    """인물명 표기 정규화 — 공백 단일화 + 라틴 표기 대문자 통일.

    'Liu Huan'/'LIU HUAN'처럼 표기만 다른 동일 인물이 sightings 병합·
    레지스트리 매칭에서 분리되지 않도록 한다(한글은 대소문자가 없어 영향 없음).
    """
    return _WS_RE.sub(" ", (name or "").strip()).upper()


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


# ── Notion 레지스트리 I/O ────────────────────────────────────────

def _notion_env() -> tuple[str, str]:
    tok = os.environ.get("NOTION_TOKEN", "")
    db = os.environ.get("DB_KNOWN_ACTORS", "")
    return (tok, db) if tok and db else ("", "")


def _notion_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": _NOTION_VERSION,
        "Content-Type": "application/json",
    }


def _plain(prop_items) -> str:
    """Notion rich_text/title 배열 → 평문."""
    return "".join(t.get("plain_text", "") for t in (prop_items or []))


def _page_to_record(page: dict) -> tuple[str, dict]:
    """Notion 페이지 → (인물명, 기록 dict). JSON 레지스트리 스키마와 동일 형태."""
    p = page.get("properties", {})
    name = _plain(p.get("인물명", {}).get("title"))
    rec = {
        "source": _plain(p.get("source", {}).get("rich_text")),
        "status": (p.get("status", {}).get("select") or {}).get("name", ""),
        "evidence": _plain(p.get("evidence", {}).get("rich_text")),
        "url": p.get("url", {}).get("url") or "",
        "date": _plain(p.get("date", {}).get("rich_text")),
        "tags": [t.get("name", "") for t in p.get("tags", {}).get("multi_select", [])],
    }
    rcept = _plain(p.get("rcept_no", {}).get("rich_text"))
    if rcept:
        rec["rcept_no"] = rcept
    return name, rec


def fetch_registry_from_notion(token: str = "", db_id: str = "") -> dict | None:
    """Notion 레지스트리 DB 전체를 {version, actors} 형태로 조회.

    env(NOTION_TOKEN/DB_KNOWN_ACTORS) 미설정 또는 조회 실패 시 None —
    호출측이 동봉 데이터로 graceful fallback 한다.
    """
    if not (token and db_id):
        token, db_id = _notion_env()
    if not (token and db_id):
        return None
    actors: dict = {}
    payload: dict = {"page_size": 100}
    try:
        while True:
            resp = requests.post(
                f"{_NOTION_BASE}/databases/{db_id}/query",
                headers=_notion_headers(token), json=payload, timeout=15)
            if resp.status_code != 200:
                return None
            data = resp.json()
            for page in data.get("results", []):
                name, rec = _page_to_record(page)
                if name:
                    actors.setdefault(name, []).append(rec)
            if not data.get("has_more"):
                break
            payload["start_cursor"] = data.get("next_cursor")
    except Exception:
        return None
    return {"version": 1, "actors": actors}


def add_registry_record(name: str, record: dict, token: str = "", db_id: str = "") -> bool:
    """레지스트리 DB에 기록 행 추가. env 미설정/실패 시 False (graceful skip)."""
    if not (token and db_id):
        token, db_id = _notion_env()
    if not (token and db_id):
        return False
    props: dict = {
        "인물명": {"title": [{"text": {"content": name}}]},
        "status": {"select": {"name": record.get("status") or "auto_matched"}},
        "source": {"rich_text": [{"text": {"content": record.get("source", "")}}]},
        "evidence": {"rich_text": [{"text": {"content": (record.get("evidence") or "")[:1900]}}]},
        "date": {"rich_text": [{"text": {"content": record.get("date", "")}}]},
        "tags": {"multi_select": [{"name": t} for t in record.get("tags", []) if t]},
    }
    if record.get("url"):
        props["url"] = {"url": record["url"]}
    if record.get("rcept_no"):
        props["rcept_no"] = {"rich_text": [{"text": {"content": record["rcept_no"]}}]}
    try:
        resp = requests.post(
            f"{_NOTION_BASE}/pages", headers=_notion_headers(token),
            json={"parent": {"database_id": db_id}, "properties": props}, timeout=15)
        return resp.status_code == 200
    except Exception:
        return False


# ── 로더 ─────────────────────────────────────────────────────────

def load_known_actors() -> dict:
    """레지스트리 로드. 우선순위: 환경변수 경로 > 신선한 Notion 캐시 > Notion > 동봉.

    Notion 실패 시 동봉 데이터로 graceful fallback(예외 비전파).
    """
    override = os.environ.get("DART_KNOWN_ACTORS_PATH")
    if override:
        try:
            with open(override, encoding="utf-8") as f:
                data = json.load(f)
            return data if _valid(data) else {"version": 1, "actors": {}}
        except Exception:
            return {"version": 1, "actors": {}}

    # Notion 미설정이면 캐시·조회 없이 동봉 데이터로 (opt-in)
    if not all(_notion_env()):
        return _bundled()

    # 24h 신선 캐시
    try:
        if _CACHE_FILE.exists() and (time.time() - _CACHE_FILE.stat().st_mtime) < _CACHE_TTL:
            data = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
            if _valid(data):
                return data
    except Exception:
        pass

    data = fetch_registry_from_notion()
    if data is not None:
        try:
            _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            _CACHE_FILE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass
        return data

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
