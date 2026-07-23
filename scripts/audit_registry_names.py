# -*- coding: utf-8 -*-
"""known_actors 노션 레지스트리 표기 변형 중복 감사 (읽기 전용).

같은 실체가 다른 표기('주식회사 액션' vs '(주)액션', '정소영(DING SHAO
YING)' vs 'DING SHAO YING')로 별도 행 등재됐는지, 관련기업 태그에 표기
변형이 섞였는지 fold_variants로 점검해 보고서만 출력한다. 행 병합·삭제는
하지 않는다 — 레지스트리는 사람이 검토·승격하는 자산이라 자동 수정 금지.

환경: NOTION_TOKEN, DB_KNOWN_ACTORS
실행: python scripts/audit_registry_names.py
"""
import os
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dart_risk_mcp.core.known_actors import fold_variants, normalize_name  # noqa: E402

_NOTION_BASE = "https://api.notion.com/v1"


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json"}


def fetch_rows(token: str, db_id: str) -> list[dict]:
    """전 행 페이지네이션 조회 → [{name, companies}]."""
    rows, cursor = [], None
    while True:
        body = {"page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        r = requests.post(f"{_NOTION_BASE}/databases/{db_id}/query",
                          headers=_headers(token), json=body, timeout=30)
        r.raise_for_status()
        data = r.json()
        for page in data.get("results", []):
            props = page.get("properties", {})
            name = "".join(t.get("plain_text", "")
                           for t in props.get("인물명", {}).get("title", []))
            comps = [o.get("name", "") for o in
                     props.get("관련기업", {}).get("multi_select", [])]
            if name.strip():
                rows.append({"name": name.strip(), "companies": comps})
        if not data.get("has_more"):
            return rows
        cursor = data.get("next_cursor")


def group_by_fold(names: list[str]) -> list[list[str]]:
    """fold_variants 교집합이 있는 이름끼리 그룹 (union-find)."""
    parent: dict = {}

    def find(x):
        while parent.get(x, x) != x:
            parent[x] = parent.get(parent[x], parent[x])
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    fold_owner: dict = {}
    for nm in names:
        for f in fold_variants(normalize_name(nm)):
            if f in fold_owner:
                union(nm, fold_owner[f])
            else:
                fold_owner[f] = nm
    groups: dict = {}
    for nm in names:
        groups.setdefault(find(nm), []).append(nm)
    return [sorted(set(g)) for g in groups.values() if len(set(g)) > 1]


def main():
    token = os.environ.get("NOTION_TOKEN", "")
    db_id = os.environ.get("DB_KNOWN_ACTORS", "")
    if not token or not db_id:
        raise SystemExit("NOTION_TOKEN / DB_KNOWN_ACTORS 환경변수 필요")
    rows = fetch_rows(token, db_id)
    print(f"레지스트리 행: {len(rows)}건")

    dup_names = group_by_fold([r["name"] for r in rows])
    print(f"\n[인물명 표기 변형 중복 의심] {len(dup_names)}그룹")
    for g in dup_names:
        print("  -", " / ".join(g))
    if not dup_names:
        print("  (없음)")

    all_tags = sorted({c for r in rows for c in r["companies"] if c.strip()})
    dup_tags = group_by_fold(all_tags)
    print(f"\n[관련기업 태그 표기 변형] {len(dup_tags)}그룹")
    for g in dup_tags:
        print("  -", " / ".join(g))
    if not dup_tags:
        print("  (없음)")
    print("\n※ 사실 나열이며 자동 수정 없음 — 병합 여부는 검토 후 노션에서 직접 정리.")


if __name__ == "__main__":
    main()
