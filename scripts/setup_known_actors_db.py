"""known_actors 레지스트리 Notion DB 셋업·스키마 마이그레이션 진입점.

DB_KNOWN_ACTORS 미설정 시(최초 실행): NOTION_PARENT_PAGE_ID 아래에
레지스트리 DB를 생성하고 동봉 known_actors.json 또는 히스토리 커밋의
기존 데이터를 시딩한 뒤 DB id를 출력한다. 출력된 id를 GitHub Secrets에
DB_KNOWN_ACTORS로 등록하면 일일 크론이 이 DB를 레지스트리 원본으로 사용.

DB_KNOWN_ACTORS 설정 시(재실행 = 스키마 마이그레이션): 기존 DB를
건드리지 않고 신규 속성만 추가(관련기업 등)한 뒤, 알려진 기존 행에
한해 회사 태그를 소급 백필한다. 재실행은 항상 안전(추가만, 삭제 없음).

사용: python scripts/setup_known_actors_db.py
환경: NOTION_TOKEN, NOTION_PARENT_PAGE_ID(최초) 또는 DB_KNOWN_ACTORS(재실행)
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
    ensure_registry_schema,
    classify_actor,
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
    "관련기업": {"multi_select": {}},
    "구분": {"select": {"options": [
        {"name": "개인", "color": "default"},
        {"name": "조합", "color": "orange"},
        {"name": "법인", "color": "purple"},
    ]}},
}

# 기존 행 소급 백필용 — 코드가 companies를 기록하기 전에 생성된 알려진
# 행만 대상. 이후 신규 행은 파이프라인이 자동으로 관련기업을 채운다.
_KNOWN_COMPANY_BACKFILL = {
    "신승수": ["CG인바이츠", "제이케이시냅스", "헬스커넥트"],
    "LIU HUAN": ["씨엑스아이", "헝셩그룹"],
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


def backfill_known_companies(token: str, db_id: str) -> int:
    """_KNOWN_COMPANY_BACKFILL에 있는 인물명의 기존 행 중 관련기업이 비어있는
    행에 한해 태깅. 페이지네이션 전체 순회. 갱신된 행 수 반환."""
    updated = 0
    payload: dict = {"page_size": 100}
    while True:
        resp = requests.post(
            f"{_NOTION_BASE}/databases/{db_id}/query",
            headers=_notion_headers(token), json=payload, timeout=15)
        if resp.status_code != 200:
            break
        data = resp.json()
        for page in data.get("results", []):
            props = page.get("properties", {})
            name = "".join(t.get("plain_text", "")
                           for t in props.get("인물명", {}).get("title", []))
            patch_props: dict = {}
            existing = props.get("관련기업", {}).get("multi_select", [])
            companies = _KNOWN_COMPANY_BACKFILL.get(name)
            if not companies and not existing:
                # 자동 발굴/자동 매칭 행은 evidence에 회사 목록이 남아 있음
                # ("... 반복 등장: A·B·C" 또는 "A CB인수 인수자로 등장") — 파싱 복구
                ev = "".join(t.get("plain_text", "")
                             for t in props.get("evidence", {}).get("rich_text", []))
                if "반복 등장: " in ev:
                    companies = [x.strip() for x in
                                 ev.split("반복 등장: ", 1)[1].split("·") if x.strip()]
                elif ev.endswith("인수자로 등장"):
                    first = ev.split(" ", 1)[0].strip()
                    companies = [first] if first else []
            if companies and not existing:  # 이미 태깅된 행은 덮어쓰지 않음
                patch_props["관련기업"] = {
                    "multi_select": [{"name": c[:100]} for c in companies][:20]}
            # 구분 도입(entity 추적) 전에 생성된 행은 전부 개인 — 미설정 시 소급
            if not (props.get("구분", {}).get("select") or {}).get("name"):
                patch_props["구분"] = {"select": {"name": "개인"}}
            # 접수번호가 있는데 url이 맨몸 홈페이지면 공시 뷰어 링크로 소급
            rcpt = "".join(t.get("plain_text", "")
                           for t in props.get("rcept_no", {}).get("rich_text", []))
            cur_url = (props.get("url", {}) or {}).get("url") or ""
            if rcpt and cur_url.rstrip("/") in ("", "https://dart.fss.or.kr"):
                patch_props["url"] = {
                    "url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcpt}"}
            if not patch_props:
                continue
            patch = requests.patch(
                f"{_NOTION_BASE}/pages/{page['id']}", headers=_notion_headers(token),
                json={"properties": patch_props}, timeout=15)
            if patch.status_code == 200:
                updated += 1
        if not data.get("has_more"):
            break
        payload["start_cursor"] = data.get("next_cursor")
    return updated


def archive_fragment_rows(token: str, db_id: str) -> int:
    """인물명이 추출 조각(classify_actor=="noise")인 행을 아카이브(삭제).

    원문 파싱이 이름 대신 보일러플레이트를 긁어 등재된 오염 행 정리.
    archived=true는 뷰에서 제거하되 복구 가능(감사 목적). 갯수 반환.
    """
    removed = 0
    payload: dict = {"page_size": 100}
    while True:
        resp = requests.post(
            f"{_NOTION_BASE}/databases/{db_id}/query",
            headers=_notion_headers(token), json=payload, timeout=15)
        if resp.status_code != 200:
            break
        data = resp.json()
        for page in data.get("results", []):
            name = "".join(t.get("plain_text", "") for t in
                           page.get("properties", {}).get("인물명", {}).get("title", []))
            if name and classify_actor(name) == "noise":
                a = requests.patch(
                    f"{_NOTION_BASE}/pages/{page['id']}",
                    headers=_notion_headers(token),
                    json={"archived": True}, timeout=15)
                if a.status_code == 200:
                    removed += 1
        if not data.get("has_more"):
            break
        payload["start_cursor"] = data.get("next_cursor")
    return removed


def main():
    token = os.environ.get("NOTION_TOKEN", "")
    db_id = os.environ.get("DB_KNOWN_ACTORS", "")

    if db_id:
        # 재실행 = 스키마 마이그레이션 (기존 DB 유지, 속성 추가 + 소급 백필)
        if not token:
            raise SystemExit("Missing env var: NOTION_TOKEN")
        ok = ensure_registry_schema(token, db_id)
        if not ok:
            raise SystemExit("스키마 속성 추가 실패 — DB_KNOWN_ACTORS/권한 확인 필요")
        updated = backfill_known_companies(token, db_id)
        removed = archive_fragment_rows(token, db_id)
        print(f"[OK] 스키마 마이그레이션 완료 · 속성(관련기업·구분) 확인 · "
              f"기존 행 {updated}건 소급 보정 · 조각 행 {removed}건 아카이브")
        return

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
