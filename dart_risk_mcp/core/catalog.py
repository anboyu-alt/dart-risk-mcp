"""주가조작 MD 카탈로그 로더

dart-monitor의 knowledge/manipulation_catalog/*.md를 읽어
도구 응답에 관련 선례를 첨부한다.

카탈로그 파일이 없어도 빈 문자열을 반환해 graceful degradation.
"""

from __future__ import annotations

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


def _taxonomy_sort_key(tid: str) -> tuple:
    """taxonomy ID("5.1" 등)를 숫자 오름차순으로 정렬하는 키.

    호출부들이 taxonomy ID 목록을 set 순회(`list({...})`)로 만들어 넘기므로,
    여기서 정렬하지 않으면 발췌 섹션 순서가 PYTHONHASHSEED에 따라 실행마다
    달라진다(2026-08-03 골드 재생성 중 실측). 숫자가 아닌 키(패턴 키 등)는
    어차피 아래 루프에서 스킵되므로 맨 뒤로 보내기만 한다.
    """
    parts = tid.split(".")
    try:
        return (0, [int(p) for p in parts])
    except ValueError:
        return (1, [tid])


# 카탈로그 MD의 유형 헤더: `## {tid}: {한글 제목}`. 다음 헤더 직전까지가 그
# 유형의 블록이다(`### 정의`/`### 탐지 키워드`/`### 위험 신호`/`### 금감원·
# 금융위 적발 사례`/`### 적발 기법 종합`/`### 인용 법조`/`### 기존 현장 기사
# 인용` 하위 섹션 포함).
_ANY_HEADER_RE = re.compile(r"^## \S+: .*$", re.MULTILINE)


def _extract_taxonomy_block(content: str, tid: str) -> str | None:
    """content에서 `## {tid}: ...` 헤더로 시작하는 블록 하나만 뽑아 반환한다.

    블록 범위는 그 헤더 줄부터 다음 `## ` 헤더 직전까지(파일 끝이면 끝까지).
    헤더를 찾지 못하면 None — 호출부가 폴백(파일 앞부분 절단)을 결정한다.
    """
    header_re = re.compile(rf"^## {re.escape(tid)}: .*$", re.MULTILINE)
    match = header_re.search(content)
    if not match:
        return None
    start = match.start()
    next_match = _ANY_HEADER_RE.search(content, match.end())
    end = next_match.start() if next_match else len(content)
    block = content[start:end]
    # 다음 헤더 직전(또는 파일 끝)의 구분선("---")과 그 앞뒤 공백을 정리한다.
    block = re.sub(r"\n+-{3,}\s*\Z", "", block)
    return block.strip()


def load_catalog_excerpt(taxonomy_ids: list[str], max_chars: int = 1500) -> str:
    """taxonomy ID 목록에 해당하는 카탈로그 MD 발췌를 반환한다.

    중복 카테고리는 한 번만 로드. 파일 부재·읽기 오류 시 해당 카테고리 건너뜀.
    섹션 순서는 입력 순서와 무관하게 taxonomy ID 숫자 오름차순(카테고리 1~8 순)
    으로 고정된다 — 입력이 set에서 왔더라도 출력은 결정적이다.

    ⚠ **함정(SE-13 Task 1에서 실사고 발생)**: 인자는 반드시 `TAXONOMY`(taxonomy.py)의
    키인 taxonomy ID 문자열(예: `"5.1"`, `"7.1"`)이어야 한다. `CROSS_SIGNAL_PATTERNS`의
    패턴 키(예: `"zombie_ma"`, `"fake_new_biz"`)를 넘기면 아래 `TAXONOMY.get(tid)`가
    조용히 `None`을 반환해 전부 스킵되고, 예외 없이 **빈 문자열**만 돌아온다 — 호출은
    정상적으로 "성공"한 것처럼 보이기 때문에 이 실수는 로그·예외로 드러나지 않는다.
    패턴 키로 발췌를 뽑고 싶다면 `CROSS_SIGNAL_PATTERNS[key]["signal_sequence"]`
    (taxonomy ID 목록)를 먼저 꺼내 이 함수에 넘길 것. 호출부를 추가/수정할 때는
    "인자가 진짜 taxonomy ID인지" 를 확인하고, 회귀 테스트는 반드시 반환값이
    비어있지 않음을 assert할 것 — 호출 여부만 확인하는 테스트는 이 버그를 잡지 못한다
    (실제로 8번째 죽은 배선 사례가 이렇게 놓쳤다. `server.py`의 `track_fund_usage` 참고).
    """
    # {category: [tid, ...]} — taxonomy ID 숫자 오름차순으로 먼저 정렬한 뒤 묶으므로,
    # 카테고리 등장 순서(dict 삽입 순서)도 같은 오름차순을 그대로 따른다. 패턴 키 등
    # taxonomy ID가 아닌 키는 여기서 조용히 스킵된다(위 docstring 경고 참고).
    ids_by_category: dict[str, list[str]] = {}
    for tid in sorted(taxonomy_ids, key=_taxonomy_sort_key):
        signal = TAXONOMY.get(tid)
        if not signal:
            continue
        category = signal.get("category", "")
        ids_by_category.setdefault(category, []).append(tid)

    excerpts: list[str] = []

    for category, ids in ids_by_category.items():
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

        # 요청받은 id들의 블록만 모은다(같은 카테고리 여러 id면 오름차순으로 이어붙임).
        blocks = [b for tid in ids if (b := _extract_taxonomy_block(content, tid)) is not None]

        if blocks:
            section_body = "\n\n---\n\n".join(blocks)
        else:
            # 폴백: 요청한 id의 헤더를 하나도 못 찾음 — 빈 문자열로 퇴화시키느니
            # 기존 동작(파일 앞부분 절단)으로 최소한의 맥락이라도 남긴다.
            section_body = content.strip()

        # 연속 빈 줄 정리 (메타 블록 제거·블록 이어붙이기 후 공백이 과다하게 남는 것을 방지)
        section_body = re.sub(r"\n{3,}", "\n\n", section_body).strip() + "\n"

        truncated = section_body[:max_chars]
        if len(section_body) > max_chars:
            truncated += "\n…(이하 생략)"

        header = f"━━ 카탈로그 선례: {category} ━━"
        prose = category_prose(category)
        if prose:
            excerpts.append(f"{header}\n이 카테고리가 뭔가요 — {prose}\n\n{truncated}")
        else:
            excerpts.append(f"{header}\n{truncated}")

    return "\n\n".join(excerpts)
