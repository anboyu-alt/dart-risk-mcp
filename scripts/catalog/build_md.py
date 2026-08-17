"""Phase D — 분류 결과 JSONL → knowledge/manipulation_catalog/*.md 재생성."""
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
from scripts.catalog import render  # noqa: E402
from scripts.catalog.labels import load_labels  # noqa: E402

OUT_DIR = _REPO_ROOT / "dart_risk_mcp" / "knowledge" / "manipulation_catalog"
IN_PATH = _REPO_ROOT / "data" / "catalog" / "catalog_classified.jsonl"


def group_cases(records: list[dict], taxonomy: dict[str, dict]) -> dict[str, dict[str, list[dict]]]:
    """분류 레코드를 {category: {tid: [case]}} 로 묶는다.

    taxonomy_ids가 비었거나 알 수 없는 id는 카탈로그에서 제외한다
    (미매핑 건은 Phase E 갭 리포트가 따로 다룬다).
    """
    grouped: dict[str, dict[str, list[dict]]] = {}
    for rec in records:
        for tid in rec.get("taxonomy_ids") or []:
            entry = taxonomy.get(tid)
            if not entry:
                continue
            cat = entry.get("category", "")
            grouped.setdefault(cat, {}).setdefault(tid, []).append(rec)
    # 사례는 최신순으로 노출
    for cats in grouped.values():
        for tid, cases in cats.items():
            cases.sort(key=lambda c: str(c.get("date", "")), reverse=True)
    return grouped


def write_catalog(records: list[dict], out_dir: Path, generated_on: str) -> list[Path]:
    """8개 카테고리 MD를 전부 쓴다. 사례가 없는 카테고리도 유형 정의는 남긴다."""
    from dart_risk_mcp.core.taxonomy import TAXONOMY

    labels = load_labels()
    grouped = group_cases(records, TAXONOMY)
    out_dir.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    for category, filename in render.CATEGORY_FILES.items():
        tids = [t for t, v in TAXONOMY.items() if v.get("category") == category]
        md = render.render_category(
            category, tids, grouped.get(category, {}), labels, TAXONOMY, generated_on
        )
        path = out_dir / filename
        path.write_text(md, encoding="utf-8")
        written.append(path)
    return written


def write_readme(records: list[dict], out_dir: Path, generated_on: str) -> Path:
    """수집 실적과 본문 확보 경로 분포를 정직하게 기록한다.

    세 범주를 구분한다 — ① 유형 매핑 ② 미매핑(신규 유형 후보, 갭 리포트 대상)
    ③ 1차 스크리닝 제외. classify.py의 build_screened_out_record가 쓰는
    screened_out=True 레코드는 taxonomy_ids가 없다는 점만 보면 ②와 똑같아
    보이지만 "새 유형을 못 찾았다"가 아니라 "애초에 정밀 분류 대상이 아니었다"는
    뜻이다. 스크리닝 탈락이 절대다수라 합쳐서 세면 "미매핑"이 실제보다 훨씬
    커 보여 신종 수법이 쏟아지는 것처럼 오독된다(2026-08-17 재리뷰에서 발견 —
    gaps.py/group_cases는 이미 이 구분을 하고 있었고 여기만 놓쳤었다).
    """
    from collections import Counter

    from dart_risk_mcp.core.taxonomy import TAXONOMY

    grouped = group_cases(records, TAXONOMY)
    screened_out = [r for r in records if r.get("screened_out")]
    classified = [r for r in records if not r.get("screened_out")]
    mapped = sum(1 for r in classified if r.get("taxonomy_ids"))
    unmapped = len(classified) - mapped
    dates = sorted(str(r.get("date", "")) for r in records if r.get("date"))

    # body_source는 스크리닝 탈락분에는 애초에 없다(상세 페이지를 열지 않았으므로).
    # 섞으면 "본문 확보를 못한 건수"가 부풀려 보이므로 정밀 분류 대상만 센다.
    src = Counter(r.get("body_source", "unknown") for r in classified)

    lines = [
        "# 주가조작·불공정거래 유형 카탈로그",
        "",
        "금융감독원·금융위원회 보도자료 기반으로 구축한 불공정거래 유형 및 적발기법 참조 자료.",
        "",
        f"- **수집 기간**: {dates[0] if dates else '—'} ~ {dates[-1] if dates else '—'}",
        f"- **총 레코드**: {len(records)}건",
        f"  - 1차 스크리닝 제외: {len(screened_out)}건 (정밀 분류 대상이 아니었던 건, 신규 유형 후보 아님)",
        f"  - 정밀 분류 대상: {len(classified)}건 (유형 매핑 {mapped}건 / **미매핑(신규 유형 후보) {unmapped}건**)",
        f"- **본문 확보 경로**(정밀 분류 대상 {len(classified)}건 기준): "
        + (", ".join(f"{k} {v}건" for k, v in sorted(src.items())) or "—"),
        f"- **생성일**: {generated_on}",
        # 오픈API는 일일 30회 한도(resultCode 033)가 실증돼 폐기했고, 공공데이터포털
        # 정책브리핑은 이 파이프라인 범위 밖이다(collect.py 참고) — 실제 수집 방식은
        # 금감원 보도자료 게시판 웹 파싱 하나뿐이다.
        "- **데이터 소스**: 금융감독원(FSS) 보도자료 게시판 웹 파싱",
        "",
        "> 본문 확보 경로가 `page`·`title_only`인 레코드는 보도자료 전문이 아니라",
        "> 게시판 요약만으로 분류된 건입니다. 적발기법·인용법조의 정밀도가 낮을 수 있습니다.",
        "",
        "## 목차",
        "",
        "| 파일 | 카테고리 | 유형 수 | 사례 건수 |",
        "|------|----------|---------|----------|",
    ]
    for category, filename in render.CATEGORY_FILES.items():
        tids = [t for t, v in TAXONOMY.items() if v.get("category") == category]
        n_cases = sum(len(v) for v in grouped.get(category, {}).values())
        ko = render.CATEGORY_KO.get(category, category)
        lines.append(f"| [{filename}]({filename}) | {ko} | {len(tids)} | {n_cases} |")
    lines.append("")

    path = out_dir / "README.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main() -> None:
    use_utf8_stdout()
    parser = argparse.ArgumentParser(description="분류 결과 → 카탈로그 MD 생성")
    parser.add_argument("--in", dest="in_path", default=str(IN_PATH))
    parser.add_argument("--out-dir", default=str(OUT_DIR))
    parser.add_argument("--date", default=date.today().isoformat())
    args = parser.parse_args()

    in_path = Path(args.in_path)
    if not in_path.exists():
        raise SystemExit(f"입력 없음: {in_path} — 먼저 classify를 실행하세요")
    records = [json.loads(l) for l in in_path.read_text(encoding="utf-8").splitlines() if l.strip()]

    written = write_catalog(records, Path(args.out_dir), args.date)
    readme = write_readme(records, Path(args.out_dir), args.date)
    print(f"[BUILD] {len(records)}건 → MD {len(written)}개 + {readme.name}")


if __name__ == "__main__":
    main()
