"""기존 카탈로그 MD에서 한글 표시 라벨을 역추출해 labels_ko.json으로 보존한다.

배경: v0.7.5에서 MD 본문(제목·정의·위험 신호)이 한글화됐지만 그 한글 텍스트는
MD 파일에만 있고 core/taxonomy.py에는 반영되지 않았다(name 45개 중 41개 영문).
MD를 재생성하면 영문으로 퇴행하므로, 재생성 전에 한글 자산을 별도 JSON으로
캡처한다. 재실행하면 기존 JSON을 덮어쓰되, MD에 없는 유형의 수기 라벨은 보존한다.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts._console import use_utf8_stdout  # noqa: E402

MD_DIR = _REPO_ROOT / "dart_risk_mcp" / "knowledge" / "manipulation_catalog"
LABELS_PATH = _REPO_ROOT / "data" / "catalog" / "labels_ko.json"

# "## 1.1: 전환가액 하향조정(리픽싱)" 로 유형 블록이 시작한다.
_BLOCK_SPLIT = re.compile(r"(?=^## \d+\.\d+: )", re.M)
_HEADER = re.compile(r"^## (\d+\.\d+):\s*(.+?)\s*$", re.M)
_DEFINITION = re.compile(r"^### 정의\s*\n(.+?)(?=\n^###|\n^---|\Z)", re.M | re.S)
_RED_FLAGS = re.compile(r"^### 위험 신호\s*\n(.+?)(?=\n^###|\n^---|\Z)", re.M | re.S)
_BULLET = re.compile(r"^-\s+(.+?)\s*$", re.M)


def parse_md_labels(md_text: str) -> dict[str, dict]:
    """MD 한 파일에서 {tid: {title, definition, red_flags}} 를 추출한다.

    정의·위험 신호가 없는 블록도 빈 값으로 반환한다(호출부가 폴백을 결정).
    """
    out: dict[str, dict] = {}
    for block in _BLOCK_SPLIT.split(md_text)[1:]:
        header = _HEADER.search(block)
        if not header:
            continue
        tid, title = header.group(1), header.group(2).strip()
        dm = _DEFINITION.search(block)
        rm = _RED_FLAGS.search(block)
        out[tid] = {
            "title": title,
            "definition": dm.group(1).strip() if dm else "",
            "red_flags": _BULLET.findall(rm.group(1)) if rm else [],
        }
    return out


def collect_from_dir(md_dir: Path) -> dict[str, dict]:
    """카탈로그 디렉터리 전체에서 라벨을 모은다."""
    merged: dict[str, dict] = {}
    for path in sorted(md_dir.glob("0*.md")):
        merged.update(parse_md_labels(path.read_text(encoding="utf-8")))
    return merged


def fill_from_taxonomy(labels: dict[str, dict]) -> dict[str, dict]:
    """MD에 없는 유형을 TAXONOMY 값으로 채운다.

    신규 8개(2.7·2.8·3.6·3.7·5.6·5.7·5.8·8.5)는 MD에 아직 없다. 이들은
    description·red_flags가 한국어로 작성돼 있어 그대로 쓸 수 있고, name만
    영문인 경우가 있어 title은 사람이 나중에 다듬을 수 있도록 그대로 넣는다.
    """
    from dart_risk_mcp.core.taxonomy import TAXONOMY

    for tid, entry in TAXONOMY.items():
        if tid in labels:
            continue
        labels[tid] = {
            "title": entry.get("name", tid),
            "definition": entry.get("description", ""),
            "red_flags": list(entry.get("red_flags") or []),
        }
    return labels


def main() -> None:
    use_utf8_stdout()
    parser = argparse.ArgumentParser(description="카탈로그 MD → labels_ko.json 역추출")
    parser.add_argument("--md-dir", default=str(MD_DIR))
    parser.add_argument("--out", default=str(LABELS_PATH))
    args = parser.parse_args()

    labels = collect_from_dir(Path(args.md_dir))
    print(f"[EXTRACT] MD에서 {len(labels)}개 유형 라벨 추출")

    # 기존 JSON의 수기 라벨은 MD보다 우선한다(사람이 다듬은 결과를 덮어쓰지 않음).
    out_path = Path(args.out)
    if out_path.exists():
        prior = json.loads(out_path.read_text(encoding="utf-8"))
        manual = {k: v for k, v in prior.items() if v.get("manual")}
        labels.update(manual)
        print(f"[EXTRACT] 기존 수기 라벨 {len(manual)}건 보존")

    labels = fill_from_taxonomy(labels)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(labels, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"[EXTRACT] {len(labels)}개 유형 → {out_path}")


if __name__ == "__main__":
    main()
