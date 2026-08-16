"""Phase E — taxonomy 45개에 매핑되지 않은 수법을 신규 신호 후보로 리포트.

이 리포트는 사람이 읽고 판단하는 입력이다. taxonomy.py를 자동으로 고치지
않는다 — 신호 추가는 CLAUDE.md의 기존 4단계 절차(signals.py →
SIGNAL_KEY_TO_TAXONOMY → taxonomy.py → 선택적 CROSS_SIGNAL_PATTERNS)를 탄다.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts._console import use_utf8_stdout  # noqa: E402

IN_PATH = _REPO_ROOT / "data" / "catalog" / "catalog_classified.jsonl"
OUT_DIR = _REPO_ROOT / "docs" / "catalog"


def _clean(value: str) -> str:
    """리포트에 넣을 문자열을 한 줄로 정리한다.

    개행은 헤딩·리스트 구조를 깨뜨리고, 파이프와 대괄호는 마크다운 링크
    문법을 깨뜨린다. 금감원 제목에는 '[보도자료]' 같은 대괄호 접두가 흔하다.
    """
    text = " ".join(str(value or "").split())
    return text.replace("|", "/").replace("[", "(").replace("]", ")")


def build_gap_report(records: list[dict], generated_on: str) -> str:
    """미매핑 레코드를 신규 유형 후보 목록으로 렌더한다."""
    unmapped = [r for r in records if not r.get("taxonomy_ids")]
    unmapped.sort(key=lambda r: str(r.get("date", "")), reverse=True)

    lines = [
        f"# 신규 신호 유형 후보 — {generated_on}",
        "",
        f"- 전체 {len(records)}건 · **미매핑 {len(unmapped)}건**",
        "- 아래는 현재 taxonomy 45개 유형 중 어디에도 매핑되지 않은 보도자료입니다.",
        "- 이 리포트는 사람 검토용이며 **`taxonomy.py`에 자동으로 반영하지 않습니다.**",
        "  신호 추가는 CLAUDE.md의 '새 신호 유형 추가' 4단계 절차를 따르세요.",
        "",
        "> `body_source`가 `page`·`title_only`인 건은 보도자료 전문이 아니라 게시판",
        "> 요약만으로 분류된 것이라, 미매핑이 실제 신종 수법이 아니라 정보 부족일 수 있습니다.",
        "",
        "---",
        "",
    ]
    if not unmapped:
        lines.append("후보 없음 — 수집된 모든 보도자료가 기존 유형에 매핑되었습니다.")
        return "\n".join(lines) + "\n"

    for rec in unmapped:
        title = _clean(rec.get("title", ""))
        url = rec.get("url", "")
        head = f"[{title}]({url})" if url else title
        summary = _clean(rec.get("summary", ""))
        techniques = ", ".join(_clean(t) for t in (rec.get("techniques") or [])) or "—"
        lines += [
            f"## {rec.get('date','')} — {head}",
            "",
            f"- 요약: {summary}",
            f"- 적발 기법: {techniques}",
            f"- confidence: {rec.get('confidence','low')} · 본문 확보: {rec.get('body_source','unknown')}",
            "",
        ]
    return "\n".join(lines) + "\n"


def main() -> None:
    use_utf8_stdout()
    parser = argparse.ArgumentParser(description="미매핑 수법 → 신규 유형 후보 리포트")
    parser.add_argument("--in", dest="in_path", default=str(IN_PATH))
    parser.add_argument("--out-dir", default=str(OUT_DIR))
    parser.add_argument("--date", default=date.today().isoformat())
    args = parser.parse_args()

    in_path = Path(args.in_path)
    if not in_path.exists():
        raise SystemExit(f"입력 없음: {in_path} — 먼저 classify를 실행하세요")
    records = [json.loads(l) for l in in_path.read_text(encoding="utf-8").splitlines() if l.strip()]

    md = build_gap_report(records, args.date)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"gap-report-{args.date}.md"
    out_path.write_text(md, encoding="utf-8")
    unmapped = sum(1 for r in records if not r.get("taxonomy_ids"))
    print(f"[GAPS] 전체 {len(records)}건 · 미매핑 {unmapped}건 → {out_path}")


if __name__ == "__main__":
    main()
