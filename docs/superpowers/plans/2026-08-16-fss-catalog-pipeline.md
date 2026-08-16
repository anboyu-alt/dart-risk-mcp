# 금감원 보도자료 카탈로그 파이프라인 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 금감원·금융위 보도자료를 수집·분류해 `knowledge/manipulation_catalog/*.md`를 이 레포 안에서 재생성하고, 기존 45개 유형에 매핑되지 않는 신종 수법을 신규 신호 후보로 리포트한다.

**Architecture:** `scripts/catalog/` 아래 5단계 배치 파이프라인(collect → extract → classify → build_md → gaps). 중간 산출물은 `data/catalog/*.jsonl`. 분류 기준은 `dart_risk_mcp.core.taxonomy.TAXONOMY` 단일 출처. 본문은 무의존 페이지 파싱을 기본으로 하고 PDF 전문은 1차 스크리닝 통과분에만 선택적으로 받는다.

**Tech Stack:** Python 3.11+, `requests`(HTTP·Anthropic API 직접 호출), 표준 라이브러리(`zipfile`·`re`·`json`·`argparse`), `pypdf`(scripts 전용 optional)

**설계 문서:** `docs/superpowers/specs/2026-08-16-fss-catalog-pipeline-design.md`

## Global Constraints

- **런타임 패키지 `dart_risk_mcp/`의 의존성은 절대 늘리지 않는다.** `pyproject.toml`의 `dependencies`는 `mcp>=1.0.0,<2.0.0`, `requests>=2.28.0` 두 줄로 고정.
- `pypdf`는 `[project.optional-dependencies]`의 `catalog` 그룹에만 넣고, `scripts/catalog/extract.py`에서 `try/except ImportError`로 optional import 한다. 미설치 환경에서 파이프라인이 예외 없이 완주해야 한다.
- **점수·등급을 사용자 출력에 노출하지 않는다(v0.8.5 원칙).** 생성 MD에는 `- **Severity**` / `- **Base Score**` / `- **Crisis Timeline**` 3줄을 그대로 포함하고, 런타임 제거는 기존 `core/catalog.py`의 `_strip_taxonomy_metadata`가 담당한다. 이 3줄의 표기를 바꾸면 정규식이 깨지므로 형식을 정확히 지킬 것.
- 테스트는 **네트워크·LLM을 호출하지 않는다.** 전부 fixture 기반.
- 모든 스크립트는 `from scripts._console import use_utf8_stdout` 후 `main()` 첫 줄에서 호출한다(Windows cp949 UnicodeEncodeError 방지).
- Python 3.11+ 문법 사용 가능(`list[dict]`, `str | None`).
- 커밋 메시지 마지막 줄: `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`

---

## File Structure

**신규 생성**

| 파일 | 책임 |
|---|---|
| `scripts/catalog/__init__.py` | 패키지 마커(빈 파일) |
| `scripts/catalog/labels.py` | 한글 표시 라벨(제목·정의·위험신호) 로드/추출. TAXONOMY 영문 필드를 사용자 노출용 한글로 대체 |
| `scripts/catalog/extract_labels.py` | 기존 MD 8개에서 한글 라벨을 역추출해 `labels_ko.json` 생성 (1회성 + 재실행 가능) |
| `data/catalog/labels_ko.json` | 45개 유형의 한글 제목·정의·위험신호. **커밋 대상**(생성물이 아니라 자산) |
| `scripts/catalog/render.py` | JSONL 분류결과 + 라벨 → MD 문자열. 순수 함수, I/O 없음 |
| `scripts/catalog/build_md.py` | Phase D CLI. render를 호출해 파일 8개 + README 기록 |
| `scripts/catalog/collect.py` | Phase A CLI. FSS·정책브리핑 수집 + 키워드 필터 |
| `scripts/catalog/extract.py` | Phase B. `extract_light`(무의존) / `extract_full`(pypdf) 두 진입점 |
| `scripts/catalog/classify.py` | Phase C. 1차 스크리닝 → 2차 정밀 분류. Anthropic API를 requests로 호출 |
| `scripts/catalog/gaps.py` | Phase E. 미매핑 수법 → 갭 리포트 MD |
| `.github/workflows/refresh-catalog.yml` | 수동 트리거 + 월 1회 cron |
| `tests/test_catalog_labels.py` | 라벨 커버리지·역추출 회귀 |
| `tests/test_catalog_render.py` | MD 렌더 포맷·카테고리 파일명 정합성 |
| `tests/test_catalog_collect.py` | 키워드 필터·레코드 정규화 |
| `tests/test_catalog_extract.py` | 페이지 본문 파싱·body_source 판정·pypdf 부재 degrade |
| `tests/test_catalog_classify.py` | 프롬프트 구성·응답 파싱·미매핑 판정 |
| `tests/fixtures/catalog/` | HTML·JSON·JSONL fixture |

**수정**

| 파일 | 변경 |
|---|---|
| `pyproject.toml` | `[project.optional-dependencies]` 추가 |
| `.gitignore` | `data/catalog/*.jsonl` 제외(단 `labels_ko.json`은 커밋) |
| `CLAUDE.md` | 카탈로그 파이프라인 절 + optional 의존성 경계 명시 |

**의존 방향**: `render.py` ← `labels.py` ← `data/catalog/labels_ko.json`. `render.py`는 네트워크·파일 I/O를 하지 않아 단위 테스트가 쉽다. CLI(`build_md.py`)가 I/O를 담당한다.

---

## Task 순서 근거

`FSS_API_KEY`·`DATA_GO_KR_API_KEY`·`ANTHROPIC_API_KEY`가 아직 없다. **Task 1~4는 키 없이 완주 가능**하도록 배치했다(라벨 보존 → 렌더 → 정합성 테스트 → 페이지 파싱). 키가 필요한 Task 5~7은 뒤에 둔다.

---

### Task 1: 한글 라벨 역추출 — 기존 MD 자산 보존

**왜 첫 태스크인가:** 기존 MD 37개 유형의 한글 제목·정의·위험신호는 v0.7.5 한글화 작업의 산출물로 **MD 파일에만 존재**한다. `TAXONOMY`의 `name`은 45개 중 41개가 영문(`'Refixing (리픽싱)'`), `description`은 37개가 영문이다. MD를 재생성하기 전에 이 한글 자산을 캡처하지 않으면 카탈로그가 영문으로 퇴행한다.

**Files:**
- Create: `scripts/catalog/__init__.py`, `scripts/catalog/extract_labels.py`, `scripts/catalog/labels.py`
- Create: `data/catalog/labels_ko.json` (스크립트가 생성)
- Test: `tests/test_catalog_labels.py`

**Interfaces:**
- Produces:
  - `scripts.catalog.labels.load_labels(path: Path | None = None) -> dict[str, dict]` — `{tid: {"title": str, "definition": str, "red_flags": list[str]}}`
  - `scripts.catalog.labels.label_for(tid: str, labels: dict, taxonomy: dict) -> dict` — 라벨 우선, 없으면 TAXONOMY 폴백
  - `scripts.catalog.extract_labels.parse_md_labels(md_text: str) -> dict[str, dict]` — MD 한 파일에서 유형별 한글 라벨 파싱

- [ ] **Step 1: 패키지 마커 생성**

```bash
mkdir -p scripts/catalog data/catalog tests/fixtures/catalog
printf '"""금감원 보도자료 카탈로그 생성 파이프라인 (배치 전용)."""\n' > scripts/catalog/__init__.py
```

- [ ] **Step 2: 실패하는 테스트 작성**

`tests/test_catalog_labels.py`:

```python
"""카탈로그 한글 라벨 역추출·로드 회귀 테스트.

기존 MD 37개 유형의 한글 제목·정의·위험신호는 v0.7.5 한글화 산출물로 MD에만
존재한다(TAXONOMY의 name은 45개 중 41개가 영문). MD 재생성 시 영문 퇴행을
막으려면 이 라벨을 별도 자산으로 보존해야 한다.
"""
import unittest
from pathlib import Path

from scripts.catalog.extract_labels import parse_md_labels
from scripts.catalog.labels import label_for, load_labels

_MD_DIR = Path(__file__).resolve().parents[1] / "dart_risk_mcp" / "knowledge" / "manipulation_catalog"

_SAMPLE_MD = """# 전환사채·부채 조작
> 카테고리: Convertible Bond & Debt Manipulation  
> 생성일: 2026-04-20  
> 포함 유형: 1.1, 1.2

---

## 1.1: 전환가액 하향조정(리픽싱)

- **Severity**: HIGH
- **Base Score**: 3
- **Crisis Timeline**: 12개월

### 정의
DART 공시 없이 전환가액을 아래쪽으로 조정해 전환 시 지분 희석을 키우는 행위입니다.

### 탐지 키워드
리픽싱, 전환가액조정

### 위험 신호
- 한 번에 10% 이상의 큰 폭 하향 조정
- 6개월 안에 두 번 이상 반복되는 리픽싱

### 금감원·금융위 적발 사례

- **2024-01-23 / 금융감독원** — [제목](https://example.invalid/a)

## 1.2: 콜옵션 남용

- **Severity**: HIGH
- **Base Score**: 3
- **Crisis Timeline**: 12개월

### 정의
콜옵션을 최대주주에게 몰아주는 행위입니다.

### 탐지 키워드
콜옵션

### 위험 신호
- 콜옵션 행사자가 최대주주
"""


class TestParseMdLabels(unittest.TestCase):
    def test_parses_title_definition_and_red_flags(self):
        got = parse_md_labels(_SAMPLE_MD)
        self.assertEqual(sorted(got), ["1.1", "1.2"])
        self.assertEqual(got["1.1"]["title"], "전환가액 하향조정(리픽싱)")
        self.assertTrue(got["1.1"]["definition"].startswith("DART 공시 없이"))
        self.assertEqual(len(got["1.1"]["red_flags"]), 2)
        self.assertEqual(got["1.2"]["red_flags"], ["콜옵션 행사자가 최대주주"])

    def test_definition_excludes_following_sections(self):
        got = parse_md_labels(_SAMPLE_MD)
        self.assertNotIn("탐지 키워드", got["1.1"]["definition"])
        self.assertNotIn("###", got["1.1"]["definition"])

    def test_real_catalog_yields_37_types(self):
        # 실제 카탈로그 8개 파일에서 37개 유형이 파싱돼야 한다(실측 기준선).
        merged = {}
        for p in sorted(_MD_DIR.glob("0*.md")):
            merged.update(parse_md_labels(p.read_text(encoding="utf-8")))
        self.assertEqual(len(merged), 37)
        self.assertEqual(merged["1.1"]["title"], "전환가액 하향조정(리픽싱)")


class TestLoadLabels(unittest.TestCase):
    def test_all_45_taxonomy_ids_have_korean_labels(self):
        from dart_risk_mcp.core.taxonomy import TAXONOMY

        labels = load_labels()
        missing = [t for t in TAXONOMY if t not in labels]
        self.assertEqual(missing, [], f"한글 라벨 누락: {missing}")

    def test_label_for_prefers_labels_over_taxonomy(self):
        from dart_risk_mcp.core.taxonomy import TAXONOMY

        labels = {"1.1": {"title": "한글제목", "definition": "한글정의", "red_flags": ["신호"]}}
        got = label_for("1.1", labels, TAXONOMY)
        self.assertEqual(got["title"], "한글제목")

    def test_label_for_falls_back_to_taxonomy(self):
        from dart_risk_mcp.core.taxonomy import TAXONOMY

        got = label_for("1.1", {}, TAXONOMY)
        self.assertEqual(got["title"], TAXONOMY["1.1"]["name"])
        self.assertEqual(got["red_flags"], TAXONOMY["1.1"]["red_flags"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: 테스트 실행 — 실패 확인**

Run: `python -m pytest tests/test_catalog_labels.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.catalog.extract_labels'`

- [ ] **Step 4: `extract_labels.py` 구현**

`scripts/catalog/extract_labels.py`:

```python
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
```

- [ ] **Step 5: `labels.py` 구현**

`scripts/catalog/labels.py`:

