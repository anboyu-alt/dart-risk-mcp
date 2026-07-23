# -*- coding: utf-8 -*-
"""known_actors 노션 레지스트리 표기 변형 중복 감사 (읽기 전용).

같은 실체가 다른 표기('주식회사 액션' vs '(주)액션', '정소영(DING SHAO
YING)' vs 'DING SHAO YING')로 별도 행 등재됐는지, 관련기업 태그에 표기
변형이 섞였는지 fold_variants로 점검해 보고서만 출력한다. 행 병합·삭제는
하지 않는다 — 레지스트리는 사람이 검토·승격하는 자산이라 자동 수정 금지.

환경: NOTION_TOKEN, DB_KNOWN_ACTORS
실행: python scripts/audit_registry_names.py            # 전문을 stdout에 출력(로컬)
     python scripts/audit_registry_names.py --mail     # stdout엔 건수만, 전문은
                                                       # 제작자 이메일 발송 (public
                                                       # 레포 Actions 로그 노출 방지)
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
                rows.append({"id": page.get("id", ""),
                             "name": name.strip(), "companies": comps})
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


def build_report(rows: list[dict]) -> tuple[str, str]:
    """(건수 요약, 실명 포함 전문) — 전문은 public 로그에 찍으면 안 됨."""
    dup_names = group_by_fold([r["name"] for r in rows])
    all_tags = sorted({c for r in rows for c in r["companies"] if c.strip()})
    dup_tags = group_by_fold(all_tags)

    summary = (f"레지스트리 행: {len(rows)}건 / "
               f"인물명 표기 변형 중복 의심: {len(dup_names)}그룹 / "
               f"관련기업 태그 표기 변형: {len(dup_tags)}그룹")

    lines = [summary, "", f"[인물명 표기 변형 중복 의심] {len(dup_names)}그룹"]
    lines += ["  - " + " / ".join(g) for g in dup_names] or []
    if not dup_names:
        lines.append("  (없음)")
    lines += ["", f"[관련기업 태그 표기 변형] {len(dup_tags)}그룹"]
    lines += ["  - " + " / ".join(g) for g in dup_tags]
    if not dup_tags:
        lines.append("  (없음)")
    lines += ["", "※ 사실 나열이며 자동 수정 없음 — 병합 여부는 검토 후 노션에서 직접 정리."]
    return summary, "\n".join(lines)


def main():
    token = os.environ.get("NOTION_TOKEN", "")
    db_id = os.environ.get("DB_KNOWN_ACTORS", "")
    if not token or not db_id:
        raise SystemExit("NOTION_TOKEN / DB_KNOWN_ACTORS 환경변수 필요")
    mail_mode = "--mail" in sys.argv
    out_path = ""
    if "--out" in sys.argv:
        i = sys.argv.index("--out")
        out_path = sys.argv[i + 1] if i + 1 < len(sys.argv) else ""
    rows = fetch_rows(token, db_id)
    summary, full = build_report(rows)
    if out_path:
        # private 저장소(sightings) 체크아웃 경로에 전문 저장 — 메일 유실 대비
        # 영속 열람 경로. public 경로에 쓰면 안 됨(호출자 책임: 워크플로우는
        # _sightings/ 아래로만 지정).
        Path(out_path).write_text(full + "\n", encoding="utf-8")
        print(f"전문 저장: {out_path}")
    if mail_mode:
        # public 레포 Actions 로그에는 건수만 — 실명 전문은 이메일로만.
        from scripts.refresh_known_actors import send_mail
        print(summary)
        if send_mail("[dart-risk-mcp] 레지스트리 표기 변형 감사 보고", full):
            print("전문은 제작자 이메일로 발송 완료.")
        else:
            print("경고: 메일 자격증명 미설정/발송 실패 — 전문 미출력(노출 방지). "
                  "MAIL_USER/MAIL_APP_PASSWORD/MAIL_TO Secrets 확인.")
    elif not out_path:
        print(full)


if __name__ == "__main__":
    main()
