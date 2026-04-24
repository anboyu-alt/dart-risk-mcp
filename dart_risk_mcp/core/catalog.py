"""주가조작 MD 카탈로그 로더

dart-monitor의 knowledge/manipulation_catalog/*.md를 읽어
도구 응답에 관련 선례를 첨부한다.

카탈로그 파일이 없어도 빈 문자열을 반환해 graceful degradation.
"""

import re
from pathlib import Path

from .explain import category_prose
from .taxonomy import TAXONOMY

# v0.7.5: MD 본문이 한글화되면서(제목·정의·위험 신호) 카탈로그 발췌 시 사용자에게
# 보여줘도 좋은 맥락 정보가 됐다. 남은 '내부 지표'는 영문 메타 라벨 3종(`Severity`,
# `Base Score`, `Crisis Timeline`)뿐이어서 이 3줄만 핀포인트로 제거한다.
# 헤더(`## N.M: 제목`), `### 정의`, `### 탐지 키워드`, `### 위험 신호`는 보존한다.
_TAXONOMY_META_LINE = re.compile(
    r"^- \*\*(?:Severity|Base Score|Crisis Timeline)\*\*:.*(?:\r?\n|$)",
    re.MULTILINE,
)


def _strip_taxonomy_metadata(md: str) -> str:
    """카탈로그 MD에서 내부용 메타 라벨(Severity / Base Score / Crisis Timeline)만 제거한다.

    제거 대상: `- **Severity**: ...`, `- **Base Score**: ...`, `- **Crisis Timeline**: ...`
    세 줄만 핀포인트로 제거.
    남기는 대상: 한글화된 제목·정의·탐지 키워드·위험 신호 섹션 + 적발 사례·법조·기존 기사 인용.
    """
    return _TAXONOMY_META_LINE.sub("", md)

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
