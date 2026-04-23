"""주가조작 MD 카탈로그 로더

dart-monitor의 knowledge/manipulation_catalog/*.md를 읽어
도구 응답에 관련 선례를 첨부한다.

카탈로그 파일이 없어도 빈 문자열을 반환해 graceful degradation.
"""

from pathlib import Path

from .explain import category_prose
from .taxonomy import TAXONOMY

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