```python
"""카탈로그 한글 표시 라벨 로더.

TAXONOMY의 name·description은 상당수가 영문이라 사용자 노출용으로 쓸 수 없다
(name 45개 중 41개 영문 — 2026-08-16 실측). labels_ko.json이 한글 표시 텍스트의
단일 출처이며, 누락 시에만 TAXONOMY로 폴백한다.
"""
from __future__ import annotations

import json
from pathlib import Path

_DEFAULT_PATH = Path(__file__).resolve().parents[2] / "data" / "catalog" / "labels_ko.json"


def load_labels(path: Path | None = None) -> dict[str, dict]:
    """labels_ko.json을 읽는다. 파일이 없으면 빈 dict(전부 TAXONOMY 폴백)."""
    p = path or _DEFAULT_PATH
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def label_for(tid: str, labels: dict[str, dict], taxonomy: dict[str, dict]) -> dict:
    """유형 하나의 표시 라벨을 결정한다. 라벨 우선, 없으면 TAXONOMY 폴백."""
    entry = taxonomy.get(tid, {})
    lab = labels.get(tid) or {}
    return {
        "title": lab.get("title") or entry.get("name", tid),
        "definition": lab.get("definition") or entry.get("description", ""),
        "red_flags": lab.get("red_flags") or list(entry.get("red_flags") or []),
    }
```

- [ ] **Step 6: 역추출 실행 — labels_ko.json 생성**

Run: `python scripts/catalog/extract_labels.py`
Expected: `[EXTRACT] MD에서 37개 유형 라벨 추출` → `[EXTRACT] 45개 유형 → .../labels_ko.json`

- [ ] **Step 7: 테스트 실행 — 통과 확인**

Run: `python -m pytest tests/test_catalog_labels.py -v`
Expected: 6 passed

- [ ] **Step 8: 커밋**

```bash
git add scripts/catalog/__init__.py scripts/catalog/extract_labels.py scripts/catalog/labels.py data/catalog/labels_ko.json tests/test_catalog_labels.py
git commit -m "$(cat <<'EOF'
feat(catalog): 기존 MD의 한글 라벨을 labels_ko.json으로 보존

TAXONOMY의 name은 45개 중 41개가 영문이라 MD를 재생성하면 카탈로그가
영문으로 퇴행한다(v0.7.5 한글화 산출물이 MD에만 존재). 재생성 전에
37개 유형의 한글 제목·정의·위험신호를 역추출해 자산으로 고정하고,
MD에 없는 신규 8개는 TAXONOMY 한국어 필드로 채운다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: MD 렌더러 (Phase D 코어)

**Files:**
- Create: `scripts/catalog/render.py`
- Test: `tests/test_catalog_render.py`

**Interfaces:**
- Consumes: `scripts.catalog.labels.label_for`
- Produces:
  - `render.CATEGORY_FILES: dict[str, str]` — 영문 category → 파일명. `core/catalog.py`의 `_CATEGORY_TO_FILE`과 동일해야 함
  - `render.CATEGORY_KO: dict[str, str]` — 영문 category → 한글 제목
  - `render.render_category(category: str, tids: list[str], cases_by_tid: dict[str, list[dict]], labels: dict, taxonomy: dict, generated_on: str) -> str`
  - `render.render_case(case: dict) -> str`
  - `render.aggregate_techniques(cases: list[dict], top_n: int = 10) -> list[tuple[str, int]]`
  - `render.aggregate_laws(cases: list[dict], top_n: int = 10) -> list[tuple[str, int]]`

> **추가 요구 (2026-08-16 Task 2 리뷰에서 발견, 사용자 결정 "둘 다 보존")**
>
> 계획 최초 작성 시 기존 MD의 섹션 2개를 누락했다. 실측하니 37개 유형 **전부**에 존재한다:
> `### 인용 법조`(37블록/142줄)와 `### 기존 현장 기사 인용`(37블록/49줄).
> 후자는 보도자료에서 파생될 수 없는 **수기 자산**이다(예: "위메이드 800억원 CB조기상환",
> "리픽싱모니터"). 이 상태로 `build_md.py`가 실제 파일을 덮어쓰면 191줄이 조용히 사라진다.
>
> 따라서:
> 1. `render_category`의 섹션 순서는 실제 MD와 같아야 한다 —
>    정의 → 탐지 키워드 → 위험 신호 → 금감원·금융위 적발 사례 → 적발 기법 종합 →
>    **인용 법조** → **기존 현장 기사 인용**
> 2. `인용 법조`는 사례의 `laws`를 집계해 재생성한다(`aggregate_laws`). `aggregate_techniques`와
>    동형이므로 공통 헬퍼 `_aggregate_field(cases, field, top_n)`로 묶고 둘은 그 얇은 래퍼로 둔다
>    (리뷰 Minor 지적 반영 — 로직 블록 복제 금지)
> 3. `기존 현장 기사 인용`은 Task 1의 한글 라벨과 같은 방식으로 보존한다 —
>    `extract_labels.parse_md_labels`가 `field_articles: list[str]`를 추가로 추출하고,
>    `labels.label_for`가 이를 반환하며, `labels_ko.json`을 재생성해 커밋한다.
>    라벨에 없으면 빈 리스트이고, 이때 섹션 본문은 `—`로 렌더한다

`case` 레코드 스키마(Task 6의 classify 출력과 일치):
```python
{"date": "2024-01-23", "agency": "금융감독원", "title": "...", "url": "https://...",
 "techniques": ["..."], "sanctions": ["..."], "laws": ["..."], "summary": "...",
 "taxonomy_ids": ["1.1"], "confidence": "high", "body_source": "pdf"}
```

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_catalog_render.py`:

```python
"""카탈로그 MD 렌더러 회귀 테스트.

핵심 계약 2가지:
1. 파일명 매핑이 core/catalog.py의 _CATEGORY_TO_FILE과 정확히 일치해야 한다.
   불일치하면 load_catalog_excerpt가 예외 없이 빈 문자열을 반환한다(죽은 배선).
2. Severity/Base Score/Crisis Timeline 3줄의 표기가 정확해야 한다.
   core/catalog.py의 _TAXONOMY_META_LINE 정규식이 이 형식에 의존한다.
"""
import re
import unittest

from dart_risk_mcp.core.catalog import _CATEGORY_TO_FILE, _TAXONOMY_META_LINE
from dart_risk_mcp.core.taxonomy import TAXONOMY
from scripts.catalog import render

_CASE = {
    "date": "2024-01-23",
    "agency": "금융감독원",
    "title": "「전환사채 시장 건전성 제고 간담회」 개최",
    "url": "https://www.fss.or.kr/fss/bbs/B0000188/view.do?nttId=133310&menuNo=200218",
    "techniques": ["전환가액 조정 기준 명확화 부재", "콜옵션 행사자 지정 공시 의무화"],
    "sanctions": [],
    "laws": ["자본시장법"],
    "summary": "제도 개선안을 발표했습니다.",
    "taxonomy_ids": ["1.1"],
    "confidence": "high",
    "body_source": "pdf",
}


class TestCategoryMapping(unittest.TestCase):
    def test_file_mapping_matches_core_catalog(self):
        self.assertEqual(render.CATEGORY_FILES, _CATEGORY_TO_FILE)

    def test_every_taxonomy_category_has_korean_title(self):
        cats = {v["category"] for v in TAXONOMY.values()}
        missing = [c for c in cats if c not in render.CATEGORY_KO]
        self.assertEqual(missing, [])


class TestRenderCategory(unittest.TestCase):
    def _render(self):
        labels = {"1.1": {"title": "전환가액 하향조정(리픽싱)",
                          "definition": "DART 공시 없이 전환가액을 조정하는 행위입니다.",
                          "red_flags": ["한 번에 10% 이상의 큰 폭 하향 조정"]}}
        return render.render_category(
            "Convertible Bond & Debt Manipulation", ["1.1"], {"1.1": [_CASE]},
            labels, TAXONOMY, "2026-08-16",
        )

    def test_uses_korean_title_not_taxonomy_name(self):
        md = self._render()
        self.assertIn("## 1.1: 전환가액 하향조정(리픽싱)", md)
        self.assertNotIn("Refixing (리픽싱)", md)

    def test_metadata_lines_match_strip_regex(self):
        # core/catalog.py가 이 3줄을 제거할 수 있어야 한다.
        md = self._render()
        self.assertIn("- **Severity**: HIGH", md)
        self.assertIn("- **Base Score**: 3", md)
        self.assertIn("- **Crisis Timeline**: 12개월", md)
        stripped = _TAXONOMY_META_LINE.sub("", md)
        self.assertNotIn("**Severity**", stripped)
        self.assertNotIn("**Base Score**", stripped)
        self.assertNotIn("**Crisis Timeline**", stripped)

    def test_header_and_sections_present(self):
        md = self._render()
        self.assertTrue(md.startswith("# 전환사채·부채 조작"))
        self.assertIn("> 카테고리: Convertible Bond & Debt Manipulation", md)
        self.assertIn("> 생성일: 2026-08-16", md)
        self.assertIn("> 포함 유형: 1.1", md)
        for section in ("### 정의", "### 탐지 키워드", "### 위험 신호",
                        "### 금감원·금융위 적발 사례", "### 적발 기법 종합"):
            self.assertIn(section, md)

    def test_case_rendered_with_link_and_fields(self):
        md = self._render()
        self.assertIn("[「전환사채 시장 건전성 제고 간담회」 개최](https://www.fss.or.kr", md)
        self.assertIn("적발 기법: 전환가액 조정 기준 명확화 부재", md)
        self.assertIn("제재: —", md)  # 빈 리스트는 em dash
        self.assertIn("인용 법조: 자본시장법", md)

    def test_type_without_cases_omits_case_section_body(self):
        labels = {"1.2": {"title": "콜옵션 남용", "definition": "정의", "red_flags": ["신호"]}}
        md = render.render_category(
            "Convertible Bond & Debt Manipulation", ["1.2"], {}, labels, TAXONOMY, "2026-08-16")
        self.assertIn("## 1.2: 콜옵션 남용", md)
        self.assertIn("적발 사례 없음", md)


class TestRenderCase(unittest.TestCase):
    def test_pipe_and_newline_sanitized(self):
        case = dict(_CASE, title="제목|파이프\n줄바꿈")
        out = render.render_case(case)
        self.assertNotIn("\n줄바꿈", out.split("\n")[0])
        self.assertNotIn("|파이프", out)


class TestAggregate(unittest.TestCase):
    def test_counts_and_sorts_desc(self):
        cases = [{"techniques": ["A", "B"]}, {"techniques": ["A"]}]
        self.assertEqual(render.aggregate_techniques(cases), [("A", 2), ("B", 1)])

    def test_respects_top_n(self):
        cases = [{"techniques": [f"T{i}" for i in range(20)]}]
        self.assertEqual(len(render.aggregate_techniques(cases, top_n=5)), 5)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 테스트 실행 — 실패 확인**

Run: `python -m pytest tests/test_catalog_render.py -v`
Expected: FAIL — `ImportError: cannot import name 'render' from 'scripts.catalog'`

- [ ] **Step 3: `render.py` 구현**

`scripts/catalog/render.py`:

