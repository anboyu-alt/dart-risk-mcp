# -*- coding: utf-8 -*-
"""정화 대상(제외 예정) 행위자 보고 — 읽기 전용, 삭제 없음 (SE-5b Task 3).

Task 2(`known_actors.py::_filter_institutions`)가 읽기 경로(`load_known_actors`)
에서 걸러내는 인물(제도권 기관으로 판정되고 + 기록 전부가 기계 등재)을
나열한다. **Notion에 아무것도 쓰지 않는다** — 삭제는 비공개 레지스트리를
관리하는 제작자의 판단이고, 이 스크립트는 무엇을 지우면 되는지 "보고"만
한다. 실제 정리(Notion에서 행 삭제)는 제작자가 이 보고서를 보고 직접 한다.

`load_known_actors()`는 이미 필터가 걸린 결과만 내놓으므로(Task 2), 여기서는
필터 적용 *전* 원본이 필요하다. 필터를 끄는 전역 플래그나 별도 재구현을
만드는 대신, 로더가 이미 분리해 둔 `_load_raw()`(원본 로드)와
`_filter_institutions()`(필터 그 자체, Task 2와 동일 함수)를 그대로 불러
그 둘의 차집합(원본에는 있는데 필터 결과에는 없는 인물)을 구한다.
should_store·classify_actor·sector_of는 재구현하지 않고 그대로 소비만 한다.

환경: NOTION_TOKEN, DB_KNOWN_ACTORS. 값은 실행 시점에 실제 환경변수 또는
저장소 루트의 .env.local에서 읽는다 — 이 스크립트에도, 어떤 파일에도 키를
박지 않는다. 둘 다 없으면(그리고 DART_KNOWN_ACTORS_PATH도 없으면)
load_known_actors()와 동일하게 동봉 빈 스켈레톤으로 조용히 0건을 보고한다
(레지스트리 미설정 시에도 죽지 않음).

실행:
    python scripts/report_registry_purge.py            # 표 형식으로 stdout 출력
    python scripts/report_registry_purge.py --json      # 기계가 읽을 JSON stdout

**출력에 실명이 포함된다.** 파일로 저장하는 기본 동작을 두지 않는다 —
public 레포에 실명이 커밋되면 안 된다는 이 저장소의 확립된 경계
(build_network_html.py가 같은 이유로 출력물을 커밋하지 않는 것과 동일).
항상 표준출력으로만 낸다. 필요하면 호출측이 셸에서 리다이렉트하되, 그
결과물을 public 저장소에 커밋하지 않는 책임은 실행한 사람에게 있다.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_ENV_FILE = _ROOT / ".env.local"
sys.path.insert(0, str(_ROOT))

from dart_risk_mcp.core.known_actors import (  # noqa: E402
    _filter_institutions,
    _load_raw,
    actor_status,
    classify_actor,
    sector_of,
)
from scripts._console import use_utf8_stdout  # noqa: E402


def load_env_file() -> None:
    """.env.local이 있으면 아직 설정 안 된 환경변수만 채운다.

    scripts/se_verify_live.py의 동일 헬퍼와 같은 관례 — 자격증명을 코드에
    박지 않고 실행 시점에만 읽는다. 이미 설정된 환경변수는 덮어쓰지 않는다.
    """
    if not _ENV_FILE.exists():
        return
    for raw in _ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        name, value = name.strip(), value.strip().strip('"').strip("'")
        if name and name not in os.environ:
            os.environ[name] = value


def _company_count(records: list) -> int:
    """기록들의 관련기업(companies) 태그 합집합 크기 — 중복 회사명 제거."""
    companies = {c for r in records for c in (r.get("companies") or []) if c}
    return len(companies)


def _reason(name: str) -> str:
    """제외 사유 표기 — classify_actor·sector_of 결과 그대로, 판정 없이 사실만.

    should_store가 거부하는 경로는 institution인데 sector_of가 '증권'·
    '은행'인 경우뿐이다(기타기관은 should_store가 보존). 그 경로를 그대로
    보여준다.
    """
    kind = classify_actor(name)
    sect = sector_of(name)
    return f"{kind}/{sect}" if sect else kind


def build_report() -> dict:
    """원본(필터 적용 전) 대비 필터 결과의 차집합 → 제외 대상 목록 + 합계.

    _filter_institutions는 Task 2에서 이미 검증된 그 함수를 그대로 호출한다
    — 여기서 배제 조건을 다시 판정하지 않는다(로직 이원화로 인한 드리프트
    방지). 그 함수가 무엇을 남기는지만 보고, 원본에서 뺀 나머지를 "제외
    대상"으로 보고한다.
    """
    raw = _load_raw()
    raw_actors = raw.get("actors", {}) if isinstance(raw, dict) else {}
    filtered = _filter_institutions(raw)
    filtered_names = set(filtered.get("actors", {}).keys()) if isinstance(filtered, dict) else set()

    excluded = []
    for name, records in raw_actors.items():
        if name in filtered_names:
            continue
        statuses = sorted({actor_status(r) for r in records})
        excluded.append({
            "name": name,
            "status": "/".join(statuses),
            "company_count": _company_count(records),
            "record_count": len(records),
            "reason": _reason(name),
        })
    # 등장 회사 수 내림차순(실측 표와 동일 정렬), 동률이면 이름으로 결정적 정렬
    excluded.sort(key=lambda e: (-e["company_count"], e["name"]))

    return {
        "total": len(raw_actors),
        "excluded_count": len(excluded),
        "excluded": excluded,
    }


def print_table(report: dict) -> None:
    print(f"제외 대상: {report['excluded_count']}명 / 전체 {report['total']}명\n")
    if not report["excluded"]:
        print("(제외 대상 없음)")
        return
    header = f"{'회사수':>4}  {'기록':>4}  {'사유':<16}  {'status':<16}  인물명"
    print(header)
    print("-" * len(header))
    for e in report["excluded"]:
        print(f"{e['company_count']:>4}  {e['record_count']:>4}  "
              f"{e['reason']:<16}  {e['status']:<16}  {e['name']}")
    print("\n※ 사실 나열이며 Notion에 아무것도 쓰지 않았다. 실제 삭제는 "
          "제작자가 이 보고서를 보고 Notion에서 직접 한다.")


def main() -> None:
    use_utf8_stdout()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="표 대신 JSON으로 출력")
    args = parser.parse_args()

    load_env_file()
    have_notion = bool(os.environ.get("NOTION_TOKEN") and os.environ.get("DB_KNOWN_ACTORS"))
    have_override = bool(os.environ.get("DART_KNOWN_ACTORS_PATH"))
    if not have_notion and not have_override:
        print("경고: NOTION_TOKEN/DB_KNOWN_ACTORS(또는 DART_KNOWN_ACTORS_PATH) "
              "미설정 — 동봉 빈 스켈레톤을 보고합니다.", file=sys.stderr)

    report = build_report()
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_table(report)


if __name__ == "__main__":
    main()
