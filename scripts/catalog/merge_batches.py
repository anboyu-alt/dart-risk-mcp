"""세션이 분류한 결과를 검증하고 catalog_classified.jsonl로 병합한다.

검증이 이 스크립트의 존재 이유다. 세션(서브에이전트)이 쓴 JSONL은 형식이 흔들릴 수
있고, taxonomy id 오타 하나가 그 유형의 사례를 조용히 사라지게 만든다. 오류는 모아서
보고하고, 유효한 레코드만 출력에 넣는다.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts._console import use_utf8_stdout  # noqa: E402

RESULTS_DIR = _REPO_ROOT / "data" / "catalog" / "results"
SCREENED_PATH = _REPO_ROOT / "data" / "catalog" / "catalog_screened.jsonl"
OUT_PATH = _REPO_ROOT / "data" / "catalog" / "catalog_classified.jsonl"

_REQUIRED = ("id", "date", "title", "url", "taxonomy_ids", "techniques",
             "sanctions", "laws", "summary", "confidence", "body_source")
_LIST_FIELDS = ("taxonomy_ids", "techniques", "sanctions", "laws")


def validate_record(rec: dict, taxonomy: dict, known_ids: set) -> list[str]:
    """레코드 하나를 검증한다. 반환은 오류 메시지 목록(빈 리스트면 유효).

    - 필수 필드(`_REQUIRED`) 전부 존재
    - 리스트 필드(`_LIST_FIELDS`)의 타입이 실제로 list
    - `taxonomy_ids`의 각 원소가 taxonomy에 실존(빈 배열은 유효 — 미매핑은
      갭 리포트의 정상 입력이지 오류가 아니다)
    - `id`가 known_ids(배치 원본 id 집합)에 존재

    오류 메시지마다 `[id=...]`를 앞에 붙여, 여러 레코드의 오류가 한꺼번에
    출력돼도 어느 레코드 얘기인지 즉시 알 수 있게 한다.
    """
    rid = str(rec.get("id", "?"))
    errors: list[str] = []

    missing = [f for f in _REQUIRED if f not in rec]
    if missing:
        errors.append(f"[id={rid}] 필수 필드 누락: {', '.join(missing)}")

    for field in _LIST_FIELDS:
        if field in rec and not isinstance(rec[field], list):
            errors.append(
                f"[id={rid}] {field}는 리스트여야 합니다(실제 타입: {type(rec[field]).__name__})"
            )

    tids = rec.get("taxonomy_ids")
    if isinstance(tids, list):
        unknown = [t for t in tids if t not in taxonomy]
        if unknown:
            errors.append(f"[id={rid}] 존재하지 않는 taxonomy id: {', '.join(unknown)}")

    if rid not in known_ids:
        errors.append(f"[id={rid}] 배치 원본(screened)에 없는 id입니다")

    return errors


def merge(results: list[dict], screened: list[dict], taxonomy: dict) -> tuple[list[dict], list[str]]:
    """세션 결과와 스크리닝 전건을 합친다. 반환: (병합 레코드, 오류 목록).

    - 유효한 결과 레코드 + keep=false였던 건의 screened_out 레코드를 합친다
    - keep=true인데 결과가 없는 id는 오류로 보고한다(조용히 빠뜨리지 않는다) —
      단, id 자체가 results에 등장했지만(잘못된 형식이라) 검증에 실패한 경우는
      그 검증 오류만 보고하고 별도의 "결과 없음" 오류를 중복으로 얹지 않는다.
    """
    known_ids = {str(r.get("id", "")) for r in screened}
    kept_ids = {str(r.get("id", "")) for r in screened if r.get("keep")}
    screened_out = [r for r in screened if not r.get("keep")]

    errors: list[str] = []
    valid_by_id: dict[str, dict] = {}
    seen_ids: set[str] = set()
    for rec in results:
        rid = str(rec.get("id", ""))
        seen_ids.add(rid)
        errs = validate_record(rec, taxonomy, known_ids)
        if errs:
            errors.extend(errs)
            continue
        valid_by_id[rid] = rec

    for mid in sorted(kept_ids - seen_ids):
        errors.append(f"[id={mid}] keep=true인데 2차 분류 결과가 없습니다(세션 누락)")

    merged: list[dict] = [valid_by_id[rid] for rid in sorted(kept_ids) if rid in valid_by_id]
    for rec in screened_out:
        out = dict(rec)
        out["screened_out"] = True
        merged.append(out)

    return merged, errors


def main() -> None:
    use_utf8_stdout()
    parser = argparse.ArgumentParser(description="세션 분류 결과 검증·병합")
    parser.add_argument("--results-dir", default=str(RESULTS_DIR))
    parser.add_argument("--screened", default=str(SCREENED_PATH))
    parser.add_argument("--out", default=str(OUT_PATH))
    parser.add_argument("--strict", action="store_true", help="오류가 있으면 exit 1")
    args = parser.parse_args()

    from dart_risk_mcp.core.taxonomy import TAXONOMY

    screened_path = Path(args.screened)
    if not screened_path.exists():
        raise SystemExit(f"입력 없음: {screened_path} — 먼저 classify.py --screen-only를 실행하세요")
    screened = [json.loads(l) for l in screened_path.read_text(encoding="utf-8").splitlines() if l.strip()]

    results: list[dict] = []
    results_dir = Path(args.results_dir)
    if results_dir.exists():
        for fp in sorted(results_dir.glob("*.jsonl")):
            for line in fp.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    results.append(json.loads(line))

    merged, errors = merge(results, screened, TAXONOMY)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as fh:
        for rec in merged:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    valid = sum(1 for r in merged if not r.get("screened_out"))
    screened_out_n = sum(1 for r in merged if r.get("screened_out"))
    print(f"[MERGE] 결과 {len(results)}건 · 유효 {valid}건 · 오류 {len(errors)}건 · "
          f"screened_out {screened_out_n}건 → 총 {len(merged)}건 → {out_path}")

    if errors:
        print("[MERGE] 오류 목록:")
        for e in errors:
            print(f"  - {e}")
        if args.strict:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