```python
"""분류 결과 → 카탈로그 MD 렌더링. 순수 함수만 두고 I/O는 build_md.py가 담당한다.

포맷은 기존 knowledge/manipulation_catalog/*.md와 바이트 수준으로 호환되어야 한다.
특히 `- **Severity**` 3줄은 core/catalog.py의 _TAXONOMY_META_LINE 정규식이
런타임에 제거하는 대상이라 표기를 바꾸면 점수·등급이 사용자에게 노출된다(v0.8.5 위반).
"""
from __future__ import annotations

from collections import Counter

from .labels import label_for

# core/catalog.py의 _CATEGORY_TO_FILE과 동일해야 한다(테스트가 기계적으로 검증).
CATEGORY_FILES: dict[str, str] = {
    "Convertible Bond & Debt Manipulation": "01_cb_debt.md",
    "Capital Structure Manipulation": "02_capital_structure.md",
    "Ownership & Control": "03_ownership_control.md",
    "Governance & Disclosure": "04_governance.md",
    "Corporate Action Manipulation": "05_corporate_action.md",
    "Accounting & Financial Reporting": "06_accounting.md",
    "Market Manipulation & Trading": "07_market_manipulation.md",
    "Crisis & Distress Signals": "08_crisis_distress.md",
}

CATEGORY_KO: dict[str, str] = {
    "Convertible Bond & Debt Manipulation": "전환사채·부채 조작",
    "Capital Structure Manipulation": "자본구조 조작",
    "Ownership & Control": "지분·지배권",
    "Governance & Disclosure": "거버넌스·공시",
    "Corporate Action Manipulation": "기업행동 조작",
    "Accounting & Financial Reporting": "회계·재무보고",
    "Market Manipulation & Trading": "시장조작·거래",
    "Crisis & Distress Signals": "위기·부실 신호",
}


def _cell(value: str) -> str:
    """개행·파이프를 정리한다(MD 표·리스트가 깨지지 않도록)."""
    return " ".join(str(value or "").replace("|", "/").split())


def _join(items, empty: str = "—") -> str:
    vals = [_cell(x) for x in (items or []) if _cell(x)]
    return ", ".join(vals) if vals else empty


def render_case(case: dict) -> str:
    """적발 사례 한 건을 렌더한다. 줄 끝 두 칸 공백은 MD 줄바꿈이라 유지한다."""
    title = _cell(case.get("title", "제목미상"))
    url = _cell(case.get("url", ""))
    head = f"[{title}]({url})" if url else title
    lines = [
        f"- **{_cell(case.get('date', ''))} / {_cell(case.get('agency', ''))}** — {head}  ",
        f"  - 적발 기법: {_join(case.get('techniques'))}  ",
        f"  - 제재: {_join(case.get('sanctions'))}  ",
        f"  - 인용 법조: {_join(case.get('laws'))}  ",
    ]
    summary = _cell(case.get("summary", ""))
    if summary:
        lines.append(f"  - 요약: {summary}")
    return "\n".join(lines)


def aggregate_techniques(cases: list[dict], top_n: int = 10) -> list[tuple[str, int]]:
    """사례들의 적발 기법을 빈도순으로 집계한다."""
    counter: Counter = Counter()
    for case in cases:
        for tech in case.get("techniques") or []:
            cleaned = _cell(tech)
            if cleaned:
                counter[cleaned] += 1
    return counter.most_common(top_n)


def render_category(
    category: str,
    tids: list[str],
    cases_by_tid: dict[str, list[dict]],
    labels: dict[str, dict],
    taxonomy: dict[str, dict],
    generated_on: str,
) -> str:
    """카테고리 MD 한 파일 전체를 렌더한다."""
    ko = CATEGORY_KO.get(category, category)
    ordered = sorted(tids, key=lambda t: [int(x) for x in t.split(".")])
    out: list[str] = [
        f"# {ko}",
        f"> 카테고리: {category}  ",
        f"> 생성일: {generated_on}  ",
        f"> 포함 유형: {', '.join(ordered)}",
        "",
        "---",
        "",
    ]
    for tid in ordered:
        entry = taxonomy.get(tid, {})
        lab = label_for(tid, labels, taxonomy)
        cases = cases_by_tid.get(tid) or []
        out += [
            f"## {tid}: {lab['title']}",
            "",
            f"- **Severity**: {entry.get('severity', '')}",
            f"- **Base Score**: {entry.get('base_score', '')}",
            f"- **Crisis Timeline**: {entry.get('crisis_timeline_months', '')}개월",
            "",
            "### 정의",
            lab["definition"],
            "",
            "### 탐지 키워드",
            ", ".join(entry.get("keywords") or []),
            "",
            "### 위험 신호",
        ]
        out += [f"- {flag}" for flag in lab["red_flags"]]
        out += ["", "### 금감원·금융위 적발 사례", ""]
        if cases:
            out += [render_case(c) for c in cases]
        else:
            out.append("적발 사례 없음 — 수집 범위에서 해당 유형의 보도자료가 확인되지 않았습니다.")
        out += ["", "### 적발 기법 종합", ""]
        agg = aggregate_techniques(cases)
        if agg:
            out += [f"- {tech} ({n}건)" for tech, n in agg]
        else:
            out.append("—")
        out += ["", "---", ""]
    return "\n".join(out).rstrip() + "\n"
```

- [ ] **Step 4: 테스트 실행 — 통과 확인**

Run: `python -m pytest tests/test_catalog_render.py -v`
Expected: 10 passed

- [ ] **Step 5: 커밋**

```bash
git add scripts/catalog/render.py tests/test_catalog_render.py
git commit -m "$(cat <<'EOF'
feat(catalog): MD 렌더러 + 카테고리 파일명 정합성 테스트

_CATEGORY_TO_FILE 불일치는 load_catalog_excerpt를 예외 없이 빈 문자열로
만들기 때문에(죽은 배선) 기계적으로 검증한다. Severity 3줄 표기도
core/catalog.py의 제거 정규식이 의존하므로 회귀 테스트로 고정한다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Phase D CLI — 파일 생성 + 발췌 무결성 검증

**Files:**
- Create: `scripts/catalog/build_md.py`
- Create: `tests/fixtures/catalog/classified_sample.jsonl`
- Modify: `tests/test_catalog_render.py` (종단 테스트 추가)

**Interfaces:**
- Consumes: `render.render_category`, `render.CATEGORY_FILES`, `labels.load_labels`
- Produces: `build_md.group_cases(records: list[dict], taxonomy: dict) -> dict[str, dict[str, list[dict]]]` — `{category: {tid: [case, ...]}}`
- Produces: `build_md.write_catalog(records, out_dir: Path, generated_on: str) -> list[Path]`

- [ ] **Step 1: fixture 작성**

`tests/fixtures/catalog/classified_sample.jsonl` (한 줄에 JSON 하나):

```json
{"date": "2024-01-23", "agency": "금융감독원", "title": "전환사채 시장 건전성 제고 간담회 개최", "url": "https://www.fss.or.kr/fss/bbs/B0000188/view.do?nttId=133310&menuNo=200218", "techniques": ["콜옵션 행사자 지정 공시 의무화"], "sanctions": [], "laws": ["자본시장법"], "summary": "제도 개선안 발표", "taxonomy_ids": ["1.1"], "confidence": "high", "body_source": "pdf"}
{"date": "2026-04-19", "agency": "금융감독원", "title": "상폐회피 목적 허위 자기자본 확충 적발", "url": "https://www.fss.or.kr/fss/bbs/B0000188/view.do?nttId=999999&menuNo=200218", "techniques": ["횡령자금 유상증자"], "sanctions": ["검찰 이첩"], "laws": ["자본시장법 제178조"], "summary": "상장폐지 회피 목적 가장납입", "taxonomy_ids": ["8.1", "2.3"], "confidence": "high", "body_source": "pdf"}
{"date": "2025-03-10", "agency": "금융위원회", "title": "투자조합 페이퍼컴퍼니 CB 가장납입", "url": "https://www.fss.or.kr/fss/bbs/B0000188/view.do?nttId=888888&menuNo=200218", "techniques": ["가장납입"], "sanctions": [], "laws": [], "summary": "무자본 인수 구조", "taxonomy_ids": [], "confidence": "low", "body_source": "page"}
```

- [ ] **Step 2: 실패하는 테스트 추가**

`tests/test_catalog_render.py` 하단에 추가:

```python
class TestBuildMdEndToEnd(unittest.TestCase):
    """생성된 MD로 load_catalog_excerpt가 실제 발췌를 내는지 종단 검증.

    catalog.py docstring이 경고하는 '죽은 배선'(조용히 빈 문자열) 회귀 방지.
    """

    def test_writes_eight_files_and_excerpt_is_non_empty(self):
        import json
        import tempfile
        from pathlib import Path
        from unittest import mock

        from scripts.catalog import build_md

        fixture = Path(__file__).parent / "fixtures" / "catalog" / "classified_sample.jsonl"
        records = [json.loads(line) for line in fixture.read_text(encoding="utf-8").splitlines() if line.strip()]

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            written = build_md.write_catalog(records, out, "2026-08-16")
            self.assertEqual(len(written), 8)
            names = sorted(p.name for p in written)
            self.assertEqual(names, sorted(render.CATEGORY_FILES.values()))

            # 생성된 MD를 카탈로그 디렉터리로 바꿔치기해 발췌가 비지 않는지 확인
            from dart_risk_mcp.core import catalog as core_catalog

            with mock.patch.object(core_catalog, "_CATALOG_DIR", out):
                excerpt = core_catalog.load_catalog_excerpt(["1.1", "8.1"])
            self.assertTrue(excerpt.strip(), "발췌가 비어있음 — 죽은 배선 회귀")
            self.assertIn("카탈로그 선례", excerpt)
            self.assertNotIn("**Severity**", excerpt)  # 런타임 제거 확인

    def test_unmapped_records_excluded_from_catalog(self):
        from scripts.catalog import build_md
        from dart_risk_mcp.core.taxonomy import TAXONOMY

        records = [{"taxonomy_ids": [], "title": "미매핑", "techniques": []}]
        grouped = build_md.group_cases(records, TAXONOMY)
        self.assertEqual(sum(len(v) for v in grouped.values()), 0)
