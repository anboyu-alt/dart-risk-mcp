"""known_actors 레지스트리 Notion DB 1회성 셋업.

NOTION_PARENT_PAGE_ID 아래에 레지스트리 DB를 생성하고, 동봉
known_actors.json의 기존 데이터(있으면)를 시딩한 뒤 DB id를 출력한다.
출력된 id를 GitHub Secrets에 DB_KNOWN_ACTORS로 등록하면 일일 크론이
이 DB를 레지스트리 원본으로 사용한다.

사용: python scripts/setup_known_actors_db.py
환경: NOTION_TOKEN, NOTION_PARENT_PAGE_ID
"""
import json
import os
import subprocess
import time
from pathlib import Path

import requests

from dart_risk_mcp.core.known_actors import (
    _NOTION_BASE,
    _notion_headers,
    add_registry_record,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
SEED_PATH = _REPO_ROOT / "dart_risk_mcp" / "data" / "known_actors.json"
# 동봉 JSON은 배포물 개인정보 제거를 위해 비워졌다 — 시딩은 제거 직전
# 히스토리 커밋에서 읽는다 (git 히스토리에는 어차피 남아 있는 데이터).
_SEED_FALLBACK_COMMIT = "33580d4"

DB_SCHEMA = {
    "인물명": {"title": {}},
    "status": {"select": {"options": [
        {"name": "verified", "color": "green"},
        {"name": "maintainer_seed", "color": "blue"},
        {"name": "auto_matched", "color": "orange"},
        {"name": "검토 대기", "color": "yellow"},
        {"name": "기각", "color": "gray"},
    ]}},
    "source": {"rich_text": {}},
    "evidence": {"rich_text": {}},
    "url": {"url": {}},
    "date": {"rich_text": {}},
    "rcept_no": {"rich_text": {}},
    "tags": {"multi_select": {}},
}


def create_registry_db(token: str, parent_page_id: str) -> str:
    """레지스트리 DB 생성 후 DB id 반환. 실패 시 SystemExit."""
    resp = requests.post(
        f"{_NOTION_BASE}/databases",
        headers=_notion_headers(token),
        json={
            "parent": {"type": "page_id", "page_id": parent_page_id},
            "title": [{"type": "text", "text": {"content": "known_actors 레지스트리 (비공개)"}}],
            "properties": DB_SCHEMA,
        },
        timeout=30,
    )
    if resp.status_code != 200:
        raise SystemExit(f"DB 생성 실패 ({resp.status_code}): {resp.text[:300]}")
    return resp.json()["id"]


def _load_seed_data() -> dict:
    """시딩 소스 로드 — 동봉 JSON에 데이터가 있으면 그것, 비워졌으면 히스토리."""
    try:
        data = json.loads(SEED_PATH.read_text(encoding="utf-8"))
        if data.get("actors"):
            return data
    except Exception:
        pass
    try:
        raw = subprocess.run(
            ["git", "show", f"{_SEED_FALLBACK_COMMIT}:dart_risk_mcp/data/known_actors.json"],
            capture_output=True, text=True, cwd=_REPO_ROOT, timeout=30)
        if raw.returncode == 0:
            return json.loads(raw.stdout)
    except Exception:
        pass
    return {"actors": {}}


def seed_from_json(token: str, db_id: str) -> int:
    """기존 레지스트리 데이터를 DB에 시딩. 시딩 행 수 반환."""
    data = _load_seed_data()
    n = 0
    for name, recs in (data.get("actors") or {}).items():
        for rec in recs:
            if add_registry_record(name, rec, token=token, db_id=db_id):
                n += 1
            time.sleep(0.34)  # Notion 3req/s 제한 준수
    return n


def main():
    token = os.environ.get("NOTION_TOKEN", "")
    parent = os.environ.get("NOTION_PARENT_PAGE_ID", "")
    if not (token and parent):
        raise SystemExit("Missing env vars: NOTION_TOKEN, NOTION_PARENT_PAGE_ID")

    db_id = create_registry_db(token, parent)
    seeded = seed_from_json(token, db_id)

    print(f"[OK] 레지스트리 DB 생성 완료 · 기존 데이터 {seeded}행 시딩")
    print("=" * 60)
    print(f"DB_KNOWN_ACTORS={db_id}")
    print("=" * 60)
    print("→ 위 id를 GitHub Secrets에 DB_KNOWN_ACTORS로 등록하세요.")


if __name__ == "__main__":
    main()
