"""1차 통과분에 본문을 붙여 배치 파일로 내보낸다 (세션 분류용).

본문 확보가 여기서 일어난다 — extract_light(상세 페이지) 후 extract_full(PDF 전문)을
시도하고, 실패하면 요약으로 degrade한다. 배치 크기가 10인 이유는 본문이 건당
약 4,000토큰이라 그 이상 묶으면 분류하는 쪽의 컨텍스트를 압박하기 때문이다.

오프라인 백필 전용 스크립트다 — 월간 증분은 classify.py의 기존 전체 흐름
(스크리닝→정밀, API 양쪽 다)을 그대로 쓴다.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts._console import use_utf8_stdout  # noqa: E402
from scripts.catalog.extract import extract_full, extract_light  # noqa: E402

IN_PATH = _REPO_ROOT / "data" / "catalog" / "catalog_screened.jsonl"
OUT_DIR = _REPO_ROOT / "data" / "catalog" / "batches"
_SLEEP = 0.25


def load_screened(path) -> list[dict]:
    """classify.py --screen-only 출력을 읽는다. 파일이 없으면 빈 리스트."""
    p = Path(path)
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def build_batches(records: list[dict], size: int) -> list[list[dict]]:
    """keep=true인 레코드만 size씩 나눈다. 순수 함수 — 네트워크·본문 확보 없음."""
    kept = [r for r in records if r.get("keep")]
    return [kept[i:i + size] for i in range(0, len(kept), size)]


def _enrich(rec: dict) -> dict:
    """레코드 하나의 본문을 확보한다: 상세 페이지(extract_light) → PDF 전문(extract_full).

    PDF 전문 추출에 성공하면 body/body_source를 pdf 버전으로 덮어쓴다. 실패하면
    extract_light가 이미 채운 page/title_only 본문으로 degrade한다.
    """
    out = extract_light(rec)
    full = extract_full(out)
    if full:
        out = dict(out, body=full, body_source="pdf")
    return out


def main() -> None:
    use_utf8_stdout()
    parser = argparse.ArgumentParser(description="1차 통과분 본문 확보 + 세션 분류용 배치 내보내기")
    parser.add_argument("--in", dest="in_path", default=str(IN_PATH))
    parser.add_argument("--out-dir", default=str(OUT_DIR))
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--resume", action="store_true", help="이미 존재하는 배치 파일은 건너뜀")
    args = parser.parse_args()

    records = load_screened(args.in_path)
    batches = build_batches(records, args.batch_size)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(batches)
    for idx, batch in enumerate(batches):
        out_path = out_dir / f"batch-{idx:03d}.jsonl"
        if args.resume and out_path.exists():
            continue

        counts = {"pdf": 0, "page": 0, "title_only": 0}
        enriched = []
        for rec in batch:
            rec = _enrich(rec)
            counts[rec.get("body_source", "title_only")] = counts.get(rec.get("body_source", "title_only"), 0) + 1
            enriched.append(rec)
            time.sleep(_SLEEP)  # 상세 페이지 + PDF 다운로드 — 네트워크 요청 페이싱

        with out_path.open("w", encoding="utf-8") as fh:
            for rec in enriched:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

        print(f"[EXPORT] 배치 {idx + 1}/{total} — 본문 pdf {counts['pdf']}건 / "
              f"page {counts['page']}건 / title_only {counts['title_only']}건")

    print(f"[EXPORT] 완료: {total}개 배치 → {out_dir}")


if __name__ == "__main__":
    main()