```

- [ ] **Step 3: 테스트 실행 — 실패 확인**

Run: `python -m pytest tests/test_catalog_render.py::TestBuildMdEndToEnd -v`
Expected: FAIL — `ImportError: cannot import name 'build_md'`

- [ ] **Step 4: `build_md.py` 구현**

`scripts/catalog/build_md.py`:

```python
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
    """수집 실적과 본문 확보 경로 분포를 정직하게 기록한다."""
    from collections import Counter

    from dart_risk_mcp.core.taxonomy import TAXONOMY

    grouped = group_cases(records, TAXONOMY)
    src = Counter(r.get("body_source", "unknown") for r in records)
    dates = sorted(str(r.get("date", "")) for r in records if r.get("date"))
    mapped = sum(1 for r in records if r.get("taxonomy_ids"))

    lines = [
        "# 주가조작·불공정거래 유형 카탈로그",
        "",
        "금융감독원·금융위원회 보도자료 기반으로 구축한 불공정거래 유형 및 적발기법 참조 자료.",
        "",
        f"- **수집 기간**: {dates[0] if dates else '—'} ~ {dates[-1] if dates else '—'}",
        f"- **총 레코드**: {len(records)}건 (유형 매핑 {mapped}건 / 미매핑 {len(records) - mapped}건)",
        f"- **본문 확보 경로**: " + ", ".join(f"{k} {v}건" for k, v in sorted(src.items())),
        f"- **생성일**: {generated_on}",
        "- **데이터 소스**: 금융감독원 오픈API, 공공데이터포털 정책브리핑",
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
```

- [ ] **Step 5: 테스트 실행 — 통과 확인**

Run: `python -m pytest tests/test_catalog_render.py -v`
Expected: 12 passed

- [ ] **Step 6: 기존 카탈로그 회귀 확인 (덮어쓰지 않고)**

Run: `python -m pytest tests/test_catalog_order.py tests/test_golden_output_hygiene.py -v`
Expected: all passed — 이 시점에는 아직 실제 MD를 교체하지 않았으므로 전부 통과해야 한다

- [ ] **Step 7: 커밋**

```bash
git add scripts/catalog/build_md.py tests/fixtures/catalog/classified_sample.jsonl tests/test_catalog_render.py
git commit -m "$(cat <<'EOF'
feat(catalog): Phase D — 분류 결과 → MD 생성 CLI

생성 MD로 load_catalog_excerpt가 비어있지 않은 발췌를 내는지 종단 검증하고,
런타임에서 Severity 3줄이 제거되는지도 함께 확인한다. README에 본문 확보
경로(pdf/page/title_only) 분포를 기록해 요약 기반 분류의 한계를 정직하게 표기.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Phase B — 본문 확보 (키 불필요 부분)

**Files:**
- Create: `scripts/catalog/extract.py`
- Create: `tests/fixtures/catalog/fss_view_page.html`
- Test: `tests/test_catalog_extract.py`

**Interfaces:**
- Produces:
  - `extract.decode_page(raw: bytes) -> tuple[str, bool]` — (텍스트, 신뢰 가능 여부)
  - `extract.parse_page_body(html: str) -> str` — `bd-view` 영역 본문 텍스트
  - `extract.parse_attachment_urls(html: str) -> dict[str, str]` — `{"hwp": url, "pdf": url}` (`fileSn=1`/`fileSn=2`)
  - `extract.extract_light(record: dict, fetch=None) -> dict` — `body`/`body_source`/`body_chars` 채운 레코드
  - `extract.extract_full(record: dict, fetch=None) -> str | None` — PDF 전문. pypdf 없거나 실패 시 `None`
  - `extract.PYPDF_AVAILABLE: bool`

> **추가 요구 (2026-08-16 Task 4 리뷰에서 발견, 사용자 결정 "지금 고친다")**
>
> 최초 코드는 `fetch(url).decode("utf-8", errors="replace")`로 UTF-8만 가정했다. 한국
> 정부 사이트는 euc-kr/cp949를 섞어 쓰며, 이 구조는 비 UTF-8 페이지에서 **예외를 던지지
> 않고** U+FFFD로 오염된 본문을 `body_source="page"`로 통과시킨다 — 12,000건 배치에서
> 품질이 눈에 띄지 않게 무너진다. 이 레포에는 이미 관례가 있다:
> `dart_client._decode_zip_file`(+`cb_extractor`·`investor_extractor`)의
> `("utf-8", "euc-kr", "cp949")` 순차 시도.
>
> 따라서 `decode_page(raw) -> (text, trusted)`를 두고:
> - 세 인코딩을 차례로 시도해 성공하면 `(text, True)`
> - 셋 다 실패하면 `errors="replace"`로 살리되, U+FFFD 비율이 **1% 초과면 `(text, False)`**
>   (사소한 바이트 깨짐으로 멀쩡한 본문을 버리지 않으면서, 인코딩을 통째로 잘못 읽은
>   경우는 잡는 기준). 빈 바이트열은 `("", True)`
> - `extract_light`는 `trusted`가 False면 그 본문을 쓰지 않고 `title_only`로 폴백하며,
>   **첨부 URL 파싱도 하지 않는다**(오염된 HTML에서 뽑은 URL은 신뢰할 수 없다)

`fetch` 인자는 테스트 주입용 콜러블(`fetch(url) -> bytes`). 기본값은 `requests` 사용.

- [ ] **Step 1: fixture 작성**

`tests/fixtures/catalog/fss_view_page.html` — 실제 구조를 축약한 것(2026-08-16 nttId=133239 실측 구조):

```html
<html><body>
<div class="bd-view">
  <h2>‘무늬만’ 신규사업, 불공정거래행위 집중조사 및 투자자 유의사항 안내</h2>
  <span>등록일 2024-01-18</span><span>조회수 3334</span>
  <div class="file-list__set">
    <a href="/fss/cmmn/file/fileDown.do?menuNo=200218&amp;atchFileId=ABC123&amp;fileSn=1&amp;bbsId=">
      <span class="file-name"><i class="ico-hwp"></i><span class="name">240119 (보도자료).hwp <span>(파일크기: 1,173KB)</span></span></span>
    </a>
    <a href="https://www.fss.or.kr/fss/etc/docView/view.do?menuNo=200218&amp;viewType=BODY&amp;atchFileId=ABC123&amp;fileSn=1" class="b-viewer">문서뷰어</a>
    <a href="/fss/cmmn/file/fileDown.do?menuNo=200218&amp;atchFileId=ABC123&amp;fileSn=2&amp;bbsId=">
      <span class="file-name"><span class="name">240119 (보도자료).pdf <span>(파일크기: 518KB)</span></span></span>
    </a>
  </div>
  <p>□ 상장기업 A사는 신규사업 진출을 공시했으나 실제 사업 실적이 없었습니다.</p>
  <p>□ 금융감독원은 불공정거래 혐의로 조사에 착수했습니다.</p>
</div>
<div class="bd-view-nav">이전글 다음글</div>
<footer>금융감독원</footer>
</body></html>
```

- [ ] **Step 2: 실패하는 테스트 작성**

`tests/test_catalog_extract.py`:

```python
"""Phase B 본문 확보 회귀 테스트.

실측 전제(2026-08-16): 금감원 첨부는 fileSn=1이 구형 HWP(OLE, D0CF11E0),
fileSn=2가 PDF다. HWP는 ZIP이 아니라 표준 라이브러리로 파싱할 수 없으므로
본문 확보는 PDF(optional pypdf) 또는 게시판 페이지 요약에 의존한다.
"""
import unittest
from pathlib import Path
from unittest import mock

from scripts.catalog import extract

_FIXTURE = Path(__file__).parent / "fixtures" / "catalog" / "fss_view_page.html"


class TestParsePage(unittest.TestCase):
    def setUp(self):
        self.html = _FIXTURE.read_text(encoding="utf-8")

    def test_body_text_extracted(self):
        body = extract.parse_page_body(self.html)
        self.assertIn("신규사업 진출을 공시했으나", body)
        self.assertIn("불공정거래 혐의로 조사", body)

    def test_body_excludes_nav_and_footer(self):
        body = extract.parse_page_body(self.html)
        self.assertNotIn("이전글", body)
        self.assertNotIn("다음글", body)

    def test_attachment_urls_by_filesn(self):
        urls = extract.parse_attachment_urls(self.html)
        self.assertTrue(urls["hwp"].endswith("fileSn=1&bbsId="))
        self.assertTrue(urls["pdf"].endswith("fileSn=2&bbsId="))
        self.assertTrue(urls["pdf"].startswith("https://www.fss.or.kr/"))

    def test_amp_entities_decoded(self):
        urls = extract.parse_attachment_urls(self.html)
        self.assertNotIn("&amp;", urls["pdf"])


class TestExtractLight(unittest.TestCase):
    def test_uses_page_body_when_available(self):
        html = _FIXTURE.read_text(encoding="utf-8")
        rec = {"url": "https://www.fss.or.kr/x", "title": "제목", "summary": "요약"}
        got = extract.extract_light(rec, fetch=lambda u: html.encode("utf-8"))
        self.assertEqual(got["body_source"], "page")
        self.assertIn("신규사업", got["body"])
        self.assertEqual(got["body_chars"], len(got["body"]))

    def test_falls_back_to_title_when_fetch_fails(self):
        rec = {"url": "https://www.fss.or.kr/x", "title": "제목", "summary": "요약본문"}
        def boom(url):
            raise OSError("network down")
        got = extract.extract_light(rec, fetch=boom)
        self.assertEqual(got["body_source"], "title_only")
        self.assertIn("제목", got["body"])
        self.assertIn("요약본문", got["body"])

    def test_no_url_falls_back_without_fetch(self):
        rec = {"url": "", "title": "제목", "summary": "요약"}
        got = extract.extract_light(rec, fetch=lambda u: b"")
        self.assertEqual(got["body_source"], "title_only")


class TestExtractFull(unittest.TestCase):
    def test_returns_none_when_pypdf_missing(self):
        rec = {"url": "https://www.fss.or.kr/x",
               "attachment_urls": {"pdf": "https://www.fss.or.kr/p.pdf"}}
        with mock.patch.object(extract, "PYPDF_AVAILABLE", False):
            self.assertIsNone(extract.extract_full(rec, fetch=lambda u: b"%PDF-1.4"))

    def test_returns_none_on_fetch_failure(self):
        rec = {"attachment_urls": {"pdf": "https://www.fss.or.kr/p.pdf"}}
        def boom(url):
            raise OSError("timeout")
        self.assertIsNone(extract.extract_full(rec, fetch=boom))

    def test_returns_none_without_pdf_url(self):
        self.assertIsNone(extract.extract_full({}, fetch=lambda u: b""))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: 테스트 실행 — 실패 확인**

Run: `python -m pytest tests/test_catalog_extract.py -v`
Expected: FAIL — `ImportError: cannot import name 'extract'`

- [ ] **Step 4: `extract.py` 구현**

`scripts/catalog/extract.py`:

```python
"""Phase B — 보도자료 본문 확보.

실측(2026-08-16, 표본 5건): 금감원 첨부는 fileSn=1이 구형 HWP(OLE 복합문서,
매직 D0CF11E0)이고 fileSn=2가 PDF다. HWP는 ZIP이 아니라 zipfile로 열 수 없고,
문서뷰어(viewType=BODY)는 vod2 이미지 렌더러라 텍스트가 없다. 따라서 전문은
PDF에서만 얻을 수 있으며 pypdf가 필요하다.

비용 통제를 위해 진입점을 둘로 나눈다:
- extract_light: 전량 대상, 의존성 없음. 게시판 페이지 본문(실측 505~1,097자)
- extract_full : 1차 스크리닝 통과분만. PDF 다운로드 + pypdf
"""
from __future__ import annotations

import html as html_mod
import io
import re

import requests

try:  # pypdf는 scripts 전용 optional 의존성
    from pypdf import PdfReader

    PYPDF_AVAILABLE = True
except ImportError:  # 미설치 환경에서도 요약 모드로 완주한다
    PdfReader = None  # type: ignore[assignment]
    PYPDF_AVAILABLE = False

_BASE = "https://www.fss.or.kr"
_TIMEOUT = 30
_HEADERS = {"User-Agent": "dart-risk-mcp catalog builder"}

# 본문 영역: <div class="bd-view"> ~ 다음 네비게이션/푸터 직전
_BODY_BLOCK = re.compile(
    r'<div[^>]*class="[^"]*bd-view[^"]*"[\s\S]*?'
    r'(?=<div[^>]*class="[^"]*bd-view-nav|<footer)',
    re.I,
)
_SCRIPT_STYLE = re.compile(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", re.I)
_TAG = re.compile(r"<[^>]+>")
_FILE_LINK = re.compile(r'href="([^"]*fileDown\.do\?[^"]*fileSn=(\d)[^"]*)"', re.I)

# 인코딩을 통째로 잘못 읽었는지 판별하는 대체문자 비율 임계. 바이트 몇 개가 깨진
# 정상 페이지를 버리지 않으면서, euc-kr 페이지를 utf-8로 읽은 경우는 걸러낸다.
_REPLACEMENT_RATIO_LIMIT = 0.01


def decode_page(raw: bytes) -> tuple[str, bool]:
    """페이지 바이트를 디코딩한다. 반환: (텍스트, 신뢰 가능 여부).

    레포 관례(dart_client._decode_zip_file)대로 utf-8 → euc-kr → cp949를 차례로
    시도한다. 셋 다 실패하면 errors="replace"로 살려내되, 대체 문자(U+FFFD)가
    본문에 과다하면 신뢰 불가로 표시한다 — 조용히 오염된 본문이 정상 본문인 척
    분류 단계로 흘러가는 것을 막기 위함이다.
    """
    if not raw:
        return "", True
    for enc in ("utf-8", "euc-kr", "cp949"):
        try:
            return raw.decode(enc), True
        except UnicodeDecodeError:
            continue
    text = raw.decode("utf-8", errors="replace")
    ratio = text.count("�") / len(text) if text else 0.0
    return text, ratio <= _REPLACEMENT_RATIO_LIMIT


def _clean_html(fragment: str) -> str:
    text = _SCRIPT_STYLE.sub(" ", fragment)
    text = _TAG.sub(" ", text)
    text = html_mod.unescape(text)
    return " ".join(text.split())


def parse_page_body(page_html: str) -> str:
    """게시판 상세 페이지에서 본문 영역 텍스트를 뽑는다."""
    block = _BODY_BLOCK.search(page_html)
    return _clean_html(block.group(0) if block else "")


def parse_attachment_urls(page_html: str) -> dict[str, str]:
    """첨부 다운로드 URL을 fileSn 기준으로 분류한다(1=HWP, 2=PDF)."""
    out: dict[str, str] = {}
    for href, sn in _FILE_LINK.findall(page_html):
        url = html_mod.unescape(href)
        if not url.startswith("http"):
            url = _BASE + url
        out["hwp" if sn == "1" else "pdf"] = url
    return out


def _default_fetch(url: str) -> bytes:
    resp = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT)
    resp.raise_for_status()
    return resp.content


def extract_light(record: dict, fetch=None) -> dict:
    """전량 대상 본문 확보. 페이지 본문 → 실패 시 제목+요약.

    record를 변형하지 않고 body/body_source/body_chars/attachment_urls를 더한 새 dict 반환.
    """
    fetch = fetch or _default_fetch
    out = dict(record)
    body, source = "", "title_only"

    url = (record.get("url") or "").strip()
    if url:
        try:
            page, trusted = decode_page(fetch(url))
            # 인코딩을 통째로 잘못 읽은 페이지는 쓰지 않는다 — 오염된 본문이 정상인 척
            # 분류 단계로 흘러가면 카탈로그 품질이 조용히 무너진다(첨부 URL도 신뢰 불가).
            if trusted:
                body = parse_page_body(page)
                if body:
                    source = "page"
                    out["attachment_urls"] = parse_attachment_urls(page)
        except Exception:
            # 네트워크·디코딩 실패는 폴백으로 흡수한다(파이프라인을 멈추지 않음)
            body = ""

    if not body:
        body = " ".join(x for x in (record.get("title"), record.get("summary")) if x).strip()
        source = "title_only"

    out["body"] = body
    out["body_source"] = source
    out["body_chars"] = len(body)
    return out


def extract_full(record: dict, fetch=None) -> str | None:
    """PDF 전문 추출. pypdf 미설치·URL 부재·다운로드 실패 시 None."""
    if not PYPDF_AVAILABLE:
        return None
    pdf_url = (record.get("attachment_urls") or {}).get("pdf")
    if not pdf_url:
        return None
    fetch = fetch or _default_fetch
    try:
        data = fetch(pdf_url)
        reader = PdfReader(io.BytesIO(data))
        pages = [(p.extract_text() or "") for p in reader.pages]
    except Exception:
        return None
    text = " ".join(" ".join(pages).split())
    return text or None
```

- [ ] **Step 5: 테스트 실행 — 통과 확인**

Run: `python -m pytest tests/test_catalog_extract.py -v`
Expected: 10 passed

- [ ] **Step 6: pypdf 없는 환경 확인**

Run: `python -c "from scripts.catalog import extract; print('PYPDF_AVAILABLE =', extract.PYPDF_AVAILABLE); print('degrade ok:', extract.extract_full({'attachment_urls':{'pdf':'x'}}) is None)"`
Expected: `PYPDF_AVAILABLE = False` (아직 미설치) / `degrade ok: True`

- [ ] **Step 7: 커밋**

```bash
git add scripts/catalog/extract.py tests/test_catalog_extract.py tests/fixtures/catalog/fss_view_page.html
git commit -m "$(cat <<'EOF'
feat(catalog): Phase B — 본문 확보 2진입점(light/full)

실측 근거: 금감원 첨부 fileSn=1은 구형 HWP(OLE, D0CF11E0 — 표본 5/5)라
zipfile로 못 열고, 문서뷰어는 이미지 렌더러라 텍스트가 없다. 전문은 PDF에서만
얻히므로 pypdf를 optional로 두고 미설치 시 페이지 요약으로 degrade한다.
PDF 다운로드는 1차 스크리닝 통과분에만 걸도록 진입점을 분리했다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Phase A — 수집 (FSS_API_KEY 필요)

**선행 조건:** `FSS_API_KEY`, `DATA_GO_KR_API_KEY` 환경변수. 없으면 Step 6(라이브 확인)만 건너뛰고 나머지는 진행 가능.

**Files:**
- Create: `scripts/catalog/collect.py`
- Create: `tests/fixtures/catalog/fss_api_response.json`
- Test: `tests/test_catalog_collect.py`

**Interfaces:**
- Produces:
  - `collect.KEYWORDS: list[str]`
  - `collect.matches_keywords(title: str, contents: str) -> list[str]`
  - `collect.normalize_fss(raw: dict) -> dict` — API 응답 → 표준 레코드
  - `collect.month_chunks(start: str, end: str) -> list[tuple[str, str]]` — `("YYYYMMDD","YYYYMMDD")`

표준 레코드 스키마(Task 4·6이 소비):
```python
{"source": "fss", "id": "133239", "title": "...", "date": "2024-01-18",
 "summary": "...", "url": "https://...", "matched_keywords": ["불공정거래"]}
```

- [ ] **Step 1: fixture 작성**

`tests/fixtures/catalog/fss_api_response.json`:

```json
{"result": {"list": [
  {"contentId": "133239", "title": "‘무늬만’ 신규사업, 불공정거래행위 집중조사", "contentKor": "상장기업의 신규사업 공시를 점검한 결과 불공정거래 혐의가 확인되었습니다.", "regDate": "2024-01-18", "atchfileUrl": "https://www.fss.or.kr/fss/cmmn/file/fileDown.do?atchFileId=A&fileSn=1", "atchfileNm": "보도자료.hwp"},
  {"contentId": "133310", "title": "「전환사채 시장 건전성 제고 간담회」 개최", "contentKor": "전환사채 시장의 리픽싱 문제를 논의했습니다.", "regDate": "2024-01-23", "atchfileUrl": "", "atchfileNm": ""},
  {"contentId": "140001", "title": "금융감독원 채용 공고", "contentKor": "신입직원을 채용합니다.", "regDate": "2024-02-01", "atchfileUrl": "", "atchfileNm": ""}
]}}
```

- [ ] **Step 2: 실패하는 테스트 작성**

`tests/test_catalog_collect.py`:

```python
"""Phase A 수집·필터 회귀 테스트.

dart-monitor 원본 키워드는 3개("불공정거래","주가조작","사모CB")뿐이라
taxonomy 45개 중 상당수 유형이 수집되지 않았다(신규 8개 공백의 직접 원인).
확장 키워드가 실제로 더 넓게 잡는지, 무관한 공고는 거르는지 검증한다.
"""
import json
import unittest
from pathlib import Path

from scripts.catalog import collect

_FIXTURE = Path(__file__).parent / "fixtures" / "catalog" / "fss_api_response.json"


class TestKeywords(unittest.TestCase):
    def test_legacy_three_keywords_still_present(self):
        for kw in ("불공정거래", "주가조작", "사모CB"):
            self.assertIn(kw, collect.KEYWORDS)

    def test_expanded_beyond_legacy(self):
        self.assertGreater(len(collect.KEYWORDS), 3)
        for kw in ("전환사채", "최대주주", "횡령", "상장폐지"):
            self.assertIn(kw, collect.KEYWORDS)

    def test_matches_title_or_contents(self):
        self.assertEqual(collect.matches_keywords("불공정거래 조사", ""), ["불공정거래"])
        self.assertIn("전환사채", collect.matches_keywords("", "전환사채 발행"))

    def test_unrelated_text_matches_nothing(self):
        self.assertEqual(collect.matches_keywords("채용 공고", "신입직원을 채용합니다."), [])


class TestNormalize(unittest.TestCase):
    def test_maps_api_fields_to_record(self):
        raw = json.loads(_FIXTURE.read_text(encoding="utf-8"))["result"]["list"][0]
        rec = collect.normalize_fss(raw)
        self.assertEqual(rec["source"], "fss")
        self.assertEqual(rec["id"], "133239")
        self.assertEqual(rec["date"], "2024-01-18")
        self.assertIn("불공정거래", rec["title"])
        self.assertTrue(rec["url"].startswith("https://www.fss.or.kr/fss/bbs/B0000188/view.do?nttId=133239"))

    def test_filters_by_keyword(self):
        rows = json.loads(_FIXTURE.read_text(encoding="utf-8"))["result"]["list"]
        kept = [r for r in (collect.normalize_fss(x) for x in rows) if r["matched_keywords"]]
        self.assertEqual(len(kept), 2)
        self.assertNotIn("140001", [r["id"] for r in kept])


class TestResumeState(unittest.TestCase):
    """FSS 개인키의 일일 호출 한도 때문에 백필은 여러 날에 걸쳐 재개돼야 한다."""

    def test_state_roundtrip(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "state.json"
            self.assertEqual(collect.load_state(p), {"done_chunks": []})
            collect.save_state(p, {"done_chunks": ["20100101-20100131"]})
            self.assertEqual(collect.load_state(p)["done_chunks"], ["20100101-20100131"])

    def test_corrupt_state_treated_as_empty(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "state.json"
            p.write_text("{ not json", encoding="utf-8")
            self.assertEqual(collect.load_state(p), {"done_chunks": []})

    def test_chunk_key_format_matches_state_entries(self):
        # main()이 f"{bgn}-{end}"로 키를 만든다. month_chunks 출력과 형식이 맞아야
        # --resume이 완료 청크를 실제로 건너뛴다.
        bgn, end = collect.month_chunks("2010-01-01", "2010-01-31")[0]
        self.assertEqual(f"{bgn}-{end}", "20100101-20100131")


class TestChunks(unittest.TestCase):
    def test_month_chunks_never_exceed_31_days(self):
        # FSS 개인 인증키는 조회기간 31일 상한이 있다고 알려져 있다. 월 청크는
        # 최대 31일이라 정합적이다 — 이 성질이 깨지면 수집이 조용히 실패한다.
        from datetime import datetime

        for bgn, end in collect.month_chunks("2010-01-01", "2026-08-16"):
            span = (datetime.strptime(end, "%Y%m%d") - datetime.strptime(bgn, "%Y%m%d")).days
            self.assertLessEqual(span, 30, f"{bgn}~{end} 가 31일을 초과")

    def test_month_chunks_cover_range(self):
        chunks = collect.month_chunks("2024-01-01", "2024-03-15")
        self.assertEqual(chunks[0], ("20240101", "20240131"))
        self.assertEqual(chunks[-1][1], "20240315")
        self.assertEqual(len(chunks), 3)

    def test_single_month(self):
        self.assertEqual(collect.month_chunks("2024-05-03", "2024-05-20"),
                         [("20240503", "20240520")])

    def test_multi_year_range_is_chunked(self):
        chunks = collect.month_chunks("2010-01-01", "2026-08-16")
        self.assertGreater(len(chunks), 190)   # 16년 7개월 ≈ 200 청크
        self.assertEqual(chunks[0][0], "20100101")
        self.assertEqual(chunks[-1][1], "20260816")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: 테스트 실행 — 실패 확인**

Run: `python -m pytest tests/test_catalog_collect.py -v`
Expected: FAIL — `ImportError: cannot import name 'collect'`

- [ ] **Step 4: `collect.py` 구현**

`scripts/catalog/collect.py`:

```python
"""Phase A — 금감원·금융위 보도자료 수집 + 키워드 필터 → JSONL.

dart-monitor 원본은 키워드가 3개("불공정거래","주가조작","사모CB")뿐이라
2.5년치에서 84건만 통과했다. taxonomy 45개(특히 v0.8.6~v1.6.1에 추가된
2.7·2.8·3.6·3.7·5.6·5.7·5.8·8.5)를 겨냥해 키워드를 넓힌다.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts._console import use_utf8_stdout  # noqa: E402

FSS_API_URL = "https://www.fss.or.kr/fss/kr/openApi/api/bodoInfo.jsp"
FSS_VIEW_URL = "https://www.fss.or.kr/fss/bbs/B0000188/view.do?nttId={id}&menuNo=200218"
OUT_PATH = _REPO_ROOT / "data" / "catalog" / "catalog_sources.jsonl"
STATE_PATH = _REPO_ROOT / "data" / "catalog" / "collect_state.json"
_TIMEOUT = 30
_SLEEP = 0.3

# FSS 개인 인증키에는 조회기간 상한(31일)과 일일 호출 한도가 있다고 알려져 있다
# (사용자 제보, 2026-08-16 — 실호출로 미검증). 월 단위 청크는 31일 상한과 정합적이고,
# 일일 한도는 한 실행의 호출 수를 제한하고 --resume으로 여러 날에 나눠 받아 흡수한다.
# 2010~2026 백필은 약 200개 청크라 한도가 30회면 최소 7일이 걸린다.
MAX_CALLS_PER_RUN = 25

# taxonomy 45개를 겨냥한 확장 키워드. 통과 건수는 --dry-run으로 측정해 조정한다.
KEYWORDS: list[str] = [
    "불공정거래", "주가조작", "시세조종", "미공개정보", "부정거래",
    "사모CB", "전환사채", "신주인수권", "유상증자", "무상감자",
    "최대주주", "무자본", "횡령", "배임", "회계처리기준", "감사의견",
    "분식회계", "상장폐지", "증권선물위원회", "공시위반", "자기주식",
]


def matches_keywords(title: str, contents: str) -> list[str]:
    """제목+본문에서 매칭된 키워드 목록(없으면 빈 리스트)."""
    text = f"{title or ''} {contents or ''}"
    return [kw for kw in KEYWORDS if kw in text]


def normalize_fss(raw: dict) -> dict:
    """FSS 오픈API 응답 한 건 → 표준 레코드."""
    cid = str(raw.get("contentId", "")).strip()
    title = (raw.get("title") or "").strip()
    contents = (raw.get("contentKor") or raw.get("contentsKor") or "").strip()
    return {
        "source": "fss",
        "id": cid,
        "title": title,
        "date": (raw.get("regDate") or "").strip()[:10],
        "summary": contents,
        "url": FSS_VIEW_URL.format(id=cid) if cid else "",
        "matched_keywords": matches_keywords(title, contents),
    }


def month_chunks(start: str, end: str) -> list[tuple[str, str]]:
    """[start, end]를 월 경계로 쪼갠다. 입력 'YYYY-MM-DD' → 출력 ('YYYYMMDD','YYYYMMDD')."""
    s = datetime.strptime(start, "%Y-%m-%d").date()
    e = datetime.strptime(end, "%Y-%m-%d").date()
    out: list[tuple[str, str]] = []
    cur = s
    while cur <= e:
        if cur.month == 12:
            nxt = date(cur.year + 1, 1, 1)
        else:
            nxt = date(cur.year, cur.month + 1, 1)
        chunk_end = min(nxt - timedelta(days=1), e)
        out.append((cur.strftime("%Y%m%d"), chunk_end.strftime("%Y%m%d")))
        cur = chunk_end + timedelta(days=1)
    return out


def fetch_fss(bgn: str, end: str, api_key: str) -> list[dict]:
    """FSS 보도자료 한 청크. 실패 시 빈 리스트(파이프라인을 멈추지 않음)."""
    params = {"apiKey": api_key, "stDt": bgn, "endDt": end, "pageIndex": 1}
    try:
        resp = requests.get(FSS_API_URL, params=params, timeout=_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        print(f"[COLLECT] FSS {bgn}~{end} 실패: {type(exc).__name__} {exc}")
        return []
    inner = data.get("result") or data
    rows = inner.get("list") or []
    return [r for r in rows if isinstance(r, dict)]


def load_state(path: Path) -> dict:
    """수집 진행 상태(완료 청크 목록)를 읽는다. 없으면 빈 상태."""
    if not path.exists():
        return {"done_chunks": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"done_chunks": []}


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    use_utf8_stdout()
    parser = argparse.ArgumentParser(description="보도자료 수집 → catalog_sources.jsonl")
    parser.add_argument("--start", default="2010-01-01")
    parser.add_argument("--end", default=date.today().isoformat())
    parser.add_argument("--out", default=str(OUT_PATH))
    parser.add_argument("--state", default=str(STATE_PATH))
    parser.add_argument("--dry-run", action="store_true", help="저장 없이 통과 건수만 출력")
    parser.add_argument("--resume", action="store_true", help="이미 수집한 청크를 건너뛴다")
    parser.add_argument(
        "--max-calls", type=int, default=MAX_CALLS_PER_RUN,
        help=f"이번 실행의 API 호출 상한(기본 {MAX_CALLS_PER_RUN}). FSS 개인키 일일 한도 대비 여유를 둔다",
    )
    args = parser.parse_args()

    api_key = os.environ.get("FSS_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("FSS_API_KEY 환경변수가 필요합니다")

    chunks = month_chunks(args.start, args.end)
    state_path = Path(args.state)
    state = load_state(state_path) if args.resume else {"done_chunks": []}
    done = set(state.get("done_chunks") or [])

    todo = [c for c in chunks if f"{c[0]}-{c[1]}" not in done]
    print(f"[COLLECT] {args.start} ~ {args.end} — 전체 {len(chunks)}개 월 청크"
          f" / 완료 {len(done)} / 남음 {len(todo)}")
    if args.max_calls and len(todo) > args.max_calls:
        print(f"[COLLECT] 이번 실행은 {args.max_calls}개 청크만 처리합니다"
              f" (남은 {len(todo) - args.max_calls}개는 다음 실행에서 --resume 으로 이어가세요)")
        todo = todo[: args.max_calls]

    out_path = Path(args.out)
    if not args.dry_run:
        out_path.parent.mkdir(parents=True, exist_ok=True)

    # 이미 저장된 id는 중복 저장하지 않는다(--resume 재실행 대비).
    seen: set[str] = set()
    if args.resume and out_path.exists():
        for line in out_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                seen.add(str(json.loads(line).get("id", "")))

    total = kept = 0
    # 청크마다 append 저장한다 — 일일 한도·중단에도 그때까지의 수집분이 남는다.
    fh = None if args.dry_run else out_path.open("a", encoding="utf-8")
    try:
        for i, (bgn, end) in enumerate(todo, 1):
            rows = fetch_fss(bgn, end, api_key)
            total += len(rows)
            for raw in rows:
                rec = normalize_fss(raw)
                if not rec["id"] or rec["id"] in seen:
                    continue
                seen.add(rec["id"])
                if rec["matched_keywords"]:
                    kept += 1
                    if fh:
                        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            if fh:
                fh.flush()
            done.add(f"{bgn}-{end}")
            if not args.dry_run:
                save_state(state_path, {"done_chunks": sorted(done)})
            if i % 10 == 0:
                print(f"[COLLECT] {i}/{len(todo)} 청크 — 원본 {total}건 / 통과 {kept}건")
            time.sleep(_SLEEP)
    finally:
        if fh:
            fh.close()

    rate = (kept / total * 100) if total else 0.0
    print(f"[COLLECT] 완료: 원본 {total}건 → 키워드 통과 {kept}건 ({rate:.1f}%)")
    remaining = len(chunks) - len(done)
    if remaining > 0:
        print(f"[COLLECT] 남은 청크 {remaining}개 — 다음 실행: "
              f"python scripts/catalog/collect.py --start {args.start} --resume")
    if not args.dry_run:
        print(f"[COLLECT] 저장 → {out_path}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: 테스트 실행 — 통과 확인**

Run: `python -m pytest tests/test_catalog_collect.py -v`
Expected: 13 passed

- [ ] **Step 6: 라이브 확인 (FSS_API_KEY 있을 때만)**

Run: `python scripts/catalog/collect.py --start 2024-01-01 --end 2024-03-31 --dry-run`
Expected: `[COLLECT] 완료: 원본 N건 → 키워드 통과 M건 (X.X%)`

**이 출력의 통과율을 스펙 §2.2에 기록할 것.** 추정치(10~15%)와 크게 다르면 `KEYWORDS`를 조정한다.

**반드시 확인할 두 가지:**

1. **페이지네이션 필요 여부** — `fetch_fss`는 현재 `pageIndex: 1`만 요청한다. 게시판 실측으로 FSS 보도자료는 **연 620~840건(월 평균 약 60건)**이므로, API의 페이지 크기가 그보다 작으면 월 청크마다 뒷부분이 조용히 잘린다. 이 스텝에서 3개월치 원본 건수 `N`이 **150건 대비 현저히 작으면 절단을 의심**하고, `pageIndex`를 증가시키며 빈 응답까지 도는 루프를 `fetch_fss`에 추가한다:

```python
def fetch_fss(bgn: str, end: str, api_key: str, max_pages: int = 20) -> list[dict]:
    """FSS 보도자료 한 청크(전 페이지). 실패 시 지금까지 모은 것만 반환."""
    rows: list[dict] = []
    for page in range(1, max_pages + 1):
        params = {"apiKey": api_key, "stDt": bgn, "endDt": end, "pageIndex": page}
        try:
            resp = requests.get(FSS_API_URL, params=params, timeout=_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            print(f"[COLLECT] FSS {bgn}~{end} p{page} 실패: {type(exc).__name__} {exc}")
            break
        inner = data.get("result") or data
        page_rows = [r for r in (inner.get("list") or []) if isinstance(r, dict)]
        if not page_rows:
            break
        rows.extend(page_rows)
        time.sleep(_SLEEP)
    return rows
```

2. **과거 데이터 범위** — `--start 2010-01-01`에서 2010~2015 구간이 0건이면 **스펙 §10 리스크 1이 현실화된 것**이다. 이 경우 게시판 목록 파싱 폴백이 필요하며, 별도 태스크로 분리해 계획을 갱신하고 여기서 멈춘다.

- [ ] **Step 7: 커밋**

```bash
git add scripts/catalog/collect.py tests/test_catalog_collect.py tests/fixtures/catalog/fss_api_response.json
git commit -m "$(cat <<'EOF'
feat(catalog): Phase A — 보도자료 수집 + 키워드 확장

dart-monitor 원본 키워드 3개는 2.5년치에서 84건만 통과시켜 신규 8개 유형
(2.7·2.8·3.6·3.7·5.6·5.7·5.8·8.5)의 사례가 비는 직접 원인이었다.
taxonomy 45개를 겨냥해 21개로 확장하고, 통과율은 --dry-run으로 실측해
조정한다. 월 단위 청크로 2010년까지 백필 가능.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: Phase C — 2단계 분류 (ANTHROPIC_API_KEY 필요)

**Files:**
- Create: `scripts/catalog/classify.py`
- Test: `tests/test_catalog_classify.py`

**Interfaces:**
- Consumes: `extract.extract_full`, `dart_risk_mcp.core.taxonomy.TAXONOMY`
- Produces:
  - `classify.build_taxonomy_prompt(taxonomy: dict) -> str` — 캐시 대상 시스템 프롬프트
  - `classify.parse_screen_response(text: str) -> dict` — `{"keep": bool, "category_hint": str}`
  - `classify.parse_classify_response(text: str) -> dict` — `{"taxonomy_ids", "techniques", "sanctions", "laws", "summary", "confidence"}`
  - `classify.call_anthropic(system: str, user: str, api_key: str, model: str) -> str`
  - `classify.MODEL: str` — 기본 `"claude-haiku-4-5-20251001"`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_catalog_classify.py`:

```python
"""Phase C 분류 회귀 테스트. LLM은 호출하지 않고 프롬프트 구성·응답 파싱만 검증."""
import json
import unittest

from dart_risk_mcp.core.taxonomy import TAXONOMY
from scripts.catalog import classify


class TestPrompt(unittest.TestCase):
    def test_includes_all_45_taxonomy_ids(self):
        prompt = classify.build_taxonomy_prompt(TAXONOMY)
        for tid in TAXONOMY:
            self.assertIn(tid, prompt, f"{tid} 누락")

    def test_includes_new_eight_types(self):
        prompt = classify.build_taxonomy_prompt(TAXONOMY)
        for tid in ("2.7", "2.8", "3.6", "3.7", "5.6", "5.7", "5.8", "8.5"):
            self.assertIn(tid, prompt)

    def test_instructs_empty_list_when_unmapped(self):
        prompt = classify.build_taxonomy_prompt(TAXONOMY)
        self.assertIn("빈 배열", prompt)


class TestParseScreen(unittest.TestCase):
    def test_parses_keep_true(self):
        got = classify.parse_screen_response('{"keep": true, "category_hint": "1"}')
        self.assertTrue(got["keep"])
        self.assertEqual(got["category_hint"], "1")

    def test_parses_keep_false(self):
        self.assertFalse(classify.parse_screen_response('{"keep": false}')["keep"])

    def test_tolerates_code_fence(self):
        got = classify.parse_screen_response('```json\n{"keep": true}\n```')
        self.assertTrue(got["keep"])

    def test_malformed_defaults_to_keep_false(self):
        self.assertFalse(classify.parse_screen_response("설명만 있고 JSON 없음")["keep"])


class TestParseClassify(unittest.TestCase):
    _GOOD = json.dumps({
        "taxonomy_ids": ["1.1", "9.9"],
        "techniques": ["리픽싱 남용"],
        "sanctions": ["과징금"],
        "laws": ["자본시장법"],
        "summary": "요약",
        "confidence": "high",
    }, ensure_ascii=False)

    def test_drops_unknown_taxonomy_ids(self):
        got = classify.parse_classify_response(self._GOOD)
        self.assertEqual(got["taxonomy_ids"], ["1.1"])  # 9.9는 존재하지 않음

    def test_keeps_list_fields(self):
        got = classify.parse_classify_response(self._GOOD)
        self.assertEqual(got["techniques"], ["리픽싱 남용"])
        self.assertEqual(got["confidence"], "high")

    def test_unmapped_returns_empty_ids(self):
        got = classify.parse_classify_response('{"taxonomy_ids": [], "summary": "신종 수법"}')
        self.assertEqual(got["taxonomy_ids"], [])
        self.assertEqual(got["summary"], "신종 수법")

    def test_malformed_yields_empty_record(self):
        got = classify.parse_classify_response("JSON 아님")
        self.assertEqual(got["taxonomy_ids"], [])
        self.assertEqual(got["confidence"], "low")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 테스트 실행 — 실패 확인**

Run: `python -m pytest tests/test_catalog_classify.py -v`
Expected: FAIL — `ImportError: cannot import name 'classify'`

- [ ] **Step 3: `classify.py` 구현**

`scripts/catalog/classify.py`:

```python
"""Phase C — 2단계 분류.

1차 스크리닝: 제목+페이지 요약(extract_light 결과)으로 등재 가치를 판정. 값싸다.
2차 정밀:     통과분만 extract_full로 PDF 전문을 받아 taxonomy 45개에 매핑.

anthropic SDK를 쓰지 않고 requests로 직접 호출한다 — 이 레포는 Notion API도
같은 방식으로 다루며, 런타임/배치 모두 서드파티 의존성을 늘리지 않는 원칙이다.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

import requests

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts._console import use_utf8_stdout  # noqa: E402
from scripts.catalog.extract import extract_full  # noqa: E402

API_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-haiku-4-5-20251001"
_TIMEOUT = 120
_SLEEP = 0.2
IN_PATH = _REPO_ROOT / "data" / "catalog" / "catalog_bodies.jsonl"
OUT_PATH = _REPO_ROOT / "data" / "catalog" / "catalog_classified.jsonl"

_JSON_BLOCK = re.compile(r"\{[\s\S]*\}")


def build_taxonomy_prompt(taxonomy: dict[str, dict]) -> str:
    """45개 유형 정의를 시스템 프롬프트로 만든다(프롬프트 캐싱 대상)."""
    lines = [
        "너는 한국 금융감독원·금융위원회 보도자료를 불공정거래 유형으로 분류하는 분석기다.",
        "아래는 분류 체계다. 각 항목은 'ID | 명칭 | 설명 | 키워드' 형식이다.",
        "",
    ]
    for tid in sorted(taxonomy, key=lambda t: [int(x) for x in t.split(".")]):
        e = taxonomy[tid]
        kws = ", ".join(e.get("keywords") or [])
        lines.append(f"{tid} | {e.get('name','')} | {e.get('description','')} | {kws}")
    lines += [
        "",
        "규칙:",
        "- 보도자료가 위 유형 중 어디에도 해당하지 않으면 taxonomy_ids를 빈 배열로 둔다.",
        "- 억지로 끼워 맞추지 마라. 확신이 없으면 confidence를 low로 하고 빈 배열을 낸다.",
        "- 반드시 JSON 객체 하나만 출력한다. 설명 문장을 덧붙이지 마라.",
    ]
    return "\n".join(lines)


def call_anthropic(system: str, user: str, api_key: str, model: str = MODEL) -> str:
    """Anthropic Messages API 호출. 시스템 프롬프트에 캐시 제어를 건다."""
    payload = {
        "model": model,
        "max_tokens": 1500,
        "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": user}],
    }
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    resp = requests.post(API_URL, headers=headers, json=payload, timeout=_TIMEOUT)
    resp.raise_for_status()
    blocks = resp.json().get("content") or []
    return "".join(b.get("text", "") for b in blocks if b.get("type") == "text")


