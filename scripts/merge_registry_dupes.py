# -*- coding: utf-8 -*-
"""known_actors 노션 레지스트리 표기 변형 중복 병합 (제작자 확인 후 실행).

audit_registry_names.py가 검출한 fold_variants 동일 그룹을 병합한다.
행 삭제 없음 — 변형 표기 행들의 '인물명' title만 정본 표기로 통일한다
(근거·태그·상태 전부 보존, 같은 이름 행들은 로드 시 한 인물로 묶임).

정본 선택 우선순위: ① 현재 DART corpCode 명부에 있는 사명(개명 후 현재명)
② 행 수 최다 ③ 긴 이름. 병합 상세 로그는 --out 파일(비공개 경로)에만
쓰고 stdout엔 건수만 출력한다(public Actions 로그 노출 방지).

환경: NOTION_TOKEN, DB_KNOWN_ACTORS, DART_API_KEY(정본 선택 보조, 선택).
실행: python scripts/merge_registry_dupes.py [--dry-run] [--out <path>]
"""
import os
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dart_risk_mcp.core.known_actors import fold_variants, normalize_name  # noqa: E402
from scripts.audit_registry_names import (  # noqa: E402
    _NOTION_BASE, _headers, fetch_rows, group_by_fold,
)


def _corp_folds(api_key: str) -> set:
    """현재 corpCode 명부 사명들의 fold 집합 (정본 선택 보조. 키 없으면 빈 집합)."""
    if not api_key:
        return set()
    try:
        import scripts.discover_actors as da
        return set(da._corp_name_index(api_key).keys())
    except Exception:
        return set()


def pick_canon(names: list[str], rows_by_name: dict, corp_folds: set) -> str:
    """그룹 내 정본 표기 선택 — 현재 명부 사명 > 행 수 최다 > 긴 이름."""
    def keyf(n):
        in_registry = any(f in corp_folds
                          for f in fold_variants(normalize_name(n)))
        return (in_registry, len(rows_by_name.get(n, [])), len(n))
    return max(sorted(names), key=keyf)


def rename_page(token: str, page_id: str, new_name: str) -> bool:
    """행의 인물명 title만 교체 (다른 속성 불변)."""
    r = requests.patch(
        f"{_NOTION_BASE}/pages/{page_id}", headers=_headers(token),
        json={"properties": {"인물명": {
            "title": [{"type": "text", "text": {"content": new_name}}]}}},
        timeout=30)
    return r.status_code == 200


def main():
    token = os.environ.get("NOTION_TOKEN", "")
    db_id = os.environ.get("DB_KNOWN_ACTORS", "")
    if not token or not db_id:
        raise SystemExit("NOTION_TOKEN / DB_KNOWN_ACTORS 환경변수 필요")
    dry = "--dry-run" in sys.argv
    out_path = ""
    if "--out" in sys.argv:
        i = sys.argv.index("--out")
        out_path = sys.argv[i + 1] if i + 1 < len(sys.argv) else ""

    rows = fetch_rows(token, db_id)
    rows_by_name: dict = {}
    for r in rows:
        rows_by_name.setdefault(r["name"], []).append(r)
    groups = group_by_fold(list(rows_by_name.keys()))
    corp_folds = _corp_folds(os.environ.get("DART_API_KEY", ""))

    log_lines = []
    renamed = failed = 0
    for g in groups:
        canon = pick_canon(g, rows_by_name, corp_folds)
        for nm in g:
            if nm == canon:
                continue
            for row in rows_by_name.get(nm, []):
                if dry:
                    log_lines.append(f"[dry] {nm!r} -> {canon!r}")
                    continue
                if rename_page(token, row["id"], canon):
                    renamed += 1
                    log_lines.append(f"{nm!r} -> {canon!r}")
                else:
                    failed += 1
                    log_lines.append(f"실패: {nm!r} ({row['id']})")
                time.sleep(0.35)   # Notion rate limit(3req/s) 여유

    print(f"레지스트리 {len(rows)}행 / 중복 그룹 {len(groups)}개 / "
          f"title 통일 {renamed}건 / 실패 {failed}건"
          + (" [dry-run]" if dry else ""))
    if out_path:
        Path(out_path).write_text("\n".join(log_lines) + "\n", encoding="utf-8")
        print(f"상세 로그 저장: {out_path}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
