"""주가조작 MD 카탈로그 로더

dart-monitor의 knowledge/manipulation_catalog/*.md를 읽어
도구 응답에 관련 선례를 첨부한다.

카탈로그 파일이 없어도 빈 문자열을 반환해 graceful degradation.
"""

import re
from pathlib import Path

from .explain import category_prose
from .taxonomy import TAXONOMY

# 각 `## N.N: ...` 서브섹션에서 내부 taxonomy 메타데이터 블록(정의·Severity·
# Base Score·Crisis Timeline·Red Flags 등)을 통째로 제거하고, 실제 가치가 있는
# `### 금감원·금융위 적발 사례` / `### 기존 현장 기사 인용`부터만 남긴다.
# v0.7.3에서 실제 출력이 영문 메타 라벨을 그대로 노출하던 문제를 수정하면서 추가.
_TAXONOMY_META_BLOCK = re.compile(
    r"^## \d+\.\d+:.*?(?=^### 금감원|^### 기존|^---|\Z)",
    re.MULTILINE | re.DOTALL,
)


def _strip_taxonomy_metadata(md: str) -> str:
    """카탈로그 MD에서 내부 분류 메타 블록을 제거한다.

    제거 대상: `## N.M: English Title` 헤더 + 바로 뒤따르는 Severity / Base Score /
    Crisis Timeline 라벨 + `### 정의` / `### 탐지 키워드` / `### Red Flags` 서브섹션.
    남기는 대상: 한글로 작성된 `### 금감원·금융위 적발 사례`, `### 적발 기법 종합`,
    `### 인용 법조`, `### 기존 현장 기사 인용` 블록.
    """
    return _TAXONOMY_META_BLOCK.sub("", md)

_CATALOG_DIR = Path(__file__).parent.parent / "knowledge" / "manipulation_catalog"

_CATEGORY_TO_FILE: dict[str, str] = {
    "Convertible Bond & Debt Manipulation": "01_cb_debt.md",
    "Capital Structure Manipulation": "02_capital_structure.md",
    "Ownership & Control": "03_ownership_control.md",
    "Governance & Disclosure": "04_governance.md",
    "Corporate Action Manipulation": "05_corporate_action.md",
    "Accounting & Financial Reporting": "06_accounting.md",
    "Market Manipulation & Trading": "07_market_manipulation.md",
    "Crisis & Distress Signals": "08_crisis_distress.md",
}


def load_catalog_excerpt(taxonomy_ids: list[str], max_chars: int = 1500) -> str:
    """taxonomy ID 목록에 해당하는 카탈로그 MD 발췌를 반환한다.

    중복 카테고리는 한 번만 로드. 파일 부재·읽기 오류 시 해당 카테고리 건너뜀.
    """
    seen: set[str] = set()
    excerpts: list[str] = []

    for tid in taxonomy_ids:
        signal = TAXONOMY.get(tid)
        if not signal:
            continue
        category = signal.get("category", "")
        if category in seen:
            continue
        seen.add(category)

        filename = _CATEGORY_TO_FILE.get(category)
        if not filename:
            continue

        md_path = _CATALOG_DIR / filename
        if not md_path.exists():
            continue

        try:
            content = md_path.read_text(encoding="utf-8")
        except OSError:
            continue

        content = _strip_taxonomy_metadata(content)
        # 연속 빈 줄 정리 (메타 블록 제거 후 공백이 과다하게 남는 것을 방지)
        content = re.sub(r"\n{3,}", "\n\n", content).strip() + "\n"

        truncated = content[:max_chars]
        if len(content) > max_chars:
            truncated += "\n…(이하 생략)"

        header = f"━━ 카탈로그 선례: {category} ━━"
        prose = category_prose(category)
        if prose:
            excerpts.append(f"{header}\n이 카테고리가 뭔가요 — {prose}\n\n{truncated}")
        else:
            excerpts.append(f"{header}\n{truncated}")

    return "\n\n".join(excerpts)