def _extract_json(text: str) -> dict:
    match = _JSON_BLOCK.search(text or "")
    if not match:
        return {}
    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def parse_screen_response(text: str) -> dict:
    """1차 스크리닝 응답 파싱. 파싱 실패는 보수적으로 keep=False."""
    data = _extract_json(text)
    return {"keep": bool(data.get("keep")), "category_hint": str(data.get("category_hint", ""))}


def parse_classify_response(text: str) -> dict:
    """2차 정밀 응답 파싱. 존재하지 않는 taxonomy id는 버린다."""
    from dart_risk_mcp.core.taxonomy import TAXONOMY

    data = _extract_json(text)

    def _strlist(key: str) -> list[str]:
        vals = data.get(key)
        return [str(v).strip() for v in vals if str(v).strip()] if isinstance(vals, list) else []

    return {
        "taxonomy_ids": [t for t in _strlist("taxonomy_ids") if t in TAXONOMY],
        "techniques": _strlist("techniques"),
        "sanctions": _strlist("sanctions"),
        "laws": _strlist("laws"),
        "summary": str(data.get("summary", "")).strip(),
        "confidence": str(data.get("confidence", "low")).strip() or "low",
    }


_SCREEN_SYSTEM = (
    "너는 한국 금융감독원 보도자료를 선별하는 분류기다. "
    "주가조작·불공정거래·회계부정·지배구조 남용 등 상장기업 투자자 보호와 직접 관련된 "
    "자료면 keep=true, 채용·행사·일반 정책 홍보면 keep=false로 판정한다. "
    'JSON 객체 하나만 출력한다: {"keep": true/false, "category_hint": "1~8 중 하나 또는 빈 문자열"}'
)


def main() -> None:
    use_utf8_stdout()
    parser = argparse.ArgumentParser(description="보도자료 2단계 분류")
    parser.add_argument("--in", dest="in_path", default=str(IN_PATH))
    parser.add_argument("--out", default=str(OUT_PATH))
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--limit", type=int, default=0, help="상위 N건만 처리(비용 통제)")
    parser.add_argument("--resume", action="store_true", help="출력에 있는 id는 건너뜀")
    args = parser.parse_args()

    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("ANTHROPIC_API_KEY 환경변수가 필요합니다")

    from dart_risk_mcp.core.taxonomy import TAXONOMY

    records = [json.loads(l) for l in Path(args.in_path).read_text(encoding="utf-8").splitlines() if l.strip()]
    out_path = Path(args.out)
    done: set[str] = set()
    if args.resume and out_path.exists():
        for line in out_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                done.add(str(json.loads(line).get("id", "")))
        print(f"[CLASSIFY] resume — 완료 {len(done)}건 건너뜀")

    todo = [r for r in records if str(r.get("id", "")) not in done]
    if args.limit:
        todo = todo[: args.limit]

    system_full = build_taxonomy_prompt(TAXONOMY)
    kept = mapped = 0
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("a", encoding="utf-8") as fh:
        for i, rec in enumerate(todo, 1):
            head = f"제목: {rec.get('title','')}\n요약: {rec.get('body','')[:1500]}"
            try:
                screen = parse_screen_response(call_anthropic(_SCREEN_SYSTEM, head, api_key, args.model))
            except Exception as exc:
                print(f"[CLASSIFY] 스크리닝 실패 {rec.get('id')}: {type(exc).__name__}")
                continue
            if not screen["keep"]:
                continue
            kept += 1

            full = extract_full(rec)
            body = full or rec.get("body", "")
            source = "pdf" if full else rec.get("body_source", "title_only")
            user = f"제목: {rec.get('title','')}\n일자: {rec.get('date','')}\n본문:\n{body[:20000]}"
            try:
                result = parse_classify_response(call_anthropic(system_full, user, api_key, args.model))
            except Exception as exc:
                print(f"[CLASSIFY] 정밀 실패 {rec.get('id')}: {type(exc).__name__}")
                continue

            out = {
                "id": rec.get("id", ""),
                "date": rec.get("date", ""),
                "agency": "금융감독원" if rec.get("source") == "fss" else "금융위원회",
                "title": rec.get("title", ""),
                "url": rec.get("url", ""),
                "body_source": source,
                **result,
            }
            if out["taxonomy_ids"]:
                mapped += 1
            fh.write(json.dumps(out, ensure_ascii=False) + "\n")
            fh.flush()
            if i % 25 == 0:
                print(f"[CLASSIFY] {i}/{len(todo)} — 통과 {kept} / 매핑 {mapped}")
            time.sleep(_SLEEP)

    print(f"[CLASSIFY] 완료: 후보 {len(todo)} → 스크리닝 통과 {kept} → 유형 매핑 {mapped}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 테스트 실행 — 통과 확인**

Run: `python -m pytest tests/test_catalog_classify.py -v`
Expected: 11 passed

- [ ] **Step 5: 커밋**

```bash
git add scripts/catalog/classify.py tests/test_catalog_classify.py
git commit -m "$(cat <<'EOF'
feat(catalog): Phase C — 2단계 분류(스크리닝 → 정밀)

전량 PDF 다운로드를 피하려고 제목+요약으로 먼저 걸러내고, 통과분만
extract_full로 전문을 받아 taxonomy 45개에 매핑한다. anthropic SDK 대신
requests 직접 호출(레포 관례) + 시스템 프롬프트 캐싱. 45개 어디에도
매핑되지 않으면 빈 배열을 내도록 지시해 Phase E 갭 리포트의 입력으로 쓴다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: Phase E — 신규 유형 후보 갭 리포트

**Files:**
- Create: `scripts/catalog/gaps.py`
- Test: `tests/test_catalog_gaps.py`

**Interfaces:**
- Consumes: Task 6의 분류 레코드
- Produces: `gaps.build_gap_report(records: list[dict], generated_on: str) -> str`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_catalog_gaps.py`:

```python
"""Phase E 갭 리포트 회귀 테스트.

목적: taxonomy 45개에 매핑되지 않은 수법을 신규 신호 후보로 표면화한다.
자동으로 taxonomy.py를 고치지 않는다 — 사람 검토용 리포트까지가 범위다.
"""
import unittest

from scripts.catalog import gaps

_RECORDS = [
    {"id": "1", "date": "2026-01-05", "title": "신종 수법 A 적발", "url": "https://x.invalid/1",
     "taxonomy_ids": [], "summary": "토큰증권 발행을 가장한 자금모집", "techniques": ["가장 발행"],
     "confidence": "high", "body_source": "pdf"},
    {"id": "2", "date": "2026-02-05", "title": "신종 수법 B", "url": "https://x.invalid/2",
     "taxonomy_ids": [], "summary": "해외법인 통한 우회 지분취득", "techniques": ["우회 취득"],
     "confidence": "low", "body_source": "page"},
    {"id": "3", "date": "2026-03-05", "title": "기존 유형", "url": "https://x.invalid/3",
     "taxonomy_ids": ["1.1"], "summary": "리픽싱", "techniques": [], "confidence": "high",
     "body_source": "pdf"},
]


class TestGapReport(unittest.TestCase):
    def test_includes_only_unmapped(self):
        md = gaps.build_gap_report(_RECORDS, "2026-08-16")
        self.assertIn("신종 수법 A", md)
        self.assertIn("신종 수법 B", md)
        self.assertNotIn("기존 유형", md)

    def test_reports_counts(self):
        md = gaps.build_gap_report(_RECORDS, "2026-08-16")
        self.assertIn("전체 3건", md)
        self.assertIn("미매핑 2건", md)

    def test_marks_low_confidence_and_body_source(self):
        md = gaps.build_gap_report(_RECORDS, "2026-08-16")
        self.assertIn("confidence: low", md)
        self.assertIn("page", md)

    def test_links_source_url(self):
        md = gaps.build_gap_report(_RECORDS, "2026-08-16")
        self.assertIn("(https://x.invalid/1)", md)

    def test_states_no_auto_taxonomy_edit(self):
        md = gaps.build_gap_report(_RECORDS, "2026-08-16")
        self.assertIn("자동으로 반영하지 않습니다", md)

    def test_empty_when_all_mapped(self):
        md = gaps.build_gap_report([_RECORDS[2]], "2026-08-16")
        self.assertIn("미매핑 0건", md)
        self.assertIn("후보 없음", md)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 테스트 실행 — 실패 확인**

Run: `python -m pytest tests/test_catalog_gaps.py -v`
Expected: FAIL — `ImportError: cannot import name 'gaps'`

- [ ] **Step 3: `gaps.py` 구현**

`scripts/catalog/gaps.py`:

```python
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
        title = str(rec.get("title", "")).replace("|", "/")
        url = rec.get("url", "")
        head = f"[{title}]({url})" if url else title
        lines += [
            f"## {rec.get('date','')} — {head}",
            "",
            f"- 요약: {rec.get('summary','')}",
            f"- 적발 기법: {', '.join(rec.get('techniques') or []) or '—'}",
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
```

- [ ] **Step 4: 테스트 실행 — 통과 확인**

Run: `python -m pytest tests/test_catalog_gaps.py -v`
Expected: 6 passed

- [ ] **Step 5: 커밋**

```bash
git add scripts/catalog/gaps.py tests/test_catalog_gaps.py
git commit -m "$(cat <<'EOF'
feat(catalog): Phase E — 미매핑 수법 신규 유형 후보 리포트

taxonomy 45개 어디에도 안 맞은 보도자료를 사람 검토용 리포트로 표면화한다.
taxonomy.py 자동 수정은 하지 않는다. body_source를 병기해 '신종 수법'과
'정보 부족으로 인한 미매핑'을 구분할 수 있게 했다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 8: 패키징·워크플로우·문서

**Files:**
- Modify: `pyproject.toml`
- Modify: `.gitignore`
- Modify: `CLAUDE.md`
- Modify: `scripts/catalog/extract.py` (Step 6에서 CLI `main()` 추가 — 워크플로우가 직접 호출한다)
- Create: `.github/workflows/refresh-catalog.yml`
- Test: `tests/test_catalog_packaging.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_catalog_packaging.py`:

```python
"""패키징 경계 회귀 테스트.

핵심 계약: pypdf는 scripts 전용 optional이며 런타임 패키지 의존성을 늘리지 않는다.
"""
import tomllib
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


class TestPackaging(unittest.TestCase):
    def setUp(self):
        self.cfg = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    def test_runtime_dependencies_unchanged(self):
        deps = self.cfg["project"]["dependencies"]
        self.assertEqual(len(deps), 2, f"런타임 의존성이 늘었다: {deps}")
        self.assertTrue(any(d.startswith("mcp") for d in deps))
        self.assertTrue(any(d.startswith("requests") for d in deps))

    def test_pypdf_is_optional_only(self):
        optional = self.cfg["project"].get("optional-dependencies", {})
        self.assertIn("catalog", optional)
        self.assertTrue(any("pypdf" in d for d in optional["catalog"]))
        self.assertFalse(any("pypdf" in d for d in self.cfg["project"]["dependencies"]))

    def test_runtime_package_does_not_import_pypdf(self):
        hits = [p for p in (_ROOT / "dart_risk_mcp").rglob("*.py")
                if "pypdf" in p.read_text(encoding="utf-8")]
        self.assertEqual(hits, [], f"런타임 패키지가 pypdf를 참조한다: {hits}")


class TestWorkflow(unittest.TestCase):
    def test_workflow_exists_with_dispatch_and_cron(self):
        wf = (_ROOT / ".github" / "workflows" / "refresh-catalog.yml").read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch", wf)
        self.assertIn("cron", wf)
        for secret in ("FSS_API_KEY", "DATA_GO_KR_API_KEY", "ANTHROPIC_API_KEY"):
            self.assertIn(secret, wf)

    def test_workflow_installs_catalog_extra(self):
        wf = (_ROOT / ".github" / "workflows" / "refresh-catalog.yml").read_text(encoding="utf-8")
        self.assertIn("[catalog]", wf)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 테스트 실행 — 실패 확인**

Run: `python -m pytest tests/test_catalog_packaging.py -v`
Expected: FAIL — `KeyError: 'optional-dependencies'` 및 워크플로우 파일 부재

- [ ] **Step 3: `pyproject.toml` 수정**

`[project.scripts]` 블록 **바로 위**에 추가:

```toml
[project.optional-dependencies]
# 카탈로그 생성 배치(scripts/catalog/) 전용. MCP 서버 런타임은 이 패키지를
# 쓰지 않으며, 미설치 시 파이프라인이 요약 모드로 degrade한다.
catalog = ["pypdf>=4.0.0"]
```

- [ ] **Step 4: `.gitignore` 수정**

파일 끝에 추가:

```gitignore
# 카탈로그 파이프라인 중간 산출물 (labels_ko.json은 자산이므로 커밋한다)
data/catalog/*.jsonl
```

- [ ] **Step 5: 워크플로우 생성**

`.github/workflows/refresh-catalog.yml`:

```yaml
name: Refresh manipulation catalog

on:
  schedule:
    - cron: "0 18 1 * *"   # 매월 1일 UTC 18:00 = 한국 익일 03:00
  workflow_dispatch:
    inputs:
      start:
        description: "수집 시작일 (YYYY-MM-DD)"
        required: false
        default: ""
      limit:
        description: "분류 건수 상한 (0=제한 없음)"
        required: false
        default: "0"

permissions:
  contents: write

jobs:
  refresh:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
      - uses: actions/setup-python@v6
        with:
          python-version: "3.11"

      - name: Install package with catalog extras
        run: pip install -e ".[catalog]"

      - name: Collect press releases
        env:
          FSS_API_KEY: ${{ secrets.FSS_API_KEY }}
          DATA_GO_KR_API_KEY: ${{ secrets.DATA_GO_KR_API_KEY }}
        run: |
          START="${{ github.event.inputs.start }}"
          if [ -z "$START" ]; then START=$(date -u -d '2 months ago' +%Y-%m-%d); fi
          python scripts/catalog/collect.py --start "$START"

      - name: Extract bodies
        run: python scripts/catalog/extract.py

      - name: Classify
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
        run: python scripts/catalog/classify.py --resume --limit "${{ github.event.inputs.limit || 0 }}"

      - name: Build catalog MD
        run: python scripts/catalog/build_md.py

      - name: Build gap report
        run: python scripts/catalog/gaps.py

      - name: Verify catalog excerpt is not empty
        run: |
          python -c "
          from dart_risk_mcp.core.catalog import load_catalog_excerpt
          e = load_catalog_excerpt(['1.1','5.7','8.1'])
          assert e.strip(), '카탈로그 발췌가 비어있음 — 생성 실패'
          assert '**Severity**' not in e, '점수 메타가 노출됨'
          print('발췌 OK:', len(e), 'chars')
          "

      - name: Run catalog tests
        run: |
          pip install pytest
          python -m pytest tests/test_catalog_render.py tests/test_catalog_labels.py tests/test_golden_output_hygiene.py -q

      - name: Commit updated catalog
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add dart_risk_mcp/knowledge/manipulation_catalog docs/catalog
          git diff --staged --quiet || git commit -m "chore(catalog): 보도자료 카탈로그 갱신 [skip ci]"
          git push
```

- [ ] **Step 6: `extract.py`에 CLI main 추가**

워크플로우가 `python scripts/catalog/extract.py`를 호출하므로 진입점이 필요하다. `scripts/catalog/extract.py` 파일 끝에 추가:

```python
def main() -> None:
    import argparse
    import json
    import sys
    from pathlib import Path

    _root = Path(__file__).resolve().parents[2]
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))
    from scripts._console import use_utf8_stdout

    use_utf8_stdout()
    parser = argparse.ArgumentParser(description="보도자료 본문 확보(light)")
    parser.add_argument("--in", dest="in_path", default=str(_root / "data" / "catalog" / "catalog_sources.jsonl"))
    parser.add_argument("--out", default=str(_root / "data" / "catalog" / "catalog_bodies.jsonl"))
    args = parser.parse_args()

    in_path = Path(args.in_path)
    if not in_path.exists():
        raise SystemExit(f"입력 없음: {in_path} — 먼저 collect를 실행하세요")
    records = [json.loads(l) for l in in_path.read_text(encoding="utf-8").splitlines() if l.strip()]

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    with out_path.open("w", encoding="utf-8") as fh:
        for rec in records:
            got = extract_light(rec)
            counts[got["body_source"]] = counts.get(got["body_source"], 0) + 1
            fh.write(json.dumps(got, ensure_ascii=False) + "\n")
    print(f"[EXTRACT] {len(records)}건 → {out_path}")
    print("[EXTRACT] 본문 확보 경로:", ", ".join(f"{k} {v}건" for k, v in sorted(counts.items())))
    print(f"[EXTRACT] pypdf 사용 가능: {PYPDF_AVAILABLE}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 7: 테스트 실행 — 통과 확인**

Run: `python -m pytest tests/test_catalog_packaging.py -v`
Expected: 5 passed

- [ ] **Step 8: 전체 테스트 회귀 확인**

Run: `python -m pytest tests/ -q`
Expected: 기존 테스트 전부 통과 + 신규 테스트 통과. 실패가 있으면 **이 브랜치가 원인인지 먼저 확인**할 것(기존 실패 주장은 `git stash`가 아니라 base 커밋 체크아웃으로 검증).

- [ ] **Step 9: `CLAUDE.md` 갱신**

"디렉토리 구조" 절의 트리 아래에 다음 단락을 추가:

```markdown
> 카탈로그 생성 파이프라인: `scripts/catalog/`(collect → extract → classify → build_md → gaps).
> `knowledge/manipulation_catalog/*.md`는 이 파이프라인의 산출물이며 손으로 고치지 않는다
> (고치면 다음 실행에서 덮어써진다). 한글 표시 라벨은 `data/catalog/labels_ko.json`이
> 단일 출처 — `TAXONOMY`의 `name`은 45개 중 41개가 영문이라 사용자 노출용으로 쓸 수 없다
> (2026-08-16 실측). 라벨을 고치려면 JSON을 고치고 `build_md.py`를 재실행한다.
> **의존성 경계**: `pypdf`는 `[project.optional-dependencies]`의 `catalog` 그룹 전용이며
> 런타임 패키지 `dart_risk_mcp/`는 여전히 `mcp`+`requests`만 쓴다. 미설치 환경에서는
> `extract_full`이 `None`을 반환해 요약 모드로 degrade한다.
> 설계·실측 근거: `docs/superpowers/specs/2026-08-16-fss-catalog-pipeline-design.md`
```

- [ ] **Step 10: 커밋**

```bash
git add pyproject.toml .gitignore CLAUDE.md .github/workflows/refresh-catalog.yml scripts/catalog/extract.py tests/test_catalog_packaging.py
git commit -m "$(cat <<'EOF'
feat(catalog): 패키징 경계 + 월간 갱신 워크플로우

pypdf를 optional-dependencies의 catalog 그룹에만 두고, 런타임 패키지가
pypdf를 참조하지 않는지 테스트로 고정한다. 워크플로우는 생성 후
load_catalog_excerpt가 비어있지 않은지, 점수 메타가 노출되지 않는지를
커밋 전에 검증한다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 9: 백필 실행 및 카탈로그 교체 (키 3개 필요, 사람 판단 게이트)

**이 태스크는 자동 실행하지 않는다.** 기존 카탈로그를 교체하는 되돌리기 어려운 변경이라 사람이 diff를 검토한 뒤 결정한다.

**선행 조건:** `FSS_API_KEY`, `DATA_GO_KR_API_KEY`, `ANTHROPIC_API_KEY` 전부 설정 + `pip install -e ".[catalog]"`

- [ ] **Step 1: 수집 규모 실측 (저비용, LLM 미사용)**

```bash
python scripts/catalog/collect.py --start 2010-01-01 --dry-run
```

Expected: `[COLLECT] 완료: 원본 N건 → 키워드 통과 M건 (X.X%)`

**측정된 N·M·X를 스펙 `docs/superpowers/specs/2026-08-16-fss-catalog-pipeline-design.md` §2.2의 추정치 자리에 실측값으로 갱신하고 커밋한다.** 추정을 실측으로 바꾸는 것이 이 단계의 산출물이다.

- [ ] **Step 2: FSS API 과거 데이터 범위 확인**

Step 1 출력에서 연도 분포를 확인한다. 2010~2015 구간이 0건이면 스펙 §10 리스크 1이 현실화된 것이다 — 게시판 목록 파싱 폴백 태스크를 계획에 추가하고 여기서 중단한다.

- [ ] **Step 3: 수집·본문 확보 실행**

```bash
python scripts/catalog/collect.py --start 2010-01-01
python scripts/catalog/extract.py
```

Expected: `[EXTRACT] 본문 확보 경로: page N건, title_only M건`

- [ ] **Step 4: 소량 분류로 비용 검증**

```bash
python scripts/catalog/classify.py --limit 50
```

50건 처리 후 Anthropic 콘솔에서 실제 비용을 확인한다. 전체 건수로 외삽해 총비용을 추정하고, 진행 여부를 사람이 결정한다.

- [ ] **Step 5: 전량 분류 (승인 후)**

```bash
python scripts/catalog/classify.py --resume
```

- [ ] **Step 6: MD 생성 + diff 검토**

```bash
python scripts/catalog/build_md.py
python scripts/catalog/gaps.py
git diff --stat dart_risk_mcp/knowledge/manipulation_catalog/
```

**검토 항목:**
- 제목이 영문으로 퇴행하지 않았는가 (`git diff | grep '^+## '`로 한글 확인)
- 기존 37개 유형의 사례가 줄어들지 않았는가
- 신규 8개 유형에 사례가 붙었는가

- [ ] **Step 7: 발췌·위생 회귀 확인**

```bash
python -m pytest tests/test_catalog_order.py tests/test_golden_output_hygiene.py tests/test_catalog_render.py -v
```

Expected: all passed. 실패하면 커밋하지 말고 원인을 먼저 규명한다.

- [ ] **Step 8: 커밋 (검토 통과 시에만)**

```bash
git add dart_risk_mcp/knowledge/manipulation_catalog docs/catalog docs/superpowers/specs/2026-08-16-fss-catalog-pipeline-design.md
git commit -m "$(cat <<'EOF'
chore(catalog): 2010년 이후 보도자료로 카탈로그 재생성

수집 범위를 2010-01-01까지 넓히고 키워드를 21개로 확장해 재생성.
스펙 §2.2의 추정 건수를 실측값으로 갱신했다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## 완료 기준

스펙 §11의 성공 기준과 대응한다.

| # | 기준 | 검증 방법 | 담당 태스크 |
|---|---|---|---|
| 1 | 5단계가 종단 실행되고 MD 8개 재생성 | Task 9 Step 6 | 1~8 |
| 2 | `load_catalog_excerpt`가 빈 문자열이 아님 | `tests/test_catalog_render.py::TestBuildMdEndToEnd` + 워크플로우 검증 스텝 | 3, 8 |
| 3 | 신규 8개 중 1개 이상에 사례 등재 | Task 9 Step 6 검토 항목 | 5, 9 |
| 4 | 갭 리포트 생성 + 후보 1건 이상 | `python scripts/catalog/gaps.py` 출력 | 7 |
| 5 | pypdf 미설치 시 요약 모드 완주 | `tests/test_catalog_extract.py::TestExtractFull` + Task 4 Step 6 | 4 |
| 6 | hygiene 통과 + 런타임 의존성 불변 | `tests/test_catalog_packaging.py`, `tests/test_golden_output_hygiene.py` | 8 |
